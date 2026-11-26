"""Registry follows the site's submission status; letters of papers without a topic (2026-11-26).

The data repository is a real temporary Git repository; ``journal-correspondence`` runs the real
paper-writing CLI, ``sync-submission-status`` a fake one (no network).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml
from openlabs import submission_status
from test_program_autonomy import _program

PAPER = Path(__file__).resolve().parents[2] / "workflows" / "paper"
FAKE_CORRESPONDENCE = """
import json, sys
from paper_writing.submission_status import record_correspondence
argv = sys.argv
value = lambda name: argv[argv.index(name) + 1] if name in argv else None
print(json.dumps(record_correspondence(value("--root"), value("--paper-id"),
                                       message_key=value("--message-key"), status=value("--status"),
                                       manuscript_id=value("--manuscript-id") or "")))
"""
FAKE_SYNC = """
import json, sys, yaml
from pathlib import Path
root = Path(sys.argv[sys.argv.index("--root") + 1])
path = root / "registry/papers/old.yaml"
record = yaml.safe_load(path.read_text())
changed = []
if "external_submission" not in record:
    record["external_submission"] = {"status": "submitted", "journal": "Synthetic Astronomy"}
    path.write_text(yaml.safe_dump(record))
    changed.append({"paper_id": "old", "fields": ["external_submission"], "from": None,
                    "to": "submitted", "path": "registry/papers/old.yaml"})
print(json.dumps({"changed": changed, "current": 1 - len(changed)}))
"""


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


def _setup(tmp_path, monkeypatch, command):
    paths, db, settings, _ = _program(tmp_path, monkeypatch, paper_writing_command=command,
                                      git_user_name="OpenLabs Test",
                                      git_user_email="test@example.invalid")
    root = paths.data
    record = root / "registry" / "papers" / "old.yaml"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(yaml.safe_dump({"paper_id": "old", "title": "An old paper"}))
    _git(root, "init", "-q")
    _git(root, "add", "registry/papers/old.yaml")
    _git(root, "-c", "user.name=Base", "-c", "user.email=base@example.invalid", "commit", "-qm", "base")
    (root / "unrelated.txt").write_text("someone else's work\n")
    return paths, db, settings, record


def test_letter_of_a_paper_without_topic_is_committed_to_its_record_once(tmp_path, monkeypatch):
    # The real registry function behind `paper-writing program journal-correspondence` (the
    # CLI itself needs the paper environment's httpx).
    monkeypatch.setenv("PYTHONPATH", str(PAPER))
    fake = tmp_path / "fake_correspondence.py"
    fake.write_text(FAKE_CORRESPONDENCE)
    paths, db, settings, record = _setup(tmp_path, monkeypatch, (sys.executable, str(fake)))
    first = submission_status.record_registry_correspondence(
        db, paths, settings, paper_id="old", message_key="e" * 64, status="submitted",
        manuscript_id="SA-D-26-00471")
    assert first["status"] == "recorded" and first["commit"]
    assert _git(paths.data, "show", "--name-only", "--format=", first["commit"]).split() == [
        "registry/papers/old.yaml"]
    entries = yaml.safe_load(record.read_text())["journal_correspondence"]
    assert [e["manuscript_id"] for e in entries] == ["SA-D-26-00471"]
    again = submission_status.record_registry_correspondence(
        db, paths, settings, paper_id="old", message_key="e" * 64, status="submitted",
        manuscript_id="SA-D-26-00471")
    assert again["status"] == "already_recorded" and again["commit"] is None
    assert len(yaml.safe_load(record.read_text())["journal_correspondence"]) == 1
    assert "unrelated.txt" in _git(paths.data, "status", "--porcelain")


def test_tick_writes_site_status_back_in_one_commit_then_waits(tmp_path, monkeypatch):
    fake = tmp_path / "fake_sync.py"
    fake.write_text(FAKE_SYNC)
    paths, db, settings, record = _setup(tmp_path, monkeypatch, (sys.executable, str(fake)))
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_URL", "https://manage.invalid")
    monkeypatch.setenv("ARA_PAPER_MANAGE_API_KEY", "test-key")
    report = SimpleNamespace(program={}, errors=[])
    submission_status.sync_tick(db, paths, settings, report)
    info = report.program["submission_status"]
    assert info["outcome"] == "ok", info
    assert info["outcome"] == "ok" and info["changed"][0]["to"] == "submitted"
    assert _git(paths.data, "show", "--name-only", "--format=", info["commit"]).split() == [
        "registry/papers/old.yaml"]
    assert yaml.safe_load(record.read_text())["external_submission"]["status"] == "submitted"
    # Within the refresh interval the cached result is shown and nothing runs.
    again = SimpleNamespace(program={}, errors=[])
    submission_status.sync_tick(db, paths, settings, again)
    assert again.program["submission_status"]["cached"] is True and again.errors == []
    cache = json.loads((paths.database / "submission-status.json").read_text())
    assert cache["commit"] == info["commit"]
