"""Dispatch matched private journal messages using the current Manage assignment."""
import hashlib
import json
import os
import re
import smtplib
import sqlite3
import ssl
import subprocess
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import parseaddr

from paper_writing.handoff import HandoffError
from paper_writing.journal_mail import REVIEW_TABLE, journal_key as _key


def ledger(args, event, extra=()):
    command = [str(args.loop), "--instance-dir", str(args.state.parent.parent), "cli", "--",
               "program", "journal-event", "--paper-id", event["paper_id"],
               "--message-key", event["message_key"], "--status", event["decision"],
               "--manuscript-id", event["manuscript_id"]]
    if event["due"]:
        command.extend(["--due", event["due"]])
    child_env = {k: v for k, v in os.environ.items() if k != "SDJU_MAIL_PASSWORD"}
    subprocess.run(command + list(extra), env=child_env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)


SMTP_SIZE_LIMIT = 20_000_000


def notify(api, paper, event, account, before_send=lambda: None, *, raw=None, note=""):
    assigned = {a["submitter_id"] for a in paper.get("assignments", []) if a.get("active")}
    if len(assigned) != 1:
        raise ValueError("Missing unique active assignment")
    users = api._request("GET", "/v1/users")
    emails = [u.get("email") for u in users if u["id"] in assigned and u.get("active")]
    if len(emails) != 1 or not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+", (emails[0] or "")):
        raise ValueError("Missing handler address")
    if parseaddr(emails[0])[1] != emails[0]:
        raise ValueError("Invalid handler mailbox")
    message = EmailMessage()
    message["From"], message["To"] = account, emails[0]
    message["Message-ID"] = "<openlabs-" + event["message_key"] + "@sdju.edu.cn>"
    message["Subject"] = "投稿待办 · " + paper["paper_id"]
    actions = {"upload_reviews": "请从期刊系统下载全部审稿意见，在管理网站上传至本轮返修。",
               "prepare_revision": "请在管理网站跟踪返修，审阅新版及逐点回复后确认提交。",
               "verify_status": "请在管理网站核对期刊状态、稿号与回执。"}
    summary = (f"{paper['title']}\n稿号 {event['manuscript_id']}\n"
               f"状态 {event['decision']}\n期限 {event['due'] or '待核实'}\n{actions[event['action']]}"
               + (f"\n{note}" if note else ""))

    def summary_only(*, oversized):
        if oversized:
            print("Journal original exceeds SMTP size", event["message_key"][:12], flush=True)
            hint = "原件过大，请登录 SDJU 邮箱查看"
        else:
            hint = "原件未归档，请登录 SDJU 邮箱查看"
        message.clear_content()
        message.set_content(summary + "\n" + hint)
        if oversized:
            message.add_attachment(summary, filename="summary.txt")
        return message.as_bytes(policy=SMTP)

    with smtplib.SMTP_SSL("smtp.qiye.163.com", timeout=15, context=ssl.create_default_context()) as smtp:
        smtp.login(account, os.environ["SDJU_MAIL_PASSWORD"])
        advertised = smtp.esmtp_features.get("size", "").strip()
        limit = SMTP_SIZE_LIMIT
        if re.fullmatch(r"[0-9]{1,20}", advertised) and int(advertised):
            limit = int(advertised)
        attached = False
        if raw is not None and len(raw) < limit:
            message.set_content(summary)
            # Splice the original into the generated MIME envelope without parsing or refolding it.
            marker = b"OPENLABS-JOURNAL-ORIGINAL"
            message.add_attachment(marker, maintype="message", subtype="rfc822",
                                   cte="8bit", filename="original.eml")
            envelope = message.as_bytes(policy=SMTP)
            prefix, suffix = envelope.rsplit(marker, 1)
            wire = prefix + raw + suffix
            attached = len(wire) <= limit
        if not attached:
            wire = summary_only(oversized=raw is not None)
        before_send()
        try:
            smtp.sendmail(account, emails, wire)
        except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
            if not attached or exc.smtp_code != 552:
                raise
            # A definitive rejection permits a summary retry without duplicate delivery.
            smtp.sendmail(account, emails, summary_only(oversized=True))


def uploaded_reviews(api, paper, round_id, directory):
    artifacts = [a for a in paper.get("artifacts", []) if a.get("review_round_id") == round_id
                 and a.get("kind") in {"decision_letter", "reviewer_report", "reviewer_comments"}
                 and a.get("status") in {"ready", "uploaded", "available", "complete", "completed"}]
    texts = []
    for item in artifacts:
        digest = item.get("sha256", "")
        if not re.fullmatch("[a-f0-9]{64}", digest):
            raise ValueError("Missing review checksum")
        path = directory / (digest + ".attachment")
        if not path.exists():
            response = api._request("GET", f"/v1/artifacts/{item['id']}/download")
            transfer = response.get("download", response)
            url = transfer.get("signed_url") or transfer.get("signedUrl") or transfer.get("fullSignedURL") or transfer.get("url")
            if not url or not url.startswith("https://"):
                raise ValueError("Missing signed review URL")
            subprocess.run(["/workspace/.download-bridge/download-submit", "--url", url,
                            "--output", str(path), "--route", "auto", "--sha256", digest,
                            "--wait", "--timeout", "120"], check=True, capture_output=True,
                           env={k:v for k,v in os.environ.items() if k != "SDJU_MAIL_PASSWORD"})
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Review checksum mismatch")
        mime = item.get("mime_type", "").split(";")[0]
        if mime == "application/pdf":
            result = subprocess.run(["pdftotext", str(path), "-"], check=True, capture_output=True, timeout=45)
            text = result.stdout.decode()
        elif mime == "text/plain":
            text = path.read_text()
        else:
            raise ValueError("Unsupported review attachment")
        if not text.strip():
            raise ValueError("Review attachment requires text extraction")
        texts.append(text)
    return "\n\n".join(texts)


def notify_once(args, api, db, paper, event, note=""):
    """Tell the handler once. ``notified``: 0 not yet, -1 sending, 1 sent, 2 nothing to tell,
    3 delivery unknown and reported for review.

    A send that fails returns to 0 and is retried on the next round (audit C5: a failed send
    used to leave -1 for ever, so the handler never heard of the letter). Only a process that
    died while sending leaves -1: it is not sent again (it may have been delivered), but it goes
    into the review digest once so a person checks it."""
    key = event["message_key"]
    notified = db.execute("SELECT notified FROM progress WHERE message_key=?", (key,)).fetchone()[0]
    if notified == -1:
        print("Handler notification may not have been delivered", key[:12], flush=True)
        db.execute(REVIEW_TABLE)
        db.execute("INSERT OR IGNORE INTO review(key, kind, reason, paper_ids, decisions) VALUES (?,?,?,?,?)",
                   ("event:" + key, "notification_unknown",
                    "the service stopped while sending the handler notification; it may not have arrived",
                    json.dumps([event.get("paper_id")]), json.dumps([event.get("decision")])))
        db.execute("UPDATE progress SET notified=3 WHERE message_key=?", (key,))
        db.commit()
        return True
    if not notified:
        def before_send():
            db.execute("UPDATE progress SET notified=-1 WHERE message_key=?", (key,))
            db.commit()
        try:
            notify(api, paper, event, args.account, before_send, raw=event.get("raw"), note=note)
        except (OSError, HandoffError, ValueError) as exc:
            db.execute("UPDATE progress SET notified=0 WHERE message_key=? AND notified=-1", (key,))
            db.commit()
            print("Handler notification pending", key[:12], type(exc).__name__, flush=True)
            return False
        db.execute("UPDATE progress SET notified=1 WHERE message_key=?", (key,))
        db.commit()
    return True


CLOSED_ATTEMPTS = frozenset({"accepted", "rejected", "withdrawn", "published", "closed"})
# Site statuses that already hold a decision's outcome: a published paper was accepted.
REGISTERED_AS = {"published": {"published", "accepted"}, "closed": {"closed", "rejected", "withdrawn"}}
# The attempt status a decision leaves behind (proofs keep the current one).
DECISION_STATUS = {"submitted": "submitted", "rejected": "rejected", "accepted": "accepted",
                   "revision_requested": "revision_preparing"}
# A submission confirmation arrives around the site registration: the site may be filled in
# before or after the journal's acknowledgement.
CONFIRMATION_WINDOW = (timedelta(days=-7), timedelta(days=30))
# A decision follows the submission; three years covers slow journals.
DECISION_WINDOW = (timedelta(days=-1), timedelta(days=3 * 365))
# The confirmation of a revised manuscript follows the revision decision (2026-11-26): the
# journal's deadline plus any extension is well inside a year.
RESUBMISSION_WINDOW = (timedelta(days=-1), timedelta(days=365))


class AttemptHold(ValueError):
    """No unique submission attempt for a letter: held with the reason recorded."""


def _instant(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _latest_round(paper, attempt):
    rounds = [r for r in paper.get("review_rounds") or []
              if isinstance(r, dict) and r.get("attempt_id") == attempt.get("id")]
    if not rounds:
        return None
    return max(rounds, key=lambda r: (int(r.get("round_no") or 0), str(r.get("received_at") or "")))


def revision_round(paper, attempt):
    """The attempt's latest review round, when the attempt is waiting for a revised manuscript.

    A submission confirmation for such an attempt is the journal acknowledging the revision
    (20260506airesearch0005, IJDSA, 2026-11-15): it is a resubmission, not a repeat of the
    original submission the site already lists.
    """
    if str(attempt.get("status") or "") != "revision_preparing":
        return None
    return _latest_round(paper, attempt)


def select_attempt(api, paper, event, context):
    """The submission attempt a letter belongs to, with the evidence it was chosen on.

    The manuscript number decides when an attempt carries it. Otherwise (the site attempt has
    no number yet, or the letter quotes none) the attempt is chosen by journal name, the
    paper's title, the submitter and a time window around the attempt's submission; only a
    unique candidate is used. Anything else raises :class:`AttemptHold` with the reason.
    """
    attempts = list(paper.get("submission_attempts") or [])
    number = str(event.get("manuscript_id") or "")
    if number:
        exact = [a for a in attempts if str(a.get("manuscript_number") or "").casefold() == number.casefold()]
        if len(exact) == 1:
            status = str(exact[0].get("status") or "")
            target = DECISION_STATUS.get(event["decision"])
            if status in CLOSED_ATTEMPTS and target and target not in REGISTERED_AS.get(status, {status}) \
                    and event["decision"] != "submitted":
                # A closed attempt is never moved to another outcome by a letter (a rejected
                # attempt "accepted", an accepted one "rejected"): a person checks it.
                raise AttemptHold(f"closed: attempt {str(exact[0].get('id'))[:8]} is already {status}; "
                                  f"the letter reads as {event['decision']}")
            return exact[0], ["manuscript_number"]
        if exact:
            raise AttemptHold(f"ambiguous: {len(exact)} attempts carry manuscript number {number}")
    content = (context or {}).get("content") or ""
    # Journal names are read up to any list of other journals the letter recommends (audit C9).
    content_key = _key((context or {}).get("journal_content", content))
    journal_key = _key(event.get("journal"))
    title = " ".join(str(paper.get("title") or "").casefold().split())
    title_seen = bool(title) and len(title) >= 12 and title in content
    received = _instant(event.get("received_at") or (context or {}).get("received_at"))
    decision = event["decision"]
    target = DECISION_STATUS.get(decision)
    candidates, refused = [], []
    for attempt in attempts:
        label = str(attempt.get("id") or "?")[:8]
        own = str(attempt.get("manuscript_number") or "")
        if number and own:
            refused.append(f"{label}: carries another manuscript number")
            continue
        name = _key(attempt.get("journal_name"))
        if not name or not (name == journal_key or (len(name) >= 6 and name in content_key)):
            refused.append(f"{label}: journal {attempt.get('journal_name')!r} not named")
            continue
        status = str(attempt.get("status") or "")
        if decision == "submitted":
            if status in CLOSED_ATTEMPTS:
                refused.append(f"{label}: already {status}")
                continue
            awaited = (_latest_round(paper, attempt)
                       if status in {"revision_preparing", "resubmitted"} else None)
            if awaited is not None:
                # A revised manuscript is confirmed after the revision decision, not around the
                # attempt's first submission (a replay after registration finds it the same way).
                reference = _instant(awaited.get("received_at") or awaited.get("created_at"))
                window = RESUBMISSION_WINDOW
            else:
                reference = _instant(attempt.get("submitted_at") or attempt.get("created_at") or attempt.get("started_at"))
                window = CONFIRMATION_WINDOW
        else:
            if status == "preparing":
                refused.append(f"{label}: not submitted yet")
                continue
            if status in CLOSED_ATTEMPTS and status != target:
                refused.append(f"{label}: already {status}")
                continue
            reference = _instant(attempt.get("submitted_at"))
            window = DECISION_WINDOW
        if received is None or reference is None:
            refused.append(f"{label}: no time to compare")
            continue
        if not reference + window[0] <= received <= reference + window[1]:
            refused.append(f"{label}: outside the time window")
            continue
        candidates.append(attempt)
    basis = ["journal", "time_window"] + (["title"] if title_seen else [])
    if len(candidates) > 1:
        addresses = (context or {}).get("addresses") or set()
        listing = api._request("GET", "/v1/users") if addresses else []
        users = {u.get("id"): str(u.get("email") or "").casefold()
                 for u in (listing if isinstance(listing, list) else []) if isinstance(u, dict)}
        assigned = {a.get("submitter_id") for a in paper.get("assignments") or [] if a.get("active")}
        def submitted_by_recipient(attempt):
            people = {attempt.get("created_by"), attempt.get("submitter_id"), *assigned} - {None}
            return any(users.get(person) and users[person] in addresses for person in people)
        narrowed = [a for a in candidates if submitted_by_recipient(a)]
        if len(narrowed) == 1:
            return narrowed[0], basis + ["submitter"]
        raise AttemptHold(f"ambiguous: {len(candidates)} attempts match journal and time window "
                          f"({', '.join(str(a.get('id'))[:8] for a in candidates)})")
    if not candidates:
        raise AttemptHold("no attempt matches: " + ("; ".join(refused) or "the paper has no submission attempt"))
    if not title_seen and not number:
        raise AttemptHold("unconfirmed: the letter quotes neither the title nor a manuscript number")
    return candidates[0], basis


def _hold(db, key, reason):
    columns = {row[1] for row in db.execute("PRAGMA table_info(progress)")}
    if "hold_reason" not in columns:
        db.execute("ALTER TABLE progress ADD COLUMN hold_reason TEXT")
    db.execute("UPDATE progress SET hold_reason=? WHERE message_key=?", (reason[:500], key))
    db.commit()


def already_registered(paper, attempt, event):
    """The site already holds this letter's outcome: the event it posted (same idempotency
    key, e.g. a hand registration of the letter), or the decision's status with the number.

    A confirmation reaching an attempt that waits for a revised manuscript is not registered
    yet: the site still shows the revision as pending (2026-11-26, IJDSA c2f005cb)."""
    key = "mail:" + event["message_key"]
    if any(item.get("idempotency_key") == key for item in paper.get("submission_events") or []):
        return True
    number = str(event.get("manuscript_id") or "")
    own = str(attempt.get("manuscript_number") or "")
    target = DECISION_STATUS.get(event["decision"])
    if event["decision"] == "submitted":
        if revision_round(paper, attempt) is not None:
            return False
        return attempt.get("status") != "preparing" and (not number or own.casefold() == number.casefold())
    return bool(target) and target in REGISTERED_AS.get(str(attempt.get("status") or ""), {attempt.get("status")}) \
        and (not number or own.casefold() == number.casefold())


def rejection_letter(args, event):
    """``--letter-file`` with a rejection's verbatim letter for the registry record (C8,
    2026-11-26): the next review of a paper outside the topic ledger reads the editor's words."""
    if event["decision"] != "rejected" or not event.get("raw"):
        return []
    from email import policy
    from email.parser import BytesParser

    from paper_writing.journal_mail import message_text

    subject, body = message_text(BytesParser(policy=policy.default).parsebytes(event["raw"]))
    if not body.strip():
        return []
    path = args.state / (event["message_key"] + ".letter.txt")
    path.write_text(f"Subject: {subject}\n\n{body.strip()}\n")
    return ["--letter-file", str(path)]


def hold_note(event, hold):
    """What the handler is asked to do about a letter held without a unique attempt."""
    reason = str(hold)
    if event["decision"] == "submitted" and reason.startswith("no attempt matches"):
        # An attempt of this journal exists but was refused (already closed, outside the time
        # window, another number): check it instead of creating a duplicate (audit C10).
        existing = [part.strip() for part in reason.removeprefix("no attempt matches:").split(";")
                    if ": " in part and not part.strip().endswith("not named")]
        if existing:
            return ("网站上已有本刊的投稿记录，但与这封投稿确认信对不上（" + "；".join(existing)[:300] + "）。"
                    "请先核对这些记录（补稿号、更正状态或提交时间）；确认这是一次新的投稿后才新建记录："
                    f"期刊 {event.get('journal') or '待核实'}，提交时间 {event.get('received_at') or '待核实'}"
                    f"，稿号 {event.get('manuscript_id') or '信中未给出'}。")
        return ("网站上没有与这封投稿确认信对应的投稿记录（原因：" + reason[:300] + "）。请在管理网站为本文新建投稿记录："
                f"期刊 {event.get('journal') or '待核实'}，提交时间 {event.get('received_at') or '待核实'}"
                f"，稿号 {event.get('manuscript_id') or '信中未给出'}。")
    return "这封信未能对应到网站上唯一的投稿记录（原因：" + reason[:300] + "），请在管理网站核对后手工登记。"


# A copy of a revision decision (forward, reply, co-author copy) arrives within weeks of it.
COPY_WINDOW = timedelta(days=45)


def open_round_letter(args, api, db, paper, attempt, event):
    """Handle a revision letter for an attempt whose last round is open or answered on the
    site; True when the letter needs nothing more.

    A letter written before the round's revision was sent back (or, without that time, within
    weeks of the round's decision) is a copy of that decision: nothing to do. A later letter
    for an attempt still waiting for its revision means the site and the journal disagree: the
    handler is told once. Either way the event is finished instead of being retried for ever
    (audit C10). A later letter after the revision was sent back is the next round (False)."""
    key = event["message_key"]
    latest = _latest_round(paper, attempt)
    received = _instant(event.get("received_at"))
    opened = _instant((latest or {}).get("received_at") or (latest or {}).get("created_at"))
    answered = _instant((latest or {}).get("response_submitted_at"))
    if latest and received and (answered and received <= answered
                                or not answered and opened and abs(received - opened) <= COPY_WINDOW):
        _hold(db, key, f"copy of round {latest.get('round_no')}")
        print("Journal revision copy", key[:12], f"round={latest.get('round_no')}", flush=True)
        db.execute("UPDATE progress SET notified=2 WHERE message_key=? AND notified=0", (key,))
        db.execute("UPDATE progress SET complete=1 WHERE message_key=?", (key,))
        db.commit()
        return True
    if attempt.get("status") != "revision_preparing":
        return False
    reason = ("revision letter while the site already waits for the revision of round "
              f"{(latest or {}).get('round_no') or '?'}")
    _hold(db, key, reason)
    print("Journal event held", key[:12], reason, flush=True)
    if notify_once(args, api, db, paper, event, note=(
            "网站上本次投稿已处于返修中（第 " + str((latest or {}).get("round_no") or "?") + " 轮），"
            "这封返修信与之对不上。请核对是否为新一轮返修，并在管理网站手工登记。")):
        db.execute("UPDATE progress SET complete=1 WHERE message_key=?", (key,))
    db.commit()
    return True


def dispatch_one(args, api, db, event):
    key = event["message_key"]
    paper = api._request("GET", "/v1/papers/" + event["paper_id"])
    context = None
    if event.get("raw"):
        from paper_writing.journal_mail import mail_context
        context = mail_context(event["raw"])
        # Events stored before 2026-11-26 lack numbers the parser did not recognise then
        # (Springer "Submission ID <uuid>"): read them again from the original.
        if not event.get("manuscript_id") and context["manuscript_id"]:
            event["manuscript_id"] = context["manuscript_id"]
    number = event["manuscript_id"]
    try:
        attempt, basis = select_attempt(api, paper, event, context)
    except AttemptHold as hold:
        _hold(db, key, str(hold))
        print("Journal event held", key[:12], str(hold)[:300], flush=True)
        # The handler hears of the letter with the reason (e.g. no attempt for a submission
        # confirmation: create it on the site); once only, the hold itself retries.
        notify_once(args, api, db, paper, event, note=hold_note(event, hold))
        ledger(args, event)
        raise
    _hold(db, key, "")
    posted_here = any(item.get("idempotency_key") == "mail:" + key for item in paper.get("submission_events") or [])
    if event["decision"] != "revision_requested" and not posted_here and already_registered(paper, attempt, event):
        # A further letter on an outcome the site already lists with this number (co-author
        # copies, forwards, replies, an accepted paper's follow-up letters): nothing for the
        # handler to do (audit C10). The site event this letter posted itself does not count:
        # its notification may still be owed after a failed send.
        db.execute("UPDATE progress SET notified=2 WHERE message_key=? AND notified=0", (key,))
        db.commit()
    if event["decision"] == "revision_requested" and not event.get("round") \
            and attempt.get("status") in {"revision_preparing", "resubmitted"} \
            and not db.execute("SELECT round_no FROM progress WHERE message_key=?", (key,)).fetchone()[0] \
            and open_round_letter(args, api, db, paper, attempt, event):
        # A copy of the open round's decision, or a letter the site disagrees with: handled
        # (and, for a copy, not notified again) before the handler hears of it.
        return
    notified = notify_once(args, api, db, paper, event)
    did = event["decision"]
    comments = event["reviewer_comments"]
    uri = f"/v1/submission-attempts/{attempt['id']}"
    if did == "revision_requested" and number and not attempt.get("manuscript_number"):
        # Matched without the number: record it on the attempt before the round opens.
        api._request("POST", uri + "/events", idempotency_key="mail:" + key + ":number",
                     json={"event_type": "note", "to_status": attempt.get("status"),
                           "payload": {"manuscript_number": number, "source": "journal_mail",
                                       "match_basis": basis}})
    if did == "revision_requested":
        row = db.execute("SELECT round_no FROM progress WHERE message_key=?", (key,)).fetchone()
        rnd = row[0] or event.get("round") or int(attempt.get("current_round") or 0) + 1
        db.execute("UPDATE progress SET round_no=? WHERE message_key=?", (rnd, key))
        db.commit()
        grade = event.get("revision_grade") or "revision_requested"
        result = api._request("POST", uri + "/review-rounds", idempotency_key="mail:" + key,
                              json={"round_no": rnd, "decision": grade, "due_at": event["due"],
                                    **({"received_at": event["received_at"]} if event.get("received_at") else {}),
                                    "summary": "Journal decision received", "revision_instructions":
                                    f"OpenLabs journal {key}\n" + (comments or "请投稿负责人下载并上传本轮完整审稿意见。")})
        rid = result["review_round"]["id"]
    elif not already_registered(paper, attempt, event):
        status = attempt.get("status")
        awaited = revision_round(paper, attempt) if did == "submitted" else None
        extra = {}
        if awaited is not None:
            # The journal confirms the revised manuscript: the attempt is resubmitted, which
            # also closes the round's revision request on the site (migration 017).
            kind, to_status = "resubmitted", "resubmitted"
            extra = {"round_no": awaited.get("round_no"), "review_round_id": awaited.get("id")}
        elif did == "proofs" or (did == "submitted" and status != "preparing"):
            # Proofs, or the journal's acknowledgement of an attempt the site already lists as
            # submitted: a note that keeps the status and records the manuscript number.
            kind, to_status = "note", status
        else:
            kind, to_status = did, did
        api._request("POST", uri + "/events", idempotency_key="mail:" + key,
                     json={"event_type": kind, "to_status": to_status, **({"occurred_at": event["received_at"]} if event.get("received_at") else {}),
                           "payload": {"manuscript_number": number, "decision": did, "source": "journal_mail",
                                       "match_basis": basis, **extra}})
    letter = rejection_letter(args, event)
    if letter:
        ledger(args, event, letter)
    else:
        ledger(args, event)
    if did == "revision_requested":
        request = result.get("revision_request") or next((r for r in paper["revision_requests"] if r["review_round_id"] == rid), {})
        request_id = request["request_id"]
        comments = comments or uploaded_reviews(api, paper, rid, args.state)
        if not comments:
            return
        brief = args.state / (key + ".txt")
        brief.write_text(comments)
        ledger(args, event, ["--round", str(rnd), "--package-id", attempt["package_id"],
                             "--revision-brief", str(brief), "--request-id", request_id])
    if notified:
        db.execute("UPDATE progress SET complete=1 WHERE message_key=?", (key,))
    db.commit()


REVIEW_KINDS = {"parse_failed": "解析失败", "no_message_id": "缺少有效 Message-ID", "unmatched": "未匹配到网站论文",
                "ambiguous": "匹配到多篇论文", "many_numbers": "信中有同一论文的多个稿号",
                "conflict": "决定冲突，已挂起", "no_decision": "认不出决定",
                "notification_unknown": "给投稿人的通知可能未送达"}


def review_digest(rows):
    """The text of one digest of letters waiting for a person (see journal_mail.Unused)."""
    lines = [f"期刊邮件服务有 {len(rows)} 封信需要人工确认（服务未据此改动网站或台账）：", ""]
    for number, (key, kind, reason, paper_ids, decisions, subject, sender, received) in enumerate(rows, 1):
        papers = ", ".join(p for p in json.loads(paper_ids or "[]") if p) or "无"
        found = ", ".join(d for d in json.loads(decisions or "[]") if d) or "无"
        lines += [f"{number}. {REVIEW_KINDS.get(kind, kind)}（{reason}）",
                  f"   邮箱位置 {key}；收信 {received or '未知'}",
                  f"   发件人 {sender or '未知'}",
                  f"   主题 {subject or '未知'}",
                  f"   候选论文 {papers}；候选决定 {found}", ""]
    lines.append("请在 SDJU 邮箱按主题找到原信，核对后在管理网站手工登记。")
    return "\n".join(lines)


def notify_review(args, db):
    """Send the letters queued for review (journal_mail.record_review) to the service's own
    mailbox in one digest per round; marked only after the send succeeded (audit C3/C8)."""
    db.execute(REVIEW_TABLE)
    rows = db.execute("SELECT key, kind, reason, paper_ids, decisions, subject, sender, received_at FROM review "
                      "WHERE notified=0 ORDER BY rowid").fetchall()
    if not rows:
        return False
    message = EmailMessage()
    message["From"] = message["To"] = args.account
    digest = hashlib.sha256("\n".join(r[0] for r in rows).encode()).hexdigest()
    # journal_mail skips the service's own <openlabs-...> letters when it reads the mailbox.
    message["Message-ID"] = "<openlabs-review-" + digest + "@sdju.edu.cn>"
    message["Subject"] = f"期刊邮件待人工确认 · {len(rows)} 封"
    message.set_content(review_digest(rows))
    try:
        with smtplib.SMTP_SSL("smtp.qiye.163.com", timeout=15, context=ssl.create_default_context()) as smtp:
            smtp.login(args.account, os.environ["SDJU_MAIL_PASSWORD"])
            smtp.sendmail(args.account, [args.account], message.as_bytes(policy=SMTP))
    except (OSError, KeyError) as exc:
        print("Journal review digest pending", len(rows), type(exc).__name__, flush=True)
        return False
    db.executemany("UPDATE review SET notified=1 WHERE key=?", [(r[0],) for r in rows])
    db.commit()
    print("Journal review digest sent", len(rows), flush=True)
    return True


def drain(args, api):
    if not (args.state / "events.sqlite").exists():
        return
    with sqlite3.connect(args.state / "events.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS progress (message_key TEXT PRIMARY KEY, "
                   "round_no INTEGER, notified INTEGER DEFAULT 0, complete INTEGER DEFAULT 0)")
        db.execute("CREATE TABLE IF NOT EXISTS originals (message_key TEXT PRIMARY KEY, raw BLOB NOT NULL)")
        db.execute("INSERT OR IGNORE INTO progress(message_key) SELECT message_key FROM events")
        db.commit()
        for key, payload in db.execute("SELECT message_key,payload FROM events JOIN progress "
                                       "USING(message_key) WHERE complete=0 ORDER BY events.rowid").fetchall():
            event = json.loads(payload)
            try:
                original = db.execute("SELECT raw FROM originals WHERE message_key=?", (key,)).fetchone()
                event["raw"] = original[0] if original else None
                dispatch_one(args, api, db, event)
            except (HandoffError, OSError, ValueError, KeyError, LookupError, subprocess.SubprocessError) as exc:
                print("Journal event pending", key[:12], type(exc).__name__, flush=True)
        notify_review(args, db)
