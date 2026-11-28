"""Import journal correspondence into a private per-paper event journal."""
import argparse
import hashlib
import imaplib
import json
import os
import re
import signal
import sqlite3
import subprocess
import ssl
from threading import Event
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import fcntl
import tomllib
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

import yaml

from paper_writing import journal_triage


FORWARD_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd|aw|wg|sv|tr)\s*:|(?:转发|回复|答复)\s*[:：])\s*", re.I)
PAPER = r"(?:manuscript|paper|submission|article|contribution)"
DECISIONS = (
    ("revision_requested", r"major revision|minor revision|revision requested|revise and resubmit|invite you to revise"
                           r"|revision invitation|asked to revise"),
    # 2026-11-26: Elsevier "will not be considered for publication" (JCTA), "was recently
    # rejected", "regret to inform you". Audit 2026-11-26 (JOURNAL-MAIL-AUDIT.md C2/C6): Wiley
    # "unable to consider it further", APS "not suitable for", "fails to match the minimal
    # threshold", "does not meet our acceptance criteria", OJS "Decline submission" and "decided
    # not to proceed", IEEE "has not been recommended for publication", MDPI "Declined for
    # Publication" / "not be able to process your submission further", Hindawi "refused to
    # consider" / "unsuitable for publication", Neurocomputing "not appropriate for this
    # journal", Discrete Mathematics "very little chance of acceptance", Elsevier "other
    # journals that may better suit your work". Refusals need the paper as their object, so
    # "cannot accept electronic files" (SIAM) or "unable to accept payment" are no decision.
    ("rejected", r"decision of rejection|(?:has|have|was|were) (?:now |recently )?been rejected|reject(?:ion|ed)? decision"
                 r"|\b" + PAPER + r" (?:rejected|refused|declined)\b|declined? (?:for publication|submission)|initial decline"
                 r"|decline to publish|will not be considered for (?:publication|review)|refused to consider"
                 r"|regret to (?:inform|tell|advise) you|(?:cannot|can ?not|could not) be (?:accepted|published|considered|recommended)"
                 r"|will not be (?:accepted|considered|recommended)|\bnot (?:been )?selected for (?:publication|inclusion)"
                 r"|(?:cannot|can ?not|could not|unable to|not (?:be )?able to) (?:accept|publish|consider|process|proceed with|offer publication (?:of|for))"
                 r" (?:it|them|(?:your|this|the) (?:" + PAPER + r"s?|work))\b"
                 r"|decided not to (?:proceed|publish|accept|consider|pursue|send)|not (?:been )?recommended for publication"
                 r"|\b(?:is|are|was|be) (?:not |un)(?:suitable|appropriate) for\b"
                 r"|\bunsuitable for publication|fails? to (?:match|meet|reach) the (?:minimal |minimum )?(?:threshold|standards?|criteria)"
                 r"|(?:do|does|did) not (?:find that [^.]{0,80}?)?meets? (?:our|the) (?:acceptance |publication |editorial )?(?:criteria|standards?|threshold)"
                 r"|very little chance of acceptance|(?:other|alternative) journals? (?:that )?(?:may|might|would) better suit"),
    # Only the journal accepting this paper, said with the paper as its subject ("your manuscript
    # has now been accepted", "\"<title>\" has been accepted", "we are accepting your paper",
    # "acceptance of your manuscript"). A bare "accepted for publication" no longer counts in
    # the body (audit C1/C2: MSP's author declaration "has not already been published or accepted
    # for publication", arXiv "Comments: Accepted for publication in ..."); declarations,
    # conditions and templates are removed first (``decision_text``).
    ("accepted", PAPER + r"[^.]{0,200}?\b(?:has|have) (?:now )?been (?:formally |provisionally |finally )?accepted"
                 r"|(?:[\"”’']|\bthe title\b)\s*(?:has|have) (?:now )?been (?:formally |provisionally )?accepted"
                 r"|\baccepting your " + PAPER + r"|(?:final )?acceptance of your " + PAPER),
    # Proofs of the paper (ACM "PDF and HTML proofs", Springer "Proofs for your article", MDPI
    # "Final Proofreading"); a singular "proof" is mathematics, not production.
    ("proofs", r"(?:page|author|article|galley|pdf|html|typeset) proofs\b|\bproofs (?:of|for) your\b"
               r"|\bproofs (?:are|is) (?:now )?(?:available|ready|attached)|\bfinal proofreading\b"),
    # Springer Nature SNAPP ("Your manuscript <title> has been submitted", subject "Track the
    # status of your manuscript") and co-author confirmations (Editorial Manager, 2026-11-26).
    # Audit C7: Editorial Manager "Confirming your submission" / "has been received by",
    # Elsevier "Your submission has been received", MSP and OpenReview "has received your
    # submission", EasyChair "We received your submission", AIP "we received the manuscript" /
    # "Receipt of New Manuscript", Springer "Receipt of Manuscript", APS "acknowledge receipt",
    # and the confirmations of a revised manuscript (dispatch turns these into "resubmitted").
    ("submitted", r"submission confirmation|submission acknowledgement|acknowledg[e]?ment of submission|submission received"
                  r"|" + PAPER + r"[^.]{0,200}?\bhas been (?:successfully )?(?:submitted|received)\b(?! from)"
                  r"|track the status of your (?:manuscript|submission)|confirm co-?authorship of (?:your |the |a )?submission"
                  r"|has listed you as a (?:contributing |co-?)author|confirming your submission"
                  r"|has received your (?:submission|manuscript|paper|article)|\bwe (?:have )?received your (?:revised )?(?:submission|manuscript|paper)"
                  r"|\bwe (?:have )?received (?:the|a revised version of the) manuscript|acknowledge (?:the )?receipt of (?:this|your|the) "
                  + PAPER + r"|(?<!confirming )\breceipt of (?:your |the )?(?:new |revised )?(?:manuscript|paper|submission)"
                  r"|editorial acknowledg[e]?ment|a manuscript number has been assigned|submission ?received"
                  r"|reference number for your (?:manuscript|paper) is"
                  r"|resubmitting the (?:modified|revised) version|revised version (?:of your paper )?received|manuscript resubmitted"
                  r"|confirmation of revision received|providing the revised version|received your revised submission"),
)
# Letters about a paper that are not a decision on it: transfer offers after a rejection
# (the rejection letter itself is the event). Read after any forward/reply prefix (audit C2).
NOT_A_DECISION = re.compile(r"transfer (?:your manuscript|recommendation)|^(?:reminder:\s*)?a recommendation for\b"
                            r"|\btransfer (?:confirmed|completed?|not completed|request)\b|\bconfirm transfer\b", re.I)
# Publisher boilerplate appended to every letter; everything from here on is not about the paper.
BOILERPLATE = re.compile(r"at elsevier, we want to help all our authors|in compliance with data protection regulations"
                         r"|disclaimer: mdpi recognizes|young investigator award|travel award application", re.I)
# Conditions and templates that name an acceptance which has not happened.
CONDITIONAL = re.compile(
    r"\b(?:if|once|when|after|before|until|unless)\s+(?:it|(?:the|your|this)\s+(?:paper|manuscript|article|submission|work))\s+"
    r"(?:is|has been|was|gets)\s+(?:formally\s+)?accepted(?:\s+for\s+publication)?"
    # Audit C1/C2: "If you transfer ... and your paper is accepted", "Once accepted for
    # publication, we aim", "should it be accepted" (SIAM), "provided that ... accepted".
    r"|\b(?:if|once(?! again)|unless|should|provided(?: that)?|whether|in case)\b[^.;]{0,160}?\baccept(?:ed|ance)\b"
    r"|\b(?:up)?on acceptance\b|\bafter acceptance\b|\bif accepted\b|\bonce accepted\b"
    r"|\b(?:will|when)\b[^.;]{0,80}?\bproofs\b", re.I)
# Phrases that mention a decision without making one: author declarations ("has not already
# been published or accepted for publication", "has not been accepted ... elsewhere"), an
# abstract-only presentation of a declined full paper (ICONIP), and "cannot be accepted in its
# present form", which belongs to a revision decision.
NOT_DECIDED = re.compile(
    r"\b(?:published|submitted) (?:or|nor) accepted\b(?: for publication)?|\bnot (?:already |previously |yet )?been accepted\b[^.]{0,80}?\belsewhere"
    r"|\bunder (?:active )?consideration (?:for publication )?elsewhere\b|\baccept(?:ed|ance)\b[^.]{0,60}?\bfor (?:an? )?(?:abstract|poster)\b"
    r"|\bcannot be accepted (?:for publication )?in its (?:present|current) form", re.I)


# A subject may announce the acceptance without naming the paper ("<journal> - Accepted for
# Publication"); in a body that phrase is too often a declaration or a quotation.
SUBJECT_ACCEPTED = re.compile(r"(?<!not )(?<!be )(?<!not been )\baccepted for publication\b", re.I)


def decision_text(text, title=""):
    """The letter text decisions are read from: publisher boilerplate cut, declarations,
    conditional acceptance phrases and the paper's own title removed, whitespace folded."""
    text = " ".join(str(text or "").split())
    cut = BOILERPLATE.search(text)
    if cut:
        text = text[:cut.start()]
    title = " ".join(str(title or "").split())
    if len(title) >= 12:
        text = re.sub(re.escape(title), "the title", text, flags=re.I)
    return CONDITIONAL.sub(" ", NOT_DECIDED.sub(" ", text))


def classify(subject, body, title=""):
    """The decisions a letter states: the subject (after any forward or reply prefix) first,
    the body if the subject names none. ``None`` for a transfer offer, which is not a decision."""
    while FORWARD_PREFIX.search(subject or ""):
        subject = FORWARD_PREFIX.sub("", subject, count=1)
    if NOT_A_DECISION.search(subject or ""):
        return None
    found = {name for name, pattern in DECISIONS if re.search(pattern, decision_text(subject, title), re.I)}
    if SUBJECT_ACCEPTED.search(subject or ""):
        found.add("accepted")
    if not found:
        found = {name for name, pattern in DECISIONS if re.search(pattern, decision_text(body, title), re.I)}
    return found


def distinctive(number):
    """A manuscript number that can identify a paper anywhere in a letter: a UUID, or at least
    six characters with a letter or separator besides digits. Short conference numbers
    ("24", "25") also occur as dates and phrases ("talk 24/7", "25 Nov 2026")."""
    number = str(number or "")
    return bool(re.fullmatch(UUID, number, re.I)) or (
        len(number) >= 6 and bool(re.search(r"\d", number)) and bool(re.search(r"[A-Za-z./-]", number)))


def catalog(root):
    papers = []
    for path in sorted((root / "registry/papers").glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())
        if entry.get("delivery") or entry.get("external_publication"):
            papers.append(entry)
    return papers


class HtmlText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "div", "p", "li"}:
            self.parts.append("\n")
        if tag == "a":
            self.parts.append(" " + dict(attrs).get("href", "") + " ")


UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# A labelled number: "Manuscript ID: X", "Manuscript number is X", "Ms. No. X",
# "Submission ID <uuid>" (Springer SNAPP), "The submission ID is: JOAA-D-26-00471"
# (Editorial Manager), "Paper #123", "Tracking number X" (Nature).
LABELLED_NUMBER = re.compile(
    r"(?:\b(?:manuscript|submission|paper|article)\s+(?:ID|number|no\.?|#|reference(?:\s+number)?|"
    r"tracking\s+number)|\bms\.?\s*no\.?|\btracking\s+number|\bref(?:erence)?\s*(?:no\.?|number)?\s*[.:])"
    r"(?:\s+is)?\s*[:#]?\s*(?P<id>" + UUID + r"|[A-Za-z0-9][\w.-]*\d[\w.-]*)", re.I)
# Unlabelled numbers by their system's shape, most specific first.
SHAPED_NUMBERS = (
    re.compile(r"\b[A-Z][A-Z0-9]{1,11}-D-\d{2}-\d{3,6}(?:R\d{1,2})?\b"),  # Editorial Manager
    # ScholarOne (TNNLS-2026-P-12345, MNRAS-26-1234.R1) and Nature (NCOMMS-26-12345-T, NATASTRON-26-01234A)
    re.compile(r"\b[A-Z][A-Za-z]{1,11}-(?:19|20)?\d{2}-(?:[A-Z]{1,3}-)?\d{3,6}(?:\.R\d{1,2}|[A-Z]\b|-[A-Z]{1,2}\b)?"),
)
LEGACY_SUBJECT_NUMBER = re.compile(r"\b([A-Z]{2,12}-[A-Z0-9]{1,8}-[\w.-]*\d[\w.-]*)\b")


def manuscript_number(subject, body):
    """The journal's manuscript number quoted in a letter, or ``""``.

    Labelled numbers win over shaped ones, and the subject over the body. Covers Springer's
    "Submission ID <uuid>", Editorial Manager / Elsevier ``JOAA-D-26-00471``, ScholarOne
    ``ABC-2026-0123.R1``, Nature ``NCOMMS-26-12345`` and generic "Manuscript ID/number".
    """
    for text in (subject, body):
        found = LABELLED_NUMBER.search(text or "")
        if found:
            return found["id"].rstrip(".-")
        for shape in SHAPED_NUMBERS:
            found = shape.search(text or "")
            if found:
                return found[0].rstrip(".-")
    found = LEGACY_SUBJECT_NUMBER.search(subject or "")
    return found[1].rstrip(".") if found else ""


def part_text(part):
    """The text of a MIME part; an unknown or broken charset is decoded with replacement
    characters instead of raising (audit C3: one such letter stopped the mailbox cursor)."""
    try:
        return part.get_content()
    except (LookupError, UnicodeError, ValueError, AssertionError):
        payload = part.get_payload(decode=True)
        return payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload or "")


def message_text(message):
    """(subject, plain body) of a parsed letter; HTML bodies are flattened with their links."""
    part = message.get_body(preferencelist=("plain", "html"))
    body = part_text(part) if part else ""
    if part and part.get_content_subtype() == "html":
        reader = HtmlText()
        reader.feed(body)
        body = "".join(reader.parts)
    return str(message.get("Subject", "")), body


def mail_context(raw):
    """What attempt matching may read of a stored original: the folded text, the addresses
    it names (headers and body), the quoted manuscript number and the received time."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    subject, body = message_text(message)
    addresses = set()
    for header in ("To", "Cc", "Delivered-To", "X-Original-To"):
        for value in message.get_all(header, []):
            addresses.update(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(value)))
    addresses.update(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", body))
    header_date = message.get("Date")
    received_at = getattr(header_date, "datetime", None)
    content = " ".join((subject + "\n" + body).casefold().split())
    return {"content": content, "journal_content": journal_text(content),
            "addresses": {item.casefold() for item in addresses},
            "manuscript_id": manuscript_number(subject, body),
            "received_at": received_at.isoformat() if received_at else None}


DATE = r"(\d{4}-\d\d-\d\d|\d{1,2}[ -][A-Za-z]{3,9}\.?[ -]\d{4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4})"
# A due date is read only where the letter speaks of the revision's deadline, never from
# announcements under the letter (MDPI "Nomination deadline: 31 December 2025", "Travel Award
# Application deadline", "Submit your abstract by ...": audit C4).
DUE_CUE = re.compile(r"revis|resubmi|deadline|\bdue\b|final version|return", re.I)
DUE_NOISE = re.compile(r"award|nominat|abstract|conference|registration|application|webinar|special issue|prize"
                       r"|travel|call for|workshop|symposium|congress|discount|voucher|newsletter|survey", re.I)
DUE_AT = re.compile(r"(?:due(?: date)?|deadline|by|before|on or before|no later than)\s*(?:is|on|by)?[ :]*" + DATE, re.I)


def _date(text):
    text = text.replace(",", "").replace(".", "").replace("-", " ") if not re.fullmatch(r"\d{4}-\d\d-\d\d", text) else text
    for pattern in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    return None


def revision_due(subject, body, received_at=None):
    """The revision's due date (ISO) stated in the decision itself, or ``None`` ("待核实").

    Read in order: the subject ("Major Revision - Due Date 4 September", the year from the
    letter's date), a sentence of the letter about the revision or its deadline ("Deadline: 27
    Jul 2026", "returned to the Editors by 15-Dec-2025", "due Dec 08, 2026"), then "within N
    days" counted from the letter's date. Announcements, awards and calls are skipped; nothing
    is guessed when none of these is found."""
    found = re.search(r"\bdue(?: date)?\s*[: ]\s*(\d{1,2}) ([A-Za-z]{3,9})\b(?!\s*,?\s*\d{4})", subject or "", re.I)
    if found and received_at:
        for year in (received_at.year, received_at.year + 1):
            day = _date(f"{found[1]} {found[2]} {year}")
            if day and day >= received_at.date():
                return day.isoformat()
    for text in (subject, body):
        text = " ".join(str(text or "").split())
        cut = BOILERPLATE.search(text)
        if cut:
            text = text[:cut.start()]
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if not DUE_CUE.search(sentence) or DUE_NOISE.search(sentence):
                continue
            for match in DUE_AT.finditer(sentence):
                day = _date(match[1])
                if day:
                    return day.isoformat()
    within = re.search(r"\b(?:revis|resubmi|upload|return)[^.]{0,120}?\bwithin (\d{1,3}) (day|week)s?\b", " ".join(str(body or "").split()), re.I)
    if within and received_at:
        days = int(within[1]) * (7 if within[2].lower() == "week" else 1)
        return (received_at + timedelta(days=days)).date().isoformat()
    return None


class Unused(NamedTuple):
    """A letter that was read but gave no event: the exits a person reviews.

    ``kind`` is one of ``parse_failed``, ``no_message_id``, ``unmatched``, ``ambiguous``,
    ``many_numbers``, ``transfer``, ``conflict``, ``no_decision``; ``paper_ids`` are the
    candidate papers, ``decisions`` the candidate decisions, and ``review`` says whether the
    letter goes into the digest for a person (decision-like letters only; a transfer offer or an
    unrelated letter is logged, not reviewed)."""
    kind: str
    reason: str
    paper_ids: tuple = ()
    decisions: tuple = ()
    review: bool = False


# Words of a letter that reads like an editorial decision although none was recognised.
DECISION_CUE = re.compile(r"decision|accept|reject|revis|declin|outcome|withdraw|regret|unfortunately"
                          r"|congratulat|not (?:be )?(?:able|suitable)|proofs", re.I)
OWN_NOTIFICATION = re.compile(r"<openlabs-[^@>]*@", re.I)
# Where a letter starts listing other journals (transfer offers): journal names after this are
# not the journal that wrote (audit C9).
TRANSFER_SECTION = re.compile(
    r"article transfer service|transfer (?:offer|your manuscript|network|desk)|alternative journals?|suggested journals?"
    r"|sister journals?|journals? (?:we|i) recommend|(?:recommend|suggest)(?:ed)? (?:the following |other |alternative )?journals?"
    r"|may better suit", re.I)
# MSP EditFlow numbers ("261010-Chen", "260907-Chen-3") are dates plus a name: unique within one
# journal only (audit C9, CPC and Acta Arithmetica shared "261010-Chen").
JOURNAL_SCOPED_NUMBER = re.compile(r"\d{6}-[A-Za-z][\w-]*")


def journal_key(name):
    """A journal name folded for comparison: letters and digits only, without a leading "the"."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").casefold()).removeprefix("the")


def journal_text(content):
    """The folded letter up to any list of other journals it recommends."""
    cut = TRANSFER_SECTION.search(content or "")
    return content[:cut.start()] if cut else (content or "")


def parse(raw, papers, log=None):
    """The event of one letter about one known paper, or None.

    ``log`` (optional) receives an :class:`Unused` for every letter that yields no event
    (unmatched, ambiguous, no decision, conflicting decisions, a transfer offer), so a letter
    that was read but not used shows in the service log, and a decision-like one reaches a
    person, instead of vanishing.
    """
    message = BytesParser(policy=policy.default).parsebytes(raw)
    note = log or (lambda unused: None)
    mid = str(message.get("Message-ID", "")).strip()
    if OWN_NOTIFICATION.match(mid):
        return  # the service's own notification to a handler
    subject, body = message_text(message)
    letter = classify(subject, body)
    letter = tuple(sorted(letter or ()))
    looks_decided = bool(set(letter) - {"submitted"}) or (not letter and bool(DECISION_CUE.search(subject)))
    if not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", mid):
        note(Unused("no_message_id", "no valid Message-ID", (), letter, bool(letter)))
        return
    content = " ".join((subject + "\n" + body).casefold().split())
    named = journal_key(journal_text(content))
    # A short number ("24") identifies a paper only where the letter labels it as the
    # manuscript number ("Paper #24", "Submission ID: 24"), not anywhere in the text.
    labelled = {found["id"].rstrip(".-").casefold() for text in (subject, body)
                for found in LABELLED_NUMBER.finditer(text or "")}
    matches = []
    for entry in papers:
        publication = entry.get("external_publication") or {}
        numbers = set(entry.get("numbers") or [])
        if publication.get("external_manuscript_id"):
            numbers.add(str(publication["external_manuscript_id"]))
        journals = entry.get("attempt_journals") or {}
        matched = [n for n in numbers if n and (
            n.casefold() in labelled if not distinctive(n)
            else re.search(r"(?<![\w-])" + re.escape(n.casefold()) + r"(?![\w-])", content))
            # A journal-scoped number counts only in a letter of that journal.
            and not (JOURNAL_SCOPED_NUMBER.fullmatch(n) and journals.get(n)
                     and journal_key(journals[n]) not in named)]
        if len(matched) > 1:
            note(Unused("many_numbers", f"quotes {len(matched)} manuscript numbers of one paper",
                        (entry.get("paper_id"),), letter, True))
            return
        title = " ".join(str(entry.get("title") or "").casefold().split())
        if matched or (len(title) >= 12 and title in content):
            matches.append((entry, matched[0] if matched else ""))
    if len(matches) > 1 and len([m for m in matches if m[1]]) == 1:
        # The paper whose manuscript number the letter quotes wins over title-only matches.
        matches = [m for m in matches if m[1]]
    if len(matches) != 1:
        if matches:
            note(Unused("ambiguous", f"ambiguous: matches {len(matches)} papers",
                        tuple(m[0].get("paper_id") for m in matches), letter, bool(letter) or looks_decided))
        else:
            note(Unused("unmatched", "matches no paper", (), letter, looks_decided))
        return
    entry, number = matches[0]
    paper_ids = (entry.get("paper_id"),)
    title = entry.get("title") or ""
    decisions = classify(subject, body, title)
    if decisions is None:
        note(Unused("transfer", "not a decision (transfer offer)", paper_ids))
        return
    if len(decisions) > 1:
        # Never choose between an acceptance and a refusal: the letter waits for a person.
        note(Unused("conflict", "held: conflicting decisions " + "+".join(sorted(decisions)), paper_ids,
                    tuple(sorted(decisions)), True))
        return
    if not decisions:
        note(Unused("no_decision", "no decision recognised", paper_ids, (),
                    bool(DECISION_CUE.search(subject))))
        return
    decision = decisions.pop()
    if not number:
        number = manuscript_number(subject, body)
    header_date = message.get("Date")
    received_at = getattr(header_date, "datetime", None)
    due_date = revision_due(subject, body, received_at)
    comments = re.search(r"^(?:reviewer\s*#?\d+|comments to (?:the )?author[s]?)\s*[:\n]\s*(\S.*)", body, re.I | re.M | re.S)
    hosts = set()
    for link in re.findall(r'https?://[^\s<>"]+', body):
        try:
            host = urlsplit(link).hostname
        except ValueError:
            continue
        if host:
            hosts.add(host)
    round_match = re.search(r"\bround\s*[:#]?\s*(\d+)\b", subject, re.I)
    reviews = comments[0] if comments else ""
    incomplete = False
    for attachment in message.iter_attachments():
        mime = attachment.get_content_type()
        if mime == "text/plain":
            reviews += "\n" + part_text(attachment)
        elif mime == "application/pdf":
            try:
                result = subprocess.run(["pdftotext", "-", "-"], input=attachment.get_payload(decode=True),
                                        capture_output=True, timeout=20, check=True,
                                        env={"PATH": os.environ.get("PATH", "/usr/bin")})
                extracted = result.stdout.decode().strip()
                if extracted:
                    reviews += "\n" + extracted
                else:
                    incomplete = True
            except (OSError, subprocess.SubprocessError, UnicodeError):
                incomplete = True
        elif not mime.startswith("image/"):
            incomplete = True
    reviews = re.sub(r'https?://[^\s<>"]+', "[portal link omitted]", reviews).strip()
    if incomplete or re.fullmatch(r"(?:reviewer\s*#?\d+|comments to (?:the )?authors?)\s*:\s*"
                                  r"(?:please )?(?:see|visit|download|view|access)?[^.\n]{0,55}"
                                  r"\[portal link omitted\][.! ]*", reviews, re.I):
        reviews = ""
    if reviews and not re.search(r"[a-zA-Z\u4e00-\u9fff]{3,}", reviews.split(":", 1)[-1].replace("[portal link omitted]", "")):
        reviews = ""
    grade = "major_revision" if "major revision" in content else "minor_revision" if "minor revision" in content else "revise_resubmit"
    return dict(received_at=received_at.isoformat() if received_at else None,
                round=int(round_match[1]) if round_match else None, revision_grade=grade, message_key=hashlib.sha256(mid.encode()).hexdigest(), paper_id=entry["paper_id"],
                journal=(entry.get("attempt_journals") or {}).get(number) or entry.get("target_journal") or (entry.get("external_publication") or {}).get("venue"),
                manuscript_id=number, decision=decision, due=due_date,
                reviewer_comments=reviews or None, portal_hosts=sorted(hosts),
                action=("prepare_revision" if reviews else "upload_reviews") if decision == "revision_requested" else "verify_status")


def record(directory, event, raw):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ValueError("Private journal directory requires mode 0700")
    with sqlite3.connect(directory / "events.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS events (message_key TEXT PRIMARY KEY, paper_id TEXT, payload TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS originals (message_key TEXT PRIMARY KEY, raw BLOB NOT NULL)")
        inserted = db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?)",
                              (event["message_key"], event["paper_id"], json.dumps(event))).rowcount
        # Backfill a legacy event only if the same paper and parsed event match.
        db.execute("INSERT OR IGNORE INTO originals SELECT message_key, ? FROM events "
                   "WHERE message_key=? AND paper_id=? AND payload=?",
                   (raw, event["message_key"], event["paper_id"], json.dumps(event)))
        return bool(inserted)


REVIEW_TABLE = ("CREATE TABLE IF NOT EXISTS review (key TEXT PRIMARY KEY, kind TEXT, reason TEXT, paper_ids TEXT, "
                "decisions TEXT, subject TEXT, sender TEXT, received_at TEXT, notified INTEGER DEFAULT 0)")
# Columns of the model reading (journal_triage; 2026-11-26), added to an older table in place:
# the redacted brief, the state (NULL none, pending, dispatched, done, failed, expired), the
# model's raw answer, the orchestrator task that carries it, when the letter was queued, and
# whether the paper's submitter was told (0 no, 1 yes, -1 the send failed).
REVIEW_MODEL_COLUMNS = (("brief", "TEXT"), ("model_state", "TEXT"), ("model", "TEXT"), ("model_task", "TEXT"),
                        ("queued_at", "TEXT"), ("handler_notified", "INTEGER DEFAULT 0"))


def review_table(db):
    """Create the review table, or add the model-reading columns to an older one."""
    db.execute(REVIEW_TABLE)
    present = {row[1] for row in db.execute("PRAGMA table_info(review)")}
    for name, kind in REVIEW_MODEL_COLUMNS:
        if name not in present:
            db.execute(f"ALTER TABLE review ADD COLUMN {name} {kind}")


def headers(raw):
    """(subject, sender, received ISO time) of a letter for the review digest; never raises."""
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
        moment = getattr(message.get("Date"), "datetime", None)
        return (str(message.get("Subject", ""))[:300], str(message.get("From", ""))[:200],
                moment.isoformat() if moment else None)
    except Exception:  # a header the parser cannot read still leaves the UID to report
        return ("", "", None)


def record_review(directory, key, unused, raw=b"", papers=(), triage=False):
    """Queue one letter for the person's review digest (once per key); see :class:`Unused`.

    With ``triage`` (``[program] journal_mail_model_review``) a letter of a kind the model reads
    also keeps its redacted brief and waits for the model (journal_triage); a letter whose brief
    cannot be built goes to the digest as before."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ValueError("Private journal directory requires mode 0700")
    subject, sender, received = headers(raw)
    letter = None
    if triage and unused.kind in journal_triage.TRIAGE_KINDS:
        try:
            letter = journal_triage.brief(raw, unused, papers)
        except Exception as exc:  # an unreadable letter is still reported, without a model reading
            print("Journal letter brief failed", key, type(exc).__name__, flush=True)
    with sqlite3.connect(directory / "events.sqlite") as db:
        review_table(db)
        return bool(db.execute("INSERT OR IGNORE INTO review(key, kind, reason, paper_ids, decisions, subject, sender, "
                               "received_at, brief, model_state, queued_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (key, unused.kind, unused.reason[:500], json.dumps(list(unused.paper_ids)),
                                json.dumps(list(unused.decisions)), subject, sender, received,
                                json.dumps(letter, ensure_ascii=False) if letter else None,
                                "pending" if letter else None,
                                datetime.now(timezone.utc).isoformat())).rowcount)


def triage_enabled(settings_file):
    """``[program] journal_mail_model_review`` of the instance (read every round; off on error)."""
    try:
        program = tomllib.loads(Path(settings_file).read_text()).get("program") or {}
    except (OSError, ValueError):
        return False
    return program.get("journal_mail_model_review") is True


def read_letter(args, uid, raw, entries):
    """The event of the letter at ``uid`` (or None), with every letter that yields none logged
    and, when it reads like a decision, queued for review. A letter the parser fails on is
    reported the same way instead of stopping the cursor (audit C3)."""
    def unused(item):
        # UID, kind, papers and decisions only: never the letter's text.
        print("Journal letter not used", f"uid={uid}", item.kind, ",".join(map(str, item.paper_ids)),
              "+".join(item.decisions), item.reason, flush=True)
        if item.review:
            record_review(args.state, f"uid:{uid}", item, raw, entries, getattr(args, "triage", False))
    try:
        return parse(raw, entries, log=unused)
    except sqlite3.Error:
        raise
    except Exception as exc:  # any failure of one letter must not stop the mailbox
        unused(Unused("parse_failed", f"parse failed: {type(exc).__name__}", (), (), True))
        return None


def poll(args, api):
    with imaplib.IMAP4_SSL("imap.qiye.163.com", timeout=20, ssl_context=ssl.create_default_context()) as mailbox:
        mailbox.login(args.account, os.environ["SDJU_MAIL_PASSWORD"])
        if mailbox.select("INBOX", readonly=True)[0] != "OK":
            raise ValueError("INBOX unavailable")
        validity = int(mailbox.response("UIDVALIDITY")[1][0])
        next_uid = int(mailbox.response("UIDNEXT")[1][0])
        cursor = args.state / "cursor.json"
        previous = json.loads(cursor.read_text()) if cursor.exists() else {}
        def checkpoint(uid):
            temporary = cursor.with_suffix(".tmp")
            temporary.write_text(json.dumps({"uidvalidity": validity, "uid": uid}))
            temporary.replace(cursor)
        if not previous:
            checkpoint(next_uid - 1)
            print("Journal mailbox baseline established", flush=True)
            return
        if previous["uidvalidity"] != validity:
            raise ValueError("UIDVALIDITY changed; reconcile mailbox cursor")
        if previous["uid"] >= next_uid - 1:
            return
        status, rows = mailbox.uid("search", None, "UID", f"{previous['uid']+1}:{next_uid-1}")
        if status != "OK":
            raise ValueError("IMAP search failed")
        known = {}
        for paper in api._request("GET", "/v1/papers"):
            known[paper["paper_id"]] = paper
        # Manuscript numbers belong to attempts; the list projection has titles only.
        entries = []
        for paper in known.values():
            detail = api._request("GET", "/v1/papers/" + paper["paper_id"], allow_not_found=True)
            attempts = (detail or {}).get("submission_attempts", [])
            journals = {str(a["manuscript_number"]): a["journal_name"] for a in attempts if a.get("manuscript_number")}
            entries.append({**paper, "numbers": list(journals), "attempt_journals": journals,
                            "attempts": [{"journal": a.get("journal_name"), "manuscript_number": a.get("manuscript_number"),
                                          "status": a.get("status")} for a in attempts]})
        for uid in sorted(map(int, rows[0].split())):
            status, data = mailbox.uid("fetch", str(uid), "(BODY.PEEK[])")
            if status != "OK":
                raise ValueError("IMAP fetch failed")
            for row in data:
                if isinstance(row, tuple):
                    event = read_letter(args, uid, row[1], entries)
                    if event:
                        record(args.state, event, row[1])
            checkpoint(uid)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--eml", type=Path)
    source.add_argument("--account")
    parser.add_argument("--interval-minutes", type=int, default=20)
    parser.add_argument("--assignment-notifications", choices=("dry-run", "send"))
    parser.add_argument("--paper-id", action="append", default=[])

    args = parser.parse_args()
    if args.interval_minutes < 1:
        parser.error("interval must be positive")
    if (args.assignment_notifications and not args.account
            or args.paper_id and args.assignment_notifications != "send"):
        parser.error("Assignment notifications require --account; --paper-id requires send mode")
    if args.eml:
        raw = args.eml.read_bytes()
        event = parse(raw, catalog(args.root))
        print("recorded" if event and record(args.state, event, raw) else "duplicate or unmatched")
        return
    from paper_writing.deliverable import orchestrator_module
    _credentials_file_values = orchestrator_module("program_autonomy")._credentials_file_values
    from paper_writing.handoff import ManageApiClient, HandoffError
    from paper_writing.journal_dispatch import drain
    args.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.state.stat().st_mode & 0o077:
        parser.error("Private state directory requires mode 0700")
    from paper_writing.assignment_notifications import reconcile
    settings_file = args.state.parent.parent / "openlabs.toml"
    config = tomllib.loads(settings_file.read_text())
    credentials, error = _credentials_file_values(Path(config["program"]["credentials_file"]))
    if error:
        parser.error(error)
    args.loop = Path(__file__).resolve().parents[3] / "bin/openlabs-container-loop"
    api = ManageApiClient(credentials["ARA_PAPER_MANAGE_API_URL"], credentials["ARA_PAPER_MANAGE_API_KEY"])
    if args.assignment_notifications:
        try:
            ok = reconcile(api, args.state, args.account,
                           dry_run=args.assignment_notifications == "dry-run", paper_ids=args.paper_id)
        except (HandoffError, OSError, ValueError, sqlite3.Error, LookupError) as exc:
            print("Assignment notification run failed", type(exc).__name__, flush=True)
            ok = False
        finally:
            api.close()
        raise SystemExit(0 if ok else 1)
    lock = (args.state / "service.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (args.state / "service.pid").write_text(str(os.getpid()) + "\n")
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while not stop.is_set():
        args.triage = triage_enabled(settings_file)
        try:
            try:
                poll(args, api)
            finally:
                drain(args, api)
            print(datetime.now(timezone.utc).isoformat(), "journal poll complete", flush=True)
        except (HandoffError, OSError, imaplib.IMAP4.error, ValueError, sqlite3.Error, KeyError, LookupError) as exc:
            print("Journal poll failed", type(exc).__name__, flush=True)
        try:
            reconcile(api, args.state, args.account)
        except (HandoffError, OSError, ValueError, sqlite3.Error, LookupError) as exc:
            print("Assignment notification run failed", type(exc).__name__, flush=True)
        stop.wait(args.interval_minutes * 60)


if __name__ == "__main__":
    main()
