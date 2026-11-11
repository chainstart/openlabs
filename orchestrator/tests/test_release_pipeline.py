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
    assert any("Release pipeline" in error and "a human must resolve" in error
               for error in report.errors)
    calls = len(_calls(log))
    report = _tick(paths, settings, monkeypatch)
    assert len(_calls(log)) == calls  # no further attempt
    assert report.program["release_exhausted"]  # still shown on every tick
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
    assert _git(paths.data, "status", "--porcelain", "--", f"registry/papers/{PAPER_ID}.json")
    _tick(paths, settings, monkeypatch)
    done = _topic(paths, settings, topic["topic_id"])
    assert done["release"]["status"] == "done"
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
