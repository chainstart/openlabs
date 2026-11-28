"""Journal grading of topics before writing (user decision 2026-11-25, item 3).

User, 2026-11-25 ("以上都同意", UD-20261125-nc-aim-decisions): the journal tier of a
topic is graded from the completed research before the manuscript is written, so the
writer writes for the graded journal (length, abstract, title, display items). It is not
graded again at review-ready.

Flow (owner mode):

1. An owner seat says the research is done (``phase: writing``, or ``ready_for_review``
   before any review). Its packet carries ``nc_readiness``: the decisive analysis and the
   four required checks (sensitivity, uncertainty, external validation, baseline or
   confounder check), each ``{"done": true, "evidence": "..."}``. Missing items send the
   owner back up to ``READINESS_RETURNS`` times; after that the grade is taken with the
   missing items as reasons (the grader grades down).
2. The control plane holds the topic (no writer seat, no next owner seat) and schedules a
   cross-family direction decision ``pre_writing_grade`` with the calibration set. The
   rules are those of :func:`nc_grade`.
3. The grade is recorded on the topic (``venue_grade`` with ``point: pre_writing`` and the
   journal's format limits) and in the owner state; writing resumes: the writer seat
   (hand-over plan) or the owner's next seat, both told the journal and its format.
4. Review ready: the topic goes straight to the ready queue; the grade is not re-checked
   (pipeline slimming 2026-11-26, "同意，精简产线"). A significance shortfall found in
   review still goes through REVIEW_DIRECTION / retarget.

A decision that cannot be taken (retries used up) lets writing continue ungraded; the
review-time full grade stays the fallback for such topics.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TRIGGER_PRE_WRITING = "pre_writing_grade"
POINT_PRE_WRITING = "pre_writing"
POINT_AFTER_REVIEW = "after_review"
# Grades taken before writing; "recheck" is a grade re-checked at review-ready before
# 2026-11-26 (the NC-trial ECG topic carries one).
GRADED_BEFORE_WRITING = frozenset({POINT_PRE_WRITING, "recheck"})
ROUTING_READINESS = "owner_nc_readiness"
ROUTING_GRADED = "owner_venue_graded"

# Evidence-based journal grading constants (moved from the deleted nc_funnel.py).
THRESHOLDS = ("generality", "counterintuitive", "scale", "benchmark", "resource")
THRESHOLD_TEXT = {
    "generality": "the question is general (global, whole-population, or a law across systems)",
    "counterintuitive": "a one-sentence counter-intuitive conclusion",
    "scale": "an order of magnitude (at least 4x) larger than the largest prior study",
    "benchmark": "benchmarked against an authoritative reference or a policy parameter",
    "resource": "delivers a reusable resource (dataset, catalogue, benchmark, tool)",
}
BANDS = ("nc", "zone_1", "zone_2", "zones_3_4")  # best first
BAND_ZONES = {"zone_1": {1}, "zone_2": {2}, "zones_3_4": {3, 4}}
CONFIDENCE = ("high", "medium", "low")
CALIBRATION_PATH = "registry/venue-calibration.yaml"
MIN_NC_THRESHOLDS = 2
READINESS_RETURNS = 2
# Reporting reference only (user 2026-11-25: ~2-3 NC and ~2-3 Zone 1 per 10 topics).
TARGET_MIX_PER_10: dict[str, tuple[int, int]] = {"nc": (2, 3), "zone_1": (2, 3)}

READINESS_ITEMS = ("decisive_analysis", "sensitivity", "uncertainty", "external_validation",
                   "baseline_or_confounding")
READINESS_TEXT = {
    "decisive_analysis": "the decisive analysis (first milestone: does the main claim hold)",
    "sensitivity": "sensitivity analysis",
    "uncertainty": "uncertainty quantification",
    "external_validation": "external validation",
    "baseline_or_confounding": "a simple baseline or a confounder check",
}

READINESS_PACKET = (
    "`nc_readiness` in the status packet: {" + ", ".join(f'"{key}"' for key in READINESS_ITEMS)
    + "}, each {\"done\": true, \"evidence\": \"result file or one line\"}."
)

GRADE_INSTRUCTION = (
    " Evidence-based journal grading (user decision 2026-11-25: the data decide the journal; "
    "this is a hard criterion). Read the calibration set (read_resources venue-calibration: "
    "accepted NC papers with their hooks, and same-subject papers of lower-tier journals) and "
    "first answer which tier this manuscript looks like (retarget.calibration_match: nc, "
    "zone_1, zone_2 or zones_3_4, with retarget.calibration_neighbours: the ids of the 2-3 "
    "closest calibration papers). Then score the NC thresholds on the actual evidence in "
    "retarget.nc_scorecard {" + ", ".join(THRESHOLDS) + ": {met, evidence}} and set "
    "retarget.confidence (high|medium|low). Set retarget.achieved_band to nc only when at "
    "least the required number of thresholds hold on the evidence, the calibration match is "
    "nc and your confidence is high; otherwise grade down step by step: zone_1, zone_2, "
    "zones_3_4. achieved_band is never higher than calibration_match. Choose an exact "
    "journal of that band from verified_alternatives (grading.nc_journals for nc, the CAS "
    "zone for the others) and explain the scope fit in retarget.why_fits. The manuscript "
    "keeps top-journal writing and figure standards in every band; a lower band only changes "
    "the journal and its length and format. If no verified journal fits the supported band, "
    "use freeze with no_eligible_venue and a concrete reopen condition."
)

PRE_WRITING_INSTRUCTION = (
    " This grade is taken BEFORE writing (user decision 2026-11-25): there is no manuscript "
    "yet. Grade the completed research - OWNER_LOG.md, research_state.json, the owner's "
    "status packet (nc_readiness: the decisive analysis and the four required checks) and the "
    "result files they name. Missing or failed checks count against the band. The writer "
    "then writes for the journal you choose, in its length and format."
)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _program(settings: Any) -> Any:
    return getattr(settings, "program", None)


def _grade_before_writing(settings: Any) -> bool:
    program = _program(settings)
    if program is None:
        return False
    if hasattr(program, "grade_before_writing"):
        return bool(program.grade_before_writing)
    funnel = getattr(program, "funnel", None)
    return bool(getattr(funnel, "grade_before_writing", True)) if funnel is not None else False


def _nc_journals(settings: Any) -> tuple[str, ...]:
    program = _program(settings)
    if program is not None and hasattr(program, "nc_journals"):
        return tuple(program.nc_journals)
    funnel = getattr(program, "funnel", None)
    if funnel is not None and hasattr(funnel, "nc_journals"):
        return tuple(funnel.nc_journals)
    return ("Nature Communications",)


def _readiness_returns(settings: Any) -> int:
    program = _program(settings)
    if program is not None and hasattr(program, "readiness_returns"):
        return int(program.readiness_returns)
    funnel = getattr(program, "funnel", None)
    if funnel is not None and hasattr(funnel, "readiness_returns"):
        return int(funnel.readiness_returns)
    return READINESS_RETURNS


def _min_nc_thresholds(settings: Any) -> int:
    funnel = getattr(_program(settings), "funnel", None)
    if funnel is not None and hasattr(funnel, "min_nc_thresholds"):
        return int(funnel.min_nc_thresholds)
    return MIN_NC_THRESHOLDS


def admitted_stage(topic: Mapping[str, Any] | None) -> str:
    """Grading mode of a topic: ``nc_aim`` (unified), ``tier2_aim`` (legacy) or ``run_in``."""

    if not isinstance(topic, Mapping):
        return "run_in"
    admission = topic.get("admission")
    if isinstance(admission, Mapping):
        stage = admission.get("target_stage")
        if stage in {"run_in", "tier2_aim", "nc_aim"}:
            return str(stage)
        # Historical pre-NC-aim topics (policy v2 / verdict admit without target_stage)
        # keep their ungraded run_in behaviour untouched.
        if (admission.get("policy") == "openlabs.topic_admission_policy.v2"
                or admission.get("verdict") == "admit"):
            return "run_in"
    elif admission == "grandfathered":
        return "run_in"
    return "nc_aim"


def band_rank(band: Any) -> int:
    return BANDS.index(band) if band in BANDS else len(BANDS)


def calibrated_band(band: Any, match: Any) -> str:
    """The worse of a claimed band and the calibration match (the grading ruler)."""

    return BANDS[min(max(band_rank(band), band_rank(match)), len(BANDS) - 1)]


def met_thresholds(block: Any) -> list[str]:
    """Threshold ids marked ``met: true`` with evidence in a ``nc_scorecard`` block."""

    if not isinstance(block, Mapping):
        return []
    return [key for key in THRESHOLDS
            if isinstance(block.get(key), Mapping) and block[key].get("met") is True
            and _text(block[key].get("evidence"))]


def calibration_resource(paths: Any) -> dict[str, str] | None:
    path = Path(paths.data) / CALIBRATION_PATH
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"label": "venue-calibration", "path": str(path.resolve()), "sha256": digest}


def _admitted_band(topic: Mapping[str, Any]) -> Any:
    """Informational band recorded at review/admission, if any."""

    admission = topic.get("admission") if isinstance(topic.get("admission"), Mapping) else {}
    if admission.get("likely_band"):
        return admission.get("likely_band")
    if isinstance(admission.get("nc_assessment"), Mapping):
        return admission["nc_assessment"].get("expected_band")
    check = topic.get("card_check") if isinstance(topic.get("card_check"), Mapping) else {}
    prescreen = check.get("prescreen") if isinstance(check.get("prescreen"), Mapping) else {}
    return prescreen.get("expected_band")


def grading_packet(settings: Any, topic: Mapping[str, Any]) -> dict[str, Any]:
    minimum = _min_nc_thresholds(settings)
    return {
        "stage": "nc_aim",
        "bands": list(BANDS),
        "nc_journals": list(_nc_journals(settings)),
        "thresholds": THRESHOLD_TEXT,
        "expected_band_at_admission": _admitted_band(topic),
        "rules": (f"achieved_band nc needs >= {minimum} thresholds met in "
                  "nc_scorecard, calibration_match nc and confidence high, and a journal of "
                  "nc_journals; zone_1 / zone_2 / zones_3_4 need a verified journal of that CAS "
                  "zone; achieved_band is never higher than calibration_match"),
        "calibration": CALIBRATION_PATH,
    }


def nc_grade(decision: Mapping[str, Any], venues: list[dict], settings: Any = None) -> dict | None:
    """The acceptance grade of a topic, or None when the decision breaks the rule."""

    minimum = _min_nc_thresholds(settings)
    nc_journals = {name.casefold() for name in _nc_journals(settings)}
    retarget = decision["retarget"]
    journal = str(retarget.get("venue_or_format") or "")
    band = _text(retarget.get("achieved_band"))
    if band not in BANDS:
        return None
    scorecard = retarget.get("nc_scorecard")
    met = met_thresholds(scorecard)
    match = _text(retarget.get("calibration_match"))
    confidence = _text(retarget.get("confidence"))
    if match not in BANDS or confidence not in CONFIDENCE or not isinstance(scorecard, Mapping):
        return None
    zone = next((v.get("cas_2025_zone") for v in venues if v.get("journal") == journal), None)
    if calibrated_band(band, match) != band:
        return None
    if band == "nc":
        if journal.casefold() not in nc_journals or len(met) < minimum or confidence != "high":
            return None
    elif zone not in BAND_ZONES[band] or journal.casefold() in nc_journals:
        return None
    return {"journal": journal, "cas_2025_zone": zone, "achieved_band": band,
            "nc_scorecard": {key: dict(scorecard.get(key) or {}) for key in THRESHOLDS},
            "met_thresholds": met, "calibration_match": match,
            "calibration_neighbours": list(retarget.get("calibration_neighbours") or [])[:5],
            "confidence": confidence, "stage": "nc_aim",
            "rationale": decision["rationale"], "why_fits": retarget["why_fits"]}


def venue_grade(decision: Mapping[str, Any], venues: list[dict], *,
                stage: str = "nc_aim", settings: Any = None) -> dict | None:
    """Check that the chosen verified journal belongs to the judged evidence band."""

    if stage == "nc_aim":
        return nc_grade(decision, venues, settings)
    retarget = decision["retarget"]
    journal = retarget["venue_or_format"]
    zone = next((v["cas_2025_zone"] for v in venues if v["journal"] == journal), None)
    bands = {1: "zones_1_2", 2: "zones_1_2", 3: "zones_3_4", 4: "zones_3_4"}
    band = bands.get(zone)
    if band is None or band != retarget.get("achieved_band"):
        return None
    return {"journal": journal, "cas_2025_zone": zone, "achieved_band": band,
            "rationale": decision["rationale"], "why_fits": retarget["why_fits"]}


def enabled(settings: Any, topic: Mapping[str, Any] | None) -> bool:
    """Whether this topic is graded before writing."""

    if topic is None or not _grade_before_writing(settings):
        return False
    program = _program(settings)
    if program is not None and hasattr(program, "line"):
        line = program.line(topic.get("research_line"))
        if getattr(line, "nc_aim", True) is False:
            return False
    return admitted_stage(topic) == "nc_aim"


def needs_acceptance_grade(settings: Any, topic: Mapping[str, Any] | None) -> bool:
    """Whether a review-ready topic requires a journal grade before entering ready_queue."""

    stage = admitted_stage(topic)
    if stage == "tier2_aim":
        return True
    if stage == "nc_aim":
        return _grade_before_writing(settings)
    return False


def research_done(before: Mapping[str, Any], packet: Mapping[str, Any], *,
                  successful: bool) -> bool:
    """The seat says the research is done and no manuscript has been reviewed yet."""

    if not successful:
        return False
    status = str(packet.get("status") or "").strip().lower()
    phase = str(packet.get("phase") or "").strip().lower()
    if not (status == "ready_for_review" or (status == "continuing" and phase == "writing")):
        return False
    if before.get("review_history") or before.get("review_round") or before.get("review_stage"):
        return False
    return True


def readiness_missing(packet: Mapping[str, Any]) -> list[str]:
    """Required checks the packet does not report as done with evidence."""

    block = packet.get("nc_readiness")
    block = block if isinstance(block, Mapping) else {}
    missing = []
    for key in READINESS_ITEMS:
        item = block.get(key)
        done = isinstance(item, Mapping) and item.get("done") is True and \
            isinstance(item.get("evidence"), str) and item["evidence"].strip()
        if not done:
            missing.append(key)
    return missing


def pre_writing_due(settings: Any, topic: Mapping[str, Any] | None, before: Mapping[str, Any],
                    packet: Mapping[str, Any], *, successful: bool) -> bool:
    if not enabled(settings, topic) or not research_done(before, packet, successful=successful):
        return False
    assert topic is not None
    if topic.get("venue_grade"):
        return False  # graded already (before writing, or a legacy review-time grade)
    if (before.get("nc_pre_writing") or {}).get("status") in {"ungraded", "graded"}:
        return False  # the decision ran (or could not run): writing goes on
    return True


def readiness_note(missing: list[str]) -> str:
    items = "; ".join(READINESS_TEXT[key] for key in missing)
    return (
        "Before writing, the journal tier of this topic is graded from the completed "
        f"research (user decision 2026-11-25). Not yet reported as done: {items}. Complete "
        "them, then end the seat again with phase writing (or ready_for_review) and "
        + READINESS_PACKET + " A check that cannot be done: say so in its evidence with done "
        "false; the grade then counts it against the band."
    )


def hold_for_grade(db, paths, settings, report, *, task: Mapping[str, Any],
                   campaign: Mapping[str, Any], topic: Mapping[str, Any],
                   packet: Mapping[str, Any], before: Mapping[str, Any],
                   result_path: Path, result_sha256: str | None, seat_trigger: str) -> bool:
    """Send the owner back for missing checks, or schedule the grade. True: held."""

    from . import owner as owner_mode
    from .program_autonomy import pending_decision, schedule_direction_decision

    campaign_id = str(campaign["campaign_id"])
    returns = int((before.get("nc_pre_writing") or {}).get("readiness_returns") or 0)
    missing = readiness_missing(packet)
    if missing and returns < _readiness_returns(settings):
        owner_mode.update_state(
            db, campaign_id, "owner_nc_readiness_returned",
            {"task_id": str(task["task_id"]), "missing": missing},
            nc_pre_writing={"status": "readiness", "readiness_returns": returns + 1,
                            "missing": missing})
        owner_mode.enqueue_seat(db, settings, report, campaign=campaign, parent=task,
                                note=readiness_note(missing), routing_reason=ROUTING_READINESS,
                                input_path=str(result_path))
        report.program.setdefault("nc_pre_writing", []).append(
            {"campaign_id": campaign_id, "action": "readiness_returned", "missing": missing})
        return True
    if pending_decision(db, campaign_id) is not None:
        return True
    reasons = ([f"Not reported as done before writing: "
                + "; ".join(READINESS_TEXT[key] for key in missing) + "."] if missing else None)
    work = Path(str(campaign.get("workstream_state_path") or ""))
    evidence = [{"path": str(result_path), "sha256": result_sha256 or ""}]
    if work.is_file():
        from .program_autonomy import _evidence

        evidence.append(_evidence(work))
    scheduled = schedule_direction_decision(
        db, paths, settings, report, topic=topic, trigger=TRIGGER_PRE_WRITING,
        source_task_id=str(task["task_id"]), evidence=evidence, reasons=reasons,
        detail={"seat_trigger": seat_trigger, "result_path": str(result_path),
                "nc_readiness": dict(packet.get("nc_readiness") or {})
                if isinstance(packet.get("nc_readiness"), Mapping) else {},
                "missing": missing, "paper_id": packet.get("paper_id")},
    )
    if scheduled is None:
        return False
    # Who writes, decided on the state before this seat (the seat itself already recorded
    # phase writing, which would read as "the owner began writing").
    plan, _why = owner_mode.writing_plan(settings, before, str(task.get("runner") or ""))
    owner_mode.update_state(
        db, campaign_id, "owner_pre_writing_grade_scheduled",
        {"decision_task": scheduled, "missing": missing},
        nc_pre_writing={"status": "pending", "decision_task": scheduled, "writing_plan": plan,
                        "readiness_returns": returns, "missing": missing,
                        "seat_trigger": seat_trigger, "source_task_id": str(task["task_id"])})
    report.program.setdefault("nc_pre_writing", []).append(
        {"campaign_id": campaign_id, "action": "grade_scheduled", "task_id": scheduled,
         "missing": missing})
    return True


def venue_format(paths, journal: str) -> dict[str, Any] | None:
    """The journal's article-type limits from registry/verified-venues.yaml, if recorded."""

    import yaml

    path = Path(paths.data) / "registry" / "verified-venues.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    key = journal.casefold()
    for entry in document.get("venues") or []:
        if not isinstance(entry, Mapping):
            continue
        names = {str(entry.get("journal") or "").casefold(),
                 *(str(alias).casefold() for alias in entry.get("aliases") or [])}
        if key in names:
            types = entry.get("article_types")
            if isinstance(types, Mapping) and types:
                name, limits = next(iter(types.items()))
                if isinstance(limits, Mapping):
                    return {"article_type": str(name), **{k: v for k, v in limits.items()}}
            return None
    return None


def format_text(grade: Mapping[str, Any]) -> str:
    form = grade.get("format") if isinstance(grade.get("format"), Mapping) else None
    if not form:
        return ("Follow that journal's guide for authors for length, abstract, title and "
                "display items (`paper-writing venue lookup --journal`).")
    labels = {"max_body_words": "main text <= {} words", "max_abstract_words": "abstract <= {} words",
              "max_title_words": "title <= {} words", "max_display_items": "<= {} display items",
              "max_methods_words": "Methods <= {} words", "max_references": "<= {} references"}
    parts = [labels[key].format(form[key]) for key in labels if form.get(key)]
    return (f"Format ({form.get('article_type', 'article')}): " + ", ".join(parts)
            + (f" (source {form['source']})." if form.get("source") else "."))


def grade_note(grade: Mapping[str, Any]) -> str:
    return (
        f"Journal graded before writing (user decision 2026-11-25): {grade.get('journal')} "
        f"(band {grade.get('achieved_band')}, confidence {grade.get('confidence')}). Write the "
        f"manuscript for this journal and set it as target_journal. {format_text(grade)} "
        "Writing and figures keep the top-journal standard."
    )


def resume_writing(db, paths, settings, report, *, topic: Mapping[str, Any],
                   source_task_id: str, detail: Mapping[str, Any],
                   grade: Mapping[str, Any] | None, reason: str) -> str | None:
    """After the grade (or when it could not be taken): the writer or the owner writes."""

    from . import owner as owner_mode

    campaign_id = str(topic.get("campaign_id") or "")
    campaign = db.campaign(campaign_id)
    task = db.task(source_task_id)
    if campaign is None or task is None:
        return None
    status = "graded" if grade is not None else "ungraded"
    plan = (owner_mode.owner_state(db, campaign_id).get("nc_pre_writing") or {}).get(
        "writing_plan")
    owner_mode.update_state(
        db, campaign_id, "owner_pre_writing_grade_" + status,
        {"reason": reason, "journal": (grade or {}).get("journal")},
        nc_pre_writing={**dict(owner_mode.owner_state(db, campaign_id).get("nc_pre_writing")
                               or {}), "status": status, "reason": reason},
        **({"venue_grade": dict(grade)} if grade is not None else {}))
    note = grade_note(grade) if grade is not None else (
        "The journal grade before writing could not be taken (" + reason + "); write for the "
        "target journal and its format. The journal is graded after review instead.")
    result_path = Path(str(detail.get("result_path") or task.get("result_path") or ""))
    if plan == owner_mode.PLAN_HANDOVER and settings.program.owner.writing_runner:
        seat = owner_mode.start_writing(
            db, paths, settings, report, task=task, campaign=campaign,
            trigger=str(detail.get("seat_trigger") or "phase_writing"),
            result_path=result_path, extra_note=note)
    else:
        seat = owner_mode.enqueue_seat(
            db, settings, report, campaign=campaign, parent=task, note=note,
            routing_reason=ROUTING_GRADED, input_path=str(result_path),
            task_id=owner_mode.seat_id(campaign_id, "venue-graded:" + source_task_id))
    report.program.setdefault("nc_pre_writing", []).append(
        {"campaign_id": campaign_id, "action": "writing_resumed", "seat": seat,
         "graded": grade is not None, "journal": (grade or {}).get("journal")})
    return seat
