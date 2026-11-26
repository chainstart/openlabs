"""Defects of the 2026-11-26 audit (maintenance/20261126-followups/JOURNAL-MAIL-AUDIT.md).

Skeletons of real letters: the publishers' key sentences are kept, every title, name, number
and address is synthetic.
"""
import sqlite3
from datetime import datetime, timezone
from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from paper_writing import journal_dispatch as dispatch
from paper_writing import journal_mail as jm
from paper_writing.journal_mail import classify, parse, record, revision_due

TITLE = "Synthetic bounds for coloured test hypergraphs"


def _letter(subject, body, *, mid="<letter@example.test>", date="Thu, 26 Nov 2026 01:26:54 +0000",
            charset=None):
    msg = EmailMessage()
    msg["Message-ID"], msg["Subject"], msg["To"], msg["Date"] = mid, subject, "author@example.test", date
    if charset:
        msg.set_content(body.encode(), maintype="text", subtype="plain", cte="8bit")
        msg.replace_header("Content-Type", f"text/plain; charset={charset}")
    else:
        msg.set_content(body)
    return msg.as_bytes()


def _paper(**extra):
    return {"paper_id": "test", "title": TITLE, "numbers": [], "attempt_journals": {}, **extra}


def _decisions(subject, body):
    found = classify(subject, body)
    return None if found is None else set(found)


# C1: MSP EditFlow receipts quote the author declaration (UID 1593403306, 1593404348, ...).
MSP_RECEIPT = ("The Synthetic Journal of Combinatorics has received your submission:\n\nDate: 03 Jun 2026\n"
               f"Title: {TITLE}\nPaper ID: 260603-Test-5\n\nBy submitting, the authors confirm:\n"
               "* The submitted article has not already been published or accepted for publication in a "
               "peer-reviewed journal.\n* The submitted article is not a revision of a *rejected* article "
               "previously submitted to this journal, unless explicitly invited to re-submit.")


@pytest.mark.parametrize(("subject", "body"), [
    ("Synth.J.Comb. 260603-Test-5 - Submission", MSP_RECEIPT),
    # AIP receipt (UID 1593404698): "has not been accepted (and is not under active consideration)".
    ("SJP: MS #SJP26-AR-00001 Receipt of New Paper",
     f"Title: {TITLE}. Your manuscript passed the submission check. It is understood that this manuscript is for our own "
     "exclusive use and has not been accepted (and is not under active consideration) for publication elsewhere."),
])
def test_author_declarations_are_not_acceptances(subject, body):
    assert _decisions(subject, body) == {"submitted"}
    event = parse(_letter(subject, body), [_paper()])
    assert event["decision"] == "submitted"


@pytest.mark.parametrize("body", [
    # arXiv announcement forwarded by a colleague (UID 1593403651).
    "Title: " + TITLE + "\nComments: Accepted for publication in Synthetic Quantum Science",
    # ICONIP 109 (UID 1593403860): the full paper declined, an abstract presentation offered.
    f'We are pleased to inform you that your submission entitled: "{TITLE}" has been accepted for abstract '
    "presentation at SYNTCONF 2026.",
    # MDPI final proofreading (UID 1593403811): a template sentence.
    "We invite you to proofread your manuscript. Once accepted for publication, we aim to ensure that research "
    "is published as soon as possible.",
])
def test_quoted_and_template_acceptances_are_not_acceptances(body):
    assert "accepted" not in (_decisions("Fw: Your letter", body) or set())


@pytest.mark.parametrize(("subject", "body"), [
    ("Synthetic Reports: Decision on your manuscript",
     "We're delighted to let you know your manuscript has now been accepted for publication in Synthetic Reports."),
    ("SYNTCONF 2026 notification for paper 108",
     f'We are pleased to inform you that your submission entitled: "{TITLE}" has been accepted for publication '
     "in the proceedings of SYNTCONF 2026."),
    ("Your manuscript SYN-118313.R1", "We are pleased to tell you that we are accepting your Paper."),
    ("[Mathematics] Manuscript ID: synth-0001 - Accepted for Publication",
     "Congratulations on the acceptance of your manuscript."),
])
def test_real_acceptances_still_count(subject, body):
    assert _decisions(subject, body) == {"accepted"}


# C2: refusals the classifier missed (APS, OJS, IEEE, MDPI, Hindawi, Elsevier, Wiley).
@pytest.mark.parametrize(("subject", "body"), [
    ("Fw:Transfer Offer for Your Submission to Synthetic Quantum Technologies",
     "Unfortunately, following editorial evaluation, we are unable to consider it further for publication in "
     "Synthetic Quantum Technologies; however, your manuscript could be suitable for a sister journal. If you "
     "transfer your manuscript to a fully open access journal and your paper is accepted for publication, then "
     "an Article Publication Charge must be paid."),
    ("Your_manuscript SD13800 Test", "After careful consideration, we have determined that this manuscript is not "
     "suitable for Physical Review S."),
    ("Decision SD14177 Test", "Regrettably, this manuscript fails to match the minimal threshold for the journals."),
    ("Decision SD13834 Test", "Unfortunately, in view of the reviewer comments, we do not find that the present "
     "manuscript meets our acceptance criteria."),
    ('[S-JC] Editor Decision "' + TITLE + '" - initial decline',
     "The editors have decided not to proceed with your submission. We aim to accept only the top 15% of papers."),
    ("Your Submission SYNCOM-D-26-00001", "Unfortunately, after an initial evaluation, I feel your manuscript is "
     "not appropriate for this journal's readership."),
    ("SDM_00001", "When we anticipate that a paper has very little chance of acceptance, we try to save time for "
     "the authors by making a quick decision without sending the paper to referees."),
    ("Decision on submission to Synthetic Solids", "After careful evaluation, I have determined there are other "
     "journals that may better suit your work. Please confirm whether you would like to accept this transfer offer."),
    ("Synthetic Access - Decision on Manuscript ID Access-2026-00001",
     "Your manuscript has not been recommended for publication in Synthetic Access."),
    ("[Synthetic] Manuscript ID: synth-0002 - Declined for Publication",
     "We are writing to inform you that we will not be able to process your submission further."),
    ("[SITC] Editor Decision", "Our decision is to: Decline submission."),
    (TITLE + ": Manuscript refused to consider", "We have unfortunately found it unsuitable for publication."),
    ("SYTCS-D-23-00001", "The handling editor has decided that publication of your article cannot be recommended."),
    ("Your submission to Synthetic Software", "While your paper was not selected for publication this time, we "
     "want you to know that you are not alone."),
])
def test_refusals_are_rejections(subject, body):
    assert _decisions(subject, body) == {"rejected"}


@pytest.mark.parametrize(("subject", "body"), [
    # SIAM receipt (UID 1593404188): neither "cannot accept electronic files" nor "should it be accepted".
    ("SISYN manuscript #M100001; receipt of new submission",
     "Please prepare the following items, should you be asked to revise your paper, or should it be accepted for "
     "publication. If your paper is accepted for publication, SIAM will ask for a LaTeX file. Note that SIAM "
     "cannot accept electronic files produced on any other typesetting system."),
    # Hindawi APC letter of an accepted paper: "unable to accept payment by check".
    ("100001: Article Processing Charges",
     f"Your manuscript, {TITLE}, has been accepted for publication. We are unable to accept payment by check."),
])
def test_refusals_need_the_paper_as_object(subject, body):
    assert "rejected" not in _decisions(subject, body)


@pytest.mark.parametrize("prefix", ["Fw:", "Fwd: ", "转发: ", "回复：", "Re: Fw: ", "Reminder: "])
def test_forward_prefixes_keep_transfer_offers_out(prefix):
    assert classify(prefix + "A recommendation for " + TITLE, "Your submission was recently rejected.") is None


def test_acceptance_and_refusal_in_one_letter_is_held_for_review(tmp_path):
    logged = []
    raw = _letter("Decision", f"Your manuscript {TITLE} has been accepted. Your manuscript has been rejected.")
    assert parse(raw, [_paper()], log=logged.append) is None
    (item,) = logged
    assert (item.kind, item.decisions, item.review) == ("conflict", ("accepted", "rejected"), True)


# C3: a letter must never stop the mailbox.
def test_unknown_charset_is_decoded_instead_of_raising():
    raw = _letter("Decision on your manuscript", f"Your manuscript {TITLE} has been rejected.", charset="x-unknown")
    assert parse(raw, [_paper()])["decision"] == "rejected"


def test_a_failing_letter_is_queued_for_review_and_skipped(tmp_path, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise TypeError("synthetic parser failure")
    monkeypatch.setattr(jm, "parse", broken)
    args = SimpleNamespace(state=tmp_path)
    raw = _letter("Decision on your manuscript", "body")
    assert jm.read_letter(args, 4242, raw, []) is None
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        assert db.execute("SELECT key, kind, reason, subject FROM review").fetchall() == [
            ("uid:4242", "parse_failed", "parse failed: TypeError", "Decision on your manuscript")]
    assert "uid=4242 parse_failed" in capsys.readouterr().out


def test_poll_moves_past_a_failing_letter(tmp_path, monkeypatch):
    """The cursor advances over a letter the parser fails on; the next letter is still read."""
    import json
    seen = []

    def fake_parse(raw, entries, log=None):
        seen.append(raw)
        if raw == b"poison":
            raise LookupError("unknown encoding")
        return None
    monkeypatch.setattr(jm, "parse", fake_parse)

    class Mailbox:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): pass
        def select(self, *a, **kw): return ("OK", [b"2"])
        def response(self, name): return ("OK", [b"7" if name == "UIDVALIDITY" else b"13"])
        def uid(self, command, *args):
            if command == "search":
                return "OK", [b"11 12"]
            return "OK", [(b"1 (UID %s BODY[]" % args[0].encode(), b"poison" if args[0] == "11" else b"fine"), b")"]

    class Site:
        def _request(self, method, path, **kw):
            return []
    monkeypatch.setattr(jm.imaplib, "IMAP4_SSL", Mailbox)
    monkeypatch.setenv("SDJU_MAIL_PASSWORD", "test")
    (tmp_path / "cursor.json").write_text(json.dumps({"uidvalidity": 7, "uid": 10}))
    jm.poll(SimpleNamespace(state=tmp_path, account="a@example.test"), Site())
    assert seen == [b"poison", b"fine"]
    assert json.loads((tmp_path / "cursor.json").read_text())["uid"] == 12
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        assert db.execute("SELECT key, kind FROM review").fetchall() == [("uid:11", "parse_failed")]


def test_unmatched_decision_letters_are_queued_and_other_letters_only_logged(tmp_path):
    args = SimpleNamespace(state=tmp_path)
    renamed = _letter('[S-JC] Editor Decision "An earlier title"', "The editors have decided not to proceed "
                      "with your submission.", mid="<a@example.test>")
    advert = _letter("Call for papers", "Submit to our special issue.", mid="<b@example.test>")
    unrelated_confirmation = _letter("Confirming your submission to Synthetic Letters",
                                     "Your submission entitled \"Other\" has been received by Synthetic Letters.",
                                     mid="<c@example.test>")
    for uid, raw in ((1, renamed), (2, advert), (3, unrelated_confirmation)):
        assert jm.read_letter(args, uid, raw, [_paper()]) is None
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        assert db.execute("SELECT key, kind, decisions FROM review").fetchall() == [
            ("uid:1", "unmatched", '["rejected"]')]


def test_own_notifications_are_not_read_as_letters():
    raw = _letter("投稿待办 · test", f"{TITLE}\n状态 accepted", mid="<openlabs-" + "a" * 64 + "@sdju.edu.cn>")
    logged = []
    assert parse(raw, [_paper()], log=logged.append) is None and logged == []


# C4: the revision's due date only from the decision itself.
RECEIVED = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
MDPI_FOOTER = ("\n------------------------------\nYoung Investigator Award—Open for Nomination\nNomination deadline: "
               "31 December 2025\nSubmit your abstract by 10 February 2026\nTravel Award Application deadline: "
               "31 October 2026\n")


@pytest.mark.parametrize(("subject", "body", "due"), [
    ("[Mathematics] Manuscript ID: synth-0003 - Minor Revision",
     "Please revise the manuscript according to the reviewers' comments and upload the revised file within 5 days."
     + MDPI_FOOTER, "2026-08-01"),
    ("[Mathematics] Manuscript ID: synth-0004 - Major Revision - Due Date 4 September",
     "Please upload the revised file within 8 days." + MDPI_FOOTER, "2026-09-04"),
    ("Synthetic Reports: Decision on your manuscript", "Decision: minor revision\nDeadline: 27 Aug 2026\nDear Dr Test,",
     "2026-08-27"),
    ("Decision", "The revised manuscript should be returned to the Editors by 15-Dec-2026.", "2026-12-15"),
    ("Interim Decision", "Minor revisions are needed. The revision is due Dec 08, 2026.", "2026-12-08"),
    ("Minor Revision", "Please revise your paper." + MDPI_FOOTER, None),
])
def test_revision_due_comes_from_the_decision_only(subject, body, due):
    assert revision_due(subject, body, RECEIVED) == due


def test_parsed_revision_carries_the_decision_due_date():
    raw = _letter("[Mathematics] Manuscript ID: synth-0003 - Minor Revision",
                  f"Your manuscript {TITLE} needs a minor revision. Upload the revised file within 5 days." + MDPI_FOOTER,
                  date="Mon, 27 Jul 2026 08:00:00 +0000")
    event = parse(raw, [_paper()])
    assert (event["decision"], event["due"]) == ("revision_requested", "2026-08-01")


# C6/C7: confirmations, confirmations of a revision, and proofs.
@pytest.mark.parametrize(("subject", "body", "decision"), [
    ("SYNTB11988 - Confirming your submission to Synthetic Theory, Series B",
     f'Your submission entitled "{TITLE}" has been received by Synthetic Theory, Series B.', "submitted"),
    ("Your submission has been received. Here's what happens next.",
     "Thank you for submitting your manuscript to Elsevier. Your article is now with the journal.", "submitted"),
    ("Synthetic Reasoning - Receipt of Manuscript 'Synthetic...'", "Thank you for submitting your manuscript.",
     "submitted"),
    ("Track the status of your submission to Synthetic Informatics", "Your submitted manuscript is under review.",
     "submitted"),
    ("Editorial Acknowledgment SD13800 Test", "The editors acknowledge receipt of this manuscript.", "submitted"),
    ("SJP: Receipt of Manuscript MS #SJP26-AR-00002", "On 31-Oct-2026, we received the manuscript entitled X.",
     "submitted"),
    ("PROC 260816-Test - Submission", "The Proceedings of the Synthetic Society has received your submission.",
     "submitted"),
    ("SYNTCONF 2026 submission 107", "We received your submission to SYNTCONF 2026.", "submitted"),
    ("SYN-26-3391R1: Confirmation of Revision Received", "We have received your revised submission.", "submitted"),
    ("[Mathematics] Manuscript ID: synth-0003 - Manuscript Resubmitted",
     "Thank you very much for resubmitting the modified version of the following manuscript.", "submitted"),
    ("[Mathematics] Manuscript ID: synth-0003 - Revised Version Received",
     "Thank you very much for providing the revised version of your paper.", "submitted"),
    ("SQS: Receipt of Revised Manuscript MS #SQS25-AR-00177R",
     "On 13-Dec-2025, we received a revised version of the manuscript entitled X.", "submitted"),
    ("PDF and HTML Proofs: available for review", "The PDF and HTML proofs for your paper are now available.",
     "proofs"),
    ("Proofs for your article in Synthetic Reports", "Please check the proofs.", "proofs"),
    ("[Mathematics] Manuscript ID: synth-0003 - Final Proofreading Before Publication",
     "We invite you to proofread your manuscript.", "proofs"),
    # An acceptance announcing later proofs is an acceptance only.
    ("Your manuscript SYN-1.R1 has been accepted for publication",
     "We will email again when article proofs are ready for your final approval.", "accepted"),
])
def test_confirmations_revisions_received_and_proofs(subject, body, decision):
    assert _decisions(subject, body) == {decision}


@pytest.mark.parametrize(("subject", "body"), [
    ("Your PDF has been built and requires approval",
     "Once all of the above steps are done, you will receive an e-mail confirming receipt of your submission."),
    ("Submission to Synthetic Letters requires action",
     "Either your manuscript has been received from another journal or pre-print service and you must now complete it."),
    ("Editor handles SYN-D-26-01626", "Your submission will be handled by an editor."),
])
def test_system_notices_are_not_confirmations(subject, body):
    assert not _decisions(subject, body)


# C9: matching.
def test_journal_scoped_number_needs_its_journal():
    """UID 1593404423: CPC's "261010-Test" is also another paper's Acta Arithmetica number."""
    other = {"paper_id": "acta", "title": "An unrelated arithmetic paper", "numbers": ["261010-Test"],
             "attempt_journals": {"261010-Test": "Acta Synthetica"}}
    raw = _letter("SCPC 261010-Test - Submission", "Synthetic Combinatorics has received your submission:\n"
                  f"Title: {TITLE}\nPaper ID: 261010-Test")
    event = parse(raw, [_paper(), other])
    assert event["paper_id"] == "test"
    own = _letter("AS 261010-Test - Submission", "Acta Synthetica has received your submission:\nPaper ID: 261010-Test",
                  mid="<own@example.test>")
    assert parse(own, [_paper(), other])["paper_id"] == "acta"


def test_recommended_journals_do_not_select_an_attempt():
    from paper_writing.journal_mail import mail_context
    raw = _letter("Decision on submission to Synthetic Solids",
                  f"Manuscript: {TITLE}\nI have determined there are other journals that may better suit your work. "
                  "The alternative journals I recommend are listed here: Synthetic Matter.")
    paper = {"paper_id": "test", "title": TITLE, "assignments": [], "submission_attempts": [
        {"id": "matter", "journal_name": "Synthetic Matter", "status": "submitted",
         "submitted_at": "2026-11-01T00:00:00+00:00"}]}
    event = {"decision": "rejected", "manuscript_id": "", "journal": None, "received_at": "2026-11-26T01:26:54+00:00"}
    with pytest.raises(dispatch.AttemptHold, match="not named"):
        dispatch.select_attempt(None, paper, event, mail_context(raw))


def test_closed_attempt_is_not_moved_to_another_outcome():
    paper = {"submission_attempts": [{"id": "rejected-1", "manuscript_number": "SYN-D-26-00001", "status": "rejected"}]}
    with pytest.raises(dispatch.AttemptHold, match="already rejected"):
        dispatch.select_attempt(None, paper, {"decision": "accepted", "manuscript_id": "SYN-D-26-00001"}, None)
    attempt, _ = dispatch.select_attempt(None, paper, {"decision": "rejected", "manuscript_id": "SYN-D-26-00001"}, None)
    assert attempt["id"] == "rejected-1"


# Dispatch: C5 notification retries, C8 review digest, C10 copies and hold notes.
class _Site:
    def __init__(self, paper):
        self.paper, self.posts = paper, []

    def _request(self, method, path, **kw):
        if method == "GET":
            return [] if path == "/v1/users" else self.paper
        self.posts.append((path, kw))
        return {"review_round": {"id": "round"}, "revision_request": {"request_id": "req"}}


ATTEMPT = {"id": "attempt-1", "journal_name": "Synthetic Letters", "status": "submitted",
           "manuscript_number": "SYN-D-26-00001", "submitted_at": "2026-11-01T00:00:00+00:00", "package_id": "pkg"}


def _event(decision, **extra):
    return {"paper_id": "test", "message_key": "d" * 64, "decision": decision, "due": None,
            "manuscript_id": "SYN-D-26-00001", "reviewer_comments": None, "received_at": "2026-11-20T00:00:00+00:00",
            "journal": "Synthetic Letters", "action": "verify_status", **extra}


def _args(tmp_path):
    return SimpleNamespace(state=tmp_path, account="service@example.test")


def _progress(tmp_path):
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        return db.execute("SELECT notified, complete, hold_reason FROM progress").fetchone()


def test_failed_send_is_retried_and_not_lost(tmp_path, monkeypatch):
    sends = []

    def flaky(api, paper, event, account, before_send=lambda: None, **kw):
        before_send()
        sends.append(event["decision"])
        if len(sends) == 1:
            raise dispatch.smtplib.SMTPServerDisconnected("synthetic drop")
    monkeypatch.setattr(dispatch, "notify", flaky)
    monkeypatch.setattr(dispatch, "ledger", lambda *a, **kw: None)
    record(tmp_path, _event("rejected"), b"fixture")
    site = _Site({"paper_id": "test", "submission_attempts": [ATTEMPT], "submission_events": []})
    dispatch.drain(_args(tmp_path), site)
    assert _progress(tmp_path)[:2] == (0, 0)
    dispatch.drain(_args(tmp_path), site)
    assert sends == ["rejected", "rejected"] and _progress(tmp_path)[:2] == (1, 1)


def test_interrupted_send_is_not_repeated_but_reported(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(dispatch, "notify", lambda *a, **kw: sent.append(a))
    monkeypatch.setattr(dispatch, "ledger", lambda *a, **kw: None)
    monkeypatch.setattr(dispatch, "notify_review", lambda *a, **kw: False)
    record(tmp_path, _event("rejected"), b"fixture")
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        db.execute("CREATE TABLE progress (message_key TEXT PRIMARY KEY, round_no INTEGER, notified INTEGER DEFAULT 0, "
                   "complete INTEGER DEFAULT 0)")
        db.execute("INSERT INTO progress(message_key, notified) VALUES (?, -1)", ("d" * 64,))
    dispatch.drain(_args(tmp_path), _Site({"paper_id": "test", "submission_attempts": [ATTEMPT]}))
    assert sent == [] and _progress(tmp_path)[:2] == (3, 1)
    with sqlite3.connect(tmp_path / "events.sqlite") as db:
        assert db.execute("SELECT key, kind FROM review").fetchall() == [("event:" + "d" * 64, "notification_unknown")]


def test_review_digest_is_one_mail_sent_once(tmp_path, monkeypatch):
    from email import policy
    from email.parser import BytesParser
    wires, fail = [], [True]

    class Mail:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): pass

        def sendmail(self, sender, recipients, wire):
            if fail[0]:
                raise dispatch.smtplib.SMTPServerDisconnected("synthetic drop")
            wires.append((recipients, wire))
    monkeypatch.setattr(dispatch.smtplib, "SMTP_SSL", Mail)
    monkeypatch.setenv("SDJU_MAIL_PASSWORD", "test")
    args = SimpleNamespace(state=tmp_path)
    jm.read_letter(args, 1, _letter("Decision", f"Your manuscript {TITLE} has been accepted. It has been rejected.",
                                    mid="<one@example.test>"), [_paper()])
    jm.read_letter(args, 2, _letter("Decision on your paper", f"About {TITLE}.", mid="<two@example.test>"), [_paper()])
    record(tmp_path, _event("rejected"), b"fixture")  # drain needs the events table
    monkeypatch.setattr(dispatch, "dispatch_one", lambda *a: None)
    dispatch.drain(_args(tmp_path), None)
    assert wires == []
    fail[0] = False
    dispatch.drain(_args(tmp_path), None)
    dispatch.drain(_args(tmp_path), None)
    ((recipients, wire),) = wires
    assert recipients == ["service@example.test"]
    message = BytesParser(policy=policy.default).parsebytes(wire)
    assert message["Message-ID"].startswith("<openlabs-review-")
    text = message.get_body().get_content()
    assert "2 封信" in text and "决定冲突" in text and "认不出决定" in text and "uid:1" in text and "uid:2" in text
    assert parse(wire, [_paper()]) is None  # the digest itself is never read as a letter


def test_letter_on_an_outcome_the_site_holds_is_not_notified_again(tmp_path, monkeypatch):
    """A forward of an acceptance the site already lists (MDPI follow-ups, colleague copies)."""
    notes = []
    monkeypatch.setattr(dispatch, "notify", lambda *a, **kw: notes.append(a))
    monkeypatch.setattr(dispatch, "ledger", lambda *a, **kw: None)
    record(tmp_path, _event("accepted"), b"fixture")
    site = _Site({"paper_id": "test", "submission_attempts": [dict(ATTEMPT, status="published")],
                  "submission_events": []})
    dispatch.drain(_args(tmp_path), site)
    assert site.posts == [] and notes == [] and _progress(tmp_path)[:2] == (2, 1)


def test_copy_of_an_open_revision_finishes_without_notice(tmp_path, monkeypatch):
    notes = []
    monkeypatch.setattr(dispatch, "notify", lambda *a, **kw: notes.append(kw.get("note")))
    monkeypatch.setattr(dispatch, "ledger", lambda *a, **kw: None)
    round_1 = {"id": "round-1", "attempt_id": "attempt-1", "round_no": 1, "received_at": "2026-11-09T00:00:00+00:00"}
    record(tmp_path, _event("revision_requested", received_at="2026-11-15T00:00:00+00:00"), b"fixture")
    site = _Site({"paper_id": "test", "submission_attempts": [dict(ATTEMPT, status="revision_preparing")],
                  "review_rounds": [round_1], "assignments": []})
    dispatch.drain(_args(tmp_path), site)
    dispatch.drain(_args(tmp_path), site)
    assert site.posts == [] and notes == [] and _progress(tmp_path) == (2, 1, "copy of round 1")


def test_late_revision_letter_for_an_open_round_is_told_once(tmp_path, monkeypatch):
    notes = []
    monkeypatch.setattr(dispatch, "notify", lambda *a, **kw: notes.append(kw.get("note")))
    monkeypatch.setattr(dispatch, "ledger", lambda *a, **kw: None)
    round_1 = {"id": "round-1", "attempt_id": "attempt-1", "round_no": 1, "received_at": "2026-06-01T00:00:00+00:00"}
    record(tmp_path, _event("revision_requested"), b"fixture")
    site = _Site({"paper_id": "test", "submission_attempts": [dict(ATTEMPT, status="revision_preparing")],
                  "review_rounds": [round_1]})
    dispatch.drain(_args(tmp_path), site)
    dispatch.drain(_args(tmp_path), site)
    assert site.posts == [] and len(notes) == 1 and "第 1 轮" in notes[0]
    assert _progress(tmp_path)[:2] == (1, 1)


def test_revision_after_the_answered_round_opens_the_next_round(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatch, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(dispatch, "ledger", lambda *a, **kw: None)
    monkeypatch.setattr(dispatch, "uploaded_reviews", lambda *a: "")
    round_1 = {"id": "round-1", "attempt_id": "attempt-1", "round_no": 1, "received_at": "2026-11-01T00:00:00+00:00",
               "response_submitted_at": "2026-11-10T00:00:00+00:00"}
    record(tmp_path, _event("revision_requested"), b"fixture")
    site = _Site({"paper_id": "test", "submission_attempts": [dict(ATTEMPT, status="resubmitted", current_round=1)],
                  "review_rounds": [round_1], "revision_requests": []})
    dispatch.drain(_args(tmp_path), site)
    ((path, kw),) = site.posts
    assert path.endswith("/review-rounds") and kw["json"]["round_no"] == 2


def test_hold_note_points_at_the_existing_attempt():
    hold = dispatch.AttemptHold("no attempt matches: 1a1b3ee6: already rejected; 5b225214: journal 'Other' not named")
    note = dispatch.hold_note({"decision": "submitted", "journal": "Synthetic Letters"}, hold)
    assert "已有本刊的投稿记录" in note and "1a1b3ee6: already rejected" in note and "not named" not in note
    fresh = dispatch.hold_note({"decision": "submitted"}, dispatch.AttemptHold(
        "no attempt matches: the paper has no submission attempt"))
    assert fresh.startswith("网站上没有") and "新建投稿记录" in fresh
