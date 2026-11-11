from __future__ import annotations

import pytest
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


def test_local_environment_loads_owner_only_zenodo_credentials(tmp_path) -> None:
    ara = tmp_path / "ara"
    ara.mkdir()
    credentials = ara / "zenodo.env"
    credentials.write_text(
        "ZENODO_ENVIRONMENT=production\nZENODO_ACCESS_TOKEN='test-production-token'\n",
        encoding="utf-8",
    )
    credentials.chmod(0o600)
    environment: dict[str, str] = {}

    loaded = load_local_environment(environment, config_home=tmp_path)

    assert loaded == (credentials.resolve(),)
    assert environment["ZENODO_ENVIRONMENT"] == "production"
    assert environment["ZENODO_ACCESS_TOKEN"] == "test-production-token"


def test_local_environment_rejects_insecure_zenodo_credentials(tmp_path) -> None:
    ara = tmp_path / "ara"
    ara.mkdir()
    credentials = ara / "zenodo.env"
    credentials.write_text("ZENODO_ACCESS_TOKEN=test-token\n", encoding="utf-8")
    credentials.chmod(0o644)

    with pytest.raises(ValueError, match="owner-only permissions"):
        load_local_environment({}, config_home=tmp_path)


def test_local_environment_rejects_unrelated_zenodo_file_variables(tmp_path) -> None:
    ara = tmp_path / "ara"
    ara.mkdir()
    credentials = ara / "zenodo.env"
    credentials.write_text(
        "ZENODO_ACCESS_TOKEN=test-token\nUNRELATED_SECRET=must-not-load\n",
        encoding="utf-8",
    )
    credentials.chmod(0o600)

    with pytest.raises(ValueError, match="unsupported private environment name"):
        load_local_environment({}, config_home=tmp_path)


def _clear_instance(monkeypatch) -> None:
    for name in ("OPENLABS_INSTANCE", "OPENLABS_DATABASE_ROOT", "OPENLABS_CONFIG_FILE"):
        monkeypatch.delenv(name, raising=False)


def test_default_instance_paths_are_unchanged(tmp_path, monkeypatch) -> None:
    _clear_instance(monkeypatch)
    paths = workspace_paths(tmp_path)

    assert paths.instance is None
    assert paths.settings_file == tmp_path / "openlabs" / "config" / "openlabs.toml"
    assert paths.job_inbox == tmp_path / "openlabs-data" / "inbox" / "jobs"
    assert paths.result_inbox == tmp_path / "openlabs-data" / "inbox" / "results"
    assert paths.receipt_archive == tmp_path / "openlabs-data" / "ledger" / "receipts"
    assert paths.attempt_workspaces == tmp_path / "openlabs-artifacts" / "attempt-workspaces"
    assert paths.program_control == tmp_path / "openlabs-artifacts" / "program-control"
    assert paths.scans_legacy_production_plans


def test_named_instance_uses_its_own_database_inbox_config_and_state(
    tmp_path, monkeypatch
) -> None:
    _clear_instance(monkeypatch)
    root = tmp_path / "instances" / "cc-sg"
    monkeypatch.setenv("OPENLABS_INSTANCE", "cc-sg")
    monkeypatch.setenv("OPENLABS_DATABASE_ROOT", str(root / "database"))
    monkeypatch.setenv("OPENLABS_CONFIG_FILE", str(root / "openlabs.toml"))
    paths = workspace_paths(tmp_path)

    assert paths.data == tmp_path / "openlabs-data"  # shared
    assert paths.artifacts == tmp_path / "openlabs-artifacts"  # shared
    assert paths.database_file == root / "database" / "live" / "factory.sqlite"
    assert paths.job_inbox == root / "database" / "inbox" / "jobs"
    assert paths.result_inbox == root / "database" / "inbox" / "results"
    assert paths.settings_file == root / "openlabs.toml"
    instance_artifacts = tmp_path / "openlabs-artifacts" / "instances" / "cc-sg"
    assert paths.attempt_workspaces == instance_artifacts / "attempt-workspaces"
    assert paths.program_control == instance_artifacts / "program-control"
    assert not paths.scans_legacy_production_plans

    with pytest.raises(FileNotFoundError):
        load_settings(paths)
    (root).mkdir(parents=True)
    (root / "openlabs.toml").write_text("[budget]\nmax_parallel_agents = 2\n", encoding="utf-8")
    assert load_settings(paths).budget.max_parallel_agents == 2


def test_instance_project_discovery_is_disjoint_from_the_default(tmp_path, monkeypatch) -> None:
    _clear_instance(monkeypatch)
    workspaces = tmp_path / "openlabs-data" / "workspaces"
    default = workspaces / "ai" / "projects" / "old" / "project.json"
    production = workspaces / "ai" / "production" / "plan" / "project.json"
    mine = workspaces / "ai" / "instances" / "cc-sg" / "projects" / "new" / "project.json"
    other = workspaces / "ai" / "instances" / "other" / "projects" / "x" / "project.json"
    for path in (default, production, mine, other):
        path.parent.mkdir(parents=True)
        path.write_text("{}", encoding="utf-8")

    assert workspace_paths(tmp_path).project_config_paths() == [production, default]
    monkeypatch.setenv("OPENLABS_INSTANCE", "cc-sg")
    monkeypatch.setenv("OPENLABS_DATABASE_ROOT", str(tmp_path / "cc-sg-db"))
    assert workspace_paths(tmp_path).project_config_paths() == [mine]


@pytest.mark.parametrize(
    ("instance", "database", "message"),
    [
        ("cc-sg", None, "needs its own"),
        ("cc-sg", "DEFAULT", "needs its own"),
        (None, "/elsewhere/db", "without OPENLABS_INSTANCE"),
        ("CC SG", "/elsewhere/db", "lower-case"),
    ],
)
def test_half_configured_instance_is_refused(
    tmp_path, monkeypatch, instance, database, message
) -> None:
    _clear_instance(monkeypatch)
    if instance is not None:
        monkeypatch.setenv("OPENLABS_INSTANCE", instance)
    if database is not None:
        monkeypatch.setenv(
            "OPENLABS_DATABASE_ROOT",
            str(tmp_path / "openlabs-database") if database == "DEFAULT" else database,
        )
    with pytest.raises(ValueError, match=message):
        workspace_paths(tmp_path)
