"""Team submission cadence: avoid bulk submissions that read as a paper mill.

The 2026-11-07 audit found same-day bursts to one journal (for example several papers to
European Journal of Combinatorics in one week, five Forum Mathematicum refusals in one day)
and median desk-rejection times of eight days.  This module enforces configurable spacing
from the shared, API-sourced ledger.  It reads only; it never submits or changes the site.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from paper_writing.journal_history import (
    _path,
    _policy,
    canonical_journal,
    journal_key,
    load_history,
)

DEFAULTS = {
    "enabled": True,
    "max_active_per_venue": 1,
    "min_days_between_same_venue": 30,
    "max_team_submissions_per_7_days": 3,
    "max_team_submissions_per_day": 1,
    "min_days_after_rejection_same_paper": 7,
}


def cadence_config(settings: Mapping[str, Any]) -> dict[str, Any]:
    config = dict(DEFAULTS)
    config.update(dict(settings.get("submission_cadence") or {}))
    for key, value in config.items():
        if key != "enabled" and (type(value) is not int or value < 0):
            raise ValueError(f"submission_cadence.{key} must be a non-negative integer")
    return config


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate_cadence(
    ledger: Mapping[str, Any],
    *,
    venue: str,
    paper_id: str,
    config: Mapping[str, Any],
    now: datetime,
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return violations for submitting ``paper_id`` to ``venue`` at ``now``."""

    key = journal_key(canonical_journal(venue, aliases))
    same = lambda name: journal_key(canonical_journal(str(name), aliases)) == key  # noqa: E731
    active = list(ledger.get("active_submissions") or [])
    rejections = list(ledger.get("rejections") or [])
    result: dict[str, Any] = {"venue": canonical_journal(venue, aliases), "paper_id": paper_id,
                              "checked_at": now.isoformat(), "violations": [], "next_allowed_at": None}
    if not config.get("enabled", True):
        result["status"] = "ok"
        return result
    if any(row.get("paper_id") == paper_id and same(row.get("journal")) for row in active):
        result["status"] = "ok"
        result["note"] = "paper already has an ongoing attempt at this venue; cadence does not apply"
        return result
    blockers: list[tuple[str, datetime | None]] = []

    venue_active = [row for row in active if same(row.get("journal"))
                    and row.get("status") not in {"accepted", "published"}]
    if len(venue_active) >= config["max_active_per_venue"] > 0:
        blockers.append((f"{len(venue_active)} team paper(s) already under consideration at this venue "
                         f"(limit {config['max_active_per_venue']})", None))

    submitted = []
    for row in [*active, *rejections]:
        at = _time(row.get("submitted_at"))
        if at is not None:
            submitted.append((at, row))
    gap = timedelta(days=config["min_days_between_same_venue"])
    recent_same = [at for at, row in submitted if same(row.get("journal")) and now - gap < at <= now]
    if recent_same and gap:
        latest = max(recent_same)
        blockers.append((f"team submitted to this venue on {latest.date()} "
                         f"(minimum spacing {config['min_days_between_same_venue']} days)", latest + gap))

    week = [at for at, _ in submitted if now - timedelta(days=7) < at <= now]
    if config["max_team_submissions_per_7_days"] and len(week) >= config["max_team_submissions_per_7_days"]:
        blockers.append((f"{len(week)} team submissions in the last 7 days "
                         f"(limit {config['max_team_submissions_per_7_days']})",
                         min(week) + timedelta(days=7)))
    day = [at for at, _ in submitted if now - timedelta(days=1) < at <= now]
    if config["max_team_submissions_per_day"] and len(day) >= config["max_team_submissions_per_day"]:
        blockers.append((f"{len(day)} team submission(s) in the last 24 hours "
                         f"(limit {config['max_team_submissions_per_day']})", min(day) + timedelta(days=1)))

    cool = timedelta(days=config["min_days_after_rejection_same_paper"])
    own = [_time(row.get("rejected_at")) for row in rejections if row.get("paper_id") == paper_id]
    own = [at for at in own if at is not None and now - cool < at <= now]
    if own and cool:
        latest = max(own)
        blockers.append((f"this paper was rejected on {latest.date()}; revise substantively and wait "
                         f"{config['min_days_after_rejection_same_paper']} days", latest + cool))

    result["violations"] = [text for text, _ in blockers]
    waits = [at for _, at in blockers if at is not None]
    if blockers and len(waits) == len(blockers):
        result["next_allowed_at"] = max(waits).isoformat()
    result["status"] = "blocked" if blockers else "ok"
    return result


def check_cadence(root: Path, *, venue: str, paper_id: str, now: datetime | None = None) -> dict[str, Any]:
    from paper_writing.registry import load_registry_settings

    settings = load_registry_settings(root)
    history_config = _policy(root, settings.get("journal_target_policy", {}))
    ledger = load_history(_path(root, history_config))
    updated = _time(ledger.get("updated_at"))
    moment = now or datetime.now(timezone.utc)
    if updated is None or moment - updated > timedelta(days=history_config["max_age_days"]):
        raise ValueError("Team ledger is stale; run journal-history sync before a cadence check")
    return evaluate_cadence(ledger, venue=venue, paper_id=paper_id, config=cadence_config(settings),
                            now=moment, aliases=history_config.get("aliases"))
