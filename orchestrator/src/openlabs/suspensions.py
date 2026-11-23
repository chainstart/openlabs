"""Time-limited provider suspensions (``[routing.provider_suspensions.<provider>]``).

User decision 2026-11-20 ("取消claude的临时放宽，后面的活都派给gpt"): a provider can be
taken out of the automatic line until a fixed time, after which the configuration as
written applies again without anybody touching it. The suspension is applied to the
parsed TOML before the settings are built, so every consumer sees the same thing:

* the provider's runners are dropped from ``[runners]`` (no owner, writer, admission,
  review, decision or light task is routed to them; with one family left the router
  runs single-family, ``same_family_different_model``);
* ``[program.owner]`` ``runners`` / ``max_topics_per_runner`` lose those names, and a
  ``writing_runner`` of that provider falls back to "the owner writes" (a
  ``figure_runner`` of that provider is dropped the same way);
* ``protected_models`` of that provider are not protected, its ``probe_commands`` entry
  is skipped, its ``provider_ceilings`` entry is set aside (no "unknown provider" error).

The settings are reloaded every tick, so the suspension ends at the first tick after
``until``. Tasks already running are not touched. Each entry needs ``until`` (ISO time
with zone) and the decision's provenance ``by``, ``date`` and ``quote`` (``reason``
optional).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

PROVENANCE_KEYS = ("by", "date", "quote")
ALLOWED_KEYS = ("until", *PROVENANCE_KEYS, "reason")


def now() -> datetime:
    """Current time (tests replace it)."""

    return datetime.now(UTC)


@dataclass(frozen=True)
class ProviderSuspension:
    provider: str
    until: datetime
    by: str
    date: str
    quote: str
    reason: str | None
    active: bool
    runners: tuple[str, ...] = ()

    def summary(self, moment: datetime) -> dict[str, Any]:
        remaining = max(0.0, (self.until - moment).total_seconds())
        return {"provider": self.provider, "until": _iso(self.until), "active": self.active,
                "remaining_hours": round(remaining / 3600, 2), "runners": list(self.runners),
                "by": self.by, "date": self.date, "quote": self.quote, "reason": self.reason}


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_until(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label}.until must be an ISO time, e.g. 2026-11-23T11:00:00Z") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label}.until needs a time zone (e.g. ...Z)")
    return parsed.astimezone(UTC)


def parse(routing: Any) -> list[dict[str, Any]]:
    """Validated raw entries of ``[routing.provider_suspensions]``."""

    table = routing.get("provider_suspensions") if isinstance(routing, dict) else None
    if table is None:
        return []
    if not isinstance(table, dict):
        raise ValueError("[routing.provider_suspensions] must be a table of provider tables")
    entries = []
    for provider, entry in table.items():
        label = f"[routing.provider_suspensions.{provider}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be a table")
        unknown = sorted(set(entry) - set(ALLOWED_KEYS))
        if unknown:
            raise ValueError(f"{label} has unknown key(s) {', '.join(unknown)}; "
                             f"allowed: {', '.join(ALLOWED_KEYS)}")
        missing = [key for key in ("until", *PROVENANCE_KEYS) if not str(entry.get(key) or "").strip()]
        if missing:
            raise ValueError(f"{label} needs {', '.join(missing)}")
        entries.append({"provider": str(provider), "until": _parse_until(entry["until"], label),
                        **{key: str(entry[key]).strip() for key in PROVENANCE_KEYS},
                        "reason": str(entry.get("reason") or "").strip() or None})
    return entries


def apply(payload: dict[str, Any], moment: datetime | None = None
          ) -> tuple[dict[str, Any], tuple[ProviderSuspension, ...]]:
    """``payload`` with the active suspensions applied, and every configured suspension."""

    routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
    entries = parse(routing)
    if not entries:
        return payload, ()
    moment = moment or now()
    runners_table = payload.get("runners") if isinstance(payload.get("runners"), dict) else {}
    active_providers = {item["provider"] for item in entries if moment < item["until"]}
    result = copy.deepcopy(payload)
    suspensions = []
    for item in entries:
        names = tuple(sorted(name for name, spec in runners_table.items()
                             if isinstance(spec, dict) and str(spec.get("provider")) == item["provider"]))
        suspensions.append(ProviderSuspension(active=item["provider"] in active_providers,
                                              runners=names, **item))
    new_routing = dict(result.get("routing") or {})
    new_routing.pop("provider_suspensions", None)
    result["routing"] = new_routing
    if not active_providers:
        return result, tuple(suspensions)
    dropped = {name for item in suspensions if item.active for name in item.runners}
    dropped_models = {str(runners_table[name].get("model")) for name in dropped
                      if runners_table[name].get("model")}
    result["runners"] = {name: spec for name, spec in runners_table.items() if name not in dropped}
    if isinstance(new_routing.get("protected_models"), list):
        new_routing["protected_models"] = [model for model in new_routing["protected_models"]
                                           if str(model) not in dropped_models]
    for key in ("provider_ceilings", "probe_commands"):
        if isinstance(new_routing.get(key), dict):
            new_routing[key] = {provider: value for provider, value in new_routing[key].items()
                                if provider not in active_providers}
    program = result.get("program") if isinstance(result.get("program"), dict) else None
    owner = program.get("owner") if program and isinstance(program.get("owner"), dict) else None
    if owner is not None:
        if isinstance(owner.get("runners"), list):
            kept = [name for name in owner["runners"] if name not in dropped]
            owner["runners"] = kept or [name for name in result["runners"]]
        if isinstance(owner.get("max_topics_per_runner"), dict):
            owner["max_topics_per_runner"] = {name: limit for name, limit
                                              in owner["max_topics_per_runner"].items()
                                              if name not in dropped}
        if owner.get("writing_runner") in dropped:
            owner.pop("writing_runner")  # the owner writes
        if owner.get("figure_runner") in dropped:
            owner.pop("figure_runner")  # figure seats follow the writer / asking seat
    return result, tuple(suspensions)


def report(suspensions: tuple[ProviderSuspension, ...], moment: datetime | None = None
           ) -> list[dict[str, Any]]:
    moment = moment or now()
    return [item.summary(moment) for item in suspensions]
