"""Formal-check retrieval fallback through the host download bridge."""
import json
import os
import stat
from pathlib import Path

import httpx
import pytest

from paper_writing import formal_checks as formal

from tests.test_formal_checks import PRIMARY, ROLE, fixture_workspace, simulated_runner, transport


def fake_bridge(tmp_path: Path, *, body: bytes | None, state: str = "completed", exit_code: int = 0) -> Path:
    """A stand-in for download-submit: writes ``body`` to --output and prints a status line."""
    payload = tmp_path / "bridge-body.bin"
    if body is not None:
        payload.write_bytes(body)
    log = tmp_path / "bridge-calls.jsonl"
    script = tmp_path / "download-submit"
    script.write_text(f"""#!/usr/bin/env python3
import json, shutil, sys
args = sys.argv[1:]
url, out = args[args.index('--url') + 1], args[args.index('--output') + 1]
open({str(log)!r}, 'a').write(json.dumps({{'url': url, 'output': out, 'args': args}}) + '\\n')
if {body is not None!r} and {state!r} == 'completed':
    shutil.copyfile({str(payload)!r}, out)
print(json.dumps({{'id': 'job1', 'state': {state!r}, 'route': 'direct', 'routes_attempted': ['direct'],
                  'fallback_reason': None, 'error': None if {state!r} == 'completed' else 'HTTP 403'}}))
sys.exit({exit_code})
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def blocked(status: int):
    def handler(request):
        if request.url.host == "publisher.example":
            return httpx.Response(status)
        return transport(request)
    return handler


def collect(tmp_path, metadata, handler):
    docs, bib = formal.current_inputs(metadata, tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return formal.collect_sources(formal.inventory(docs, bib), metadata, tmp_path, tmp_path / "evidence", client)


def calls(tmp_path):
    log = tmp_path / "bridge-calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_direct_403_then_bridge_success_uses_same_checks(tmp_path, monkeypatch):
    metadata = fixture_workspace(tmp_path)
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", str(fake_bridge(tmp_path, body=PRIMARY.encode())))
    sources, errors = collect(tmp_path, metadata, blocked(403))
    assert errors == []
    primary = next(s for s in sources if s["kind"] == "primary_text")
    assert primary["text"] == PRIMARY
    retrieval = primary["retrieval"]
    assert retrieval["method"] == "download_bridge" and retrieval["direct_failure"] == "HTTPStatusError 403"
    assert retrieval["bridge_route"] == "direct" and retrieval["bridge_job_id"] == "job1"
    assert retrieval["bridge_file_sha256"] == primary["body_sha256"]
    assert (tmp_path / retrieval["bridge_file"]).is_file()
    assert calls(tmp_path)[0]["url"] == "https://publisher.example/original"
    crossref = next(s for s in sources if s["kind"] == "bibliographic_metadata")
    assert crossref["retrieval"] == {"method": "direct"}


def test_bridge_content_is_checked_like_direct_content(tmp_path, monkeypatch):
    metadata = fixture_workspace(tmp_path)
    metadata["formal_check"]["sources"][0]["url"] = "https://publisher.example/original.pdf"
    # The bridge returns an HTML page for a PDF endpoint: rejected exactly as a direct response would be.
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", str(fake_bridge(tmp_path, body=b"<html>not a pdf</html>")))
    sources, errors = collect(tmp_path, metadata, blocked(403))
    assert all(s["kind"] != "primary_text" for s in sources)
    assert "Declared primary source unavailable" in (tmp_path / "evidence/retrieval-failures.json").read_text()
    # A challenge page returned by the bridge is still an access failure, not evidence.
    (tmp_path / "evidence").rename(tmp_path / "evidence-1")
    metadata["formal_check"]["sources"][0]["url"] = "https://publisher.example/original"
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", str(fake_bridge(
        tmp_path, body=b"<html><title>Access Denied</title></html>")))
    sources, errors = collect(tmp_path, metadata, blocked(403))
    assert all(s["kind"] != "primary_text" for s in sources)


@pytest.mark.parametrize("state,exit_code", [("failed", 1), ("queued", 2)])
def test_bridge_failure_keeps_the_original_outcome(tmp_path, monkeypatch, state, exit_code):
    metadata = fixture_workspace(tmp_path)
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", str(fake_bridge(tmp_path, body=None, state=state, exit_code=exit_code)))
    sources, errors = collect(tmp_path, metadata, blocked(403))
    assert all(s["kind"] != "primary_text" for s in sources)
    log = (tmp_path / "evidence/retrieval-failures.json").read_text()
    assert "bridge fallback failed" in log and "Declared primary source unavailable" in log


@pytest.mark.parametrize("status", [404, 410])
def test_absent_record_does_not_use_the_bridge(tmp_path, monkeypatch, status):
    metadata = fixture_workspace(tmp_path)
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", str(fake_bridge(tmp_path, body=PRIMARY.encode())))
    sources, errors = collect(tmp_path, metadata, blocked(status))
    assert calls(tmp_path) == [] and all(s["kind"] != "primary_text" for s in sources)


def test_mismatch_does_not_use_the_bridge(tmp_path, monkeypatch):
    metadata = fixture_workspace(tmp_path); metadata.pop("formal_check")
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", str(fake_bridge(tmp_path, body=PRIMARY.encode())))
    def wrong(request):
        return httpx.Response(200, json={"message": {"DOI": "10.1234/other", "title": ["Other"], "author": [{"family": "Else"}]}})
    sources, errors = collect(tmp_path, metadata, wrong)
    assert sources == [] and errors and calls(tmp_path) == []


def test_disabled_or_missing_bridge_is_not_called(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", "off")
    assert formal.bridge_command() is None
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", str(tmp_path / "missing"))
    assert formal.bridge_command() is None
    monkeypatch.delenv("OPENLABS_FORMAL_BRIDGE")
    monkeypatch.setattr(formal, "DEFAULT_BRIDGE", str(tmp_path / "missing"))
    assert formal.bridge_command() is None
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE_TIMEOUT", "45")
    assert formal.bridge_timeout() == 45


def test_full_pipeline_with_bridge_evidence_revalidates_and_detects_tampering(tmp_path, monkeypatch):
    metadata = fixture_workspace(tmp_path)
    (tmp_path / metadata["manuscript_dir"] / "main.bbl").write_text(r"\bibitem{s}Smith. Exact positivity. 2020.")
    monkeypatch.setenv("OPENLABS_FORMAL_BRIDGE", str(fake_bridge(tmp_path, body=PRIMARY.encode())))
    client_class = httpx.Client
    monkeypatch.setattr(formal.httpx, "Client", lambda **kwargs: client_class(
        transport=httpx.MockTransport(blocked(403)), **kwargs))
    run = tmp_path / "review"; run.mkdir()
    binding = formal.run_checks({"metadata": metadata}, tmp_path, run, ROLE, 1, simulated_runner)
    assert binding["valid"] is True
    assert formal.validate_binding(binding, metadata, tmp_path, ROLE) == []
    report = json.loads((tmp_path / binding["path"]).read_text())
    bridged = [s for s in report["sources"] if s["retrieval"]["method"] == "download_bridge"]
    assert len(bridged) == 1
    (tmp_path / bridged[0]["retrieval"]["bridge_file"]).write_bytes(b"tampered")
    assert any("Bridge-retrieved evidence changed" in b for b in formal.validate_binding(binding, metadata, tmp_path, ROLE))
