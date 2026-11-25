"""Replay of archived unified-review decisions through the synthesis code (B6, 2026-11-25).

A replay recomputes ``merged`` from the archived role reports only: editor screen, referee
reports, delivery reader, the formal verifier's blockers and issue summary (with the finding
kinds of its report), the rejection-history blockers, the follow-up items and changed text,
and a recorded final-ruling basis. No model is called and nothing is written.

The module works with any version of ``paper_writing`` on ``sys.path`` (the B6 replay ran it
against the pre-refactor commit 8ac8a1b and against the refactor), so it uses public
functions only.
"""
from __future__ import annotations

import copy
import gzip
import json
import re
from pathlib import Path
from typing import Any, Mapping

FIXTURE = Path(__file__).with_name("decisions.json.gz")
EXPECTATIONS = Path(__file__).with_name("expectations.json")

# Narrative fields the synthesis never reads; a snapshot drops them.
_NARRATIVE = {"summary", "correctness_findings", "novelty_and_context", "significance", "presentation",
              "evidence_consistency", "contribution_in_two_sentences", "closest_prior_work",
              "advance_over_prior_work", "significance_for_journal", "readership_for_journal",
              "presentation_fails_restatement", "prior_rejections_addressed"}
_QUOTED = re.compile(r"[“\"‘]([^”\"’]{12,600})[”\"’]")


def _plain(text: str) -> str:
    text = re.sub(r"\\[A-Za-z]+\*?", " ", str(text or ""))
    text = re.sub(r"[{}~$]", " ", text)
    return " ".join(text.lower().split())


def _changed_excerpt(changed: str | None, record: Mapping[str, Any]) -> str | None:
    """The pieces of the round's added text that any quotation in the record matches.

    Quote matching is a substring test against the changed text, so keeping only the
    matching pieces preserves every result while the snapshot stays small."""
    if changed is None:
        return None
    found = []
    for span in _QUOTED.findall(json.dumps(record, ensure_ascii=False).replace('\\"', '"')):
        for piece in re.split(r"\.\.\.|…|\[\.\.\.\]", span):
            piece = _plain(piece).strip(" .,;:")
            if len(piece) >= 12 and piece in changed and piece not in found:
                found.append(piece)
    return " || ".join(found)


def _slim_summary(summary: Any) -> Any:
    """Raw formal findings only; root causes and categories are recomputed on load."""
    if isinstance(summary, Mapping) and isinstance(summary.get("raw_findings"), list):
        return {"raw_findings": summary["raw_findings"]}
    return summary


def snapshot(record: Mapping[str, Any], root: Path, kinds: Mapping[str, str]) -> dict[str, Any]:
    """The inputs of one archived decision that the synthesis reads."""
    def slim(report):
        return {k: v for k, v in (report or {}).items() if k not in _NARRATIVE}

    formal = record.get("formal_check") or {}
    reader = record.get("delivery_reader")
    if isinstance(reader, Mapping):
        reader = {k: (("x" if str(v or "").strip() else "") if k in ("question", "comparison", "answer", "meaning",
                                                                      "supporting_panel") else v)
                  for k, v in reader.items() if k in ("question", "comparison", "answer", "meaning",
                                                      "supporting_panel", "repairs", "image_errors")}
    inputs = {"editor_screen": slim(record.get("editor_screen")),
              "referee_reports": {n: slim(r) for n, r in (record.get("referee_reports") or {}).items()},
              "delivery_reader": reader}
    snap = {
        "paper_id": record.get("paper_id"), "run_id": record.get("run_id"),
        "target_journal": record.get("target_journal"), "review_mode": record.get("review_mode"),
        "round_for_target": record.get("round_for_target"),
        **inputs,
        "formal": {"blockers": formal.get("blockers") or [], "issue_summary": _slim_summary(formal.get("issue_summary")),
                   "has_report": bool(formal.get("path")), "kinds": dict(kinds)},
        "raw_formal_blockers": (record.get("merged") or {}).get("raw_formal_blockers") or [],
        "editorial_history_blockers": record.get("editorial_history_blockers") or [],
        "followup_items": record.get("followup_items"),
        "followup_changed_text": _changed_excerpt(record.get("followup_changed_text"), inputs),
        "previous_required_items": record.get("previous_required_items"),
        "final_check": bool(record.get("final_check")),
        "final_ruling_basis": record.get("final_ruling_basis"),
        "review_track": record.get("review_track") or {"track": "routine", "minimum_overall_score": None},
        "archived_outcome": (record.get("merged") or {}).get("outcome"),
    }
    return snap


def load_fixture(path: Path = FIXTURE) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def replay(snap: Mapping[str, Any]) -> dict[str, Any]:
    """``merged`` recomputed from a snapshot with the ``paper_writing`` on ``sys.path``."""
    from paper_writing import formal_checks
    from paper_writing import review_flow as flow

    snap = copy.deepcopy(snap)
    formal = snap["formal"]
    kinds = formal.get("kinds") or {}
    blockers = list(formal.get("blockers") or [])
    summary = formal.get("issue_summary")
    if isinstance(summary, Mapping) and "by_category" not in summary and "raw_findings" in summary:
        summary = formal_checks.issue_summary(summary["raw_findings"])
    blockers, downgraded = formal_checks.material_blockers(blockers, summary, kinds)
    if downgraded and summary:
        summary = formal_checks.precision_view(summary, kinds)
    if not blockers and snap.get("raw_formal_blockers"):
        # Binding or stage failures (validate_binding, a failed verifier) are not materiality.
        recorded = set(formal.get("blockers") or [])
        blockers = [b for b in snap["raw_formal_blockers"] if b not in recorded]
    if blockers and summary and not any((summary.get("by_category") or {}).values()):
        summary = {"by_category": {"scientific": [], "technical": blockers}}
    if blockers and not summary:
        summary = {"by_category": {"scientific": [], "technical": blockers}}
    items = snap.get("followup_items")
    previous = None
    if items is not None:
        previous = {"items": items}
    elif snap.get("previous_required_items"):
        previous = {"items": snap["previous_required_items"]}
    history = snap.get("editorial_history_blockers") or []
    referees = snap["referee_reports"]
    merged = flow.merge(snap["editor_screen"], referees, history, formal_blockers=blockers,
                        formal_summary=summary, followup_items=items, reader_report=snap.get("delivery_reader"),
                        previous=previous, changed_text=snap.get("followup_changed_text"),
                        final_check=bool(snap.get("final_check")))
    merged = flow.apply_review_track(merged, referees, snap.get("review_track") or {"track": "routine"})
    basis = snap.get("final_ruling_basis")
    if isinstance(basis, Mapping) and not snap.get("final_check") and not blockers and not history \
            and merged.get("outcome") == "revision_required":
        merged = flow.apply_final_ruling(merged, basis)
    return merged


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())[:240]


def verdicts(merged: Mapping[str, Any]) -> dict[str, Any]:
    """Each itemised finding of ``merged`` with its verdict (block / advice)."""
    rows: dict[str, str] = {}
    reasons: dict[str, str] = {}

    def put(key: str, blocking: bool, reason: Any = None) -> None:
        # One finding listed twice (a dimension repair and its required change) keeps the
        # stricter verdict.
        rows[key] = "block" if blocking or rows.get(key) == "block" else "advice"
        if reason and rows[key] == "advice":
            reasons[key] = str(reason)

    for change in merged.get("required_changes") or []:
        put(f"change|{change.get('referee')}|{_text(change.get('change'))}", not change.get("advisory"),
            change.get("downgrade_reason") or change.get("materiality_rule"))
    for item in merged.get("unresolved_previous_items") or []:
        put(f"previous|{item.get('referee')}|{_text(item.get('item'))}", not item.get("advisory"),
            item.get("downgrade_reason") or item.get("materiality_rule"))
    for blocker in merged.get("scientific_blockers") or []:
        put(f"science|{_text(blocker)}", True)
    for item in merged.get("advisory_items") or []:
        key = f"change|{item.get('referee')}|{_text(item.get('change'))}"
        if key not in rows:
            put(key, False, item.get("downgrade_reason") or item.get("materiality_rule"))
    return {"outcome": merged.get("outcome"), "next_action": merged.get("next_action"), "items": rows,
            "reasons": reasons}


EXPECTED = Path(__file__).with_name("expected_verdicts.json")


def digest(verdict: Mapping[str, Any]) -> dict[str, Any]:
    """A compact, order-free fingerprint of one replayed decision's verdicts."""
    import hashlib

    items = verdict.get("items") or {}
    blocking = sorted(key for key, value in items.items() if value == "block")
    return {"outcome": verdict.get("outcome"), "next_action": verdict.get("next_action"),
            "blocking": len(blocking), "advice": len(items) - len(blocking),
            "blocking_sha256": hashlib.sha256("\n".join(blocking).encode()).hexdigest()[:16]}


def snapshot_key(snap: Mapping[str, Any]) -> str:
    return f"{snap['paper_id']}/{snap['run_id']}"
