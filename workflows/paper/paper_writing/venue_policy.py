"""Venue eligibility, escalation and real-data requirements for new targets.

User instruction 2026-11-07: every paper targets either an SCIE journal in the fixed
2025 CAS upgraded-edition major-category Zones 1-4, or a CCF-recommended conference
ranked C or better.  Publication charges are never paid: journals need a fee-free
route, conferences need a route without a mandatory page/publication charge (ordinary
registration is recorded separately and is not a page charge).  Default selections
use the configured routine tiers; Zone 1-2 journals and CCF-A conferences are an
explicit escalation track for results that cleared a stronger internal review.

The policy applies only to targets verified on or after ``effective_from`` and to papers
created on or after it, so historical targets and ongoing submissions remain truthful.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

CCF_RANKS = ("A", "B", "C")
REAL_DATA_KINDS = {
    "public_dataset",
    "experimental_measurement",
    "observational_survey",
    "clinical_or_cohort_registry",
    "field_or_sensor_record",
    "benchmark_with_real_samples",
}
NON_REAL_DATA_KINDS = {"simulation", "synthetic", "derived_model_output"}
ESCALATION_STATUSES = {"approved"}


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _filled(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _http(value: Any) -> bool:
    return _filled(value) and str(value).startswith(("https://", "http://"))


def eligibility_config(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the normalized ``journal_target_policy.venue_eligibility`` block or ``{}``."""

    if not isinstance(policy, Mapping):
        return {}
    config = policy.get("venue_eligibility")
    if not isinstance(config, Mapping) or not config.get("enabled", True):
        return {}
    effective = _date(config.get("effective_from"))
    if effective is None:
        raise ValueError("venue_eligibility.effective_from must be YYYY-MM-DD")
    journal = dict(config.get("journal") or {})
    conference = dict(config.get("conference") or {})
    escalation = dict(config.get("escalation") or {})
    tiers = journal.get("allowed_tiers", [1, 2, 3, 4])
    routine = journal.get("routine_tiers", [3, 4])
    if any(type(t) is not int or t not in {1, 2, 3, 4} for t in [*tiers, *routine]):
        raise ValueError("venue_eligibility journal tiers must be CAS zones 1-4")
    ranks = [str(r).upper() for r in conference.get("allowed_ccf_ranks", list(CCF_RANKS))]
    routine_ranks = [str(r).upper() for r in conference.get("routine_ccf_ranks", ["B", "C"])]
    if any(r not in CCF_RANKS for r in [*ranks, *routine_ranks]):
        raise ValueError("venue_eligibility CCF ranks must be A, B or C")
    return {
        "effective_from": effective,
        "journal": {
            "required_indexes": [str(x).upper() for x in journal.get("required_indexes", ["SCIE"])],
            "allowed_tiers": set(tiers),
            "routine_tiers": set(routine),
            "require_no_mandatory_author_fee": bool(
                journal.get("require_no_mandatory_author_fee", True)
            ),
        },
        "conference": {
            "allowed_ccf_ranks": set(ranks),
            "routine_ccf_ranks": set(routine_ranks),
            "ccf_list_edition": str(conference.get("ccf_list_edition") or ""),
            "require_no_mandatory_publication_fee": bool(
                conference.get("require_no_mandatory_publication_fee", True)
            ),
        },
        "escalation": {
            "journal_tiers": set(escalation.get("journal_tiers", [1, 2])),
            "ccf_ranks": {str(r).upper() for r in escalation.get("ccf_ranks", ["A"])},
            "minimum_internal_score": float(escalation.get("minimum_internal_score", 7.0)),
        },
        "empirical": dict(config.get("empirical_real_data") or {}),
    }


def _applies(checked_at: Any, config: Mapping[str, Any]) -> bool:
    checked = _date(checked_at)
    return checked is not None and checked >= config["effective_from"]


def _validate_escalation(paper: Mapping[str, Any], *, paper_id: str, venue: str,
                         config: Mapping[str, Any]) -> None:
    record = paper.get("target_escalation")
    prefix = f"target_escalation for {paper_id}"
    if not isinstance(record, Mapping):
        raise ValueError(
            f"{venue} is on the escalation track (CAS Zone 1-2 / CCF-A); record an approved "
            f"target_escalation for {paper_id}"
        )
    if record.get("status") not in ESCALATION_STATUSES:
        raise ValueError(f"{prefix} must have status approved")
    if str(record.get("venue") or "").strip().casefold() != venue.strip().casefold():
        raise ValueError(f"{prefix} names a different venue")
    if not _date(record.get("approved_at")):
        raise ValueError(f"{prefix}.approved_at must be YYYY-MM-DD")
    for key in ("approved_by", "strength_evidence", "fallback_venue"):
        if not _filled(record.get(key)):
            raise ValueError(f"{prefix}.{key} is required")
    score = record.get("internal_review_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError(f"{prefix}.internal_review_score must be a number")
    if float(score) < config["escalation"]["minimum_internal_score"]:
        raise ValueError(
            f"{prefix}.internal_review_score {score} is below the escalation minimum "
            f"{config['escalation']['minimum_internal_score']}"
        )
    if not _filled(record.get("internal_review_source")):
        raise ValueError(f"{prefix}.internal_review_source is required")


def validate_journal_eligibility(paper: Mapping[str, Any], *, paper_id: str,
                                 policy: Mapping[str, Any] | None) -> None:
    config = eligibility_config(policy)
    if not config or str(paper.get("venue_type") or "journal") != "journal":
        return
    if not paper.get("target_journal") or not _applies(paper.get("target_journal_checked_at"), config):
        return
    rules = config["journal"]
    indexing = paper.get("target_journal_indexing")
    actual = set()
    if isinstance(indexing, Mapping) and isinstance(indexing.get("indexes"), list):
        actual = {str(x).strip().upper() for x in indexing["indexes"]}
    if not isinstance(indexing, Mapping) or not set(rules["required_indexes"]).issubset(actual):
        raise ValueError(
            f"target_journal must carry dated indexing evidence including "
            f"{rules['required_indexes']} for {paper_id} (ESCI-only journals are not eligible)"
        )
    if not _http(indexing.get("source")) or not _date(indexing.get("checked_at")):
        raise ValueError(f"target_journal_indexing needs an HTTP(S) source and checked_at for {paper_id}")
    year = (policy or {}).get("classification_year", 2025)
    if paper.get("target_journal_ranking_year") != year or paper.get("target_journal_ranking_scope") != "major_category":
        raise ValueError(
            f"target_journal zone must come from the {year} CAS upgraded-edition major-category table for {paper_id}"
        )
    tier = paper.get("target_journal_tier")
    if type(tier) is not int or tier not in rules["allowed_tiers"]:
        raise ValueError(
            f"target_journal_tier must be one of {sorted(rules['allowed_tiers'])} "
            f"(2025 CAS major category) for {paper_id}"
        )
    if rules["require_no_mandatory_author_fee"] and paper.get("target_journal_fee_policy") != "no_mandatory_author_fee":
        raise ValueError(f"target_journal must have a fee-free publication route for {paper_id}")
    if tier in config["escalation"]["journal_tiers"]:
        _validate_escalation(paper, paper_id=paper_id, venue=str(paper["target_journal"]), config=config)


def validate_conference_eligibility(paper: Mapping[str, Any], *, paper_id: str,
                                    policy: Mapping[str, Any] | None) -> None:
    config = eligibility_config(policy)
    if not config or not paper.get("target_conference"):
        return
    if not _applies(paper.get("target_conference_checked_at"), config):
        return
    rules = config["conference"]
    if str(paper.get("venue_type") or "") != "conference":
        raise ValueError(f"target_conference requires venue_type conference for {paper_id}")
    ccf = paper.get("target_conference_ccf")
    if not isinstance(ccf, Mapping):
        raise ValueError(f"target_conference_ccf evidence is required for {paper_id}")
    rank = str(ccf.get("rank") or "").upper()
    if rank not in rules["allowed_ccf_ranks"]:
        raise ValueError(
            f"target_conference CCF rank must be one of {sorted(rules['allowed_ccf_ranks'])} for {paper_id}"
        )
    for key in ("category", "edition"):
        if not _filled(ccf.get(key)):
            raise ValueError(f"target_conference_ccf.{key} is required for {paper_id}")
    if rules["ccf_list_edition"] and str(ccf.get("edition")) != rules["ccf_list_edition"]:
        raise ValueError(
            f"target_conference_ccf.edition must be {rules['ccf_list_edition']!r} for {paper_id}"
        )
    if not _http(ccf.get("source")) or not _date(ccf.get("checked_at")):
        raise ValueError(f"target_conference_ccf needs an HTTP(S) source and checked_at for {paper_id}")
    if rules["require_no_mandatory_publication_fee"]:
        if paper.get("target_conference_fee_policy") != "no_mandatory_publication_fee":
            raise ValueError(
                f"target_conference must have no mandatory page/publication charge for {paper_id}"
            )
        if not _http(paper.get("target_conference_fee_source")):
            raise ValueError(f"target_conference_fee_source must be an HTTP(S) source for {paper_id}")
    if rank in config["escalation"]["ccf_ranks"]:
        _validate_escalation(paper, paper_id=paper_id, venue=str(paper["target_conference"]), config=config)


def validate_empirical_data_sources(paper: Mapping[str, Any], *, paper_id: str,
                                    policy: Mapping[str, Any] | None) -> None:
    """New empirical papers must declare at least one sourced, real-world data source."""

    config = eligibility_config(policy)
    if not config:
        return
    rules = config["empirical"]
    if not rules.get("enabled", True):
        return
    domains = set(rules.get("domains", ["ai", "biology", "materials", "physics", "quant"]))
    created = _date(paper.get("created_at"))
    exempt = paper.get("research_track") in set(rules.get("exempt_tracks", []))
    if exempt or str(paper.get("domain") or "") not in domains or created is None or created < config["effective_from"]:
        if "data_sources" in paper:
            _validate_sources(paper.get("data_sources"), paper_id=paper_id, require_real=False)
        return
    _validate_sources(paper.get("data_sources"), paper_id=paper_id, require_real=True)


def _validate_sources(sources: Any, *, paper_id: str, require_real: bool) -> None:
    if not isinstance(sources, list) or (require_real and not sources):
        raise ValueError(f"data_sources must list the real data used by {paper_id}")
    real = 0
    for index, row in enumerate(sources):
        prefix = f"data_sources[{index}] for {paper_id}"
        if not isinstance(row, Mapping):
            raise ValueError(f"{prefix} must be an object")
        kind = row.get("kind")
        if kind not in REAL_DATA_KINDS | NON_REAL_DATA_KINDS:
            raise ValueError(f"{prefix}.kind must be one of {sorted(REAL_DATA_KINDS | NON_REAL_DATA_KINDS)}")
        for key in ("name", "license_or_access"):
            if not _filled(row.get(key)):
                raise ValueError(f"{prefix}.{key} is required")
        if not (_http(row.get("source")) or _filled(row.get("doi"))):
            raise ValueError(f"{prefix} needs an HTTP(S) source or a DOI")
        if not (_filled(row.get("version")) or _date(row.get("accessed_at"))):
            raise ValueError(f"{prefix} needs a version or accessed_at date")
        real += kind in REAL_DATA_KINDS
    if require_real and not real:
        raise ValueError(
            f"{paper_id} must use at least one real (non-synthetic, non-simulated) data source"
        )


def is_escalation_venue(paper: Mapping[str, Any], policy: Mapping[str, Any] | None) -> bool:
    config = eligibility_config(policy)
    if not config:
        return False
    if paper.get("target_conference"):
        ccf = paper.get("target_conference_ccf")
        return isinstance(ccf, Mapping) and str(ccf.get("rank") or "").upper() in config["escalation"]["ccf_ranks"]
    return paper.get("target_journal_tier") in config["escalation"]["journal_tiers"]
