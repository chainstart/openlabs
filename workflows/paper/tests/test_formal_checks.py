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
    with pytest.raises(ValueError, match="original primary text"):
        formal.report_blockers(result["report"], result["inventory"], result["sources"])
