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

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
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
# ``provisional``: set by the research-program admission gate (``approved_by:
# admission:<task_id>``). It allows review on the escalation track without an
# internal score yet; delivery at that target needs the score (then ``approved``).
ESCALATION_STATUSES = {"approved", "provisional"}
# A fallback venue must carry the same eligibility evidence as a registered target, and
# its fee evidence must name every mandatory author charge it ruled out -- not only the
# APC.  Lesson 2026-11-12: a journal's open-access page said "no APC charges apply" on
# the subscription route while its separate costs page levied a page charge per typeset
# page, so it had been registered as a fallback that was never fee-free.
FALLBACK_REQUIRED_CHARGES = ("page_charge", "colour_charge", "submission_fee")
# ``target_escalation.score_waiver``: the owner explicitly keeps an escalation target although
# the internal review score is below ``minimum_internal_score``. It names the lowest score
# the owner accepted (the score of the review the owner saw, bound by path and hash) and a
# hash-bound receipt of the owner's own words. It only lowers the score bar for this paper
# and venue; the review must still be ready (no blockers, no low-confidence referee).
SCORE_WAIVER_KIND = "escalation_score_waiver"
_USER_RECEIPT_SCHEMA = "openlabs.actual_author_instruction.v1"
_USER_RECEIPT_SOURCE = "actual user message in this session"


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


def _safe_file(root: Path, source: Any, digest: Any, label: str) -> Path:
    if (not isinstance(source, str) or not source or "\\" in source
            or Path(source).is_absolute() or ".." in Path(source).parts
            or Path(source).as_posix() != source
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError(f"Unsafe or unbound {label}")
    base = Path(root).resolve()
    component = base
    for part in Path(source).parts:
        component /= part
        if component.is_symlink():
            raise ValueError(f"Unsafe {label}: symlink")
    path = base / source
    if (not path.is_file() or path.stat().st_size > 2_000_000
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
        raise ValueError(f"{label} missing or changed")
    return path


def score_waiver_problems(record: Mapping[str, Any], *, paper_id: str, venue: str,
                          root: str | Path | None = None) -> list[str]:
    """Why ``record['score_waiver']`` is not a valid owner waiver (``[]``: it is).

    Without ``root`` only the structure is checked; with ``root`` the receipt and the basis
    review are re-hashed and the receipt's grant must cover this paper, venue and score.
    """

    waiver = record.get("score_waiver")
    prefix = f"target_escalation.score_waiver for {paper_id}"
    if not isinstance(waiver, Mapping):
        return [f"{prefix} must be an object"]
    problems = []
    if str(waiver.get("venue") or "").strip().casefold() != venue.strip().casefold():
        problems.append(f"{prefix} names a different venue")
    for key in ("authorized_by", "user_text"):
        if not _filled(waiver.get(key)):
            problems.append(f"{prefix}.{key} is required")
    if not _date(waiver.get("authorized_at")):
        problems.append(f"{prefix}.authorized_at must be YYYY-MM-DD")
    floor = waiver.get("minimum_accepted_score")
    if isinstance(floor, bool) or not isinstance(floor, (int, float)):
        problems.append(f"{prefix}.minimum_accepted_score must be a number")
    basis = waiver.get("basis_review")
    auth = waiver.get("authorization")
    if not isinstance(basis, Mapping) or not _filled(basis.get("path")) or not _filled(basis.get("sha256")):
        problems.append(f"{prefix}.basis_review needs the reviewed decision record path and sha256")
    if (not isinstance(auth, Mapping) or not _filled(auth.get("summary"))
            or not _filled(auth.get("path")) or not _filled(auth.get("sha256"))
            or not str(auth.get("json_pointer") or "").startswith("/")):
        problems.append(f"{prefix}.authorization needs a hash-bound user receipt "
                        "(path, sha256, json_pointer, summary)")
    if problems or root is None:
        return problems
    try:
        _safe_file(Path(root), basis["path"], basis["sha256"], f"{prefix} basis review")
        path = _safe_file(Path(root), auth["path"], auth["sha256"], f"{prefix} authorization")
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [str(exc)]
    if (not isinstance(receipt, Mapping) or receipt.get("schema") != _USER_RECEIPT_SCHEMA
            or receipt.get("source") != _USER_RECEIPT_SOURCE
            or receipt.get("user_text") != waiver.get("user_text")):
        return [f"{prefix} requires an actual user instruction receipt with the same user_text"]
    grant: Any = receipt
    try:
        for token in str(auth["json_pointer"])[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            grant = grant[int(token)] if isinstance(grant, list) else grant[token]
    except (KeyError, IndexError, ValueError, TypeError):
        return [f"{prefix} authorization pointer does not resolve"]
    if (not isinstance(grant, Mapping) or grant.get("kind") != SCORE_WAIVER_KIND
            or grant.get("paper_id") != paper_id
            or str(grant.get("target_journal") or grant.get("venue") or "").strip().casefold()
            != venue.strip().casefold()
            or grant.get("minimum_accepted_score") != floor
            or grant.get("authorization") != auth.get("summary")):
        return [f"{prefix}: the user receipt does not cover this paper, venue and score"]
    return []


def escalation_minimum(paper: Mapping[str, Any], policy: Mapping[str, Any] | None, *,
                       paper_id: str, root: str | Path | None = None) -> float | None:
    """The score bar for this paper's escalation target: the configured minimum, or the
    lower floor of a valid owner ``score_waiver``. ``None`` when not on the escalation track.
    An invalid waiver raises ``ValueError`` rather than silently falling back."""

    config = eligibility_config(policy)
    if not config or not is_escalation_venue(paper, policy):
        return None
    minimum = config["escalation"]["minimum_internal_score"]
    record = paper.get("target_escalation")
    if not isinstance(record, Mapping) or record.get("score_waiver") is None:
        return minimum
    venue = str(paper.get("target_conference") or paper.get("target_journal") or "")
    problems = score_waiver_problems(record, paper_id=paper_id, venue=venue, root=root)
    if problems:
        raise ValueError(problems[0])
    return min(minimum, float(record["score_waiver"]["minimum_accepted_score"]))


def _validate_escalation(paper: Mapping[str, Any], *, paper_id: str, venue: str,
                         config: Mapping[str, Any], root: str | Path | None = None) -> None:
    record = paper.get("target_escalation")
    prefix = f"target_escalation for {paper_id}"
    if not isinstance(record, Mapping):
        raise ValueError(
            f"{venue} is on the escalation track (CAS Zone 1-2 / CCF-A); record an approved "
            f"target_escalation for {paper_id}"
        )
    if record.get("status") not in ESCALATION_STATUSES:
        raise ValueError(f"{prefix} must have status approved (or provisional from admission)")
    provisional = record.get("status") == "provisional"
    if str(record.get("venue") or "").strip().casefold() != venue.strip().casefold():
        raise ValueError(f"{prefix} names a different venue")
    if not _date(record.get("approved_at")):
        raise ValueError(f"{prefix}.approved_at must be YYYY-MM-DD")
    for key in ("approved_by", "strength_evidence", "fallback_venue"):
        if not _filled(record.get(key)):
            raise ValueError(f"{prefix}.{key} is required")
    score = record.get("internal_review_score")
    if provisional:
        if not str(record.get("approved_by") or "").startswith("admission:"):
            raise ValueError(f"{prefix}: a provisional escalation is set by the admission gate")
        if score is None:
            return  # reviewed on the escalation track; scored before delivery
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError(f"{prefix}.internal_review_score must be a number")
    minimum = config["escalation"]["minimum_internal_score"]
    if record.get("score_waiver") is not None:
        problems = score_waiver_problems(record, paper_id=paper_id, venue=venue, root=root)
        if problems:
            raise ValueError(problems[0])
        minimum = min(minimum, float(record["score_waiver"]["minimum_accepted_score"]))
    if float(score) < minimum:
        raise ValueError(
            f"{prefix}.internal_review_score {score} is below the escalation minimum {minimum}"
        )
    if not _filled(record.get("internal_review_source")):
        raise ValueError(f"{prefix}.internal_review_source is required")


def validate_journal_eligibility(paper: Mapping[str, Any], *, paper_id: str,
                                 policy: Mapping[str, Any] | None,
                                 root: str | Path | None = None) -> None:
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
        _validate_escalation(paper, paper_id=paper_id, venue=str(paper["target_journal"]), config=config,
                             root=root)
    else:
        _validate_executed_fallback(paper, paper_id=paper_id, venue=str(paper["target_journal"]),
                                    policy=policy)


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
    else:
        _validate_executed_fallback(paper, paper_id=paper_id, venue=str(paper["target_conference"]),
                                    policy=policy)


def fallback_eligibility_problems(evidence: Any, *, fallback_venue: str,
                                  policy: Mapping[str, Any] | None) -> list[str]:
    """Why ``evidence`` does not show that ``fallback_venue`` is eligible (``[]``: it does).

    The record mirrors a registered target: dated SCIE indexing, the 2025 CAS upgraded
    major-category zone (a routine tier) with its category and source -- or, for a
    conference, the CCF rank of the configured edition -- and a fee-free route whose
    sourced evidence explicitly covers page, colour and submission charges.
    """

    config = eligibility_config(policy)
    prefix = f"fallback venue {fallback_venue!r}"
    if not config:
        return []
    if not isinstance(evidence, Mapping):
        return [
            f"{prefix} has no eligibility evidence (fallback_eligibility): record SCIE indexing, the "
            "2025 CAS major-category zone with its source, and the fee policy with its source "
            f"covering {', '.join(FALLBACK_REQUIRED_CHARGES)}"
        ]
    problems: list[str] = []
    if str(evidence.get("venue") or "").strip().casefold() != fallback_venue.strip().casefold():
        problems.append(f"{prefix}: fallback_eligibility.venue must name the fallback venue")
    if not _date(evidence.get("checked_at")):
        problems.append(f"{prefix}: fallback_eligibility.checked_at must be YYYY-MM-DD")
    kind = str(evidence.get("venue_type") or "journal")
    if kind == "journal":
        rules = config["journal"]
        indexing = evidence.get("indexing")
        indexes = set()
        if isinstance(indexing, Mapping) and isinstance(indexing.get("indexes"), list):
            indexes = {str(x).strip().upper() for x in indexing["indexes"]}
        if not set(rules["required_indexes"]).issubset(indexes):
            problems.append(
                f"{prefix}: fallback_eligibility.indexing.indexes must include "
                f"{rules['required_indexes']} (ESCI-only journals are not eligible)"
            )
        if not isinstance(indexing, Mapping) or not _http(indexing.get("source")) \
                or not _date(indexing.get("checked_at")):
            problems.append(f"{prefix}: fallback_eligibility.indexing needs an HTTP(S) source and checked_at")
        year = (policy or {}).get("classification_year", 2025)
        if evidence.get("ranking_year") != year or evidence.get("ranking_scope") != "major_category":
            problems.append(
                f"{prefix}: the zone must come from the {year} CAS upgraded-edition major-category "
                "table (ranking_year, ranking_scope: major_category)"
            )
        tier = evidence.get("tier")
        if type(tier) is not int or tier not in rules["routine_tiers"]:
            problems.append(
                f"{prefix}: fallback_eligibility.tier must be a routine CAS zone "
                f"{sorted(rules['routine_tiers'])}"
            )
        if not _filled(evidence.get("ranking_category")) or not _http(evidence.get("ranking_source")):
            problems.append(f"{prefix}: fallback_eligibility needs ranking_category and an HTTP(S) ranking_source")
        expected_fee = "no_mandatory_author_fee"
        fee_required = rules["require_no_mandatory_author_fee"]
    elif kind == "conference":
        rules = config["conference"]
        ccf = evidence.get("ccf")
        ccf = ccf if isinstance(ccf, Mapping) else {}
        if str(ccf.get("rank") or "").upper() not in rules["routine_ccf_ranks"]:
            problems.append(
                f"{prefix}: fallback_eligibility.ccf.rank must be a routine CCF rank "
                f"{sorted(rules['routine_ccf_ranks'])}"
            )
        if rules["ccf_list_edition"] and str(ccf.get("edition") or "") != rules["ccf_list_edition"]:
            problems.append(f"{prefix}: fallback_eligibility.ccf.edition must be {rules['ccf_list_edition']!r}")
        if not _filled(ccf.get("category")) or not _http(ccf.get("source")) or not _date(ccf.get("checked_at")):
            problems.append(f"{prefix}: fallback_eligibility.ccf needs category, an HTTP(S) source and checked_at")
        expected_fee = "no_mandatory_publication_fee"
        fee_required = rules["require_no_mandatory_publication_fee"]
    else:
        return [*problems, f"{prefix}: fallback_eligibility.venue_type must be journal or conference"]
    if fee_required:
        if evidence.get("fee_policy") != expected_fee:
            problems.append(
                f"{prefix} is not eligible: fallback_eligibility.fee_policy must be {expected_fee} "
                "(a mandatory page, colour or submission charge disqualifies it even without an APC)"
            )
        if not _http(evidence.get("fee_source")):
            problems.append(f"{prefix}: fallback_eligibility.fee_source must be an HTTP(S) source")
        checked = evidence.get("fee_charges_checked")
        checked = {str(x).strip().casefold() for x in checked} if isinstance(checked, list) else set()
        missing = [charge for charge in FALLBACK_REQUIRED_CHARGES if charge not in checked]
        if missing:
            problems.append(
                f"{prefix}: fallback_eligibility.fee_charges_checked must cover "
                f"{', '.join(FALLBACK_REQUIRED_CHARGES)} (missing {', '.join(missing)}); "
                "\"no APC\" alone does not rule out page or colour charges"
            )
        if not _filled(evidence.get("fee_evidence")):
            problems.append(
                f"{prefix}: fallback_eligibility.fee_evidence must quote the publisher text on charges"
            )
    return problems


def validate_fallback_eligibility(evidence: Any, *, fallback_venue: str,
                                  policy: Mapping[str, Any] | None) -> None:
    problems = fallback_eligibility_problems(evidence, fallback_venue=fallback_venue, policy=policy)
    if problems:
        raise ValueError("; ".join(problems))


def _validate_executed_fallback(paper: Mapping[str, Any], *, paper_id: str, venue: str,
                                policy: Mapping[str, Any] | None) -> None:
    """A paper now targeting its registered fallback venue must have passed the fallback check.

    Older escalation records without ``fallback_eligibility`` stay loadable while the
    escalation target is current; the evidence is required when the fallback is used.
    """

    record = paper.get("target_escalation")
    if not isinstance(record, Mapping):
        return
    fallback = str(record.get("fallback_venue") or "").strip()
    if not fallback or fallback.casefold() != venue.strip().casefold():
        return
    if str(record.get("venue") or "").strip().casefold() == fallback.casefold():
        return
    problems = fallback_eligibility_problems(
        record.get("fallback_eligibility"), fallback_venue=fallback, policy=policy
    )
    if problems:
        raise ValueError(
            f"{paper_id} targets its registered fallback venue without passing the fallback "
            f"eligibility check: {'; '.join(problems)}"
        )


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


def provisional_escalation_blockers(paper: Mapping[str, Any], policy: Mapping[str, Any] | None,
                                    *, paper_id: str, root: str | Path | None = None) -> list[str]:
    """Why a provisional escalation target cannot be delivered yet (``[]``: it can).

    Delivery needs a ready unified review whose score (the lowest referee overall
    score) meets ``venue_eligibility.escalation.minimum_internal_score``, or the lower
    floor of a valid owner ``score_waiver`` (the review must still be ready).
    """

    record = paper.get("target_escalation")
    if not isinstance(record, Mapping) or record.get("status") != "provisional":
        return []
    config = eligibility_config(policy)
    if not config or not is_escalation_venue(paper, policy):
        return []
    try:
        minimum = escalation_minimum(paper, policy, paper_id=paper_id, root=root)
    except ValueError as exc:
        return [str(exc)]
    release = paper.get("writing_release")
    release = release if isinstance(release, Mapping) else {}
    score = release.get("score")
    if release.get("status") != "ready":
        return [f"target_escalation for {paper_id} is provisional and the review is not ready"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return [f"target_escalation for {paper_id} is provisional and has no internal review score"]
    if float(score) < minimum:
        return [
            f"target_escalation for {paper_id} is provisional: internal review score {score} is "
            f"below the escalation minimum {minimum:g}; deliver at the fallback venue instead"
        ]
    if not _filled(release.get("decision_record")):
        return [f"target_escalation for {paper_id} is provisional and the review has no record"]
    return []


def is_escalation_venue(paper: Mapping[str, Any], policy: Mapping[str, Any] | None) -> bool:
    config = eligibility_config(policy)
    if not config:
        return False
    if paper.get("target_conference"):
        ccf = paper.get("target_conference_ccf")
        return isinstance(ccf, Mapping) and str(ccf.get("rank") or "").upper() in config["escalation"]["ccf_ranks"]
    return paper.get("target_journal_tier") in config["escalation"]["journal_tiers"]
