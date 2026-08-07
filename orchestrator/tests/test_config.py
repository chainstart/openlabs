from __future__ import annotations

from openlabs.config import workspace_paths


def test_workspace_repository_names_match_remote_names(tmp_path) -> None:
    paths = workspace_paths(tmp_path)

    assert paths.code == tmp_path / "openlabs"
    assert paths.data == tmp_path / "openlabs-data"
    assert paths.artifacts == tmp_path / "openlabs-artifacts"
    assert paths.database == tmp_path / "openlabs-database"
    assert paths.database_file == tmp_path / "openlabs-database" / "live" / "factory.sqlite"
