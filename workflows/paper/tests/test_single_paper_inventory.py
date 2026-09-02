from pathlib import Path
from typing import Any

from paper_writing import inventory
from paper_writing import zenodo


def test_build_inventory_forwards_paper_filter(monkeypatch: Any, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_load_registry(root: Path, *, paper_ids: Any = None) -> dict[str, Any]:
        captured["root"] = root
        captured["paper_ids"] = paper_ids
        return {"papers": {}}

    monkeypatch.setattr(inventory, "load_registry", fake_load_registry)
    result = inventory.build_inventory(
        tmp_path,
        config={},
        paper_ids=["20260901-math-combinatorics-random-mst-effective-errors"],
    )

    assert result["papers"] == []
    assert captured["root"] == tmp_path.resolve()
    assert captured["paper_ids"] == [
        "20260901-math-combinatorics-random-mst-effective-errors"
    ]


def test_find_paper_record_requests_only_target(monkeypatch: Any, tmp_path: Path) -> None:
    paper_id = "20260901-math-combinatorics-random-mst-effective-errors"
    captured: dict[str, Any] = {}

    monkeypatch.setattr(zenodo, "load_config", lambda _: {})

    def fake_build_inventory(
        root: Path,
        *,
        config: Any = None,
        paper_ids: Any = None,
    ) -> dict[str, Any]:
        captured["paper_ids"] = paper_ids
        return {"papers": [{"id": paper_id}]}

    monkeypatch.setattr(zenodo, "build_inventory", fake_build_inventory)

    assert zenodo.find_paper_record(paper_id, repo_root=tmp_path)["id"] == paper_id
    assert captured["paper_ids"] == [paper_id]
