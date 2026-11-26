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
from datetime import datetime, timezone
from html.parser import HTMLParser
import fcntl
import tomllib
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit

import yaml


DECISIONS = (
    ("revision_requested", r"major revision|minor revision|revision requested|revise and resubmit|invite you to revise|revision invitation"),
    # 2026-11-26: Elsevier "will not be considered for publication" (JCTA), "was recently
    # rejected", "regret to inform you".
    ("rejected", r"decision of rejection|(?:has|have|was|were) (?:now |recently )?been rejected|unable to accept"
                 r"|reject(?:ion|ed)? decision|decline to publish|will not be considered for (?:publication|review)"
                 r"|regret to inform you|(?:cannot|can ?not|could not) (?:be )?(?:accept|publish|consider)"),
    # Only the journal accepting this paper: conditional and boilerplate phrases ("if it is
    # accepted for publication", "before the paper has been accepted") are removed first
    # (``decision_text``) and a bare "has been accepted" no longer counts (2026-11-26).
    ("accepted", r"(?<!not )(?<!not be )(?<!cannot be )(?<!can not be )(?<!not been )accepted for publication|(?:manuscript|paper|submission|article)[^.]{0,200}?"
                 r"\b(?:has|have) (?:now )?been (?:formally |provisionally )?accepted"
                 r"|(?:final )?acceptance of your (?:manuscript|paper|submission|article)"),
    ("proofs", r"page proofs|author proofs"),
    # Springer Nature SNAPP ("Your manuscript <title> has been submitted", subject "Track the
    # status of your manuscript") and co-author confirmations (Editorial Manager, 2026-11-26).
    ("submitted", r"submission confirmation|submission acknowledgement|acknowledg[e]?ment of submission|submission received"
                  r"|(?:manuscript|paper|submission|article)[^.]{0,200}?\bhas been (?:successfully )?submitted"
                  r"|track the status of your manuscript|confirm co-?authorship of (?:your |the |a )?submission"
                  r"|has listed you as a (?:contributing |co-?)author"),
)
# Letters about a paper that are not a decision on it: transfer offers after a rejection
# (the rejection letter itself is the event).
NOT_A_DECISION = re.compile(r"transfer (?:your manuscript|recommendation)|^a recommendation for\b", re.I)
# Publisher boilerplate appended to every letter; everything from here on is not about the paper.
BOILERPLATE = re.compile(r"at elsevier, we want to help all our authors|in compliance with data protection regulations", re.I)
# Conditions and templates that name an acceptance which has not happened.
CONDITIONAL = re.compile(
    r"\b(?:if|once|when|after|before|until|unless)\s+(?:it|(?:the|your|this)\s+(?:paper|manuscript|article|submission|work))\s+"
    r"(?:is|has been|was|gets)\s+(?:formally\s+)?accepted(?:\s+for\s+publication)?"
    r"|\b(?:up)?on acceptance\b|\bafter acceptance\b|\bif accepted\b", re.I)


def decision_text(text, title=""):
    """The letter text decisions are read from: publisher boilerplate cut, conditional
    acceptance phrases and the paper's own title removed, whitespace folded."""
    text = " ".join(str(text or "").split())
    cut = BOILERPLATE.search(text)
    if cut:
        text = text[:cut.start()]
    title = " ".join(str(title or "").split())
    if len(title) >= 12:
        text = re.sub(re.escape(title), "the title", text, flags=re.I)
    return CONDITIONAL.sub(" ", text)


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


def message_text(message):
    """(subject, plain body) of a parsed letter; HTML bodies are flattened with their links."""
    part = message.get_body(preferencelist=("plain", "html"))
    body = part.get_content() if part else ""
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
    return {"content": " ".join((subject + "\n" + body).casefold().split()),
            "addresses": {item.casefold() for item in addresses},
            "manuscript_id": manuscript_number(subject, body),
            "received_at": received_at.isoformat() if received_at else None}


def parse(raw, papers, log=None):
    """The event of one letter about one known paper, or None.

    ``log`` (optional) receives ``(reason, paper_ids)`` when a letter names a known paper but
    yields no event (ambiguous match, no decision, conflicting decisions, a transfer offer), so
    a letter that was read but not used shows in the service log instead of vanishing.
    """
    message = BytesParser(policy=policy.default).parsebytes(raw)
    mid = str(message.get("Message-ID", "")).strip()
    if not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", mid):
        return
    note = log or (lambda reason, paper_ids: None)
    subject, body = message_text(message)
    content = " ".join((subject + "\n" + body).casefold().split())
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
        matched = [n for n in numbers if n and (
            n.casefold() in labelled if not distinctive(n)
            else re.search(r"(?<![\w-])" + re.escape(n.casefold()) + r"(?![\w-])", content))]
        if len(matched) > 1:
            note(f"quotes {len(matched)} manuscript numbers of one paper", [entry.get("paper_id")])
            return
        title = " ".join(str(entry.get("title") or "").casefold().split())
        if matched or (len(title) >= 12 and title in content):
            matches.append((entry, matched[0] if matched else ""))
    if len(matches) != 1:
        if matches:
            note(f"ambiguous: matches {len(matches)} papers", [m[0].get("paper_id") for m in matches])
        return
    entry, number = matches[0]
    if NOT_A_DECISION.search(subject):
        note("not a decision (transfer offer)", [entry.get("paper_id")])
        return
    title = entry.get("title") or ""
    decisions = {name for name, pattern in DECISIONS if re.search(pattern, decision_text(subject, title), re.I)}
    if not decisions:
        decisions = {name for name, pattern in DECISIONS if re.search(pattern, decision_text(body, title), re.I)}
    if len(decisions) > 1:
        # Never choose between an acceptance and a refusal: the letter waits for a person.
        note("held: conflicting decisions " + "+".join(sorted(decisions)), [entry.get("paper_id")])
        return
    if not decisions:
        note("no decision recognised", [entry.get("paper_id")])
        return
    decision = decisions.pop()
    if not number:
        number = manuscript_number(subject, body)
    due = re.search(r"(?:due(?: date)?|deadline|submit by)\s*(?:is|on|by)?[ :]*(\d{4}-\d\d-\d\d|\d{1,2} [A-Za-z]+ \d{4}|[A-Za-z]+ \d{1,2},? \d{4})", body, re.I)
    due_date = None
    if due:
        for pattern in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
            try:
                due_date = datetime.strptime(due[1].replace(",", ""), pattern).date().isoformat()
                break
            except ValueError:
                pass
    comments = re.search(r"^(?:reviewer\s*#?\d+|comments to (?:the )?author[s]?)\s*[:\n]\s*(\S.*)", body, re.I | re.M | re.S)
    hosts = set()
    for link in re.findall(r'https?://[^\s<>"]+', body):
        try:
            host = urlsplit(link).hostname
        except ValueError:
            continue
        if host:
            hosts.add(host)
    header_date = message.get("Date")
    received_at = getattr(header_date, "datetime", None)
    round_match = re.search(r"\bround\s*[:#]?\s*(\d+)\b", subject, re.I)
    reviews = comments[0] if comments else ""
    incomplete = False
    for attachment in message.iter_attachments():
        mime = attachment.get_content_type()
        if mime == "text/plain":
            reviews += "\n" + attachment.get_content()
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
            entries.append({**paper, "numbers": list(journals), "attempt_journals": journals})
        for uid in sorted(map(int, rows[0].split())):
            status, data = mailbox.uid("fetch", str(uid), "(BODY.PEEK[])")
            if status != "OK":
                raise ValueError("IMAP fetch failed")
            for row in data:
                if isinstance(row, tuple):
                    def unused(reason, paper_ids, uid=uid):
                        # UID, paper and reason only: never the letter's text.
                        print("Journal letter not used", f"uid={uid}", ",".join(map(str, paper_ids)),
                              reason, flush=True)
                    event = parse(row[1], entries, log=unused)
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
    args = parser.parse_args()
    if args.interval_minutes < 1:
        parser.error("interval must be positive")
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
    lock = (args.state / "service.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (args.state / "service.pid").write_text(str(os.getpid()) + "\n")
    config = tomllib.loads((args.state.parent.parent / "openlabs.toml").read_text())
    credentials, error = _credentials_file_values(Path(config["program"]["credentials_file"]))
    if error:
        parser.error(error)
    args.loop = Path(__file__).resolve().parents[3] / "bin/openlabs-container-loop"
    api = ManageApiClient(credentials["ARA_PAPER_MANAGE_API_URL"], credentials["ARA_PAPER_MANAGE_API_KEY"])
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while not stop.is_set():
        try:
            try:
                poll(args, api)
            finally:
                drain(args, api)
            print(datetime.now(timezone.utc).isoformat(), "journal poll complete", flush=True)
        except (HandoffError, OSError, imaplib.IMAP4.error, ValueError, sqlite3.Error, KeyError, LookupError) as exc:
            print("Journal poll failed", type(exc).__name__, flush=True)
        stop.wait(args.interval_minutes * 60)


if __name__ == "__main__":
    main()
