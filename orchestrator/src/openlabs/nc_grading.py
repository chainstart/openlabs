"""Journal grading of NC-aim topics before writing (user decision 2026-11-25, item 3).

User, 2026-11-25 ("以上都同意", UD-20261125-nc-aim-decisions): the journal tier of an NC-aim
topic is graded before the manuscript is written, so the writer writes for the graded
journal (length, abstract, title, display items). It is not graded again at review-ready.

Flow (owner mode):

1. An owner seat says the research is done (``phase: writing``, or ``ready_for_review``
   before any review). Its packet carries ``nc_readiness``: the decisive analysis and the
   four required checks (sensitivity, uncertainty, external validation, baseline or
   confounder check), each ``{"done": true, "evidence": "..."}``. Missing items send the
   owner back up to ``[program.funnel].readiness_returns`` times; after that the grade is
   taken with the missing items as reasons (the grader grades down).
2. The control plane holds the topic (no writer seat, no next owner seat) and schedules a
   cross-family direction decision ``pre_writing_grade`` with the calibration set. The
   rules are those of the review-time grade (:func:`openlabs.nc_funnel.nc_grade`).
3. The grade is recorded on the topic (``venue_grade`` with ``point: pre_writing`` and the
   journal's format limits) and in the owner state; writing resumes: the writer seat
   (hand-over plan) or the owner's next seat, both told the journal and its format.
4. Review ready: the topic goes straight to the ready queue; the grade is not re-checked
   (pipeline slimming 2026-11-26, "同意，精简产线"). A significance shortfall found in
   review still goes through REVIEW_DIRECTION / retarget.

A decision that cannot be taken (retries used up) lets writing continue ungraded; the
review-time full grade of before stays the fallback for such topics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

TRIGGER_PRE_WRITING = "pre_writing_grade"
POINT_PRE_WRITING = "pre_writing"
POINT_AFTER_REVIEW = "after_review"
# Grades taken before writing; "recheck" is a grade re-checked at review-ready before
# 2026-11-26 (the NC-trial ECG topic carries one).
GRADED_BEFORE_WRITING = frozenset({POINT_PRE_WRITING, "recheck"})
ROUTING_READINESS = "owner_nc_readiness"
ROUTING_GRADED = "owner_venue_graded"

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

PRE_WRITING_INSTRUCTION = (
    " This grade is taken BEFORE writing (user decision 2026-11-25): there is no manuscript "
    "yet. Grade the completed research - OWNER_LOG.md, research_state.json, the owner's "
    "status packet (nc_readiness: the decisive analysis and the four required checks) and the "
    "result files they name. Missing or failed checks count against the band. The writer "
    "then writes for the journal you choose, in its length and format."
)

def _funnel(settings) -> Any:
    return getattr(getattr(settings, "program", None), "funnel", None)


def enabled(settings, topic: Mapping[str, Any] | None) -> bool:
    """Whether this topic is graded before writing (an NC-aim topic, setting on)."""

    from . import target_stage

    funnel = _funnel(settings)
    if topic is None or funnel is None or not getattr(funnel, "grade_before_writing", True):
        return False
    if str(topic.get("research_line") or "") in set(getattr(funnel, "exempt_lines", ()) or ()):
        return False
    return target_stage.admitted_stage(topic) == target_stage.NC_AIM


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


def pre_writing_due(settings, topic: Mapping[str, Any] | None, before: Mapping[str, Any],
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
        "Before writing, the journal tier of this NC-aim topic is graded from the completed "
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
    funnel = _funnel(settings)
    returns = int((before.get("nc_pre_writing") or {}).get("readiness_returns") or 0)
    missing = readiness_missing(packet)
    if missing and returns < int(getattr(funnel, "readiness_returns", 2)):
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
        "NC aim and its format. The journal is graded after review instead.")
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
