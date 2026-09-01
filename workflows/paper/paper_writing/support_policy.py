"""Configuration helpers for supporting-material lifecycle gates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SUPPORT_PUBLICATION_MODES = frozenset(
    {"zenodo_only", "github_zenodo", "not_required"}
)
SUPPORT_PUBLICATION_STATUSES = ("planned", "draft", "published")
_STATUS_RANK = {
    status: rank for rank, status in enumerate(SUPPORT_PUBLICATION_STATUSES)
}


def publication_policy(settings: Mapping[str, Any]) -> Mapping[str, Any]:
    value = settings.get("support_publication")
    return value if isinstance(value, Mapping) else {}


def effective_publication_mode(
    publication: Mapping[str, Any], policy: Mapping[str, Any]
) -> str:
    return str(
        publication.get("mode") or policy.get("default_mode") or ""
    ).strip()


def effective_publication_license(
    publication: Mapping[str, Any], policy: Mapping[str, Any]
) -> str:
    """Resolve a paper override before the user-approved repository default."""

    zenodo = publication.get("zenodo")
    zenodo = zenodo if isinstance(zenodo, Mapping) else {}
    return str(
        zenodo.get("license")
        or publication.get("license")
        or policy.get("default_license")
        or ""
    ).strip()


def lifecycle_gate(
    policy: Mapping[str, Any], gate_name: str
) -> Mapping[str, Any]:
    gates = policy.get("gates")
    gates = gates if isinstance(gates, Mapping) else {}
    value = gates.get(gate_name)
    return value if isinstance(value, Mapping) else {}


def status_meets_minimum(status: str, minimum_status: str) -> bool:
    if not minimum_status:
        return True
    return (
        status in _STATUS_RANK
        and minimum_status in _STATUS_RANK
        and _STATUS_RANK[status] >= _STATUS_RANK[minimum_status]
    )


def require_not_required_reason(policy: Mapping[str, Any]) -> bool:
    value = policy.get("not_required")
    value = value if isinstance(value, Mapping) else {}
    return bool(value.get("require_reason", False))


def validate_publication_policy(policy: Mapping[str, Any]) -> None:
    default_mode = str(policy.get("default_mode") or "").strip()
    if default_mode and default_mode not in SUPPORT_PUBLICATION_MODES:
        raise ValueError(
            f"support_publication.default_mode must be one of "
            f"{sorted(SUPPORT_PUBLICATION_MODES)!r}"
        )
    default_license = policy.get("default_license")
    if default_license is not None and (
        not isinstance(default_license, str) or not default_license.strip()
    ):
        raise ValueError(
            "support_publication.default_license must be a non-empty string"
        )
    for gate_name in (
        "before_review",
        "before_support_release",
        "before_handoff",
    ):
        gate = lifecycle_gate(policy, gate_name)
        minimum = str(gate.get("minimum_status") or "").strip()
        if minimum and minimum not in SUPPORT_PUBLICATION_STATUSES:
            raise ValueError(
                f"support_publication.gates.{gate_name}.minimum_status must be one "
                f"of {list(SUPPORT_PUBLICATION_STATUSES)!r}"
            )
        for field in (
            "require_version_doi",
            "require_manuscript_citation",
            "require_quality_gate_package_binding",
        ):
            if field in gate and not isinstance(gate[field], bool):
                raise ValueError(
                    f"support_publication.gates.{gate_name}.{field} must be boolean"
                )
    not_required = policy.get("not_required")
    if not_required is not None and not isinstance(not_required, Mapping):
        raise ValueError("support_publication.not_required must be an object")
    if isinstance(not_required, Mapping) and "require_reason" in not_required:
        if not isinstance(not_required["require_reason"], bool):
            raise ValueError(
                "support_publication.not_required.require_reason must be boolean"
            )
