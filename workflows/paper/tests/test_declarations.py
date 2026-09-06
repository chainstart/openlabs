import hashlib

import pytest

from paper_writing.declarations import check_record, normalized, render_contributions, section


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
