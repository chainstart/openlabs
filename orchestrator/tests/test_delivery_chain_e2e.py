"""Delivery chain end to end: review ready -> papers/ -> commit -> Zenodo -> management site.

The two papers that reached delivery on 2026-11-20 (NEM settlement, topic-d9479445; TIC
260161938, topic-7504c471) both needed a person somewhere between review ``ready`` and the
delivery. This test walks one paper through the whole chain against a fake Zenodo service
and a fake management site (local HTTP servers; nothing leaves the loopback interface),
and replays each stop of that day on the way:

* the data repository has no Git identity          -> waits for it, by name, then goes on;
* the instance ledger is ignored by .gitignore      -> committed around, never forced in;
* ``auto_release`` is off                           -> waits for the setting, then goes on;
* the management-site credentials are missing      -> waits for them, then delivers;
* the delivery command fails behind the resource guard's stderr banner
                                                    -> the command's own error is recorded
                                                       and retried, not "the guard";
* a delta review that fails its preflight          -> retried, never a full review;
* a stage exhausted until a code fix lands          -> retried by itself on the new code;
* a missing manuscript source (format_fix had no main.tex)
                                                    -> needs a human, no writer is started.

The paper side is ``fake_paper_writing.py`` run through a wrapper that prints the resource
guard's banners first, exactly as ``~/.local/bin/paper-writing`` does.
"""

from __future__ import annotations

import json
import socket
import stat
import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from openlabs import program_autonomy
from test_program_autonomy import _program, _ready, _tick, _topic
from test_release_pipeline import (
    FAKE,
    PAPER_ID,
    PREPARE_ISSUE,
    _calls,
    _commands,
    _git,
    _install_paper,
    _paper,
    _write_paper,
)

LEDGER = "registry/topic-ledger.json"
GUARD_BANNER = ("OpenLabs container guard: verified CPU/memory/swap/pids limits and shared GPU "
                "locks\nOpenLabs resource guard: task-type=cpu; GPU admission/monitoring not "
                "required")


# --------------------------------------------------------------------------- fake services


class _Service:
    """A recording HTTP service on 127.0.0.1 (fake Zenodo or fake management site)."""

    def __init__(self, name: str, token: str):
        self.name, self.token, self.requests = name, token, []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _reply(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                authorized = self.headers.get("Authorization") == f"Bearer {service.token}"
                service.requests.append({"method": self.command, "path": self.path,
                                         "authorized": authorized, "bytes": len(body)})
                if not authorized:
                    self._reply(401, {"message": "bad credentials"})
                    return
                code, payload = service.route(self.command, self.path, body)
                self._reply(code, payload)

            do_GET = do_POST = do_PUT = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def route(self, method: str, path: str, body: bytes) -> tuple[int, dict]:
        if self.name == "zenodo":
            if method == "POST" and path == "/api/deposit/depositions":
                return 201, {"id": 4242, "state": "unsubmitted",
                             "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.4242"}},
                             "links": {"bucket": f"{self.url}/api/files/bucket-4242"}}
            if method == "PUT" and path.startswith("/api/files/bucket-4242/"):
                return 201, {"key": path.rsplit("/", 1)[1], "size": len(body)}
            if method == "POST" and path == "/api/deposit/depositions/4242/actions/publish":
                return 202, {"id": 4242, "state": "done", "submitted": True,
                             "doi": "10.5281/zenodo.4242", "conceptdoi": "10.5281/zenodo.4241"}
        if self.name == "manage" and method == "POST" and path == "/api/packages":
            document = json.loads(body or b"{}")
            assert document.get("submission_handler") is None
            return 201, {"package_id": f"pkg_{document['paper_id']}_{document['version']}"}
        return 404, {"message": f"no route {method} {path}"}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def services():
    zenodo, manage = _Service("zenodo", "zenodo-test-token"), _Service("manage", "manage-test-key")
    yield zenodo, manage
    zenodo.close()
    manage.close()


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch):
    """No real service is ever reached: only loopback connections are allowed."""

    original = socket.socket.connect

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if self.family in (socket.AF_INET, socket.AF_INET6) and host not in {"127.0.0.1", "::1"}:
            raise AssertionError(f"the delivery-chain test tried to reach {address}")
        return original(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                 "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAKE_LOOPBACK_ONLY", "1")


# --------------------------------------------------------------------------- fixture


def _guarded_command(tmp_path: Path) -> tuple[str, ...]:
    """paper-writing as installed: the resource guard's banners on stderr, then the CLI."""

    wrapper = tmp_path / "paper-writing"
    wrapper.write_text(
        "#!/bin/sh\n"
        "echo 'OpenLabs container guard: verified CPU/memory/swap/pids limits and shared GPU "
        "locks' >&2\n"
        "echo 'OpenLabs resource guard: task-type=cpu; GPU admission/monitoring not required' "
        ">&2\n"
        f"exec '{sys.executable}' '{FAKE}' \"$@\"\n", encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return (str(wrapper),)


def _chain(tmp_path, monkeypatch, services, *, issues=(), **paper):
    """A topic whose paper lives only in its campaign workspace, as an owner leaves it.

    The data repository ignores the instance ledger (runtime state) and has no Git
    identity; no credentials are in the environment yet; auto_release is off.
    """

    zenodo, manage = services
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("ARA_PAPER_MANAGE_API_URL", "ARA_PAPER_MANAGE_API_KEY", "ZENODO_ACCESS_TOKEN",
                 "OPENLABS_ENABLE_EXTERNAL_WRITES"):
        monkeypatch.delenv(name, raising=False)
    paths, db, settings, (topic,) = _program(
        tmp_path, monkeypatch, auto_handoff=True, auto_release=False,
        paper_writing_command=_guarded_command(tmp_path))
    assert settings.program.ledger_path == LEDGER
    root = paths.data
    _git(root, "init", "-q")
    (root / ".gitignore").write_text(f"/{LEDGER}\n")
    (root / "README").write_text("data\n")
    _git(root, "add", ".gitignore", "README")
    _git(root, "-c", "user.name=Base", "-c", "user.email=base@example.invalid", "commit",
         "-qm", "base")
    _install_paper(paths, issues=list(issues), **paper)
    workspace = program_autonomy.asset_library.topic_workspace(db, paths, topic)
    for relative in (f"registry/papers/{PAPER_ID}.json", f"papers/{PAPER_ID}"):
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        (root / relative).rename(target)
    log = tmp_path / "paper-calls.jsonl"
    monkeypatch.setenv("FAKE_PAPER_LOG", str(log))
    monkeypatch.setenv("FAKE_ZENODO_URL", zenodo.url)
    return paths, db, settings, topic, log


def _program_set(settings, **changes):
    return replace(settings, program=replace(settings.program, **changes))


def _stuck(report) -> dict[str, dict]:
    return {item["topic_id"]: item for item in report.program["delivery_stuck"]}


def _history(paths, settings, topic_id) -> list[dict]:
    return list(_topic(paths, settings, topic_id).get("history") or [])


# --------------------------------------------------------------------------- the chain


def test_ready_paper_reaches_the_management_site_through_every_2026_11_20_stop(
    tmp_path, monkeypatch, services
):
    zenodo, manage = services
    paths, db, settings, topic, log = _chain(
        tmp_path, monkeypatch, services, issues=[PREPARE_ISSUE],
        unbound_artifacts=[f"papers/{PAPER_ID}/main.pdf"])
    topic_id = topic["topic_id"]
    head_before = _git(paths.data, "rev-parse", "HEAD").strip()

    # Review ready -> ready_queue -> adopted into papers/ -> the Zenodo step waits for the
    # auto_release setting (TIC 260161938 stopped here without saying what it waited for).
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert report.errors == [], report.errors
    assert _commands(log)[:2] == ["program adopt", "program release-status"]
    assert (paths.data / "registry" / "papers" / f"{PAPER_ID}.json").is_file()
    stuck = _stuck(report)[topic_id]
    assert stuck["state"] == "waiting" and stuck["waiting_for"] == "auto_release_off"
    assert "auto_release = true" in stuck["condition"]
    assert zenodo.requests == [] and manage.requests == []

    # Setting on: the commit before the Zenodo draft needs a Git identity, and the data
    # repository has none (the NEM paper's first stop). It waits, naming the setting.
    settings = _program_set(settings, auto_release=True)
    monkeypatch.setenv("ZENODO_ACCESS_TOKEN", zenodo.token)
    report = _tick(paths, settings, monkeypatch)
    stuck = _stuck(report)[topic_id]
    assert stuck["state"] == "waiting" and stuck["waiting_for"] == "git_identity_missing"
    assert "[program.git] user_name" in stuck["condition"]
    assert zenodo.requests == []
    release = _topic(paths, settings, topic_id)["release"]
    assert release["status"] == "waiting" and release.get("attempts") == {}

    # Identity configured: commit (the ignored ledger is left out, never forced - the NEM
    # paper's commit failed three times on it), Zenodo draft, delta review, artifact
    # binding, Zenodo publication, release-ready commit; then delivery waits for its
    # credentials (they are not in the scheduler's environment).
    settings = _program_set(settings, git_user_name="OpenLabs Release",
                            git_user_email="release@example.invalid")
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    stuck = _stuck(report)[topic_id]
    assert stuck["state"] == "waiting" and stuck["waiting_for"] == "waiting_credentials"
    assert "ARA_PAPER_MANAGE_API_URL" in stuck["condition"]
    assert [(r["method"], r["path"].split("/")[-1]) for r in zenodo.requests] == [
        ("POST", "depositions"), ("PUT", "support.zip"), ("POST", "publish")]
    assert all(r["authorized"] for r in zenodo.requests)
    assert manage.requests == []
    paper = _paper(paths)
    assert paper["support"]["status"] == "published" and paper["support"]["doi"] == (
        "10.5281/zenodo.4242")
    assert _git(paths.data, "ls-files", LEDGER).strip() == ""  # still untracked
    assert _git(paths.data, "check-ignore", LEDGER).strip() == LEDGER

    # Credentials present; the delivery command fails once with its own JSON error behind
    # the guard's banner (the NEM delivery failure was recorded as just that banner).
    # The delivery credentials come from [program] credentials_file (0600, outside Git),
    # for the delivery child only: a group-readable file is refused and named.
    secret = tmp_path / "secrets" / "pipeline.env"
    secret.parent.mkdir()
    secret.write_text(f"ARA_PAPER_MANAGE_API_URL={manage.url}\n"
                      f"ARA_PAPER_MANAGE_API_KEY={manage.token}\n")
    secret.chmod(0o640)
    settings = _program_set(settings, credentials_file=str(secret))
    report = _tick(paths, settings, monkeypatch)
    stuck = _stuck(report)[topic_id]
    assert stuck["waiting_for"] == "waiting_credentials"
    assert "file refused: credentials_file_mode_not_0600" in stuck["condition"]
    secret.chmod(0o600)
    _write_paper(paths, {**_paper(paths), "deliver_error_once": "package upload rejected: 503"})
    report = _tick(paths, settings, monkeypatch)
    handoff = _topic(paths, settings, topic_id)["handoff"]
    assert handoff["status"] == "failed" and handoff["attempts"] == 1
    assert "package upload rejected: 503" in handoff["last_error"]
    assert "resource guard" not in handoff["last_error"]
    chain = {item["topic_id"]: item for item in report.program["delivery_chain"]}
    assert chain[topic_id]["state"] == "auto_retry" and chain[topic_id]["max_attempts"] == 3
    assert topic_id not in _stuck(report)

    # Next tick: delivered to the management site, the delivery record committed.
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    final = _topic(paths, settings, topic_id)
    assert final["release"]["status"] == "done" and final["handoff"]["status"] == "delivered"
    assert final["handoff"]["package_id"] == f"pkg_{PAPER_ID}_1.0.0"
    assert final["handoff"]["submission_handler"] is None
    assert [(r["method"], r["path"]) for r in manage.requests] == [("POST", "/api/packages")]
    import os

    assert "ARA_PAPER_MANAGE_API_KEY" not in os.environ  # never put into the tick's environment
    assert manage.requests[0]["authorized"]
    assert report.program["delivery_chain"] == [] and report.program["delivery_stuck"] == []
    commits = _git(paths.data, "rev-list", f"{head_before}..HEAD").split()
    actions = [c["action"] for c in final["release"]["commits"]]
    assert len(commits) == len(actions) >= 3 and actions[-1] == "record-delivery"
    for sha in commits:
        assert _git(paths.data, "log", "-1", "--format=%an <%ae>", sha).strip() == (
            "OpenLabs Release <release@example.invalid>")
        assert LEDGER not in _git(paths.data, "show", "--name-only", "--format=", sha)
    assert _git(paths.data, "status", "--porcelain", "--", f"papers/{PAPER_ID}",
                f"registry/papers/{PAPER_ID}.json") == ""
    # No person was needed: no release-retry, no needs_human anywhere on the way.
    kinds = [entry.get("kind") for entry in final.get("history") or []]
    assert "release_retry" not in kinds and "release_exhausted" not in kinds

    # A finished paper is left alone: no command, no request, no new history entry.
    calls, entries = len(_calls(log)), len(final.get("history") or [])
    report = _tick(paths, settings, monkeypatch)
    assert len(_calls(log)) == calls and len(_history(paths, settings, topic_id)) == entries
    assert len(manage.requests) == 1 and len(zenodo.requests) == 3


def test_preflight_failure_is_retried_then_resumed_by_a_code_fix_never_a_full_review(
    tmp_path, monkeypatch, services
):
    """TIC 260161938: a delta-review preflight failure queued a full review; later stages
    that stopped needed a human `release-retry` even after the code was fixed."""

    zenodo, manage = services
    # Exercise the code-revision fallback independently of the repair worker.
    monkeypatch.setattr(program_autonomy, "_repair_delivery", lambda *_: None)
    paths, db, settings, topic, log = _chain(tmp_path, monkeypatch, services,
                                             support="not_required",
                                             delta_outcome="preflight_failed")
    topic_id = topic["topic_id"]
    settings = _program_set(settings, auto_release=True, git_user_name="OpenLabs Release",
                            git_user_email="release@example.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", manage.url)
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", manage.token)
    revision = {"value": "a" * 40}
    monkeypatch.setattr(program_autonomy, "code_revision", lambda _paths: revision["value"])
    # The adopted paper's manuscript changed after the ready review: delta review needed.
    workspace = program_autonomy.asset_library.topic_workspace(db, paths, topic)
    (workspace / "papers" / PAPER_ID / "main.tex").write_text("\\title{T}\nBody, reworded.\n")

    report = _ready(paths, db, settings, monkeypatch, topic)
    for attempt in (1, 2):
        current = _topic(paths, settings, topic_id)
        assert current["status"] == "ready_queue", "never sent back to a full review"
        assert current["release"]["status"] == "failed"
        assert current["release"]["attempts"]["delta_review"] == attempt
        item = {i["topic_id"]: i for i in report.program["delivery_chain"]}[topic_id]
        assert item["state"] == "auto_retry" and item["attempt"] == attempt
        report = _tick(paths, settings, monkeypatch)
    exhausted = _topic(paths, settings, topic_id)
    assert exhausted["release"]["status"] == "exhausted"
    assert exhausted["release"]["exhausted_code_revision"] == "a" * 40
    stuck = _stuck(report)[topic_id]
    assert stuck["state"] == "waiting" and "release-retry" in stuck["condition"]
    assert "preflight_failed" in stuck["condition"]
    assert not any(task_id.startswith("release-review:") for task_id in report.enqueued)

    # Same code: it stays stopped.
    report = _tick(paths, settings, monkeypatch)
    assert _topic(paths, settings, topic_id)["release"]["status"] == "exhausted"

    # The cause is fixed in the code (a new revision on main): the next tick retries by
    # itself and the paper goes through.
    paper = _paper(paths)
    paper.pop("delta_outcome")
    _write_paper(paths, paper)
    revision["value"] = "b" * 40
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    final = _topic(paths, settings, topic_id)
    assert final["release"]["status"] == "done" and final["handoff"]["status"] == "delivered"
    retry = [e for e in final["history"] if e.get("kind") == "release_retry"]
    assert len(retry) == 1 and retry[0]["decided_by"] == "orchestrator:code_update"
    assert final["release"]["code_retries"] == 1
    assert len(manage.requests) == 1 and zenodo.requests == []


def test_code_retries_are_bounded(tmp_path, monkeypatch, services):
    # Exercise the code-revision fallback independently of the repair worker.
    monkeypatch.setattr(program_autonomy, "_repair_delivery", lambda *_: None)
    paths, db, settings, topic, log = _chain(tmp_path, monkeypatch, services,
                                             support="not_required",
                                             delta_outcome="preflight_failed")
    topic_id = topic["topic_id"]
    settings = _program_set(settings, auto_release=True, release_max_attempts=1,
                            git_user_name="R", git_user_email="r@example.invalid")
    workspace = program_autonomy.asset_library.topic_workspace(db, paths, topic)
    (workspace / "papers" / PAPER_ID / "main.tex").write_text("\\title{T}\nBody, reworded.\n")
    revisions = iter([c * 40 for c in "abcdefgh"])
    current = {"value": next(revisions)}
    monkeypatch.setattr(program_autonomy, "code_revision", lambda _paths: current["value"])
    _ready(paths, db, settings, monkeypatch, topic)
    for _ in range(program_autonomy.RELEASE_CODE_RETRIES + 2):
        assert _topic(paths, settings, topic_id)["release"]["status"] == "exhausted"
        current["value"] = next(revisions)
        report = _tick(paths, settings, monkeypatch)
    release = _topic(paths, settings, topic_id)["release"]
    assert release["status"] == "exhausted"
    assert release["code_retries"] == program_autonomy.RELEASE_CODE_RETRIES
    assert _stuck(report)[topic_id]["state"] == "waiting"


def test_missing_manuscript_source_needs_a_human_and_starts_no_writer(
    tmp_path, monkeypatch, services
):
    """TIC 260161938: format_fix writers were started three times on a paper whose main.tex
    the release check could not find; each ended needs_human within seconds."""

    missing = {"code": "STYLE-MANUSCRIPT-MISSING", "location": "manuscript/main.tex",
               "remedy": "control_plane", "message": "canonical manuscript source is missing",
               "text": "STYLE-MANUSCRIPT-MISSING: manuscript/main.tex: canonical manuscript "
                       "source is missing"}
    paths, db, settings, topic, log = _chain(tmp_path, monkeypatch, services, issues=[missing],
                                             support="not_required")
    settings = _program_set(settings, auto_release=True)
    report = _ready(paths, db, settings, monkeypatch, topic)
    _tick(paths, settings, monkeypatch)
    report = _tick(paths, settings, monkeypatch)
    release = _topic(paths, settings, topic["topic_id"])["release"]
    assert release["status"] == "waiting" and release["waiting_for"] == "control_plane"
    assert not release.get("writer_task_id") and not release.get("writer_rounds")
    assert not any(task_id.startswith("release-fix:") for task_id in report.enqueued)
    item = next(i for i in report.program["delivery_chain"] if i["topic_id"] == topic["topic_id"])
    assert item["state"] == "waiting" and "STYLE-MANUSCRIPT-MISSING" in item["condition"]
    assert "repair" not in item


# --------------------------------------------------------------------------- classification


def test_every_release_state_has_an_owner(tmp_path):
    from openlabs.config import FactorySettings, ProgramSettings

    class DB:
        def task(self, task_id):
            return {"status": "running"} if task_id == "w1" else None

    settings = FactorySettings(program=ProgramSettings(auto_handoff=True))

    def state(release=None, handoff=None, status="ready_queue", **topic):
        return program_autonomy.delivery_chain_state(DB(), settings, {
            "topic_id": "t", "status": status, "paper_id": "p", "release": release or {},
            "handoff": {"paper_id": "p", **(handoff or {})}, **topic})

    assert state(handoff={"status": "delivered"}, release={"status": "done"}) is None
    assert state()["state"] == "in_progress"
    assert state({"status": "running"})["state"] == "in_progress"
    assert state({"status": "failed", "stage": "commit", "attempts": {"commit": 2}}) == {
        "topic_id": "t", "paper_id": "p", "stage": "commit", "state": "auto_retry",
        "attempt": 2, "max_attempts": 3, "last_error": ""}
    assert state(handoff={"status": "failed", "attempts": 1})["state"] == "auto_retry"
    assert state({"status": "commit_pending"}, {"status": "delivered"})["state"] == "auto_retry"
    assert state({"status": "waiting", "writer_task_id": "w1"})["state"] == "in_progress"
    waiting = state({"status": "waiting", "waiting_for": "waiting_credentials",
                     "waiting_detail": {"missing": ["ARA_PAPER_MANAGE_API_KEY"]}})
    assert waiting["state"] == "waiting" and "ARA_PAPER_MANAGE_API_KEY" in waiting["condition"]
    assert state({"status": "waiting", "waiting_for": "needs_owner"})["state"] == "needs_human"
    assert state({"status": "exhausted", "stage": "commit"})["state"] == "waiting"
    assert state({"status": "exhausted", "stage": "form_fix_writer",
                  "last_error": "writer exited without a result"})["state"] == "waiting"
    assert state(handoff={"status": "exhausted"})["state"] == "waiting"
    unknown = state({"status": "waiting", "waiting_for": "something_new"})
    assert unknown["state"] == "needs_human" and unknown["unrecognized"] is True
    assert state({"status": "mystery"})["unrecognized"] is True
    off = program_autonomy.delivery_chain_state(
        DB(), FactorySettings(program=ProgramSettings()),
        {"topic_id": "t", "status": "ready_queue", "handoff": {"paper_id": "p"}})
    assert off["state"] == "waiting" and "auto_handoff" in off["condition"]
    returned = {"status": "returned_to_review"}
    history = [{"kind": "release_returned_to_review", "detail": {"review_task_id": "w1"}}]
    assert state(returned, status="in_review", history=history)["state"] == "in_progress"
    gone = [{"kind": "release_returned_to_review", "detail": {"review_task_id": "gone"}}]
    assert state(returned, status="in_review", history=gone)["state"] == "needs_human"
    assert state(status="active") is None


def test_command_error_detail_never_reports_only_the_guard_banner() -> None:
    detail = program_autonomy.command_error_detail
    banner = GUARD_BANNER + "\n"
    # 2026-11-20 02:33Z: exit 1 recorded as nothing but these two lines.
    assert "resource guard" not in detail('{"status": "failed", "error": "x"}', banner)
    assert detail('{"status": "failed", "error": "Release files are not committed"}',
                  banner) == "Release files are not committed"
    assert detail("", banner).startswith("no output from the command (only the resource guard")
    assert detail("", banner + "Traceback: boom\n") == "Traceback: boom"
    refusal = "OpenLabs GPU guard: STOP: requested GPU index is unavailable"
    assert detail("", banner + refusal) == refusal
    assert detail("plain text failure", "") == "plain text failure"
