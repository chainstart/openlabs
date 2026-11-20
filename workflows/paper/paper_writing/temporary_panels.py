"""Time-limited review panels (``review.temporary_panels``; user decision 2026-11-20).

Each entry replaces the standard panel for reviews that START before its ``until`` (and,
when given, at or after ``since``)::

    review:
      temporary_panels:
      - since: '2026-11-20T08:30:42+00:00'     # optional
        until: '2026-11-23T11:00:00+00:00'
        authorization: {actor: user, date: '2026-11-20', quote: ...}
        cross_model: {basis: model}           # basis_authorization = authorization
        referee_roles: [referee_a, referee_b] # optional, default: the standard list
        roles: {editor: ..., referee_a: ..., referee_b: ..., formal_verifier: ...}
        editorial_rewrite: {rewriters: ..., judges: ...}   # optional

After ``until`` the standard panel applies again by itself; a review that started under
the temporary panel stays bound to it (``review_flow.policy_for_record``), like a
``previous_panels`` entry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

AUTHORIZATION_KEYS = ("actor", "date", "quote")


def now() -> datetime:
    """Current time (tests replace it)."""
    return datetime.now(UTC)


def _time(value: Any, label: str) -> datetime:
    try:
        parsed = (value if isinstance(value, datetime)
                  else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO time with a zone") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be an ISO time with a zone")
    return parsed.astimezone(UTC)


def entries(settings: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validated ``review.temporary_panels`` entries, earliest ``until`` first."""

    review = settings.get("review") or {}
    raw = review.get("temporary_panels") if isinstance(review, Mapping) else None
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("review.temporary_panels must be a list")
    result = []
    for index, item in enumerate(raw):
        label = f"review.temporary_panels[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{label} must be a mapping")
        until = _time(item.get("until"), f"{label}.until")
        since = _time(item["since"], f"{label}.since") if item.get("since") else None
        receipt = item.get("authorization")
        if not isinstance(receipt, Mapping) or any(
                not str(receipt.get(key) or "").strip() for key in AUTHORIZATION_KEYS):
            raise ValueError(f"{label}.authorization needs actor, date and quote")
        if not isinstance(item.get("roles"), Mapping):
            raise ValueError(f"{label}.roles must be a mapping")
        cross = item.get("cross_model") or {}
        if not isinstance(cross, Mapping):
            raise ValueError(f"{label}.cross_model must be a mapping")
        rewrite = item.get("editorial_rewrite") or {}
        if not isinstance(rewrite, Mapping):
            raise ValueError(f"{label}.editorial_rewrite must be a mapping")
        result.append({**dict(item), "until": until, "since": since,
                       "authorization": dict(receipt), "cross_model": dict(cross),
                       "editorial_rewrite": dict(rewrite)})
    return sorted(result, key=lambda entry: entry["until"])


def active(settings: Mapping[str, Any], moment: datetime | None = None) -> dict[str, Any] | None:
    """The temporary panel in force at ``moment`` (default now), or None."""

    moment = moment or now()
    for entry in entries(settings):
        if moment < entry["until"] and (entry["since"] is None or moment >= entry["since"]):
            return entry
    return None
