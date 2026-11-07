from __future__ import annotations

from paper_writing.editorial_voice import editorial_voice_issues, editorial_voice_metrics

PLAIN = " ".join(["The cohort analysis shows a stable association between exposure and outcome."] * 60)


def test_plain_text_has_no_voice_issues() -> None:
    metrics, issues = editorial_voice_issues(PLAIN)
    assert metrics["words"] > 500 and issues == []


def test_hedge_internal_and_stock_phrasing_are_flagged() -> None:
    noisy = PLAIN + " " + " ".join([
        "We do not claim generality.", "This does not establish causality.", "We caution readers.",
        "The frozen panel receipt and SHA-256 manifest were checked.", "We delve into the intricate tapestry.",
    ] * 4)
    _, issues = editorial_voice_issues(noisy)
    codes = {issue["code"] for issue in issues}
    assert {"VOICE-HEDGE-DENSITY", "VOICE-INTERNAL-VOCABULARY", "VOICE-STOCK-PHRASING"} <= codes


def test_data_availability_section_is_excluded() -> None:
    text = PLAIN + "\n\\section{Data availability}\n" + "SHA-256 checksums and manifests. " * 40
    assert editorial_voice_metrics(text)["internal_terms"] == 0


def test_long_abstract_is_flagged() -> None:
    text = "\\begin{abstract}" + "word " * 320 + "\\end{abstract}" + PLAIN
    _, issues = editorial_voice_issues(text)
    assert any(issue["code"] == "VOICE-ABSTRACT-LENGTH" for issue in issues)
