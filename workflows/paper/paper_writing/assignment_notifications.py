"""Notify the current submitter of a site-ready paper from the journal-mail service."""

import fcntl
import hashlib
import os
import smtplib
import sqlite3
from contextlib import closing, nullcontext
from email.message import EmailMessage
from pathlib import Path

from paper_writing.handoff import HandoffError
from paper_writing.journal_dispatch import handler_address, mail_connection
from paper_writing.site_assignments import _current_package

SITE = "https://webgame-d4gl5d4jee12dd248-1253393736.tcloudbaseapp.com/ara-paper-manage/"
READY = "ready_to_submit"


def _send(account, address, name, paper, assignment_id, before_send):
    paper_id = paper["paper_id"]
    writing = (paper.get("writing_metadata") or {}).get("target_journal") or {}
    journal = paper.get("target_journal") or writing.get("name") or "请在站点核对"
    version = _current_package(paper).get("version") or "请在站点核对"
    key = hashlib.sha256(f"{paper_id}:{assignment_id}".encode()).hexdigest()
    message = EmailMessage()
    message["From"], message["To"] = account, address
    message["Subject"] = f"投稿待办 · 可投稿 · {paper_id}"
    message["Message-ID"] = f"<openlabs-assignment-{key}@sdju.edu.cn>"
    message.set_content(
        f"{name}，您好！\n\n"
        f"论文《{paper['title']}》已可投稿，由您负责。\n"
        f"目标期刊：{journal}\n版本：{version}\n\n"
        f"{SITE}\n"
        f"请在论文列表中按 {paper_id} 找到并打开详情，在「投稿包」下载材料，"
        "并查看包内的投稿信和建议审稿人。\n\n"
        "投稿前，请确认所有作者均同意投稿。\n"
        "投稿后，请在站点登记投稿信息和稿件编号。\n\n"
        "OpenLabs 产线（自动发送）"
    )
    # Delivery is accepted at DATA. A later QUIT failure must not trigger another send.
    with closing(mail_connection()) as smtp:
        smtp.login(account, os.environ["SDJU_MAIL_PASSWORD"])
        before_send()
        smtp.send_message(message)


def reconcile(api, state: Path, account: str, *, dry_run=False, paper_ids=()) -> bool:
    """Use the live site as the work list, including manual assignments and missed polls."""
    placeholder = api._request("GET", "/v1/me")["id"]
    if not placeholder:
        raise ValueError("Missing site service account")
    users = api._request("GET", "/v1/users")
    names = {user["id"]: user.get("display_name") for user in users if user.get("active")}
    if not paper_ids:
        paper_ids = [row["paper_id"] for row in api._request("GET", "/v1/papers")
                     if row.get("lifecycle_status") == READY]
    path = state.resolve() / "assignment-notifications.sqlite"
    # Preview reads an existing ledger without creating or changing it.
    preview_existing = dry_run and path.exists()
    db = (sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) if preview_existing
          else sqlite3.connect(":memory:" if dry_run else path, timeout=60))
    ok = True
    lock = nullcontext() if dry_run else path.with_suffix(".lock").open("a")
    with closing(db), lock as handle:
        if handle is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        if not preview_existing:
            db.execute("""CREATE TABLE IF NOT EXISTS sent (
                paper_id TEXT NOT NULL, assignment_id TEXT NOT NULL, submitter_id TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (paper_id, assignment_id)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS sending (
                paper_id TEXT NOT NULL, assignment_id TEXT NOT NULL,
                PRIMARY KEY (paper_id, assignment_id)
            )""")
        for paper_id in sorted(set(paper_ids)):
            try:
                with db:
                    paper = api._request("GET", f"/v1/papers/{paper_id}", allow_not_found=True)
                    if not paper or paper.get("lifecycle_status") != READY:
                        continue
                    active = [row for row in paper.get("assignments") or [] if row.get("active")]
                    if len(active) != 1:
                        continue
                    assignment_id = active[0].get("id")
                    submitter_id = active[0].get("submitter_id")
                    name = names.get(submitter_id)
                    if not assignment_id or not name or submitter_id == placeholder:
                        continue
                    if db.execute("SELECT 1 FROM sent WHERE paper_id=? AND assignment_id=?",
                                  (paper_id, assignment_id)).fetchone():
                        continue
                    last = db.execute("SELECT submitter_id FROM sent WHERE paper_id=? "
                                      "ORDER BY rowid DESC LIMIT 1", (paper_id,)).fetchone()
                    # Parking then restoring the same submitter can create a new assignment ID.
                    if last == (submitter_id,):
                        continue
                    key = (paper_id, assignment_id)
                    if db.execute("SELECT 1 FROM sending WHERE paper_id=? AND assignment_id=?", key).fetchone():
                        print(paper_id, "Assignment notification delivery unknown", flush=True)
                        ok = False
                        continue
                    address = handler_address(api, paper, users=users)
                    if not dry_run:
                        _send_once(db, key, submitter_id, account, address, name, paper)
                print(paper_id, name, *([] if dry_run else ["SMTP accepted"]), flush=True)
            except (HandoffError, OSError, LookupError, ValueError, sqlite3.Error) as exc:
                print(paper_id, "Assignment notification failed", type(exc).__name__, flush=True)
                ok = False
    return ok


def _send_once(db, key, submitter_id, account, address, name, paper):
    def mark_sending():
        # Persist before SMTP DATA so a crash or lost response cannot cause a second send.
        db.execute("INSERT INTO sending VALUES (?, ?)", key)
        db.commit()

    try:
        _send(account, address, name, paper, key[1], mark_sending)
    except (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError):
        db.execute("DELETE FROM sending WHERE paper_id=? AND assignment_id=?", key)
        db.commit()
        raise
    db.execute("INSERT INTO sent(paper_id, assignment_id, submitter_id) VALUES (?, ?, ?)",
               (*key, submitter_id))
    db.execute("DELETE FROM sending WHERE paper_id=? AND assignment_id=?", key)
