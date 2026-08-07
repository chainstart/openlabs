from pathlib import Path

from paper_writing.bundles import validate_result_bundle


ROOT = Path(__file__).resolve().parents[1]


def test_example_bundle_is_valid() -> None:
    result = validate_result_bundle(ROOT / "contracts" / "examples" / "minimal")

    assert result.valid is True
    assert result.checked_artifacts == 1
    assert result.checked_claims == 1


def test_bundle_rejects_path_escape(tmp_path: Path) -> None:
    (tmp_path / "claims.yaml").write_text("claims: []\n", encoding="utf-8")
    (tmp_path / "result_bundle.yaml").write_text(
        """schema_version: ara.result_bundle.v1
bundle_id: unsafe
producer:
  repository: example
  commit: 0123456789abcdef0123456789abcdef01234567
claims_file: claims.yaml
artifacts:
  - id: escaped
    path: ../outside.csv
    sha256: 0000000000000000000000000000000000000000000000000000000000000000
""",
        encoding="utf-8",
    )

    result = validate_result_bundle(tmp_path)

    assert result.valid is False
    assert any("escapes" in error for error in result.errors)
