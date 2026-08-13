from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[2]
MATH_RUNTIME_PATH = CODE_ROOT / "labs/math/tools/computation/math_runtime.py"
RESOURCE_GUARD_PATH = CODE_ROOT / "labs/math/tools/runtime_guard.py"
AMRA_PROTOCOL_PATH = CODE_ROOT / "labs/math/protocols/amra_math_protocol.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_exact_and_arb_outputs_require_typed_evidence() -> None:
    runtime = _load(MATH_RUNTIME_PATH, "openlabs_math_runtime_test")
    exact = runtime._profile("sage-exact-v10.8")
    assert runtime._validate_exact_output(
        {
            "schema_version": exact["output_schema"],
            "status": "passed",
            "evidence_class": exact["evidence_class"],
            "claims": [{"claim_id": "c", "statement": "exact", "exact": True}],
        },
        exact,
    ) == []
    arb = runtime._profile("arb-certified-v10.8")
    errors = runtime._validate_arb_output(
        {
            "schema_version": arb["output_schema"],
            "status": "passed",
            "evidence_class": arb["evidence_class"],
            "certificates": [
                {
                    "certificate_id": "bad",
                    "statement": "reversed interval",
                    "precision_bits": 128,
                    "intervals": [{"quantity": "x", "lower": "2", "upper": "1"}],
                }
            ],
        },
        arb,
    )
    assert errors == ["Arb certificate 0 interval 0 has invalid bounds"]


def test_resource_guard_enforces_memory_and_wall_limits(tmp_path) -> None:
    guard = _load(RESOURCE_GUARD_PATH, "openlabs_resource_guard_test")
    limits = guard.ResourceLimits(
        memory_mib=64,
        cpu_seconds=5,
        wall_seconds=2,
        file_mib=16,
        open_files=64,
        threads=1,
        output_mib=1,
    )
    memory = guard.run_guarded(
        [sys.executable, "-c", "bytearray(256 * 1024 * 1024)"],
        cwd=tmp_path,
        limits=limits,
    )
    assert memory.returncode != 0
    timeout_limits = guard.ResourceLimits(**{**limits.to_dict(), "wall_seconds": 1})
    timeout = guard.run_guarded(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        limits=timeout_limits,
    )
    assert timeout.timed_out is True
    assert timeout.returncode != 0


def test_host_relative_limits_are_not_reduced_by_scheduler_reservations(
    monkeypatch,
) -> None:
    guard = _load(RESOURCE_GUARD_PATH, "openlabs_fractional_resource_guard_test")
    monkeypatch.setattr(guard, "host_memory_mib", lambda: 44_000)
    monkeypatch.setattr(guard, "host_cpu_threads", lambda: 20)
    monkeypatch.setenv("OPENLABS_MEMORY_MIB", "4096")
    monkeypatch.setenv("OPENLABS_CPU_THREADS", "2")

    limits = guard.limits_from_environment(
        wall_seconds=300,
        memory_fraction_of_host=0.75,
        max_cpu_seconds=4_500,
        max_file_mib=512,
        threads_fraction_of_host=0.75,
        respect_task_reservations=False,
    )

    assert limits.memory_mib == 33_000
    assert limits.threads == 15
    assert limits.cpu_seconds == 4_500


def test_amra_protocol_rejects_unreceipted_passed_computation(tmp_path) -> None:
    protocol = _load(AMRA_PROTOCOL_PATH, "openlabs_amra_computation_test")
    campaign = tmp_path / "research" / "target"
    campaign.mkdir(parents=True)
    (campaign / "audit.json").write_text(
        '{"computation_checks":[{"profile_id":"sage-exact-v10.8",'
        '"status":"passed","evidence":["experiments/sage/note.json"]}]}\n',
        encoding="utf-8",
    )
    note = campaign / "experiments" / "sage" / "note.json"
    note.parent.mkdir(parents=True)
    note.write_text('{"status":"agent-says-passed"}\n', encoding="utf-8")

    errors = protocol._validate_computations(tmp_path, campaign, mode="commit")

    assert errors == [
        "passed computation_checks[0] contains no OpenLabs computation receipt"
    ]
