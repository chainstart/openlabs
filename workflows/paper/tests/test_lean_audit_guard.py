import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = (
    Path(__file__).parents[1]
    / "skills"
    / "openlabs-paper-review"
    / "scripts"
    / "run_lean_audit.py"
)
SPEC = importlib.util.spec_from_file_location("ara_run_lean_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
lean_audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lean_audit
SPEC.loader.exec_module(lean_audit)


def test_default_lean_limits_use_wsl_capacity_but_keep_hard_caps() -> None:
    limits = lean_audit.ResourceLimits()

    limits.validate()

    assert limits.threads == 2
    assert limits.aggregate_rss_mib == 16384
    assert limits.per_process_as_mib == 24576
    assert limits.max_processes == 12
    assert limits.timeout_seconds == 3600


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("threads", 5),
        ("aggregate_rss_mib", 24577),
        ("per_process_as_mib", 32769),
        ("max_processes", 25),
        ("timeout_seconds", 3601),
    ],
)
def test_lean_limits_reject_values_above_repository_caps(field: str, value: int) -> None:
    values = lean_audit.ResourceLimits().__dict__.copy()
    values[field] = value

    with pytest.raises(lean_audit.AuditError, match=field):
        lean_audit.ResourceLimits(**values).validate()


def test_source_hashes_bind_project_but_ignore_build_cache(tmp_path: Path) -> None:
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.26.0\n", encoding="utf-8")
    (tmp_path / "lakefile.lean").write_text("package Guard\n", encoding="utf-8")
    (tmp_path / "Guard.lean").write_text("theorem guard : True := by trivial\n", encoding="utf-8")
    cache = tmp_path / ".lake" / "build"
    cache.mkdir(parents=True)
    (cache / "Generated.lean").write_text("should be ignored\n", encoding="utf-8")

    hashes = lean_audit._source_hashes(tmp_path)

    assert set(hashes) == {"Guard.lean", "lakefile.lean", "lean-toolchain"}
    assert all(len(value) == 64 for value in hashes.values())


def test_preflight_reserves_quarter_of_large_wsl_memory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(lean_audit, "_memory_mib", lambda: (44000, 40000))
    monkeypatch.setattr(lean_audit, "_cpu_utilization", lambda: 0.25)
    monkeypatch.setattr(
        lean_audit.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=20 * 1024 * 1024 * 1024),
    )

    preflight = lean_audit._preflight(tmp_path, lean_audit.ResourceLimits())

    assert preflight["reserved_headroom_mib"] == 11000
    assert preflight["required_available_memory_mib"] == 27384


def test_preflight_refuses_to_consume_reserved_host_memory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(lean_audit, "_memory_mib", lambda: (44000, 27000))

    with pytest.raises(lean_audit.AuditError, match="reserved for the host") as captured:
        lean_audit._preflight(tmp_path, lean_audit.ResourceLimits())

    assert captured.value.reason == "insufficient_memory"


def test_portable_log_redacts_machine_specific_prefixes(tmp_path: Path) -> None:
    project = tmp_path / "paper" / "lean"
    log = {
        "bytes": 12,
        "sha256": "a" * 64,
        "tail": f"{project}/Guard.lean {Path.home()}/.elan/bin/lean",
    }

    portable = lean_audit._portable_log(log, project)

    assert portable["sha256"] == "a" * 64
    assert str(tmp_path) not in str(portable["tail"])
    assert str(Path.home()) not in str(portable["tail"])
    assert "<lean-project>/Guard.lean" in str(portable["tail"])


def test_matching_pass_receipt_is_reused_only_for_exact_binding(tmp_path: Path) -> None:
    receipt = tmp_path / "lean.json"
    source_hashes = {"Guard.lean": "a" * 64}
    receipt.write_text(
        json.dumps(
            {
                "schema_version": lean_audit.SCHEMA_VERSION,
                "status": "PASS",
                "paper_id": "paper-1",
                "manuscript_snapshot_sha256": "b" * 64,
                "support_package_sha256": "c" * 64,
                "source_sha256": source_hashes,
                "formal_validation_execution_count": 1,
                "cumulative_formal_validation_execution_count": 1,
            }
        ),
        encoding="utf-8",
    )

    assert lean_audit._matching_pass_receipt(
        receipt,
        paper_id="paper-1",
        snapshot="b" * 64,
        support_sha256="c" * 64,
        source_hashes=source_hashes,
    )
    assert not lean_audit._matching_pass_receipt(
        receipt,
        paper_id="paper-1",
        snapshot="d" * 64,
        support_sha256="c" * 64,
        source_hashes=source_hashes,
    )


def test_prior_failed_attempt_must_match_and_is_hash_linked(tmp_path: Path) -> None:
    source_hashes = {"Guard.lean": "a" * 64}
    receipt = tmp_path / "failed.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": lean_audit.SCHEMA_VERSION,
                "status": "FAIL",
                "paper_id": "paper-1",
                "manuscript_snapshot_sha256": "b" * 64,
                "support_package_sha256": "c" * 64,
                "source_sha256": source_hashes,
                "failure": {"reason": "command_failed"},
            }
        ),
        encoding="utf-8",
    )

    record = lean_audit._prior_failed_attempt(
        receipt,
        root=tmp_path,
        paper_id="paper-1",
        snapshot="b" * 64,
        support_sha256="c" * 64,
        source_hashes=source_hashes,
    )

    assert record["source"] == "failed.json"
    assert len(record["sha256"]) == 64
    assert record["reason"] == "command_failed"
    assert record["cumulative_formal_validation_execution_count"] == 0


def test_prior_failed_attempt_cannot_repeat_formal_validation(tmp_path: Path) -> None:
    source_hashes = {"Guard.lean": "a" * 64}
    receipt = tmp_path / "failed.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": lean_audit.SCHEMA_VERSION,
                "status": "FAIL",
                "paper_id": "paper-1",
                "manuscript_snapshot_sha256": "b" * 64,
                "support_package_sha256": "c" * 64,
                "source_sha256": source_hashes,
                "commands": [
                    {"command": ["lake", "build", "--quiet"]},
                    {"command": ["lake", "env", "lean", "GuardAxiomAudit.lean"]},
                ],
                "failure": {"reason": "command_failed"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(lean_audit.AuditError) as captured:
        lean_audit._prior_failed_attempt(
            receipt,
            root=tmp_path,
            paper_id="paper-1",
            snapshot="b" * 64,
            support_sha256="c" * 64,
            source_hashes=source_hashes,
        )

    assert captured.value.reason == "formal_validation_already_executed"


def test_lean_audit_runs_build_and_axiom_audit_sequentially() -> None:
    assert lean_audit._commands(Path("GuardAxiomAudit.lean")) == [
        ["lake", "build", "--quiet"],
        ["lake", "env", "lean", "GuardAxiomAudit.lean"],
    ]


def test_lean_audit_uses_one_host_global_lock() -> None:
    assert lean_audit.GLOBAL_LOCK_NAME == "openlabs-paper-writing-lean-audit.lock"


def test_command_failure_keeps_machine_readable_result(monkeypatch, tmp_path: Path) -> None:
    class FailedProcess:
        pid = 42

        def poll(self):
            return 1

    monkeypatch.setattr(lean_audit.subprocess, "Popen", lambda *args, **kwargs: FailedProcess())

    with pytest.raises(lean_audit.AuditError) as captured:
        lean_audit._run_command(
            ["lake", "build", "--quiet"],
            project=tmp_path,
            environment={},
            limits=lean_audit.ResourceLimits(),
            cpu_ids=[0],
            deadline=lean_audit.time.monotonic() + 60,
        )

    assert captured.value.reason == "command_failed"
    assert captured.value.command_result is not None
    assert captured.value.command_result["return_code"] == 1
