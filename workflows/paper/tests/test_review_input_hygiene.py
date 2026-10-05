import subprocess
import sys
import zipfile
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "skills"
    / "openlabs-paper-review"
    / "scripts"
    / "check_input_hygiene.py"
)


def _zip(path: Path, members: dict[str, bytes | str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in members.items():
            archive.writestr(name, value.encode("utf-8") if isinstance(value, str) else value)


def test_review_input_hygiene_rejects_nested_publishability_projection(tmp_path: Path) -> None:
    nested = tmp_path / "nested.zip"
    _zip(nested, {"THEOREM_DRAFT.md": "This is potentially publishable content.\n"})
    outer = tmp_path / "outer.zip"
    _zip(outer, {"evidence/nested.zip": nested.read_bytes()})

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--archive", str(outer), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "REVIEW-INPUT-EVALUATION-PROJECTION" in result.stdout
    assert "publishability" in result.stdout


def test_review_input_hygiene_allows_deterministic_replay_status(tmp_path: Path) -> None:
    archive = tmp_path / "support.zip"
    _zip(
        archive,
        {
            "README.md": "Exact replay instructions.\n",
            "result.txt": "PASS|tests=48|claims=20\n",
        },
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--archive", str(archive)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Review input hygiene: valid" in result.stdout


def test_event_filter_disclaimer_does_not_hide_a_prior_review(tmp_path: Path) -> None:
    archive = tmp_path / "domain.zip"
    disclaimer = "frozen fingerprints. No quality gate or event classification is inferred.\n"
    _zip(archive, {"source.py": disclaimer})
    clean = subprocess.run(
        [sys.executable, str(SCRIPT), "--archive", str(archive), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert clean.returncode == 0
    _zip(archive, {"source.py": disclaimer + 'writing_release = "ready"\noverall = 7\n'})
    contaminated = subprocess.run(
        [sys.executable, str(SCRIPT), "--archive", str(archive), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert contaminated.returncode == 1
    assert "writing_release" in contaminated.stdout
    assert "review_score" in contaminated.stdout
