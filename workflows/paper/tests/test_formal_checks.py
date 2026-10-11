"""Coverage, provider failures, independent outputs and release refusal tests."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from paper_writing import formal_checks as formal, review_flow as flow
from paper_writing.review_launcher import LaunchError


ROLE = {"provider": "openai-codex", "tool": "Codex", "model": "fixture-model"}
PRIMARY = "Smith. Exact positivity. 2020. Theorem 2: for every real x, x squared is nonnegative."


def fixture_workspace(root):
    manuscript = root / "papers/p/manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text(r"\begin{document}" + "\n\n" +
        r"For real $x$, $x^2\ge0$ by \cite{s}." + "\n\n" + r"\end{document}")
    (manuscript / "main.bbl").write_text(r"\begin{thebibliography}{1}\bibitem{s}Smith. Exact positivity. 2020. DOI:10.1234/example.\end{thebibliography}")
    return {"paper_id": "p", "version": "1.0", "manuscript_dir": "papers/p/manuscript",
            "formal_check": {"sources": [{"reference_keys": ["s"],
                "url": "https://publisher.example/original", "kind": "primary_text"}]}}


def transport(request):
    if request.url.host == "api.crossref.org":
        return httpx.Response(200, json={"message": {"DOI": "10.1234/example", "title": ["Exact positivity"],
            "author": [{"family": "Smith"}], "issued": {"date-parts": [[2020]]}}})
    if request.url.host == "publisher.example":
        return httpx.Response(200, text=PRIMARY, headers={"Content-Type": "text/plain"})
    return httpx.Response(404)


def mock_http(monkeypatch, handler=transport):
    client_class = httpx.Client
    monkeypatch.setattr(formal.httpx, "Client", lambda **kwargs: client_class(
        transport=httpx.MockTransport(handler), **kwargs))


def evidence(sources):
    source = next(s for s in sources if s["kind"] == "primary_text")
    return [{"source_id": source["id"], "locator": "Theorem 2", "quote": "for every real x, x squared is nonnegative"}]


def simulated_output(packet):
    result = {"references": [], "passages": []}
    proof = evidence(packet["retrieved_sources"]) if any(s["kind"] == "primary_text" for s in packet["retrieved_sources"]) else []
    if packet["scope"] == "references":
        for ref in packet["items"]:
            row = {k: "Checked against the exact original identity" for k in formal.REFERENCE_SCHEMA["properties"]
                   if k not in {"key", "status", "evidence"}}
            result["references"].append(dict(row, key=ref["key"], status="verified", evidence=proof))
    else:
        for unit in packet["items"]:
            prerequisites = []
            if unit["citations"]:
                prerequisites = [{"statement": "Nonnegativity of real squares", "status": "verified",
                    "kind": "external",
                    "reference_keys": ["s"], "original_locator": "Theorem 2", "original_assumptions": "x is real",
                    "original_conclusion": "x squared is nonnegative", "manuscript_instantiation": "real x",
                    "condition_check": "real domain explicitly given", "formula_check": "Same square and inequality", "evidence": proof}]
            result["passages"].append({"passage_id": unit["id"], "status": "verified",
                "coverage_rationale": "Every displayed/inline formula checked; source boilerplate has no external prerequisite",
                "prerequisites": prerequisites,
                "formulas": [{"formula_id": f["id"], "status": "verified", "assumptions": "real x",
                    "derivation_or_source_check": "Real square is nonnegative; notation is consistent", "evidence": proof} for f in unit["formulas"]],
                "citations": [{"citation_id": c["id"], "key": c["key"], "status": "verified",
                    "manuscript_claim": "Real squares are nonnegative", "support_check": "Exact Theorem 2 matches",
                    "evidence": proof} for c in unit["citations"]]})
    return result


def simulated_runner(**kwargs):
    # Deterministic fake provider for integrity/integration tests, in isolated
    # tmp fixtures only. No fake records enter the data repository.
    output = simulated_output(json.loads(kwargs["user_prompt"]))
    workdir = kwargs["workdir"]
    workdir.mkdir(parents=True)
    prompt = kwargs["system_prompt"] + "\n\n" + kwargs["user_prompt"]
    (workdir / "prompt.txt").write_text(prompt)
    (workdir / "system.txt").write_text(kwargs["system_prompt"])
    (workdir / "output.json").write_text(json.dumps(output))
    receipt = {"provider": ROLE["provider"], "model": ROLE["model"], "runtime_reported_models": [ROLE["model"]],
        "independent_context": True, "output_sha256": formal.sha((workdir / "output.json").read_bytes()),
        "prompt_sha256": formal.sha(prompt.encode()), "system_prompt_sha256": formal.sha(kwargs["system_prompt"].encode()),
        "schema_sha256": formal.sha(json.dumps(kwargs["schema"], sort_keys=True).encode())}
    (workdir / "receipt.json").write_text(json.dumps(receipt))
    return output, receipt


def run_fixture(root, monkeypatch):
    metadata = fixture_workspace(root)
    mock_http(monkeypatch)
    run = root / "reviews/p/run"
    run.mkdir(parents=True)
    binding = formal.run_checks({"metadata": metadata}, root, run, ROLE, 1, simulated_runner)
    assert binding["valid"] is True
    return metadata, binding, json.loads((root / binding["path"]).read_text())


def test_covers_comment_free_citations_formulas_and_uncited_passages():
    docs = [{"id": "main", "text": r"% \cite{fake}" + "\n" + r"A $x$ and \[x^2\ge0\] \citep[Thm. 2]{a,b}." +
        "\n\n" + r"An uncited theorem is also checked. \nocite{*}"},
        {"id": "supplement", "text": r"\begin{equation}y=x\end{equation}\cite{a}"}]
    inv = formal.inventory(docs, r"\bibitem[A]{a}Work A.\bibitem{b}Work B.")
    assert len(inv["references"]) == 2
    assert sum(len(u["citations"]) for u in inv["passages"]) == 3
    assert sum(len(u["formulas"]) for u in inv["passages"]) == 3
    assert any("uncited theorem" in u["text"] for u in inv["passages"])


@pytest.mark.parametrize("bib,text", [(r"\bibitem{a}One.\bibitem{a}Two.", "body"),
    (r"\bibitem{a}One.", r"\cite{missing}"), ("@article{a,title={Unused record}}", "body")])
def test_ambiguous_or_unrendered_inventory_refuses(bib, text):
    with pytest.raises(ValueError):
        formal.inventory([{"id": "main", "text": text}], bib)


def test_valid_full_pipeline_and_revalidation(tmp_path, monkeypatch):
    metadata, binding, result = run_fixture(tmp_path, monkeypatch)
    assert formal.validate_binding(binding, metadata, tmp_path, ROLE) == []
    assert len(result["receipts"]) == 2
    assert any(s["kind"] == "bibliographic_metadata" for s in result["sources"])
    assert "not a machine proof" in formal.packet(binding, tmp_path)


@pytest.mark.parametrize("mutation", ["missing_reference", "duplicate_passage", "missing_formula", "missing_citation",
    "wrong_cited_key", "invented_source", "invented_quote", "metadata_for_theorem", "unchecked_formula",
    "unchecked_reference", "unchecked_citation", "unchecked_prerequisite", "empty_conditions", "uncited_prerequisite"])
def test_incomplete_or_false_evidence_never_passes(tmp_path, monkeypatch, mutation):
    _, _, result = run_fixture(tmp_path, monkeypatch)
    report = copy.deepcopy(result["report"])
    unit = next(p for p in report["passages"] if p["citations"])
    if mutation == "missing_reference": report["references"] = []
    elif mutation == "duplicate_passage": report["passages"].append(report["passages"][0])
    elif mutation == "missing_formula": unit["formulas"].pop()
    elif mutation == "missing_citation": unit["citations"] = []
    elif mutation == "wrong_cited_key": unit["citations"][0]["key"] = "other"
    elif mutation == "invented_source": report["references"][0]["evidence"][0]["source_id"] = "invented"
    elif mutation == "invented_quote": report["references"][0]["evidence"][0]["quote"] = "The source does not contain these words."
    elif mutation == "metadata_for_theorem":
        source = next(s for s in result["sources"] if s["kind"] == "bibliographic_metadata")
        unit["prerequisites"][0]["evidence"] = [{"source_id": source["id"], "locator": "title", "quote": "Exact positivity"}]
    elif mutation == "unchecked_formula": unit["formulas"][0]["status"] = "unchecked"
    elif mutation == "unchecked_reference": report["references"][0]["status"] = "unchecked"
    elif mutation == "unchecked_citation": unit["citations"][0]["status"] = "unchecked"
    elif mutation == "unchecked_prerequisite": unit["prerequisites"][0]["status"] = "unchecked"
    elif mutation == "empty_conditions": unit["prerequisites"][0]["condition_check"] = ""
    elif mutation == "uncited_prerequisite": unit["prerequisites"][0]["reference_keys"] = []
    try:
        assert formal.report_blockers(report, result["inventory"], result["sources"])
    except (ValueError, LaunchError):
        pass


@pytest.mark.parametrize("mutation", ["evidence_body", "evidence_text", "output", "prompt", "receipt", "source_plan", "version", "policy", "report", "different_role"])
def test_changed_accepted_inputs_refuse_at_release(tmp_path, monkeypatch, mutation):
    metadata, binding, result = run_fixture(tmp_path, monkeypatch)
    if mutation.startswith("evidence_"):
        source = result["sources"][0]
        (tmp_path / source[mutation.removeprefix("evidence_") + "_path"]).write_text("changed")
    elif mutation in {"output", "prompt", "receipt"}:
        (tmp_path / result["receipts"][0]["workdir"] / (mutation + (".txt" if mutation == "prompt" else ".json"))).write_text("changed")
    elif mutation == "source_plan": metadata["formal_check"]["sources"][0]["url"] += "/changed"
    elif mutation == "version": metadata["version"] = "2.0"
    elif mutation == "different_role":
        assert formal.validate_binding(binding, metadata, tmp_path, dict(ROLE, model="another-model"))
        return
    else:
        if mutation == "policy": result["policy"]["implementation_sha256"] = "0" * 64
        elif mutation == "report": result["report"]["passages"][0]["coverage_rationale"] = "Forged aggregate"
        path = tmp_path / binding["path"]
        path.write_text(json.dumps(result)); binding["sha256"] = formal.sha(path.read_bytes())
    assert formal.validate_binding(binding, metadata, tmp_path, ROLE)


def test_provider_outage_retained_and_blocks_without_primary(tmp_path, monkeypatch):
    metadata = fixture_workspace(tmp_path); metadata.pop("formal_check")
    mock_http(monkeypatch, lambda request: httpx.Response(503))
    run = tmp_path / "review"; run.mkdir()
    def unexpected(**kwargs): raise AssertionError("A model must not be asked to invent missing evidence")
    binding = formal.run_checks({"metadata": metadata}, tmp_path, run, ROLE, 1, unexpected)
    assert binding["valid"] is False and any("lookup unresolved" in b for b in binding["blockers"])
    assert (run / "formal-check/evidence/retrieval-failures.json").is_file()


def test_doi_mismatch_not_accepted_as_success(tmp_path):
    metadata = fixture_workspace(tmp_path); metadata.pop("formal_check")
    docs, bib = formal.current_inputs(metadata, tmp_path)
    def wrong(request):
        return httpx.Response(200, json={"message": {"DOI": "10.1234/other", "title": ["Other"], "author": [{"family": "Else"}]}})
    with httpx.Client(transport=httpx.MockTransport(wrong)) as client:
        sources, errors = formal.collect_sources(formal.inventory(docs, bib), metadata, tmp_path, tmp_path / "evidence", client)
    assert sources == [] and errors


def test_no_doi_valid_publisher_source(tmp_path, monkeypatch):
    metadata = fixture_workspace(tmp_path)
    (tmp_path / metadata["manuscript_dir"] / "main.bbl").write_text(r"\bibitem{s}Smith. Exact positivity. 2020.")
    mock_http(monkeypatch)
    run = tmp_path / "review"; run.mkdir()
    binding = formal.run_checks({"metadata": metadata}, tmp_path, run, ROLE, 1, simulated_runner)
    assert binding["valid"] is True


def test_referee_can_block_misclassified_prerequisites():
    editor = {"decision": "send_to_review", "desk_reject_category": "none"}
    referee = {"recommendation": "accept", "scientific_blockers": [], "required_changes": [], "previous_items": [],
        "formal_check_assessment": {"coverage_complete": False, "omissions_or_errors": ["Uncited independence assumption"]}}
    result = flow.merge(editor, {"referee_b": referee})
    assert result["outcome"] != "ready" and result["next_action"] == "evidence_remediation"
    assert any("independence" in b for b in result["scientific_blockers"])


def test_missing_formal_check_blocks_even_current_policy_legacy_accept(tmp_path, monkeypatch):
    config = {"process": flow.PROCESS, "roles": {"editor": ROLE}, "referee_roles": ["referee_b"],
              "rejection_clearance_required": True}
    monkeypatch.setattr(flow, "review_config", lambda *args: config)
    report = {"recommendation": "accept", "scientific_blockers": [], "required_changes": [], "previous_items": []}
    record = {"merged": {"outcome": "ready"}, "editor_screen": {"decision": "send_to_review"},
        "fingerprints": {"manuscript_snapshot_sha256": "a" * 64}, "target_journal": "J",
        "review_policy_sha256": flow.review_policy_sha256(config), "referee_reports": {"referee_b": report}, "prior_decisions": []}
    path = tmp_path / "decision.json"; path.write_text(json.dumps(record))
    metadata = {"target_journal": "J", "writing_release": {"review_process": flow.PROCESS,
        "decision_record": path.name, "decision_record_sha256": formal.sha(path.read_bytes())}}
    assert any("Missing passing mandatory formal check" in p for p in flow.validate_unified_release("p", metadata, tmp_path, "a" * 64))


def test_editor_remains_first_and_failed_formal_stage_skips_ordinary_referee(tmp_path, monkeypatch):
    config = {"process": flow.PROCESS, "roles": {"editor": ROLE, "referee_b": ROLE}, "referee_roles": ["referee_b"],
        "rejection_clearance_required": True, "max_rounds_per_target": 15, "timeout_seconds": 1}
    monkeypatch.setattr(flow, "review_config", lambda *args: config)
    monkeypatch.setattr(flow, "preflight", lambda *args: {"metadata": {"paper_id": "p", "version": "1.0", "target_journal": "J"},
        "target": "J", "fingerprints": {}, "expanded": "body", "bibliography": "", "blockers": []})
    calls = []
    def formal_failure(*args):
        calls.append("formal")
        return {"valid": False, "blockers": ["Theorem conditions not established"]}
    monkeypatch.setattr(flow.formal_checks, "run_checks", formal_failure)
    def role(**kwargs):
        calls.append(kwargs["role_name"])
        if kwargs["role_name"] == "editor": return {"decision": "send_to_review", "desk_reject_category": "none"}, {}
        assert kwargs["role_name"] == "decision_letter"
        return {"letter": "Theorem conditions must be verified"}, {}
    monkeypatch.setattr(flow, "run_role", role)
    result = flow.run_review("p", root=tmp_path, apply=False)
    assert calls == ["editor", "formal", "decision_letter"]
    assert result["merged"]["outcome"] == "formal_check_blocked" and result["round_for_target"] == 1
    assert result["referee_reports"] == {}


@pytest.mark.parametrize("value", [{"enabled": False}, {"sources": "skip"}, {"sources": [
    {"reference_keys": ["s"], "kind": "primary_text", "url": "https://user:password@publisher.example/book"}]},
    {"sources": [{"reference_keys": ["s"], "kind": "primary_text", "url": "https://publisher.example/book", "pages": [10, 3]}]}])
def test_no_disable_or_unsafe_source_plan(value):
    with pytest.raises(ValueError): formal.source_plan({"formal_check": value})


@pytest.mark.parametrize("inline", [True, False])
def test_supplement_independent_printed_bibliography_is_covered(tmp_path, inline):
    metadata = fixture_workspace(tmp_path)
    manuscript = tmp_path / metadata["manuscript_dir"]
    bib = r"\begin{thebibliography}{1}\bibitem{extra}Additional work. 2021.\end{thebibliography}"
    (manuscript / "supplementary.tex").write_text(r"A supplement \cite{extra}." + (bib if inline else ""))
    if not inline:
        (manuscript / "supplementary.bbl").write_text(bib)
    docs, bibliography = formal.current_inputs(metadata, tmp_path)
    inv = formal.inventory(docs, bibliography)
    assert {r["key"] for r in inv["references"]} == {"s", "extra"}
    assert any(c["key"] == "extra" for p in inv["passages"] for c in p["citations"])


@pytest.mark.parametrize("fault", ["missing", "recursive", "dynamic", "unbraced", "conflicting_bib", "missing_bbl"])
def test_source_expansion_never_silently_drops_material(tmp_path, fault):
    metadata = fixture_workspace(tmp_path)
    manuscript = tmp_path / metadata["manuscript_dir"]
    texts = {"missing": r"\input{absent-proof}", "recursive": r"\input{supplementary}",
             "dynamic": r"\input{\unknown}", "unbraced": r"\input absent-proof",
             "conflicting_bib": r"\begin{thebibliography}{1}\bibitem{s}Different identity.\end{thebibliography}",
             "missing_bbl": r"\bibliography{unrendered}"}
    (manuscript / "supplementary.tex").write_text(texts[fault])
    with pytest.raises(ValueError):
        formal.current_inputs(metadata, tmp_path)


def test_redirect_to_metadata_cannot_be_declared_primary(tmp_path):
    metadata = fixture_workspace(tmp_path)
    def handler(request):
        if request.url.host == "publisher.example":
            return httpx.Response(302, headers={"Location": "https://api.crossref.org/works/10.1234%2Fexample"})
        return transport(request)
    docs, bib = formal.current_inputs(metadata, tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        sources, errors = formal.collect_sources(formal.inventory(docs, bib), metadata, tmp_path, tmp_path / "evidence", client)
    assert errors == []
    assert sources and all(s["kind"] == "bibliographic_metadata" for s in sources)


@pytest.mark.parametrize("returned", ["9999.99999v1", "1234.56789v2"])
def test_arxiv_response_identity_and_requested_version_are_exact(tmp_path, returned):
    metadata = fixture_workspace(tmp_path); metadata.pop("formal_check")
    manuscript = tmp_path / metadata["manuscript_dir"]
    (manuscript / "main.bbl").write_text(r"\bibitem{s}Smith. Work. arXiv:1234.56789v1.")
    atom = f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/{returned}</id><title>Wrong record</title></entry></feed>'
    docs, bib = formal.current_inputs(metadata, tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=atom))) as client:
        sources, errors = formal.collect_sources(formal.inventory(docs, bib), metadata, tmp_path, tmp_path / "evidence", client)
    assert sources == [] and errors


def test_rebinding_aggregate_evidence_cannot_change_what_model_read(tmp_path, monkeypatch):
    metadata, binding, result = run_fixture(tmp_path, monkeypatch)
    source = next(s for s in result["sources"] if s["kind"] == "primary_text")
    # Keep exact old quoted fragment but change other bytes and self-consistent
    # aggregate hashes. The immutable role prompt still contains the old source.
    source["text"] += " Additional unreviewed claim."
    for field in ("body", "text"):
        path = tmp_path / source[field + "_path"]
        path.write_text(source["text"])
        source[field + "_sha256"] = formal.sha(path.read_bytes())
    path = tmp_path / binding["path"]
    path.write_text(json.dumps(result)); binding["sha256"] = formal.sha(path.read_bytes())
    assert any("exact bound" in error for error in formal.validate_binding(binding, metadata, tmp_path, ROLE))


def test_malformed_historical_referee_record_refuses_without_crashing(tmp_path, monkeypatch):
    config = {"process": flow.PROCESS, "roles": {"editor": ROLE}, "referee_roles": ["referee_b"],
              "rejection_clearance_required": True}
    monkeypatch.setattr(flow, "review_config", lambda *args: config)
    record = {"editor_screen": {"decision": "send_to_review"}, "referee_reports": {"referee_b": {}},
        "merged": {"outcome": "ready"}, "target_journal": "J", "prior_decisions": [],
        "fingerprints": {"manuscript_snapshot_sha256": "a" * 64}, "review_policy_sha256": flow.review_policy_sha256(config)}
    path = tmp_path / "decision.json"; path.write_text(json.dumps(record))
    metadata = {"target_journal": "J", "writing_release": {"review_process": flow.PROCESS,
        "decision_record": path.name, "decision_record_sha256": formal.sha(path.read_bytes())}}
    problems = flow.validate_unified_release("p", metadata, tmp_path, "a" * 64)
    assert any("malformed" in p for p in problems)


def test_multicite_cannot_hide_second_reference():
    with pytest.raises(ValueError, match="Multiple-argument"):
        formal.inventory([{"id": "main", "text": r"\parencites{a}{missing}"}], r"\bibitem{a}Work A.")


def test_ensuremath_formulas_are_in_inventory():
    inv = formal.inventory([{"id": "main", "text": r"Use \ensuremath{x^{2}+{y}}."}], "")
    assert inv["passages"][0]["formulas"][0]["text"] == r"\ensuremath{x^{2}+{y}}"


def test_doi_redirect_cannot_change_requested_identity(tmp_path):
    metadata = fixture_workspace(tmp_path); metadata.pop("formal_check")
    def handler(request):
        if request.url.path.endswith("/example"):
            return httpx.Response(302, headers={"Location": "https://api.crossref.org/works/10.1234/other"})
        return httpx.Response(200, json={"message": {"DOI": "10.1234/other", "title": ["Other"], "author": [{"family": "Else"}]}})
    docs, bib = formal.current_inputs(metadata, tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        sources, errors = formal.collect_sources(formal.inventory(docs, bib), metadata, tmp_path, tmp_path / "evidence", client)
    assert sources == [] and errors


def test_formula_cannot_use_metadata_as_proof(tmp_path, monkeypatch):
    metadata, binding, result = run_fixture(tmp_path, monkeypatch)
    source = next(s for s in result["sources"] if s["kind"] == "bibliographic_metadata")
    formula = next(f for p in result["report"]["passages"] for f in p["formulas"])
    formula["evidence"] = [{"source_id": source["id"], "locator": "JSON metadata", "quote": source["text"]}]
    assert any("Evidence type" in b for b in formal.report_blockers(result["report"], result["inventory"], result["sources"]))


def test_implicit_dependency_routing_preserves_actual_text():
    docs = [{"id": "main", "text": "The named concentration bound applies here."}]
    inv = formal.inventory(docs, r"\bibitem{s}Smith. Exact positivity.")
    source = {"id": "S1", "kind": "primary_text", "reference_keys": ["s"],
              "url": "https://publisher.example/original", "text": PRIMARY,
              "passage_patterns": ["concentration bound"]}
    packet = json.loads(formal.batch_packet("passages", inv["passages"], docs, inv, [source]))
    assert packet["retrieved_sources"] == [source]
    source.pop("passage_patterns")
    packet = json.loads(formal.batch_packet("passages", inv["passages"], docs, inv, [source]))
    assert packet["retrieved_sources"] == []
    assert packet["available_source_catalog"][0]["id"] == "S1"
    assert "text" not in packet["available_source_catalog"][0]


def test_located_internal_reconstruction_without_invented_reference(tmp_path, monkeypatch):
    _, _, result = run_fixture(tmp_path, monkeypatch)
    unit = next(p for p in result["report"]["passages"] if p["prerequisites"])
    row = unit["prerequisites"][0]
    row.update(kind="internal_derivation", reference_keys=[], evidence=[],
               original_locator=unit["passage_id"], formula_check="Multiply the real scalar x by itself; positive and negative signs both give nonnegative product.")
    assert formal.report_blockers(result["report"], result["inventory"], result["sources"]) == []
    row["kind"] = "external"
    assert any("valid cited source" in b for b in formal.report_blockers(result["report"], result["inventory"], result["sources"]))


def test_collect_all_evidence_and_scientific_blockers(tmp_path, monkeypatch):
    _, _, result = run_fixture(tmp_path, monkeypatch)
    result["report"]["references"][0]["evidence"][0]["quote"] = "Invented exact evidence quote."
    unit = next(p for p in result["report"]["passages"] if p["formulas"])
    unit["formulas"][0]["status"] = "error"
    unit["prerequisites"][0]["status"] = "gap"
    blockers = formal.report_blockers(result["report"], result["inventory"], result["sources"])
    assert any("absent from source" in b for b in blockers)
    assert any(b.endswith(": error") for b in blockers)
    assert any(b.endswith(": gap") for b in blockers)


def test_nested_ids_checked_per_batch(tmp_path, monkeypatch):
    _, _, result = run_fixture(tmp_path, monkeypatch)
    batch = result["inventory"]["passages"]
    output = {"references": [], "passages": copy.deepcopy(result["report"]["passages"])}
    unit = next(p for p in output["passages"] if p["formulas"])
    unit["formulas"][0]["formula_id"] += "invented"
    with pytest.raises(ValueError, match="Formulas"):
        formal.batch_coverage(output, "passages", batch)


def test_local_code_is_bound_and_not_external_theorem_evidence(tmp_path, monkeypatch):
    metadata = fixture_workspace(tmp_path)
    code = tmp_path / "papers/p/evidence/replay.py"
    code.parent.mkdir()
    code.write_text("# Actual scientific code establishes implementation only.\nassert 2 * 2 == 4\n")
    metadata["formal_check"]["local_evidence"] = [{"path": code.relative_to(tmp_path).as_posix(),
        "sha256": formal.sha(code.read_bytes()), "kind": "manuscript_code", "passage_patterns": ["For real"]}]
    mock_http(monkeypatch)
    run = tmp_path / "reviews/run"; run.mkdir(parents=True)
    binding = formal.run_checks({"metadata": metadata}, tmp_path, run, ROLE, 1, simulated_runner)
    assert formal.validate_binding(binding, metadata, tmp_path, ROLE) == []
    result = json.loads((tmp_path / binding["path"]).read_text())
    local = next(s for s in result["sources"] if s["kind"] == "manuscript_code")
    unit = next(p for p in result["report"]["passages"] if p["prerequisites"])
    unit["prerequisites"][0]["evidence"] = [{"source_id": local["id"], "locator": "line 1", "quote": "Actual scientific code establishes implementation only."}]
    assert any("original primary text" in b for b in formal.report_blockers(result["report"], result["inventory"], result["sources"]))
    code.write_text("# Changed after review.\nassert 2 * 2 == 4\n")
    assert formal.validate_binding(binding, metadata, tmp_path, ROLE)


@pytest.mark.parametrize("fault", ["wrong_hash", "no_match", "secret", "outside_paper"])
def test_unsafe_or_stale_local_records_refuse(tmp_path, fault):
    metadata = fixture_workspace(tmp_path)
    path = tmp_path / "papers/p/evidence/record.json"
    path.parent.mkdir()
    path.write_text('Scientific actual scope record.' if fault != "secret" else 'Authorization: Bearer PRIVATE')
    item = {"path": path.relative_to(tmp_path).as_posix(), "sha256": formal.sha(path.read_bytes()),
            "kind": "execution_record", "passage_patterns": ["For real"]}
    if fault == "wrong_hash": item["sha256"] = "0" * 64
    if fault == "no_match": item["passage_patterns"] = ["Absent manuscript selector"]
    if fault == "outside_paper": item["path"] = "registry/settings.yaml"
    metadata["formal_check"]["local_evidence"] = [item]
    docs, bib = formal.current_inputs(metadata, tmp_path)
    directory = tmp_path / "evidence"; directory.mkdir()
    with pytest.raises(ValueError):
        formal._local_records(formal.source_plan(metadata), formal.inventory(docs, bib), tmp_path, directory)


def test_bad_actual_nested_ids_are_retained_and_never_rewritten(tmp_path, monkeypatch):
    metadata = fixture_workspace(tmp_path)
    mock_http(monkeypatch)
    run = tmp_path / "review"; run.mkdir()
    def bad(**kwargs):
        output, receipt = simulated_runner(**kwargs)
        if kwargs["role_name"].startswith("formal_passages"):
            unit = next(p for p in output["passages"] if p["formulas"])
            unit["formulas"][0]["formula_id"] += "invented"
            path = kwargs["workdir"] / "output.json"
            path.write_text(json.dumps(output))
            receipt["output_sha256"] = formal.sha(path.read_bytes())
            (kwargs["workdir"] / "receipt.json").write_text(json.dumps(receipt))
        return output, receipt
    binding = formal.run_checks({"metadata": metadata}, tmp_path, run, ROLE, 1, bad)
    assert binding["valid"] is False
    assert any("coverage protocol failure" in b for b in binding["blockers"])
    result = json.loads((tmp_path / binding["path"]).read_text())
    assert any(f["formula_id"].endswith("invented") for p in result["report"]["passages"] for f in p["formulas"])
    assert len(result["receipts"]) == 2


def test_ocr_requires_original_pdf_and_explicit_bounded_pages(tmp_path):
    with pytest.raises(ValueError, match="actual PDF"):
        formal._text_document(b"Not a PDF original.", "text/plain", tmp_path, "scan", method="ocr")
    with pytest.raises(ValueError, match="explicit range"):
        formal._text_document(b"%PDF- actual bytes", "application/pdf", tmp_path, "scan", method="ocr")


def test_short_quote_schema_is_enforced_before_acceptance():
    with pytest.raises(LaunchError, match="string length"):
        formal._validate_against_schema([{"source_id": "S1", "locator": "page 1", "quote": "Define"}], formal.EVIDENCE)


@pytest.mark.parametrize("endpoint", ["https://publisher.example/original.pdf", "https://publisher.example/original"])
def test_http_200_challenge_is_not_primary_text(tmp_path, endpoint):
    metadata = fixture_workspace(tmp_path)
    metadata["formal_check"]["sources"][0]["url"] = endpoint
    docs, bib = formal.current_inputs(metadata, tmp_path)
    def handler(request):
        if request.url.host == "publisher.example":
            return httpx.Response(200, text='<html><title>Client Challenge</title>Enable JavaScript</html>',
                                  headers={"Content-Type": "text/html"})
        return transport(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sources, errors = formal.collect_sources(formal.inventory(docs,bib), metadata,tmp_path,tmp_path/'evidence',client)
    assert errors == [] and all(s["kind"] != "primary_text" for s in sources)
    assert "Declared primary source unavailable" in (tmp_path / "evidence/retrieval-failures.json").read_text()


def test_metadata_suffices_without_original_document(tmp_path, monkeypatch):
    metadata = fixture_workspace(tmp_path)
    mock_http(monkeypatch, lambda request: transport(request) if request.url.host == "api.crossref.org" else httpx.Response(403))
    run = tmp_path / "review"; run.mkdir()
    def metadata_runner(**kwargs):
        packet = json.loads(kwargs["user_prompt"])
        output = simulated_output(packet)
        if packet["scope"] == "references":
            source = next(s for s in packet["retrieved_sources"] if s["kind"] == "bibliographic_metadata")
            for row in output["references"]:
                row["evidence"] = [{"source_id": source["id"], "locator": "message.title", "quote": "Exact positivity"}]
        return output, {}
    binding = formal.run_checks({"metadata": metadata}, tmp_path, run, ROLE, 1, metadata_runner)
    assert binding["valid"] is True
    result = json.loads((tmp_path / binding["path"]).read_text())
    assert all(s["kind"] == "bibliographic_metadata" for s in result["sources"])
    assert "Declared primary source unavailable" in (run / "formal-check/evidence/retrieval-failures.json").read_text()


def test_actual_v2_support_receipt_preserves_bibliographic_data_without_private_links(tmp_path, monkeypatch):
    from paper_writing import support_citations
    metadata = fixture_workspace(tmp_path); metadata.pop("formal_check")
    receipt = tmp_path / "papers/p/production/draft.json"; receipt.parent.mkdir()
    receipt.write_text(json.dumps({"schema_version": "ara.paper_writing.zenodo_draft.v2", "paper_id": "p",
        "paper_version": "1.0", "deposition_id": 1234, "reserved_version_doi": "10.5281/zenodo.1234",
        "submitted_metadata": {"title": "Exact current scientific support", "version": "1.0", "creators": [{"name": "Smith"}]},
        "verified_remote_metadata": {"title": "Exact current scientific support", "version": "1.0"},
        "upload_url": "https://storage.example/private?sig=dummy", "links": {"edit": "DUMMY_PRIVATE_EDIT"}}))
    metadata["support"] = {"publication": {"status": "draft", "bibliography_key": "s", "draft_receipt": receipt.relative_to(tmp_path).as_posix()}}
    monkeypatch.setattr(support_citations, "audit_manuscript_support", lambda *args, **kwargs: {"valid": True})
    docs, bib = formal.current_inputs(metadata, tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        sources, errors = formal.collect_sources(formal.inventory(docs, bib), metadata, tmp_path, tmp_path / "evidence", client)
    assert errors == []
    source = next(s for s in sources if s["kind"] == "current_support_draft")
    assert "Exact current scientific support" in source["text"] and "10.5281/zenodo.1234" in source["text"]
    assert "DUMMY_PRIVATE_EDIT" not in source["text"] and "sig=dummy" not in source["text"]
    assert source["body_sha256"] == formal.sha(receipt.read_bytes())


@pytest.mark.parametrize("suffix", ["\n", "\n   ", "\t", ""])
def test_trailing_single_newline_does_not_omit_final_formulas_or_citations(suffix):
    text = "Opening.\n\n" + r"\begin{table}Final $z=1$ \cite{s}.\end{table} AI declaration." + suffix
    inv = formal.inventory([{"id": "main", "text": text}], r"\bibitem{s}Smith. Work.")
    assert len(inv["passages"]) == 2
    assert inv["passages"][-1]["text"].endswith("AI declaration.")
    assert len(inv["passages"][-1]["formulas"]) == len(inv["passages"][-1]["citations"]) == 1


def test_arbitrary_internal_proof_locator_and_author_facts_for_external_citation_refuse(tmp_path, monkeypatch):
    _, _, result = run_fixture(tmp_path, monkeypatch)
    unit = next(p for p in result["report"]["passages"] if p["prerequisites"])
    row = unit["prerequisites"][0]
    row.update(kind="internal_derivation", reference_keys=[], evidence=[], original_locator="No such proof anywhere")
    assert any("actual manuscript passage" in b for b in formal.report_blockers(result["report"], result["inventory"], result["sources"]))
    row["original_locator"] = unit["passage_id"]
    source = next(s for s in result["sources"] if s["kind"] == "primary_text")
    source["kind"] = "author_attestation"
    assert any("Evidence type" in b for b in formal.report_blockers(result["report"], result["inventory"], result["sources"]))


@pytest.mark.parametrize("query", ["X-Amz-Signature=dummy", "X-Amz-Credential=dummy", "X-Goog-Signature=dummy", "sig=dummy"])
def test_signed_urls_excluded_from_local_model_records(tmp_path, query):
    metadata = fixture_workspace(tmp_path)
    path = tmp_path / "papers/p/evidence/record.txt"; path.parent.mkdir()
    path.write_text("https://storage.example/item?" + query)
    plan = {"local_evidence": [{"path": path.relative_to(tmp_path).as_posix(), "sha256": formal.sha(path.read_bytes()),
        "kind": "research_record", "passage_patterns": ["For real"]}]}
    docs, bib = formal.current_inputs(metadata, tmp_path)
    with pytest.raises(ValueError, match="private service"):
        formal._local_records(plan, formal.inventory(docs, bib), tmp_path, tmp_path)
