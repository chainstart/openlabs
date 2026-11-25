"""Per-line data capability catalogues reach scouts, admission and owners (2026-11-25)."""

from __future__ import annotations

from pathlib import Path

import pytest

from openlabs.data_catalog import (
    SCHEMA,
    catalog_summary,
    load_catalog,
    main,
    validate_catalog,
)
from openlabs.research_lines import line_resources, line_summary

REAL_CATALOGUES = Path("/workspace/openlabs/openlabs-data/registry/data-catalog")

CATALOGUE = f"""
schema_version: {SCHEMA}
line: demo-line
updated_at: '2026-11-25'
sources:
  - id: ztf-dr24
    name: ZTF DR24 light curves
    status: onboarded
    summary: g/r/i light curves 2018-2025 by cone through the IRSA API
    access: {{kind: query_api, endpoints: [https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves]}}
    licence: public, cite Masci+2019
    tool: labs/physics/tools/astro_open_data.py ztf-sample
    sample: {{path: /workspace/x/ztf.csv, check: columns oid mjd mag magerr filtercode}}
    source_selection: {{chosen: https://irsa.ipac.caltech.edu, route: clash-query}}
  - id: atlas-forced
    name: ATLAS forced photometry
    status: needs_registration
    summary: c/o photometry since 2015 at any position
    access: {{kind: query_api}}
    licence: free with account
    registration: account + API token (REGISTER-LIST.md)
  - id: tess-ffi
    name: TESS FFI
    status: catalogued
    summary: full-frame images from the open AWS bucket
    access: {{kind: bucket}}
    licence: public domain
    large: true
    offpeak_rule: whole sectors only Beijing 02:00-14:00 when proxy-bound
"""


def _write(tmp_path: Path, text: str = CATALOGUE) -> Path:
    path = tmp_path / "demo-line.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_catalogue_has_no_problems(tmp_path):
    assert validate_catalog(load_catalog(_write(tmp_path))) == []
    assert main([str(_write(tmp_path))]) == 0


def test_schema_problems_are_named(tmp_path):
    document = load_catalog(_write(tmp_path))
    broken = dict(document)
    sources = [dict(item) for item in document["sources"]]
    sources[0].pop("sample")                      # onboarded without a sample
    sources[1].pop("registration")                # needs_registration without what to register
    sources[2].pop("offpeak_rule")                # large without the off-peak rule
    sources.append(dict(sources[2]))              # duplicate id
    sources.append({"id": "x", "name": "X", "summary": "s", "licence": "l",
                    "status": "maybe", "access": {"kind": "ftp"}})
    broken["sources"] = sources
    problems = "\n".join(validate_catalog(broken))
    assert "ztf-dr24: an onboarded source records sample.path" in problems
    assert "atlas-forced: needs_registration names what to register" in problems
    assert "tess-ffi: large sources state offpeak_rule" in problems
    assert "duplicate id" in problems
    assert "status must be one of" in problems and "access.kind must be one of" in problems
    assert validate_catalog({"schema_version": "v0", "line": "", "sources": []})[:2] == [
        f"schema_version must be {SCHEMA}", "line is required"]


def test_summary_is_compact_and_reports_unreadable_files(tmp_path):
    summary = catalog_summary(str(_write(tmp_path)))
    assert summary["counts"] == {"onboarded": 1, "needs_registration": 1, "catalogued": 1}
    first = summary["sources"][0]
    assert first == {"id": "ztf-dr24", "status": "onboarded", "name": "ZTF DR24 light curves",
                     "summary": "g/r/i light curves 2018-2025 by cone through the IRSA API",
                     "tool": "labs/physics/tools/astro_open_data.py ztf-sample"}
    assert summary["sources"][2]["large"] is True
    assert "sample" not in first and "licence" not in first   # full entries stay in the file
    assert catalog_summary(None) is None and catalog_summary("  ") is None
    missing = catalog_summary(str(tmp_path / "nope.yaml"))
    assert missing["path"].endswith("nope.yaml") and "missing" in missing["error"]
    long = CATALOGUE.replace("g/r/i light curves 2018-2025 by cone through the IRSA API",
                             "word " * 100)
    clipped = catalog_summary(str(_write(tmp_path, long)))["sources"][0]["summary"]
    assert len(clipped) == 160 and clipped.endswith("…")


def test_line_summary_and_owner_resources_carry_the_catalogue(tmp_path):
    path = _write(tmp_path)
    document = {"lines": [{"id": "demo-line", "title": "Demo", "host_domain": "physics",
                           "environment": {"status": "ready", "data": "/workspace/x/data",
                                           "data_catalog": str(path)}},
                          {"id": "plain", "environment": {"status": "ready"}}]}
    summary = line_summary(document, "demo-line")
    assert summary["data_catalog"]["path"] == str(path)
    assert [s["id"] for s in summary["data_catalog"]["sources"]] == [
        "ztf-dr24", "atlas-forced", "tess-ffi"]
    assert "data_catalog" not in line_summary(document, "plain")
    resources = line_resources(document["lines"][0])
    assert resources["data_catalog"] == str(path) and resources["data"] == "/workspace/x/data"
    assert "data_catalog" not in line_resources(document["lines"][1])


@pytest.mark.skipif(not REAL_CATALOGUES.is_dir(), reason="data repository not checked out")
def test_committed_catalogues_are_valid():
    files = sorted(REAL_CATALOGUES.glob("*.yaml"))
    assert files
    for path in files:
        assert validate_catalog(load_catalog(path)) == [], path
