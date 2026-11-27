"""NC-aimed topic funnel (user decision 2026-11-25, UD-20261125-nc-aim).

Every topic aims at Nature Communications; the journal is decided by the results (NC, then
CAS Zone 1, 2, 3-4). Topic supply is a graded funnel; each level is dearer and stricter than
the one before (design: maintenance/20261125-nc-aim/DESIGN.md):

L0 scout (``program_flow.schedule_scouts``)        pool low water, interval, empty-draw backoff,
                                                    plus :func:`scout_blocks` (weekly model
                                                    budget per line, funnel-stall backoff)
L1 mechanical (:func:`screen_card`, no model)       data catalogue, capacity, near duplicates
                                                    (the NC case is a card contract field)
L2+L3 ``topic_prescreen`` task (:func:`advance_prescreens`)
                                                    calibration match, quick novelty +
                                                    independent NC thresholds, then a <= 2
                                                    core-hour kill test
L4 admission (:func:`admission_problems`)           checks the prescreen (thresholds,
                                                    calibration match, kill test), adds the
                                                    >= 50-paper novelty search
L5 research                                         milestones, decisive analysis first
L6 grading (:func:`nc_grade`)                       scorecard + calibration set, hard rule

Hard stops are only: data unavailable, fewer than ``min_nc_thresholds`` thresholds in the
prescreen, a kill test whose signal is absent, and an expected band below
``admission_min_band``. The scout's own threshold claims are recorded, not screened
(pipeline slimming 2026-11-26: L1 rejected 0 of 23 cards on them). Everything
else is recorded for the next level (``card_check``). Parameters: ``[program.funnel]``.

One ruler (NC trial 2026-11-25, maintenance/20261125-nc-trial/REPORT.md section 5): the
prescreen, the admission gate and the grade all read the same calibration set
(``registry/venue-calibration.yaml``) and first say which tier the topic resembles
(``calibration_match``); a band is never better than that match (:func:`calibrated_band`).
The trial's ECG topic was admitted as zone_1 and graded zones_3_4 before writing because only
the grader had the calibration set.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import SUPPLY_STAGE
from .db import utc_now

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
NOVELTY_VERDICTS = ("clear", "incremental", "scooped")

PRESCREEN_TASK_TYPE = "topic_prescreen"
PRESCREEN_ROUTING_REASON = "topic_prescreen"
PRESCREEN_PACKET_SCHEMA = "openlabs.topic_prescreen_packet.v1"
PRESCREEN_DECIDER = "orchestrator:nc_prescreen"
PRESCREEN_WAITING = frozenset({"pending", "scheduled"})

DATA_REJECTION = "card_data_unavailable"
CAPACITY_REJECTION = "card_beyond_capacity"
DUPLICATE_REJECTION = "card_near_duplicate"
PRESCREEN_REJECTION = "card_prescreen_failed"
KILL_TEST_REJECTION = "card_kill_test_failed"
BAND_REJECTION = "card_expected_band_below_floor"
PRESCREEN_UNAVAILABLE = "card_prescreen_unavailable"
ADMISSION_REJECTION = "nc_aim_admission_requirements"
L1_REJECTIONS = frozenset({DATA_REJECTION, CAPACITY_REJECTION, DUPLICATE_REJECTION})
L23_REJECTIONS = frozenset({PRESCREEN_REJECTION, KILL_TEST_REJECTION, BAND_REJECTION,
                            PRESCREEN_UNAVAILABLE})
# Reasons that judged a topic on its merits (a same-fingerprint card is a duplicate).
JUDGED = frozenset({PRESCREEN_REJECTION, KILL_TEST_REJECTION,
                    BAND_REJECTION, ADMISSION_REJECTION, DUPLICATE_REJECTION})
CALIBRATION_PATH = "registry/venue-calibration.yaml"
# Read resources of scouts, prescreens and the admission gate (copies of the maintenance reports).
NC_REFERENCES = (
    ("nc-survey", "registry/research-references/nc-survey-20261125.md"),
    ("nc-hotspots", "registry/research-references/nc-hotspots-20261126.md"),
)

# Few-shot hooks from the 2026-11-25 survey of 63 NC papers (maintenance/20261125-nc-survey,
# papers.md; DOIs verified there). The full set is the calibration file.
HOOKS = (
    ("E1", "Flash droughts cut global vegetation 9.0% vs 5.3% for ordinary droughts, and the "
           "loss grows 1.8% per decade (41 years, global)."),
    ("E3", "Warming makes 71% of basins' snowmelt floods earlier but ~30% later, because "
           "slower melt offsets the earlier start (243k floods, 70 years): overturns intuition."),
    ("E4", "Multi-thread channels are 51% of the world's alluvial river length, against the "
           "textbook view; the global map is released as a dataset."),
    ("E5", "Tropical-cyclone rain rate rises >20% in the 60 h before landfall in every basin "
           "and intensity class: a global regularity with hazard implications."),
    ("N1", "Simple models beat deep learning for PV forecasting in 17 of 20 site x horizon "
           "settings: a systematic re-evaluation of a mainstream practice."),
    ("N2", "Open probabilistic day-ahead forecasts beat the system operator's (CAISO) own "
           "forecast by ~25%: benchmarked against the authoritative operator."),
    ("N6", "Coping with the worst Dunkelflaute winter needs 351 TWh of long-duration storage "
           "(~7% of European demand), robust over many weather years: a policy parameter."),
    ("N7", "A ~55% tariff alone would cut Canadian power imports, raising prices and "
           "emissions: a topical policy scenario with open models."),
    ("M2", "An ECG model finds occlusion MI (C >= 0.95) with more detections than the "
           "commercial algorithm at equal false positives, externally validated in several "
           "countries."),
    ("M5", "Diagnose a general failure (cross-site shift and unfairness of pathology "
           "foundation models) first, then fix it for 3 models x 5 datasets."),
    ("A1", "Random splits leak: a drug-mean baseline explains ~67.5% of the variance and "
           "deep models lose to tuned trees under leave-drug-out: a field's progress claim "
           "audited."),
    ("A2", "Untrained models explain >80% of the 'brain alignment' of GPT2-XL under shuffled "
           "splits; >98% comes from position and word-rate confounds."),
    ("A5", "With structured missingness, linear interpolation is the most robust imputation; "
           "deep autoencoders only win under completely-at-random missingness."),
    ("L2", "A global atlas of Salmonella resistance over 1900-2023, 4x larger than before, "
           "with drivers: scale plus a century of time."),
    ("S1", "Doubling a city's population raises intra-urban inequality by ~8-9%: a universal "
           "law (accepted with R^2 ~0.04, carried by generality and scale)."),
    ("S2", "High-income countries' 7-day weather forecasts are as accurate as low-income "
           "countries' 1-day forecasts: one sentence, global, policy-relevant."),
    ("P4", "Across 48 globular clusters, blue-straggler frequency tracks the binary fraction "
           "(r = 0.81), not the collision rate: a uniform large sample settles a long debate."),
)


def hooks_text() -> str:
    return " ".join(f"[{key}] {text}" for key, text in HOOKS)


def thresholds_text() -> str:
    return "; ".join(f"`{key}`: {text}" for key, text in THRESHOLD_TEXT.items())


CALIBRATION_TEXT = (
    "Read the calibration set first (read_resources venue-calibration, "
    "registry/venue-calibration.yaml: accepted NC papers with their hooks and same-subject "
    "papers of lower-tier journals) and say which tier this topic resembles - compare the card, "
    "a plan, with each paper's `at_admission` (its question, data and design before the work), "
    "not with its published hook: calibration_match "
    "(nc|zone_1|zone_2|zones_3_4) with calibration_neighbours (the ids of the 2-3 closest "
    "calibration papers). The control plane places the topic no higher than its calibration "
    "match, the same rule as the acceptance grade before writing."
)


_SCOUT_TAIL = (
    "plus the rest of `nc_case` "
    "{claim, alternative_claim (the conclusion if the result goes the other way), challenges (the "
    "view, practice or number it overturns), benchmark (the authoritative reference, policy "
    "parameter or largest prior study it is measured against), thresholds {" + ", ".join(THRESHOLDS) + ": {met, "
    "evidence}}, exemplars [ids of the hooks below it resembles]}, `data_volume` {total_gb, "
    "largest_file_gb, proxy_expected, offpeak_days, ailab_storage_gb} (large proxy downloads "
    "only run 02:00-14:00 Beijing time), `kill_test` {signal, null_model, ceiling, pass_rule, "
    "core_hours <= 2}: the cheap test of whether the key signal exists, how much a null model "
    "or simple baseline explains and the theoretical ceiling, and `milestones` [{name, kind, "
    "agent_hours, core_hours, model_usd}] whose first item has kind `decisive` (the test that "
    "decides whether the main claim holds). Give each data source its data-catalogue "
    "`catalog_id`; a newly found source you verified gets `catalog_candidate: true`. "
    "For every decisive dataset in `data_sources[]`, check how it is obtained and whether every "
    "field needed for the decisive analysis actually exists in the public release, and record "
    "`access` {method: direct|form_or_registration|restricted, required_fields_present: bool, "
    "required_fields: [...], missing_fields: [...], registration: \"...\"}: e.g. Living Planet "
    "Database 2026 requires a named-recipient access form and non-commercial terms "
    "(method: form_or_registration, mark needs_registration on the card), while PhysioNet "
    "Challenge-2021 Georgia lacks a patient-linkage map for patient-disjoint splits "
    "(required_fields_present: false, missing_fields: [\"patient_linkage_map\"]). L1 rejects "
    "any decisive dataset that is restricted or missing a required field. NC "
    "thresholds (at least two must hold): " + thresholds_text() + ". Hooks of accepted NC "
    "papers: " + hooks_text() + " A card that cannot meet two thresholds is not proposed; "
    "do not re-propose a direction the ledger shows rejected or frozen for its substance. "
    "Entries of ledger_snapshot carry `screen_feedback` when the independent prescreen "
    "judged an earlier card (the thresholds that held on its reading, novelty, expected band, "
    "why it failed, its summary): your own threshold claims are checked the same way, so do "
    "not propose a card that would fail for the same reason (for example a single-catalogue or "
    "reporting-rule audit is not a general question, an unvalidated proxy cannot support a "
    "real-world failure claim, and an effect a simple null model explains is not a finding). Work "
    "in the skill's NC order: the field's substantive question, the complete free data that "
    "directly answers it (the claim is about the full population; only the kill test uses a "
    "subset), a novelty search across NC/Nature/Science and the last 18 months of preprints "
    "(Research Square, arXiv, bioRxiv, medRxiv, SSRN, EarthArXiv) separating the same claim from "
    "adjacent work, then the kill test. Keep the free-data rule: paid and blocked sources are "
    "forbidden; a free source that needs a registration may carry the full-scale analysis when "
    "the card marks it needs_registration (what to register) and the kill test runs on data "
    "obtainable now. Optional illustrations, never limits or a checklist to converge on "
    "(read_resources nc-survey and nc-hotspots): the ten templates of nc-hotspots section 2 "
    "(A-J, with their citation statistics and crowding) and the line's seed_directions "
    "(research_line_summary.seed_directions, numbers of the candidate directions in nc-hotspots "
    "section 3.2). The method and pipeline may follow a template; the claim itself must be new. "
    "Down-weight crowded subjects: a template marked very high crowding, a subject with three or "
    "more NC papers in the last 18 months, and the crowded topics of nc-hotspots section 3.3 "
    "(global flash drought and vegetation; urban heat island and greening cooling) - propose one "
    "only with an angle the crowded papers lack, and say so in the card."
)

SCOUT_INSTRUCTION = (
    " NC aim (target_stage nc_aim, user decision 2026-11-25): every topic aims at Nature "
    "Communications and the results will decide the journal (NC, else CAS Zone 1, 2, 3-4). "
    "Scout broadly and cheaply across diverse fields: read recent literature and the line's data "
    "catalogue (research_line_summary.data_catalog), and return distinct cards spread across "
    "different disciplines and mechanisms (never cluster multiple cards in one subfield or repeat "
    "a seed direction/domain that recently failed in ledger_snapshot). Prefer substantive "
    "scientific questions: a new natural/biological/physical/socio-technical phenomenon or "
    "mechanism, a decision-relevant global quantity with a clear first/largest/causal claim, or "
    "settling a cross-field debate with direct observational outcomes. Steer away from "
    "audit/meta-science/reporting-rule framings (auditing one catalogue, archive lag, reporting "
    "checklist, station-count coverage, monitoring calendar, or literature body: these calibrate "
    "to Zone 1 comparators, not NC) unless the audit overturns a widely used result, method or "
    "benchmark across an entire field (multiple independent datasets and all major model classes, "
    "as in A1/A2). Verify that the data directly measures the claimed real-world outcome (not an "
    "unvalidated proxy), has enough events/time steps, and is not trivially explained by an "
    "obvious algebraic or statistical null. Each card states: in `nc_case.claim`, the concrete "
    "declarative headline finding it would publish in NC if the kill test passes; in "
    "`audience.who`, why NC readers across fields (beyond one narrow subfield) would care; in "
    "`closest_prior_work`, the closest prior Nature Communications, Nature or Science papers "
    "(plus 18-month preprints) and what is genuinely new beyond them; "
    + _SCOUT_TAIL
)

ADMISSION_NC_INSTRUCTION = (
    " NC aim (entries stamped target_stage nc_aim, user decision 2026-11-25): judge each card "
    "against the Nature Communications bar instead of the routine standard. You did not take "
    "part in choosing the topic: run your own novelty search over the last {years} years "
    "covering at least {papers} papers and return `admission.novelty_search` {window_years, "
    "papers_screened, queries[], closest[{citation, year, doi_or_url, what_it_shows, "
    "our_increment}] (the {closest} closest), increment (one sentence)}. Do not score the NC "
    "thresholds again: the prescreen (card_check.prescreen) did, with the calibration set and "
    "the kill test. Check that its result stands - the thresholds it counted, its "
    "calibration_match and the kill-test signal - and reject, quoting which one, when it does "
    "not. Admit when the claim, the challenged view, the benchmark and the data plan "
    "(data_volume, download window, ailab storage) stand; the first milestone must be the "
    "decisive analysis. At the scout stage an nc_aim card's fee_check, license_check and "
    "audience citations are warnings (card_check.warnings) and a needs_registration data source "
    "is a note (card_check.nc_screen.data_catalog): complete them as admission conditions "
    "(licences and the owner's registration before_decisive_analysis, fees and audience "
    "before_submission), not as reasons to reject."
)

GRADE_INSTRUCTION = (
    " NC-aim acceptance grading (user decision 2026-11-25: the data decide the journal; this "
    "is a hard criterion). Read the calibration set (read_resources venue-calibration: accepted "
    "NC papers with their hooks, and same-subject papers of lower-tier journals) and first "
    "answer which tier this manuscript looks like (retarget.calibration_match: nc, zone_1, "
    "zone_2 or zones_3_4, with retarget.calibration_neighbours: the ids of the 2-3 closest "
    "calibration papers). Then score the NC thresholds on the actual evidence in "
    "retarget.nc_scorecard {" + ", ".join(THRESHOLDS) + ": {met, evidence}} and set "
    "retarget.confidence (high|medium|low). Set retarget.achieved_band to nc only when at "
    "least the required number of thresholds hold on the evidence, the calibration match is "
    "nc and your confidence is high; otherwise grade down step by step: zone_1, zone_2, "
    "zones_3_4. achieved_band is never higher than calibration_match. Choose an exact "
    "journal of that band from verified_alternatives (grading."
    "nc_journals for nc, the CAS zone for the others) and explain the scope fit in "
    "retarget.why_fits. The manuscript keeps top-journal writing and figure standards in every "
    "band; a lower band only changes the journal and its length and format. If no verified "
    "journal fits the supported band, use freeze with no_eligible_venue and a concrete reopen "
    "condition."
)


def admission_min_band(settings, line: Any = None) -> str:
    """Effective admission floor of ``line`` (``[program.lines.<id>]`` if set, else global)."""

    program = getattr(settings, "program", None)
    if program is not None and hasattr(program, "admission_min_band"):
        return program.admission_min_band(line)
    if program is not None and hasattr(program, "line"):
        override = program.line(line).admission_min_band
        if override is not None:
            return override
    return settings.program.funnel.admission_min_band


def scout_instruction(settings, line: str | None = None) -> str:
    """Graded-funnel scout guidance adapted to the line's effective admission floor."""

    floor = admission_min_band(settings, line) if settings is not None else "nc"
    if floor == "nc":
        return SCOUT_INSTRUCTION
    audit_note = (
        "Steer away from narrow reporting-rule/metadata-only audits that calibrate below zone_1 "
        "unless the audit overturns a widely used result, method or benchmark across an entire "
        "field (multiple independent datasets and all major model classes, as in A1/A2). "
        if floor == "zone_1" else
        f"Avoid trivial metadata-only or single-parameter checks that calibrate below {floor}; "
        f"systematic empirical studies, multi-system or rule-change analyses, and cross-dataset "
        f"evaluation audits that calibrate at {floor} or better and meet the required thresholds "
        "are welcome. "
    )
    return (
        f" NC aim (target_stage nc_aim, line admission floor {floor}; standing rule: topics aim "
        "high and the results will decide the journal — NC, else CAS Zone 1, 2, 3-4). "
        "Scout broadly and cheaply across diverse fields or within this line's scope: read recent "
        "literature and the line's data catalogue (research_line_summary.data_catalog), and "
        "return distinct cards (never cluster multiple cards on one narrow angle or repeat a "
        "seed direction/domain that recently failed in ledger_snapshot). Prefer substantive "
        "scientific questions: a new natural/biological/physical/socio-technical phenomenon or "
        "mechanism, a decision-relevant quantity or systematic multi-system result with a clear "
        "claim, or settling a debate with direct observational outcomes. "
        + audit_note
        + "Verify that the data directly measures the claimed real-world outcome (not an "
        "unvalidated proxy), has enough events/time steps, and is not trivially explained by an "
        "obvious algebraic or statistical null. Each card states: in `nc_case.claim`, the concrete "
        "declarative headline finding the paper would publish if the kill test passes (aim high; "
        f"cards calibrating at {floor} or better pass prescreen); in `audience.who`, why readers "
        f"across fields or the target CAS {floor}+ journal community would care; in "
        "`closest_prior_work`, the closest prior Nature Communications, Nature, Science and "
        f"leading domain ({floor}+) papers (plus 18-month preprints) and what is genuinely new "
        "beyond them; "
        + _SCOUT_TAIL
    )


def scout_floor_instruction(settings, line: str | None = None) -> str:
    """The admission floor a scout's cards face (line override if set, else global funnel)."""

    floor = admission_min_band(settings, line)
    if floor == "nc":
        return (" Admission floor: nc (user 2026-11-26, \"接下来的出题希望选题至少是够nc档次的\"). "
                "The prescreen and the admission gate reject a card whose calibration match or "
                "expected band is below Nature Communications, so propose only questions that an "
                "accepted NC paper of the calibration set would resemble; after the research the "
                "evidence still grades the journal (NC, else Zone 1, 2, 3-4).")
    return (f" Admission floor: {floor}. The prescreen and the admission gate reject a card whose "
            f"calibration match or expected band is below {floor}; topics still aim high and the "
            "evidence grades the journal after the research (NC, else Zone 1, 2, 3-4).")


def admission_instruction(settings, line: str | None = None) -> str:
    funnel = settings.program.funnel
    floor = admission_min_band(settings, line)
    text = (ADMISSION_NC_INSTRUCTION
            .replace("{years}", str(funnel.novelty_window_years))
            .replace("{papers}", str(funnel.novelty_min_papers))
            .replace("{closest}", str(funnel.novelty_closest)))
    return (text + f" Effective admission floor: {floor} (topics aim high and the data grade the "
            f"journal after research; prescreen calibration_match and expected_band must be at "
            f"least {floor}).")


def band_rank(band: Any) -> int:
    return BANDS.index(band) if band in BANDS else len(BANDS)


def calibrated_band(band: Any, match: Any) -> str:
    """The worse of a claimed band and the calibration match (the grading ruler).

    The same rule as :func:`nc_grade`: a topic is never placed above the tier its closest
    calibration papers belong to. An unknown band or match counts as the lowest band.
    """

    return BANDS[min(max(band_rank(band), band_rank(match)), len(BANDS) - 1)]



def lower_band(band: str) -> str:
    rank = band_rank(band)
    return BANDS[min(rank + 1, len(BANDS) - 1)] if rank < len(BANDS) else BANDS[-1]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def met_thresholds(block: Any) -> list[str]:
    """Threshold ids marked ``met: true`` with evidence in a ``thresholds`` block."""

    if not isinstance(block, Mapping):
        return []
    return [key for key in THRESHOLDS
            if isinstance(block.get(key), Mapping) and block[key].get("met") is True
            and _text(block[key].get("evidence"))]


# --------------------------------------------------------------------------- L1: contract


def card_contract_errors(card: Mapping[str, Any]) -> list[str]:
    """Fields an nc_aim card needs (format errors: the card gets one automatic repair)."""

    from .contracts import data_source_access_errors

    errors: list[str] = []
    case = card.get("nc_case")
    if not isinstance(case, Mapping):
        errors.append("nc_aim requires nc_case {claim, alternative_claim, challenges, benchmark, "
                      "thresholds, exemplars}")
    else:
        for key in ("claim", "alternative_claim", "challenges", "benchmark"):
            if not _text(case.get(key)):
                errors.append(f"nc_case.{key} is missing")
        thresholds = case.get("thresholds")
        if not isinstance(thresholds, Mapping) or not all(
            isinstance(thresholds.get(key), Mapping)
            and isinstance(thresholds[key].get("met"), bool) for key in THRESHOLDS
        ):
            errors.append("nc_case.thresholds needs " + ", ".join(THRESHOLDS)
                          + " each as {met: bool, evidence}")
    volume = card.get("data_volume")
    if not isinstance(volume, Mapping) or _number(volume.get("total_gb")) is None:
        errors.append("nc_aim requires data_volume {total_gb, largest_file_gb, proxy_expected, "
                      "offpeak_days, ailab_storage_gb}")
    kill = card.get("kill_test")
    if not isinstance(kill, Mapping) or not all(
        _text(kill.get(key)) for key in ("signal", "null_model", "ceiling", "pass_rule")
    ):
        errors.append("nc_aim requires kill_test {signal, null_model, ceiling, pass_rule, "
                      "core_hours}")
    milestones = card.get("milestones")
    if not isinstance(milestones, list) or not milestones or not isinstance(
        milestones[0], Mapping
    ) or milestones[0].get("kind") != "decisive":
        errors.append("nc_aim requires milestones whose first item has kind decisive")
    for index, source in enumerate(card.get("data_sources") or []):
        if isinstance(source, Mapping) and source.get("decisive") is not False:
            # Skip duplicate structure errors already reported by validate_topic_card when
            # access is present; require it here when omitted on an nc_aim card.
            if source.get("access") is None:
                errors.extend(
                    data_source_access_errors(source, f"data_sources[{index}]", required=True)
                )
    return errors


# --------------------------------------------------------------------------- L1: screens


_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""a an the of in on for to and or with by from at as is are be we our this
that which whether how what does do can than into across over under between using use via
its their per vs""".split())


def _tokens(*parts: Any) -> frozenset[str]:
    words: set[str] = set()
    for part in parts:
        words.update(w for w in _WORD.findall(str(part or "").lower())
                     if w not in _STOP and len(w) > 2)
    return frozenset(words)


def card_tokens(card: Mapping[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    """``(question words, claim words)`` of a card (content words only)."""

    case = card.get("nc_case") if isinstance(card.get("nc_case"), Mapping) else {}
    return _tokens(card.get("question")), _tokens(case.get("claim"))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def similarity(left: tuple[frozenset[str], frozenset[str]],
               right: tuple[frozenset[str], frozenset[str]]) -> float:
    """The closer of question-to-question and claim-to-claim word overlap (Jaccard)."""

    return max(_jaccard(left[0], right[0]), _jaccard(left[1], right[1]))


def _topic_card(topic: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(topic.get("card_path") or ""))
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _reason(topic: Mapping[str, Any]) -> str:
    for entry in reversed(list(topic.get("history") or [])):
        if entry.get("to") in {"rejected", "frozen"}:
            return str(entry.get("reason") or "")
    return ""


# Rejections that say nothing about the direction (format, bookkeeping, infrastructure).
_NEUTRAL_REJECTIONS = frozenset({
    "card_invalid", "duplicate_fingerprint", "admission_undecided", "card_precheck_failed",
    "card_capability_missing", "card_pilot_unavailable", PRESCREEN_UNAVAILABLE,
    "card_target_repeat_failure",
})


def near_duplicates(card: Mapping[str, Any], document: Mapping[str, Any],
                    settings) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(blocking, warnings)``: ledger topics whose question+claim is close to this card's.

    Blocking: similarity >= ``dedup_reject_similarity`` to a topic in progress (proposed ...
    ready) or one rejected or frozen for its substance (a failed direction). Warnings:
    similarity >= ``dedup_warn_similarity`` to any topic.
    """

    funnel = settings.program.funnel
    mine = card_tokens(card)
    line = str(card.get("research_line") or "")
    reopens = {str(card.get("reopens") or ""), str(card.get("revises") or ""),
               str(card.get("repair_of") or "")}
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping) or str(topic.get("topic_id")) in reopens:
            continue
        if line and topic.get("research_line") not in {line, None}:
            continue
        stored = _topic_card(topic) if topic.get("card_path") else {}
        other = card_tokens(stored) if stored else (_tokens(topic.get("question")), frozenset())
        score = similarity(mine, other)
        if score < funnel.dedup_warn_similarity:
            continue
        status = str(topic.get("status") or "")
        reason = _reason(topic)
        item = {"topic_id": topic.get("topic_id"), "status": status, "reason": reason or None,
                "similarity": round(score, 3)}
        failed = status in {"rejected", "frozen"} and reason not in _NEUTRAL_REJECTIONS
        live = status in {"proposed", "admitted", "active", "in_review", "ready_queue",
                          "submitted"}
        if score >= funnel.dedup_reject_similarity and (live or failed):
            blocking.append(item)
        else:
            warnings.append(item)
    blocking.sort(key=lambda item: -item["similarity"])
    warnings.sort(key=lambda item: -item["similarity"])
    return blocking[:5], warnings[:5]


def _catalog(line_entry: Mapping[str, Any]) -> dict[str, dict[str, Any]] | None:
    environment = line_entry.get("environment") if isinstance(line_entry, Mapping) else None
    path = environment.get("data_catalog") if isinstance(environment, Mapping) else None
    if not _text(path):
        return None
    from .data_catalog import DataCatalogError, load_catalog

    try:
        document = load_catalog(Path(str(path)))
    except (OSError, DataCatalogError):
        return None
    return {str(item.get("id")): dict(item) for item in document.get("sources") or []
            if isinstance(item, Mapping) and item.get("id")}


def source_access_problems(card: Mapping[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """``(rejecting problems, needs_registration notes)`` from each source's ``access`` field."""

    problems: list[str] = []
    notes: list[dict[str, Any]] = []
    for index, source in enumerate(card.get("data_sources") or []):
        if not isinstance(source, Mapping):
            continue
        decisive = source.get("decisive") is not False
        key = _text(source.get("catalog_id"))
        label = key or _text(source.get("name")) or _text(source.get("url")) or f"#{index}"
        access = source.get("access") if isinstance(source.get("access"), Mapping) else {}
        method = _text(access.get("method"))
        present = access.get("required_fields_present")
        missing = [
            _text(item) for item in (access.get("missing_fields") or [])
            if _text(item)
        ] if isinstance(access.get("missing_fields"), list) else []
        reg_text = (
            _text(access.get("registration"))
            or (_text(source.get("needs_registration"))
                if isinstance(source.get("needs_registration"), str) else "")
            or _text(source.get("registration_note"))
        )
        if decisive and method == "restricted":
            problems.append(
                f"decisive data source {label} has restricted access (not freely obtainable)"
            )
        if decisive and (present is False or missing):
            detail = ", ".join(missing) if missing else "unspecified required field(s)"
            problems.append(
                f"decisive data source {label} is missing required field(s): {detail}"
            )
        if method == "form_or_registration" or bool(source.get("needs_registration")):
            notes.append({
                "source": label,
                "status": "needs_registration",
                "registration": reg_text or None,
                "note": "free, needs the owner's registration before the full-scale analysis",
            })
    return problems, notes


def data_problems(card: Mapping[str, Any], line_entry: Mapping[str, Any],
                  settings) -> tuple[list[str], list[dict[str, Any]]]:
    """``(rejecting problems, catalogue notes)`` of a card's data sources."""

    access_problems, access_notes = source_access_problems(card)
    catalog = _catalog(line_entry)
    if catalog is None:
        return access_problems, access_notes
    reg_by_source = {item["source"]: item for item in access_notes}
    problems: list[str] = list(access_problems)
    notes: list[dict[str, Any]] = []
    for index, source in enumerate(card.get("data_sources") or []):
        if not isinstance(source, Mapping):
            continue
        key = _text(source.get("catalog_id"))
        entry = catalog.get(key) if key else None
        label = key or _text(source.get("name")) or _text(source.get("url")) or f"#{index}"
        reg_note = reg_by_source.pop(label, None)
        if entry is None:
            if source.get("catalog_candidate") is True:
                if reg_note is not None:
                    notes.append({
                        **reg_note,
                        "note": reg_note["note"]
                        + "; catalog_candidate (verified by the scout's access receipt; "
                        "add it to the data catalogue)",
                    })
                else:
                    notes.append({"source": label, "note": "catalog_candidate (verified by the "
                                  "scout's access receipt; add it to the data catalogue)"})
            elif settings.program.funnel.uncatalogued_data == "reject":
                problems.append(f"data source {label} is not in the line's data catalogue "
                                "(give its catalog_id, or mark a newly verified source "
                                "catalog_candidate)")
                if reg_note is not None:
                    notes.append(reg_note)
            else:
                notes.append(reg_note if reg_note is not None
                             else {"source": label, "note": "not in the data catalogue"})
            continue
        status = str(entry.get("status") or "")
        if status == "blocked":
            problems.append(f"data source {key} is blocked in the data catalogue ("
                            + (_text(entry.get("blocked_reason")) or "not obtainable now") + ")")
        elif status == "needs_registration" or reg_note is not None:
            # User rule (free data only): a free source behind a registration is listed for the
            # owner to register, not excluded (NC calibration 2026-11-26). The card goes on; the
            # admission gate makes the registration a before_decisive_analysis condition.
            registration = (
                _text(entry.get("registration"))
                or (reg_note.get("registration") if reg_note is not None else None)
                or None
            )
            notes.append({"source": key, "status": "needs_registration",
                          "registration": registration,
                          "note": "free, needs the owner's registration before the "
                                  "full-scale analysis"})
        else:
            notes.append({"source": key, "status": status})
    return problems, notes


def capacity_problems(card: Mapping[str, Any], settings) -> list[str]:
    funnel = settings.program.funnel
    volume = card.get("data_volume") if isinstance(card.get("data_volume"), Mapping) else {}
    problems = []
    total = _number(volume.get("total_gb"))
    storage = _number(volume.get("ailab_storage_gb"))
    if total is not None and total > funnel.max_topic_data_gb:
        problems.append(f"data_volume.total_gb {total:g} exceeds the topic limit "
                        f"{funnel.max_topic_data_gb:g} GB")
    if storage is not None and storage > funnel.max_topic_storage_gb:
        problems.append(f"data_volume.ailab_storage_gb {storage:g} exceeds the topic limit "
                        f"{funnel.max_topic_storage_gb:g} GB")
    return problems


def screen_card(settings, card: Mapping[str, Any], line_entry: Mapping[str, Any],
                ledger_document: Mapping[str, Any], stage: str
                ) -> tuple[str | None, list[str], dict[str, Any]]:
    """L1 of an nc_aim card: ``(rejection reason, errors, card_check additions)``."""

    from . import target_stage

    if stage != target_stage.NC_AIM:
        return None, [], {}
    funnel = settings.program.funnel
    floor = admission_min_band(settings, card.get("research_line"))
    case = card.get("nc_case") if isinstance(card.get("nc_case"), Mapping) else {}
    claimed = met_thresholds(case.get("thresholds"))
    extra: dict[str, Any] = {"target_stage": stage,
                             "nc_screen": {"claimed_thresholds": claimed,
                                           "admission_min_band": floor}}
    problems, notes = data_problems(card, line_entry, settings)
    if notes:
        extra["nc_screen"]["data_catalog"] = notes
    if problems:
        return DATA_REJECTION, [f"{DATA_REJECTION}: {item}" for item in problems], extra
    capacity = capacity_problems(card, settings)
    if capacity:
        return CAPACITY_REJECTION, [f"{CAPACITY_REJECTION}: {item}" for item in capacity], extra
    blocking, warnings = near_duplicates(card, ledger_document, settings)
    if warnings:
        extra["nc_screen"]["similar_topics"] = warnings
    if blocking:
        return DUPLICATE_REJECTION, [
            f"{DUPLICATE_REJECTION}: close to {item['topic_id']} ({item['status']}"
            + (f", {item['reason']}" if item.get("reason") else "")
            + f"; similarity {item['similarity']})" for item in blocking], extra
    if funnel.prescreen:
        extra["prescreen"] = {"status": "pending", "attempts": 0, "registered_at": utc_now()}
    return None, [], extra


# --------------------------------------------------------------------------- L2+L3: prescreen


def prescreen_held(topic: Mapping[str, Any]) -> bool:
    check = topic.get("card_check") if isinstance(topic.get("card_check"), Mapping) else {}
    state = check.get("prescreen") if isinstance(check.get("prescreen"), Mapping) else {}
    return str(state.get("status") or "") in PRESCREEN_WAITING


def evaluate_prescreen(result: Any, settings, digests: set[str], *,
                       line: str | None = None) -> dict[str, Any]:
    """Deterministic verdict of one ``topic_prescreen`` result.

    ``{"status": pass|fail|invalid, "reason", "expected_band", "met", ...}``.
    """

    from .contracts import DATA_ACCESS_METHODS

    funnel = settings.program.funnel
    floor = admission_min_band(settings, line)
    if not isinstance(result, Mapping):
        return {"status": "invalid", "errors": ["topic_prescreen is missing"]}
    errors: list[str] = []
    novelty = result.get("novelty_quick") if isinstance(result.get("novelty_quick"),
                                                        Mapping) else {}
    verdict = _text(novelty.get("verdict"))
    if verdict not in NOVELTY_VERDICTS:
        errors.append("novelty_quick.verdict must be clear, incremental or scooped")
    thresholds = result.get("thresholds")
    if not isinstance(thresholds, Mapping) or not all(
        isinstance(thresholds.get(key), Mapping)
        and isinstance(thresholds[key].get("met"), bool) for key in THRESHOLDS
    ):
        errors.append("thresholds needs " + ", ".join(THRESHOLDS) + " as {met, evidence}")
    match = _text(result.get("calibration_match"))
    if match not in BANDS:
        errors.append("calibration_match must be nc, zone_1, zone_2 or zones_3_4 (the tier of "
                      "the closest papers of the calibration set)")
    access_check = result.get("data_access_check")
    access_issues: list[str] = []
    prescreen_regs: list[dict[str, Any]] = []
    checked_access: list[dict[str, Any]] = []
    if access_check is not None:
        if not isinstance(access_check, list):
            errors.append("data_access_check must be a list of per-dataset objects")
        else:
            for index, item in enumerate(access_check):
                if not isinstance(item, Mapping):
                    errors.append(f"data_access_check[{index}] must be an object")
                    continue
                src = _text(item.get("source")) or _text(item.get("name")) or f"#{index}"
                method = _text(item.get("method"))
                if method not in DATA_ACCESS_METHODS:
                    errors.append(
                        f"data_access_check[{index}].method must be one of "
                        f"{', '.join(DATA_ACCESS_METHODS)}"
                    )
                    continue
                present = item.get("required_fields_present")
                if not isinstance(present, bool):
                    errors.append(
                        f"data_access_check[{index}].required_fields_present must be a boolean"
                    )
                    continue
                missing = [
                    _text(f) for f in (item.get("missing_fields") or []) if _text(f)
                ] if isinstance(item.get("missing_fields"), list) else []
                decisive = item.get("decisive") is not False
                reg = _text(item.get("registration")) or None
                checked_access.append({
                    "source": src, "method": method, "required_fields_present": present,
                    **({"missing_fields": missing} if missing else {}),
                    **({"registration": reg} if reg else {}),
                })
                if decisive and method == "restricted":
                    access_issues.append(f"decisive data source {src} has restricted access")
                if decisive and (present is False or missing):
                    detail = ", ".join(missing) if missing else "unspecified required field(s)"
                    access_issues.append(
                        f"decisive data source {src} is missing required field(s): {detail}"
                    )
                if method == "form_or_registration":
                    prescreen_regs.append({
                        "source": src,
                        "status": "needs_registration",
                        "registration": reg,
                        "note": "free, needs the owner's registration before the "
                                "full-scale analysis",
                    })
    if errors:
        return {"status": "invalid", "errors": errors}
    met = met_thresholds(thresholds)
    base = {"met": met, "novelty": verdict, "calibration_match": match,
            "admission_min_band": floor,
            "calibration_neighbours": [str(item) for item in
                                       list(result.get("calibration_neighbours") or [])[:5]],
            "closest": list(novelty.get("closest") or [])[:5]}
    if checked_access:
        base["data_access_check"] = checked_access
    if prescreen_regs:
        base["needs_registration"] = prescreen_regs
    if _text(result.get("summary")):
        # Fed back to later scouts of the line (program_flow._ledger_snapshot).
        base["summary"] = _text(result.get("summary"))[:1500]
    if access_issues:
        return {**base, "status": "fail", "reason": DATA_REJECTION,
                "why": "; ".join(access_issues)}
    if verdict == "scooped" or len(met) < funnel.min_nc_thresholds:
        return {**base, "status": "fail", "reason": PRESCREEN_REJECTION,
                "why": ("prior work already reports the claim" if verdict == "scooped" else
                        f"{len(met)} NC threshold(s) hold on an independent reading; "
                        f"{funnel.min_nc_thresholds} required")}
    if band_rank(match) > band_rank(floor):
        # Phase A stop on the calibration match (the brief and the skill tell the prescreener
        # not to run the kill test then). Judged here, not left invalid: NC trial 2026-11-26,
        # such a stop was read as "kill_test must run" twice and ended as prescreen_unavailable.
        return {**base, "status": "fail", "reason": BAND_REJECTION, "expected_band": match,
                "why": f"the calibration set places it at {match}, below the admission floor "
                       f"{floor}"
                       + (f" (closest: {', '.join(base['calibration_neighbours'])})"
                          if base["calibration_neighbours"] else "")}
    kill = result.get("kill_test") if isinstance(result.get("kill_test"), Mapping) else {}
    signal = kill.get("signal") if isinstance(kill.get("signal"), Mapping) else {}
    artifact = kill.get("result_artifact") if isinstance(kill.get("result_artifact"),
                                                         Mapping) else {}
    if kill.get("ran") is not True or not isinstance(signal.get("present"), bool):
        return {**base, "status": "invalid",
                "errors": ["kill_test must run (ran: true) and report signal.present"]}
    if _text(artifact.get("sha256")) not in digests:
        return {**base, "status": "invalid",
                "errors": ["kill_test.result_artifact must be a hash-bound artifact of the result"]}
    used = _number(kill.get("used_core_hours"))
    null = kill.get("null_baseline") if isinstance(kill.get("null_baseline"), Mapping) else {}
    # A signal fixed by a known formula or algebraic relation (e.g. "98.5% is predicted by
    # RR") is fully explained by the null model (NC trial 2026-11-25, item 2).
    known = null.get("determined_by_known_relation") is True
    summary = {
        "signal": {key: signal.get(key) for key in ("present", "estimate", "interval", "note")
                   if signal.get(key) is not None},
        "null_explained": 1.0 if known else _number(null.get("explained_fraction")),
        **({"known_relation": _text(null.get("relation")) or True} if known else {}),
        "claim_reachable": (kill.get("ceiling") or {}).get("claim_reachable")
        if isinstance(kill.get("ceiling"), Mapping) else None,
        "used_core_hours": used, "result_artifact": dict(artifact),
    }
    base["kill_test"] = summary
    if signal["present"] is False:
        return {**base, "status": "fail", "reason": KILL_TEST_REJECTION,
                "why": "the kill test found no key signal"}
    claimed = _text(result.get("expected_band"))
    claimed = claimed if claimed in BANDS else "nc"
    # The calibration match caps the band first (the grading ruler), then the kill test's
    # findings take one more step down from whatever band that leaves.
    band = calibrated_band(claimed, match)
    downgrades = []
    if band != claimed:
        downgrades.append(f"the calibration set places it at {match}"
                          + (f" (closest: {', '.join(base['calibration_neighbours'])})"
                             if base["calibration_neighbours"] else ""))
    kill_downgrades = []
    if summary["null_explained"] is not None and summary["null_explained"] >= \
            funnel.null_explained_max:
        kill_downgrades.append(
            "the signal is fixed by a known relation (null model explains all of it)" if known
            else f"a null model explains {summary['null_explained']:.2f} of the effect")
    if summary["claim_reachable"] is False:
        kill_downgrades.append("the theoretical ceiling is below the claimed effect")
    if kill_downgrades:
        band = lower_band(band)
    downgrades.extend(kill_downgrades)
    base.update(expected_band=band, claimed_band=claimed, downgrades=downgrades)
    if band_rank(band) > band_rank(floor):
        return {**base, "status": "fail", "reason": BAND_REJECTION,
                "why": f"expected band {band} is below the admission floor "
                       f"{floor}"
                       + (f" ({'; '.join(downgrades)})" if downgrades else "")}
    return {**base, "status": "pass"}


def _prescreen_task_id(topic_id: str, attempt: int) -> str:
    digest = hashlib.sha256(f"{topic_id}\0{attempt}".encode()).hexdigest()
    return f"topic-prescreen:{digest[:32]}"


def preferred_prescreen_runner(settings, exclude: str | None) -> str | None:
    """First ``[program.funnel].prescreen_runners`` entry outside the proposer's family."""

    for name in settings.program.funnel.prescreen_runners:
        spec = settings.runners.get(name)
        if spec is not None and spec.family != exclude:
            return name
    return None


def _enqueue_prescreen(db, paths, settings, *, topic: Mapping[str, Any], attempt: int
                       ) -> str | None:
    from . import program_flow as flow
    from .config import dispatch_runner
    from .resources import ResourceVector, default_task_resources

    project = flow._project_of(paths, topic)
    if project is None:
        return None
    campaign = flow._active_scout_campaign(db, project)
    if campaign is None:
        return None
    topic_id = str(topic["topic_id"])
    task_id = _prescreen_task_id(topic_id, attempt)
    if db.task(task_id) is not None:
        return task_id
    card = _topic_card(topic)
    funnel = settings.program.funnel
    line = project.research_line or topic.get("research_line")
    floor = admission_min_band(settings, line)
    ledger = flow.open_topic_ledger(paths, settings.program)
    packet_path = (flow._control_root(paths) / flow._token(project.project_id)
                   / "prescreen-packets" / f"{flow._token(topic_id)}-{attempt}.json")
    provider = str(topic.get("proposer_provider") or flow.HUMAN_PROVIDER)
    exclude = None if provider == flow.HUMAN_PROVIDER else provider
    preferred = preferred_prescreen_runner(settings, exclude)
    packet = flow._signed({
        "schema_version": PRESCREEN_PACKET_SCHEMA,
        **({"preferred_runner": preferred} if preferred else {}),
        "project_id": project.project_id,
        "domain": project.domain,
        "topic_id": topic_id,
        "card": card,
        "card_check": dict(topic.get("card_check") or {}),
        **({"research_line": line,
            "research_line_summary": flow.line_summary(
                flow.research_lines_document(paths, settings), line)} if line else {}),
        "funnel": {"min_nc_thresholds": funnel.min_nc_thresholds,
                   "thresholds": THRESHOLD_TEXT,
                   "kill_test_core_hours": funnel.kill_test_core_hours,
                   "kill_test_cpus": funnel.kill_test_cpus,
                   "kill_test_max_download_mb": funnel.kill_test_max_download_mb,
                   "null_explained_max": funnel.null_explained_max,
                   "admission_min_band": floor,
                   "calibration": CALIBRATION_PATH,
                   "calibration_rule": "expected band = the worse of your expected_band and "
                                       "calibration_match, as in the acceptance grade"},
        "hooks": [{"id": key, "hook": text} for key, text in HOOKS],
        "read_resources": [*flow.program_read_resources(paths, settings, ledger),
                           *[item for item in [calibration_resource(paths)] if item]],
        "created_at": utc_now(),
    })
    flow.atomic_write_json(packet_path, packet)
    base = default_task_resources(settings)
    resources = ResourceVector(max(base.cpu_threads, funnel.kill_test_cpus),
                               max(base.memory_mib, 4096), base.scratch_mib)
    db.enqueue_task(
        task_id=task_id,
        campaign_id=str(campaign["campaign_id"]),
        domain=project.domain,
        task_type=PRESCREEN_TASK_TYPE,
        objective=(
            f"Prescreen one NC-aimed topic card of the {project.domain} research program "
            "(funnel levels 2 and 3; follow the 'Prescreen' section of the skill). The packet at "
            "the input path has the card. You did not write it. " + CALIBRATION_TEXT + " A "
            f"match below {floor} rejects the card. Phase A (cheap): a quick "
            "novelty search of the last three years, preprints included (Research Square, arXiv, "
            "bioRxiv, medRxiv, SSRN, EarthArXiv; list the 3-5 closest papers), an independent "
            "data-access check of every decisive dataset in `card.data_sources` (how it is "
            "obtained: `direct`, `form_or_registration`, or `restricted`, and whether every "
            "required decisive field actually exists in the public release — e.g. Living Planet "
            "Database 2026 requires a portal form -> `form_or_registration`, while Challenge-2021 "
            "Georgia lacks a patient-linkage map -> `required_fields_present: false` with "
            "`missing_fields: [\"patient_linkage_map\"]`), and your own "
            "scoring of the five NC thresholds on the design's potential as knowable at "
            "admission; if any decisive dataset is `restricted` or missing a required field, "
            "fewer than "
            f"{funnel.min_nc_thresholds} hold, the same claim is already reported (adjacent work "
            "with a different claim is closest prior work, not a scoop) or the calibration "
            "match is below the floor, stop and return without running anything. Judge crowding "
            "with read_resources nc-hotspots (section 2 crowding, section 3.3 crowded topics: "
            "global flash drought and vegetation, urban heat island and greening cooling): a "
            "card on a crowded subject without a new angle is incremental, not clear. Phase B, only "
            "when phase A passes: the kill test of the "
            f"card within {funnel.kill_test_core_hours:g} core-hours on at most "
            f"{funnel.kill_test_cpus} CPU threads here (no ailab job), using data already on "
            "disk or catalogued small samples (files over "
            f"{funnel.kill_test_max_download_mb} MB are out of scope; any download goes "
            "through the download bridge): does the key signal exist, how much does the null "
            "model or simple baseline explain, what is the theoretical ceiling. A signal that a "
            "known formula or algebraic relation already determines (for example \"98.5% of it "
            "is predicted by RR\") is fully explained by the null model: set null_baseline."
            "determined_by_known_relation true and name the relation. Return the "
            "result field `topic_prescreen` {calibration_match, calibration_neighbours, "
            "data_access_check [{source, method direct|form_or_registration|restricted, "
            "required_fields_present, missing_fields[], registration}], "
            "novelty_quick {verdict clear|incremental|scooped, "
            "papers_screened, closest[{citation, year, overlap}]}, thresholds {"
            + ", ".join(THRESHOLDS) + ": {met, evidence}}, kill_test {ran, signal {present, "
            "estimate, interval, note}, null_baseline {explained_fraction, "
            "determined_by_known_relation, relation}, ceiling {value, "
            "claim_reachable}, used_core_hours, result_artifact {path, sha256}}, "
            "expected_band nc|zone_1|zone_2|zones_3_4, summary}; include top-level `claims: []` "
            "in the result bundle, and declare the kill-test result file as a hash-bound result "
            "artifact. Do not start the research itself."
        ),
        input_path=str(packet_path),
        skill_path=flow.ADMISSION_SKILL,
        runner=dispatch_runner(settings, PRESCREEN_TASK_TYPE, PRESCREEN_ROUTING_REASON,
                               "cheap"),
        routing_reason=PRESCREEN_ROUTING_REASON,
        agent_role="researcher",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0) + 1,
        max_attempts=settings.max_attempts,
        max_wall_seconds=min(funnel.prescreen_wall_seconds, settings.max_task_wall_seconds),
        exclude_provider=exclude,
        **resources.to_dict(),
    )
    db.record_event_once("topic", topic_id, "topic_prescreen_scheduled",
                         {"task_id": task_id, "attempt": attempt, "exclude_provider": exclude},
                         event_key=task_id)
    return task_id


def _result(db, task_id: str) -> tuple[Any, set[str]] | None:
    from .contracts import artifact_digests
    from .program_flow import _read_object, sha256_file

    task = db.task(task_id) or {}
    path = Path(str(task.get("result_path") or ""))
    expected = str(task.get("result_sha256") or "")
    if not path.is_file() or not expected or sha256_file(path) != expected:
        return None
    payload = _read_object(path)
    return payload.get("topic_prescreen"), set(artifact_digests(payload).values())


def advance_prescreens(db, paths, settings, report) -> list[dict[str, Any]]:
    """Schedule pending prescreens (cap ``prescreen_max_concurrent``) and judge finished ones.

    The cap counts scheduled prescreens that can run now; one queued behind a future
    ``not_before`` holds no slot. Unfinished ones are reported with their task status
    (``queued`` with its ``not_before``, ``leased``, ``running``, ...)."""

    from .program import open_topic_ledger, record_topic_note, reject_topic
    from .program_flow import TERMINAL_FAILED_STATUSES

    funnel = settings.program.funnel
    if not funnel.prescreen or settings.program.stops(SUPPLY_STAGE):
        return []
    ledger = open_topic_ledger(paths, settings.program)
    waiting = [topic for topic in ledger.read().get("topics") or []
               if isinstance(topic, Mapping) and topic.get("status") == "proposed"
               and prescreen_held(topic)
               and not settings.program.stops(SUPPLY_STAGE, topic.get("research_line"))]
    if not waiting:
        return []
    outcomes: list[dict[str, Any]] = []
    moment = _now_moment()

    def deferred(task: Mapping[str, Any]) -> bool:
        """Queued with a not_before still ahead (a backoff): it holds no slot of the cap,
        so a line held back does not keep other lines' cards from their prescreen."""

        not_before = _parse(task.get("not_before"))
        return task.get("status") == "queued" and not_before is not None \
            and not_before > moment

    running = 0
    for topic in waiting:
        held = topic["card_check"]["prescreen"]
        if held.get("status") == "scheduled" \
                and not deferred(db.task(str(held.get("task_id") or "")) or {}):
            running += 1

    def record(topic: Mapping[str, Any], state: dict[str, Any], event: str) -> None:
        check = {**dict(topic.get("card_check") or {}), "prescreen": state}
        regs = state.get("needs_registration")
        if isinstance(regs, list) and regs:
            nc_screen = dict(check.get("nc_screen") or {}) if isinstance(
                check.get("nc_screen"), Mapping
            ) else {}
            existing = list(nc_screen.get("data_catalog") or [])
            seen = {
                str(item.get("source") or "") for item in existing
                if isinstance(item, Mapping) and item.get("status") == "needs_registration"
            }
            for item in regs:
                if isinstance(item, Mapping) and str(item.get("source") or "") not in seen:
                    existing.append(dict(item))
                    seen.add(str(item.get("source") or ""))
            nc_screen["data_catalog"] = existing
            check["nc_screen"] = nc_screen
        record_topic_note(
            ledger, str(topic["topic_id"]), db=db, event_type="card_prescreen_recorded",
            reason=event, decided_by=PRESCREEN_DECIDER,
            detail={key: state.get(key) for key in (
                "status", "task_id", "attempts", "expected_band", "calibration_match",
                "admission_min_band", "met", "reason", "why", "errors")},
            updates={"card_check": check},
            key=f"card_prescreen:{topic['topic_id']}:{event}:{state.get('attempts')}")

    def fail(topic: Mapping[str, Any], state: dict[str, Any], reason: str) -> None:
        record(topic, state, reason)
        reject_topic(ledger, str(topic["topic_id"]), db=db, reason=reason,
                     decided_by=PRESCREEN_DECIDER)

    for topic in waiting:
        topic_id = str(topic["topic_id"])
        state = dict(topic["card_check"]["prescreen"])
        if state.get("status") == "scheduled":
            task = db.task(str(state.get("task_id") or "")) or {}
            status = str(task.get("status") or "missing")
            if status != "succeeded" and status not in TERMINAL_FAILED_STATUSES \
                    and status != "missing":
                outcomes.append({"topic_id": topic_id, "status": status,
                                 "task_id": state.get("task_id"),
                                 **({"not_before": task["not_before"]}
                                    if task.get("not_before") else {})})
                continue
            running -= 1
            found = _result(db, str(state.get("task_id"))) if status == "succeeded" else None
            verdict = evaluate_prescreen(
                found[0], settings, found[1], line=topic.get("research_line")
            ) if found else {
                "status": "invalid", "errors": [f"task {status}"]}
            state.update({key: value for key, value in verdict.items() if key != "status"},
                         finished_at=utc_now())
            if verdict["status"] in {"pass", "fail"}:
                state.pop("errors", None)
                state["status"] = verdict["status"]
                if verdict["status"] == "pass":
                    record(topic, state, "card_prescreen_pass")
                else:
                    fail(topic, state, str(verdict["reason"]))
                outcomes.append({"topic_id": topic_id, "status": state["status"],
                                 "expected_band": state.get("expected_band"),
                                 "reason": state.get("reason")})
                continue
            if int(state.get("attempts") or 0) >= funnel.prescreen_max_attempts:
                state["status"] = "unavailable"
                fail(topic, state, PRESCREEN_UNAVAILABLE)
                outcomes.append({"topic_id": topic_id, "status": "unavailable",
                                 "errors": state.get("errors")})
                continue
            state["status"] = "pending"
            record(topic, state, "card_prescreen_retry")
        if running >= funnel.prescreen_max_concurrent:
            outcomes.append({"topic_id": topic_id, "status": "pending",
                             "reason": "prescreen_max_concurrent"})
            continue
        attempt = int(state.get("attempts") or 0) + 1
        task_id = _enqueue_prescreen(db, paths, settings, topic=topic, attempt=attempt)
        if task_id is None:
            outcomes.append({"topic_id": topic_id, "status": "pending",
                             "reason": "no_active_scout_campaign"})
            continue
        state.update(status="scheduled", task_id=task_id, attempts=attempt,
                     scheduled_at=utc_now())
        record(topic, state, "card_prescreen_scheduled")
        if hasattr(report, "enqueued"):
            report.enqueued.append(task_id)
        running += 1
        outcomes.append({"topic_id": topic_id, "status": "scheduled", "task_id": task_id})
    return outcomes


# --------------------------------------------------------------------------- L4: admission


def admission_problems(admission: Mapping[str, Any], settings,
                       prescreen: Mapping[str, Any] | None = None, *,
                       line: str | None = None) -> list[str]:
    """Why an nc_aim admit does not meet the NC admission requirements ([] when it does).

    Pipeline slimming 2026-11-26: the gate no longer scores the NC thresholds again; it checks
    that the prescreen passed (thresholds, calibration match, kill test, line floor) and adds
    the independent novelty search.
    """

    funnel = settings.program.funnel
    gaps: list[str] = []
    if funnel.prescreen:
        if str((prescreen or {}).get("status") or "") != "pass":
            gaps.append("the prescreen (card_check.prescreen) has not passed")
        else:
            floor = admission_min_band(settings, line)
            match = _text((prescreen or {}).get("calibration_match"))
            band = _text((prescreen or {}).get("expected_band"))
            if match in BANDS and band_rank(match) > band_rank(floor):
                gaps.append(
                    f"prescreen calibration_match {match} is below the admission floor {floor}"
                )
            elif band in BANDS and band_rank(band) > band_rank(floor):
                gaps.append(
                    f"prescreen expected_band {band} is below the admission floor {floor}"
                )
    search = admission.get("novelty_search")
    if not isinstance(search, Mapping):
        gaps.append("admission.novelty_search is missing (independent novelty search)")
    else:
        screened = _number(search.get("papers_screened"))
        if screened is None or screened < funnel.novelty_min_papers:
            gaps.append(f"novelty_search.papers_screened must be at least "
                        f"{funnel.novelty_min_papers}")
        closest = [item for item in search.get("closest") or [] if isinstance(item, Mapping)
                   and _text(item.get("citation")) and _text(item.get("our_increment"))]
        if len(closest) < funnel.novelty_closest:
            gaps.append(f"novelty_search.closest must list the {funnel.novelty_closest} "
                        "closest papers with our_increment")
        if not _text(search.get("increment")):
            gaps.append("novelty_search.increment is missing")
    return gaps


def research_fields(record: Mapping[str, Any],
                    prescreen: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """NC-aim fields an admitted topic carries into its research state."""

    card = record.get("card") if isinstance(record.get("card"), Mapping) else {}
    admission = record.get("admission") if isinstance(record.get("admission"), Mapping) else {}
    prescreen = prescreen if isinstance(prescreen, Mapping) else {}
    fields = {key: card.get(key) for key in ("nc_case", "kill_test", "milestones",
                                             "data_volume") if card.get(key) is not None}
    if admission.get("novelty_search") is not None:
        fields["novelty_search"] = admission["novelty_search"]
    if prescreen.get("expected_band") in BANDS:
        fields["expected_band"] = prescreen["expected_band"]  # already capped by the match
        # The kill test is the first research stage's feasibility evidence (2026-11-26).
        fields["prescreen"] = {key: prescreen.get(key) for key in (
            "expected_band", "calibration_match", "met", "summary", "kill_test")
            if key in prescreen}
    return fields


# --------------------------------------------------------------------------- L6: grading


def calibration_resource(paths) -> dict[str, str] | None:
    path = Path(paths.data) / CALIBRATION_PATH
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"label": "venue-calibration", "path": str(path.resolve()), "sha256": digest}


def _admitted_band(topic: Mapping[str, Any]) -> Any:
    """The band a topic was admitted with: the prescreen's (topics admitted before
    2026-11-26 carry the admission gate's own ``nc_assessment``)."""

    admission = topic.get("admission") if isinstance(topic.get("admission"), Mapping) else {}
    if isinstance(admission.get("nc_assessment"), Mapping):
        return admission["nc_assessment"].get("expected_band")
    check = topic.get("card_check") if isinstance(topic.get("card_check"), Mapping) else {}
    prescreen = check.get("prescreen") if isinstance(check.get("prescreen"), Mapping) else {}
    return prescreen.get("expected_band")


def grading_packet(settings, topic: Mapping[str, Any]) -> dict[str, Any]:
    funnel = settings.program.funnel
    return {
        "stage": "nc_aim",
        "bands": list(BANDS),
        "nc_journals": list(funnel.nc_journals),
        "thresholds": THRESHOLD_TEXT,
        "expected_band_at_admission": _admitted_band(topic),
        "rules": (f"achieved_band nc needs >= {funnel.min_nc_thresholds} thresholds met in "
                  "nc_scorecard, calibration_match nc and confidence high, and a journal of "
                  "nc_journals; zone_1 / zone_2 / zones_3_4 need a verified journal of that CAS "
                  "zone; achieved_band is never higher than calibration_match"),
        "calibration": CALIBRATION_PATH,
    }


def nc_grade(decision: Mapping[str, Any], venues: list[dict], settings) -> dict | None:
    """The acceptance grade of an nc_aim topic, or None when the decision breaks the rule."""

    funnel = settings.program.funnel if settings is not None else None
    minimum = funnel.min_nc_thresholds if funnel else 2
    nc_journals = {name.casefold() for name in (funnel.nc_journals if funnel else
                                                ("Nature Communications",))}
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
        return None  # placed above its calibration match (the ruler of every funnel level)
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


# --------------------------------------------------------------------------- L0: scout gates


def _proposed_at(topic: Mapping[str, Any]) -> str:
    history = topic.get("history") or []
    return str(history[0].get("at") or "") if history else ""


def _decided_at(topic: Mapping[str, Any]) -> str:
    for entry in reversed(list(topic.get("history") or [])):
        if entry.get("to"):
            return str(entry.get("at") or "")
    return ""


def stall_streak(document: Mapping[str, Any], line: str) -> dict[str, Any]:
    """Trailing run of this line's decided cards that passed no funnel level to admission."""

    topics = sorted((t for t in document.get("topics") or [] if isinstance(t, Mapping)
                     and t.get("research_line") == line and t.get("status") != "proposed"),
                    key=_proposed_at)
    streak = 0
    reasons: Counter[str] = Counter()
    last = ""
    for topic in reversed(topics):
        states = {entry.get("to") for entry in topic.get("history") or []}
        if "admitted" in states or topic.get("status") != "rejected":
            break
        reason = _reason(topic)
        if reason in {"card_invalid", "duplicate_fingerprint"} and topic.get("card_repair"):
            continue  # its repair is the next card
        streak += 1
        reasons[reason] += 1
        last = max(last, _decided_at(topic))
    return {"streak": streak, "reasons": dict(reasons.most_common(3)), "last_at": last}


def _parse(value: Any) -> datetime | None:
    from . import budget as budget_control

    return budget_control.parse_time(value)


def _now_moment() -> datetime:
    from . import program_flow

    return program_flow._now_moment()


def weekly_scout_usd(db, settings, campaign_id: str, moment: datetime) -> float:
    from .usage import attempt_figures, normalized_attempts

    since = moment - timedelta(days=7)
    total = 0.0
    for attempt in normalized_attempts(db, campaign_ids=[campaign_id]):
        finished = _parse(attempt.get("finished_at"))
        if finished is None or finished < since:
            continue
        total += attempt_figures(attempt, settings).get("equivalent_usd") or 0.0
    return round(total, 3)


def scout_blocks(db, paths, settings, projects, document: Mapping[str, Any], *,
                 moment: datetime) -> dict[str, dict[str, Any]]:
    """``{rotation key: block}`` for lines the funnel holds: weekly budget, funnel stall."""

    from . import program_flow as flow
    from . import target_stage

    funnel = settings.program.funnel
    blocks: dict[str, dict[str, Any]] = {}
    for project in projects:
        line = project.research_line
        if not line or target_stage.stage_for(db, line, settings) != target_stage.NC_AIM:
            continue
        key = flow.scout_key(project)
        campaign_id = flow.scout_workstream_id(project)
        base = {"research_line": line, "domain": project.domain, "campaign_id": campaign_id}
        if funnel.stall_zero_pass_after:
            stall = stall_streak(document, line)
            last = _parse(stall["last_at"])
            if stall["streak"] >= funnel.stall_zero_pass_after and last is not None:
                until = last + timedelta(hours=funnel.stall_backoff_hours)
                if moment < until:
                    blocks[key] = {
                        **base, "reason": "funnel_stall_backoff", "until": flow._iso(until),
                        "zero_pass_cards": stall["streak"], "top_reasons": stall["reasons"],
                        "hint": "change direction: the last cards of this line all stopped "
                                "before admission; revise the line's direction or data "
                                "catalogue instead of re-scouting the same ground",
                        "release_when": "the backoff ends or a card of the line is admitted",
                    }
                    continue
        if funnel.scout_weekly_usd_per_line and campaign_id:
            spent = weekly_scout_usd(db, settings, campaign_id, moment)
            if spent >= funnel.scout_weekly_usd_per_line:
                blocks[key] = {**base, "reason": "scout_weekly_budget", "spent_usd_7d": spent,
                               "budget_usd_7d": funnel.scout_weekly_usd_per_line,
                               "release_when": "the line's scout spend of the last 7 days "
                                               "falls below the budget"}
    return blocks


# --------------------------------------------------------------------------- metrics


FUNNEL_LEVELS = ("candidates", "passed_l1", "prescreened", "passed_prescreen", "admitted",
                 "ready", "graded", "delivered")


def metrics(document: Mapping[str, Any], settings, *, scout_counts: Mapping[str, Any] | None
            = None) -> dict[str, Any]:
    """Per line: NC-era funnel counts, conversion rates, expected vs achieved bands."""

    from .delivery_facts import ever_delivered

    lines: dict[str, dict[str, Any]] = {}
    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping):
            continue
        line = str(topic.get("research_line") or f"legacy:{topic.get('domain') or 'unknown'}")
        row = lines.setdefault(line, {"all": Counter(), "nc": Counter(),
                                      "expected": Counter(), "achieved": Counter()})
        check = topic.get("card_check") if isinstance(topic.get("card_check"), Mapping) else {}
        nc = check.get("target_stage") == "nc_aim" or (
            isinstance(topic.get("admission"), Mapping)
            and topic["admission"].get("target_stage") == "nc_aim")
        states = {topic.get("status"), *(entry.get("to") for entry in topic.get("history") or [])}
        reason = _reason(topic) if topic.get("status") in {"rejected", "frozen"} else ""
        levels = {"candidates"}
        if not (topic.get("status") == "rejected" and reason in (
                L1_REJECTIONS | {"card_invalid", "card_precheck_failed",
                                 "card_capability_missing", "card_data_unavailable",
                                 "card_target_repeat_failure", "duplicate_fingerprint"})):
            levels.add("passed_l1")
        prescreen = check.get("prescreen") if isinstance(check.get("prescreen"), Mapping) else {}
        if prescreen.get("status") in {"pass", "fail", "unavailable"}:
            levels.add("prescreened")
        if prescreen.get("status") == "pass":
            levels.add("passed_prescreen")
        if "admitted" in states:
            levels.add("admitted")
        if "ready_queue" in states:
            levels.add("ready")
        grade = topic.get("venue_grade") if isinstance(topic.get("venue_grade"), Mapping) else {}
        if grade.get("achieved_band"):
            levels.add("graded")
            row["achieved"][str(grade["achieved_band"])] += 1
        if topic.get("paper_id") and ever_delivered(topic):
            levels.add("delivered")
        for level in levels:
            row["all"][level] += 1
            if nc:
                row["nc"][level] += 1
        if nc and "admitted" in states:
            row["expected"][str(_admitted_band(topic) or "unknown")] += 1
    target = settings.program.funnel.target_mix
    result: dict[str, Any] = {}
    for line, row in sorted(lines.items()):
        nc_counts = {level: row["nc"][level] for level in FUNNEL_LEVELS}
        conversion = {}
        for before, after in zip(FUNNEL_LEVELS, FUNNEL_LEVELS[1:]):
            if row["nc"][before]:
                conversion[f"{before}->{after}"] = round(row["nc"][after] / row["nc"][before], 3)
        achieved = dict(row["achieved"])
        graded = sum(achieved.values())
        result[line] = {
            "admission_min_band": admission_min_band(settings, line),
            "all_topics": {level: row["all"][level] for level in FUNNEL_LEVELS},
            "nc_aim": nc_counts, "conversion": conversion,
            "expected_band_at_admission": dict(row["expected"]),
            "achieved_band": achieved,
            "achieved_per_10": {band: round(10 * count / graded, 1)
                                for band, count in achieved.items()} if graded else {},
            **({"scouts": dict(scout_counts.get(line) or {})} if scout_counts else {}),
        }
    configured_lines = getattr(getattr(settings, "program", None), "lines", None) or {}
    return {"lines": result,
            "admission_min_band": settings.program.funnel.admission_min_band,
            "line_floors": {line: admission_min_band(settings, line)
                            for line in configured_lines},
            "target_mix_per_10": {band: list(pair) for band, pair in target.items()},
            "note": "nc_aim counts only cards registered under the NC aim; all_topics is the "
                    "whole ledger. Conversion is level-to-level within nc_aim."}


def scout_counts(db, *, since: str | None = None) -> dict[str, dict[str, int]]:
    """Per line: scouts scheduled and empty draws (from program events)."""

    counts: dict[str, Counter] = defaultdict(Counter)
    for event in db.events(entity_type="program"):
        if since and str(event.get("created_at") or "") < since:
            continue
        payload = event.get("payload") or {}
        if event["event_type"] == "topic_scout_scheduled" and payload.get("research_line"):
            counts[payload["research_line"]]["scheduled"] += 1
        elif event["event_type"] == "topic_scout_empty":
            line = str(payload.get("key") or event.get("entity_id") or "")
            counts[line]["empty"] += 1
    return {line: dict(row) for line, row in counts.items()}


def spin_hours(db, settings, document: Mapping[str, Any], scout_campaigns: Mapping[str, str],
               *, moment: datetime) -> dict[str, float]:
    """Agent hours of the last 7 days on scout-campaign tasks that left no live card."""

    from .usage import attempt_figures, normalized_attempts

    alive_sources = set()
    for topic in document.get("topics") or []:
        if isinstance(topic, Mapping) and topic.get("status") != "rejected":
            alive_sources.update(str(topic.get(key) or "") for key in (
                "source_task_id", "proposer_task_id"))
            state = (topic.get("card_check") or {}).get("prescreen") if isinstance(
                topic.get("card_check"), Mapping) else None
            if isinstance(state, Mapping):
                alive_sources.add(str(state.get("task_id") or ""))
    since = moment - timedelta(days=7)
    result: dict[str, float] = {}
    for line, campaign in scout_campaigns.items():
        hours = 0.0
        for attempt in normalized_attempts(db, campaign_ids=[campaign]):
            finished = _parse(attempt.get("finished_at"))
            if finished is None or finished < since or attempt["task_id"] in alive_sources:
                continue
            hours += attempt_figures(attempt, settings)["agent_seconds"] / 3600
        result[line] = round(hours, 2)
    return result


__all__ = [
    "BANDS", "HOOKS", "THRESHOLDS", "admission_instruction", "admission_min_band",
    "admission_problems", "advance_prescreens", "calibrated_band", "card_contract_errors",
    "evaluate_prescreen", "metrics", "nc_grade", "prescreen_held", "research_fields",
    "scout_blocks", "scout_floor_instruction", "scout_instruction", "screen_card",
    "source_access_problems",
]
