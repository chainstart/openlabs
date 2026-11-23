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
    metadata = {"authors": [{"name": "A. Person", "affiliation_ids": ["u"]}],
                "affiliations": [{"id": "u", "name": "Test University"}],
                "narrative_limits": {"min_body_words": 30}, "declarations": {"ai_use": {"model_usage": [{
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


def test_registry_byline_is_part_of_the_floor(tmp_path):
    """TIC 236779149 v0.1.2: byline in main.tex, none in the registry -> site showed no authors."""
    manuscript = tmp_path / "papers/p/manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text(r"""
\author*[1]{\fnm{Zhipeng} \sur{Chen}}\email{c@example.org}
\author[1]{\fnm{Qisheng} \sur{Wang}}
\affil*[1]{\orgname{Test University}}
\begin{document}Known short content.\end{document}""")
    metadata = {"narrative_limits": {"min_body_words": 1}}
    codes = {i["code"] for i in delivery_floor.check("p", metadata, tmp_path, author=True)["issues"]}
    assert "REGISTRY-AUTHORS-MISSING" in codes
    assert not {"BYLINE-MISSING", "AFFILIATION-MISSING"} & codes
    metadata["authors"] = [{"name": "Zhipeng Chen", "affiliation_ids": ["u"]},
                           {"name": "Qisheng Wang", "affiliation_ids": ["u"]}]
    codes = {i["code"] for i in delivery_floor.check("p", metadata, tmp_path, author=True)["issues"]}
    assert "REGISTRY-AFFILIATIONS-MISSING" in codes and "REGISTRY-AUTHORS-MISSING" not in codes
    metadata["affiliations"] = [{"id": "u", "name": "Test University"}]
    codes = {i["code"] for i in delivery_floor.check("p", metadata, tmp_path, author=True)["issues"]}
    assert not {c for c in codes if c.startswith("REGISTRY-") or c == "BYLINE-REGISTRY-MISMATCH"}
    # The canonical people mapping counts too; a registered author absent from main.tex does not.
    metadata["authors"] = {"names": ["Zhipeng Chen", "Jingyi Zhan"], "people": [
        {"name": "Zhipeng Chen", "affiliation_ids": ["u"]}, {"name": "Jingyi Zhan", "affiliation_ids": ["u"]}]}
    issues = delivery_floor.check("p", metadata, tmp_path, author=True)["issues"]
    mismatch = [i for i in issues if i["code"] == "BYLINE-REGISTRY-MISMATCH"]
    assert mismatch and "Jingyi Zhan" in mismatch[0]["message"] and "Zhipeng" not in mismatch[0]["message"]


def test_registry_byline_tolerates_tex_accents():
    issues = delivery_floor.registry_byline_issues(
        {"authors": [{"name": "Jörg Müller", "affiliation_ids": ["u"]}],
         "affiliations": [{"id": "u", "name": "U"}]}, r"\fnm{J\"org} \sur{M\"{u}ller}")
    assert issues == []
