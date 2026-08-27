from pathlib import Path

from paper_writing.funding import eligible_funding, funding_is_eligible
from paper_writing.manuscript_style import audit_manuscript_style


FUNDING_POLICY = {
    "funder": "National Natural Science Foundation of China",
    "grant_number": "62501380",
    "statement": "Supported by NSFC grant 62501380.",
    "eligibility": {
        "requires_author": {"name": "Yan Feng", "name_zh": "冯岩"},
    },
}


def test_funding_requires_the_registered_author() -> None:
    assert funding_is_eligible(
        FUNDING_POLICY,
        [{"name": "Yan Feng", "name_zh": "冯岩"}],
    )
    assert not funding_is_eligible(
        FUNDING_POLICY,
        [{"name": "Zhipeng Chen", "name_zh": "陈智鹏"}],
    )


def test_funding_inherits_the_local_policy_by_grant_number() -> None:
    declared = [
        {
            "funder": "National Natural Science Foundation of China",
            "grant_number": "62501380",
            "statement": "Supported by NSFC grant 62501380.",
        }
    ]

    assert eligible_funding(
        declared,
        [{"name": "Zhipeng Chen", "name_zh": "陈智鹏"}],
        policies=[FUNDING_POLICY],
    ) == []
    assert eligible_funding(
        declared,
        [{"name": "Yan Feng", "name_zh": "冯岩"}],
        policies=[FUNDING_POLICY],
    ) == declared


def _style_fixture(tmp_path: Path, *, include_required_author: bool) -> str:
    paper_id = "20260824-math-number-funding-policy-test"
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "This work was supported by Grant No.~62501380.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    authors = (
        "  - name: Yan Feng\n    name_zh: 冯岩\n"
        if include_required_author
        else "  - name: Zhipeng Chen\n    name_zh: 陈智鹏\n"
    )
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
created_at: '2026-08-24'
domain: math
subdomain: number
authors:
{authors}manuscript_dir: papers/{paper_id}/manuscript
latest_source: papers/{paper_id}/manuscript/main.tex
""",
        encoding="utf-8",
    )
    (tmp_path / "registry" / "settings.yaml").write_text(
        """schema_version: ara.paper_writing.registry.v1
quality_gate:
  require_ai_use_declaration: false
defaults:
  funding:
    - funder: National Natural Science Foundation of China
      grant_number: '62501380'
      statement: Supported by NSFC grant 62501380.
      eligibility:
        requires_author:
          name: Yan Feng
          name_zh: 冯岩
""",
        encoding="utf-8",
    )
    return paper_id


def test_style_check_blocks_restricted_funding_without_required_author(
    tmp_path: Path,
) -> None:
    paper_id = _style_fixture(tmp_path, include_required_author=False)

    result = audit_manuscript_style(
        paper_id,
        root=tmp_path,
        require_ai_declaration=False,
    )

    assert result["valid"] is False
    assert {item["code"] for item in result["errors"]} == {
        "STYLE-FUNDING-AUTHOR-ELIGIBILITY"
    }


def test_style_check_allows_restricted_funding_with_required_author(
    tmp_path: Path,
) -> None:
    paper_id = _style_fixture(tmp_path, include_required_author=True)

    result = audit_manuscript_style(
        paper_id,
        root=tmp_path,
        require_ai_declaration=False,
    )

    assert result["valid"] is True
