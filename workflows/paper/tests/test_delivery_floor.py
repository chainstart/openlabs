import hashlib

from paper_writing import delivery_floor


def test_floor_counts_body_and_distinct_main_figures_and_binds_reader(tmp_path, monkeypatch):
    manuscript = tmp_path / "papers/p/manuscript"
    manuscript.mkdir(parents=True)
    for name in ("design", "result", "appendix"):
        (manuscript / f"{name}.pdf").write_bytes(name.encode())
    main = manuscript / "main.tex"
    main.write_text(r"""
\author[1]{A. Person}
\affil[1]{Test University}
\begin{document}
\maketitle
\section{Methods}
The actual comparison was tested.
\begin{figure}\includegraphics{design}\end{figure}
\begin{figure}\includegraphics{result}\end{figure}
\begin{figure}\includegraphics{result}\end{figure}
\appendix
""" + " long" * 100 + r"""
\begin{figure}\includegraphics{appendix}\end{figure}
\section*{AI use}
The author used gpt-6.2-sol through Codex.
\end{document}""")
    plan = {"manuscript_type": "rank_audit", "figures": [
        {"figure": name, "kind": kind} for name, kind in
        (("design", "schematic"), ("result", "result"), ("appendix", "result"))]}
    monkeypatch.setattr(delivery_floor, "read_plan", lambda path: (plan, None))
    runtime = b'{"actual_runtime_model":"gpt-6.2-sol"}'
    (tmp_path / "runtime.json").write_bytes(runtime)
    digest = hashlib.sha256(runtime).hexdigest()
    metadata = {"narrative_limits": {"min_body_words": 30}, "declarations": {"ai_use": {"model_usage": [{
        "model": "gpt-6.2-sol", "provider": "openai-codex", "tool": "Codex", "purpose": "editing",
        "evidence": {"path": "runtime.json", "sha256": digest, "json_pointer": "/actual_runtime_model"},
    }]}}}
    record = {"delivery_reader": {"supporting_panel": "Figure 2", "image_sha256": ["attached"],
                                   "image_inputs": {f"{name}.pdf": hashlib.sha256(name.encode()).hexdigest()
                                                    for name in ("design", "result")}},
              "receipts": {"delivery_reader": {"independent_context": True, "images": [{"sha256": "attached"}]}}}
    result = delivery_floor.check("p", metadata, tmp_path, record)
    assert result["metrics"]["result"] == 1
    assert result["metrics"]["schematic"] == 1
    assert {i["code"] for i in result["issues"]} == {
        "BODY-BELOW-MINIMUM", "RESULT-FIGURES-BELOW-MINIMUM"}
    (manuscript / "result.pdf").write_bytes(b"changed")
    (tmp_path / "runtime.json").write_bytes(b'{}')
    result = delivery_floor.check("p", metadata, tmp_path, record)
    assert {"FIGURES-NOT-REVIEWED", "AI-USE-UNVERIFIED"} <= {i["code"] for i in result["issues"]}
    assert "FIGURES-NOT-REVIEWED" not in {
        i["code"] for i in delivery_floor.check("p", metadata, tmp_path, author=True)["issues"]}


def test_venue_article_type_minimum_and_empty_byline(tmp_path):
    manuscript = tmp_path / "papers/p/manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text(r"\author{}\begin{document}Known short content.\end{document}")
    venue = tmp_path / "registry/verified-venues.yaml"
    venue.parent.mkdir()
    venue.write_text("""schema_version: openlabs.verified_venues.v1
venues:
- journal: Test Journal
  article_types:
    Research Note:
      min_body_words: 1234
""")
    metadata = {"target_journal": "Test Journal", "target_journal_article_type": "Research Note"}
    result = delivery_floor.check("p", metadata, tmp_path, author=True)
    assert result["metrics"]["min_body_words"] == 1234
    assert {"BYLINE-MISSING", "AFFILIATION-MISSING"} <= {i["code"] for i in result["issues"]}
    metadata["narrative_limits"] = {"min_body_words": 750}
    assert delivery_floor.check("p", metadata, tmp_path, author=True)["metrics"]["min_body_words"] == 750
