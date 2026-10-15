"""Shared team rejection ledger, refreshed from the management site's read-only API."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "openlabs.journal_rejections.v1"
DEFAULT_PATH = "registry/journal-rejections.json"
ACTIVE = {"submitted", "editorial_check", "under_review", "revision_preparing",
          "revision_requested", "resubmitted", "accepted", "published"}
ALIASES = {
    "EJC": "European Journal of Combinatorics",
    "Eur. J. Comb.": "European Journal of Combinatorics",
    "European J. Combin.": "European Journal of Combinatorics",
    "Electronic Journal of Combinatorics": "The Electronic Journal of Combinatorics",
    "Electron. J. Combin.": "The Electronic Journal of Combinatorics",
    "ElJC": "The Electronic Journal of Combinatorics",
    "JCTB": "Journal of Combinatorial Theory, Series B",
    "Journal of Combinatorial Theory B": "Journal of Combinatorial Theory, Series B",
    "J. Combin. Theory Ser. B": "Journal of Combinatorial Theory, Series B",
    "JCTA": "Journal of Combinatorial Theory, Series A",
    "Journal of Combinatorial Theory A": "Journal of Combinatorial Theory, Series A",
    "J. Combin. Theory Ser. A": "Journal of Combinatorial Theory, Series A",
    "DM": "Discrete Mathematics",
    "AAM": "Advances in Applied Mathematics",
    "Adv. Appl. Math.": "Advances in Applied Mathematics",
    "Forum Math.": "Forum Mathematicum",
    "Mach. Learn.": "Machine Learning",
    "SIDMA": "SIAM Journal on Discrete Mathematics",
    "SIAM J. Discrete Math.": "SIAM Journal on Discrete Mathematics",
    "JACO": "Journal of Algebraic Combinatorics",
    "JGT": "Journal of Graph Theory",
    "AJC": "Australasian Journal of Combinatorics",
    "GCOM": "Graphs and Combinatorics",
    "DMGT": "Discussiones Mathematicae Graph Theory",
    "JNT": "Journal of Number Theory",
    "JAMC": "Journal of Applied Mathematics and Computing",
    "PRD": "Physical Review D",
    "Ann. Comb.": "Annals of Combinatorics",
}


def journal_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.casefold()).removeprefix("the")


def canonical_journal(name: str, aliases: Mapping[str, str] | None = None) -> str:
    names = {journal_key(k): v for k, v in {**ALIASES, **(aliases or {})}.items()}
    return names.get(journal_key(name), name.strip())


def _policy(root: Path, policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if policy is None:
        from paper_writing.registry import load_registry_settings
        policy = load_registry_settings(root).get("journal_target_policy", {})
    config = dict((policy or {}).get("team_rejection_history") or {})
    exclude = config.get("exclude_after_distinct_papers", 3)
    caution = config.get("caution_after_distinct_papers", 2)
    age = config.get("max_age_days", 7)
    if any(type(n) is not int for n in (exclude, caution, age)) or not 1 <= caution < exclude or age < 1:
        raise ValueError("Invalid team rejection history thresholds or max_age_days")
    config.update(exclude_after_distinct_papers=exclude,
                  caution_after_distinct_papers=caution, max_age_days=age)
    return config


def _path(root: Path, config: Mapping[str, Any]) -> Path:
    path = (root / config.get("ledger_path", DEFAULT_PATH)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Team rejection ledger must be inside the data repository")
    return path


def load_history(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA:
            raise ValueError("unsupported schema")
        datetime.fromisoformat(data["updated_at"]).astimezone(timezone.utc)
        if not isinstance(data["rejections"], list) or not isinstance(data["active_submissions"], list):
            raise ValueError("rows must be lists")
        seen = set()
        for row in data["rejections"]:
            if any(not isinstance(row.get(k), str) or not row[k].strip()
                   for k in ("attempt_id", "paper_id", "journal", "source")):
                raise ValueError("incomplete rejection row")
            if row.get("venue_type") not in {"journal", "conference"}:
                raise ValueError("invalid venue type")
            if row["attempt_id"] in seen:
                raise ValueError("duplicate submission attempt")
            seen.add(row["attempt_id"])
        for row in data["active_submissions"]:
            if not all(row.get(k) for k in ("paper_id", "journal", "attempt_id")) or row.get("status") not in ACTIVE:
                raise ValueError("invalid active submission row")
        return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"Team rejection ledger unavailable/invalid: {path}; run journal-history sync ({exc})") from exc


def _result(data: Mapping[str, Any], name: str, config: Mapping[str, Any]) -> dict[str, Any]:
    canonical = canonical_journal(name, config.get("aliases"))
    key = journal_key(canonical)
    rows = [r for r in data["rejections"] if r["venue_type"] == "journal"
            and journal_key(canonical_journal(r["journal"], config.get("aliases"))) == key]
    count = len({r["paper_id"] for r in rows})
    status = ("excluded" if count >= config["exclude_after_distinct_papers"] else
              "caution" if count >= config["caution_after_distinct_papers"] else "eligible")
    return {"journal": canonical, "status": status, "eligible": status != "excluded",
            "distinct_rejected_papers": count, "rejected_attempts": len(rows),
            "ledger_updated_at": data["updated_at"], "rejections": rows}


def check_journal(root: Path, name: str, *, policy: Mapping[str, Any] | None = None,
                  now: datetime | None = None) -> dict[str, Any]:
    config = _policy(root, policy)
    path = _path(root, config)
    data = load_history(path)
    updated = datetime.fromisoformat(data["updated_at"])
    if updated.tzinfo is None:
        raise ValueError("Team rejection ledger updated_at must include timezone")
    elapsed = ((now or datetime.now(timezone.utc)) - updated).total_seconds()
    if elapsed < -300 or elapsed > config["max_age_days"] * 86400:
        raise ValueError("Team rejection ledger is stale or future-dated; run journal-history sync")
    result = _result(data, name, config)
    result["ledger_path"] = path.relative_to(root.resolve()).as_posix()
    result["ledger_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def guard_target(root: Path, paper: Mapping[str, Any], *, policy: Mapping[str, Any] | None = None,
                 preserve_historical_record: bool = False) -> None:
    """Block new targets at excluded venues; keep actual ongoing submissions and history."""
    config = _policy(root, policy)
    if not config.get("enabled") or paper.get("venue_type", "journal") != "journal" or not paper.get("target_journal"):
        return
    name = str(paper["target_journal"])
    result = check_journal(root, name, policy=policy)
    if result["status"] != "excluded":
        return
    data = load_history(_path(root, config))
    pid = str(paper.get("paper_id") or "")
    key = journal_key(canonical_journal(name, config.get("aliases")))
    # Only an API-sourced ongoing attempt exempts an existing revision from this new-selection rule.
    if any(a["paper_id"] == pid and journal_key(canonical_journal(a["journal"], config.get("aliases"))) == key
           for a in data["active_submissions"]):
        return
    if preserve_historical_record and any(r["paper_id"] == pid for r in result["rejections"]):
        return
    raise ValueError(f"Team rejection history excludes {name}: {result['distinct_rejected_papers']} distinct papers "
                     f"(limit {config['exclude_after_distinct_papers']}); select another journal. "
                     f"See {result['ledger_path']}")


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh_history(root: Path, papers: list[dict[str, Any]], *, source: str,
                    checked_at: str | None = None) -> dict[str, Any]:
    """Merge sourced refusals without erasing older evidence; regenerate CSV and summary."""
    config = _policy(root)
    path = _path(root, config)
    old_bytes = path.read_bytes() if path.exists() else None
    old = load_history(path) if path.exists() else {"rejections": []}
    rows = {r["attempt_id"]: dict(r) for r in old["rejections"]}
    active = []
    for paper in papers:
        pid = paper["paper_id"]
        for attempt in paper.get("submission_attempts", []):
            name = canonical_journal(attempt["journal_name"], config.get("aliases"))
            aid = attempt["id"]
            if attempt["status"] in ACTIVE:
                active.append({"paper_id": pid, "journal": name, "attempt_id": aid, "status": attempt["status"]})
            if attempt["status"] != "rejected":
                continue
            events = [e for e in paper.get("submission_events", [])
                      if e.get("attempt_id") == aid and e.get("event_type") == "rejected"]
            event = max(events, key=lambda e: str(e.get("occurred_at") or ""), default={})
            payload = event.get("payload") or {}
            reason = next((payload[k] for k in ("reason_summary", "comment_to_author", "reason", "editor_comments")
                           if isinstance(payload.get(k), str) and payload[k].strip()), "")
            row = {"attempt_id": aid, "paper_id": pid, "title": paper.get("title", ""),
                   "journal": name, "venue_type": "conference" if re.search(r"\b(PRICAI|ICONIP)\b", name, re.I) else "journal",
                   "manuscript_number": attempt.get("manuscript_number") or "",
                   "rejected_at": event.get("occurred_at") or attempt.get("closed_at") or "",
                   "reason_summary": reason, "source_event_id": event.get("id") or "",
                   "evidence_level": "decision_event" if event else "management_status_only",
                   "source": f"management:papers/{pid}/submission-attempts/{aid}"}
            previous = rows.get(aid, {})
            if previous and (previous["paper_id"] != pid or journal_key(previous["journal"]) != journal_key(name)):
                raise ValueError(f"Conflicting identity for submission attempt {aid}")
            for field in ("reason_summary", "source_event_id", "rejected_at", "manuscript_number"):
                if not row[field] and previous.get(field):
                    row[field] = previous[field]
            if row["source_event_id"]:
                row["evidence_level"] = "decision_event"
            rows[aid] = row
    data = {"schema_version": SCHEMA, "updated_at": checked_at or datetime.now(timezone.utc).isoformat(),
            "source": source, "source_papers": len(papers),
            "source_snapshot_sha256": hashlib.sha256(json.dumps(papers, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "rejections": sorted(rows.values(), key=lambda r: (journal_key(r["journal"]), r["rejected_at"], r["attempt_id"])),
            "active_submissions": active}
    if (path.read_bytes() if path.exists() else None) != old_bytes:
        raise ValueError("Concurrent journal ledger update; refresh again")
    _atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    load_history(path)
    fields = ["journal", "venue_type", "paper_id", "title", "manuscript_number", "rejected_at",
              "reason_summary", "evidence_level", "attempt_id", "source_event_id", "source"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows({k: r[k] for k in fields} for r in data["rejections"])
    _atomic(path.with_suffix(".csv"), output.getvalue())
    summaries = [_result(data, name, config) for name in sorted({r["journal"] for r in rows.values() if r["venue_type"] == "journal"})]
    summaries.sort(key=lambda s: (-s["distinct_rejected_papers"], s["journal"]))
    text = ["# 团队期刊拒稿汇总", "", f"更新时间：{data['updated_at']}。明细见同目录 journal-rejections.csv；JSON 为唯一数据源。", "",
            "| 期刊 | 被拒论文数 | 拒稿轮次 | 新选刊处理 |", "|---|---:|---:|---|"]
    labels = {"excluded": "排除", "caution": "谨慎备选", "eligible": "继续按范围与贡献评估"}
    text += [f"| {s['journal']} | {s['distinct_rejected_papers']} | {s['rejected_attempts']} | {labels[s['status']]} |" for s in summaries]
    text += ["", "会议明细保留在总表中，不计入期刊排除次数。缺少原始决定的记录明确标为 management_status_only；不会补写拒稿原因。", ""]
    _atomic(path.with_suffix(".md"), "\n".join(text))
    return {"ledger": str(path), "records": len(rows), "journal_rejections": sum(r["venue_type"] == "journal" for r in rows.values()),
            "conference_rejections": sum(r["venue_type"] == "conference" for r in rows.values()), "journals": summaries}


def sync_from_site(root: Path) -> dict[str, Any]:
    from openlabs.config import load_local_environment
    from paper_writing.handoff import ManageApiClient
    load_local_environment()
    url = os.environ["ARA_PAPER_MANAGE_API_URL"]
    with ManageApiClient.from_environment(url) as client:
        listing = client._request("GET", "/v1/papers")
    def read(paper: dict[str, Any]) -> dict[str, Any]:
        with ManageApiClient.from_environment(url) as client:
            return client._request("GET", "/v1/papers/" + paper["paper_id"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        papers = list(pool.map(read, listing))
    return refresh_history(root, papers, source="management_api_read_only")
