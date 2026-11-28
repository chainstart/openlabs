import smtplib
import sqlite3
from unittest.mock import Mock

from paper_writing.assignment_notifications import reconcile


def test_assignment_notifications(monkeypatch, tmp_path, capsys):
    def user(user_id, name):
        return {"id": user_id, "display_name": name, "active": True,
                "email": f"{user_id}@example.org"}

    paper = {"paper_id": "paper", "lifecycle_status": "ready_to_submit", "title": "Title",
             "target_journal": "Journal", "current_package_id": "p1",
             "packages": [{"id": "p1", "version": "2"}],
             "assignments": [{"id": "a1", "submitter_id": "first", "active": True}]}
    parked = {**paper, "paper_id": "parked",
              "assignments": [{"id": "p", "submitter_id": "service", "active": True}]}
    drafts = {"paper_id": "draft", "lifecycle_status": "assigned"}
    responses = {"/v1/me": {"id": "service"},
                 "/v1/users": [user("service", "服务号"), user("first", "甲"), user("second", "乙")],
                 "/v1/papers": [paper, parked, drafts], "/v1/papers/paper": paper,
                 "/v1/papers/parked": parked, "/v1/papers/draft": drafts}
    api = Mock()
    api._request.side_effect = lambda method, path, **kwargs: responses[path]
    smtp_factory = Mock()
    smtp = smtp_factory.return_value
    monkeypatch.setattr("paper_writing.journal_dispatch.smtplib.SMTP_SSL", smtp_factory)
    monkeypatch.setenv("SDJU_MAIL_PASSWORD", "fake")

    account = "sender@example.org"
    state = tmp_path / "assignment-notifications.sqlite"
    assert reconcile(api, tmp_path, account, dry_run=True)
    assert capsys.readouterr().out == "paper 甲\n"
    assert not state.exists()
    smtp_factory.assert_not_called()

    smtp.send_message.side_effect = smtplib.SMTPDataError(451, b"try later")
    assert not reconcile(api, tmp_path, account)
    with sqlite3.connect(state) as db:
        assert db.execute("SELECT COUNT(*) FROM sent").fetchone() == (0,)

    smtp.send_message.side_effect = None
    assert reconcile(api, tmp_path, account)
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "first@example.org"
    assert message["Subject"] == "投稿待办 · 可投稿 · paper"
    for text in ("甲", "Title", "Journal", "版本：2", "投稿包", "投稿信", "建议审稿人",
                 "作者均同意", "稿件编号", "OpenLabs 产线"):
        assert text in message.get_content()
    smtp.send_message.reset_mock()
    assert reconcile(api, tmp_path, account)
    paper["assignments"][0]["id"] = "a2"
    assert reconcile(api, tmp_path, account)
    smtp.send_message.assert_not_called()
    paper["assignments"][0].update(id="a3", submitter_id="second")
    assert reconcile(api, tmp_path, account)
    assert smtp.send_message.call_args.args[0]["To"] == "second@example.org"
    smtp.send_message.reset_mock()
    paper["assignments"][0].update(id="a4", submitter_id="first")
    paper["lifecycle_status"] = "assigned"
    assert reconcile(api, tmp_path, account, paper_ids=["paper"])
    smtp.send_message.assert_not_called()
    paper["lifecycle_status"] = "ready_to_submit"
    assert reconcile(api, tmp_path, account, paper_ids=["paper"])
    assert smtp.send_message.call_args.args[0]["To"] == "first@example.org"
    with sqlite3.connect(state) as db:
        assert db.execute("SELECT assignment_id FROM sent ORDER BY rowid").fetchall() == [
            ("a1",), ("a3",), ("a4",)]

    paper["assignments"][0].update(id="a5", submitter_id="second")
    smtp.send_message.side_effect = smtplib.SMTPServerDisconnected("response lost")
    assert not reconcile(api, tmp_path, account)
    smtp.send_message.reset_mock()
    assert not reconcile(api, tmp_path, account)
    smtp.send_message.assert_not_called()
