"""Author-based eligibility rules for locally registered funding records."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _funding_matches(record: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    record_grant = _text(record.get("grant_number"))
    policy_grant = _text(policy.get("grant_number"))
    if not record_grant or record_grant != policy_grant:
        return False
    record_funder = _text(record.get("funder"))
    policy_funder = _text(policy.get("funder"))
    return not record_funder or not policy_funder or record_funder == policy_funder


def _eligibility(
    record: Mapping[str, Any], policies: Iterable[Mapping[str, Any]]
) -> Mapping[str, Any]:
    declared = record.get("eligibility")
    if isinstance(declared, Mapping):
        return declared
    for policy in policies:
        if _funding_matches(record, policy):
            inherited = policy.get("eligibility")
            if isinstance(inherited, Mapping):
                return inherited
    return {}


def funding_is_eligible(
    record: Mapping[str, Any],
    authors: Iterable[Mapping[str, Any]],
    *,
    policies: Iterable[Mapping[str, Any]] = (),
) -> bool:
    """Return whether the registered author list satisfies a funding rule."""

    eligibility = _eligibility(record, policies)
    required = eligibility.get("requires_author")
    if not isinstance(required, Mapping):
        return True
    aliases = {
        _text(required.get(field))
        for field in ("name", "name_zh", "display_name")
        if _text(required.get(field))
    }
    if not aliases:
        return False
    for author in authors:
        author_aliases = {
            _text(author.get(field))
            for field in ("name", "name_zh", "display_name")
            if _text(author.get(field))
        }
        if aliases & author_aliases:
            return True
    return False


def eligible_funding(
    records: Any,
    authors: Iterable[Mapping[str, Any]],
    *,
    policies: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Copy only funding records permitted by the registered author list."""

    candidates = records if isinstance(records, list) else []
    policy_records = [dict(item) for item in policies if isinstance(item, Mapping)]
    people = [dict(item) for item in authors if isinstance(item, Mapping)]
    return [
        dict(item)
        for item in candidates
        if isinstance(item, Mapping)
        and funding_is_eligible(item, people, policies=policy_records)
    ]


def ineligible_funding(
    records: Any,
    authors: Iterable[Mapping[str, Any]],
    *,
    policies: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Copy funding records whose required author is absent."""

    candidates = records if isinstance(records, list) else []
    policy_records = [dict(item) for item in policies if isinstance(item, Mapping)]
    people = [dict(item) for item in authors if isinstance(item, Mapping)]
    return [
        dict(item)
        for item in candidates
        if isinstance(item, Mapping)
        and not funding_is_eligible(item, people, policies=policy_records)
    ]
