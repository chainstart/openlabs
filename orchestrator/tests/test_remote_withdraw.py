"""`openlabs-remote withdraw` and `list` (2026-11-19).

Before the per-topic thread limit existed, topic owners had queued about 22 ailab jobs
(96 declared threads against 8 of capacity), most without ``submitter.json``. Owners
now list their topic's jobs (untagged ones attributed by path or by a unique mention in
the topic workspace) and withdraw the queued ones that matter less; a wait on a
withdrawn job ends normally.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openlabs import remote_compute as rc
from openlabs import remote_wait

TOPIC_A = "cc-sg-astro-research-program-candidate-topic-aaaaaaaaaaaaaaaa-1111111111111111"
TOPIC_B = "cc-sg-astro-research-program-candidate-topic-bbbbbbbbbbbbbbbb-2222222222222222"


def _job(root: Path, job_id: str, *, state: str = "queued", cpus: int = 4,
         campaign: str | None = None, ready: bool = True, request: dict | None = None,
         transport: bool = False) -> Path:
    directory = root / "jobs" / job_id
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps({
        "job_id": job_id, "argv": ["bash", "run.sh"], "created_at": "2026-11-18T11:00:00+00:00",
        "resources": {"cpu_threads": cpus, "memory_mib": 5120, "wall_seconds": 3600},
        **(request or {})}))
    (directory / "status.json").write_text(json.dumps({"job_id": job_id, "state": state}))
    if ready:
        (directory / "READY").write_text(job_id)
    if transport:
        (directory / "transport.log").write_text("")
    if campaign is not None:
        (directory / rc.SUBMITTER_FILE).write_text(json.dumps({"campaign_id": campaign}))
    return directory


@pytest.fixture
def env(tmp_path, monkeypatch):
    remote, local, workspaces = tmp_path / "remote", tmp_path / "local", tmp_path / "workspaces"
    for path in (remote / "jobs", local / "jobs", workspaces / "physics" / TOPIC_A,
                 workspaces / "physics" / TOPIC_B):
        path.mkdir(parents=True)
    values = {"OPENLABS_REMOTE_QUEUE": str(remote), "OPENLABS_LOCAL_QUEUE": str(local),
              rc.ATTRIBUTION_ROOTS_ENV: str(workspaces), "OPENLABS_CAMPAIGN_ID": TOPIC_A,
              "OPENLABS_TASK_ID": "owner:1"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return remote, local, workspaces


def _ids(*chars: str) -> list[str]:
    return [char * 32 for char in chars]


def test_withdraw_queued_job_records_who_and_leaves_it_out_of_every_load(env) -> None:
    remote, local, workspaces = env
    job_a, = _ids("a")
    directory = _job(remote, job_a, campaign=TOPIC_A)
    sleeps: list[float] = []
    [outcome] = rc.withdraw([job_a], reason="coarse grid first", sleep=sleeps.append)
    assert outcome["withdrawn"] is True and outcome["backend"] == "ailab"
    assert sleeps == [rc.WITHDRAW_SETTLE_SECONDS]
    assert not (directory / "READY").exists() and (directory / "READY.withdrawn").is_file()
    marker = json.loads((directory / rc.WITHDRAWN_BY_SUBMITTER).read_text())
    assert marker["by"] == {"campaign_id": TOPIC_A, "task_id": "owner:1"}
    assert marker["reason"] == "coarse grid first" and marker["withdrawn_at"]
    assert rc.active_state(directory) is None
    assert rc.campaign_queue_load(TOPIC_A, (remote, local))["jobs"] == 0
    # Withdrawing again is refused, and nothing changes.
    [again] = rc.withdraw([job_a], sleep=sleeps.append)
    assert again["withdrawn"] is False and "already withdrawn" in again["error"]


def test_running_finished_and_in_transfer_jobs_are_refused(env) -> None:
    remote, _local, _ = env
    running, done, transfer, unready = _ids("b", "c", "d", "e")
    _job(remote, running, state="running", campaign=TOPIC_A)
    _job(remote, done, state="succeeded", campaign=TOPIC_A, ready=False)
    _job(remote, transfer, campaign=TOPIC_A, transport=True)
    _job(remote, unready, campaign=TOPIC_A, ready=False)
    outcomes = rc.withdraw([running, done, transfer, unready, "f" * 32, "xyz"],
                           sleep=lambda _s: None)
    assert [item["withdrawn"] for item in outcomes] == [False] * 6
    errors = [item["error"] for item in outcomes]
    assert "state is running" in errors[0] and "not stopped by withdraw" in errors[0]
    assert "state is succeeded" in errors[1]
    assert "transport.log" in errors[2]
    assert "no READY" in errors[3]
    assert "no such job" in errors[4] and "32 lowercase hex" in errors[5]
    assert (remote / "jobs" / running / "READY").is_file()
    assert not list((remote / "jobs" / running).glob("WITHDRAWN*"))


def test_a_job_the_bridge_takes_during_the_settle_is_rolled_back(env) -> None:
    remote, _local, _ = env
    job_a, = _ids("a")
    directory = _job(remote, job_a, campaign=TOPIC_A)

    def bridge_takes_it(_seconds: float) -> None:
        (directory / "status.json").write_text(json.dumps({"job_id": job_a, "state": "running"}))

    [outcome] = rc.withdraw([job_a], sleep=bridge_takes_it)
    assert outcome["withdrawn"] is False and "taken by the dispatcher" in outcome["error"]
    assert (directory / "READY").is_file() and not (directory / "READY.withdrawn").exists()
    assert not list(directory.glob("WITHDRAWN*"))
    assert rc.active_state(directory) == "running"


def test_another_topics_job_needs_any_topic(env) -> None:
    remote, _local, workspaces = env
    tagged, mentioned = _ids("a", "b")
    _job(remote, tagged, campaign=TOPIC_B)
    _job(remote, mentioned)
    (workspaces / "physics" / TOPIC_B / "OWNER_LOG.md").write_text(f"submitted {mentioned}\n")
    outcomes = rc.withdraw([tagged, mentioned], sleep=lambda _s: None)
    assert [item["withdrawn"] for item in outcomes] == [False, False]
    assert "another topic" in outcomes[0]["error"] and "by submitter" in outcomes[0]["error"]
    assert "by workspace_mention" in outcomes[1]["error"]
    outcomes = rc.withdraw([tagged], any_topic=True, sleep=lambda _s: None)
    assert outcomes[0]["withdrawn"] is True


def test_local_queue_jobs_are_withdrawn_and_dispatch_skips_them(env, monkeypatch) -> None:
    from openlabs import local_compute

    remote, local, _ = env
    queued, running = _ids("a", "b")
    _job(local, queued, campaign=TOPIC_A, request={"backend": "local"})
    _job(local, running, state="running", campaign=TOPIC_A, request={"backend": "local"})
    outcomes = rc.withdraw([queued, running], sleep=lambda _s: None)
    assert outcomes[0]["withdrawn"] is True and outcomes[0]["backend"] == "local"
    assert outcomes[1]["withdrawn"] is False and "state is running" in outcomes[1]["error"]
    assert queued not in {path.name for path, _r, _s in local_compute._jobs(local)}


def test_list_attributes_untagged_jobs_by_path_and_by_unique_mention(env) -> None:
    remote, local, workspaces = env
    tagged, by_source, by_token, by_note, shared, unknown, withdrawn = _ids(
        "1", "2", "3", "4", "5", "6", "7")
    _job(remote, tagged, campaign=TOPIC_A)
    _job(local, by_source, state="running", request={
        "backend": "local",
        "source": f"/ws/attempt-workspaces/x/y/workspaces/physics/{TOPIC_B}/stage"})
    _job(local, by_token, request={
        "backend": "local", "source": f"/ws/attempt-workspaces/{rc.attempt_token(TOPIC_A)}/a/s"})
    _job(remote, by_note, cpus=8)
    _job(remote, shared)
    _job(remote, unknown)
    _job(remote, withdrawn)
    (remote / "jobs" / withdrawn / "WITHDRAWN.by-submitter").write_text("old marker\n")
    notes = workspaces / "physics" / TOPIC_A / "notes"
    notes.mkdir()
    (notes / "submit.txt").write_text(f"job_id: {by_note}\njob_id: {shared}\n")
    (workspaces / "physics" / TOPIC_B / "OWNER_HANDOVER.md").write_text(f"waits on {shared}")
    listing = rc.queue_jobs(rc.default_roots())
    rows = {row["job_id"]: row for row in listing["jobs"]}
    assert listing["attribution_complete"] is True
    assert withdrawn not in rows
    assert (rows[tagged]["campaign_id"], rows[tagged]["attribution"]) == (TOPIC_A, "submitter")
    assert (rows[by_source]["campaign_id"], rows[by_source]["attribution"]) == (
        TOPIC_B, "source_path")
    assert rows[by_token]["campaign_id"] == TOPIC_A
    assert (rows[by_note]["campaign_id"], rows[by_note]["attribution"]) == (
        TOPIC_A, "workspace_mention")
    assert rows[shared]["campaign_id"] is None and rows[shared]["attribution"] == "ambiguous"
    assert rows[shared]["candidates"] == sorted([TOPIC_A, TOPIC_B])
    assert rows[unknown]["attribution"] == "unknown"
    load = rc.campaign_queue_load(TOPIC_A, (remote, local), infer=True)
    assert (load["jobs"], load["cpu_threads"], load["inferred"]) == (3, 16, 2)
    # Without inference only submitter.json counts (the old rule).
    assert rc.campaign_queue_load(TOPIC_A, (remote, local))["jobs"] == 1


def test_submit_limit_counts_inferred_jobs(env) -> None:
    remote, local, workspaces = env
    job_a, = _ids("a")
    _job(remote, job_a, cpus=8)
    (workspaces / "physics" / TOPIC_A / "OWNER_LOG.md").write_text(f"queued {job_a}\n")
    environ = {"OPENLABS_CAMPAIGN_ID": TOPIC_A, "OPENLABS_CAMPAIGN_COMPUTE_THREADS": "8",
               rc.ATTRIBUTION_ROOTS_ENV: str(workspaces)}
    problem = rc.campaign_limit_problem(4, environ, (remote, local))
    assert problem is not None and "list --mine" in problem and "withdraw" in problem


def test_cli_list_mine_and_withdraw(env, capsys) -> None:
    remote, _local, workspaces = env
    mine, other = _ids("a", "b")
    _job(remote, mine, campaign=TOPIC_A)
    _job(remote, other, campaign=TOPIC_B)
    assert rc.main(["list", "--mine"]) == rc.EXIT_OK
    out = capsys.readouterr().out
    assert mine in out and other not in out and "topic-aaaaaaaa" in out
    assert rc.main(["list", "--json"]) == rc.EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert {row["job_id"] for row in data["jobs"]} == {mine, other}
    # Refused before anything is renamed, so no settle wait.
    assert rc.main(["withdraw", other]) == rc.EXIT_NOT_WITHDRAWN
    assert "another topic" in capsys.readouterr().err
    assert (remote / "jobs" / other / "READY").is_file()


def test_cli_list_mine_needs_a_topic(env, monkeypatch, capsys) -> None:
    monkeypatch.delenv("OPENLABS_CAMPAIGN_ID")
    assert rc.main(["list", "--mine"]) == rc.EXIT_INVALID
    assert "OPENLABS_CAMPAIGN_ID" in capsys.readouterr().err


def test_wait_view_of_a_withdrawn_job_is_a_normal_end(env) -> None:
    remote, local, _ = env
    job_a, job_b = _ids("a", "b")
    _job(remote, job_a, campaign=TOPIC_A)
    _job(remote, job_b, campaign=TOPIC_A)
    rc.withdraw([job_a], reason="superseded by the coarse grid", sleep=lambda _s: None)
    view = remote_wait.job_state(remote, job_a, local_root=local)
    assert view["state"] == "withdrawn" and remote_wait.is_terminal(view)
    assert "by owner:1" in view["withdrawn"] and "superseded" in view["withdrawn"]
    # A legacy free-text marker is still a withdrawal.
    (remote / "jobs" / job_b / "WITHDRAWN.by-submitter").write_text("withdrawn by hand\n")
    assert remote_wait.job_state(remote, job_b, local_root=local)["state"] == "withdrawn"
    # A job the bridge ran despite a marker reports its real state.
    (remote / "jobs" / job_b / "status.json").write_text(
        json.dumps({"job_id": job_b, "state": "running"}))
    assert remote_wait.job_state(remote, job_b, local_root=local)["state"] == "running"


def test_parked_wait_on_a_withdrawn_job_releases_normally(env, tmp_path) -> None:
    from test_remote_wait import _db, _paths, _run, _yield_payload

    remote, local, _ = env
    job_a, job_b = _ids("a", "b")
    _job(remote, job_a, campaign=TOPIC_A)
    _job(remote, job_b, state="running", campaign=TOPIC_A)
    paths = _paths(tmp_path / "factory")
    db = _db(paths)
    report = _run(db, paths, "research-1", _yield_payload(job_a, job_b))
    parked_id = report.enqueued[0]
    assert db.task(parked_id)["status"] == "awaiting_remote"
    rc.withdraw([job_a], reason="lower priority", any_topic=True, sleep=lambda _s: None)
    assert remote_wait.release_ready_waits(db)["released"] == []      # job_b still runs
    (remote / "jobs" / job_b / "status.json").write_text(
        json.dumps({"job_id": job_b, "state": "succeeded"}))
    summary = remote_wait.release_ready_waits(db)
    assert summary["released"] == [parked_id] and not summary.get("needs_human")
    task = db.task(parked_id)
    assert task["status"] == "queued"
    assert f"{job_a} (ailab): withdrawn (WITHDRAWN.by-submitter; by owner:1" in task["objective"]
    assert "reason: lower priority; not run - resubmit it if it is still needed" in task[
        "objective"]
