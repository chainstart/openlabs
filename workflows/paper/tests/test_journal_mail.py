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
    assert record(tmp_path, event, b"fixture")
    assert not record(tmp_path, event, b"other delivery of the same Message-ID")
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone() == (1,)
        assert db.execute("SELECT raw FROM originals").fetchone() == (b"fixture",)
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
    monkeypatch.setattr(dispatch, "notify", lambda *a, **kw: notices.append(kw["raw"]))
    monkeypatch.setattr(dispatch, "ledger", lambda *a: commands.append(a))
    uploaded = []
    monkeypatch.setattr(dispatch, "uploaded_reviews", lambda *a: "".join(uploaded))
    assert record(tmp_path, event, b"fixture")
    dispatch.drain(args, Site())
    if not with_reviews:
        assert not (tmp_path / ("a"*64 + ".txt")).exists()
        uploaded.append("Clarify lemma 1")
    dispatch.drain(args, Site())
    dispatch.drain(args, Site())
    assert set(calls) == {"mail:" + "a"*64}
    assert notices == [b"fixture"]
    assert (tmp_path / ("a"*64 + ".txt")).read_text() == "Clarify lemma 1"
    assert len([a for a in commands if len(a) == 3]) == 1


def test_rejection_letter_goes_with_the_journal_event(tmp_path):
    # C8 (2026-11-26): the dispatcher hands the verbatim letter of a rejection to journal-event.
    from email.message import EmailMessage
    from types import SimpleNamespace
    from paper_writing import journal_dispatch as dispatch

    msg = EmailMessage()
    msg["Subject"] = "Decision on your submission"
    msg.set_content("The manuscript does not clearly articulate the research problem.")
    args = SimpleNamespace(state=tmp_path)
    event = {"message_key": "b" * 64, "decision": "rejected", "raw": msg.as_bytes()}
    flag, path = dispatch.rejection_letter(args, event)
    assert flag == "--letter-file" and path == str(tmp_path / ("b" * 64 + ".letter.txt"))
    text = (tmp_path / ("b" * 64 + ".letter.txt")).read_text()
    assert text.startswith("Subject: Decision") and "research problem" in text
    assert dispatch.rejection_letter(args, {**event, "decision": "accepted"}) == []
    assert dispatch.rejection_letter(args, {**event, "raw": None}) == []


@pytest.mark.parametrize("delivery", ["attached", "advertised_limit", "rejected", "legacy"])
def test_notifier_only_uses_current_site_assignment(monkeypatch, capsys, delivery):
    from email import policy
    from email.parser import BytesParser
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
        esmtp_features = {"size": "1000"} if delivery == "advertised_limit" else {}

        def sendmail(self, sender, recipients, wire):
            sent.append((sender, recipients, wire))
            if delivery == "rejected" and len(sent) == 1:
                raise dispatch.smtplib.SMTPDataError(552, b"message exceeds fixed limit")
    monkeypatch.setattr(dispatch.smtplib, "SMTP_SSL", Mail)
    monkeypatch.setenv("SDJU_MAIL_PASSWORD", "test")
    paper = {"paper_id": "test", "title": "Synthetic", "assignments": [
        {"submitter_id": "prior", "active": False}, {"submitter_id": "actual", "active": True}]}
    event = {"message_key": "f"*64, "manuscript_id": "TEST", "due": None,
             "decision": "revision_requested", "action": "upload_reviews", "reviewer_comments": "private review text"}
    original = EmailMessage(policy=policy.SMTP)
    original["Subject"] = "Private journal letter"
    original.set_content("https://portal.example/private/token")
    original.add_attachment(b"PDF" * 500, maintype="application", subtype="pdf", filename="reviews.pdf")
    raw = original.as_bytes()
    dispatch.notify(Site(), paper, event, "test@example.test", raw=None if delivery == "legacy" else raw)
    assert all(recipients == ["actual@example.test"] for _, recipients, _ in sent)
    assert len(sent) == (2 if delivery == "rejected" else 1)
    wire = sent[-1][2]
    message = BytesParser(policy=policy.default).parsebytes(wire)
    summary = message.get_body().get_content()
    assert "稿号 TEST" in summary and "下载全部审稿意见" in summary
    assert "private review text" not in summary
    attachments = list(message.iter_attachments())
    if delivery == "attached":
        assert raw in wire
        assert len(attachments) == 1
        assert attachments[0].get_content_type() == "message/rfc822"
        embedded = attachments[0].get_payload(0)
        assert next(embedded.iter_attachments()).get_payload(decode=True) == b"PDF" * 500
    else:
        assert "请登录 SDJU 邮箱查看" in summary
        if delivery == "legacy":
            assert not attachments
        else:
            assert [part.get_filename() for part in attachments] == ["summary.txt"]
            assert "稿号 TEST" in attachments[0].get_content()
    log = capsys.readouterr().out
    assert ("exceeds SMTP size" in log) == (delivery in {"advertised_limit", "rejected"})
    assert "private/token" not in log
    paper["assignments"][0]["active"] = True
    with pytest.raises(ValueError, match="unique active assignment"):
        dispatch.notify(Site(), paper, event, "test@example.test", raw=raw)
    assert len(sent) == (2 if delivery == "rejected" else 1)


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
    record(tmp_path, event, b"fixture")
    dispatch.drain(SimpleNamespace(state=tmp_path, account="test@example.test"), Site())
    assert len(commands) == 2
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        assert db.execute("SELECT notified,complete FROM progress").fetchone() == (0,0)


# 2026-11-26: numbers of the systems the team submits through (synthetic fixtures).
@pytest.mark.parametrize(("subject", "body", "number"), [
    ("Decision on your submission to Synthetic Journal",
     "Ref: Submission ID 50488870-e5b6-4062-98ff-b95e3d9bfc5d\nDear Dr Test,", "50488870-e5b6-4062-98ff-b95e3d9bfc5d"),
    ("Submission received", "Your Submission ID is 0a1b2c3d-0000-4fff-8aaa-123456789abc.", "0a1b2c3d-0000-4fff-8aaa-123456789abc"),
    ("JOAA-D-26-00471 - Submission Confirmation for Test",
     "Your manuscript will be given a reference number once an Editor has been assigned.", "JOAA-D-26-00471"),
    ("Submission Confirmation", "The submission ID is: TEST-D-26-00012\nPlease refer to this number.", "TEST-D-26-00012"),
    ("Decision on submission to Synthetic Theory", "Ref.: Ms. No. JNTH-D-26-01626R1\nDear author,", "JNTH-D-26-01626R1"),
    ("Your submission", "Your manuscript number is JCTB11992.", "JCTB11992"),
    ("Manuscript ID TNNLS-2026-P-12345.R1 - Decision", "Dear author,", "TNNLS-2026-P-12345.R1"),
    ("Decision letter", "Thank you for submitting ABC-2026-0123 to the journal.", "ABC-2026-0123"),
    ("Decision on Nature Communications manuscript NCOMMS-26-12345-T", "Dear Dr Test,", "NCOMMS-26-12345-T"),
    ("Your manuscript", "Tracking number: NATASTRON-26-01234A", "NATASTRON-26-01234A"),
    ("Your submission", "Manuscript Number: FORUM.2026.0322", "FORUM.2026.0322"),
    ("Your submission", "Paper #24 has been received.", "24"),
    ("Thank you", "Your manuscript will be given a reference number once an Editor has been assigned.", ""),
])
def test_manuscript_numbers_of_common_systems(subject, body, number):
    from paper_writing.journal_mail import manuscript_number
    assert manuscript_number(subject, body) == number


def _letter(subject, body, *, to="submitter@example.test", date="Thu, 26 Nov 2026 01:26:54 +0000"):
    msg = EmailMessage()
    msg["Message-ID"] = "<letter@example.test>"
    msg["Subject"], msg["To"], msg["Date"] = subject, to, date
    msg.set_content(body)
    return msg.as_bytes()


def test_springer_rejection_by_submission_id():
    raw = _letter("Decision on your submission to Synthetic Journal of Learning",
                  "Ref: Submission ID 50488870-e5b6-4062-98ff-b95e3d9bfc5d\n\nYour manuscript "
                  '"Exact Synthetic Bounds For Testing" has now been assessed.\nRegrettably, your '
                  "manuscript has been rejected for publication in Synthetic Journal of Learning.")
    paper = {"paper_id": "test", "title": "Exact synthetic bounds for testing", "numbers": [],
             "target_journal": "Synthetic Journal of Learning"}
    event = parse(raw, [paper])
    assert (event["decision"], event["manuscript_id"]) == ("rejected", "50488870-e5b6-4062-98ff-b95e3d9bfc5d")


ATTEMPT = {"id": "attempt-1", "journal_name": "Synthetic Journal of Astronomy", "status": "submitted",
           "manuscript_number": None, "submitted_at": "2026-11-25T16:29:13+08:00", "package_id": "pkg",
           "created_by": "u1"}
PAPER = {"paper_id": "test", "title": "Synthetic contact binary photometry over eight years",
         "assignments": [{"submitter_id": "u1", "active": True}], "submission_events": []}
CONFIRMATION = ("TEST-D-26-00471 - Submission Confirmation for Synthetic contact binary photometry over eight years",
                "Your submission entitled \"Synthetic contact binary photometry over eight years\" has been "
                "received by journal Synthetic Journal of Astronomy\n\nThe submission ID is: TEST-D-26-00471")


def _event(decision="submitted", number="TEST-D-26-00471", received="2026-11-25T08:06:29+00:00"):
    return {"paper_id": "test", "message_key": "c"*64, "decision": decision, "due": None,
            "manuscript_id": number, "reviewer_comments": None, "received_at": received,
            "journal": "Synthetic Journal of Astronomy", "action": "verify_status"}


class _Users:
    def __init__(self):
        self.calls = []

    def _request(self, method, path, **kw):
        self.calls.append((method, path))
        return [{"id": "u1", "email": "submitter@example.test"}, {"id": "u2", "email": "other@example.test"}]


def test_attempt_without_number_matches_by_journal_title_and_time():
    from paper_writing.journal_mail import mail_context
    from paper_writing.journal_dispatch import select_attempt
    context = mail_context(_letter(*CONFIRMATION, date="Wed, 25 Nov 2026 08:06:29 +0000"))
    attempt, basis = select_attempt(_Users(), dict(PAPER, submission_attempts=[
        ATTEMPT, dict(ATTEMPT, id="old", journal_name="Other Letters", status="rejected")]), _event(), context)
    assert attempt["id"] == "attempt-1" and basis == ["journal", "time_window", "title"]


@pytest.mark.parametrize(("attempts", "event", "reason"), [
    ([ATTEMPT, dict(ATTEMPT, id="attempt-2", created_by="u2")], _event(), "ambiguous: 2 attempts"),
    ([dict(ATTEMPT, journal_name="Unrelated Letters")], _event(), "not named"),
    ([ATTEMPT], _event(received="2027-03-01T00:00:00+00:00"), "outside the time window"),
    ([dict(ATTEMPT, manuscript_number="TEST-D-26-00001")], _event(), "another manuscript number"),
    ([dict(ATTEMPT, status="preparing", submitted_at=None, created_at="2026-11-25T16:00:00+08:00")],
     _event("rejected"), "not submitted yet"),
])
def test_attempt_fallback_holds_with_a_reason(attempts, event, reason):
    from paper_writing.journal_mail import mail_context
    from paper_writing.journal_dispatch import AttemptHold, select_attempt
    context = mail_context(_letter(*CONFIRMATION, to="nobody@example.test"))
    with pytest.raises(AttemptHold, match=reason):
        select_attempt(_Users(), dict(PAPER, submission_attempts=attempts), event, context)


def test_submitter_breaks_a_tie_between_attempts():
    from paper_writing.journal_mail import mail_context
    from paper_writing.journal_dispatch import select_attempt
    context = mail_context(_letter(*CONFIRMATION, to="other@example.test"))
    paper = dict(PAPER, assignments=[], submission_attempts=[ATTEMPT, dict(ATTEMPT, id="attempt-2", created_by="u2")])
    attempt, basis = select_attempt(_Users(), paper, _event(), context)
    assert attempt["id"] == "attempt-2" and basis[-1] == "submitter"


class _Site:
    def __init__(self, paper):
        self.paper, self.posts = paper, []

    def _request(self, method, path, **kw):
        if method == "GET":
            return [] if path == "/v1/users" else self.paper
        self.posts.append((path, kw))
        return {}


def _drain(tmp_path, monkeypatch, site, event, raw):
    from types import SimpleNamespace
    from paper_writing import journal_dispatch as dispatch
    commands = []
    monkeypatch.setattr(dispatch, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(dispatch, "ledger", lambda *a: commands.append(a))
    record(tmp_path, event, raw)
    dispatch.drain(SimpleNamespace(state=tmp_path, account="test@example.test"), site)
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        row = db.execute("SELECT complete, hold_reason FROM progress").fetchone()
    return commands, row


def test_confirmation_of_a_submitted_attempt_records_its_number(tmp_path, monkeypatch):
    site = _Site(dict(PAPER, submission_attempts=[ATTEMPT]))
    commands, row = _drain(tmp_path, monkeypatch, site, _event(),
                           _letter(*CONFIRMATION, date="Wed, 25 Nov 2026 08:06:29 +0000"))
    ((path, kw),) = site.posts
    assert path == "/v1/submission-attempts/attempt-1/events"
    assert kw["json"]["event_type"] == "note" and kw["json"]["to_status"] == "submitted"
    assert kw["json"]["payload"]["manuscript_number"] == "TEST-D-26-00471"
    assert row == (1, "") and len(commands) == 1


def test_hand_registered_rejection_is_not_posted_again(tmp_path, monkeypatch):
    """An event stored before the Submission ID fix, already registered on the site by hand."""
    raw = _letter("Decision on your submission to Synthetic Journal of Astronomy",
                  "Ref: Submission ID 50488870-e5b6-4062-98ff-b95e3d9bfc5d\nYour manuscript has been rejected.")
    attempt = dict(ATTEMPT, status="rejected", manuscript_number="50488870-e5b6-4062-98ff-b95e3d9bfc5d")
    site = _Site(dict(PAPER, submission_attempts=[attempt],
                      submission_events=[{"idempotency_key": "mail:" + "c"*64, "event_type": "rejected"}]))
    commands, row = _drain(tmp_path, monkeypatch, site, _event("rejected", number=""), raw)
    assert site.posts == [] and row == (1, "")
    assert len(commands) == 1 and commands[0][1]["manuscript_id"] == "50488870-e5b6-4062-98ff-b95e3d9bfc5d"


def test_ambiguous_letter_is_held_with_its_reason(tmp_path, monkeypatch):
    site = _Site(dict(PAPER, submission_attempts=[ATTEMPT, dict(ATTEMPT, id="attempt-2")]))
    commands, row = _drain(tmp_path, monkeypatch, site, _event(), _letter(*CONFIRMATION, to="nobody@example.test"))
    assert site.posts == [] and row[0] == 0 and row[1].startswith("ambiguous: 2 attempts")
    assert len(commands) == 1


# 2026-11-26: skeletons of the letters journal_mail misread (subjects and key sentences only;
# titles, names and numbers are synthetic). See maintenance/20261126-followups/JOURNAL-MAIL-MISS.md.
TITLE = "Synthetic source classification of later isolates: the accuracy loss is concentrated in C. coli"
ELSEVIER_TAIL = ("\n\nAt Elsevier, we want to help all our authors to stay safe when publishing. If you are "
                 "publishing open access with Elsevier, bear in mind that we will never request payment before "
                 "the paper has been accepted. Identifying fake acceptance letters.\n")


def _paper(**extra):
    return {"paper_id": "test", "title": TITLE, "target_journal": "Synthetic Microbiology", "numbers": [], **extra}


@pytest.mark.parametrize(("subject", "body", "decision"), [
    # Springer Nature SNAPP acknowledgement (UID 1593404948 / 1593404923).
    ("Track the status of your manuscript",
     f"Your manuscript {TITLE} has been submitted\nTrack submission status: https://track.example/x", "submitted"),
    # Elsevier desk rejection with the anti-fraud boilerplate (UID 1593404945): never accepted.
    ("Your Submission for SYNT-26-00630",
     "Ms. Ref. No.: SYNT-26-00630\nTitle: " + TITLE + "\n\nI regret to inform you that, based on the advice "
     "from an expert in the field, your submission will not be considered for publication in Synthetic "
     "Microbiology.\nAs a matter of general policy, a submission is rejected if the initial recommendation is "
     "negative. We keep high standards for the papers we accept for publication." + ELSEVIER_TAIL, "rejected"),
    # Editorial Manager co-author confirmation (UID 1593404913): "if it is accepted" is a condition.
    ("Confirm co-authorship of submission to Synthetic Microbiology",
     "Manuscript Number: SYNT-D-26-00692\nTitle: " + TITLE + "\nThe corresponding author has listed you as a "
     "contributing author. Elsevier asks all authors to verify their co-authorship by confirming agreement to "
     "publish this article if it is accepted for publication.", "submitted"),
    # Springer rejection phrased as "cannot be accepted for publication".
    ("Decision on your Manuscript SYNT-D-26-00432",
     "With regret, I must inform you that your manuscript " + TITLE + " cannot be accepted for publication.", "rejected"),
    ("Decision on your manuscript",
     "We're delighted to let you know your manuscript " + TITLE + " has now been accepted for publication.", "accepted"),
    ("Decision on your manuscript", "Your paper " + TITLE + " has been accepted. Please complete the licence form.",
     "accepted"),
])
def test_letters_misread_on_2026_11_26(subject, body, decision):
    event = parse(_letter(subject, body), [_paper()])
    assert event and event["decision"] == decision


@pytest.mark.parametrize(("subject", "body", "reason"), [
    # Elsevier transfer offer after the rejection (UID 1593404944): the rejection is the event.
    ("A recommendation for " + TITLE, "We're sorry your submission was recently rejected. View Suggested Journals.",
     "not a decision (transfer offer)"),
    # Springer preprint opt-in: about the paper, but no decision.
    ("Preprint opt-in confirmation for Synthetic Microbiology",
     "Thank you for choosing to post your manuscript, " + TITLE + ", as a preprint.", "no decision recognised"),
    # An acceptance and a refusal in one letter: held, never chosen between.
    ("Decision", "Your manuscript " + TITLE + " has been accepted. Your manuscript has been rejected.",
     "held: conflicting decisions accepted+rejected"),
])
def test_letters_without_an_event_are_logged(subject, body, reason):
    logged = []
    assert parse(_letter(subject, body), [_paper()], log=lambda *item: logged.append(item)) is None
    assert logged == [(reason, ["test"])]


@pytest.mark.parametrize("phrase", ["Our help desk is open to talk 24/7.", "Submitted on 24 Nov 2026."])
def test_short_conference_numbers_do_not_claim_letters(phrase):
    """UID 1593404913 / 1593404931: "24" and "25" of conference papers matched dates and phrases."""
    conference = {"paper_id": "conference", "title": "An unrelated conference paper on entropy",
                  "numbers": ["24"], "attempt_journals": {"24": "SYNT Conference 2026"}}
    raw = _letter("Submission Confirmation for " + TITLE, "Your submission entitled " + TITLE
                  + " has been received by journal Synthetic Microbiology. " + phrase)
    logged = []
    event = parse(raw, [_paper(), conference], log=lambda *item: logged.append(item))
    assert event["paper_id"] == "test" and event["decision"] == "submitted" and not logged
    # Labelled as the manuscript number, a short number still identifies its paper.
    labelled = parse(_letter("Submission received", "Paper #24 has been received."), [_paper(), conference])
    assert labelled["paper_id"] == "conference" and labelled["manuscript_id"] == "24"


def test_ambiguous_letter_is_logged_with_both_papers():
    other = _paper(paper_id="other", numbers=["SYNT-D-26-00692"])
    logged = []
    raw = _letter("Submission Confirmation", "Manuscript Number: SYNT-D-26-00692\nYour submission " + TITLE
                  + " has been received.")
    assert parse(raw, [_paper(), other], log=lambda *item: logged.append(item)) is None
    assert logged == [("ambiguous: matches 2 papers", ["test", "other"])]


def test_confirmation_without_an_attempt_tells_the_submitter(tmp_path, monkeypatch):
    """UID 1593404948: the site had no attempt; the handler is told to create it (once)."""
    from types import SimpleNamespace
    from paper_writing import journal_dispatch as dispatch
    notes, commands = [], []
    monkeypatch.setattr(dispatch, "notify", lambda *a, **kw: notes.append(kw.get("note")))
    monkeypatch.setattr(dispatch, "ledger", lambda *a: commands.append(a))
    raw = _letter("Track the status of your manuscript", f"Your manuscript {TITLE} has been submitted",
                  date="Thu, 26 Nov 2026 05:58:16 +0000")
    event = parse(raw, [_paper()])
    assert event["decision"] == "submitted"
    site = _Site(dict(PAPER, title=TITLE, submission_attempts=[]))
    record(tmp_path, event, raw)
    args = SimpleNamespace(state=tmp_path, account="test@example.test")
    dispatch.drain(args, site)
    dispatch.drain(args, site)
    assert site.posts == [] and len(notes) == 1
    assert "新建投稿记录" in notes[0] and "Synthetic Microbiology" in notes[0] and "2026-11-26T05:58:16" in notes[0]
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        complete, notified, reason = db.execute("SELECT complete, notified, hold_reason FROM progress").fetchone()
    assert (complete, notified) == (0, 1) and reason.startswith("no attempt matches")
    assert len(commands) == 2  # the registry keeps the letter while it waits


def test_repeat_confirmation_of_a_registered_submission_is_not_notified(tmp_path, monkeypatch):
    """Co-author copies (UID 1593404931/934) of a confirmation the site already holds."""
    from types import SimpleNamespace
    from paper_writing import journal_dispatch as dispatch
    notes = []
    monkeypatch.setattr(dispatch, "notify", lambda *a, **kw: notes.append(kw))
    monkeypatch.setattr(dispatch, "ledger", lambda *a: None)
    attempt = dict(ATTEMPT, manuscript_number="TEST-D-26-00471")
    site = _Site(dict(PAPER, submission_attempts=[attempt]))
    record(tmp_path, _event(), _letter(*CONFIRMATION, date="Wed, 25 Nov 2026 09:22:40 +0000"))
    dispatch.drain(SimpleNamespace(state=tmp_path, account="test@example.test"), site)
    assert site.posts == [] and notes == []
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        assert db.execute("SELECT complete, notified FROM progress").fetchone() == (1, 2)


def test_status_corrected_rejection_counts_as_the_rejection():
    from paper_writing.journal_history import is_rejection_event
    assert is_rejection_event({"event_type": "rejected", "to_status": "rejected"})
    assert is_rejection_event({"event_type": "status_corrected", "to_status": "rejected"})
    assert not is_rejection_event({"event_type": "status_corrected", "to_status": "closed"})
    assert not is_rejection_event({"event_type": "accepted", "to_status": "accepted"})
