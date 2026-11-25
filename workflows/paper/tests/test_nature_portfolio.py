"""Nature Portfolio rules (2026-11-25): AI-use disclosure section and no generated images."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from paper_writing import declarations, figures
from paper_writing.publisher_family import nature_portfolio, venue_family

DEFAULT = {"heading_latex": r"\section*{Declaration of generative AI and AI-assisted technologies"
                            r" in the manuscript preparation process}",
           "automatically_reusable": True,
           "text_template": "During the preparation of this work, the author(s) used "
                            "[NAME OF TOOL/SERVICE] for [REASON]. The author(s) will review the "
                            "full manuscript before submission and take full responsibility for "
                            "the content of the published article."}
NATURE = {**DEFAULT, "heading_latex": r"\section*{AI use disclosure}"}


def test_family_by_name_and_by_register(tmp_path) -> None:
    for name in ("Nature Communications", "Scientific Reports", "npj Digital Medicine",
                 "Communications Physics", "Nature Astronomy", "nature"):
        assert nature_portfolio(name), name
    for name in ("Applied Energy", "Communications in Mathematical Physics", "Natural Hazards",
                 "Journal of Nature Studies", None, ""):
        assert not nature_portfolio(name), name
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "verified-venues.yaml").write_text(
        "schema_version: openlabs.verified_venues.v1\nvenues:\n"
        "- journal: Nature Energy Letters Fake\n  portfolio: other\n"
        "- journal: Some Partner Journal\n  aliases: [SPJ]\n  portfolio: Nature Portfolio\n",
        encoding="utf-8")
    assert venue_family("SPJ", tmp_path) == "nature_portfolio"
    assert venue_family("Nature Energy Letters Fake", tmp_path) is None


def _paper(tmp_path, monkeypatch, journal: str) -> tuple:
    paper = tmp_path / "papers/test"
    paper.mkdir(parents=True)
    path = paper / "main.tex"
    path.write_text("\\section{Methods}\nWe fitted the model.\n"
                    "\\section*{Data availability}\nOn Zenodo.\n"
                    "\\section*{Generative AI declaration}\nOld.\n\\bibliography{refs}\n")
    registry = tmp_path / "registry/paper-declarations"
    registry.mkdir(parents=True)
    (registry / "templates.yaml").write_text(json.dumps({
        "default_ai_template_id": "default", "venue_ai_templates": {"nature_portfolio": "nature"},
        "ai_templates": {"default": DEFAULT, "nature": NATURE}}))
    receipt = tmp_path / "runtime.json"
    receipt.write_text('{"model":"gpt-6.2-sol"}')
    usage = {"model": "gpt-6.2-sol", "tool": "Codex", "provider": "openai-codex",
             "purpose": "data-analysis code, literature search and writing support",
             "evidence": {"path": "runtime.json", "json_pointer": "/model",
                          "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}}
    metadata = {"latest_source": "papers/test/main.tex", "target_journal": journal,
                "authors": [{"name": "A", "credit_roles": ["Software"]},
                            {"name": "B", "credit_roles": ["Supervision"]}],
                "declarations": {"ai_use": {"model_usage": [usage]}}}
    monkeypatch.setattr(declarations, "load_paper_metadata", lambda *_: metadata)
    return path, metadata


def test_nature_target_gets_an_end_matter_ai_use_disclosure(tmp_path, monkeypatch) -> None:
    path, _ = _paper(tmp_path, monkeypatch, "Nature Communications")
    assert declarations.apply_default_declarations("test", tmp_path)["changed"]
    text = path.read_text()
    heading, body = declarations.section(text, "ai_use")
    assert heading == r"\section*{AI use disclosure}"
    assert body.startswith("During the preparation of this work, the authors used gpt-6.2-sol "
                           "through Codex for data-analysis code, literature search and writing")
    # The end matter, after Data availability and before the references; not in Methods.
    assert text.index("Data availability") < text.index("AI use disclosure") < \
        text.index("\\bibliography")
    methods = text[text.index("\\section{Methods}"):text.index("Data availability")]
    assert "Codex" not in methods
    assert "Generative AI declaration" not in text


def test_other_targets_keep_the_default_heading(tmp_path, monkeypatch) -> None:
    path, _ = _paper(tmp_path, monkeypatch, "Applied Energy")
    assert declarations.apply_default_declarations("test", tmp_path)["changed"]
    assert "Declaration of generative AI and AI-assisted technologies" in path.read_text()


def _workspace(tmp_path, journal: str):
    paper = tmp_path / "papers/p1"
    manuscript = paper / "manuscript"
    (manuscript / "figures").mkdir(parents=True)
    (paper / "figure-sources/figures").mkdir(parents=True)
    image = paper / "figure-sources/figures/concept-genimg.png"
    image.write_bytes(b"\x89PNG fake")
    (paper / "figure-sources/figures/concept-genimg.png.provenance.json").write_text(json.dumps({
        "file": image.name, "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "tool": "OpenAI Codex CLI built-in image generation (image_gen)"}))
    (paper / "figure-sources/compose.py").write_text("art = 'figures/concept-genimg.png'\n")
    ws = figures.workspace(manuscript=manuscript)
    return replace(ws, metadata={"target_journal": journal}, root=tmp_path), paper


def test_generated_images_are_blocked_for_nature_targets_only(tmp_path) -> None:
    ws, paper = _workspace(tmp_path, "Nature Communications")
    found = figures.generated_image_findings(ws)
    assert [item["code"] for item in found] == [figures.NATURE_AI_IMAGE_CODE]
    assert "concept-genimg.png" in found[0]["message"]
    other = replace(ws, metadata={"target_journal": "Applied Energy"})
    assert figures.generated_image_findings(other) == []
    # A generated file nothing uses any more is not a finding (moved out of use).
    (paper / "figure-sources/compose.py").write_text("art = None\n")
    assert figures.generated_image_findings(ws) == []
    # A registered artwork disclosure is generated artwork as well.
    flagged = replace(ws, metadata={"target_journal": "Scientific Reports",
                                    "artwork_disclosures": [{"figure": "figures/art.png"}]})
    assert [item["figure"] for item in figures.generated_image_findings(flagged)] == ["art.png"]


def test_ai_generated_library_asset_blocks_a_nature_target(tmp_path) -> None:
    ws, _paper_dir = _workspace(tmp_path, "Nature Communications")
    assets = ws.manuscript / "figure-src" / "assets"
    assets.mkdir(parents=True)
    (assets / "cell.svg").write_text("<svg/>")
    (assets / "cell.license.json").write_text(json.dumps({
        "source": "x", "license": "CC0 1.0", "attribution": "x", "url": "x", "ai_generated": True}))
    blocking, advisory, _ = figures.license_findings(ws, [], "")
    assert [item["code"] for item in blocking] == [figures.NATURE_AI_IMAGE_CODE]
    blocking, advisory, _ = figures.license_findings(
        replace(ws, metadata={"target_journal": "Energy"}), [], "")
    assert blocking == [] and [item["code"] for item in advisory] == ["FIG-ASSET-AI-GENERATED"]
