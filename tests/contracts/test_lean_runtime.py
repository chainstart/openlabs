from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


CODE_ROOT = Path(__file__).resolve().parents[2]
LEAN_RUNTIME_PATH = CODE_ROOT / "labs/math/tools/formal/lean_runtime.py"
AMRA_PROTOCOL_PATH = CODE_ROOT / "labs/math/protocols/amra_math_protocol.py"


def _load_runtime():
    spec = importlib.util.spec_from_file_location("openlabs_lean_runtime", LEAN_RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_protocol():
    spec = importlib.util.spec_from_file_location("openlabs_amra_protocol", AMRA_PROTOCOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lean_sources_must_be_attempt_local_and_under_formal_directory(tmp_path) -> None:
    runtime = _load_runtime()
    source = tmp_path / "research" / "target" / "formal" / "lean" / "Main.lean"
    source.parent.mkdir(parents=True)
    source.write_text("theorem checked : True := by trivial\n", encoding="utf-8")

    relative, resolved = runtime._formal_source(
        tmp_path,
        "research/target/formal/lean/Main.lean",
    )

    assert relative.as_posix() == "research/target/formal/lean/Main.lean"
    assert resolved == source
    with pytest.raises(ValueError, match="formal/lean"):
        runtime._formal_source(tmp_path, "research/target/Main.lean")
    with pytest.raises(ValueError, match="workspace-relative"):
        runtime._formal_source(tmp_path, "../outside/formal/lean/Main.lean")


def test_verify_writes_receipt_only_after_kernel_payload_passes(tmp_path, monkeypatch) -> None:
    runtime = _load_runtime()
    payload = {
        "schema_version": runtime.RECEIPT_SCHEMA,
        "status": "passed",
        "profile_id": "test",
    }
    monkeypatch.setattr(runtime, "_verify_payload", lambda *args, **kwargs: (payload, []))

    result = runtime.verify(
        tmp_path,
        source="formal/lean/Main.lean",
        inputs=[],
        declarations=["Test.main"],
        receipt="formal/lean/verification.json",
        timeout=10,
    )

    assert result["valid"] is True
    assert (tmp_path / "formal/lean/verification.json").is_file()

    monkeypatch.setattr(
        runtime,
        "_verify_payload",
        lambda *args, **kwargs: ({**payload, "status": "failed"}, ["kernel failure"]),
    )
    failed = runtime.verify(
        tmp_path,
        source="formal/lean/Bad.lean",
        inputs=[],
        declarations=["Test.bad"],
        receipt="formal/lean/rejected.json",
        timeout=10,
    )
    assert failed["valid"] is False
    assert not (tmp_path / "formal/lean/rejected.json").exists()


def test_amra_protocol_rejects_unreceipted_formalization_claim(tmp_path) -> None:
    protocol = _load_protocol()
    campaign = tmp_path / "research" / "target"
    campaign.mkdir(parents=True)
    (campaign / "audit.json").write_text(
        '{"formalization_check":{"status":"passed","evidence":["formal/lean/note.md"]}}\n',
        encoding="utf-8",
    )
    note = campaign / "formal" / "lean" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("Agent says Lean passed.\n", encoding="utf-8")

    errors = protocol._validate_formalization(tmp_path, campaign, mode="commit")

    assert errors == ["passed formalization evidence contains no OpenLabs Lean v1 receipt"]
