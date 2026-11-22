"""Factual rebuttal of one archived blocker, and revision evidence outside the support digest."""
import hashlib
import json

import pytest
import yaml

from paper_writing import rebuttal, resynthesis, review_flow as flow
from test_review_flow import MANUSCRIPT, _apply_fixture, _formal_only_fixture

TABLE_LINE = MANUSCRIPT.split("\n").index(r"\begin{table}\begin{tabular}{cc}a & 1.5\\\end{tabular}\end{table}") + 1
PRINTED = ("The table prints 1.6 for row a. The archived value rounds to 1.5.")
UNPRINTED = ("The archived value for row a rounds to 1.5 and not to 1.6, so the reader takes 1.6.")


def _basis(tmp_path, monkeypatch, finding=PRINTED):
    """An archived same-journal follow-up blocked only by referee_a's new finding."""
    from paper_writing import operations

    basis, response, pre, _ = _formal_only_fixture(tmp_path, monkeypatch, MANUSCRIPT)
    meta, written = _apply_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(operations, "_review_workspace_fingerprints", lambda *args: pre["fingerprints"])
    monkeypatch.setattr(flow, "preflight", lambda *args, **kwargs: pre | {
        "build_inputs": [], "preparation_advisories": []})
    monkeypatch.setattr(flow, "body_length_block", lambda *args: {})
    monkeypatch.setattr(flow, "expanded_review_documents", lambda *args: MANUSCRIPT)
    monkeypatch.setattr(flow.formal_checks, "validate_binding", lambda *args, **kwargs: [])
    monkeypatch.setattr(flow.formal_checks, "archived_inputs", lambda *args: ([{"id": "main", "text": MANUSCRIPT}], ""))
    monkeypatch.setattr(flow.formal_checks, "current_inputs", lambda *args: ([{"id": "main", "text": MANUSCRIPT}], ""))
    data = json.loads(basis.read_text())
    report = data["referee_reports"]["referee_a"]
    report.update(followup_review=True, previous_items=[], new_findings=[dict(
        kind="numeric_or_statistical_error", location="Table, row a", finding=finding,
        reader_misconclusion="A reader takes 1.6 as the value.", why_missed="New check.")])
    data["referee_reports"]["referee_b"]["recommendation"] = "accept"
    for role, value in data["referee_reports"].items():
        payload = json.dumps(value).encode()
        (basis.parent / role / "output.json").write_bytes(payload)
        data["receipts"][role]["output_sha256"] = flow._sha256(payload)
    data["receipts"]["referee_a"]["model"] = "opus"
    formal_file = basis.parent / "formal.json"
    data.update(process=flow.PROCESS, manuscript_version="1.0", followup_items=[], formal_check={
        "valid": True, "path": formal_file.relative_to(tmp_path).as_posix(),
        "sha256": flow._json_dump(formal_file, {"inventory": {}, "issue_summary": {"raw_findings": []}})})
    data["merged"] = flow.merge(data["editor_screen"], data["referee_reports"], followup_items=[])
    assert data["merged"]["outcome"] == "revision_required"
    digest = flow._json_dump(basis, data)
    blocker = data["merged"]["required_changes"][0]["change"]
    return basis, digest, blocker, response, meta, written


def _rebuttal_file(tmp_path, digest, blocker, **overrides):
    proof = tmp_path / "papers/p/revisions/r1/proof.json"
    proof.parent.mkdir(parents=True, exist_ok=True)
    proof.write_text('{"crossing": 1.5023}\n')
    content = {"schema": rebuttal.SCHEMA, "claim": "factual_error", "decision_sha256": digest,
               "blocker": blocker, "rebuttal": "Row a prints 1.5 in the reviewed snapshot.",
               "asserted_text": "1.6", "expected_text": "1.5",
               "snapshot": {"sha256": flow._sha256(MANUSCRIPT.encode()), "line": TABLE_LINE, "quote": "a & 1.5"},
               "recomputations": [{"path": "papers/p/revisions/r1/proof.json",
                                   "sha256": flow._sha256(proof.read_bytes()), "value": "1.5023"}]}
    content.update(overrides)
    path = tmp_path / "rebuttal.json"
    path.write_text(json.dumps(content))
    return path


def _reply(tmp_path, digest, adjudications):
    path = tmp_path / "resynthesis.json"
    flow._json_dump(path, {"decision_sha256": digest, "manuscript_sha256": flow._sha256(MANUSCRIPT.encode()),
                           "explanation": "The only blocker contradicts the reviewed snapshot.",
                           "changes": [], "formal_findings": {},
                           "rebuttals": [{"adjudication": f"{a['run_dir']}/adjudication.json",
                                          "sha256": a["adjudication_sha256"]} for a in adjudications]})
    return path


def _no_model(monkeypatch):
    monkeypatch.setattr(flow, "run_role", lambda **kw: pytest.fail("A model was started"))


def test_snapshot_contradiction_is_sustained_without_a_model_and_clears_the_replay(tmp_path, monkeypatch):
    basis, digest, blocker, _, meta, written = _basis(tmp_path, monkeypatch)
    _no_model(monkeypatch)
    blocked = resynthesis.run("p", root=tmp_path, decision=basis.parent, response=_reply(tmp_path, digest, []),
                              actor="independent operator", reason="Replay", apply=False)
    assert blocked["merged"]["outcome"] == "full_review_required"
    assert not written

    record = rebuttal.run("p", root=tmp_path, decision=basis.parent, rebuttal=_rebuttal_file(
        tmp_path, digest, blocker), actor="operator", reason="Factual rebuttal")
    assert record["verdict"] == "sustained" and record["decided_by"] == "deterministic"
    assert record["blocker_roles"] == ["referee_a"] and not record["consumes_scientific_round"]
    assert record["evidence"]["snapshot"]["sha256"] == flow._sha256(MANUSCRIPT.encode())
    assert record["evidence"]["files"][0]["path"] == "papers/p/revisions/r1/proof.json"
    assert record["run_dir"].startswith("reviews/rebuttals/p/")
    # No label: the disputed value is checked against the whole snapshot.
    assert [row["check"] for row in record["checks"] if not row["passed"]] == ["located_scope"]

    result = resynthesis.run("p", root=tmp_path, decision=basis.parent,
                             response=_reply(tmp_path, digest, [record]),
                             actor="independent operator", reason="Apply the sustained rebuttal")
    assert result["merged"]["outcome"] == "ready", result["merged"]
    assert not result["consumes_scientific_round"]
    assert result["resynthesis"]["rebuttals"][0]["verdict"] == "sustained"
    assert any("withdrawn: factual rebuttal sustained" in item["change"]
               for item in result["merged"]["advisory_items"])
    assert result["referee_reports"] == json.loads(basis.read_text())["referee_reports"]
    assert written[-1]["writing_release"]["status"] == "ready"
    assert flow.validate_unified_release("p", meta, tmp_path, "snapshot") == []

    # A later delta review over this basis carries the withdrawal, not the archived blocker.
    delta = {"delta_review": {"basis_mode": "resynthesize", "basis_decision": f"{result['run_dir']}/decision.json"},
             "editor_screen": result["editor_screen"], "referee_reports": result["referee_reports"],
             "followup_items": result["followup_items"]}
    assert flow._recorded_merge(delta, [])["outcome"] == "revision_required"
    assert flow._recorded_merge(resynthesis.science_view(delta, tmp_path, meta), [])["outcome"] == "ready"

    adjudication = tmp_path / record["run_dir"] / "adjudication.json"
    adjudication.write_text(adjudication.read_text().replace('"sustained"', '"rejected"'))
    assert any("adjudication record changed" in issue
               for issue in flow.validate_unified_release("p", meta, tmp_path, "snapshot"))


@pytest.mark.parametrize("fault", ["snapshot_hash", "quote", "file_hash", "not_a_blocker", "printed"])
def test_unverified_or_contradicted_rebuttals_leave_the_blocker(tmp_path, monkeypatch, fault):
    basis, digest, blocker, _, _, written = _basis(tmp_path, monkeypatch)
    _no_model(monkeypatch)
    overrides = {"snapshot_hash": {"snapshot": {"sha256": "0" * 64, "line": TABLE_LINE, "quote": "a & 1.5"}},
                 "quote": {"snapshot": {"sha256": flow._sha256(MANUSCRIPT.encode()), "line": 2, "quote": "a & 1.5"}},
                 "file_hash": {"recomputations": [{"path": "papers/p/revisions/r1/proof.json",
                                                   "sha256": "1" * 64}]},
                 "not_a_blocker": {"blocker": "Some advisory wording."},
                 "printed": {"asserted_text": "1.5", "expected_text": "1.6"}}[fault]
    # "printed": the blocker would then be literally true of the cited line.
    quoted = overrides.pop("blocker", blocker)
    record = rebuttal.run("p", root=tmp_path, decision=basis.parent,
                          rebuttal=_rebuttal_file(tmp_path, digest, quoted, **overrides),
                          actor="operator", reason="Factual rebuttal")
    assert record["verdict"] == "rejected" and record["decided_by"] == "deterministic"
    result = resynthesis.run("p", root=tmp_path, decision=basis.parent, response=_reply(tmp_path, digest, [record]),
                             actor="independent operator", reason="Replay")
    assert result["merged"]["outcome"] == "full_review_required"
    assert any("the blocker stands" in reason for reason in result["merged"]["full_review_reasons"])
    assert not written


@pytest.mark.parametrize("verdict,outcome", [("sustained", "ready"), ("rejected", "full_review_required")])
def test_interpretive_rebuttal_goes_to_one_independent_model(tmp_path, monkeypatch, verdict, outcome):
    basis, digest, blocker, _, meta, _ = _basis(tmp_path, monkeypatch, finding=UNPRINTED)
    calls = []

    def judge(**kw):
        calls.append(kw)
        result = {"verdict": verdict, "blocker_premise": "Row a prints 1.6.",
                  "snapshot_reading": "Row a prints 1.5.", "reason": "The cited row prints 1.5."}
        kw["workdir"].mkdir()
        digest_out = flow._json_dump(kw["workdir"] / "output.json", result)
        return result, {"model": kw["role"]["model"], "output_sha256": digest_out}

    monkeypatch.setattr(flow, "run_role", judge)
    record = rebuttal.run("p", root=tmp_path, decision=basis.parent,
                          rebuttal=_rebuttal_file(tmp_path, digest, blocker),
                          actor="operator", reason="Factual rebuttal")
    assert len(calls) == 1 and calls[0]["role_name"] == rebuttal.ROLE_NAME
    assert record["decided_by"] == "model" and record["verdict"] == verdict
    # referee_a (opus, anthropic) raised it; the other family's configured model adjudicates.
    assert record["adjudicator"]["role"] == "referee_b" and record["adjudicator"]["independence"] == "cross_family"
    packet = calls[0]["user_prompt"]
    assert blocker in packet and f"{TABLE_LINE:5d}: " in packet and '"crossing": 1.5023' in packet
    result = resynthesis.run("p", root=tmp_path, decision=basis.parent, response=_reply(tmp_path, digest, [record]),
                             actor="independent operator", reason="Apply the adjudication")
    assert result["merged"]["outcome"] == outcome
    if verdict == "sustained":
        assert flow.validate_unified_release("p", meta, tmp_path, "snapshot") == []
        output = tmp_path / record["run_dir"] / "adjudicator" / "output.json"
        output.write_text(output.read_text().replace("1.5.", "1.6."))
        assert any("adjudicator output changed" in issue
                   for issue in flow.validate_unified_release("p", meta, tmp_path, "snapshot"))


def test_no_model_records_undetermined(tmp_path, monkeypatch):
    basis, digest, blocker, _, _, _ = _basis(tmp_path, monkeypatch, finding=UNPRINTED)
    _no_model(monkeypatch)
    record = rebuttal.run("p", root=tmp_path, decision=basis.parent,
                          rebuttal=_rebuttal_file(tmp_path, digest, blocker),
                          actor="operator", reason="Dry run", allow_model=False)
    assert record["verdict"] == "undetermined"
    _, problems, _ = rebuttal.sustained(tmp_path, "p", *resynthesis._basis(tmp_path, "p", basis.parent),
                                        [{"adjudication": f"{record['run_dir']}/adjudication.json",
                                          "sha256": record["adjudication_sha256"]}])
    assert problems


def test_adjudicator_independence():
    base = {"receipts": {"referee_a": {"model": "gpt-6.2-sol"}}, "writer_model": "gpt-6.2-sol"}
    roles = {"editor": {"provider": "openai-codex", "model": "gpt-6.2-astra"},
             "referee_a": {"provider": "openai-codex", "model": "gpt-6.2-sol"}}
    config = {"roles": roles, "cross_model_basis": "model"}
    assert rebuttal.select_adjudicator(config, base, ["referee_a"])[::2] == ("editor", "same_family_different_model")
    with pytest.raises(ValueError, match="differs in family"):
        rebuttal.select_adjudicator(config | {"cross_model_basis": "model_family"}, base, ["referee_a"])
    roles["referee_b"] = {"provider": "anthropic", "model": "claude-fable-5"}
    assert rebuttal.select_adjudicator(config, base, ["referee_a"])[::2] == ("referee_b", "cross_family")
    with pytest.raises(ValueError, match="not configured"):
        rebuttal.select_adjudicator(config, base, ["referee_a"], "referee_a")


def test_located_table_scope_ignores_the_value_in_another_table():
    snapshot = "\n".join([
        r"\begin{table}\caption{Fine mesh}\label{tab:fine}", r"S100 & 0.248--0.301\\", r"\end{table}",
        r"\begin{table*}\caption{Coarse mesh}\label{tab:coarse}", r"S100 & 0.247--0.298\\", r"\end{table*}"])
    line_start = snapshot.index("S100 & 0.247")
    scope = rebuttal._located_scope(snapshot, "Table tab:coarse, S100 row", line_start)
    assert scope[:2] == ("tab:coarse", "table*")
    assert "0.248" not in snapshot[scope[2]:scope[3]]
    assert rebuttal._located_scope(snapshot, "Table tab:fine, S100 row", line_start) is None
    macros = rebuttal._macros(r"\newcommand{\lo}{0.248}")
    assert rebuttal._occurs("0.248", rebuttal._expand(r"S100 & \lo--0.301", macros))


def _registry(tmp_path, sources):
    workspace = tmp_path / "papers/p"
    for name in ("support/run.py", "revisions/r4/verify.py", "revisions/r4/proof.json"):
        (workspace / name).parent.mkdir(parents=True, exist_ok=True)
        (workspace / name).write_text(name + "\n")
    record = {"paper_id": "p", "workspace": "papers/p", "target_journal": "J",
              "support": {"publication": {"source_files": [f"papers/p/{name}" for name in sources]}}}
    path = tmp_path / "registry/papers/p.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record))
    return record, path


def _decision(tmp_path, digest):
    run = tmp_path / "reviews/unified/p/20260101T000000Z"
    run.mkdir(parents=True)
    (run / "decision.json").write_text(json.dumps({
        "target_journal": "J", "stage_reached": "decision", "fingerprints": {"support_sources_sha256": digest}}))
    return run


def test_mistaken_support_entries_move_to_revision_evidence(tmp_path):
    from paper_writing import revision_evidence
    from paper_writing.support import support_sources_snapshot_sha256

    reviewed, _ = _registry(tmp_path, ["support/run.py"])
    digest = support_sources_snapshot_sha256(reviewed, repo_root=tmp_path)
    _decision(tmp_path, digest)
    record, path = _registry(tmp_path, ["support/run.py", "revisions/r4/verify.py", "revisions/r4/proof.json"])
    assert support_sources_snapshot_sha256(record, repo_root=tmp_path) != digest
    result = revision_evidence.register("p", root=tmp_path, actor="operator", reason="Response only",
                                        paths=["papers/p/revisions/r4/verify.py", "papers/p/revisions/r4/proof.json"])
    assert result["matches_review"] is True and result["support_sources_sha256"] == digest
    assert result["moved_from_support_sources"] == ["papers/p/revisions/r4/verify.py",
                                                    "papers/p/revisions/r4/proof.json"]
    stored = yaml.safe_load(path.read_text())["support"]["publication"]
    assert stored["source_files"] == ["papers/p/support/run.py"]
    assert [row["path"] for row in stored["revision_evidence"]] == result["moved_from_support_sources"]
    assert stored["revision_evidence"][1]["sha256"] == hashlib.sha256(b"revisions/r4/proof.json\n").hexdigest()
    assert (tmp_path / "papers/p/revisions/r4/proof.json").is_file()


def test_cli_registers_revision_evidence(tmp_path, capsys):
    from paper_writing.__main__ import main

    _registry(tmp_path, ["support/run.py", "revisions/r4/proof.json"])
    code = main(["program", "register-revision-evidence", "--paper-id", "p", "--root", str(tmp_path),
                 "--path", "papers/p/revisions/r4/proof.json", "--actor", "o", "--reason", "r", "--json"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["moved_from_support_sources"] == ["papers/p/revisions/r4/proof.json"]
    assert main(["review", "rebut", "--paper-id", "p", "--root", str(tmp_path), "--decision", "missing",
                 "--rebuttal", "missing.json", "--actor", "o", "--reason", "r"]) == 2


def test_revision_evidence_refuses_reviewed_or_outside_files(tmp_path):
    from paper_writing import revision_evidence
    from paper_writing.support import support_sources_snapshot_sha256

    record, _ = _registry(tmp_path, ["support/run.py", "revisions/r4/verify.py"])
    _decision(tmp_path, support_sources_snapshot_sha256(record, repo_root=tmp_path))
    with pytest.raises(ValueError, match="reviewed"):
        revision_evidence.register("p", root=tmp_path, actor="o", reason="r",
                                   paths=["papers/p/revisions/r4/verify.py"])
    with pytest.raises(ValueError, match="revisions/"):
        revision_evidence.register("p", root=tmp_path, actor="o", reason="r", paths=["papers/p/support/run.py"])
    added = revision_evidence.register("p", root=tmp_path, actor="o", reason="r",
                                       paths=["papers/p/revisions/r4/proof.json"])
    assert added["added"] == ["papers/p/revisions/r4/proof.json"] and added["matches_review"] is True
