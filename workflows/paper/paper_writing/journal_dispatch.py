"""Dispatch matched private journal messages using the current Manage assignment."""
import hashlib
import json
import os
import re
import smtplib
import sqlite3
import ssl
import subprocess
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import parseaddr

from paper_writing.handoff import HandoffError


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


def notify(api, paper, event, account, before_send=lambda: None, *, raw=None):
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
               f"状态 {event['decision']}\n期限 {event['due'] or '待核实'}\n{actions[event['action']]}")

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


def notify_once(args, api, db, paper, event):
    key = event["message_key"]
    notified = db.execute("SELECT notified FROM progress WHERE message_key=?", (key,)).fetchone()[0]
    if notified == -1:
        return False
    if not notified:
        def before_send():
            db.execute("UPDATE progress SET notified=-1 WHERE message_key=?", (key,))
            db.commit()
        try:
            notify(api, paper, event, args.account, before_send, raw=event.get("raw"))
        except (OSError, HandoffError, ValueError) as exc:
            print("Handler notification pending", key[:12], type(exc).__name__, flush=True)
            return False
        db.execute("UPDATE progress SET notified=1 WHERE message_key=?", (key,))
        db.commit()
    return True


def dispatch_one(args, api, db, event):
    key = event["message_key"]
    paper = api._request("GET", "/v1/papers/" + event["paper_id"])
    notified = notify_once(args, api, db, paper, event)
    number = event["manuscript_id"]
    attempts = [a for a in paper["submission_attempts"] if number and
                str(a.get("manuscript_number") or "").casefold() == number.casefold()]
    if not attempts and number and event["decision"] == "submitted":
        attempts = [a for a in paper["submission_attempts"] if not a.get("manuscript_number")
                    and a["status"] == "preparing" and a.get("journal_name") == event["journal"]]
    if len(attempts) != 1:
        ledger(args, event)
        raise ValueError("Attempt requires reconciliation")
    attempt = attempts[0]
    did = event["decision"]
    comments = event["reviewer_comments"]
    uri = f"/v1/submission-attempts/{attempt['id']}"
    if did == "revision_requested":
        row = db.execute("SELECT round_no FROM progress WHERE message_key=?", (key,)).fetchone()
        rnd = row[0] or event.get("round") or int(attempt.get("current_round") or 0) + 1
        if not row[0] and attempt["status"] == "revision_preparing" and not event.get("round"):
            raise ValueError("Existing open round needs reconciliation")
        db.execute("UPDATE progress SET round_no=? WHERE message_key=?", (rnd, key))
        db.commit()
        grade = event.get("revision_grade") or "revision_requested"
        result = api._request("POST", uri + "/review-rounds", idempotency_key="mail:" + key,
                              json={"round_no": rnd, "decision": grade, "due_at": event["due"],
                                    **({"received_at": event["received_at"]} if event.get("received_at") else {}),
                                    "summary": "Journal decision received", "revision_instructions":
                                    f"OpenLabs journal {key}\n" + (comments or "请投稿负责人下载并上传本轮完整审稿意见。")})
        rid = result["review_round"]["id"]
    else:
        kind = {"proofs": "note"}.get(did, did)
        api._request("POST", uri + "/events", idempotency_key="mail:" + key,
                     json={"event_type": kind, "to_status": attempt["status"] if did == "proofs" else did, **({"occurred_at": event["received_at"]} if event.get("received_at") else {}), "payload": {"manuscript_number": number, "decision": did}})
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
            except (HandoffError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                print("Journal event pending", key[:12], type(exc).__name__, flush=True)
