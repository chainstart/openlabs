"""Tests for 2026-11-27 four-class freeze reasons and read-only backfill report."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import test_program_autonomy as autonomy

from openlabs import owner
from openlabs.contracts import (
    FREEZE_REASON_CATEGORIES,
    FREEZE_REASON_TO_CATEGORY,
    freeze_reason_category,
    validate_direction_decision,
)
from openlabs.program import freeze_topic, open_topic_ledger
from openlabs.reopen import ReopenGrantError, grant_operator_reopen
from openlabs.topic_freeze import (
    freeze_backfill_report,
    operator_freeze,
)


# --------------------------------------------------------------------------- 1. Freeze reason classes


@pytest.mark.parametrize(
    ("reason_class", "expected_category"),
    [
        ("data_access", "data_access"),
        ("method_capability", "method_capability"),
        ("negative_result", "negative_result"),
        ("resources_exhausted", "resources_exhausted"),
        ("decisive_data_unavailable", "data_access"),
        ("feasibility_precheck_failed", "method_capability"),
        ("primary_endpoint_failed", "negative_result"),
        ("contribution_insufficient", "negative_result"),
        ("no_eligible_venue", "negative_result"),
        ("budget_exhausted", "resources_exhausted"),
        ("overdue", "resources_exhausted"),
        ("review_stalled", "resources_exhausted"),
        ("infrastructure", "resources_exhausted"),
    ],
)
def test_freeze_topic_records_class_and_mapped_category(
    tmp_path: Path, monkeypatch, reason_class: str, expected_category: str
) -> None:
    paths, db, settings, (topic,) = autonomy._program(tmp_path, monkeypatch)
    ledger = open_topic_ledger(paths, settings.program)
    evidence = [{"path": "evidence/freeze.json", "sha256": "a" * 64}]

    assert freeze_reason_category(reason_class) == expected_category
    assert FREEZE_REASON_TO_CATEGORY[reason_class] == expected_category

    freeze_topic(
        ledger,
        topic["topic_id"],
        db=db,
        reason_class=reason_class,
        evidence=evidence,
        decided_by="direction:test",
    )
    stored = ledger.topic(topic["topic_id"])
    assert stored is not None
    assert stored["status"] == "frozen"
    assert stored["freeze_reason_class"] == reason_class
    assert stored["freeze_reason_category"] == expected_category


def test_operator_freeze_records_four_classes_and_category(tmp_path: Path, monkeypatch) -> None:
    paths, db, settings, (topic,) = autonomy._program(tmp_path, monkeypatch)
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET status='queued' WHERE campaign_id=?",
            (topic["campaign_id"],),
        )
    ev = paths.data / "revisions" / "FREEZE-20261127.md"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text("Frozen due to solver capability limit.\n", encoding="utf-8")

    result = operator_freeze(
        db,
        paths,
        settings,
        topic_id=topic["topic_id"],
        reason_class="method_capability",
        evidence=["revisions/FREEZE-20261127.md"],
        by="owner",
        reason="Shared solver lacks spot + third-light configuration.",
        reopen_conditions=["new_method=Add validated spot+l3 configuration to shared solver."],
    )
    assert result["freeze_reason_class"] == "method_capability"
    assert result["freeze_reason_category"] == "method_capability"
    stored = open_topic_ledger(paths, settings.program).topic(topic["topic_id"])
    assert stored["freeze_reason_class"] == "method_capability"
    assert stored["freeze_reason_category"] == "method_capability"


def test_direction_decision_validated_against_four_classes() -> None:
    base_reason = autonomy.CONTEXT["strongest_desk_reject_reason"]
    for category in FREEZE_REASON_CATEGORIES:
        decision = {
            "choice": "freeze",
            "rationale": f"Evidence establishes {category}.",
            "answers_reason": base_reason,
            "freeze": {
                "reason_class": category,
                "reopen_conditions": [
                    {"type": "new_method", "description": "Concrete reopen condition."}
                ],
            },
        }
        assert validate_direction_decision(decision).valid, category

    # Explicit reason_category matching a legacy code is accepted; mismatching one is rejected.
    matching = {
        "choice": "freeze",
        "rationale": "Primary endpoint failed.",
        "answers_reason": base_reason,
        "freeze": {
            "reason_class": "primary_endpoint_failed",
            "reason_category": "negative_result",
            "reopen_conditions": [
                {"type": "new_method", "description": "New formulation."}
            ],
        },
    }
    assert validate_direction_decision(matching).valid

    mismatched = {
        **matching,
        "freeze": {
            **matching["freeze"],
            "reason_category": "data_access",
        },
    }
    res_mismatch = validate_direction_decision(mismatched)
    assert not res_mismatch.valid
    assert any("does not match" in err for err in res_mismatch.errors)

    # Unlisted / ad-hoc freeze reason strings are rejected with the four classes listed.
    for invalid in ("primary_endpoint_inconclusive", "shared_solver_missing", "tired", ""):
        bad = {
            "choice": "freeze",
            "rationale": "Invalid class test.",
            "answers_reason": base_reason,
            "freeze": {
                "reason_class": invalid,
                "reopen_conditions": [
                    {"type": "new_method", "description": "Concrete reopen condition."}
                ],
            },
        }
        result = validate_direction_decision(bad)
        assert not result.valid
        assert any("data_access" in err and "method_capability" in err for err in result.errors)


def test_direction_decision_prompt_and_owner_brief_include_four_classes(
    tmp_path: Path, monkeypatch
) -> None:
    paths, db, settings, (topic,) = autonomy._program(tmp_path, monkeypatch)
    research = db.latest_task(topic["campaign_id"])
    autonomy._lease(paths, settings, monkeypatch, db, research["task_id"])
    autonomy._finish(
        db, paths, research["task_id"],
        extra=autonomy._research_payload(topic, "failed"), session="r1",
    )
    autonomy._tick(paths, settings, monkeypatch)
    decision_task = autonomy._direction_task(db)
    objective = decision_task["objective"]
    packet = json.loads(Path(decision_task["input_path"]).read_text(encoding="utf-8"))

    for cls in FREEZE_REASON_CATEGORIES:
        assert cls in objective
        assert cls in packet["freeze_reason_classes"]
    assert "Living Planet Database 2026" in objective
    assert "Challenge-2021 Georgia" in objective

    skill_text = (
        Path(__file__).resolve().parents[2]
        / "workflows/paper/skills/openlabs-direction-decision/SKILL.md"
    ).read_text(encoding="utf-8")
    for cls in FREEZE_REASON_CATEGORIES:
        assert cls in skill_text

    # Owner brief also instructs freezing seats to set freeze_reason_class.
    campaign = db.campaign(topic["campaign_id"])
    brief = owner.render_brief(
        paths, settings, campaign=campaign, task=research,
        topic=topic, adapter_family="anthropic", deadline=datetime.now(UTC),
    )
    assert "freeze_reason_class" in brief
    for cls in FREEZE_REASON_CATEGORIES:
        assert cls in brief


def test_scientific_four_classes_block_operator_reopen_grant(tmp_path: Path, monkeypatch) -> None:
    paths, db, settings, (topic,) = autonomy._program(tmp_path, monkeypatch)
    ledger = open_topic_ledger(paths, settings.program)
    evidence = [{"path": "evidence/freeze.json", "sha256": "b" * 64}]
    freeze_topic(
        ledger, topic["topic_id"], db=db, reason_class="method_capability",
        evidence=evidence, decided_by="direction:test",
    )
    with pytest.raises(ReopenGrantError, match="scientific reason"):
        grant_operator_reopen(
            db, paths, settings, topic_id=topic["topic_id"],
            reason="try text revision", by="owner",
        )


def test_freeze_backfill_report_is_read_only_and_classifies_four_classes(
    tmp_path: Path, monkeypatch
) -> None:
    paths, db, settings, (topic,) = autonomy._program(tmp_path, monkeypatch)
    ev_dir = tmp_path / "ev"
    ev_dir.mkdir()

    def _write_ev(name: str, payload: dict) -> dict[str, str]:
        p = ev_dir / f"{name}.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return {"path": str(p), "sha256": "c" * 64}

    samples = [
        ("t-data-form", "data_access", _write_ev("e1", {
            "summary": "Living Planet Database 2026.1 requires a human recipient portal form.",
            "direction_decision": {"rationale": "Access form requires named recipient."},
        })),
        ("t-data-field", "data_access", _write_ev("e2", {
            "summary": "Four-continent endpoint inconclusive.",
            "gate_result": {"reason": "Public Georgia release has no verified patient-linkage map."},
        })),
        ("t-method", "method_capability", _write_ev("e3", {
            "summary": "FEMTO STFEN source reproduction miss vs published baseline.",
            "gate_result": {"reason": "Does not explain FEMTO source reproduction miss."},
        })),
        ("t-solver-after-wait", "method_capability", _write_ev("e3b", {
            "summary": "The mandatory shared solver lacks exact recovery support.",
            "gate_result": {
                "freeze_reason_class": "shared_solver_missing_frozen_precheck_recovery",
                "reason": "Freeze for a missing line capability.",
            },
        })),
        ("t-negative", "negative_result", _write_ev("e4", {
            "summary": "Registered change -6.39 (95% interval -24.10 to +6.62).",
            "primary_endpoint_verdict": "inconclusive",
            "gate_result": {
                "freeze_reason_class": "primary_endpoint_inconclusive",
                "reason": "The registered 95% moving-block interval includes zero.",
            },
        })),
        ("t-resources", "resources_exhausted", _write_ev("e5", {
            "summary": "12 core-hour allocation is exhausted.",
            "gate_result": {"reason": "compute_budget_exhausted; precheck incomplete."},
        })),
    ]

    ledger = open_topic_ledger(paths, settings.program)
    doc = ledger.read()
    doc["topics"] = [
        {
            **topic,
            "topic_id": tid,
            "status": "frozen",
            "frozen_at": f"2026-11-20T0{idx}:00:00Z",
            "freeze_reason_class": "decisive_data_unavailable",
            "freeze_evidence": [ev],
            "history": [
                *(
                    [{"decided_by": "direction:earlier",
                      "detail": {"answers_reason": "agent-time budget appears exhausted"}}]
                    if tid == "t-solver-after-wait" else []
                ),
                {"kind": "topic_freeze_noted", "detail": {"reason_class_inferred": True}},
            ],
        }
        for idx, (tid, _expected, ev) in enumerate(samples, 1)
    ]
    ledger.path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    before_bytes = ledger.path.read_bytes()

    report = freeze_backfill_report(paths, settings)
    assert ledger.path.read_bytes() == before_bytes  # strictly read-only
    assert report["read_only"] is True
    assert report["matched_topics"] == len(samples)
    by_id = {row["topic_id"]: row["recommended_class"] for row in report["topics"]}
    for tid, expected, _ev in samples:
        assert by_id[tid] == expected
    assert report["by_recommended_class"] == {
        "data_access": 2,
        "method_capability": 2,
        "negative_result": 1,
        "resources_exhausted": 1,
    }
