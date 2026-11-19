"""Three-line trial (2026-11-19): per-line research slots, paused topics, line resources in
the owner brief, GPU-hour card floors, GPU jobs in the local queue and queue entries taken
by ledger topics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import test_parallel_program as parallel
import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs import card_precheck, local_compute, utilization
from openlabs.config import load_program_settings
from openlabs.contracts import atomic_write_json
from openlabs.program import (
    activate_topic,
    admit_topic,
    open_topic_ledger,
    paused_topic_campaigns,
    propose_topic,
    slot_status,
)
from openlabs.program_flow import (
    LAST_SCOUT_KEY,
    LINE_SLOTS_FULL_REASON,
    _admission_record_path,
    ledger_queue_entries,
    materialize_waiting_topics,
    schedule_scouts,
    template_supply,
)
from openlabs.projects import load_project
from openlabs.research_lines import line_resources, line_uses_gpu

NOW = parallel.NOW
ASTRO, ENGINEERING = "astro-photometry", "engineering-vvuq"


# --------------------------------------------------------------------------- config


def test_line_limits_parse_and_reject_nonsense() -> None:
    settings = load_program_settings({"enabled": True, "line_max_active_topics": {
        "astro-survey-photometry": 2, "power-market-backtest": 2, "phm-evaluation-audit": 1}})
    assert settings.line_max_active_topics == {
        "astro-survey-photometry": 2, "power-market-backtest": 2, "phm-evaluation-audit": 1}
    assert load_program_settings({}).line_max_active_topics == {}
    for bad in ({"x": -1}, {"x": "2"}, {"x": True}, ["x"]):
        with pytest.raises(ValueError, match="line_max_active_topics"):
            load_program_settings({"line_max_active_topics": bad})


# --------------------------------------------------------------------------- slot counts


def _topic(topic_id: str, status: str, line: str, campaign: str | None = None) -> dict:
    return {"topic_id": topic_id, "status": status, "research_line": line,
            "program_project_id": f"{line}-project", "campaign_id": campaign}


def test_paused_topics_and_line_waiting_admissions_hold_no_slot() -> None:
    settings = load_program_settings({"enabled": True, "max_active_topics": 5,
                                      "line_max_active_topics": {"astro": 2, "power": 2,
                                                                 "phm": 1}})
    ledger = {"topics": [
        _topic("a1", "active", "astro", "c1"), _topic("a2", "active", "astro", "c2"),
        *[_topic(f"p{n}", "active", "astro", f"paused-{n}") for n in range(4)],
        _topic("w", "admitted", "astro"),
        _topic("x", "frozen", "astro", "c9"),
    ]}
    before = slot_status(ledger, settings)
    # Without the paused campaigns the four paused topics fill every slot (the bug).
    assert before.occupied == 6 and before.free_slots == 0
    status = slot_status(ledger, settings, paused_campaigns={f"paused-{n}" for n in range(4)})
    assert status.paused == 4
    # The admitted astro topic waits for its own line (2 in research = its limit): it holds
    # no global slot, so the other lines can still take three.
    assert status.line_waiting == 1 and status.admitted == 0
    assert status.occupied == 2 and status.free_slots == 3
    assert status.line_occupied["astro"] == 3 and status.line_full("astro")
    assert not status.line_can_materialize("astro")
    assert status.line_free_slots("power") == 2 and status.line_can_materialize("phm")
    assert status.line_free_slots("unlisted") is None and not status.line_full("unlisted")
    assert status.full_lines == frozenset({"astro"})
    view = status.to_dict()
    assert view["paused_topics"] == 4 and view["line_waiting_admitted"] == 1
    assert view["lines"]["astro"] == {"limit": 2, "occupied": 3, "researching": 2,
                                      "free_slots": 0}
    # Without line limits nothing changes for the admitted topic.
    plain = slot_status(ledger, load_program_settings({"enabled": True}),
                        paused_campaigns={f"paused-{n}" for n in range(4)})
    assert plain.admitted == 1 and plain.line_waiting == 0


def test_paused_topic_campaigns_reads_the_research_state(tmp_path) -> None:
    paths = flow._paths(tmp_path)
    db = flow._db(paths)
    for name, campaign_status, state in (("held", "production_paused", "paused"),
                                         ("broken", "production_paused", "active"),
                                         ("running", "active", "paused")):
        db.register_campaign(name, domain="physics", title=name, status=campaign_status)
        state_path = tmp_path / f"{name}.json"
        atomic_write_json(state_path, {"status": state})
        with db.connect() as connection:
            connection.execute("UPDATE campaigns SET workstream_state_path=? WHERE campaign_id=?",
                               (str(state_path), name))
    # Only a campaign paused on purpose (state paused) frees its topic's slot; one paused
    # for another reason (invalid binding, protocol hook) keeps it.
    assert paused_topic_campaigns(db) == frozenset({"held"})


# --------------------------------------------------------------------------- scheduling


def _seed(ledger, db, settings, project_id: str, line: str, n: int, status: str,
          campaign: str | None = None) -> str:
    card = {"domain": "physics", "question": f"seed {line} {n}", "data_sources": [f"s:{n}"],
            "primary_endpoint": f"endpoint {n}", "grandfathered": True}
    topic_id = propose_topic(ledger, card, db=db, decided_by="test", metadata={
        "research_line": line, "program_project_id": project_id}).topic_id
    if status in ("admitted", "active"):
        admit_topic(ledger, topic_id, db=db, settings=settings.program, decided_by="test",
                    admission_task_id="test", queue_when_full=True)
    if status == "active":
        db.register_campaign(campaign, domain="physics", title=campaign)
        activate_topic(ledger, topic_id, db=db, campaign_id=campaign, decided_by="test")
    return topic_id


def _full_astro(tmp_path, **program):
    paths, db, settings = lines_tests._line_program(
        tmp_path, (ASTRO, ENGINEERING), max_concurrent_scouts=1, candidate_pool_low_water=4,
        scout_min_interval_hours=0, line_max_active_topics={ASTRO: 2, ENGINEERING: 1},
        max_active_topics=5, **program)
    projects = {load_project(path).research_line: load_project(path).project_id
                for path in paths.project_config_paths() if load_project(path).research_line}
    ledger = open_topic_ledger(paths, settings.program)
    _seed(ledger, db, settings, projects[ASTRO], ASTRO, 1, "active", "astro-c1")
    _seed(ledger, db, settings, projects[ASTRO], ASTRO, 2, "active", "astro-c2")
    waiting = _seed(ledger, db, settings, projects[ASTRO], ASTRO, 3, "admitted")
    return paths, db, settings, projects, ledger, waiting


def test_a_full_line_gets_no_scout_and_the_free_line_asks_only_for_its_slots(tmp_path):
    paths, db, settings, _, _, _ = _full_astro(tmp_path)
    scheduled, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert [item.research_line for item in scheduled] == [ENGINEERING]
    packet = json.loads(Path(parallel._scouts(db)[0]["input_path"]).read_text())
    assert packet["max_cards"] == 1 and packet["line_free_slots"] == 1
    # Once the engineering line's card waits for admission, it has no room left either.
    parallel._finish(db, [item.task_id for item in scheduled])
    db.update_meta({LAST_SCOUT_KEY: "2000-01-01T00:00:00Z"})
    ledger = open_topic_ledger(paths, settings.program)
    project = next(load_project(p).project_id for p in paths.project_config_paths()
                   if load_project(p).research_line == ENGINEERING)
    _seed(ledger, db, settings, project, ENGINEERING, 9, "proposed")
    again, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert again == [] and reason == LINE_SLOTS_FULL_REASON


def test_waiting_cards_of_a_full_line_do_not_hold_the_pool(tmp_path):
    paths, db, settings, projects, ledger, _ = _full_astro(tmp_path)
    for n in range(10, 14):  # four astro cards: the pool's low water, all of a full line
        _seed(ledger, db, settings, projects[ASTRO], ASTRO, n, "proposed")
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert [item.research_line for item in scheduled] == [ENGINEERING], reason


def test_an_admitted_topic_of_a_full_line_waits_and_is_not_dropped(tmp_path):
    paths, db, settings, projects, ledger, waiting = _full_astro(tmp_path)
    atomic_write_json(_admission_record_path(paths, waiting), {
        "topic_id": waiting, "project_path": "/nonexistent/project.json", "card": {}})
    spawned = materialize_waiting_topics(db, paths, settings)
    assert spawned.campaign_ids == ()
    topic = open_topic_ledger(paths, settings.program).topic(waiting)
    assert topic["status"] == "admitted" and not topic.get("campaign_id")


def test_admission_of_a_full_line_waits_for_its_slot(tmp_path, monkeypatch):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    lines_tests._make_line_project(paths)
    lines_tests._lines_file(paths, "ready")
    db = flow._db(paths)
    settings = flow._settings(line_max_active_topics={lines_tests.LINE: 0})
    card = lines_tests._line_card(0)
    first = flow._tick(paths, settings, monkeypatch)
    assert first.program["scouts_scheduled"] == []
    assert first.program["scout_blocked"] == LINE_SLOTS_FULL_REASON
    # With a slot the same line scouts and reviews as before.
    settings = flow._settings(line_max_active_topics={lines_tests.LINE: 1})
    _, admission, _ = flow._to_admission(paths, db, settings, monkeypatch, [card])
    assert len(flow._packet(admission)["topic_cards"]) == 1


# --------------------------------------------------------------------------- card floor


def test_gpu_hour_floor_raises_a_gpu_card_only() -> None:
    line = {"card_compute_floor": {"core_hours": 20, "gpu_hours": 40, "agent_hours": 10}}
    floor = card_precheck.compute_floor(line, {})
    assert floor == {"source": "line card_compute_floor", "core_hours": 20.0,
                     "agent_seconds": 36000, "gpu_hours": 40.0}
    gpu_card = {"cost_estimate": {"agent_seconds": 7200, "gpu_hours": 12, "compute_plan": {
        "locations": ["container_gpu", "container_cpu"], "gpu_memory_mib": 2048}}}
    fixed, notes = card_precheck.apply_compute_floor(gpu_card, floor)
    assert fixed["cost_estimate"]["gpu_hours"] == 40
    assert fixed["cost_estimate"]["agent_seconds"] == 36000
    assert any("gpu_hours raised from 12 to 40" in note for note in notes)
    cpu_card = {"cost_estimate": {"agent_seconds": 72000, "gpu_hours": 0, "compute_plan": {
        "locations": ["container_cpu"]}}}
    fixed, notes = card_precheck.apply_compute_floor(cpu_card, floor)
    assert fixed["cost_estimate"]["gpu_hours"] == 0 and notes == []
    # per_paper_cost: gpu_hours_lower_bound first, else the leading number of gpu_hours.
    template = {"per_paper_cost": {"gpu_hours_lower_bound": 40, "gpu_hours": "60-200 est"}}
    assert card_precheck.compute_floor({}, template)["gpu_hours"] == 40
    template = {"per_paper_cost": {"gpu_hours": "60-200 (estimate)", "agent_hours": "10-30"}}
    assert card_precheck.compute_floor({}, template)["gpu_hours"] == 60
    astro = {"per_paper_cost": {"cpu_core_hours": "60-120", "gpu_hours": 0}}
    assert "gpu_hours" not in card_precheck.compute_floor({}, astro)


# --------------------------------------------------------------------------- line resources


ASTRO_ENTRY = {"id": "astro", "analysis_package": {"path": "/l/astro/toolkit", "entry": "python -m t"},
               "review_checklist": {"path": "sop.md", "section": "8.4"},
               "environment": {"sop": "sop-astro.md", "data_access": "bridge fetch helper",
                               "compute_placement": "ailab first. No GPU is used by this line.",
                               "standard_solver": {"entry": "/l/astro/solver/submit.sh",
                                                   "analysis_library": "/l/astro/lib",
                                                   "control_receipt": "/l/astro/CONTROL.json"}}}
PHM_ENTRY = {"id": "phm", "standard_tools": {"path": "/l/phm/tools/phm_audit"},
             "control": {"receipt": "/l/phm/baselines/CONTROL_RECEIPT.json"},
             "analysis_package": {"path": "/l/phm/tools/phm_audit", "entry": "python -m r"},
             "environment": {"activate": "source /l/phm/activate.sh", "data": "/l/phm/data",
                             "sop": "sop-phm.md",
                             "gpu": {"usage": "one GPU job at a time", "memory_mib": 2048}}}
PMB_ENTRY = {"id": "pmb", "environment": {"tools": "/l/pmb/tools/pmb (API.md)", "gpu": "none",
                                          "control_receipt": "/l/pmb/CONTROL_RECEIPT.json",
                                          "data": "/l/pmb/data"}}


def test_line_resources_come_from_each_lines_own_entry() -> None:
    astro = line_resources(ASTRO_ENTRY)
    assert astro["standard_entry"] == "/l/astro/solver/submit.sh"
    assert astro["control_receipt"] == "/l/astro/CONTROL.json"
    assert astro["data"] == "bridge fetch helper" and "gpu" not in astro
    phm = line_resources(PHM_ENTRY)
    assert "standard_entry" not in phm  # the same tools as the analysis package: named once
    assert phm["analysis_package"] == "/l/phm/tools/phm_audit; python -m r"
    assert phm["control_receipt"] == "/l/phm/baselines/CONTROL_RECEIPT.json"
    assert phm["gpu"] == "one GPU job at a time; declare --gpu-memory-mib 2048"
    pmb = line_resources(PMB_ENTRY)
    assert pmb["standard_entry"].startswith("/l/pmb/tools/pmb") and "gpu" not in pmb
    assert line_uses_gpu(PHM_ENTRY) and not line_uses_gpu(PMB_ENTRY)
    assert not line_uses_gpu(ASTRO_ENTRY)


def _lines_document(paths, entries) -> None:
    import yaml

    path = paths.data / "registry" / "research-lines.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"schema_version": "openlabs.research_lines.v1",
                                    "lines": entries}), encoding="utf-8")


def test_owner_brief_names_the_lines_own_tools_and_gpu_rules(tmp_path, monkeypatch):
    import test_owner_mode as owner_tests
    from openlabs import owner

    paths, db, settings, (topic,) = owner_tests._owner_program(tmp_path, monkeypatch)
    campaign = db.campaign(topic["campaign_id"])
    seat = owner_tests._latest(db, topic["campaign_id"])
    base = owner.spec_block(paths, settings, task=seat, spec=owner_tests._spec(
        tmp_path / "base", seat["task_id"]), campaign=campaign, wall_seconds=600,
        db=db)["request"].split("\n---\n")[0]
    for entry, gpu in ((PHM_ENTRY, True), (PMB_ENTRY, False), (ASTRO_ENTRY, False)):
        _lines_document(paths, [{**entry, "id": "line-x"}])
        monkeypatch.setattr(owner, "campaign_line", lambda _campaign: "line-x")
        spec = owner_tests._spec(tmp_path / entry["id"], seat["task_id"])
        body = owner.spec_block(paths, settings, task=seat, spec=spec, campaign=campaign,
                                wall_seconds=600, db=db)["request"].split("\n---\n")[0]
        assert ("openlabs-local submit --gpu-memory-mib" in body) is gpu
        tools = body.split("## Tools", 1)[1].split("## Hard limits", 1)[0]
        resources = line_resources(entry)
        for key, _label, _limit in owner._LINE_RESOURCE_LABELS:
            if key in resources:
                assert resources[key][:40] in tools, key
        assert "TESS" not in body and "PHOEBE" not in body
        # The line's own pointers (and the GPU rule for a GPU line) add under 0.9 KB.
        assert len(body.encode("utf-8")) - len(base.encode("utf-8")) <= 900


# --------------------------------------------------------------------------- GPU local queue


@pytest.fixture
def local_queue(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("OPENLABS_LOCAL_QUEUE", str(local))
    config = tmp_path / "local-compute.json"
    config.write_text(json.dumps({"max_jobs": 4, "max_cpus": 12, "max_memory_mib": 32768}))
    monkeypatch.setattr(local_compute, "CONFIG_PATH", config)
    return local


def _src(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "run.py").write_text("print(1)\n")
    return root


def test_gpu_jobs_queue_one_at_a_time(local_queue, tmp_path, monkeypatch):
    started: list[list[str]] = []
    monkeypatch.setattr(local_compute.subprocess, "Popen",
                        lambda argv, **kwargs: started.append(argv))
    jobs = [local_compute.submit(_src(tmp_path, f"g{n}"), ["python3", "run.py"], cpu_threads=2,
                                 memory_mib=4096, wall_seconds=3600, queue_root=local_queue,
                                 gpu_memory_mib=2048) for n in range(2)]
    cpu = local_compute.submit(_src(tmp_path, "c"), ["python3", "run.py"], cpu_threads=2,
                               memory_mib=4096, wall_seconds=3600, queue_root=local_queue)
    request = json.loads((local_queue / "jobs" / jobs[0] / "request.json").read_text())
    assert request["resources"]["gpu_memory_mib"] == 2048
    assert request["resources"]["gpu_device"] == 0
    summary = local_compute.dispatch(local_queue)
    assert sorted(summary["started"]) == sorted([jobs[0], cpu])
    load = local_compute.local_load(local_queue)
    assert load["running_gpu"] == 1 and load["queued_gpu"] == 1
    assert load["queued_gpu_cpus"] == 2
    with pytest.raises(local_compute.RemoteComputeError, match="gpu_memory_mib"):
        local_compute.submit(_src(tmp_path, "bad"), ["python3", "run.py"], cpu_threads=1,
                             memory_mib=1024, wall_seconds=60, queue_root=local_queue,
                             gpu_memory_mib=1024)


def _fake_guard(tmp_path: Path, body: str) -> Path:
    code_root = tmp_path / "code"
    (code_root / "bin").mkdir(parents=True)
    guard = code_root / "bin" / "openlabs-resource-guard"
    guard.write_text("#!/bin/bash\n" + body)
    guard.chmod(0o755)
    return code_root


def test_gpu_job_runs_with_its_reservation_and_requeues_when_the_gpu_is_held(
        local_queue, tmp_path, monkeypatch):
    # The guard sees the reservation; CUDA stays visible to a GPU job.
    code_root = _fake_guard(tmp_path, (
        '[ "$1 $2 $3 $4 $5 $6 $7" = "--task-type gpu --gpu-memory-mib 2048 --gpu-device 0 --" ]'
        ' || exit 99\nshift 7\nexec "$@"\n'))
    monkeypatch.setattr(local_compute, "CODE_ROOT", code_root)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    src = tmp_path / "gpu"
    src.mkdir()
    (src / "run.py").write_text(
        "import os, pathlib\n"
        "out = pathlib.Path(os.environ['OPENLABS_OUTPUT_DIR'])\n"
        "(out / 'cuda.txt').write_text(os.environ.get('CUDA_VISIBLE_DEVICES', 'unset'))\n")
    job = local_compute.submit(src, ["python3", "run.py"], cpu_threads=1, memory_mib=512,
                               wall_seconds=60, queue_root=local_queue, gpu_memory_mib=2048)
    assert local_compute.run(job, local_queue) == 0
    directory = local_queue / "jobs" / job
    assert json.loads((directory / "status.json").read_text())["state"] == "succeeded"
    # Not hidden as for CPU jobs: the real guard sets CUDA_VISIBLE_DEVICES to the reserved GPU.
    assert (directory / "result" / "outputs" / "cuda.txt").read_text() != ""
    # A reservation held outside the queue: the guard refuses at once (exit 75) and the job
    # goes back to the queue instead of failing.
    code_root = _fake_guard(tmp_path / "held", (
        'echo "OpenLabs GPU guard: GPU already reserved by another research job; retry after'
        ' it finishes" >&2\nexit 75\n'))
    monkeypatch.setattr(local_compute, "CODE_ROOT", code_root)
    held = local_compute.submit(src, ["python3", "run.py"], cpu_threads=1, memory_mib=512,
                                wall_seconds=60, queue_root=local_queue, gpu_memory_mib=2048)
    assert local_compute.run(held, local_queue) == 0
    status = json.loads((local_queue / "jobs" / held / "status.json").read_text())
    assert status["state"] == "queued" and status["gpu_requeues"] == 1
    assert not (local_queue / "jobs" / held / "result" / "receipt.json").exists()


def test_queued_gpu_jobs_do_not_trip_the_cpu_backlog_gate(tmp_path, monkeypatch):
    remote, local = tmp_path / "remote", tmp_path / "local"
    (remote / "jobs").mkdir(parents=True)
    config = tmp_path / "remote-compute.json"
    config.write_text(json.dumps({"enabled": True, "cpu_threads": 8, "memory_mib": 62961,
                                  "max_concurrent_jobs": 8}))
    monkeypatch.setattr(local_compute, "REMOTE_CONFIG_PATH", config)
    monkeypatch.setattr(local_compute, "CONFIG_PATH", tmp_path / "none.json")
    monkeypatch.setenv("OPENLABS_REMOTE_QUEUE", str(remote))
    monkeypatch.setenv("OPENLABS_LOCAL_QUEUE", str(local))
    monkeypatch.setenv("OPENLABS_LOCAL_MAX_CPUS", "12")
    for n in range(5):
        local_compute.submit(_src(tmp_path, f"g{n}"), ["python3", "run.py"], cpu_threads=2,
                             memory_mib=2048, wall_seconds=600, queue_root=local,
                             gpu_memory_mib=2048)
    settings = flow._settings(compute_backlog_max_queued_jobs=2)
    backlog = utilization.compute_backlog(settings)
    assert backlog["backlogged"] is False and backlog["queued_jobs"] == 0
    assert backlog["local"]["queued_gpu"] == 5


# --------------------------------------------------------------------------- queue entries


def test_queue_entries_taken_by_ledger_topics(tmp_path) -> None:
    def card(path: Path, entry: str) -> str:
        atomic_write_json(path, {"candidate_queue_entry": {"entry_id": entry}})
        return str(path)

    document = {"topics": [
        {"topic_id": "t1", "research_line": "pmb", "status": "active",
         "card_path": card(tmp_path / "a.json", "PMB-01")},
        {"topic_id": "t2", "research_line": "pmb", "status": "rejected",
         "history": [{"to": "rejected", "reason": "card_invalid"}],
         "card_path": card(tmp_path / "b.json", "PMB-02")},
        {"topic_id": "t3", "research_line": "other", "status": "active",
         "card_path": card(tmp_path / "c.json", "PMB-03")},
    ]}
    taken = ledger_queue_entries(document, "pmb")
    assert taken == {"PMB-01": "active"}  # a format rejection may be drawn again
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({"candidates": [
        {"entry_id": "PMB-01", "rank": 1}, {"entry_id": "PMB-02", "rank": 2},
        {"entry_id": "TIC1", "ledger_occupancy": {"state": "blocked"}}]}))
    assert template_supply({"t": str(queue)}, taken)["t"]["drawable"] == 1
    assert template_supply({"t": str(queue)})["t"]["drawable"] == 2
    # One queue file shared by two templates: each counts its own entries.
    shared = tmp_path / "shared.json"
    shared.write_text(json.dumps({"candidates": [
        {"entry_id": "PMB-01", "card_fields": {"paper_template": "rule"}},
        {"entry_id": "PMB-13", "card_fields": {"paper_template": "evolution"}},
        {"entry_id": "PMB-03", "card_fields": {"paper_template": "rule"}}]}))
    supply = template_supply({"rule": str(shared), "evolution": str(shared)}, taken)
    assert supply["rule"]["drawable"] == 1 and supply["evolution"]["drawable"] == 1


# --------------------------------------------------------------------------- repository


def test_new_lines_in_the_repository_direction_file_are_complete() -> None:
    from openlabs.research_lines import load_research_lines

    data = flow.CODE_ROOT.parent / "openlabs-data" / "registry" / "research-lines.yaml"
    if not data.is_file():
        pytest.skip("the data repository is not next to this checkout")
    document = load_research_lines(data)
    for line in ("power-market-backtest", "phm-evaluation-audit"):
        entry = next((item for item in document["lines"] if item["id"] == line), None)
        if entry is None:
            pytest.skip(f"{line} is not merged into this data checkout")
        assert entry["environment"]["status"] == "ready"
        assert entry["review_checklist"]["path"].startswith("registry/research-lines/sop-")
        assert entry["venues"]["tier_policy"]
        for template in entry["paper_templates"]:
            spec = card_precheck.precheck_spec(entry, template["id"])
            assert spec is not None and "{entry_id}" in spec["command"]
            assert Path(template["candidate_queue"]).is_absolute()
        assert card_precheck.compute_floor(entry, entry["paper_templates"][0])
        resources = line_resources(entry)
        assert {"analysis_package", "control_receipt", "data", "sop"} <= set(resources)
    phm = next(item for item in document["lines"] if item["id"] == "phm-evaluation-audit")
    assert line_uses_gpu(phm) and card_precheck.compute_floor(phm, {})["gpu_hours"] == 40
