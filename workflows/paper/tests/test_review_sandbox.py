"""Codex review roles: native read-only sandbox, or the hashed read-only copy fallback."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from paper_writing import review_sandbox
from paper_writing.review_launcher import LaunchError, run_role
from paper_writing.support import support_sources_snapshot_sha256

CODEX = {"provider": "openai-codex", "tool": "Codex", "model": "gpt-6.2-astra"}

# A stand-in for the codex CLI: ``codex sandbox -- true`` exits $FAKE_PROBE_RC; ``codex exec``
# records its arguments, cwd and prompt, runs $FAKE_ACTION in its cwd and writes the output.
FAKE = r'''#!/bin/sh
if [ "$1" = sandbox ]; then
  echo "probe" >> "$FAKE_LOG/probes"
  [ "${FAKE_PROBE_RC:-0}" = 0 ] || echo "bwrap: No permissions to create new namespace" >&2
  exit "${FAKE_PROBE_RC:-0}"
fi
echo "$@" > "$FAKE_LOG/args"
pwd > "$FAKE_LOG/cwd"
cat > "$FAKE_LOG/prompt"
env > "$FAKE_LOG/env"
while [ $# -gt 0 ]; do if [ "$1" = -o ]; then out=$2; fi; shift; done
if [ -n "$FAKE_ACTION" ]; then eval "$FAKE_ACTION" > "$FAKE_LOG/action" 2>&1; fi
if [ -n "$FAKE_OUTPUT" ]; then printf '%s' "$FAKE_OUTPUT" > "$out"; else echo '{"answer": "ok"}' > "$out"; fi
echo 'model: gpt-6.2-astra' >&2
'''


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "codex"
    script.write_text(FAKE)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "log"
    log.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv(review_sandbox.COPY_ROOT_ENV, str(tmp_path / "copies"))
    monkeypatch.delenv(review_sandbox.MODE_ENV, raising=False)
    monkeypatch.delenv("FAKE_ACTION", raising=False)
    monkeypatch.delenv("FAKE_OUTPUT", raising=False)
    monkeypatch.setattr(review_sandbox, "_probe_cache", {})
    return log


METADATA = {"paper_id": "p", "research_line": "line-a", "support": {"publication": {"source_files": [
    "papers/p/evidence/replication/verify.py",
    "papers/p/evidence/replication/daily.csv",
    "papers/p/evidence/replication/data",
]}}}


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    rep = root / "papers/p/evidence/replication"
    (rep / "data").mkdir(parents=True)
    (rep / "verify.py").write_text("print('verified')\n")
    (rep / "daily.csv").write_text("date,x\n2024-01-01,1\n")
    (rep / "data" / "inner.json").write_text('{"k": 1}\n')
    return root


def _materials(tmp_path: Path, registered: str | None = "auto"):
    root = _workspace(tmp_path)
    expected = support_sources_snapshot_sha256(METADATA, repo_root=root) if registered == "auto" else registered
    materials = review_sandbox.materials_from_support(METADATA, root, registered_sha256=expected)
    assert materials is not None
    return root, materials


def _packet(root: Path) -> str:
    files = METADATA["support"]["publication"]["source_files"]
    return "Registered material locations:\n" + "\n".join(f"- {(root / f).resolve()}" for f in files)


def _run(tmp_path, root, materials, name="referee_a"):
    return run_role(role_name=name, role=CODEX, system_prompt="s", user_prompt=_packet(root),
                    schema={"type": "object"}, workdir=tmp_path / "run" / name, materials=materials)


# --------------------------------------------------------------------------- mode selection


def test_native_sandbox_is_preferred_when_bubblewrap_works(tmp_path, monkeypatch, fake_codex):
    monkeypatch.setenv("FAKE_PROBE_RC", "0")
    root, materials = _materials(tmp_path)
    _, receipt = _run(tmp_path, root, materials)
    args = (fake_codex / "args").read_text().split()
    assert args[args.index("-s") + 1] == "read-only"
    assert Path((fake_codex / "cwd").read_text().strip()).name == "empty-cwd"
    assert receipt["sandbox_mode"] == "read-only"
    assert receipt["isolation"] == "codex_bwrap_read_only"
    assert receipt["native_sandbox_probe"]["available"] is True
    assert "readonly_copy" not in receipt
    # The native run reads the originals in place: the prompt keeps their paths.
    assert str((root / "papers/p/evidence/replication/verify.py").resolve()) in (fake_codex / "prompt").read_text()
    assert not (tmp_path / "copies").exists() or not any((tmp_path / "copies").iterdir())


def test_fallback_is_chosen_when_bubblewrap_cannot_start(tmp_path, monkeypatch, fake_codex):
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    mode, probe = review_sandbox.select_mode("codex")
    assert mode == review_sandbox.READONLY_COPY
    assert probe["available"] is False and "namespace" in probe["detail"]
    review_sandbox.select_mode("codex")
    assert (fake_codex / "probes").read_text().count("probe") == 1  # probed once per process


def test_mode_can_be_forced(tmp_path, monkeypatch, fake_codex):
    monkeypatch.setenv("FAKE_PROBE_RC", "0")
    monkeypatch.setenv(review_sandbox.MODE_ENV, "readonly_copy")
    assert review_sandbox.select_mode("codex")[0] == review_sandbox.READONLY_COPY
    monkeypatch.setenv(review_sandbox.MODE_ENV, "native")
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    assert review_sandbox.select_mode("codex")[0] == review_sandbox.NATIVE
    assert not (fake_codex / "probes").exists()


def test_roles_without_materials_are_unchanged_and_not_probed(tmp_path, monkeypatch, fake_codex):
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    _, receipt = run_role(role_name="editor", role=CODEX, system_prompt="s", user_prompt="u",
                          schema={"type": "object"}, workdir=tmp_path / "run")
    args = (fake_codex / "args").read_text().split()
    assert args[args.index("-s") + 1] == "read-only"
    assert receipt["sandbox_mode"] == "read-only" and "isolation" not in receipt
    assert not (fake_codex / "probes").exists()


# --------------------------------------------------------------------------- read-only copy


def test_readonly_copy_run_is_isolated_and_hash_checked(tmp_path, monkeypatch, fake_codex):
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    # The role reads a material, checks it cannot write there, and writes into its output dir.
    monkeypatch.setenv("FAKE_ACTION",
                       'cat papers/p/evidence/replication/daily.csv; '
                       'if [ -w papers/p/evidence/replication/verify.py ]; then echo WRITABLE; fi; '
                       'if [ -w papers/p/evidence/replication ]; then echo DIR-WRITABLE; fi; '
                       'echo result > "$OPENLABS_OUTPUT_DIR/out.txt"')
    root, materials = _materials(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result, receipt = _run(tmp_path, root, materials)
    assert result == {"answer": "ok"}

    args = (fake_codex / "args").read_text().split()
    assert args[args.index("-s") + 1] == "danger-full-access"
    cwd = Path((fake_codex / "cwd").read_text().strip())
    assert cwd == Path(args[args.index("-C") + 1])
    assert tmp_path / "copies" in cwd.parents and root not in cwd.parents
    action = (fake_codex / "action").read_text()
    assert "2024-01-01" in action and "WRITABLE" not in action

    prompt = (fake_codex / "prompt").read_text()
    assert str(root.resolve()) not in prompt
    assert str(cwd / "papers/p/evidence/replication/verify.py") in prompt
    assert str(cwd / "papers/p/evidence/replication/data") in prompt
    assert "read-only copy mode" in prompt
    env = (fake_codex / "env").read_text()
    assert "PYTHONDONTWRITEBYTECODE=1" in env

    assert receipt["sandbox_mode"] == "readonly-copy"
    assert receipt["isolation"] == "readonly_copy_danger_full_access"
    assert receipt["native_sandbox_probe"]["available"] is False
    copy = receipt["readonly_copy"]
    assert copy["valid"] is True and copy["file_count"] == 3 and copy["outputs"] == 1
    assert copy["registered_sources"]["matches"] is True
    record = json.loads((tmp_path / "run/referee_a" / review_sandbox.MANIFEST_FILE).read_text())
    assert record["pre_run"]["ok"] and record["post_run"]["ok"] and record["write_protected"]
    assert record["registered_sources"]["matches"] is True
    assert {item["path"] for item in record["files"]} == {
        "papers/p/evidence/replication/verify.py", "papers/p/evidence/replication/daily.csv",
        "papers/p/evidence/replication/data/inner.json"}
    assert record["outputs"][0]["path"] == "out.txt"
    # The copy and its output directory are discarded; the originals are untouched.
    assert not any((tmp_path / "copies").iterdir())
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_tampered_copy_invalidates_the_run(tmp_path, monkeypatch, fake_codex):
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    monkeypatch.setenv("FAKE_ACTION",
                       'chmod u+w papers/p/evidence/replication/daily.csv; '
                       'echo "date,x" > papers/p/evidence/replication/daily.csv')
    root, materials = _materials(tmp_path)
    with pytest.raises(LaunchError, match="invalid"):
        _run(tmp_path, root, materials)
    record = json.loads((tmp_path / "run/referee_a" / review_sandbox.MANIFEST_FILE).read_text())
    assert record["valid"] is False
    assert any("modified: papers/p/evidence/replication/daily.csv" in p for p in record["post_run"]["problems"])
    assert not (tmp_path / "run/referee_a/receipt.json").exists()
    assert not any((tmp_path / "copies").iterdir())


def test_added_file_in_copy_invalidates_the_run(tmp_path, monkeypatch, fake_codex):
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    monkeypatch.setenv("FAKE_ACTION", 'chmod u+w . && touch extra.txt')
    root, materials = _materials(tmp_path)
    with pytest.raises(LaunchError, match="invalid"):
        _run(tmp_path, root, materials)
    record = json.loads((tmp_path / "run/referee_a" / review_sandbox.MANIFEST_FILE).read_text())
    assert any("added: extra.txt" in p for p in record["post_run"]["problems"])


def test_changed_original_invalidates_the_run(tmp_path, monkeypatch, fake_codex):
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    root, materials = _materials(tmp_path)
    original = root / "papers/p/evidence/replication/verify.py"
    monkeypatch.setenv("FAKE_ACTION", f'echo "print(1)" > {original}')
    with pytest.raises(LaunchError, match="original registered file changed"):
        _run(tmp_path, root, materials)


def test_registered_checksum_mismatch_stops_before_the_role_runs(tmp_path, monkeypatch, fake_codex):
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    root, materials = _materials(tmp_path, registered="0" * 64)
    with pytest.raises(LaunchError, match="registered support_sources_sha256"):
        _run(tmp_path, root, materials)
    assert not (fake_codex / "args").exists()
    record = json.loads((tmp_path / "run/referee_a" / review_sandbox.MANIFEST_FILE).read_text())
    assert record["pre_run"]["ok"] is False and record["registered_sources"]["matches"] is False
    assert not any((tmp_path / "copies").iterdir())


def test_copy_never_lands_inside_the_workspace(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    monkeypatch.setenv(review_sandbox.COPY_ROOT_ENV, str(root / "scratch"))
    monkeypatch.setenv("OPENLABS_SCRATCH_DIR", str(tmp_path / "scratch"))
    assert review_sandbox._copy_base(root) == (tmp_path / "scratch").resolve()


def test_registered_digest_matches_the_review_fingerprint(tmp_path):
    root, materials = _materials(tmp_path)
    copy = review_sandbox.ReadonlyCopy(materials, "referee_a")
    try:
        record = copy.create()
        assert record["registered_sources"]["copy_sha256"] == support_sources_snapshot_sha256(
            METADATA, repo_root=root)
        assert all(not os.access(p, os.W_OK) for p in copy.inputs.rglob("*"))
    finally:
        copy.release()
    assert not copy.base.exists()


def test_line_interpreter_hint(tmp_path):
    root = _workspace(tmp_path)
    python = tmp_path / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    (root / "registry").mkdir()
    (root / "registry/research-lines.yaml").write_text(
        f"lines:\n  - id: line-a\n    environment:\n      activate: {python} -I (note)\n")
    assert review_sandbox.line_interpreter(METADATA, root) == str(python)
    assert review_sandbox.line_interpreter({"research_line": "other"}, root) is None


def test_unified_review_hands_the_registered_sources_to_the_referees(tmp_path, monkeypatch):
    from paper_writing import review_flow as flow
    from test_review_flow import editor, mock_formal_stage, referee

    mock_formal_stage(monkeypatch)
    root = _workspace(tmp_path)
    registered = support_sources_snapshot_sha256(METADATA, repo_root=root)
    config = {'process': flow.PROCESS, 'roles': {'editor': {'provider': 'openai-codex'},
              'referee_b': {'provider': 'openai-codex'}}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': False, 'timeout_seconds': 1, 'max_rounds_per_target': 10}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    pre = {'metadata': {**METADATA, 'version': '1.0', 'target_journal': 'J'}, 'target': 'J', 'blockers': [],
           'fingerprints': {'support_sources_sha256': registered}, 'expanded': 'x', 'bibliography': ''}
    monkeypatch.setattr(flow, 'preflight', lambda *args: pre)
    monkeypatch.setattr(flow, 'prior_decisions', lambda *args: [])
    seen = {}

    def role(**kw):
        seen[kw['role_name']] = kw
        if kw['role_name'] == 'editor':
            return editor(), {}
        if kw['role_name'] == 'decision_letter':
            return {'letter': 'fixed decision'}, {}
        return referee('accept'), {}

    monkeypatch.setattr(flow, 'run_role', role)
    flow.run_review('p', root=root, apply=False)
    materials = seen['referee_b']['materials']
    assert materials.registered_sha256 == registered
    assert set(materials.relative.values()) == {
        "papers/p/evidence/replication/verify.py", "papers/p/evidence/replication/daily.csv",
        "papers/p/evidence/replication/data/inner.json"}
    assert 'materials' not in seen['editor'] and 'materials' not in seen['decision_letter']


# --------------------------------------------------------------------------- runtime preflight


def _preflight_fixture(tmp_path, monkeypatch):
    import zipfile

    from paper_writing import review_preflight

    root = _workspace(tmp_path)
    monkeypatch.setattr("paper_writing.registry.load_paper_metadata", lambda paper_id, root: METADATA)
    registered = support_sources_snapshot_sha256(METADATA, repo_root=root)
    attachment = tmp_path / "stage" / "referee-replication.zip"
    attachment.parent.mkdir()
    rep = root / "papers/p/evidence/replication"
    files = {"verify.py": rep / "verify.py", "daily.csv": rep / "daily.csv", "inner.json": rep / "data/inner.json"}
    with zipfile.ZipFile(attachment, "w") as archive:
        sums = []
        for name, path in files.items():
            archive.writestr(f"replication/{name}", path.read_bytes())
            sums.append(f"{review_sandbox.sha256_file(path)}  {name}")
        archive.writestr("replication/SHA256SUMS", "\n".join(sums) + "\n")
    return review_preflight, root, registered, attachment


def _report(**changes):
    report = {"files_checked": 3, "checksums_matched": 3, "mismatches": [], "verifier_command": "python verify.py",
              "verifier_exit_code": 0, "verifier_output_tail": "verified", "attachment_opened": True, "notes": ""}
    return json.dumps(report | changes)


def test_runtime_preflight_passes_in_readonly_copy_mode(tmp_path, monkeypatch, fake_codex):
    review_preflight, root, registered, attachment = _preflight_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    monkeypatch.setenv("FAKE_OUTPUT", _report())
    monkeypatch.setenv("FAKE_ACTION", "ls attachment > /dev/null")
    record = review_preflight.run_preflight("p", root, tmp_path / "out", role=CODEX, attachment=attachment,
                                            verifier="python verify.py", registered_sha256=registered)
    assert record["ok"] is True, record
    assert record["sandbox_mode"] == "readonly-copy" and record["copy_valid"] is True
    assert record["registered_sources_match"] is True and record["expected_checksums"] == 3
    assert record["attachment"]["matched_registered_sources"] == 3
    prompt = (fake_codex / "prompt").read_text()
    assert "attachment/referee-replication.zip" in prompt and str(attachment) not in prompt
    saved = json.loads((tmp_path / "out/preflight.json").read_text())
    assert saved["ok"] is True and saved["isolation"] == "readonly_copy_danger_full_access"


def test_runtime_preflight_fails_on_verifier_or_checksum_problems(tmp_path, monkeypatch, fake_codex):
    review_preflight, root, registered, attachment = _preflight_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_PROBE_RC", "1")
    monkeypatch.setenv("FAKE_OUTPUT", _report(verifier_exit_code=1))
    record = review_preflight.run_preflight("p", root, tmp_path / "out1", role=CODEX, attachment=attachment,
                                            registered_sha256=registered)
    assert record["ok"] is False and record["runtime_started"] is True
    monkeypatch.setenv("FAKE_OUTPUT", _report())
    record = review_preflight.run_preflight("p", root, tmp_path / "out2", role=CODEX, attachment=attachment,
                                            registered_sha256="f" * 64)
    assert record["ok"] is False and record["runtime_started"] is False
    assert "registered support_sources_sha256" in record["error"]
