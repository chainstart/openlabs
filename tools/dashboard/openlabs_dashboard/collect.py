"""Read-only aggregation of OpenLabs state for the researcher dashboard.

Sources (never written):
- ``openlabs-data/registry/papers/*.yaml`` and ``registry/settings.yaml``;
- ``openlabs-data/registry/journal-rejections.json`` (API-sourced team ledger);
- an optional management-site paper-detail snapshot (submission attempts, review rounds);
- ``openlabs-data/workspaces/<domain>/...`` project directories;
- ``openlabs-database/live/factory.sqlite`` (or ``$OPENLABS_DATABASE_ROOT/live/factory.sqlite``)
  opened in SQLite read-only mode.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

URL = re.compile(r"https?://[^\s\"'<>\\{}|`)\]]+|\b10\.\d{4,9}/[^\s\"'<>\\{}|`)\]]+")
DOMAIN_LABELS = {"ai": "人工智能", "biology": "生物医学", "math": "数学", "physics": "物理",
                 "materials": "材料", "cs": "计算机", "se": "软件工程", "quant": "量化金融"}
STAGES = ["研究中", "写作中", "待投稿", "在审", "返修中", "已录用", "被拒待处理", "已停止"]
MAX_TEXT_BYTES = 2_000_000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_text(path: Path) -> str:
    try:
        if path.is_file() and path.stat().st_size <= MAX_TEXT_BYTES:
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def _read_json(path: Path) -> Any:
    text = _read_text(path)
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return None


def _yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(_read_text(path)) or {}
    except yaml.YAMLError:
        return {}
    return value if isinstance(value, dict) else {}


def _local(workspace: Path, path: Any) -> Path | None:
    """Map absolute paths recorded on another machine to this workspace."""
    if not isinstance(path, str) or not path:
        return None
    for marker in ("openlabs-data/", "openlabs-artifacts/", "maintenance/"):
        if marker in path:
            return workspace / (marker + path.split(marker, 1)[1])
    candidate = Path(path)
    return candidate if candidate.is_absolute() else workspace / "openlabs-data" / path


# ---------------------------------------------------------------- TeX helpers

def _strip_tex(text: str) -> str:
    text = re.sub(r"(?<!\\)%.*", "", text)
    text = re.sub(r"\\(?:cite[tp]?|ref|eqref|label)\*?\{[^}]*\}", "", text)
    text = re.sub(r"\\(?:emph|textbf|textit|mathrm|text)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}$~]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tex_tree(main: Path, limit: int = 40) -> str:
    seen: set[Path] = set()
    parts: list[str] = []

    def visit(path: Path) -> None:
        if path in seen or len(seen) >= limit:
            return
        seen.add(path)
        text = _read_text(path)
        parts.append(text)
        for name in re.findall(r"\\(?:input|include)\s*\{([^}]+)\}", text):
            child = (path.parent / name)
            child = child if child.suffix == ".tex" else child.with_suffix(".tex")
            if child.is_file():
                visit(child)

    if main.is_file():
        visit(main)
    return "\n".join(parts)


def manuscript_summary(main: Path) -> dict[str, Any]:
    tex = _tex_tree(main)
    abstract = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", tex, re.DOTALL)
    availability = re.search(
        r"\\(?:sub)*section\*?\{[^}]*(?:data|code)[^}]*availab[^}]*\}(.*?)(?=\\(?:sub)*section\*?\{|\\end\{document\}|\\bibliography)",
        tex, re.DOTALL | re.IGNORECASE)
    data_text = availability.group(1) if availability else ""
    links = sorted({m.rstrip(".,;") for m in URL.findall(data_text)})
    return {
        "abstract": _strip_tex(abstract.group(1))[:3000] if abstract else "",
        "data_availability": _strip_tex(data_text)[:1500],
        "data_links": links[:20],
    }


# ---------------------------------------------------------------- submissions

def find_site_snapshot(workspace: Path) -> Path | None:
    candidates: list[Path] = []
    root = workspace / "maintenance"
    if root.is_dir():
        for child in root.iterdir():
            for name in ("website-details.json", "site-papers.json", "site-after.json"):
                path = child / name
                if path.is_file():
                    candidates.append(path)
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def load_site_papers(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = _read_json(path) if path.stat().st_size <= MAX_TEXT_BYTES else json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("data", data.get("papers"))
    return [p for p in data or [] if isinstance(p, dict) and p.get("paper_id")]


def _attempts_from_site(site: dict[str, Any]) -> list[dict[str, Any]]:
    rounds: dict[str, list[dict[str, Any]]] = {}
    for item in site.get("review_rounds") or []:
        rounds.setdefault(str(item.get("attempt_id")), []).append({
            "decision": item.get("decision"), "received_at": item.get("received_at"),
            "due_at": item.get("due_at"), "response_submitted_at": item.get("response_submitted_at")})
    events: dict[str, str] = {}
    for item in site.get("submission_events") or []:
        payload = item.get("payload") or {}
        if item.get("event_type") == "rejected" and isinstance(payload, dict):
            for key in ("reason_summary", "comment_to_author", "reason", "editor_comments"):
                if isinstance(payload.get(key), str) and payload[key].strip():
                    events[str(item.get("attempt_id"))] = payload[key].strip()
                    break
    rows = []
    for attempt in site.get("submission_attempts") or []:
        aid = str(attempt.get("id"))
        rows.append({"venue": attempt.get("journal_name"), "status": attempt.get("status"),
                     "manuscript_number": attempt.get("manuscript_number"),
                     "submitted_at": attempt.get("submitted_at"), "closed_at": attempt.get("closed_at"),
                     "reason": events.get(aid, ""), "rounds": rounds.get(aid, [])})
    rows.sort(key=lambda r: str(r.get("submitted_at") or r.get("closed_at") or ""))
    return rows


def _attempts_from_ledger(pid: str, ledger: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [{"venue": r.get("journal"), "status": "rejected", "manuscript_number": r.get("manuscript_number"),
             "submitted_at": r.get("submitted_at"), "closed_at": r.get("rejected_at"),
             "reason": r.get("reason_summary", ""), "rounds": []}
            for r in ledger.get("rejections", []) if r.get("paper_id") == pid]
    rows += [{"venue": r.get("journal"), "status": r.get("status"), "submitted_at": r.get("submitted_at"),
              "closed_at": None, "reason": "", "rounds": []}
             for r in ledger.get("active_submissions", []) if r.get("paper_id") == pid]
    return rows


def paper_stage(paper: dict[str, Any], attempts: list[dict[str, Any]], lifecycle: str | None) -> str:
    statuses = [a.get("status") for a in attempts]
    if any(s in {"accepted", "published"} for s in statuses) or lifecycle in {"accepted", "published"}:
        return "已录用"
    pending_revision = any(
        r.get("decision") in {"major_revision", "minor_revision", "revise_resubmit"} and not r.get("response_submitted_at")
        for a in attempts if a.get("status") not in {"resubmitted", "rejected"} for r in a.get("rounds", []))
    if pending_revision or any(s in {"revision_requested", "revision_preparing"} for s in statuses):
        return "返修中"
    if any(s in {"submitted", "under_review", "resubmitted", "editorial_check"} for s in statuses):
        return "在审"
    release = (paper.get("writing_release") or {}).get("status") if isinstance(paper.get("writing_release"), dict) else None
    freeze = paper.get("freeze_decision") if isinstance(paper.get("freeze_decision"), dict) else {}
    if lifecycle == "closed" or paper.get("record_status") == "frozen" or freeze.get("status") == "frozen":
        return "已停止"
    if "rejected" in statuses:
        return "被拒待处理"
    if lifecycle == "ready_to_submit" or release == "ready":
        return "待投稿"
    if paper.get("record_status") in {"research", "candidate"}:
        return "研究中"
    return "写作中"


def _venue(paper: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    escalation = (policy.get("venue_eligibility") or {}).get("escalation") or {}
    if paper.get("target_conference"):
        ccf = paper.get("target_conference_ccf") or {}
        rank = str(ccf.get("rank") or "").upper()
        return {"type": "conference", "name": paper.get("target_conference"), "level": f"CCF-{rank}" if rank else "CCF 未登记",
                "category": ccf.get("category"), "fee": paper.get("target_conference_fee_policy"),
                "escalation": rank in set(escalation.get("ccf_ranks", ["A"])),
                "checked_at": paper.get("target_conference_checked_at")}
    tier = paper.get("target_journal_tier")
    indexing = paper.get("target_journal_indexing") or {}
    return {"type": paper.get("venue_type") or "journal", "name": paper.get("target_journal"),
            "level": f"中科院{tier}区" if tier else "分区未登记",
            "category": paper.get("target_journal_ranking_category"),
            "indexes": indexing.get("indexes") if isinstance(indexing, dict) else None,
            "fee": paper.get("target_journal_fee_policy"),
            "escalation": tier in set(escalation.get("journal_tiers", [1, 2])),
            "checked_at": paper.get("target_journal_checked_at")}


def collect_papers(workspace: Path, site_papers: list[dict[str, Any]], ledger: dict[str, Any],
                   policy: dict[str, Any]) -> list[dict[str, Any]]:
    data = workspace / "openlabs-data"
    site = {p["paper_id"]: p for p in site_papers}
    rows = []
    for path in sorted((data / "registry" / "papers").glob("*.yaml")):
        paper = _yaml(path)
        pid = str(paper.get("paper_id") or path.stem)
        detail = site.get(pid)
        attempts = _attempts_from_site(detail) if detail else _attempts_from_ledger(pid, ledger)
        lifecycle = detail.get("lifecycle_status") if detail else None
        main = data / str(paper.get("latest_source") or f"papers/{pid}/manuscript/main.tex")
        summary = manuscript_summary(main)
        sources = paper.get("data_sources") if isinstance(paper.get("data_sources"), list) else []
        findings = paper.get("key_findings") if isinstance(paper.get("key_findings"), list) else []
        validation = paper.get("scientific_validation") if isinstance(paper.get("scientific_validation"), dict) else {}
        release = paper.get("writing_release") if isinstance(paper.get("writing_release"), dict) else {}
        authors = [a.get("name_zh") or a.get("name") for a in paper.get("authors") or [] if isinstance(a, dict)]
        venue = _venue(paper, policy)
        if not venue.get("name"):
            latest_attempt = attempts[-1] if attempts else {}
            venue["name"] = (detail or {}).get("target_journal") or latest_attempt.get("venue")
            venue["unregistered"] = True
        rows.append({
            "paper_id": pid, "display_id": paper.get("display_id") or pid,
            "title": str(paper.get("title") or (detail or {}).get("title") or pid).strip(),
            "domain": paper.get("domain"), "domain_label": DOMAIN_LABELS.get(str(paper.get("domain")), paper.get("domain")),
            "subdomain": paper.get("subdomain"), "created_at": str(paper.get("created_at") or ""),
            "updated_at": str(paper.get("status_updated_at") or (detail or {}).get("updated_at") or ""),
            "version": paper.get("version"), "stage": paper_stage(paper, attempts, lifecycle),
            "lifecycle": lifecycle, "writing_release": release.get("status"),
            "research_track": paper.get("research_track"), "validation": validation.get("status"),
            "validation_note": validation.get("promotion_blocker"),
            "venue": venue, "attempts": attempts,
            "escalation_record": paper.get("target_escalation"),
            "data_sources": sources, "data_sources_registered": bool(sources),
            "data_links": summary["data_links"], "data_availability": summary["data_availability"],
            "key_findings": [str(x) for x in findings], "abstract": summary["abstract"],
            "authors": authors, "pdf": paper.get("latest_pdf"),
        })
    return rows


# ---------------------------------------------------------------- research projects

def _first_paragraph(markdown: str) -> tuple[str, str]:
    title, body = "", []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not title and stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            continue
        if stripped.startswith("#") and body:
            break
        if stripped and not stripped.startswith(("|", "```", "-", "*", ">")):
            body.append(stripped)
        elif body:
            break
    return title, re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", " ".join(body))[:1200]


def _project_dirs(workspace: Path) -> Iterable[tuple[str, Path]]:
    root = workspace / "openlabs-data" / "workspaces"
    if not root.is_dir():
        return
    instance = os.environ.get("OPENLABS_INSTANCE", "").strip()
    for domain_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if instance:
            # A named instance shows only its own projects (and their campaigns).
            projects = domain_dir / "instances" / instance / "projects"
            if projects.is_dir():
                for project in sorted(p for p in projects.iterdir() if p.is_dir()):
                    yield domain_dir.name, project
            continue
        for child in sorted(p for p in domain_dir.iterdir() if p.is_dir()):
            if child.name == "instances":
                continue
            if child.name == "projects":
                for project in sorted(p for p in child.iterdir() if p.is_dir()):
                    yield domain_dir.name, project
            elif child.name not in {"plans", "__pycache__"}:
                yield domain_dir.name, child


def _latest_mtime(path: Path) -> float:
    try:
        times = [path.stat().st_mtime] + [c.stat().st_mtime for c in path.iterdir()]
    except OSError:
        return 0.0
    return max(times)


def collect_projects(workspace: Path, campaigns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path = {}
    for campaign in campaigns:
        local = _local(workspace, campaign.get("state_path"))
        if local is not None:
            by_path.setdefault(str(local), []).append(campaign)
    rows = []
    now = datetime.now(timezone.utc).timestamp()
    for domain, path in _project_dirs(workspace):
        project = _read_json(path / "project.json") or {}
        state = _read_json(path / "research_state.json") or {}
        readme = next((p for p in (path / "README.zh.md", path / "README.md", path / "PROTOCOL.md",
                                   path / "RESULTS.md") if p.is_file()), None)
        title, summary = _first_paragraph(_read_text(readme)) if readme else ("", "")
        latest_text = ""
        latest = state.get("latest_report") if isinstance(state, dict) else None
        if isinstance(latest, str) and latest and (path / latest).is_file():
            _, latest_text = _first_paragraph(_read_text(path / latest))
        links: set[str] = set()
        for name in ("data-manifest.json", "public-inputs.json", "data_manifest.json", "inputs.json"):
            links.update(URL.findall(_read_text(path / name)))
        if readme:
            links.update(URL.findall(_read_text(readme)))
        linked = [c for key, values in by_path.items() if key.startswith(str(path)) for c in values]
        mtime = _latest_mtime(path)
        status = (state.get("status") if isinstance(state, dict) else None) or project.get("status") or (
            linked[0]["status"] if linked else None)
        rows.append({
            "id": project.get("project_id") or path.name, "domain": domain,
            "domain_label": DOMAIN_LABELS.get(domain, domain),
            "path": path.relative_to(workspace).as_posix(),
            "title": title or (project.get("workstreams") or [{}])[0].get("title") or path.name,
            "objective": project.get("objective") or "", "status": status,
            "paper_candidate": state.get("paper_candidate") if isinstance(state, dict) else None,
            "summary": summary, "latest_progress": latest_text,
            "data_links": sorted(l.rstrip(".,;") for l in links)[:15],
            "updated_at": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds") if mtime else "",
            "active": bool(mtime) and now - mtime < 14 * 86400,
            "campaigns": [{"id": c["campaign_id"], "status": c["status"], "agent_hours": c["agent_hours"]} for c in linked],
        })
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows


def database_root(workspace: Path) -> Path:
    """Runtime database directory: OPENLABS_DATABASE_ROOT (a separate instance) or the default."""

    configured = os.environ.get("OPENLABS_DATABASE_ROOT", "").strip()
    return Path(configured).expanduser() if configured else workspace / "openlabs-database"


def collect_campaigns(workspace: Path) -> dict[str, Any]:
    path = database_root(workspace) / "live" / "factory.sqlite"
    if not path.is_file():
        return {"available": False, "campaigns": [], "tasks": {}}
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        try:
            campaigns = [
                {"campaign_id": r[0], "domain": r[1], "title": r[2], "status": r[3], "state_path": r[4],
                 "updated_at": r[5], "agent_hours": round((r[6] or 0) / 3600, 1)}
                for r in connection.execute(
                    "select campaign_id, domain, title, status, state_path, updated_at, agent_seconds_used "
                    "from campaigns order by updated_at desc")]
            tasks = dict(connection.execute("select status, count(*) from tasks group by status").fetchall())
            running = [{"task_id": r[0], "campaign_id": r[1], "objective": (r[2] or "")[:300], "status": r[3]}
                       for r in connection.execute(
                           "select task_id, campaign_id, objective, status from tasks "
                           "where status in ('queued','leased','running') order by priority desc limit 50")]
            last = connection.execute("select max(created_at) from tasks").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return {"available": False, "error": str(exc), "campaigns": [], "tasks": {}}
    return {"available": True, "campaigns": campaigns, "tasks": tasks, "open_tasks": running, "last_task_created_at": last}


# ---------------------------------------------------------------- assembly

def build_state(workspace: Path, *, site_snapshot: Path | None = None,
                site_papers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    workspace = workspace.resolve()
    data = workspace / "openlabs-data"
    settings = _yaml(data / "registry" / "settings.yaml")
    policy = settings.get("journal_target_policy") or {}
    ledger = _read_json(data / "registry" / "journal-rejections.json") or {}
    source = {"kind": "ledger_only", "path": None, "modified_at": None}
    if site_papers is not None:
        source = {"kind": "management_api", "path": None, "modified_at": now_iso()}
    else:
        snapshot = site_snapshot or find_site_snapshot(workspace)
        site_papers = load_site_papers(snapshot) if snapshot else []
        if snapshot:
            source = {"kind": "snapshot", "path": snapshot.relative_to(workspace).as_posix()
                      if snapshot.is_relative_to(workspace) else str(snapshot),
                      "modified_at": datetime.fromtimestamp(snapshot.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}
    factory = collect_campaigns(workspace)
    papers = collect_papers(workspace, site_papers, ledger, policy)
    projects = collect_projects(workspace, factory["campaigns"])
    monitor: dict[str, Any] = {}
    try:
        from paper_writing.submission_monitor import build_report
        monitor = build_report(site_papers, thresholds=settings.get("submission_monitor")) if site_papers else {}
    except ImportError:
        monitor = {}
    attempts = [a for p in papers for a in p["attempts"]]
    stage_counts = {stage: sum(p["stage"] == stage for p in papers) for stage in STAGES}
    eligibility = policy.get("venue_eligibility") or {}
    return {
        "generated_at": now_iso(), "workspace": str(workspace), "submission_source": source,
        "ledger_updated_at": ledger.get("updated_at"),
        "policy": {
            "journal": eligibility.get("journal"), "conference": eligibility.get("conference"),
            "escalation": eligibility.get("escalation"), "new_selection_tiers": policy.get("new_selection_tiers"),
            "cadence": settings.get("submission_cadence"), "portfolio": settings.get("research_portfolio"),
        },
        "summary": {
            "papers": len(papers), "stages": stage_counts,
            "attempts": len(attempts),
            "rejections": sum(a.get("status") == "rejected" for a in attempts),
            "accepted": sum(a.get("status") in {"accepted", "published"} for a in attempts),
            "active_projects": sum(p["active"] for p in projects), "projects": len(projects),
            "papers_without_registered_data": sum(1 for p in papers if p["domain"] != "math" and not p["data_sources_registered"]),
        },
        "papers": papers, "projects": projects, "factory": factory, "monitor": monitor,
    }


def default_workspace() -> Path:
    env = os.environ.get("OPENLABS_WORKSPACE")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3].parent
