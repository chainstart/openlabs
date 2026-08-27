from __future__ import annotations

import json
import urllib.error

import pytest

from openlabs.__main__ import _parser
from openlabs.proxy import ProxyPreflightError, agent_preflight_target, ensure_proxy_ready


def _environment(tmp_path, port: int) -> dict[str, str]:
    proxy = f"http://172.29.176.1:{port}"
    return {
        "HOME": str(tmp_path),
        "HTTP_PROXY": proxy,
        "HTTPS_PROXY": proxy,
        "ALL_PROXY": proxy,
        "NO_PROXY": "localhost,127.0.0.1",
        "http_proxy": proxy,
        "https_proxy": proxy,
        "all_proxy": proxy,
        "no_proxy": "localhost,127.0.0.1",
        "OPENLABS_AGENT_PREFLIGHT_URL": "https://chatgpt.example/backend-api/codex",
    }


def _write_proxy_file(tmp_path, port: int) -> None:
    path = tmp_path / "environment.d" / "90-openlabs-proxy.conf"
    path.parent.mkdir()
    proxy = f"http://172.29.176.1:{port}"
    path.write_text(
        f'HTTP_PROXY="{proxy}"\n'
        f'HTTPS_PROXY="{proxy}"\n'
        f'ALL_PROXY="{proxy}"\n'
        'NO_PROXY="localhost,127.0.0.1"\n'
        f'http_proxy="{proxy}"\n'
        f'https_proxy="{proxy}"\n'
        f'all_proxy="{proxy}"\n'
        'no_proxy="localhost,127.0.0.1"\n',
        encoding="utf-8",
    )


def test_reachable_process_proxy_is_persisted_before_startup(tmp_path) -> None:
    environment = _environment(tmp_path, 60032)
    inherited = dict(environment)
    _write_proxy_file(tmp_path, 50827)
    seen: list[str] = []

    def probe(_target, proxies, timeout):
        assert timeout == 10.0
        seen.append(proxies["HTTPS_PROXY"])

    report = ensure_proxy_ready(
        environment=environment,
        inherited_environment=inherited,
        config_home=tmp_path,
        probe=probe,
        sync_systemd=False,
    )

    persisted = (tmp_path / "environment.d" / "90-openlabs-proxy.conf").read_text()
    assert seen == ["http://172.29.176.1:60032"]
    assert "50827" not in persisted
    assert persisted.count("60032") == 6
    assert report["source"] == "process"
    assert report["route"] == "172.29.176.1:60032"
    assert report["proxy_file_changed"] is True


def test_reachable_configured_proxy_overrides_stale_process_proxy(tmp_path) -> None:
    environment = _environment(tmp_path, 50827)
    inherited = dict(environment)
    _write_proxy_file(tmp_path, 60032)

    def probe(_target, proxies, _timeout):
        if proxies["HTTPS_PROXY"].endswith(":50827"):
            raise urllib.error.URLError("connection refused")

    report = ensure_proxy_ready(
        environment=environment,
        inherited_environment=inherited,
        config_home=tmp_path,
        probe=probe,
        sync_systemd=False,
    )

    assert environment["HTTPS_PROXY"] == "http://172.29.176.1:60032"
    assert environment["https_proxy"] == "http://172.29.176.1:60032"
    assert report["source"] == "configured"
    assert report["proxy_file_changed"] is False


def test_unreachable_proxy_candidates_fail_closed_without_rewriting(tmp_path) -> None:
    environment = _environment(tmp_path, 50827)
    inherited = dict(environment)
    _write_proxy_file(tmp_path, 50828)
    path = tmp_path / "environment.d" / "90-openlabs-proxy.conf"
    before = path.read_text(encoding="utf-8")

    def probe(_target, _proxies, _timeout):
        raise urllib.error.URLError("connection refused")

    with pytest.raises(ProxyPreflightError, match="unreachable") as raised:
        ensure_proxy_ready(
            environment=environment,
            inherited_environment=inherited,
            config_home=tmp_path,
            probe=probe,
            sync_systemd=False,
        )

    assert "connection refused" not in str(raised.value)
    assert path.read_text(encoding="utf-8") == before


def test_direct_route_is_allowed_when_no_proxy_is_configured(tmp_path) -> None:
    environment = {
        "HOME": str(tmp_path),
        "OPENLABS_AGENT_PREFLIGHT_URL": "https://provider.example/codex",
    }
    seen: list[dict[str, str]] = []

    report = ensure_proxy_ready(
        environment=environment,
        inherited_environment=dict(environment),
        config_home=tmp_path,
        probe=lambda _target, proxies, _timeout: seen.append(dict(proxies)),
        sync_systemd=False,
    )

    assert seen == [{}]
    assert report["source"] == "direct"
    assert report["route"] == "direct"
    assert report["proxy_file_changed"] is False


def test_preflight_target_comes_from_codex_provider_config() -> None:
    environment = {
        "OPENLABS_AGENT_COMMAND_JSON": json.dumps(
            [
                "codex",
                "exec",
                "-c",
                'model_providers.chatgpt.base_url="https://chatgpt.com/backend-api/codex"',
                "-",
            ]
        )
    }

    assert agent_preflight_target(environment) == "https://chatgpt.com/backend-api/codex"


def test_network_preflight_exec_preserves_nested_command_separator() -> None:
    arguments = _parser().parse_args(
        ["network-preflight", "--exec", "/repo/bin/openlabs-resource-guard", "--", "codex"]
    )

    assert arguments.execute is True
    assert arguments.exec_command == ["/repo/bin/openlabs-resource-guard", "--", "codex"]
