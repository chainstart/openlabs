"""A model's reading of the journal letters the rules could not settle (2026-11-26).

``journal_mail`` queues a letter for a person (:class:`journal_mail.Unused`, the ``review``
table of events.sqlite) when it is held, undecided, unmatched or unreadable. With
``[program] journal_mail_model_review`` on, such a letter also gets a *brief*
(:func:`brief`): its subject and decision-related sentences with personal information removed,
the sender's domain, the manuscript numbers it quotes, the candidate papers and what the rules
found. The orchestrator hands pending briefs to a light-tier ``journal_mail_triage`` task (no
resident model process) and writes the model's answer back into the review row; the digest
(``journal_dispatch.notify_review``) shows the answer after :func:`check` has validated it.

The answer never changes the site or the ledger. A person reads it in the digest ("系统判断为
X（依据原句…），请在管理网站核对登记"). An answer that fails the schema or quotes a sentence
that is not in the brief counts as no answer.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr

# Kinds of journal_mail.Unused a model reads (the others are bookkeeping: a missing
# Message-ID, a notification that may not have arrived).
TRIAGE_KINDS = frozenset({"conflict", "no_decision", "unmatched", "ambiguous", "many_numbers", "parse_failed"})
CATEGORIES = {
    "submitted": "投稿确认", "resubmitted": "修改稿收到确认", "rejected": "拒稿",
    "desk_reject": "直接拒稿（未送审）", "major_revision": "大修", "minor_revision": "小修",
    "accepted": "录用", "proof": "校样", "transfer_offer": "转刊推荐",
    "not_a_decision": "不是期刊决定信", "other": "其他",
}
# Categories worth a word to the paper's submitter when the model names the paper.
HANDLER_CATEGORIES = frozenset(CATEGORIES) - {"not_a_decision", "other"}
HANDLER_MIN_CONFIDENCE = 0.7
# A letter waits this long for the model before the digest goes out without its answer.
WAIT = timedelta(hours=3)
WAITING_STATES = frozenset({"pending", "dispatched"})
ANSWER_KEYS = {"key", "category", "paper_id", "manuscript_id", "due", "confidence", "evidence_quotes"}
OPTIONAL_KEYS = {"note"}
MAX_SENTENCES = 30
MAX_CHARS = 5000
MAX_CANDIDATES = 5

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.I)
PHONE = re.compile(r"(?:\b(?:tel|phone|fax|mobile|telephone)\b\.?\s*[:：]?\s*)[+\d(][\d ()./-]{6,}\d|\+\d[\d ()./-]{7,}\d", re.I)
HONORIFIC = re.compile(r"\b(?:Dr|Prof|Professor|Mr|Mrs|Ms|Miss|Assoc\. Prof|Asst\. Prof)\.?\s+"
                       r"(?:[A-Z]\.\s*)*[A-Z][\w'’-]+(?:\s+(?:[A-Z]\.\s*)*[A-Z][\w'’-]+){0,2}")
GREETING = re.compile(r"^\s*(?:(?:dear|hi|hello)\b|尊敬的|亲爱的)[^\n,:：.!?]{0,60}[,:：]", re.I | re.M)
# Header lines of a forwarded or quoted letter carry names and addresses.
HEADER_LINE = re.compile(r"^\s*>*\s*(?:from|to|cc|bcc|sent|reply-to|发件人|收件人|抄送|发送时间|时间|日期)\s*[:：].*$",
                         re.I | re.M)
AUTHOR_LINE = re.compile(r"^\s*(?:(?:corresponding|submitting|first|contributing) )?(?:authors?|co-?authors?|作者|通讯作者)"
                         r"(?:\s*\(s\))?\s*[:：].*$", re.I)
SIGNOFF = re.compile(r"^\s*(?:(?:with\s+)?(?:(?:best|kind|warm|warmest)\s+)?(?:regards|wishes)\b[^\n]{0,30}"
                     r"|sincerely[^\n]{0,30}|yours (?:sincerely|truly|faithfully)[^\n]{0,30}|cordially|respectfully"
                     r"|(?:thank you|many thanks|thanks)[,!.]?|此致[^\n]{0,10}|祝好[^\n]{0,10})\s*$", re.I)
# The quote line of a reply ("On <date>, <name> <address> wrote:", "在 <时间>，<姓名> 写道：").
WROTE_LINE = re.compile(r"^\s*(?:on\b|在).{0,160}(?:wrote|写道)\s*[:：]?\s*$", re.I)
# Style sheets of HTML letters ("body { margin: 0; }").
CSS = re.compile(r"^@import\b|\{[^{}]*:[^{}]*\}|^[@#.]?[\w-]+(?:\s*,\s*[\w.#-]+)*\s*\{")
CUE = re.compile(r"decision|accept|reject|revis|declin|outcome|withdraw|regret|unfortunately|congratulat|proof"
                 r"|not (?:be )?(?:able|suitable)|transfer|received|receipt|submi|manuscript|review|editor|due\b"
                 r"|deadline|publish|consider|suitab|scope|journal|稿|录用|退修|修改", re.I)


def fold(text):
    return " ".join(str(text or "").split())


def redact(text):
    """``text`` without addresses, links, phone numbers, salutations and titled names."""
    text = URL.sub("[link]", EMAIL.sub("[email]", str(text or "")))
    text = PHONE.sub("[phone]", text)
    text = GREETING.sub(lambda m: re.match(r"\s*", m[0])[0] + "Dear [name],", text)
    return HONORIFIC.sub("[name]", text)


def _body_lines(body):
    """Body lines without forwarded headers, quote marks and the names under a sign-off."""
    kept, skip = [], 0
    for line in str(body or "").splitlines():
        line = re.sub(r"^\s*(?:>\s*)+", "", line)
        if skip and line.strip():
            skip -= 1
            if len(line.strip()) < 80:
                continue
        if HEADER_LINE.match(line) or WROTE_LINE.match(line):
            continue
        if AUTHOR_LINE.match(line):
            kept.append("Authors: [names]")
            continue
        if SIGNOFF.match(line):
            skip = 4  # the name, title and affiliation under the sign-off
            continue
        kept.append(line)
    return kept


def sentences(body, cut=None):
    """The body's sentences, in order, redacted; publisher boilerplate (``cut``) removed."""
    paragraphs = re.split(r"\n\s*\n", "\n".join(_body_lines(body)))
    found = []
    for paragraph in paragraphs:
        text = redact(fold(paragraph))  # before splitting: "Dr." must not end a sentence
        if cut is not None:
            hit = cut.search(text)
            if hit:
                found.extend(_split(text[:hit.start()]))
                break
        found.extend(_split(text))
    return found


def _split(text):
    return [fold(item)[:400] for item in re.split(r"(?<=[.!?。！？])\s+", text)
            if len(item.strip()) > 2 and not CSS.search(item)]


def _attempts(entry):
    attempts = entry.get("attempts")
    if attempts is None:
        attempts = [{"journal": journal, "manuscript_number": number}
                    for number, journal in (entry.get("attempt_journals") or {}).items()]
    return [{k: a.get(k) for k in ("journal", "manuscript_number", "status") if a.get(k)} for a in attempts][-6:]


WORD = re.compile(r"[a-z][a-z0-9-]{3,}")
STOP = frozenset({"with", "from", "that", "this", "their", "there", "into", "under", "over", "using", "based",
                  "towards", "between", "through", "when", "what", "which", "study", "analysis", "paper"})


def candidates(unused, papers, subject, body, journal_key, journal_text):
    """The papers a model may name: the rules' candidates, else at most five papers whose title
    words or attempt journal the letter mentions."""
    by_id = {str(p.get("paper_id")): p for p in papers or () if p.get("paper_id")}
    chosen = [by_id[p] for p in unused.paper_ids if p in by_id]
    if not chosen:
        content = fold(subject + "\n" + body).casefold()
        named = journal_key(journal_text(content))
        words = set(WORD.findall(content))
        scored = []
        for entry in by_id.values():
            title = set(WORD.findall(str(entry.get("title") or "").casefold())) - STOP
            ratio = len(title & words) / len(title) if title else 0.0
            journals = {journal_key(a.get("journal")) for a in _attempts(entry)} | {journal_key(entry.get("target_journal"))}
            journal_named = any(len(key) >= 6 and key in named for key in journals)
            if ratio >= 0.6 or (journal_named and ratio >= 0.3):
                scored.append((ratio + journal_named, entry))
        chosen = [entry for _, entry in sorted(scored, key=lambda item: -item[0])[:MAX_CANDIDATES]]
    return [{"paper_id": str(e.get("paper_id")), "title": str(e.get("title") or "")[:300], "attempts": _attempts(e)}
            for e in chosen]


def brief(raw, unused, papers=()):
    """What the model reads of one letter (JSON-ready), or None for a letter beyond reading.

    Never the whole letter, its recipients or the sender's name: the subject and the
    decision-related sentences, redacted (:func:`redact`), at most ``MAX_SENTENCES`` and
    ``MAX_CHARS``; the sender's domain; the manuscript numbers; the candidate papers; the rules'
    reading (kind, reason, candidate decisions)."""
    from paper_writing import journal_mail as jm  # journal_mail imports this module
    if unused.kind not in TRIAGE_KINDS:
        return None
    message = BytesParser(policy=policy.default).parsebytes(raw)
    subject, body = jm.message_text(message)
    subject = fold(subject)
    every = sentences(body, jm.BOILERPLATE)
    chosen, size = [], 0
    for index, sentence in enumerate(every):
        if index >= 3 and not (CUE.search(sentence) or jm.DECISION_CUE.search(sentence)):
            continue
        if sentence in chosen:
            continue
        if len(chosen) >= MAX_SENTENCES or size + len(sentence) > MAX_CHARS:
            break
        chosen.append(sentence)
        size += len(sentence)
    numbers = []
    for text in (subject, body):
        for found in jm.LABELLED_NUMBER.finditer(text or ""):
            numbers.append(found["id"].rstrip(".-"))
    numbers.insert(0, jm.manuscript_number(subject, body))
    sender = parseaddr(str(message.get("From", "")))[1]
    moment = getattr(message.get("Date"), "datetime", None)
    return {
        "subject": redact(subject)[:300],
        "sender_domain": sender.rpartition("@")[2].casefold()[:100] if "@" in sender else "",
        "received_at": moment.isoformat() if moment else None,
        "manuscript_ids": list(dict.fromkeys(n for n in numbers if n))[:5],
        "sentences": chosen,
        "rules": {"kind": unused.kind, "reason": unused.reason[:300], "decisions": list(unused.decisions)},
        "candidates": candidates(unused, papers, subject, body, jm.journal_key, jm.journal_text),
    }


def waiting(model_state, queued_at, now=None):
    """True while a letter's model reading is still expected (the digest holds it back)."""
    if model_state not in WAITING_STATES:
        return False
    try:
        queued = datetime.fromisoformat(str(queued_at))
    except ValueError:
        return False
    if queued.tzinfo is None:
        queued = queued.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - queued < WAIT


def check(letter, answer):
    """``(verdict, None)`` for an answer that holds up, else ``(None, problem)``.

    The answer must match the schema of the Skill (openlabs-journal-mail-triage) exactly, name
    a candidate paper or none, and every evidence quote must occur word for word (whitespace
    folded) in the brief's subject or one of its sentences."""
    if not isinstance(letter, dict):
        return None, "无可核对的信件摘要"
    if not isinstance(answer, dict):
        return None, "模型未给出结论"
    if answer.get("error"):
        return None, str(answer["error"])[:200]
    keys = set(answer)
    if not ANSWER_KEYS <= keys or keys - ANSWER_KEYS - OPTIONAL_KEYS:
        return None, "结论格式不符（字段）"
    category = answer["category"]
    if category not in CATEGORIES:
        return None, "结论格式不符（category）"
    known = {c.get("paper_id") for c in letter.get("candidates") or ()}
    paper_id = answer["paper_id"]
    if paper_id is not None and (not isinstance(paper_id, str) or paper_id not in known):
        return None, "结论格式不符（paper_id 不在候选论文中）"
    number = answer["manuscript_id"]
    if number is not None and (not isinstance(number, str) or not 0 < len(number) <= 80):
        return None, "结论格式不符（manuscript_id）"
    due = answer["due"]
    if due is not None:
        try:
            if not isinstance(due, str) or datetime.strptime(due, "%Y-%m-%d").strftime("%Y-%m-%d") != due:
                raise ValueError
        except ValueError:
            return None, "结论格式不符（due）"
    confidence = answer["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        return None, "结论格式不符（confidence）"
    quotes = answer["evidence_quotes"]
    if (not isinstance(quotes, list) or not 1 <= len(quotes) <= 3
            or any(not isinstance(q, str) or not 8 <= len(fold(q)) <= 400 for q in quotes)):
        return None, "结论格式不符（evidence_quotes）"
    note = answer.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > 300):
        return None, "结论格式不符（note）"
    texts = [fold(letter.get("subject"))] + [fold(s) for s in letter.get("sentences") or ()]
    for quote in quotes:
        if not any(fold(quote) in text for text in texts):
            return None, "引文不在原信中"
    return {"category": category, "paper_id": paper_id, "manuscript_id": number, "due": due,
            "confidence": float(confidence), "evidence_quotes": [fold(q) for q in quotes]}, None


def reading(row_brief, model_state, model):
    """(verdict or None, the digest's line about the model) for one review row."""
    if model_state is None:
        return None, ""
    if model_state in WAITING_STATES or model_state == "expired":
        return None, "模型无结论（未在等待时间内完成）"
    try:
        letter = json.loads(row_brief) if row_brief else None
        answer = json.loads(model) if model else None
    except ValueError:
        return None, "模型无结论（结论无法读取）"
    verdict, problem = check(letter, answer)
    if verdict is None:
        return None, f"模型无结论（{problem}）"
    parts = [f"系统判断为 {CATEGORIES[verdict['category']]}"
             f"（依据原句：{'；'.join('「' + q + '」' for q in verdict['evidence_quotes'])}）"]
    if verdict["paper_id"]:
        parts.append(f"论文 {verdict['paper_id']}")
    if verdict["manuscript_id"]:
        parts.append(f"稿号 {verdict['manuscript_id']}")
    if verdict["due"]:
        parts.append(f"期限 {verdict['due']}")
    parts.append(f"置信度 {verdict['confidence']:.2f}")
    return verdict, "，".join(parts) + "。这是模型的判断，网站和台账均未改动，请在管理网站核对登记"


def handler_worthy(verdict):
    return bool(verdict and verdict["paper_id"] and verdict["category"] in HANDLER_CATEGORIES
                and verdict["confidence"] >= HANDLER_MIN_CONFIDENCE)
