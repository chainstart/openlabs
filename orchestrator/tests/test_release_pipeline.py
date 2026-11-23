"""Release pipeline: review ready -> formal fixes -> Zenodo -> delta review -> commit -> delivery.

The paper-writing CLI is replaced by ``fake_paper_writing.py`` (no network, no
model); the data repository is a real temporary Git repository.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from openlabs import program_autonomy
from openlabs.config import load_program_settings
from openlabs.program import IllegalTopicTransition, TRANSITIONS
from test_program_autonomy import _events, _finish, _lease, _program, _ready, _tick, _topic

PAPER_ID = "20261111-ai-health-temporal-retrieval"
FAKE = Path(__file__).with_name("fake_paper_writing.py")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


def _install_paper(paths, *, issues=(), support="planned", authorization=True, **extra) -> Path:
    root = paths.data
    (root / "papers" / PAPER_ID).mkdir(parents=True, exist_ok=True)
    manuscript = root / "papers" / PAPER_ID / "main.tex"
    manuscript.write_text("\\title{T}\nBody.\n", encoding="utf-8")
    import hashlib

    paper = {"version": "1.0.0", "authorization": authorization,
             "review": {"ready": True,
                        "snapshot": hashlib.sha256(manuscript.read_bytes()).hexdigest(),
                        "support_sha": None},
             "support": {"status": support}, "issues": list(issues), **extra}
    registry = root / "registry" / "papers" / f"{PAPER_ID}.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps(paper, indent=2, sort_keys=True), encoding="utf-8")
    return registry


def _repo(paths) -> None:
    root = paths.data
    _git(root, "init", "-q")
    (root / "unrelated.txt").write_text("base\n")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=Base", "-c", "user.email=base@example.invalid", "commit", "-qm",
         "base")
    # Somebody else's work in progress: one modified, one staged, one untracked file.
    (root / "unrelated.txt").write_text("someone else's edit\n")
    (root / "staged.txt").write_text("staged by someone else\n")
    _git(root, "add", "staged.txt")
    (root / "scratch.txt").write_text("untracked\n")


def _setup(tmp_path, monkeypatch, *, issues=(), support="planned", authorization=True,
           identity=True, paper_extra=None, **program):
    settings_kw = {"auto_handoff": True, "auto_release": True,
                   "paper_writing_command": (sys.executable, str(FAKE)), **program}
    if identity:
        settings_kw.update(git_user_name="OpenLabs Release", git_user_email="release@example.invalid")
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch, **settings_kw)
    _install_paper(paths, issues=issues, support=support, authorization=authorization,
                   **(paper_extra or {}))
    _repo(paths)
    if not identity:
        _git(paths.data, "config", "user.name", "")
        _git(paths.data, "config", "user.email", "")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-gitconfig"))
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    log = tmp_path / "paper-calls.jsonl"
    monkeypatch.setenv("FAKE_PAPER_LOG", str(log))
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", "https://manage.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", "test-key")
    monkeypatch.setenv("ZENODO_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv("OPENLABS_ENABLE_EXTERNAL_WRITES", raising=False)
    return paths, db, settings, topic, log


def _calls(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _commands(log: Path) -> list[str]:
    return [call["command"] for call in _calls(log)]


def _paper(paths) -> dict:
    return json.loads((paths.data / "registry" / "papers" / f"{PAPER_ID}.json").read_text())


def _write_paper(paths, paper: dict) -> None:
    (paths.data / "registry" / "papers" / f"{PAPER_ID}.json").write_text(
        json.dumps(paper, indent=2, sort_keys=True))


def _commit_files(root: Path, sha: str) -> set[str]:
    return set(_git(root, "show", "--name-only", "--format=", sha).split())


WRITER_ISSUE = {"code": "STYLE-UNRESOLVED-MARKER", "location": "main.tex:2", "remedy": "writer",
                "message": "TODO marker", "text": "STYLE-UNRESOLVED-MARKER: main.tex:2: TODO marker"}
PREPARE_ISSUE = {"code": "SUPPORT-RECEIPT-DOI", "location": "", "remedy": "zenodo_prepare",
                 "message": "receipt DOI", "text": "SUPPORT-RECEIPT-DOI: receipt DOI"}


def _finish_writer(paths, settings, monkeypatch, db, task_id: str, *, fix: bool = True) -> None:
    """Fake writer: edits the manuscript (text only) and resolves the listed issues."""

    _lease(paths, settings, monkeypatch, db, task_id)
    if fix:
        manuscript = paths.data / "papers" / PAPER_ID / "main.tex"
        manuscript.write_text(manuscript.read_text().replace("Body.", "Body, revised wording."))
        paper = _paper(paths)
        paper["issues"] = [i for i in paper["issues"] if i["remedy"] != "writer"]
        _write_paper(paths, paper)
    _finish(db, paths, task_id, supported=False)


# --------------------------------------------------------------------------- configuration


def test_release_configuration_defaults_are_off_and_git_table_is_parsed() -> None:
    program = load_program_settings({})
    assert program.auto_release is False and program.release_max_attempts == 3
    assert program.git_user_name is None and program.git_message == "{action}: {paper_id} v{version}"
    custom = load_program_settings({"auto_release": True, "git": {
        "user_name": "Bot", "user_email": "bot@example.invalid", "message": "{paper_id} {action}"}})
    assert custom.auto_release and custom.git_user_email == "bot@example.invalid"
    with pytest.raises(ValueError, match="message may only use"):
        load_program_settings({"git": {"message": "{unknown}"}})
    assert "in_review" in TRANSITIONS["ready_queue"]


# --------------------------------------------------------------------------- end to end


def test_end_to_end_ready_to_delivery_with_fixes_release_delta_review_and_commits(
    tmp_path, monkeypatch
):
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, issues=[PREPARE_ISSUE],
        paper_extra={"after_prepare_issues": [WRITER_ISSUE]})
    head_before = _git(paths.data, "rev-parse", "HEAD").strip()

    report = _ready(paths, db, settings, monkeypatch, topic)
    # Deterministic fix first (zenodo prepare), then a writer for the text problems.
    assert _commands(log)[:3] == ["program release-status", "zenodo prepare",
                                  "program release-status"]
    prepare = next(c for c in _calls(log) if c["command"] == "zenodo prepare")
    assert prepare["external_writes"] is True and "--confirm-production" in prepare["argv"]
    assert not any(c["external_writes"] for c in _calls(log) if c["command"].startswith("program"))
    release = _topic(paths, settings, topic["topic_id"])["release"]
    assert release["stage"] == "form_fix_writer" and release["writer_rounds"] == 1
    writer = db.task(release["writer_task_id"])
    assert writer["task_type"] == "format_fix" and writer["agent_role"] == "writer"
    assert writer["campaign_id"] == "ai-program-release"
    packet = json.loads(Path(writer["input_path"]).read_text())
    assert [i["code"] for i in packet["issues"]] == ["STYLE-UNRESOLVED-MARKER"]
    assert any(e["outcome"] == "writer_scheduled" for e in report.program["releases"])

    # A tick while the writer works changes nothing.
    calls_before = len(_calls(log))
    _tick(paths, settings, monkeypatch)
    assert len(_calls(log)) == calls_before

    _finish_writer(paths, settings, monkeypatch, db, writer["task_id"])
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors

    commands = _commands(log)[calls_before:]
    assert commands == ["program release-status", "review unified-run", "program release-status",
                        "support-check", "zenodo release", "program release-status",
                        "program deliver"]
    final = _topic(paths, settings, topic["topic_id"])
    assert final["status"] == "ready_queue" and final["awaiting_owner_review"] is True
    assert final["handoff"]["status"] == "delivered" and final["handoff"]["submission_handler"] is None
    assert final["release"]["status"] == "done"
    actions = [c["action"] for c in final["release"]["commits"]]
    # The prepare step found the tree clean; then: the writer's fix and the delta
    # review record before the Zenodo release, the published DOI before delivery,
    # and the delivery block afterwards.
    assert actions == ["commit-before-zenodo-release", "release-ready", "record-delivery"]

    # Every pipeline commit holds this paper's paths (and the ledger) only.
    commits = _git(paths.data, "rev-list", f"{head_before}..HEAD").split()
    assert len(commits) == len(actions)
    allowed = (f"registry/papers/{PAPER_ID}.json", f"papers/{PAPER_ID}/",
               f"reviews/unified/{PAPER_ID}/", "registry/topic-ledger.json")
    for sha in commits:
        assert all(name.startswith(allowed) for name in _commit_files(paths.data, sha)), sha
        assert _git(paths.data, "log", "-1", "--format=%an <%ae>", sha).strip() == (
            "OpenLabs Release <release@example.invalid>")
        message = _git(paths.data, "log", "-1", "--format=%B", sha)
        assert PAPER_ID in message and "v1.0.0" in message and "not pushed" in message
    # The paper's paths are clean after the second commit, so `handoff sync` would pass.
    assert _git(paths.data, "status", "--porcelain", "--", f"registry/papers/{PAPER_ID}.json",
                f"papers/{PAPER_ID}") == ""
    # Somebody else's changes are untouched: still modified, still staged, still untracked.
    status = _git(paths.data, "status", "--porcelain").splitlines()
    assert " M unrelated.txt" in status and "A  staged.txt" in status and "?? scratch.txt" in status
    assert {"release_support_prepared", "release_writer_scheduled", "release_delta_review",
            "release_support_published", "release_committed", "handoff_delivered",
            "release_done"} <= set(_events(db, topic["topic_id"]))

    # Delivered once; later ticks do nothing.
    calls_before = len(_calls(log))
    _tick(paths, settings, monkeypatch)
    assert len(_calls(log)) == calls_before


# --------------------------------------------------------------------------- stages


def test_auto_release_off_stops_before_the_first_zenodo_write(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, auto_release=False)
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert "zenodo prepare" not in _commands(log)
    release = _topic(paths, settings, topic["topic_id"])["release"]
    assert release["status"] == "waiting" and release["waiting_for"] == "auto_release_off"
    assert release["stage"] == "support_prepare"
    assert report.program["releases"][-1]["outcome"] == "waiting_auto_release_off"
    # Waiting again does not grow the history.
    history = len(_topic(paths, settings, topic["topic_id"])["history"])
    _tick(paths, settings, monkeypatch)
    assert len(_topic(paths, settings, topic["topic_id"])["history"]) == history
    assert release.get("attempts") == {}


def test_missing_standing_authorization_also_waits(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, authorization=False)
    _ready(paths, db, settings, monkeypatch, topic)
    assert "zenodo prepare" not in _commands(log)
    assert _topic(paths, settings, topic["topic_id"])["release"]["waiting_for"] == (
        "no_standing_authorization")


@pytest.mark.parametrize("retarget", [True, False])
def test_full_review_at_cap_dispatches_direction_and_bounds_invalid_choices(tmp_path, monkeypatch, retarget):
    from test_program_autonomy import _decide, _direction_task, _retarget_decision

    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, support="not_required", issues=[WRITER_ISSUE])
    _ready(paths, db, settings, monkeypatch, topic)
    writer = _topic(paths, settings, topic["topic_id"])["release"]["writer_task_id"]
    _finish_writer(paths, settings, monkeypatch, db, writer)
    from paper_writing.review_flow import runs_dir, scientific_rounds
    for number in range(1, 5):
        path = runs_dir(paths.data, PAPER_ID) / str(number) / "decision.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"target_journal": "Old journal", "stage_reached": "decision",
                                    "round_for_target": number, "merged": {"outcome": "ready"}}))
    cap = {"paper_id": PAPER_ID, "target_journal": "Old journal", "direction_context": {},
           "rounds_for_target": 4, "max_rounds_per_target": 4,
           "decision_record": str(path.relative_to(paths.data)),
           "decision_record_sha256": program_autonomy.sha256_file(path)}
    monkeypatch.setattr(program_autonomy, "run_delta_review", lambda *args: {
        "outcome": "review_rounds_exhausted", "review_outcome": cap,
        "full_review_reasons": ["primary result changed"]})
    registry = paths.data / "registry" / "verified-venues.yaml"
    registry.write_text(json.dumps({"schema_version": "openlabs.verified_venues.v1", "venues": [
        {"journal": name, "status": "verified", "cas_2025": {"zone": zone, "source": "fixture"},
         "indexes": {"list": ["SCIE"]}} for name, zone in [
             ("Old journal", 1), ("New journal", 1), ("Unknown fees", 2)]]}))
    from paper_writing.venue_registry import alternatives
    original = program_autonomy._run_paper_command
    def command(paths, settings, args, **kwargs):
        if args[:2] == ["venue", "alternatives"]:
            return alternatives(paths.data, exclude=args[3])
        return original(paths, settings, args, **kwargs)
    monkeypatch.setattr(program_autonomy, "_run_paper_command", command)
    report = _tick(paths, settings, monkeypatch)
    assert not report.errors
    decision = _direction_task(db)
    packet = json.loads(Path(decision["input_path"]).read_text())
    assert packet["trigger"]["detail"]["decision_record"] == str(path.relative_to(paths.data))
    assert packet["options"] == ["retarget_or_short_format", "freeze"]
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"
    assert [item["journal"] for item in packet["verified_alternatives"]] == ["New journal"]
    if retarget:
        chosen = _decide(paths, settings, monkeypatch, db,
                         _retarget_decision("primary result changed", "New journal"))
        successor = db.task(chosen.program["direction_decisions"][-1]["executed_task_id"])
        assert "New journal" in successor["objective"]
        assert scientific_rounds(paths.data, PAPER_ID, "New journal") == []
        assert len(scientific_rounds(paths.data, PAPER_ID, "Old journal")) == 4
        assert db.campaign(topic["campaign_id"])["status"] == "active"
        return
    for _ in range(program_autonomy.MAX_DECISION_ATTEMPTS):
        _decide(paths, settings, monkeypatch, db,
                _retarget_decision("primary result changed", "Unverified venue"))
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"


def test_delta_review_needing_a_full_review_returns_the_topic_to_review(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, support="not_required", issues=[WRITER_ISSUE],
        paper_extra={"delta_eligible": False})
    _ready(paths, db, settings, monkeypatch, topic)
    writer = _topic(paths, settings, topic["topic_id"])["release"]["writer_task_id"]
    _finish_writer(paths, settings, monkeypatch, db, writer)
    report = _tick(paths, settings, monkeypatch)
    returned = _topic(paths, settings, topic["topic_id"])
    assert returned["status"] == "in_review"
    assert returned["release"]["status"] == "returned_to_review"
    assert [h.get("to") for h in returned["history"] if "to" in h][-2:] == ["ready_queue",
                                                                          "in_review"]
    review = db.latest_task(topic["campaign_id"])
    assert review["task_type"] == "paper_review" and review["agent_role"] == "reviewer"
    assert review["routing_reason"] == "release_full_review"
    assert db.campaign(topic["campaign_id"])["status"] == "active"
    assert "program deliver" not in _commands(log)
    assert any(e["outcome"] == "returned_to_review" for e in report.program["releases"])
    # The full review passes: the topic is ready-queued again with a fresh release state.
    from test_program_autonomy import _outcome

    _lease(paths, settings, monkeypatch, db, review["task_id"])
    _finish(db, paths, review["task_id"], extra={
        "paper_candidate": True, "review_outcome": _outcome(status="ready")})
    paper = _paper(paths)
    paper["delta_eligible"] = True
    _write_paper(paths, paper)
    _tick(paths, settings, monkeypatch)
    again = _topic(paths, settings, topic["topic_id"])
    assert again["status"] == "ready_queue" and again["handoff"]["status"] == "delivered"


@pytest.mark.parametrize("outcome", ["preflight_failed", "formal_check_blocked"])
def test_delta_review_blocked_by_a_check_is_retried_not_sent_back_to_review(
        tmp_path, monkeypatch, outcome):
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, support="not_required", issues=[WRITER_ISSUE],
        release_max_attempts=2, paper_extra={"delta_outcome": outcome})
    _ready(paths, db, settings, monkeypatch, topic)
    writer = _topic(paths, settings, topic["topic_id"])["release"]["writer_task_id"]
    _finish_writer(paths, settings, monkeypatch, db, writer)
    _tick(paths, settings, monkeypatch)
    state = _topic(paths, settings, topic["topic_id"])
    assert state["status"] == "ready_queue"
    assert state["release"]["status"] == "failed" and state["release"]["stage"] == "delta_review"
    assert state["release"]["attempts"] == {"delta_review": 1}
    assert f"outcome='{outcome}'" in state["release"]["last_error"]
    assert "run_dir='reviews/unified/blocked'" in state["release"]["last_error"]
    # No full review was queued.
    assert db.latest_task(topic["campaign_id"]).get("routing_reason") != "release_full_review"
    report = _tick(paths, settings, monkeypatch)
    state = _topic(paths, settings, topic["topic_id"])
    assert state["status"] == "ready_queue" and state["release"]["status"] == "exhausted"
    assert report.errors == []
    assert report.program["delivery_chain"][0]["state"] == "waiting"
    assert state["handoff"]["status"] != "returned_to_review"
    assert _commands(log).count("review unified-run") == 2
    assert "program deliver" not in _commands(log)


def test_git_commit_without_identity_fails_with_a_hint(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support="not_required",
                                             identity=False)
    (paths.data / "papers" / PAPER_ID / "main.tex").write_text("\\title{T}\nBody.\n%x\n")
    paper = _paper(paths)
    paper["review"]["snapshot"] = __import__("hashlib").sha256(
        (paths.data / "papers" / PAPER_ID / "main.tex").read_bytes()).hexdigest()
    _write_paper(paths, paper)
    report = _ready(paths, db, settings, monkeypatch, topic)
    release = _topic(paths, settings, topic["topic_id"])["release"]
    assert release["waiting_for"] == "git_identity_missing" and release["stage"] == "commit"
    entry = report.program["releases"][-1]
    assert entry["outcome"] == "waiting_git_identity_missing" and "[program.git]" in entry["hint"]
    assert "program deliver" not in _commands(log)


def test_commit_only_takes_the_papers_paths(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch)
    root = paths.data
    (root / "papers" / PAPER_ID / "new-figure.txt").write_text("fig\n")
    (root / "papers" / "other-paper").mkdir(parents=True)
    (root / "papers" / "other-paper" / "x.tex").write_text("other\n")
    sha = program_autonomy.commit_paper_paths(
        paths, settings, paper_id=PAPER_ID, version="1.0.0", action="test",
        topic_id=topic["topic_id"],
        commit_paths=[f"registry/papers/{PAPER_ID}.json", f"papers/{PAPER_ID}",
                      f"reviews/unified/{PAPER_ID}"])
    files = _commit_files(root, sha)
    assert f"papers/{PAPER_ID}/new-figure.txt" in files
    assert not any(name.startswith(("papers/other-paper", "unrelated", "staged", "scratch"))
                   for name in files)
    assert _git(root, "status", "--porcelain", "--", "staged.txt").startswith("A ")
    # Nothing left to commit: no empty commit.
    assert program_autonomy.commit_paper_paths(
        paths, settings, paper_id=PAPER_ID, version="1.0.0", action="test",
        topic_id=topic["topic_id"], commit_paths=[f"papers/{PAPER_ID}"]) is None
    with pytest.raises(program_autonomy.ReleaseError, match="outside the data repository"):
        program_autonomy.commit_paper_paths(
            paths, settings, paper_id=PAPER_ID, version="1", action="x", topic_id="t",
            commit_paths=["../elsewhere"])


def test_commit_skips_paper_paths_git_cannot_match(tmp_path, monkeypatch):
    """An empty (or only-ignored) review directory must not break `git commit --only`."""

    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch)
    root = paths.data
    (root / "reviews" / "unified" / PAPER_ID).mkdir(parents=True)  # exists, nothing for git
    (root / ".gitignore").write_text("*.aux\n")
    (root / "papers" / PAPER_ID / "main.aux").write_text("ignored\n")
    _write_paper(paths, {**_paper(paths), "delivery": {"package_id": "pkg-1"}})
    sha = program_autonomy.commit_paper_paths(
        paths, settings, paper_id=PAPER_ID, version="1.0.0", action="test",
        topic_id=topic["topic_id"],
        commit_paths=[f"registry/papers/{PAPER_ID}.json", f"papers/{PAPER_ID}",
                      f"reviews/unified/{PAPER_ID}"])
    files = _commit_files(root, sha)
    assert f"registry/papers/{PAPER_ID}.json" in files
    assert f"papers/{PAPER_ID}/main.aux" not in files
    # Only ignored files under a path: nothing to commit, and no pathspec error.
    assert program_autonomy.commit_paper_paths(
        paths, settings, paper_id=PAPER_ID, version="1.0.0", action="test",
        topic_id=topic["topic_id"], commit_paths=[f"reviews/unified/{PAPER_ID}"]) is None


def test_failed_stage_is_retried_then_exhausted_and_reported(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, release_max_attempts=2,
        paper_extra={"fail": {"zenodo prepare": 5}})
    report = _ready(paths, db, settings, monkeypatch, topic)
    first = _topic(paths, settings, topic["topic_id"])["release"]
    assert first["status"] == "failed" and first["attempts"] == {"support_prepare": 1}
    assert "simulated" in first["last_error"]
    report = _tick(paths, settings, monkeypatch)
    state = _topic(paths, settings, topic["topic_id"])["release"]
    assert state["status"] == "exhausted" and state["attempts"]["support_prepare"] == 2
    assert report.program["release_exhausted"][0]["stage"] == "support_prepare"
    assert not report.errors
    assert report.program["delivery_chain"][0]["state"] == "waiting"
    calls = len(_calls(log))
    report = _tick(paths, settings, monkeypatch)
    assert len(_calls(log)) == calls  # no further attempt
    assert not report.program["delivery_chain"][0].get("repair")
    assert "release_exhausted" in _events(db, topic["topic_id"])


def test_writer_rounds_are_bounded(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support="not_required",
                                             issues=[WRITER_ISSUE], release_max_attempts=1)
    _ready(paths, db, settings, monkeypatch, topic)
    writer = _topic(paths, settings, topic["topic_id"])["release"]["writer_task_id"]
    _finish_writer(paths, settings, monkeypatch, db, writer, fix=False)
    report = _tick(paths, settings, monkeypatch)
    state = _topic(paths, settings, topic["topic_id"])["release"]
    assert state["status"] == "exhausted" and "writer round" in state["last_error"]
    assert report.program["release_exhausted"]
    assert "program deliver" not in _commands(log)


def test_resume_after_a_crash_between_delivery_and_its_commit(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support="not_required")
    original = program_autonomy.commit_paper_paths
    from openlabs import paper_figures

    harvested = []
    monkeypatch.setattr(paper_figures, "harvest", lambda *args: harvested.append(args[2]) or [])
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        if kwargs.get("action") == "record-delivery" and calls["n"] == 0:
            calls["n"] += 1
            raise program_autonomy.ReleaseError("disk full")
        return original(*args, **kwargs)

    monkeypatch.setattr(program_autonomy, "commit_paper_paths", flaky)
    _ready(paths, db, settings, monkeypatch, topic)
    pending = _topic(paths, settings, topic["topic_id"])
    assert pending["handoff"]["status"] == "delivered"
    assert pending["release"]["status"] == "commit_pending"
    assert harvested == []
    assert _git(paths.data, "status", "--porcelain", "--", f"registry/papers/{PAPER_ID}.json")
    _tick(paths, settings, monkeypatch)
    done = _topic(paths, settings, topic["topic_id"])
    assert done["release"]["status"] == "done"
    assert harvested == [PAPER_ID]
    assert _commands(log).count("program deliver") == 1  # never delivered twice
    assert _git(paths.data, "status", "--porcelain", "--", f"registry/papers/{PAPER_ID}.json") == ""


def test_writer_result_is_owned_by_the_pipeline() -> None:
    from openlabs.config import FactorySettings, ProgramSettings

    settings = FactorySettings(program=ProgramSettings(enabled=True))
    task = {"task_type": "format_fix", "routing_reason": program_autonomy.RELEASE_FIX_ROUTING,
            "campaign_id": "ai-program-release"}
    assert program_autonomy.on_result(None, None, settings, None, task=task, payload={},
                                      result_path=Path("x"), result_sha256="0") == "handled"


def test_ready_queue_only_returns_to_review(tmp_path, monkeypatch) -> None:
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, auto_handoff=False)
    _ready(paths, db, settings, monkeypatch, topic)
    from openlabs.program import open_topic_ledger, transition_topic

    with pytest.raises(IllegalTopicTransition):
        transition_topic(open_topic_ledger(paths, settings.program), topic["topic_id"], "active",
                         db=db, reason="x", decided_by="test")
    assert _commands(log) == []  # auto_handoff off: the pipeline never runs


# --------------------------------------------------------------------------- no public deposit


def test_support_release_setting_defaults_to_zenodo_and_rejects_unknown_values() -> None:
    program = load_program_settings({})
    assert program.support_release == "zenodo" and "No Zenodo record" in program.support_none_reason
    custom = load_program_settings({"support_release": "none", "support_none_reason": "Owner: none."})
    assert custom.support_release == "none" and custom.support_none_reason == "Owner: none."
    with pytest.raises(ValueError, match="support_release must be one of"):
        load_program_settings({"support_release": "github"})
    with pytest.raises(ValueError, match="support_none_reason"):
        load_program_settings({"support_none_reason": " "})


def _no_zenodo(calls: list[dict]) -> None:
    assert not any(c["command"].startswith("zenodo") or c["command"] == "support-check"
                   for c in calls)
    assert [c["command"] for c in calls if c["external_writes"]] in ([], ["program deliver"])


def test_support_release_none_waives_the_deposit_and_delivers_without_zenodo(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("ZENODO_ACCESS_TOKEN", raising=False)
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, issues=[PREPARE_ISSUE], auto_release=False,
        support_release="none", support_none_reason="Owner 2026-11-20: no Zenodo records.")
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.errors == [], report.errors
    assert _commands(log) == ["program release-status", "program waive-support",
                              "program release-status", "program deliver"]
    _no_zenodo(_calls(log))
    waiver = next(c for c in _calls(log) if c["command"] == "program waive-support")
    assert "Owner 2026-11-20: no Zenodo records." in waiver["argv"]
    support = _paper(paths)["support"]
    assert support["status"] == "not_required"
    assert support["not_required_recorded_by"] == "orchestrator:support_release=none"
    final = _topic(paths, settings, topic["topic_id"])
    assert final["handoff"]["status"] == "delivered" and final["release"]["status"] == "done"
    assert [c["action"] for c in final["release"]["commits"]] == ["release-ready",
                                                                  "record-delivery"]
    assert {"release_support_waived", "handoff_delivered"} <= set(_events(db, topic["topic_id"]))


def test_support_release_none_waits_for_the_owner_when_a_record_exists(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support="draft",
                                             support_release="none")
    _ready(paths, db, settings, monkeypatch, topic)
    _no_zenodo(_calls(log))
    release = _topic(paths, settings, topic["topic_id"])["release"]
    assert release["status"] == "waiting" and release["waiting_for"] == "support_record_exists"
    assert release["stage"] == "support_waiver" and release.get("attempts") == {}
    assert "program deliver" not in _commands(log)


def test_support_release_none_waits_when_the_manuscript_cites_a_deposit(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support_release="none",
                                             paper_extra={"cites_deposit": True})
    _ready(paths, db, settings, monkeypatch, topic)
    _no_zenodo(_calls(log))
    release = _topic(paths, settings, topic["topic_id"])["release"]
    assert release["waiting_for"] == "manuscript_cites_deposit"
    assert "program deliver" not in _commands(log)


@pytest.mark.parametrize("line_workspace", [False, True])
def test_workspace_paper_is_adopted_into_the_data_repository_then_delivered(
    tmp_path, monkeypatch, line_workspace,
):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, auto_release=False,
                                             support_release="none")
    if line_workspace:
        campaign = db.campaign(topic["campaign_id"])
        root = paths.data / "workspaces" / "lines" / "line-id" / topic["campaign_id"]
        db.register_campaign(topic["campaign_id"], domain=campaign["domain"],
                             title=campaign["title"], state_path=str(root))
    # Owner mode: the paper exists only in the topic's campaign workspace.
    workspace = program_autonomy.asset_library.topic_workspace(db, paths, topic)
    for relative in (f"registry/papers/{PAPER_ID}.json", f"papers/{PAPER_ID}"):
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        (paths.data / relative).rename(target)
    _git(paths.data, "add", "-A", "--", f"registry/papers/{PAPER_ID}.json", f"papers/{PAPER_ID}")
    _git(paths.data, "-c", "user.name=Base", "-c", "user.email=base@example.invalid", "commit",
         "-qm", "paper lives in the workspace")

    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.errors == [], report.errors
    commands = _commands(log)
    assert commands[:2] == ["program adopt", "program release-status"]
    adopt = _calls(log)[0]
    assert adopt["argv"][adopt["argv"].index("--source") + 1] == str(workspace)
    # The ready review's bundle first, then the campaign's other archived results, once each.
    manifests = [adopt["argv"][i + 1] for i, a in enumerate(adopt["argv"])
                 if a == "--artifact-manifest"]
    review = db.result_bundle_path(str(_topic(paths, settings, topic["topic_id"])["handoff"]
                                       ["review_task_id"]))
    assert manifests and manifests[0] == review and len(manifests) == len(set(manifests))
    assert set(db.campaign_result_bundle_paths(topic["campaign_id"])) <= set(manifests)
    assert "program deliver" in commands
    _no_zenodo(_calls(log))
    assert (paths.data / "registry" / "papers" / f"{PAPER_ID}.json").is_file()
    final = _topic(paths, settings, topic["topic_id"])
    assert final["release"]["status"] == "done"
    assert "release_paper_adopted" in _events(db, topic["topic_id"])
    # The adopted paper is committed with the release.
    assert _git(paths.data, "status", "--porcelain", "--", f"registry/papers/{PAPER_ID}.json",
                f"papers/{PAPER_ID}") == ""


def test_missing_paper_waits_instead_of_failing(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support_release="none")
    (paths.data / "registry" / "papers" / f"{PAPER_ID}.json").unlink()
    _ready(paths, db, settings, monkeypatch, topic)
    release = _topic(paths, settings, topic["topic_id"])["release"]
    assert release["waiting_for"] == "paper_not_found" and release.get("attempts") == {}
    assert _commands(log) == []


# --------------------------------------------------------------------------- ignored ledger, retry


def _ignore_ledger(paths, settings) -> str:
    """The instance ledger as runtime state the data repository ignores and never tracked."""

    ledger = settings.program.ledger_path
    root = paths.data
    if _git(root, "ls-files", "--", ledger).strip():
        _git(root, "update-index", "--force-remove", "--", ledger)
        _git(root, "-c", "user.name=Base", "-c", "user.email=base@example.invalid", "commit",
             "-qm", "untrack the runtime ledger")
    with (root / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write(f"/{ledger}\n")
    return ledger


def test_an_ignored_untracked_ledger_is_left_out_of_the_commit(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support_release="none")
    ledger = _ignore_ledger(paths, settings)
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.errors == [], report.errors
    final = _topic(paths, settings, topic["topic_id"])
    assert final["release"]["status"] == "done" and final["handoff"]["status"] == "delivered"
    assert final["release"]["commits"]
    for commit in final["release"]["commits"]:
        files = _commit_files(paths.data, commit["sha"])
        assert ledger not in files and f"registry/papers/{PAPER_ID}.json" in files
    # Still ignored and untracked; never forced in.
    assert _git(paths.data, "ls-files", "--", ledger).strip() == ""
    assert _git(paths.data, "check-ignore", "--", ledger).strip() == ledger


def test_only_an_ignored_ledger_left_means_no_commit(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch)
    ledger = _ignore_ledger(paths, settings)
    assert (paths.data / ledger).is_file()  # the ledger changed, the paper is clean at HEAD
    assert program_autonomy.commit_paper_paths(
        paths, settings, paper_id=PAPER_ID, version="1.0.0", action="test",
        topic_id=topic["topic_id"],
        commit_paths=[f"registry/papers/{PAPER_ID}.json", f"papers/{PAPER_ID}"]) is None


def test_release_retry_lets_an_exhausted_stage_try_again(tmp_path, monkeypatch):
    monkeypatch.setattr(program_autonomy, "_repair_delivery", lambda *_: None)
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, release_max_attempts=2,
        paper_extra={"fail": {"zenodo prepare": 2}})
    _ready(paths, db, settings, monkeypatch, topic)
    _tick(paths, settings, monkeypatch)
    state = _topic(paths, settings, topic["topic_id"])["release"]
    assert state["status"] == "exhausted"
    with pytest.raises(program_autonomy.DeliveryError, match="needs its reason"):
        program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID, by="op",
                                       reason=" ")
    result = program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID,
                                            by="operator", reason="Zenodo outage over")
    assert result["release_reset"] is True and result["stage"] == "support_prepare"
    reset = _topic(paths, settings, topic["topic_id"])
    assert reset["release"]["status"] == "pending"
    assert "support_prepare" not in reset["release"]["attempts"]
    retry = reset["release"]["retries"][-1]
    assert retry["by"] == "manual:operator" and retry["reason"] == "Zenodo outage over"
    assert retry["previous_attempts"] == {"support_prepare": 2}
    assert "simulated" in retry["previous_error"]
    assert "release_retry" in _events(db, topic["topic_id"])
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    final = _topic(paths, settings, topic["topic_id"])
    assert final["release"]["status"] == "done" and final["handoff"]["status"] == "delivered"
    # Nothing stopped any more: a second retry is refused.
    with pytest.raises(program_autonomy.DeliveryError, match="nothing stopped"):
        program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID, by="op",
                                       reason="again")


def test_release_retry_resets_an_exhausted_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(program_autonomy, "_repair_delivery", lambda *_: None)
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, handoff_max_attempts=1, support="not_required",
        paper_extra={"fail": {"program deliver": 1}})
    _ready(paths, db, settings, monkeypatch, topic)
    assert _topic(paths, settings, topic["topic_id"])["handoff"]["status"] == "exhausted"
    result = program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID,
                                            by="operator", reason="site back up")
    assert result["handoff_reset"] is True
    assert _topic(paths, settings, topic["topic_id"])["handoff"]["attempts"] == 0
    _tick(paths, settings, monkeypatch)
    assert _topic(paths, settings, topic["topic_id"])["handoff"]["status"] == "delivered"


def test_release_retry_requeues_delivery_of_a_newer_paper_version(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support="not_required")
    _ready(paths, db, settings, monkeypatch, topic)
    delivered = _topic(paths, settings, topic["topic_id"])
    assert delivered["handoff"]["status"] == "delivered"
    assert delivered["handoff"]["package_id"] == "pkg-1"
    # The current version is delivered: nothing to retry.
    with pytest.raises(program_autonomy.DeliveryError, match="already delivered"):
        program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID, by="op",
                                       reason="new version")
    # The paper moves on to a new version; the ledger still says "delivered".
    paper = _paper(paths)
    paper["version"] = "1.1.0"
    _write_paper(paths, paper)
    calls = len(_calls(log))
    _tick(paths, settings, monkeypatch)
    assert len(_calls(log)) == calls  # a delivered topic is never looked at by the tick
    seq = int(delivered["release"].get("seq") or 0)
    result = program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID,
                                            by="operator", reason="v1.1.0 is ready")
    assert result["kind"] == "new_version" and result["handoff_reset"] is True
    assert result["previous_delivered_version"] == "1.0.0" and result["version"] == "1.1.0"
    reset = _topic(paths, settings, topic["topic_id"])
    assert reset["status"] == "ready_queue"
    assert reset["handoff"]["status"] == "queued" and reset["handoff"]["attempts"] == 0
    assert reset["handoff"]["previous_package_id"] == "pkg-1"
    assert reset["handoff"]["previous_delivered_version"] == "1.0.0"
    assert reset["release"]["status"] == "pending" and reset["release"]["stage"] == "check"
    assert reset["release"]["seq"] == seq + 1
    retry = reset["release"]["retries"][-1]
    assert retry["by"] == "manual:operator" and retry["reason"] == "v1.1.0 is ready"
    assert retry["kind"] == "new_version"
    note = [h for h in reset["history"] if h.get("kind") == "release_retry"][-1]
    assert note["detail"]["kind"] == "new_version" and note["reason"] == "new_paper_version"
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    final = _topic(paths, settings, topic["topic_id"])
    assert final["handoff"]["status"] == "delivered" and final["release"]["status"] == "done"
    assert final["handoff"]["package_id"] == "pkg-1.1.0"
    assert _paper(paths)["delivery"]["version"] == "1.1.0"
    assert _commands(log).count("program deliver") == 2
    with pytest.raises(program_autonomy.DeliveryError, match="already delivered"):
        program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID, by="op",
                                       reason="again")


def _returned_to_review(tmp_path, monkeypatch):
    """A writer's fix falls outside the delta rule: the pipeline queues a full review."""
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, support="not_required", issues=[WRITER_ISSUE],
        paper_extra={"delta_eligible": False})
    _ready(paths, db, settings, monkeypatch, topic)
    writer = _topic(paths, settings, topic["topic_id"])["release"]["writer_task_id"]
    _finish_writer(paths, settings, monkeypatch, db, writer)
    # No worker free in this tick: the full review stays queued.
    from openlabs.db import FactoryDB

    with monkeypatch.context() as patch:
        patch.setattr(FactoryDB, "claim_next_task", lambda self, **kwargs: None)
        _tick(paths, settings, monkeypatch)
    returned = _topic(paths, settings, topic["topic_id"])
    assert returned["status"] == "in_review"
    event = next(entry for entry in reversed(returned["history"])
                 if entry.get("kind") == "release_returned_to_review")
    review = db.task(event["detail"]["review_task_id"])
    assert review["task_id"].startswith("release-review:") and review["status"] == "queued"
    return paths, db, settings, topic, log, review


def _bind_review_to_current_manuscript(paths) -> None:
    """The registered ready review already covers the current manuscript (e.g. owner-directed)."""
    import hashlib

    paper = _paper(paths)
    paper["review"]["snapshot"] = hashlib.sha256(
        (paths.data / "papers" / PAPER_ID / "main.tex").read_bytes()).hexdigest()
    _write_paper(paths, paper)


def test_release_retry_recovers_historical_full_review_at_cap(tmp_path, monkeypatch):
    paths, db, settings, topic, log, review = _returned_to_review(tmp_path, monkeypatch)
    path = paths.data / "prior.json"
    path.write_text('{"merged":{"outcome":"ready"}}')
    cap = {"paper_id": PAPER_ID, "target_journal": "Old journal", "direction_context": {},
           "decision_record": path.name, "decision_record_sha256": program_autonomy.sha256_file(path)}
    monkeypatch.setattr(program_autonomy, "run_release_status", lambda *args: {
        "review": {"ready": True, "current": False, "exhausted_review": cap}})
    monkeypatch.setattr(program_autonomy, "run_delta_review", lambda *args: {
        "outcome": "review_rounds_exhausted", "review_outcome": cap})
    first = program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID, by="op",
                                           reason="historical stalled review")
    second = program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID, by="op",
                                            reason="retry")
    assert first["direction_task_id"] == second["direction_task_id"]
    assert db.task(review["task_id"])["status"] == "cancelled"


def test_release_retry_returns_a_ready_current_paper_from_review(tmp_path, monkeypatch):
    paths, db, settings, topic, log, review = _returned_to_review(tmp_path, monkeypatch)
    # The ready decision is not bound to the rewritten manuscript: refused.
    with pytest.raises(program_autonomy.DeliveryError, match="not ready and current"):
        program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID, by="op",
                                       reason="review is current")
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"
    assert db.task(review["task_id"])["status"] == "queued"

    _bind_review_to_current_manuscript(paths)
    result = program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID,
                                            by="operator", reason="review is current")
    assert result["kind"] == "returned_review_ready"
    assert review["task_id"] in result["cancelled_tasks"]
    assert result["release_review_cancelled"] == [review["task_id"]]
    assert result["release_review_tasks"] == {review["task_id"]: "cancelled"}
    assert db.task(review["task_id"])["status"] == "cancelled"
    assert db.campaign(topic["campaign_id"])["status"] == "production_paused"
    back = _topic(paths, settings, topic["topic_id"])
    assert back["status"] == "ready_queue"
    assert [h.get("to") for h in back["history"] if "to" in h][-1] == "ready_queue"
    assert back["handoff"]["status"] == "queued" and back["handoff"]["paper_id"] == PAPER_ID
    assert back["release"]["status"] == "pending" and back["release"]["stage"] == "check"
    retry = back["release"]["retries"][-1]
    assert retry["kind"] == "returned_review_ready" and retry["by"] == "manual:operator"
    note = [h for h in back["history"] if h.get("kind") == "release_retry"][-1]
    assert note["detail"]["cancelled_tasks"] == result["cancelled_tasks"]
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    final = _topic(paths, settings, topic["topic_id"])
    assert final["handoff"]["status"] == "delivered" and final["release"]["status"] == "done"
    assert db.task(review["task_id"])["status"] == "cancelled"  # the full review never ran


def test_release_retry_refuses_while_the_full_review_runs(tmp_path, monkeypatch):
    paths, db, settings, topic, log, review = _returned_to_review(tmp_path, monkeypatch)
    _bind_review_to_current_manuscript(paths)
    _lease(paths, settings, monkeypatch, db, review["task_id"])
    with pytest.raises(program_autonomy.DeliveryError, match="already running"):
        program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID, by="op",
                                       reason="review is current")
    assert _topic(paths, settings, topic["topic_id"])["status"] == "in_review"


def test_release_retry_refuses_an_in_review_topic_not_returned_by_the_pipeline(
        tmp_path, monkeypatch):
    paths, db, settings, topic, log, review = _returned_to_review(tmp_path, monkeypatch)
    _bind_review_to_current_manuscript(paths)
    program_autonomy.record_topic_note(
        program_autonomy._ledger(paths, settings), topic["topic_id"], db=db,
        event_type="test_note", reason="test", decided_by="test",
        updates={"release": {"status": "pending"}})
    with pytest.raises(program_autonomy.DeliveryError, match="not 'returned_to_review'"):
        program_autonomy.retry_release(db, paths, settings, paper_id=PAPER_ID, by="op",
                                       reason="review is current")


# --------------------------------------------------------------------------- layout, artifacts


def test_ignored_release_products_are_bound_and_committed_before_delivery(tmp_path, monkeypatch):
    pdf = f"papers/{PAPER_ID}/manuscript/main.pdf"
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support="not_required",
                                             paper_extra={"unbound_artifacts": [pdf]})
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.errors == [], report.errors
    assert _commands(log) == ["program release-status", "program bind-release-artifacts",
                              "program release-status", "program deliver"]
    final = _topic(paths, settings, topic["topic_id"])
    assert final["handoff"]["status"] == "delivered" and final["handoff"]["attempts"] == 1
    ready = next(c["sha"] for c in final["release"]["commits"] if c["action"] == "release-ready")
    assert f"papers/{PAPER_ID}/production/release-artifacts.json" in _commit_files(paths.data, ready)
    assert "release_artifacts_bound" in _events(db, topic["topic_id"])


def test_ignored_release_products_are_bound_before_the_zenodo_release(tmp_path, monkeypatch):
    """`zenodo release` refuses unbound ignored files, so binding comes first."""
    pdf = f"papers/{PAPER_ID}/manuscript/main.pdf"
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch,
                                             paper_extra={"unbound_artifacts": [pdf]})
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.errors == [], report.errors
    assert _commands(log) == ["program release-status", "zenodo prepare",
                              "program release-status", "review unified-run",
                              "program release-status", "program bind-release-artifacts",
                              "program release-status", "support-check", "zenodo release",
                              "program release-status", "program deliver"]
    final = _topic(paths, settings, topic["topic_id"])
    assert final["handoff"]["status"] == "delivered" and final["release"]["status"] == "done"
    assert final["release"].get("attempts") == {}
    # The manifest is frozen by the commit that precedes the Zenodo release.
    before = next(c["sha"] for c in final["release"]["commits"]
                  if c["action"] == "commit-before-zenodo-release")
    assert f"papers/{PAPER_ID}/production/release-artifacts.json" in _commit_files(paths.data,
                                                                                  before)


def test_an_over_limit_evidence_file_is_bound_before_the_first_commit(tmp_path, monkeypatch):
    """PMB-13B, 2026-11-20: an 8 MB formal-check evidence body made every commit fail."""
    body = f"reviews/unified/{PAPER_ID}/run/formal-check/evidence/S71c226eba714f63bcbed.body"
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support="not_required",
                                             paper_extra={"oversize_payloads": [body]})
    target = paths.data / body
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    (target.parent / "S71c226eba714f63bcbed.text").write_text("text\n")
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.errors == [], report.errors
    assert _commands(log) == ["program release-status", "program bind-oversize-payloads",
                              "program release-status", "program deliver"]
    final = _topic(paths, settings, topic["topic_id"])
    assert final["handoff"]["status"] == "delivered"
    ready = next(c["sha"] for c in final["release"]["commits"] if c["action"] == "release-ready")
    files = _commit_files(paths.data, ready)
    assert body not in files
    assert f"papers/{PAPER_ID}/production/payload-artifacts.json" in files
    assert str(target.parent.relative_to(paths.data) / ".gitignore") in files
    assert "release_payloads_bound" in _events(db, topic["topic_id"])
    assert target.stat().st_size == 5 * 1024 * 1024 + 1  # the reviewed bytes stay in place


def test_workspace_support_sources_are_relocated_before_zenodo_prepare(tmp_path, monkeypatch):
    """PMB-13B, 2026-11-20: zenodo prepare refused decisive/... (a workspace path)."""
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, paper_extra={"unadopted_sources": ["decisive/solve.py"]})
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.errors == [], report.errors
    commands = _commands(log)
    assert commands[:3] == ["program release-status", "program relocate-support-sources",
                            "program release-status"]
    assert commands.index("program relocate-support-sources") < commands.index("zenodo prepare")
    assert "release_support_sources_relocated" in _events(db, topic["topic_id"])
    assert _topic(paths, settings, topic["topic_id"])["handoff"]["status"] == "delivered"


def test_unsupported_workspace_layout_waits_for_the_owner(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support_release="none")
    workspace = program_autonomy.asset_library.topic_workspace(db, paths, topic)
    for relative in (f"registry/papers/{PAPER_ID}.json", f"papers/{PAPER_ID}"):
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        (paths.data / relative).rename(target)
    (workspace / "LAYOUT-UNSUPPORTED").write_text("x")
    _ready(paths, db, settings, monkeypatch, topic)
    release = _topic(paths, settings, topic["topic_id"])["release"]
    assert release["status"] == "waiting" and release["waiting_for"] == "layout_unsupported"
    assert release["stage"] == "adopt" and release.get("attempts") == {}
    assert _commands(log) == ["program adopt"]
    assert not (paths.data / "registry" / "papers" / f"{PAPER_ID}.json").exists()


def test_paper_command_error_keeps_the_json_error_behind_a_stderr_banner(tmp_path, monkeypatch):
    from openlabs.config import FactorySettings, ProgramSettings

    class Done:
        returncode, stdout = 1, '{"status": "failed", "error": "Release files are not committed"}'
        stderr = "OpenLabs resource guard: task-type=cpu\n"

    monkeypatch.setattr(program_autonomy.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(program_autonomy.DeliveryError, match="Release files are not committed"):
        program_autonomy._run_paper_command(
            type("P", (), {"data": tmp_path})(), FactorySettings(program=ProgramSettings()),
            ["program", "deliver"])


# --------------------------------------------------------------------------- credentials file


def _credentials_file(tmp_path: Path, mode: int = 0o600) -> Path:
    path = tmp_path / "secrets" / "pipeline.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# test credentials\nexport ARA_PAPER_MANAGE_API_URL='https://file.invalid'\n"
                    "ARA_PAPER_MANAGE_API_KEY=\"file-key\"\nZENODO_ACCESS_TOKEN=file-token\n"
                    "UNRELATED_SECRET=not-read\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _drop_credentials(monkeypatch) -> None:
    for name in ("ARA_PAPER_MANAGE_API_URL", "ARA_PAPER_MANAGE_API_KEY", "ZENODO_ACCESS_TOKEN",
                 "UNRELATED_SECRET"):
        monkeypatch.delenv(name, raising=False)


def test_credentials_file_reaches_only_the_delivery_and_zenodo_children(tmp_path, monkeypatch):
    import os

    secrets = _credentials_file(tmp_path)
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch,
                                             credentials_file=str(secrets))
    _drop_credentials(monkeypatch)
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.errors == [], report.errors
    final = _topic(paths, settings, topic["topic_id"])
    assert final["handoff"]["status"] == "delivered" and final["release"]["status"] == "done"
    calls = {c["command"]: c for c in _calls(log)}
    assert calls["program deliver"]["credentials"] == ["ARA_PAPER_MANAGE_API_KEY",
                                                       "ARA_PAPER_MANAGE_API_URL"]
    assert calls["program deliver"]["api_url"] == "https://file.invalid"
    assert calls["zenodo release"]["credentials"] == ["ZENODO_ACCESS_TOKEN"]
    # Every other child (and the tick itself) never sees them.
    for command, call in calls.items():
        if command not in {"program deliver", "zenodo prepare", "zenodo release"}:
            assert call["credentials"] == [], command
    for name in ("ARA_PAPER_MANAGE_API_URL", "ARA_PAPER_MANAGE_API_KEY", "ZENODO_ACCESS_TOKEN",
                 "UNRELATED_SECRET"):
        assert name not in os.environ


def test_environment_wins_over_the_credentials_file(tmp_path, monkeypatch):
    secrets = _credentials_file(tmp_path)
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch,
                                             credentials_file=str(secrets))
    _ready(paths, db, settings, monkeypatch, topic)
    deliver = next(c for c in _calls(log) if c["command"] == "program deliver")
    assert deliver["api_url"] == "https://manage.invalid"


@pytest.mark.parametrize("mode", [0o640, 0o604])
def test_a_credentials_file_open_to_others_is_refused(tmp_path, monkeypatch, mode):
    secrets = _credentials_file(tmp_path, mode)
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, issues=[],
                                             support="published",
                                             credentials_file=str(secrets))
    _drop_credentials(monkeypatch)
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert "program deliver" not in _commands(log)
    waiting = [h for h in report.program.get("handoffs", [])
               if h.get("outcome") == "waiting_credentials"]
    assert waiting and waiting[0]["credentials_file"] == "credentials_file_mode_not_0600"
    assert "file-key" not in json.dumps(report.program)


def test_missing_credentials_file_waits_without_error(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, support="published",
        credentials_file=str(tmp_path / "absent.env"))
    _drop_credentials(monkeypatch)
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert "program deliver" not in _commands(log)
    waiting = [h for h in report.program.get("handoffs", [])
               if h.get("outcome") == "waiting_credentials"]
    assert waiting and waiting[0]["credentials_file"] == "credentials_file_missing"


def test_credentials_file_setting_must_be_absolute() -> None:
    assert load_program_settings({}).credentials_file is None
    assert load_program_settings({"credentials_file": "/x/y.env"}).credentials_file == "/x/y.env"
    with pytest.raises(ValueError, match="credentials_file must be an absolute path"):
        load_program_settings({"credentials_file": "relative.env"})


def test_import_writer_artifact_rechecks_base_and_is_idempotent(tmp_path):
    import hashlib
    from types import SimpleNamespace
    data = tmp_path / "data"
    manuscript = data / "papers" / PAPER_ID / "manuscript/main.tex"
    manuscript.parent.mkdir(parents=True)
    manuscript.write_text("base")
    packet = tmp_path / "packet.json"
    sources = program_autonomy._writer_sources(data, PAPER_ID)
    packet.write_text(json.dumps({"paper_id": PAPER_ID, "source_sha256": sources}))
    bundle = tmp_path / "bundle/result.json"
    artifact = bundle.parent / "artifacts/0.tex"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fixed")
    relative = manuscript.relative_to(data).as_posix()
    artifact_id = "edit-" + hashlib.sha256(relative.encode()).hexdigest()[:16]
    bundle.write_text(json.dumps({"artifacts": [{"artifact_id": artifact_id,
                         "uri": artifact.as_uri(), "sha256": hashlib.sha256(b"fixed").hexdigest()}]}))
    db = SimpleNamespace(task=lambda _: {"input_path": str(packet)}, result_bundle_path=lambda _: str(bundle))
    paths = SimpleNamespace(data=data)
    assert program_autonomy._apply_writer_files(db, paths, "task") == 1
    assert program_autonomy._apply_writer_files(db, paths, "task") == 0
    manuscript.write_text("concurrent edit")
    with pytest.raises(program_autonomy.ReleaseError, match="base changed"):
        program_autonomy._apply_writer_files(db, paths, "task")
    assert manuscript.read_text() == "concurrent edit"


def test_exhausted_support_stage_waits_for_control_plane_retry(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, release_max_attempts=1, paper_extra={"fail": {"zenodo prepare": 9}})
    report = _ready(paths, db, settings, monkeypatch, topic)
    item = report.program["delivery_chain"][0]
    assert item["state"] == "waiting" and item["stage"] == "support_prepare"
    assert "release-retry" in item["condition"]
    assert not item.get("repair")


def test_prepared_package_binding_mismatch_runs_automatic_delta_review(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(
        tmp_path, monkeypatch, support="draft",
        issues=[{"code": "REVIEW-SNAPSHOT-MISMATCH", "remedy": "delta_review"}],
    )
    paper = _paper(paths)
    paper["support"]["package_sha"] = "prepared-package"
    _write_paper(paths, paper)

    _ready(paths, db, settings, monkeypatch, topic)

    commands = _commands(log)
    assert "zenodo prepare" not in commands
    assert commands.index("review unified-run") < commands.index("zenodo release")


def test_changed_published_support_stops_at_a_retryable_checkpoint(tmp_path, monkeypatch):
    paths, db, settings, topic, log = _setup(tmp_path, monkeypatch, support="published")
    real_status = program_autonomy.run_release_status

    def stale_status(*args):
        status = real_status(*args)
        status["support"]["published_package_stale"] = "Support source changed"
        return status

    monkeypatch.setattr(program_autonomy, "run_release_status", stale_status)
    _ready(paths, db, settings, monkeypatch, topic)

    state = _topic(paths, settings, topic["topic_id"])["release"]
    assert state["status"] == "failed" and state["stage"] == "support_prepare"
    assert state["attempts"] == {"support_prepare": 1}
    assert "Cannot reuse the published support version" in state["last_error"]
    assert set(_commands(log)) == {"program release-status"}


@pytest.mark.parametrize("mode", ["resynthesize", "presentation"])
def test_registered_ready_decision_queues_only_after_binding_validation(tmp_path, monkeypatch, mode):
    from openlabs.program import mark_topic_in_review, open_topic_ledger

    paths, db, settings, topic, _ = _setup(tmp_path, monkeypatch, auto_release=False)
    topic_id = topic["topic_id"]
    ledger = open_topic_ledger(paths, settings.program)
    mark_topic_in_review(ledger, topic_id, db=db, decided_by="review")
    draft = paths.data / "draft" / "publication" / "registry" / "papers" / f"{PAPER_ID}.yaml"
    draft.parent.mkdir(parents=True)
    draft.write_text("paper_id: " + PAPER_ID)
    read_campaign = db.campaign
    monkeypatch.setattr(db, "campaign", lambda key: {**read_campaign(key),
                                                      "state_path": str(paths.data / "draft")})
    monkeypatch.setattr(db, "has_active_tasks", lambda _: False)
    record = _paper(paths)
    record["writing_release"] = {"status": "ready", "review_mode": mode}
    _write_paper(paths, record)
    review = {"ready": True, "decision_current": False, "review_mode": mode,
              "decision_sha256": "b" * 64}
    monkeypatch.setattr(program_autonomy, "run_release_status", lambda *args: {
        "review": review, "version": "1.0.0", "target_journal": "Journal",
    })
    from openlabs.engine import TickReport

    report = TickReport()
    with pytest.raises(program_autonomy.DeliveryError, match="current ready"):
        program_autonomy.queue_registered_ready(db, paths, settings, report, topic_id)
    assert ledger.topic(topic_id)["status"] == "in_review"
    review["decision_current"] = True
    program_autonomy._queue_resynthesized(db, paths, settings, report)
    result = ledger.topic(topic_id)
    assert result["status"] == "ready_queue"
    assert result["handoff"]["status"] == "queued"
    assert result["paper_id"] == PAPER_ID
    assert not program_autonomy.queue_registered_ready(db, paths, settings, report, topic_id)["changed"]
