"""Submitter assignments on the management site follow the paper's readiness (2026-11-23).

User rule (2026-11-23): "当处于'尚未投稿'状态的论文，不要分配投稿人，只有通过门禁，状态改为
'可投稿'后，才分配投稿人".

The site assigns the second declared author automatically when ``POST /v1/papers`` first
creates a paper (server side; the request has no switch to skip it). This module brings the
active assignment in line with the rule after the fact, through the regular assignment
endpoint ``POST /v1/papers/<id>/assignments`` (the previous row is kept, ``active=false``):

* a paper that is not ``可投稿`` keeps no active submitter: a real assignee is replaced by the
  ARA admin service account (the API key's own account, ``GET /v1/me``) as a placeholder,
  and the placeholder's notes record the default submitter;
* a ``可投稿`` paper without a real assignee gets one: the recorded original submitter first
  (placeholder notes, the 2026-11-23 park receipts, the site's assignment history), else the
  paper's second author;
* papers with submission attempts, or past the pre-submission lifecycle (submitted, under
  review, accepted, published, closed), are never touched;
* papers under a manual-assignment hold are never touched either (2026-11-24, user: "撤回3篇论文
  中的投稿负责人（将负责人从王琪盛改为未分配）"): the submitter is chosen by a person. The hold is
  the registry field ``manual_assignment: {hold: true, ...}`` or, should the shared data checkout
  lag, an active site assignment whose notes carry ``manual_assignment=hold``.

``可投稿`` means: lifecycle ``backlog|assigned|ready_to_submit``, no submission attempt, the
site's ``readiness.ready_for_submission`` true, no held/recalled marker, a current package in
status ``ready`` -- and, when the registry has the paper, its ``writing_release`` is ready
and its version is the delivered package's version (a revision in progress rolls it back
even before the site projection is refreshed).

Admin users see every paper on the site whatever the assignment; that cannot be changed here.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

SCHEMA = "openlabs.site_assignment_sync.v1"
MARKER = "[openlabs-site-assignment]"
PRE_SUBMISSION_LIFECYCLES = frozenset({"backlog", "assigned", "ready_to_submit"})
NOT_READY_REVISION = frozenset({"draft", "blocked", "revision_required"})
HELD_SUBMISSION = frozenset({"on_hold", "abandoned", "withdrawn"})
PARK_RECEIPT_GLOB = "SUBMITTER-HIDE-site-receipt-*.json"
HOLD_NOTE = "manual_assignment=hold"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _registry(root: Path, paper_id: str) -> Mapping[str, Any] | None:
    path = root / "registry" / "papers" / f"{paper_id}.yaml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, Mapping) else None


def _settings_authors(root: Path) -> list[Mapping[str, Any]]:
    path = root / "registry" / "settings.yaml"
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults") if isinstance(data, Mapping) else None
    authors = defaults.get("authors") if isinstance(defaults, Mapping) else None
    return [item for item in authors or [] if isinstance(item, Mapping)]


def _byline(registry: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    authors = (registry or {}).get("authors")
    if isinstance(authors, Mapping):
        authors = authors.get("people")
    return [item for item in authors or [] if isinstance(item, Mapping)]


def classify(paper: Mapping[str, Any],
             registry: Mapping[str, Any] | None) -> tuple[str, list[str]]:
    """``(untouched|ready|not_ready, reasons)`` for one site paper."""

    lifecycle = str(paper.get("lifecycle_status") or "")
    if paper.get("submission_attempts"):
        return "untouched", [f"has submission attempts (lifecycle {lifecycle})"]
    if lifecycle not in PRE_SUBMISSION_LIFECYCLES:
        return "untouched", [f"lifecycle {lifecycle} is past pre-submission"]
    reasons: list[str] = []
    writing = paper.get("writing_metadata") or {}
    if (writing.get("readiness") or {}).get("ready_for_submission") is not True:
        reasons.append("site readiness is not true")
    revision = str((writing.get("llm_revision") or {}).get("status") or "")
    if revision in NOT_READY_REVISION:
        reasons.append(f"site review status {revision}")
    held = str((writing.get("submission") or {}).get("status") or "")
    if held in HELD_SUBMISSION:
        reasons.append(f"site submission status {held}")
    recall = writing.get("polish_recall")
    if (isinstance(recall, Mapping) and recall.get("status") == "recalled_for_revision"
            and recall.get("recalled_package_id") in (None, paper.get("current_package_id"))):
        # A recall applies to the package it recalled; a newer delivered package clears it.
        reasons.append("recalled for revision")
    package = next((item for item in paper.get("packages") or []
                    if item.get("id") == paper.get("current_package_id")), None)
    if package is None:
        reasons.append("no current package")
    elif package.get("status") != "ready":
        reasons.append(f"current package status {package.get('status')}")
    if registry is not None:
        release = registry.get("writing_release") or {}
        if release.get("status") != "ready":
            reasons.append(f"registry writing_release {release.get('status')}")
        version = str(registry.get("version") or "")
        if package is not None and version and version != str(package.get("version") or ""):
            reasons.append(f"registry version {version} is not the delivered "
                           f"{package.get('version')} (revision in progress)")
    return ("not_ready" if reasons else "ready"), reasons


def _user_for_author(author: Mapping[str, Any],
                     users: Iterable[Mapping[str, Any]], placeholder: str) -> Mapping[str, Any] | None:
    candidates = [u for u in users if u.get("active", True) and u.get("id") != placeholder]
    email = str(author.get("email") or "").strip().casefold()
    names = {str(author.get(key) or "").strip().casefold() for key in ("name", "name_zh")} - {""}
    for test in (
        lambda u: email and str(u.get("email") or "").strip().casefold() == email,
        lambda u: str(u.get("display_name") or "").strip().casefold() in names,
        lambda u: names & {str(a).strip().casefold() for a in u.get("author_aliases") or []},
    ):
        matches = [u for u in candidates if test(u)]
        if len(matches) == 1:
            return matches[0]
    return None


def default_submitter(registry: Mapping[str, Any] | None, settings_authors: list[Mapping[str, Any]],
                      users: list[Mapping[str, Any]], placeholder: str) -> dict[str, Any] | None:
    """The paper's second author (byline, else the registry default roster) as a site user."""

    for source, roster in (("byline_second_author", _byline(registry)),
                           ("default_roster_second_author", settings_authors)):
        if len(roster) >= 2:
            user = _user_for_author(roster[1], users, placeholder)
            if user is not None:
                return {"submitter_id": user["id"], "name": user.get("display_name"),
                        "source": source}
    return None


def recorded_submitter(paper: Mapping[str, Any], root: Path, users: list[Mapping[str, Any]],
                       placeholder: str) -> dict[str, Any] | None:
    """The original submitter recorded when the assignment was parked, if any."""

    by_id = {u["id"]: u for u in users if u.get("active", True) and u.get("id") != placeholder}
    rows = list(paper.get("assignments") or [])
    row_owner = {row.get("id"): row.get("submitter_id") for row in rows}

    def hit(submitter_id: Any, source: str) -> dict[str, Any] | None:
        user = by_id.get(str(submitter_id or ""))
        return ({"submitter_id": user["id"], "name": user.get("display_name"), "source": source}
                if user else None)

    for row in rows:
        if not row.get("active") or row.get("submitter_id") != placeholder:
            continue
        notes = str(row.get("notes") or "")
        match = re.search(rf"default_submitter_id=({_UUID})", notes)
        if match and (found := hit(match.group(1), "placeholder_notes")):
            return found
        for assignment_id in re.findall(rf"assignment[ =]?\s*({_UUID})", notes):
            if found := hit(row_owner.get(assignment_id), "placeholder_notes"):
                return found
    receipts = sorted((root / "papers" / str(paper["paper_id"]) / "revisions")
                      .glob(PARK_RECEIPT_GLOB))
    for path in reversed(receipts):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        original = (data.get("original_assignment") or {}).get("submitter_id")
        if found := hit(original, f"park_receipt:{path.name}"):
            return found
    history = [row for row in rows if row.get("submitter_id") in by_id]
    history.sort(key=lambda row: str(row.get("assigned_at") or ""))
    if history:
        return hit(history[-1]["submitter_id"], "site_assignment_history")
    return None


def _holds():
    """openlabs.holds -- the one reader of every hold record (2026-11-25, B3). A pure module
    of the orchestrator package, importable from this checkout without its dependencies."""
    try:
        from openlabs import holds
    except ImportError:
        source = str(Path(__file__).resolve().parents[3] / "orchestrator" / "src")
        if source not in sys.path:
            sys.path.append(source)
        from openlabs import holds
    return holds


def manual_hold(paper: Mapping[str, Any],
                registry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The manual-assignment hold on this paper, if any: a person picks the submitter."""

    return _holds().assignment_hold(registry, list(paper.get("assignments") or []),
                                    scope=str(paper.get("paper_id") or ""))


def _version_key(value: Any) -> tuple[int, ...] | None:
    numbers = re.findall(r"\d+", str(value or ""))
    return tuple(int(n) for n in numbers) if numbers else None


def stale_registry(paper: Mapping[str, Any], registry: Mapping[str, Any] | None) -> str | None:
    """Why the local registry, not the paper, makes a site-ready paper look not ready.

    The shared data checkout can lag origin (agents push from their own worktrees). When the
    site shows ``ready_to_submit`` with every site-side condition met and the registry's
    version is older than the site's current package, the registry is out of date: skip and
    report instead of taking the assignment away (TIC 421871796, 2026-11-23 14:07Z).
    """
    if registry is None or str(paper.get("lifecycle_status") or "") != "ready_to_submit":
        return None
    if classify(paper, None)[0] != "ready":
        return None
    package = next((item for item in paper.get("packages") or []
                    if item.get("id") == paper.get("current_package_id")), None) or {}
    local, site = _version_key(registry.get("version")), _version_key(package.get("version"))
    if local is None or site is None or local >= site:
        return None
    return (f"local registry version {registry.get('version')} is older than the site's current "
            f"package {package.get('version')}; the data checkout is behind, not the paper")


def plan_paper(paper: Mapping[str, Any], *, root: Path, users: list[Mapping[str, Any]],
               placeholder: str, settings_authors: list[Mapping[str, Any]]) -> dict[str, Any]:
    paper_id = str(paper["paper_id"])
    registry = _registry(root, paper_id)
    state, reasons = classify(paper, registry)
    names = {u["id"]: u.get("display_name") for u in users}
    active = [row for row in paper.get("assignments") or [] if row.get("active")]
    real = [row for row in active if row.get("submitter_id") != placeholder]
    entry: dict[str, Any] = {
        "paper_id": paper_id, "state": state, "reasons": reasons,
        "lifecycle": paper.get("lifecycle_status"),
        "active": [names.get(row.get("submitter_id"), row.get("submitter_id")) for row in active],
        "action": "none",
    }
    if state == "untouched":
        return entry
    if (hold := manual_hold(paper, registry)) is not None:
        entry.update(action="hold", manual_assignment=hold,
                     why="manual assignment hold: a person assigns the submitter")
        return entry
    fallback = default_submitter(registry, settings_authors, users, placeholder)
    if state == "not_ready" and (stale := stale_registry(paper, registry)) is not None:
        entry.update(state="stale_registry", action="skip", why=stale)
        return entry
    if state == "not_ready":
        if real:
            row = real[0]
            entry.update(action="park", original_assignment_id=row.get("id"),
                         default_submitter={"submitter_id": row.get("submitter_id"),
                                            "name": names.get(row.get("submitter_id")),
                                            "source": "current_assignee"},
                         second_author=fallback)
        return entry
    if real:
        return entry
    target = recorded_submitter(paper, root, users, placeholder) or fallback
    if target is None:
        entry.update(action="blocked", why="no recorded submitter and no second author on the site")
    else:
        package = next((item for item in paper.get("packages") or []
                        if item.get("id") == paper.get("current_package_id")), {})
        entry.update(action="assign", target=target, version=package.get("version"))
    return entry


def _notes(entry: Mapping[str, Any]) -> str:
    if entry["action"] == "park":
        default = entry["default_submitter"]
        return (f"{MARKER} 暂停投稿人分配：论文尚不是可投稿状态（{'; '.join(entry['reasons'])}）。"
                f"原投稿人 {default.get('name')} 停用，由 ARA 管理员服务账号占位；稿件通过门禁、"
                "网站状态变为可投稿后自动恢复给原投稿人。"
                f" default_submitter_id={default['submitter_id']}"
                f" original_assignment_id={entry.get('original_assignment_id')}")
    target = entry["target"]
    return (f"{MARKER} 稿件 v{entry.get('version')} 已通过门禁、网站状态为可投稿，"
            f"按规则分配投稿人 {target.get('name')}（来源 {target['source']}）。")


def _apply(client: Any, entry: dict[str, Any], placeholder: str) -> None:
    paper_id = entry["paper_id"]
    path = f"/v1/papers/{paper_id}"
    before = client._request("GET", path)
    current = sorted(str(row.get("id")) for row in before.get("assignments") or []
                     if row.get("active"))
    submitter = (placeholder if entry["action"] == "park"
                 else entry["target"]["submitter_id"])
    client._request(
        "POST", f"{path}/assignments",
        json={"submitter_id": submitter, "notes": _notes(entry)},
        idempotency_key=f"site-assignment:{paper_id}:{entry['action']}:{submitter}:"
                        f"{'+'.join(current) or 'none'}",
    )
    after = client._request("GET", path)
    now_active = [row for row in after.get("assignments") or [] if row.get("active")]
    if [row.get("submitter_id") for row in now_active] != [submitter]:
        raise RuntimeError(f"{paper_id}: active assignment after {entry['action']} is "
                           f"{[row.get('submitter_id') for row in now_active]}, not [{submitter}]")
    for key in ("current_package_id", "submission_attempts"):
        if after.get(key) != before.get(key):
            raise RuntimeError(f"{paper_id}: {key} changed during the assignment")
    entry.update(applied=True, assignment_id=now_active[0].get("id"),
                 lifecycle_after=after.get("lifecycle_status"), applied_at=_now())


def sync_site_assignments(client: Any, *, root: str | Path,
                          paper_ids: Iterable[str] | None = None, apply: bool = False,
                          log_path: str | Path | None = None) -> dict[str, Any]:
    """Plan (and with ``apply`` carry out) the assignment changes; idempotent."""

    repo_root = Path(root).resolve()
    me = client._request("GET", "/v1/me")
    if not isinstance(me, Mapping) or me.get("role") != "admin" or not me.get("id"):
        raise RuntimeError("the Agent API account is not an admin; cannot hold the placeholder")
    placeholder = str(me["id"])
    users = [dict(u) for u in client._request("GET", "/v1/users") or [] if isinstance(u, Mapping)]
    settings_authors = _settings_authors(repo_root)
    wanted = sorted({str(p).strip() for p in paper_ids or [] if str(p).strip()})
    warnings: list[str] = []
    papers: list[Mapping[str, Any]] = []
    untouched = 0
    if wanted:
        for paper_id in wanted:
            found = client._request("GET", f"/v1/papers/{paper_id}", allow_not_found=True)
            if found is None:
                warnings.append(f"{paper_id}: not on the site")
            else:
                papers.append(found)
    else:
        listing = [item for item in client._request("GET", "/v1/papers") or []
                   if isinstance(item, Mapping)]
        if len(listing) >= 100:
            warnings.append(f"the site listed {len(listing)} papers; check for a page cap")
        for item in listing:
            paper_id = str(item.get("paper_id") or "")
            if (item.get("lifecycle_status") not in PRE_SUBMISSION_LIFECYCLES
                    or _registry(repo_root, paper_id) is None):
                untouched += 1
                continue
            papers.append(client._request("GET", f"/v1/papers/{paper_id}"))
    entries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for paper in papers:
        try:
            entry = plan_paper(paper, root=repo_root, users=users, placeholder=placeholder,
                               settings_authors=settings_authors)
        except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
            errors.append({"paper_id": paper.get("paper_id"), "error": str(exc)[:400]})
            continue
        if apply and entry["action"] in {"park", "assign"}:
            try:
                _apply(client, entry, placeholder)
            except Exception as exc:  # noqa: BLE001 - reported per paper, retried next run
                errors.append({"paper_id": entry["paper_id"], "error": str(exc)[:400]})
        entries.append(entry)
    changed = [entry for entry in entries if entry.get("applied")]
    if log_path and changed:
        log = Path(log_path)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            for entry in changed:
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    blocked = [entry for entry in entries if entry["action"] in {"blocked", "skip"}]
    held = [entry["paper_id"] for entry in entries if entry["action"] == "hold"]
    return {
        "schema_version": SCHEMA, "apply": apply, "placeholder_id": placeholder,
        "checked_at": _now(), "papers": entries, "changed": changed,
        "pending": [e for e in entries if e["action"] in {"park", "assign"} and not e.get("applied")],
        "blocked": blocked, "held": held, "untouched_by_lifecycle_or_scope": untouched,
        "warnings": warnings, "errors": errors, "ok": not errors,
    }
