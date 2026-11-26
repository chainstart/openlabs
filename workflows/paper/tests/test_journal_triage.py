"""Model reading of the letters journal_mail leaves to a person (paper_writing.journal_triage).
Synthetic letters only: titles, names, numbers and addresses are made up."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

from paper_writing import journal_dispatch as dispatch
from paper_writing import journal_mail as jm
from paper_writing import journal_triage as triage

TITLE = "Synthetic bounds for coloured test hypergraphs"
REJECTION = ("Dear Prof. Wei Example,\n\nThank you for submitting your manuscript SYN-D-26-00042 to Synthetic "
             "Letters.\nWe regret to inform you that your manuscript cannot be considered further for publication in "
             "Synthetic Letters.\nPlease contact editor.office@synthetic.example or call +86 21 5555 0123 with "
             "questions, or visit https://www.editorialmanager.example/syn/ for details.\n\nSincerely,\nDr. Anna "
             "Editor\nEditor-in-Chief\nanna.editor@synthetic.example\n")


def _letter(subject, body, *, mid="<letter@example.test>", sender="Anna Editor <em@editorialmanager.example>"):
    msg = EmailMessage()
    msg["Message-ID"], msg["Subject"], msg["From"] = mid, subject, sender
    msg["To"], msg["Date"] = "author.person@sdju.example", "Thu, 26 Nov 2026 01:26:54 +0000"
    msg.set_content(body)
    return msg.as_bytes()


def _paper(paper_id="p-1", title=TITLE, journal="Synthetic Letters"):
    return {"paper_id": paper_id, "title": title, "numbers": [], "attempt_journals": {},
            "attempts": [{"journal": journal, "manuscript_number": None, "status": "submitted"}]}


def _unmatched(decisions=("rejected",)):
    return jm.Unused("unmatched", "matches no paper", (), decisions, True)


def _brief(subject="Decision on SYN-D-26-00042", body=REJECTION, papers=()):
    return triage.brief(_letter(subject, body), _unmatched(), papers)


def _answer(**override):
    answer = {"key": "uid:1", "category": "rejected", "paper_id": None, "manuscript_id": "SYN-D-26-00042",
              "due": None, "confidence": 0.9, "evidence_quotes": [
                  "We regret to inform you that your manuscript cannot be considered further for publication in "
                  "Synthetic Letters."]}
    answer.update(override)
    return answer


# ---------------------------------------------------------------- the brief: no personal information


def test_brief_keeps_the_decision_and_drops_personal_information():
    letter = _brief()
    text = json.dumps(letter, ensure_ascii=False)
    for private in ("Wei Example", "Anna", "author.person", "sdju.example", "editor.office", "5555", "https://",
                    "editorialmanager.example/syn", "anna.editor"):
        assert private not in text, private
    assert letter["sender_domain"] == "editorialmanager.example"
    assert letter["manuscript_ids"] == ["SYN-D-26-00042"]
    assert any("We regret to inform you" in s for s in letter["sentences"])
    assert letter["sentences"][0].startswith("Dear [name],")
    assert letter["rules"] == {"kind": "unmatched", "reason": "matches no paper", "decisions": ["rejected"]}
    assert triage.redact("Write to a.b@x.example, call Tel: +86 21 5555 0123, see https://x.example/a or "
                         "ask Prof. Li Ming") == "Write to [email], call [phone], see [link] or ask [name]"


def test_forward_headers_and_author_lists_are_removed():
    body = ("FYI\n\n---------- Forwarded message ---------\nFrom: Editor Person <ed@journal.example>\n"
            "Date: Mon, 2 Nov 2026\nSubject: Decision on your submission\nTo: Colleague Name <c@uni.example>\n\n"
            "Authors: Wei Example, Li Sample\nYour manuscript has been rejected.\n")
    letter = _brief("Fwd: Decision on your submission", body)
    text = json.dumps(letter)
    assert "Editor Person" not in text and "Colleague Name" not in text and "Li Sample" not in text
    assert any("has been rejected" in s for s in letter["sentences"])


def test_candidates_are_the_papers_the_letter_names():
    papers = [_paper(), _paper("p-2", "Quantum walks on synthetic lattices", "Other Journal")]
    letter = _brief(body=REJECTION.replace("Thank you for submitting your manuscript",
                                           f"Thank you for submitting your manuscript \"{TITLE.lower()}\""), papers=papers)
    assert [c["paper_id"] for c in letter["candidates"]] == ["p-1"]
    assert letter["candidates"][0]["attempts"] == [{"journal": "Synthetic Letters", "status": "submitted"}]
    assert _brief(papers=[_paper("p-2", "Quantum walks on synthetic lattices", "Other Journal")])["candidates"] == []


def test_size_is_bounded_and_bookkeeping_kinds_get_no_brief():
    letter = _brief(body="Your manuscript was reviewed. " * 2000)
    assert len(letter["sentences"]) <= triage.MAX_SENTENCES
    assert sum(map(len, letter["sentences"])) <= triage.MAX_CHARS
    assert triage.brief(_letter("x", "y"), jm.Unused("no_message_id", "x"), ()) is None


# ---------------------------------------------------------------- the answer: schema and verbatim evidence


def test_a_sound_answer_holds_up():
    verdict, problem = triage.check(_brief(), _answer(evidence_quotes=[
        "We regret to inform you  that your manuscript\ncannot be considered further"]))  # whitespace folds
    assert problem is None and verdict["category"] == "rejected" and verdict["confidence"] == 0.9


@pytest.mark.parametrize("override", [
    {"category": "rejection"}, {"paper_id": "p-9"}, {"paper_id": 3}, {"due": "2026-13-01"}, {"due": "1 Dec 2026"},
    {"confidence": 1.5}, {"confidence": True}, {"confidence": "high"}, {"evidence_quotes": []},
    {"evidence_quotes": "We regret to inform you"}, {"evidence_quotes": ["short"]}, {"manuscript_id": ""},
    {"extra": 1}, {"note": "x" * 301},
])
def test_answers_off_the_schema_are_no_answer(override):
    verdict, problem = triage.check(_brief(), _answer(**override))
    assert verdict is None and problem.startswith("结论格式不符")


def test_a_missing_field_is_no_answer():
    answer = _answer()
    del answer["due"]
    assert triage.check(_brief(), answer) == (None, "结论格式不符（字段）")


@pytest.mark.parametrize("quote", [
    "We regret to inform you that your paper cannot be considered further",  # paraphrase
    "Your manuscript has been accepted for publication.",  # invented
    "we regret to inform you that your manuscript cannot be considered",  # case changed
    "Dr. Anna Editor Editor-in-Chief",  # removed from the brief
])
def test_evidence_must_be_quoted_word_for_word(quote):
    assert triage.check(_brief(), _answer(evidence_quotes=[quote])) == (None, "引文不在原信中")


def test_a_named_paper_must_be_a_candidate():
    letter = _brief(body=REJECTION.replace("your manuscript SYN", f"your manuscript \"{TITLE}\" SYN"), papers=[_paper()])
    assert triage.check(letter, _answer(paper_id="p-1"))[0]["paper_id"] == "p-1"


# ---------------------------------------------------------------- failures fall back to "模型无结论"


@pytest.mark.parametrize(("state", "model", "says"), [
    ("failed", {"error": "任务 failed"}, "任务 failed"),
    ("failed", {"error": "任务 quarantined"}, "任务 quarantined"),  # timeout / killed attempt
    ("failed", {"error": "任务结果无此信的结论"}, "无此信"),
    ("expired", None, "未在等待时间内完成"),  # quota deferral outlasting the wait
    ("pending", None, "未在等待时间内完成"),
    ("done", "{not json", "无法读取"),
    ("done", {"category": "rejected"}, "结论格式不符"),
])
def test_model_failures_are_no_answer(state, model, says):
    raw = model if isinstance(model, str) else (json.dumps(model) if model else None)
    verdict, line = triage.reading(json.dumps(_brief()), state, raw)
    assert verdict is None and line.startswith("模型无结论") and says in line


def test_waiting_ends_after_the_wait():
    now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
    assert triage.waiting("pending", (now - timedelta(hours=1)).isoformat(), now)
    assert triage.waiting("dispatched", (now - timedelta(hours=2)).isoformat(), now)
    assert not triage.waiting("pending", (now - triage.WAIT).isoformat(), now)
    assert not triage.waiting("done", now.isoformat(), now) and not triage.waiting(None, now.isoformat(), now)
    assert not triage.waiting("pending", "garbage", now)


# ---------------------------------------------------------------- the service: queue, migrate, digest


def _review(tmp_path):
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        return {r[0]: r[1:] for r in db.execute("SELECT key, model_state, brief, notified, handler_notified FROM review")}


def test_triage_queues_a_brief_only_when_on(tmp_path):
    raw = _letter("Decision on your manuscript", REJECTION)
    jm.read_letter(SimpleNamespace(state=tmp_path), 1, raw, [])
    jm.read_letter(SimpleNamespace(state=tmp_path, triage=True), 2, _letter("Decision on your paper", REJECTION,
                                                                            mid="<two@example.test>"), [])
    rows = _review(tmp_path)
    assert rows["uid:1"][:2] == (None, None)
    assert rows["uid:2"][0] == "pending" and "We regret" in rows["uid:2"][1]


def test_an_older_review_table_gains_the_columns(tmp_path):
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        db.execute("CREATE TABLE review (key TEXT PRIMARY KEY, kind TEXT, reason TEXT, paper_ids TEXT, decisions TEXT, "
                   "subject TEXT, sender TEXT, received_at TEXT, notified INTEGER DEFAULT 0)")
        db.execute("INSERT INTO review(key, kind) VALUES ('uid:0', 'unmatched')")
    jm.read_letter(SimpleNamespace(state=tmp_path, triage=True), 1, _letter("Decision", REJECTION), [])
    rows = _review(tmp_path)
    assert rows["uid:0"][0] is None and rows["uid:1"][0] == "pending"


def test_triage_switch_is_read_from_the_instance(tmp_path):
    toml = tmp_path / "openlabs.toml"
    assert jm.triage_enabled(toml) is False
    toml.write_text("[program]\njournal_mail_model_review = true\n")
    assert jm.triage_enabled(toml) is True
    toml.write_text("[program]\njournal_mail_model_review = 1\n")
    assert jm.triage_enabled(toml) is False


class _Mail:
    sent, fail = [], [False]

    def __init__(self, *a, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def login(self, *a): pass

    def sendmail(self, sender, recipients, wire):
        if self.fail[0]:
            raise dispatch.smtplib.SMTPServerDisconnected("synthetic drop")
        self.sent.append((recipients, BytesParser(policy=policy.default).parsebytes(wire)))


class _Site:
    def __init__(self):
        self.gets = []

    def _request(self, method, path, **kw):
        self.gets.append(path)
        if path == "/v1/users":
            return [{"id": "u1", "email": "handler@example.test", "active": True}]
        return {"paper_id": "p-1", "title": TITLE, "assignments": [{"submitter_id": "u1", "active": True}]}


@pytest.fixture
def mail(monkeypatch):
    _Mail.sent, _Mail.fail = [], [False]
    monkeypatch.setattr(dispatch.smtplib, "SMTP_SSL", _Mail)
    monkeypatch.setenv("SDJU_MAIL_PASSWORD", "test")
    return _Mail


def _queue(tmp_path, papers=()):
    args = SimpleNamespace(state=tmp_path, account="service@example.test", triage=True)
    # The paper was renamed since it was submitted: the rules match nothing, the words do.
    body = REJECTION.replace("your manuscript SYN", "your manuscript \"Synthetic bounds for coloured hypergraphs\" SYN")
    jm.read_letter(args, 1, _letter("Decision on your manuscript", body), list(papers))
    return args


def _set(tmp_path, **values):
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        for column, value in values.items():
            db.execute(f"UPDATE review SET {column}=?", (value,))


def _digest(tmp_path, args, api=None):
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        return dispatch.notify_review(args, db, api=api)


def test_digest_waits_for_the_model_then_goes_without(tmp_path, mail):
    args = _queue(tmp_path)
    assert _digest(tmp_path, args) is False and mail.sent == []
    _set(tmp_path, queued_at=(datetime.now(timezone.utc) - triage.WAIT).isoformat())
    assert _digest(tmp_path, args) is True
    ((_, message),) = mail.sent
    assert "模型无结论（未在等待时间内完成）" in message.get_body().get_content()
    assert _review(tmp_path)["uid:1"][0] == "expired"


def test_digest_shows_the_reading_and_tells_the_submitter_once(tmp_path, mail):
    args = _queue(tmp_path, [_paper()])
    quote = "We regret to inform you that your manuscript"
    _set(tmp_path, model_state="done", model=json.dumps(_answer(paper_id="p-1", evidence_quotes=[quote])))
    site = _Site()
    mail.fail[0] = True  # the handler notice and the digest both fail: nothing is marked
    assert _digest(tmp_path, args, site) is False
    assert _review(tmp_path)["uid:1"][2:] == (0, -1)
    mail.fail[0] = False
    assert _digest(tmp_path, args, site) is True
    handler, digest = mail.sent
    assert handler[0] == ["handler@example.test"] and handler[1]["Message-ID"].startswith("<openlabs-triage-")
    assert "系统判断为 拒稿" in handler[1].get_body().get_content() and quote in handler[1].get_body().get_content()
    text = digest[1].get_body().get_content()
    assert digest[0] == ["service@example.test"]
    assert f"系统判断为 拒稿（依据原句：「{quote}」）" in text and "论文 p-1" in text and "已通知该论文投稿人" in text
    assert "请在管理网站核对登记" in text
    assert _review(tmp_path)["uid:1"][2:] == (1, 1)
    assert _digest(tmp_path, args, site) is False and len(mail.sent) == 2  # never twice
    assert jm.parse(handler[1].as_bytes(), [_paper()]) is None  # the notice is not read back as a letter


def test_an_unverified_reading_tells_no_one(tmp_path, mail):
    args = _queue(tmp_path, [_paper()])
    _set(tmp_path, model_state="done",
         model=json.dumps(_answer(paper_id="p-1", evidence_quotes=["Your manuscript has been accepted."])))
    site = _Site()
    assert _digest(tmp_path, args, site) is True
    ((recipients, message),) = mail.sent
    assert recipients == ["service@example.test"] and site.gets == []
    assert "模型无结论（引文不在原信中）" in message.get_body().get_content()


def test_a_low_confidence_reading_goes_to_the_digest_only(tmp_path, mail):
    args = _queue(tmp_path, [_paper()])
    _set(tmp_path, model_state="done", model=json.dumps(_answer(paper_id="p-1", confidence=0.4)))
    assert _digest(tmp_path, args, _Site()) is True
    ((recipients, message),) = mail.sent
    assert recipients == ["service@example.test"] and "置信度 0.40" in message.get_body().get_content()


def test_reply_quotes_signatures_and_style_sheets_are_dropped():
    body = ("Thanks a lot!\n\nOn Mon, 2 Nov 2026 at 10:00, Wei Example <w@x.example> wrote:\n"
            "在 2026年11月2日，19:35，示例 某某 <a@b.example> 写道：\n"
            "body { margin: 0; padding: 0; }\n\nThank you for your submission.\nYour manuscript has been rejected.\n\n"
            "With best wishes,\nAlexander Sample\nStaff Editor\n")
    letter = _brief("Re: Decision", body)
    text = json.dumps(letter, ensure_ascii=False)
    assert "Wei Example" not in text and "示例" not in text and "Alexander" not in text and "margin" not in text
    assert "Thank you for your submission." in letter["sentences"]
    assert "Your manuscript has been rejected." in letter["sentences"]
