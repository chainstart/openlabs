from pathlib import Path

from paper_writing.manuscript_style import audit_tex_tree


CODE_DECLARATION = r"""
\section*{AI use disclosure}
During the preparation of this work, the authors used OpenAI GPT-5.6 through
Codex to assist with manuscript drafting, editing, technical preparation,
source-code development, and preparation of computational verification scripts.
The authors reviewed and edited all AI-assisted text, inspected AI-assisted code,
and independently executed and validated the stated checks. The authors take full
responsibility for the article and its computational materials. The reported results
are based on verified outputs. Unverified model responses were not used as evidence.
"""


def _write(tmp_path: Path, body: str, declaration: str = CODE_DECLARATION) -> Path:
    path = tmp_path / "main.tex"
    path.write_text(
        "\\documentclass{article}\n"
        "\\author{A. Author\\\\AI Agent Lab}\n"
        "\\begin{document}\n"
        f"{body}\n"
        f"{declaration}\n"
        "\\bibliographystyle{plain}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    return path


def test_style_check_accepts_neutral_body_and_complete_code_disclosure(
    tmp_path: Path,
) -> None:
    main = _write(
        tmp_path,
        "An exact Python verifier checks the finite identities and reports the results.",
    )

    result = audit_tex_tree(main)

    assert result["valid"] is True
    assert result["ai_declaration"] == {
        "present": True,
        "code_assistance_relevant": True,
        "lean_assistance_relevant": False,
    }


def test_style_check_rejects_internal_workflow_and_ai_narration_in_body(
    tmp_path: Path,
) -> None:
    main = _write(
        tmp_path,
        "Our bounded source audit used Codex and produced a reader-facing claim registry.",
    )

    result = audit_tex_tree(main)
    codes = {item["code"] for item in result["errors"]}

    assert "STYLE-INTERNAL-AUDIT" in codes
    assert "STYLE-AI-WORKFLOW-IN-BODY" in codes
    assert "STYLE-READER-FACING" in codes
    assert "STYLE-REPOSITORY-WORKFLOW" in codes


def test_style_check_rejects_unconfirmed_submission_language(tmp_path: Path) -> None:
    main = _write(
        tmp_path,
        "This internal draft is not submission-ready and requires confirmation.",
    )

    result = audit_tex_tree(main)
    codes = {item["code"] for item in result["errors"]}

    assert "STYLE-UNCONFIRMED-SUBMISSION-TEXT" in codes


def test_style_check_rejects_todo_even_in_tex_comment(tmp_path: Path) -> None:
    main = _write(tmp_path, "% TODO(AUTHOR): add the final author list.\nThe result holds.")

    result = audit_tex_tree(main)
    codes = {item["code"] for item in result["errors"]}

    assert "STYLE-UNRESOLVED-MARKER" in codes


def test_style_check_rejects_auditability_and_internal_literal_paths(
    tmp_path: Path,
) -> None:
    main = _write(
        tmp_path,
        r"For auditability, see \path{evidence/claim_evidence_map.md}.",
    )

    result = audit_tex_tree(main)
    codes = {item["code"] for item in result["errors"]}

    assert "STYLE-INTERNAL-AUDIT" in codes
    assert "STYLE-INTERNAL-PATH" in codes


def test_style_check_rejects_workflow_notes_in_bibliography(tmp_path: Path) -> None:
    main = _write(tmp_path, r"The result is classical.\bibliography{references}")
    (tmp_path / "references.bib").write_text(
        "@misc{x,\n  title = {Source},\n"
        "  note = {Version 3.5 used in the audit; accessed 2026-07-24}\n}\n",
        encoding="utf-8",
    )

    result = audit_tex_tree(main)
    codes = {item["code"] for item in result["errors"]}

    assert "STYLE-BIBLIOGRAPHY-WORKFLOW" in codes


def test_style_check_requires_one_final_ai_use_declaration(tmp_path: Path) -> None:
    main = _write(tmp_path, "The argument is elementary.", declaration="")

    result = audit_tex_tree(main)
    codes = {item["code"] for item in result["errors"]}

    assert "STYLE-AI-DECLARATION-MISSING" in codes


def test_style_check_accepts_aadm_unnumbered_ai_use_declaration(tmp_path: Path) -> None:
    declaration = CODE_DECLARATION.replace(
        r"\section*{AI use disclosure}",
        r"\aadmunnumberedsection{AI use disclosure}",
    )
    main = _write(tmp_path, "The argument is elementary.", declaration)

    result = audit_tex_tree(main)

    assert result["valid"] is True


def test_style_check_allows_venue_address_block_after_bibliography(tmp_path: Path) -> None:
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\nThe result is proved.\n"
        f"{CODE_DECLARATION}\n"
        "\\bibliographystyle{plain}\n\\bibliography{references}\n"
        "\\bigskip\n\\noindent A. Author\\\\University address.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    result = audit_tex_tree(main)

    assert result["valid"] is True


def test_style_check_accepts_self_contained_proof_boundary(tmp_path: Path) -> None:
    declaration = r"""
\section*{AI use disclosure}
During the preparation of this work, the authors used OpenAI GPT-5.6 through
Codex to assist with manuscript drafting, editing, technical preparation, and
source-code development. The authors inspected the AI-assisted code and
independently executed the exploratory checks. All results are established by
the self-contained proofs in the manuscript and do not depend on exploratory
computations. The authors take full responsibility for the article.
"""
    main = _write(tmp_path, "The argument is self-contained.", declaration)

    result = audit_tex_tree(main)

    assert result["valid"] is True


def test_style_check_requires_lean_disclosure_and_toolchain_boundary(
    tmp_path: Path,
) -> None:
    main = _write(
        tmp_path,
        "The upper bound was formalized in Lean and checked by the accompanying Lean project.",
    )

    result = audit_tex_tree(main)
    codes = {item["code"] for item in result["errors"]}

    assert "STYLE-AI-DISCLOSURE-LEAN" in codes
    assert "STYLE-AI-DISCLOSURE-LEAN-BOUNDARY" in codes


def test_style_check_accepts_truthful_lean_boundary(tmp_path: Path) -> None:
    declaration = CODE_DECLARATION.replace(
        "preparation of computational verification scripts.",
        "preparation of computational verification scripts, and preparation and checking "
        "of Lean code. Formal-verification claims rely on successful checking by the "
        "pinned Lean toolchain rather than on AI output.",
    )
    main = _write(
        tmp_path,
        "The upper bound was formalized in Lean and checked by the accompanying Lean project.",
        declaration,
    )

    result = audit_tex_tree(main)

    assert result["valid"] is True


def test_style_check_accepts_toolchain_positive_lean_boundary(tmp_path: Path) -> None:
    declaration = CODE_DECLARATION.replace(
        "preparation of computational verification scripts.",
        "preparation of computational verification scripts, and preparation and checking "
        "of Lean code. Formal-verification claims are based on successful checking of the "
        "archived sources by the pinned Lean toolchain.",
    )
    main = _write(
        tmp_path,
        "The upper bound was formalized in Lean and checked by the accompanying Lean project.",
        declaration,
    )

    result = audit_tex_tree(main)

    assert result["valid"] is True
