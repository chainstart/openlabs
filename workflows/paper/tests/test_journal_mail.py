"""Synthetic journal letters. All people, papers and decisions here are test fixtures."""
import sqlite3
from email.message import EmailMessage

import pytest

from paper_writing.journal_mail import parse, record


@pytest.mark.parametrize(("subject", "body", "decision", "action"), [
    ("Major revision", "Reviewer 1: Justify the bound.", "revision_requested", "prepare_revision"),
    ("Minor revision", "See https://portal.example/private/token", "revision_requested", "upload_reviews"),
    ("Submission confirmation", "Thank you.", "submitted", "verify_status"),
    ("Accepted for publication", "Congratulations.", "accepted", "verify_status"),
])
def test_synthetic_decisions(tmp_path, subject, body, decision, action):
    msg = EmailMessage()
    msg["Message-ID"] = "<fixture@example.test>"
    msg["Subject"] = subject + " — Synthetic Test Manuscript"
    msg.set_content("Manuscript ID: TEST-23\nDeadline: 2026-12-31\n" + body)
    paper = {"paper_id": "test", "title": "Synthetic Test Manuscript", "target_journal": "Test Journal"}
    event = parse(msg.as_bytes(), [paper])
    assert (event["decision"], event["action"]) == (decision, action)
    assert (event["manuscript_id"], event["due"]) == ("TEST-23", "2026-12-31")
    assert "private/token" not in str(event)
    assert record(tmp_path, event)
    assert not record(tmp_path, event)
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone() == (1,)
    assert parse(msg.as_bytes(), [paper, dict(paper, paper_id="other")]) is None


@pytest.mark.parametrize("with_reviews", [True, False])
def test_offline_dispatch_replay_and_handler_upload(tmp_path, monkeypatch, with_reviews):
    from types import SimpleNamespace
    from paper_writing import journal_dispatch as dispatch
    calls, notices, commands = [], [], []
    class Site:
        def _request(self, method, path, **kw):
            if method == "GET":
                return {"paper_id": "test", "submission_attempts": [{"id": "attempt", "manuscript_number": "TEST-42",
                        "package_id": "original", "current_round": 0, "status": "submitted"}]}
            assert path == "/v1/submission-attempts/attempt/review-rounds"
            calls.append(kw["idempotency_key"])
            assert kw["json"]["round_no"] == 1
            return {"review_round": {"id": "round"}, "revision_request": {"request_id": "req"}}
    event = {"paper_id": "test", "message_key": "a"*64, "decision": "revision_requested", "due": None,
             "manuscript_id": "TEST-42", "reviewer_comments": "Clarify lemma 1" if with_reviews else None}
    args = SimpleNamespace(state=tmp_path, account="test@example.test")
    monkeypatch.setattr(dispatch, "notify", lambda *a: notices.append(True))
    monkeypatch.setattr(dispatch, "ledger", lambda *a: commands.append(a))
    uploaded = []
    monkeypatch.setattr(dispatch, "uploaded_reviews", lambda *a: "".join(uploaded))
    assert record(tmp_path, event)
    dispatch.drain(args, Site())
    if not with_reviews:
        assert not (tmp_path / ("a"*64 + ".txt")).exists()
        uploaded.append("Clarify lemma 1")
    dispatch.drain(args, Site())
    dispatch.drain(args, Site())
    assert set(calls) == {"mail:" + "a"*64}
    assert notices == [True]
    assert (tmp_path / ("a"*64 + ".txt")).read_text() == "Clarify lemma 1"
    assert len([a for a in commands if len(a) == 3]) == 1


def test_notifier_only_uses_current_site_assignment(monkeypatch):
    from paper_writing import journal_dispatch as dispatch
    class Site:
        def _request(self, *a):
            return [{"id": i, "email": i+"@example.test", "active": True} for i in ("prior", "actual")]
    sent = []
    class Mail:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): pass
        def send_message(self, message, **kw): sent.append((message, kw))
    monkeypatch.setattr(dispatch.smtplib, "SMTP_SSL", Mail)
    monkeypatch.setenv("SDJU_MAIL_PASSWORD", "test")
    paper = {"paper_id": "test", "title": "Synthetic", "assignments": [
        {"submitter_id": "prior", "active": False}, {"submitter_id": "actual", "active": True}]}
    event = {"message_key": "f"*64, "manuscript_id": "TEST", "due": None,
             "decision": "revision_requested", "action": "upload_reviews", "reviewer_comments": "private review text"}
    dispatch.notify(Site(), paper, event, "test@example.test")
    assert sent[0][1]["to_addrs"] == ["actual@example.test"]
    assert "private review text" not in sent[0][0].get_content()


def test_copyable_fields_and_private_revision_file_gate(tmp_path):
    from paper_writing.handoff import HandoffError, _copyable_tex_fields, _journal_response_files
    (tmp_path / "main.tex").write_text(r"\abstract{An {actual} abstract}\keywords{graphs, bounds}")
    assert _copyable_tex_fields(tmp_path) == {"abstract": "An {actual} abstract", "keywords": "graphs, bounds"}
    with pytest.raises(HandoffError):
        _journal_response_files(tmp_path, "test", "../escape")
    folder = tmp_path / "papers/test/journal-revisions/R1"
    folder.mkdir(parents=True)
    for name in ("marked.pdf", "response.md", "locations.md"):
        (folder / name).write_text("TEST")
    with pytest.raises(HandoffError, match="uploads.md"):
        _journal_response_files(tmp_path, "test", "R1")
    (folder / "uploads.md").write_text("TEST")
    assert len(_journal_response_files(tmp_path, "test", "R1")) == 4


def test_missing_handler_does_not_block_model_or_status(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from paper_writing import journal_dispatch as dispatch
    class Site:
        def _request(self, method, path, **kwargs):
            if method == "GET":
                return {"assignments": [], "submission_attempts": [{"id": "a", "manuscript_number": "TEST-1",
                        "status": "submitted", "package_id": "package"}]}
            return {"review_round": {"id": "round"}, "revision_request": {"request_id": "req"}}
    commands = []
    monkeypatch.setattr(dispatch, "ledger", lambda *args: commands.append(args))
    event = {"paper_id": "test", "message_key": "b"*64, "decision": "revision_requested", "due": None,
             "manuscript_id": "TEST-1", "reviewer_comments": "Explain proof."}
    record(tmp_path, event)
    dispatch.drain(SimpleNamespace(state=tmp_path, account="test@example.test"), Site())
    assert len(commands) == 2
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        assert db.execute("SELECT notified,complete FROM progress").fetchone() == (0,0)
