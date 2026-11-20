"""Local registry of verified journals (``registry/verified-venues.yaml``).

Eligibility checks read this registry before going online. Each entry records the
journal's 2025 CAS upgraded-edition major-category zone, its SCIE indexing and every
author charge (APC, page, colour, submission) with the evidence (URL or local file), the
date and who verified it. The rule it is checked against is the owner's: paid routes only
for a CAS 2025 zone-1 journal; every other zone needs a route with no mandatory author
fee (``AGENTS.md``, ``registry/settings.yaml#journal_target_policy.venue_eligibility``).

A publisher page that refuses the request (HTTP 403/406, a challenge page) is not a reason
to stop for a human: the journal is recorded ``pending_verification`` with the failed
URL (``venue mark-pending``) and the owner either continues with it pending (verification
is completed before submission, which a human confirms anyway) or switches to a verified
alternative from the registry (``venue alternatives``).
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

REGISTRY_PATH = "registry/verified-venues.yaml"
SCHEMA = "openlabs.verified_venues.v1"
STATUSES = ("verified", "pending_verification")
CHARGES = ("apc", "page_charge", "colour_charge", "submission_fee")
ZONES = (1, 2, 3, 4)


class VenueRegistryError(ValueError):
    """The registry cannot be read or an update is refused."""


def registry_path(root: str | Path) -> Path:
    return Path(root) / REGISTRY_PATH


def _key(value: Any) -> str:
    text = str(value or "").casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _issn(value: Any) -> str:
    return re.sub(r"[^0-9X]", "", str(value or "").upper())


def load_venues(root: str | Path) -> dict[str, Any]:
    """The registry document (an empty one when the file does not exist yet)."""

    path = registry_path(root)
    if not path.is_file():
        return {"schema_version": SCHEMA, "venues": []}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise VenueRegistryError(f"{path}: {exc}") from exc
    if not isinstance(document, Mapping) or not isinstance(document.get("venues"), list):
        raise VenueRegistryError(f"{path}: expected a mapping with a `venues` list")
    if document.get("schema_version") != SCHEMA:
        raise VenueRegistryError(f"{path}: schema_version must be {SCHEMA}")
    return dict(document)


def find_venue(document: Mapping[str, Any], *, journal: str | None = None,
               issn: str | None = None) -> dict[str, Any] | None:
    """The entry whose name, alias, ISSN or eISSN matches (ISSN first)."""

    venues = [item for item in document.get("venues") or [] if isinstance(item, Mapping)]
    wanted = _issn(issn)
    if wanted:
        for item in venues:
            if wanted in {_issn(item.get("issn")), _issn(item.get("eissn"))} - {""}:
                return dict(item)
    name = _key(journal)
    if name:
        for item in venues:
            names = {_key(item.get("journal")), *(_key(a) for a in item.get("aliases") or [])}
            if name in names:
                return dict(item)
    return None


def _zone(entry: Mapping[str, Any]) -> int | None:
    cas = entry.get("cas_2025")
    zone = cas.get("zone") if isinstance(cas, Mapping) else None
    return zone if type(zone) is int and zone in ZONES else None


def venue_problems(entry: Mapping[str, Any]) -> list[str]:
    """Why a registry entry is not (yet) an eligible target under the owner's rule."""

    problems: list[str] = []
    if entry.get("status") != "verified":
        problems.append(f"status is {entry.get('status')!r}, not verified")
    zone = _zone(entry)
    cas = entry.get("cas_2025") if isinstance(entry.get("cas_2025"), Mapping) else {}
    if zone is None:
        problems.append("no 2025 CAS major-category zone on record")
    elif not str(cas.get("source") or "").strip():
        problems.append("the 2025 CAS zone has no source")
    indexes = entry.get("indexes") if isinstance(entry.get("indexes"), Mapping) else {}
    if "SCIE" not in {str(item).upper() for item in indexes.get("list") or []}:
        problems.append("SCIE indexing is not on record")
    charges = entry.get("charges") if isinstance(entry.get("charges"), Mapping) else {}
    mandatory = {name: (charges.get(name) or {}).get("mandatory")
                 if isinstance(charges.get(name), Mapping) else None for name in CHARGES}
    unknown = [name for name, value in mandatory.items() if value is None]
    if zone != 1:
        if unknown:
            problems.append("charges not verified: " + ", ".join(unknown))
        paid = [name for name, value in mandatory.items() if value is True]
        if paid:
            problems.append(f"mandatory {', '.join(paid)} outside CAS zone 1 (paid routes are "
                            "for zone-1 journals only)")
        if entry.get("fee_free_route") is not True:
            problems.append("no verified fee-free route")
    return problems


def _summary(entry: Mapping[str, Any]) -> dict[str, Any]:
    cas = entry.get("cas_2025") if isinstance(entry.get("cas_2025"), Mapping) else {}
    return {"journal": entry.get("journal"), "issn": entry.get("issn"),
            "status": entry.get("status"), "cas_2025_zone": _zone(entry),
            "major_category": cas.get("major_category"),
            "fee_free_route": entry.get("fee_free_route"),
            "verified_at": entry.get("verified_at"), "verified_by": entry.get("verified_by")}


def lookup(root: str | Path, *, journal: str | None = None,
           issn: str | None = None) -> dict[str, Any]:
    """Registry first: is this journal verified and eligible, and what to do otherwise."""

    if not (journal or issn):
        raise VenueRegistryError("lookup needs --journal or --issn")
    document = load_venues(root)
    entry = find_venue(document, journal=journal, issn=issn)
    result: dict[str, Any] = {"schema_version": "openlabs.venue_lookup.v1",
                              "registry": REGISTRY_PATH, "query": {"journal": journal,
                                                                   "issn": issn}}
    if entry is None:
        return {**result, "found": False, "eligible": False, "status": None,
                "next": ("not in the registry: verify the journal online (public pages through "
                         "the download bridge); a publisher refusal (HTTP 403/406) is recorded "
                         "with `paper-writing venue mark-pending` and is not a reason to stop; "
                         "verified alternatives: `paper-writing venue alternatives`")}
    problems = venue_problems(entry)
    eligible = not problems
    if eligible:
        step = "eligible on the registry's evidence; cite the entry's evidence in the paper record"
    elif entry.get("status") == "pending_verification":
        step = ("pending verification: continue with it (the open items are completed before "
                "submission) or switch to a verified alternative (`paper-writing venue "
                "alternatives`); do not stop for a human over it")
    else:
        step = "not eligible: choose a verified alternative (`paper-writing venue alternatives`)"
    return {**result, "found": True, "eligible": eligible, "status": entry.get("status"),
            "problems": problems, "open_items": list(entry.get("open_items") or []),
            "next": step, "venue": entry}


def alternatives(root: str | Path, *, zones: Iterable[int] | None = None,
                 category: str | None = None, exclude: str | None = None) -> dict[str, Any]:
    """Verified, eligible journals of the registry (optionally of some zones / category)."""

    document = load_venues(root)
    wanted = set(zones or ())
    needle = _key(category)
    skip = _key(exclude)
    found = []
    for item in document.get("venues") or []:
        if not isinstance(item, Mapping) or venue_problems(item):
            continue
        if wanted and _zone(item) not in wanted:
            continue
        cas = item.get("cas_2025") if isinstance(item.get("cas_2025"), Mapping) else {}
        if needle and needle not in _key(cas.get("major_category")):
            continue
        if skip and skip in {_key(item.get("journal")), *(_key(a) for a in item.get("aliases") or [])}:
            continue
        found.append(_summary(item))
    found.sort(key=lambda entry: (entry["cas_2025_zone"] or 9, _key(entry["journal"])))
    return {"schema_version": "openlabs.venue_alternatives.v1", "registry": REGISTRY_PATH,
            "filters": {"zones": sorted(wanted) or None, "category": category,
                        "exclude": exclude},
            "count": len(found), "venues": found}


def _write(root: str | Path, document: Mapping[str, Any]) -> Path:
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(dict(document), allow_unicode=True, sort_keys=False, width=100)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".verified-venues.",
                                         suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.replace(temporary, path)
    return path


def mark_pending(root: str | Path, *, journal: str, by: str, reason: str,
                 url: str | None = None, http_status: int | None = None,
                 issn: str | None = None, accessed_at: str | None = None) -> dict[str, Any]:
    """Record an unverifiable journal as ``pending_verification`` (never downgrades one).

    The failed request (URL, HTTP status, time, who) is appended to the entry's
    ``access_failures``; a verified entry stays verified (its evidence is unchanged) and
    only gains the record.
    """

    journal = str(journal or "").strip()
    by, reason = str(by or "").strip(), str(reason or "").strip()
    if not journal or not by or not reason:
        raise VenueRegistryError("mark-pending needs --journal, --by and --reason")
    when = accessed_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    failure = {"url": url, "http_status": http_status, "accessed_at": when, "by": by,
               "reason": reason}
    document = load_venues(root)
    venues = [dict(item) for item in document.get("venues") or [] if isinstance(item, Mapping)]
    existing = find_venue({"venues": venues}, journal=journal, issn=issn)
    if existing is not None:
        index = next(i for i, item in enumerate(venues)
                     if item.get("journal") == existing.get("journal"))
        entry = venues[index]
        failures = [*list(entry.get("access_failures") or []), failure][-20:]
        entry["access_failures"] = failures
        if entry.get("status") != "verified":
            entry["status"] = "pending_verification"
            item = f"{reason} ({url or 'no URL'}, HTTP {http_status or '?'}, {when[:10]})"
            entry["open_items"] = [*list(entry.get("open_items") or []), item][-20:]
        outcome = "recorded_on_verified" if entry.get("status") == "verified" else "pending"
    else:
        entry = {"journal": journal, "aliases": [], "issn": issn or None, "eissn": None,
                 "publisher": None, "status": "pending_verification", "indexes": None,
                 "cas_2025": None,
                 "charges": {name: {"mandatory": None, "note": None, "source": None}
                             for name in CHARGES},
                 "fee_free_route": None, "evidence": [], "verified_at": None,
                 "verified_by": None, "source_records": [],
                 "open_items": [f"{reason} ({url or 'no URL'}, HTTP {http_status or '?'}, "
                                f"{when[:10]})"],
                 "access_failures": [failure]}
        venues.append(entry)
        outcome = "added_pending"
    venues.sort(key=lambda item: _key(item.get("journal")))
    _write(root, {**document, "schema_version": SCHEMA,
                  "updated_at": when[:10], "venues": venues})
    return {"schema_version": "openlabs.venue_mark_pending.v1", "registry": REGISTRY_PATH,
            "journal": entry["journal"], "status": entry["status"], "outcome": outcome,
            "access_failure": failure}

