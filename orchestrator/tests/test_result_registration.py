"""Artifact ids and claim evidence are fixed by the control plane (2026-11-16).

Owner attempt 071e990c wrote three artifacts without ``artifact_id`` and card repair
3b5a56f4 cited ``repaired-topic-card``, which it never listed; both went to needs_replan.
"""

from __future__ import annotations

import json
from pathlib import Path

from openlabs import codex_hook
from openlabs.contracts import IDENTIFIER, validate_result_bundle
from openlabs.result_normalize import legal_id, normalize_registration, warnings_of

SHA = {name: (name * 64)[:64] for name in "abcdef"}


def _bundle(artifacts: list[dict], claims: list[dict] | None = None) -> dict:
    return {
        "schema_version": "openlabs.result_bundle.v1",
        "task_id": "task", "campaign_id": "campaign", "lab_id": "physics",
        "domain": "physics", "status": "succeeded", "summary": "Done.",
        "artifacts": artifacts,
        "claims": claims if claims is not None else [],
        "next_actions": [],
    }


def _artifact(name: str, sha: str, artifact_id: object = None) -> dict:
    item = {"uri": f"file:///stage/{name}", "sha256": sha, "kind": "data"}
    if artifact_id is not None:
        item["artifact_id"] = artifact_id
    return item


def _claim(evidence: list, status: str = "supported") -> dict:
    return {"claim_id": "c1", "text": "Claim.", "status": status, "evidence": evidence,
            "limitations": []}


def test_the_owner_seat_without_ids_validates() -> None:
    # 071e990c, shortened: three staged files, no artifact_id at all.
    payload = _bundle([
        _artifact("reference_source.tar.gz", SHA["a"]),
        _artifact("TIC198415814_S86_recomputed.fits", SHA["b"]),
        _artifact("hlsp_tess-spoc_tess_phot_0000000198415814-s0086_tess_v1_lc.fits", SHA["c"]),
    ])
    assert not validate_result_bundle(payload).valid
    fixed, changes = normalize_registration(payload)
    assert validate_result_bundle(fixed).errors == ()
    ids = [item["artifact_id"] for item in fixed["artifacts"]]
    assert ids[0] == "reference_source-aaaaaaaa"
    assert ids[1] == "TIC198415814_S86_recomputed-bbbbbbbb"
    assert [item["kind"] for item in changes] == ["missing_id"] * 3
    # Deterministic: the same payload gives the same ids.
    assert normalize_registration(payload)[0] == fixed


def test_duplicates_get_suffixes_and_ambiguous_references_keep_the_first() -> None:
    payload = _bundle(
        [_artifact("x.json", SHA["a"], "fig"), _artifact("y.json", SHA["b"], "fig"),
         _artifact("z.json", SHA["c"], "")],
        [_claim(["fig"])],
    )
    fixed, changes = normalize_registration(payload)
    assert validate_result_bundle(fixed).errors == ()
    assert [item["artifact_id"] for item in fixed["artifacts"]][:2] == ["fig", "fig-2"]
    assert fixed["claims"][0]["evidence"] == ["fig"]
    assert any(item["kind"] == "ambiguous_evidence" and item["also_declared_as"] == ["fig-2"]
               for item in changes)
    assert any("names several artifacts" in text for text in warnings_of(changes))


def test_illegal_and_long_ids_are_rewritten_with_their_references() -> None:
    long_id = "a" * 200
    payload = _bundle(
        [_artifact("p.json", SHA["a"], "my figure (final).png"),
         _artifact("q.json", SHA["b"], long_id), _artifact("r.json", SHA["c"], "-lead")],
        [_claim(["my figure (final).png", long_id, "-lead"])],
    )
    fixed, _changes = normalize_registration(payload)
    assert validate_result_bundle(fixed).errors == ()
    ids = [item["artifact_id"] for item in fixed["artifacts"]]
    assert ids[0] == "my-figure-final-.png"
    assert len(ids[1]) <= 128 and IDENTIFIER.fullmatch(ids[1])
    assert ids[2] == "lead"
    assert fixed["claims"][0]["evidence"] == ids
    assert legal_id("***") == ""


def test_an_unknown_evidence_id_is_matched_by_file_name_or_left_unresolved() -> None:
    payload = _bundle(
        [_artifact("repaired_topic_card.json", SHA["a"], "card-json")],
        [_claim(["repaired-topic-card"]), {**_claim(["nothing-like-it"]), "claim_id": "c2"}],
    )
    fixed, changes = normalize_registration(payload)
    assert validate_result_bundle(fixed).errors == ()
    assert fixed["claims"][0]["evidence"] == ["card-json"]
    second = fixed["claims"][1]
    assert second["evidence"] == [] and second["unresolved_evidence"] == ["nothing-like-it"]
    assert second["status"] == "unsupported"
    assert second["status_before_normalization"] == "supported"
    kinds = [item["kind"] for item in changes]
    assert "evidence_matched" in kinds and "claim_unsupported" in kinds


def test_the_card_repair_reference_is_downgraded_not_refused() -> None:
    # 3b5a56f4: the card is in topic_cards, the claim cited it as an artifact.
    payload = _bundle(
        [_artifact("topic-c53fc3b521aee0d7.json", SHA["a"], "repair-packet")],
        [_claim(["repaired-topic-card"])],
    )
    fixed, changes = normalize_registration(payload)
    assert validate_result_bundle(fixed).errors == ()
    assert fixed["claims"][0]["status"] == "unsupported"
    assert normalize_registration(fixed)[1] == []  # idempotent


def test_valid_results_are_left_alone() -> None:
    payload = _bundle([_artifact("a.json", SHA["a"], "a")], [_claim(["a"])])
    fixed, changes = normalize_registration(payload)
    assert fixed == payload and changes == []


def test_the_stop_hook_judges_the_normalized_form(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    staged = tmp_path / "out.json"
    staged.write_text("{}", encoding="utf-8")
    payload = _bundle([{"uri": staged.as_uri(), "kind": "data"}], [_claim(["out"])])
    payload["status"] = "needs_replan"
    payload["next_actions"] = ["Continue."]
    result.write_text(json.dumps(payload), encoding="utf-8")
    problems = codex_hook._stop_gate_problems({"result_path": str(result)})
    assert not any("artifact_id" in problem or "unknown artifacts" in problem
                   for problem in problems), problems
    # The agent's file is not rewritten by the hook; the ingest applies the same fix.
    assert json.loads(result.read_text(encoding="utf-8")) == payload


def test_a_supported_claim_without_evidence_is_read_as_unsupported() -> None:
    # 3b5a56f4's first Stop block: "claims[0] requires evidence for status supported".
    payload = _bundle([_artifact("a.json", SHA["a"], "a")], [_claim([])])
    fixed, changes = normalize_registration(payload)
    assert validate_result_bundle(fixed).errors == ()
    assert fixed["claims"][0]["status"] == "unsupported"
    assert [item["kind"] for item in changes] == ["claim_unsupported"]
    hypothesis = _bundle([], [_claim([], status="hypothesis")])
    assert normalize_registration(hypothesis)[1] == []
