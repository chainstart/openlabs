from __future__ import annotations

from openlabs.config import load_local_environment, load_settings, workspace_paths


def test_workspace_repository_names_match_remote_names(tmp_path) -> None:
    paths = workspace_paths(tmp_path)

    assert paths.code == tmp_path / "openlabs"
    assert paths.data == tmp_path / "openlabs-data"
    assert paths.artifacts == tmp_path / "openlabs-artifacts"
    assert paths.database == tmp_path / "openlabs-database"
    assert paths.database_file == tmp_path / "openlabs-database" / "live" / "factory.sqlite"


def test_epoch_task_window_accepts_new_and_legacy_config_keys(tmp_path) -> None:
    paths = workspace_paths(tmp_path)
    paths.code.mkdir(parents=True)
    config = paths.code / "config" / "openlabs.toml"
    config.parent.mkdir()
    config.write_text(
        "[factory]\nmax_auto_tasks_per_campaign = 11\nmax_auto_tasks_per_epoch = 7\n",
        encoding="utf-8",
    )

    assert load_settings(paths).max_auto_tasks_per_campaign == 7

    config.write_text(
        "[factory]\nmax_auto_tasks_per_campaign = 11\n",
        encoding="utf-8",
    )
    assert load_settings(paths).max_auto_tasks_per_campaign == 11


def test_cpu_fraction_is_loaded_and_invalid_values_fail_to_default(tmp_path) -> None:
    paths = workspace_paths(tmp_path)
    config = paths.code / "config" / "openlabs.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[resources]\nmax_cpu_fraction_of_host = 0.5\n", encoding="utf-8")
    assert load_settings(paths).max_cpu_fraction_of_host == 0.5

    config.write_text("[resources]\nmax_cpu_fraction_of_host = 1.5\n", encoding="utf-8")
    assert load_settings(paths).max_cpu_fraction_of_host == 0.75


def test_local_environment_matches_systemd_files_without_overriding_process(tmp_path) -> None:
    openlabs = tmp_path / "openlabs"
    proxy = tmp_path / "environment.d"
    openlabs.mkdir()
    proxy.mkdir()
    (openlabs / "env").write_text(
        "# local agent\n"
        "OPENLABS_AGENT_COMMAND_JSON='[\"codex\", \"exec\", \"-\"]'\n"
        "EXPLICIT_VALUE=from-file\n",
        encoding="utf-8",
    )
    (proxy / "90-openlabs-proxy.conf").write_text(
        "export HTTPS_PROXY=http://127.0.0.1:7890\n",
        encoding="utf-8",
    )
    environment = {"EXPLICIT_VALUE": "from-process"}

    loaded = load_local_environment(environment, config_home=tmp_path)

    assert loaded == (
        (openlabs / "env").resolve(),
        (proxy / "90-openlabs-proxy.conf").resolve(),
    )
    assert environment["OPENLABS_AGENT_COMMAND_JSON"] == '["codex", "exec", "-"]'
    assert environment["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert environment["EXPLICIT_VALUE"] == "from-process"


def test_local_environment_treats_shell_syntax_as_inert_text(tmp_path) -> None:
    openlabs = tmp_path / "openlabs"
    openlabs.mkdir()
    marker = tmp_path / "must-not-exist"
    (openlabs / "env").write_text(
        f"INERT_VALUE=$(touch {marker})\n",
        encoding="utf-8",
    )
    environment: dict[str, str] = {}

    load_local_environment(environment, config_home=tmp_path)

    assert environment["INERT_VALUE"] == f"$(touch {marker})"
    assert not marker.exists()
