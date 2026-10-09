import hashlib

import pytest

from paper_writing.declarations import check_record, normalized, render_contributions, section


def test_bibliography_size_commands_are_not_declaration_prose():
    source = (r"\section*{AI-use disclosure}" + "\nActual disclosure.\n"
              + r"\begingroup" + "\n" + r"\small" + "\n"
              + r"\bibliographystyle{plainnat}\bibliography{references}\endgroup")
    assert section(source, "ai_use")[1] == "Actual disclosure."
    with_extra_prose = source.replace(r"\bibliographystyle", "Additional disclosure.\n"
                                     + r"\bibliographystyle")
    assert "Additional disclosure." in section(with_extra_prose, "ai_use")[1]


def test_inline_thebibliography_is_not_part_of_ai_disclosure():
    source = (r'\section*{AI-use disclosure}' + '\nActual disclosure.\n'
              + r'\begin{thebibliography}{9}' + '\n'
              + r'\bibitem{prior}Prior research.\end{thebibliography}\end{document}')
    assert section(source, 'ai_use')[1] == 'Actual disclosure.'


def bound(heading, text, **extra):
    return dict(heading_latex=heading, text_latex=text,
                text_sha256=hashlib.sha256(normalized(text).encode()).hexdigest(), **extra)


def sample():
    contribution = bound(r"\section*{Author contributions}", "Alice: Software. Bob: Supervision.")
    ai = bound(r"\section*{Generative AI declaration}", "The authors used Codex for editing.")
    metadata = {"authors": [{"name": "Alice", "credit_roles": ["Software"]}, {"name": "Bob", "credit_roles": ["Supervision"]}],
                "declarations": {"author_contributions": contribution, "ai_use": ai}}
    tex = "\n".join([contribution["heading_latex"], contribution["text_latex"], ai["heading_latex"], ai["text_latex"], r"\sloppy", r"\bibliography{references}"])
    return metadata, tex


def test_metadata_matches_and_layout_is_not_disclosure():
    metadata, tex = sample()
    assert check_record(metadata, tex)["valid"]
    assert "sloppy" not in section(tex, "ai_use")[1]


def test_nocite_is_not_disclosure_and_does_not_hide_later_prose():
    metadata, tex = sample()
    tex = tex.replace(r"\sloppy", r"\nocite{*}")
    assert check_record(metadata, tex)["valid"]
    assert not check_record(metadata, tex.replace(r"\nocite{*}",
                                                 r"\nocite{*} Extra claim."))["valid"]


def test_partial_author_statement_rejected():
    metadata, tex = sample()
    tex = tex.replace("Alice: Software. ", "")
    assert not check_record(metadata, tex)["valid"]


def test_optional_omission_requires_source():
    metadata, tex = sample()
    metadata["declarations"]["author_contributions"] = bound("", "", include_in_manuscript=False, requirement="recommended", requirement_sources=["https://journals.aps.org/authors/editorial-policies"])
    tex = tex[tex.index(r"\section*{Generative"):]
    assert check_record(metadata, tex)["valid"]
    metadata["declarations"]["author_contributions"]["requirement_sources"] = []
    assert not check_record(metadata, tex)["valid"]


def test_render_requires_roles_and_follows_byline():
    with pytest.raises(ValueError, match="Missing explicit"):
        render_contributions([{"name": "Alice"}])
    assert render_contributions([{"name": "Bob", "credit_roles": ["Software"]}, {"name": "Alice", "credit_roles": ["Methodology"]}]).splitlines()[0] == "Bob: Software."


def test_duplicate_section_rejected():
    _, tex = sample()
    with pytest.raises(ValueError, match="Duplicate"):
        section(tex + "\n\\section*{Author contributions}\nAlice.", "author_contributions")


def test_text_drift_and_hash_drift_rejected():
    metadata, tex = sample()
    assert not check_record(metadata, tex.replace("Codex", "Other tool"))["valid"]
    metadata["declarations"]["ai_use"]["text_sha256"] = "wrong"
    assert not check_record(metadata, tex)["valid"]


def test_role_drift_rejected_even_with_matching_statement_hash():
    metadata, tex = sample()
    metadata["authors"][0]["credit_roles"] = ["Methodology"]
    assert not check_record(metadata, tex)["valid"]


def test_invalid_or_duplicate_roles_rejected():
    for roles in (["Reviewer"], ["Software", "Software"]):
        with pytest.raises(ValueError, match="Invalid or duplicate"):
            render_contributions([{"name": "Alice", "credit_roles": roles}])


def test_gpt6_is_not_blacklisted_in_a_truthful_bound_declaration():
    metadata, tex = sample()
    old = metadata["declarations"]["ai_use"]["text_latex"]
    text = "The authors used OpenAI Codex with gpt-6-astra for editing."
    metadata["declarations"]["ai_use"] = bound(r"\section*{Generative AI declaration}", text)
    assert check_record(metadata, tex.replace(old, text))["valid"]


def test_explicit_unrecorded_model_blocks_declaration():
    metadata, tex = sample()
    metadata["declarations"]["ai_use"]["model_usage"] = []
    assert not check_record(metadata, tex)["valid"]


def test_explicit_family_description_requires_disclosed_evidenced_variant(tmp_path):
    import json
    from paper_writing.ai_disclosure import model_disclosure_issues
    runtime=tmp_path/'runtime.json'
    runtime.write_text(json.dumps({'model':'gpt-5.6-sol'}))
    usage=[{'provider':'openai-codex','tool':'Codex','model':'gpt-5.6-sol',
            'purpose':'Historical internal review only','evidence':{
                'path':'runtime.json','sha256':hashlib.sha256(runtime.read_bytes()).hexdigest(),
                'json_pointer':'/model'}}]
    text='Earlier author assistance used the GPT-5.6 family (exact variant unverified). An internal review used gpt-5.6-sol.'
    assert not model_disclosure_issues(text,usage,root=tmp_path)
    assert any(k=='MODEL-UNREGISTERED' for k,_ in model_disclosure_issues(
        text.replace('GPT-5.6 family','GPT-5.6'),usage,root=tmp_path))
    assert any(k=='MODEL-MISMATCH' for k,_ in model_disclosure_issues(
        'GPT-5.6 family only.',usage,root=tmp_path))
    assert any(k=='MODEL-UNREGISTERED' for k,_ in model_disclosure_issues(
        text+' GPT-6 family also.',usage,root=tmp_path))
@pytest.mark.parametrize('name', ['references', 'references.tex'])
def test_final_reference_include_is_not_declaration_prose(name):
    from paper_writing.declarations import section
    source = '\\section*{Generative AI declaration}\nExact disclosure.\n\\input{' + name + '}\n\\end{document}'
    assert section(source, 'ai_use')[1] == 'Exact disclosure.'


def test_reference_include_followed_by_prose_remains_bound():
    from paper_writing.declarations import section
    source = '\\section*{Generative AI declaration}\nExact disclosure.\n\\input{references.tex}\nAdditional disclosure.\n\\end{document}'
    assert 'Additional disclosure.' in section(source, 'ai_use')[1]
    assert '\\input{references.tex}' in section(source, 'ai_use')[1]


def test_arbitrary_final_include_remains_bound():
    from paper_writing.declarations import section
    source = '\\section*{Generative AI declaration}\nExact disclosure.\n\\input{disclosure.tex}\n\\end{document}'
    assert '\\input{disclosure.tex}' in section(source, 'ai_use')[1]



def test_ai_section_stops_before_appendices():
    from paper_writing.declarations import section

    for tail in ("\\input{appendices.tex}\n", "\\appendix\n\\section{Proofs}\nText.\n"):
        source = "\\section*{Generative AI declaration}\nThe authors used X.\n\n" + tail
        assert section(source, "ai_use")[1].strip() == "The authors used X."
