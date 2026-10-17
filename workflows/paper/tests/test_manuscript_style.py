from pathlib import Path
import hashlib
import json

import pytest

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


def _artwork_fixture(tmp_path):
    figure = tmp_path / 'figures/flow.png'
    figure.parent.mkdir()
    figure.write_bytes(b'illustration fixture')
    digest = hashlib.sha256(figure.read_bytes()).hexdigest()
    source = tmp_path / 'generation.json'
    source.write_text(json.dumps({'purpose': 'explanatory_schematic', 'figure_sha256': digest,
                                  'tool': 'OpenAI Codex image service', 'model': None}))
    credit = 'Artwork disclosure: OpenAI Codex image service produced this explanatory schematic; the image-model version was not reported.'
    entry = {'figure': 'figures/flow.png', 'sha256': digest, 'caption_text': credit,
             'requirement_source': 'https://publisher.example/artwork-policy',
             'evidence': {'path': 'generation.json', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}}
    body = '\\begin{figure}\n\\includegraphics{figures/flow.png}\n\\caption{Study design. ' + credit + '}\n\\end{figure}'
    return entry, credit, body


def test_source_bound_publisher_image_credit_preserves_single_final_declaration(tmp_path):
    entry, credit, body = _artwork_fixture(tmp_path)
    main = _write(tmp_path, body)
    assert not audit_tex_tree(main)['valid']  # No blanket caption exemption.
    assert audit_tex_tree(main, artwork_disclosures=[entry])['valid']
    main = _write(tmp_path, body, declaration='')
    assert not audit_tex_tree(main, artwork_disclosures=[entry])['valid']


@pytest.mark.parametrize('fault', ['image_hash', 'evidence_hash', 'body_location', 'extra_narration', 'missing_model_boundary'])
def test_artwork_credit_cannot_hide_body_narration_or_unbound_images(tmp_path, fault):
    entry, credit, body = _artwork_fixture(tmp_path)
    if fault == 'image_hash':
        (tmp_path / 'figures/flow.png').write_bytes(b'changed artwork')
    elif fault == 'evidence_hash':
        (tmp_path / 'generation.json').write_text('{}')
    elif fault == 'body_location':
        body = credit + '\nAn ordinary scientific paragraph.'
    elif fault == 'extra_narration':
        body = body.replace('Study design.', 'Study design. Codex also wrote the paper.')
    else:
        body = body.replace('the image-model version was not reported.', 'a clear image.')
        entry['caption_text'] = entry['caption_text'].replace('the image-model version was not reported.', 'a clear image.')
    main = _write(tmp_path, body)
    assert not audit_tex_tree(main, artwork_disclosures=[entry])['valid']


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


def test_mathematical_gap_does_not_require_code_validation(tmp_path: Path) -> None:
    main = _write(tmp_path, r"The density gap is positive. \begin{equation}\label{eq:gap}1>0\end{equation}")
    result = audit_tex_tree(main)
    assert result["valid"] is True
    assert result["ai_declaration"]["code_assistance_relevant"] is False


def test_gap_software_still_requires_code_validation(tmp_path: Path) -> None:
    disclosure = CODE_DECLARATION.replace("inspected AI-assisted code,\nand independently executed and validated the stated checks", "checked the mathematical argument")
    main = _write(tmp_path, "We used GAP to verify the group computations.", disclosure)
    result = audit_tex_tree(main)
    assert result["ai_declaration"]["code_assistance_relevant"] is True
    assert "STYLE-AI-DISCLOSURE-CODE-VALIDATION" in {e["code"] for e in result["errors"]}


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


def test_cited_models_in_wrapped_prior_work_are_scientific_subjects(tmp_path: Path) -> None:
    main = _write(tmp_path, r"""
Hu et al. study rank sensitivity in LoRA, including GPT-3 on WikiSQL
and GPT-2 after 26,000 training steps \citep{hu2021lora}.
""")
    assert "STYLE-AI-WORKFLOW-IN-BODY" not in {
        e["code"] for e in audit_tex_tree(main)["errors"]}


def test_citation_does_not_hide_author_preparation_narration(tmp_path: Path) -> None:
    main = _write(tmp_path, r"""
We used GPT-5 to draft the classification manuscript \citep{hu2021lora}.
""")
    assert "STYLE-AI-WORKFLOW-IN-BODY" in {
        e["code"] for e in audit_tex_tree(main)["errors"]}


def test_corporate_author_in_included_bibliography_is_not_tool_narration(tmp_path: Path) -> None:
    main = _write(tmp_path, r"The result is in \cite{OpenAI332}.")
    main.write_text(main.read_text().replace(r"\bibliographystyle{plain}", r"\input{references}"))
    (tmp_path / 'references.tex').write_text(r"""
\begin{thebibliography}{9}
\bibitem{OpenAI332}
OpenAI. Metric Markov cotype two of $\ell_1$.
\url{https://github.com/openai/math/tree/123/preprints/example}.
\end{thebibliography}
""")
    assert 'STYLE-AI-WORKFLOW-IN-BODY' not in {
        e['code'] for e in audit_tex_tree(main)['errors']}


def test_bibliography_cannot_hide_preparation_narration(tmp_path: Path) -> None:
    main = _write(tmp_path, r"The result is classical.")
    main.write_text(main.read_text().replace(r"\bibliographystyle{plain}", r"\input{references}"))
    (tmp_path / 'references.tex').write_text(r"""
\begin{thebibliography}{9}
\bibitem{OpenAI332} OpenAI. Codex assisted with proof development.
\end{thebibliography}
""")
    assert 'STYLE-AI-WORKFLOW-IN-BODY' in {
        e['code'] for e in audit_tex_tree(main)['errors']}


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
