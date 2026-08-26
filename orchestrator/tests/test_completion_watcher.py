from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_result_path_unit_triggers_atomic_receipt_ingestion() -> None:
    unit = (ROOT / "deploy/systemd/openlabs-results.path").read_text(encoding="utf-8")
    assert "PathExistsGlob=%h/work/projects/openlabs/openlabs-data/inbox/results/*.json" in unit
    assert "Unit=openlabs-tick.service" in unit
    assert "WantedBy=default.target" in unit


def test_completion_watcher_is_independent_of_factory_timer() -> None:
    installer = (ROOT / "bin/install-completion-watcher").read_text(encoding="utf-8")
    assert "enable --now openlabs-results.path" in installer
    assert "openlabs-factory.target" not in installer
    assert "openlabs-tick.timer" not in installer
