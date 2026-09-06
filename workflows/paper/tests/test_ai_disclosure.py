import hashlib
import json

import pytest

from paper_writing.ai_disclosure import model_disclosure_issues, model_usage_for_record
from paper_writing.manuscript_style import audit_tex_tree


def usage(tmp_path, model="gpt-6-astra"):
    raw = json.dumps({"runtime": {"model": model}}).encode()
    (tmp_path / "runtime.json").write_bytes(raw)
    return [{"provider": "openai-codex", "tool": "Codex", "model": model,
             "purpose": "Research assistance",
             "evidence": {"path": "runtime.json", "sha256": hashlib.sha256(raw).hexdigest(),
                          "json_pointer": "/runtime/model"}}]


@pytest.mark.parametrize("ending", [".", ",", ")", "}"])
def test_actual_gpt6_model_matches_hash_bound_runtime(tmp_path, ending):
    assert not model_disclosure_issues("OpenAI Codex used gpt-6-astra" + ending, usage(tmp_path), root=tmp_path)


def test_previous_version_remains_valid_when_actually_recorded(tmp_path):
    assert not model_disclosure_issues("OpenAI GPT-5.6 through Codex.", usage(tmp_path, "gpt-5.6"), root=tmp_path)


def test_do_not_substitute_old_template_model(tmp_path):
    errors = model_disclosure_issues("OpenAI GPT-5.6 through Codex.", usage(tmp_path), root=tmp_path)
    assert {code for code, _ in errors} >= {"MODEL-MISMATCH", "MODEL-UNREGISTERED"}


def test_cannot_drop_runtime_model_suffix(tmp_path):
    errors = model_disclosure_issues("OpenAI GPT-6 through Codex.", usage(tmp_path), root=tmp_path)
    assert "MODEL-MISMATCH" in {code for code, _ in errors}


def test_missing_new_usage_is_a_blocker():
    assert model_disclosure_issues("OpenAI Codex.", [])[0][0] == "MODEL-UNRECORDED"


@pytest.mark.parametrize("metadata", [
    {"created_at": "2026-09-06"},
    {"paper_id": "20260906-math-graph-example"},
    {"created_at": "2026-08-01", "declarations": {"ai_use": {"model_usage": None}}},
])
def test_new_or_explicit_null_records_cannot_downgrade_to_legacy(metadata):
    assert model_usage_for_record(metadata) == []


def test_legacy_record_without_new_field_is_unchanged():
    assert model_usage_for_record({"paper_id": "20260801-math-graph-example"}) is None


def test_structured_evidence_without_root_is_not_verified(tmp_path):
    errors = model_disclosure_issues("OpenAI Codex gpt-6-astra", usage(tmp_path))
    assert "MODEL-EVIDENCE-UNCHECKED" in {code for code, _ in errors}


@pytest.mark.parametrize("failure", ["hash", "model", "pointer", "escape", "missing"])
def test_runtime_provenance_fails_closed(tmp_path, failure):
    records = usage(tmp_path)
    evidence = records[0]["evidence"]
    if failure == "hash":
        evidence["sha256"] = "0" * 64
    elif failure == "model":
        records[0]["model"] = "gpt-5.6"
    elif failure == "pointer":
        evidence["json_pointer"] = "/absent"
    elif failure == "escape":
        evidence["path"] = "../outside.json"
    else:
        evidence["path"] = "missing.json"
    errors = model_disclosure_issues("OpenAI Codex used " + records[0]["model"], records, root=tmp_path)
    assert "MODEL-EVIDENCE-MISMATCH" in {code for code, _ in errors}


def test_version_change_does_not_waive_human_code_validation(tmp_path):
    main = tmp_path / "main.tex"
    main.write_text(r"""\documentclass{article}
\begin{document}
The Python scripts check finite examples.
\section*{Generative AI declaration}
OpenAI Codex, using gpt-6-astra, assisted with manuscript drafting, editing,
technical preparation and source-code development.
The authors take full responsibility for the article.
AI-generated output was not treated as mathematical proof.
\end{document}
""")
    result = audit_tex_tree(main, root=tmp_path, model_usage=usage(tmp_path))
    codes = {item["code"] for item in result["errors"]}
    assert "STYLE-AI-DISCLOSURE-CODE-VALIDATION" in codes
    assert "STYLE-AI-DISCLOSURE-TOOL" not in codes
    assert not any("MODEL" in code for code in codes)


def test_no_provider_or_tool_is_still_rejected(tmp_path):
    main = tmp_path / "main.tex"
    main.write_text(r"""\documentclass{article}
\begin{document}
The theorem has a proof.
\section*{Generative AI declaration}
gpt-6-astra assisted with manuscript drafting, editing, technical preparation.
The authors take full responsibility for the article.
AI-generated output was not treated as mathematical proof.
\end{document}
""")
    result = audit_tex_tree(main, root=tmp_path, model_usage=usage(tmp_path))
    assert "STYLE-AI-DISCLOSURE-TOOL" in {item["code"] for item in result["errors"]}
