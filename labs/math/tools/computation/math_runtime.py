#!/usr/bin/env python3
"""Prepare and replay exact, ball-arithmetic, and SMT mathematics experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
COMPUTATION_ROOT = SCRIPT_PATH.parent
MATH_TOOLS_ROOT = COMPUTATION_ROOT.parent
PROFILES_PATH = COMPUTATION_ROOT / "computation-profiles.json"
PROFILES_SCHEMA = "openlabs.math_computation_profiles.v1"
PREPARED_SCHEMA = "openlabs.math_computation_runtime.v1"
RECEIPT_SCHEMA = "openlabs.math_computation.v1"
DECISIONS = frozenset({"sat", "unsat", "unknown"})
sys.path.insert(0, str(MATH_TOOLS_ROOT))

from runtime_guard import (  # noqa: E402
    GuardedResult,
    ResourceLimits,
    limits_from_environment,
    run_guarded,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _object_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value


def _atomic_write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def _profiles() -> dict[str, dict[str, Any]]:
    payload = _read_object(PROFILES_PATH)
    if payload.get("schema_version") != PROFILES_SCHEMA:
        raise ValueError("unsupported mathematics computation profile schema")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("mathematics computation profiles are missing")
    validated: dict[str, dict[str, Any]] = {}
    for profile_id, raw in profiles.items():
        if not isinstance(profile_id, str) or not profile_id or not isinstance(raw, dict):
            raise ValueError("invalid mathematics computation profile entry")
        for field in ("mode", "evidence_class", "source_root", "source_suffix"):
            if not isinstance(raw.get(field), str) or not raw[field]:
                raise ValueError(f"profile {profile_id} requires {field}")
        limits = raw.get("resource_limits")
        if not isinstance(limits, dict) or any(
            not isinstance(limits.get(field), int)
            or isinstance(limits.get(field), bool)
            or limits[field] < 1
            for field in (
                "memory_mib",
                "cpu_seconds",
                "wall_seconds",
                "file_mib",
                "threads",
                "output_mib",
            )
        ):
            raise ValueError(f"profile {profile_id} has invalid resource limits")
        validated[profile_id] = raw
    return validated


def _profile(profile_id: str) -> dict[str, Any]:
    try:
        return _profiles()[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown mathematics computation profile: {profile_id}") from exc


def _profile_sha256(profile_id: str, profile: dict[str, Any]) -> str:
    return _object_sha256({"profile_id": profile_id, **profile})


def _limits(profile: dict[str, Any], wall_seconds: int) -> ResourceLimits:
    configured = profile["resource_limits"]
    return limits_from_environment(
        wall_seconds=min(wall_seconds, configured["wall_seconds"]),
        max_memory_mib=configured["memory_mib"],
        max_cpu_seconds=configured["cpu_seconds"],
        max_file_mib=configured["file_mib"],
        max_threads=configured["threads"],
        output_mib=configured["output_mib"],
    )


def _engine_result(
    engine_id: str,
    executable: Path,
    version: str,
    result: GuardedResult | None = None,
    *,
    environment_sha256: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "engine_id": engine_id,
        "executable": str(executable),
        "executable_sha256": _sha256(executable),
        "version": version,
    }
    if environment_sha256:
        value["environment_sha256"] = environment_sha256
    if result is not None:
        value.update(
            {
                "returncode": result.returncode,
                "stdout_sha256": _text_sha256(result.stdout),
                "stderr_sha256": _text_sha256(result.stderr),
            }
        )
    return value


def _sage_environment_sha256(sage_local: Path) -> str:
    conda_meta = sage_local / "conda-meta"
    if not conda_meta.is_dir():
        raise RuntimeError(f"Sage environment has no conda metadata: {sage_local}")
    entries = [
        {"name": path.name, "sha256": _sha256(path)}
        for path in sorted(conda_meta.glob("*.json"))
    ]
    if not entries:
        raise RuntimeError("Sage environment fingerprint is empty")
    return _object_sha256(entries)


def _probe_engines(
    profile_id: str,
    profile: dict[str, Any],
    *,
    timeout: int,
) -> list[dict[str, Any]]:
    limits = _limits(profile, min(timeout, 60))
    mode = profile["mode"]
    if mode in {"sage-json", "arb-json"}:
        executable = shutil.which(str(profile.get("executable") or ""))
        if executable is None:
            raise RuntimeError(f"profile {profile_id} executable is unavailable")
        probe = (
            "import json,sage.version; from sage.env import SAGE_LOCAL; "
            "from sage.all import RealBallField; "
            "print(json.dumps({'version':sage.version.version,'sage_local':SAGE_LOCAL,"
            "'arb_type':str(type(RealBallField(53)(1)))}))"
        )
        completed = run_guarded(
            [executable, "-c", probe],
            cwd=COMPUTATION_ROOT,
            limits=limits,
        )
        if completed.returncode != 0 or completed.timed_out or completed.output_overflow:
            raise RuntimeError(f"Sage runtime probe failed: {completed.stderr[-2000:]}")
        payload = json.loads(completed.stdout)
        version = str(payload.get("version") or "")
        if version != profile.get("expected_version"):
            raise RuntimeError(
                f"Sage version differs for {profile_id}: {version!r}"
            )
        if mode == "arb-json" and "RealBall" not in str(payload.get("arb_type") or ""):
            raise RuntimeError("Sage Arb RealBall backend is unavailable")
        resolved = Path(executable).resolve()
        return [
            _engine_result(
                "sage-arb" if mode == "arb-json" else "sage",
                resolved,
                version,
                environment_sha256=_sage_environment_sha256(
                    Path(str(payload["sage_local"])).resolve()
                ),
            )
        ]
    if mode == "smt-consensus":
        engines: list[dict[str, Any]] = []
        for configured in profile.get("executables", []):
            if not isinstance(configured, dict):
                raise ValueError(f"profile {profile_id} has an invalid SMT engine")
            engine_id = str(configured.get("id") or "")
            executable = shutil.which(str(configured.get("command") or ""))
            if not engine_id or executable is None:
                raise RuntimeError(f"SMT engine is unavailable: {engine_id or configured}")
            version_command = [executable, "-version"] if engine_id == "z3" else [executable, "--version"]
            completed = run_guarded(
                version_command,
                cwd=COMPUTATION_ROOT,
                limits=limits,
            )
            output = (completed.stdout + "\n" + completed.stderr).strip()
            expected = str(configured.get("expected_version") or "")
            if completed.returncode != 0 or expected not in output:
                raise RuntimeError(f"SMT engine {engine_id} version differs: {output[:500]}")
            engines.append(
                _engine_result(engine_id, Path(executable).resolve(), expected)
            )
        if len(engines) < 2:
            raise RuntimeError("SMT consensus profile requires at least two engines")
        return engines
    raise ValueError(f"unsupported computation mode: {mode}")


def _prepared_path(workspace: Path, profile_id: str) -> Path:
    return workspace / ".openlabs" / "tools" / f"{profile_id}.json"


def prepare_attempt(
    workspace: Path,
    profile_id: str,
    *,
    timeout: int,
) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"agent workspace does not exist: {root}")
    profile = _profile(profile_id)
    engines = _probe_engines(profile_id, profile, timeout=timeout)
    payload = {
        "schema_version": PREPARED_SCHEMA,
        "profile_id": profile_id,
        "profile_sha256": _profile_sha256(profile_id, profile),
        "evidence_class": profile["evidence_class"],
        "source_root": profile["source_root"],
        "engines": engines,
        "resource_limits": _limits(
            profile,
            profile["resource_limits"]["wall_seconds"],
        ).to_dict(),
        "prepared_at": _utc_now(),
    }
    path = _atomic_write_json(_prepared_path(root, profile_id), payload)
    return {
        "valid": True,
        "profile_id": profile_id,
        "evidence_class": profile["evidence_class"],
        "receipt_path": str(path),
        "engines": engines,
        "resource_limits": payload["resource_limits"],
    }


def _safe_relative(value: str, *, suffix: str | None = None) -> PurePosixPath:
    relative = PurePosixPath(value)
    if not value.strip() or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"path must be workspace-relative: {value!r}")
    if suffix is not None and relative.suffix != suffix:
        raise ValueError(f"path must end in {suffix}: {value!r}")
    return relative


def _under_root(relative: PurePosixPath, configured_root: str) -> bool:
    parts = PurePosixPath(configured_root).parts
    return any(
        relative.parts[index : index + len(parts)] == parts
        for index in range(max(0, len(relative.parts) - len(parts) + 1))
    )


def _experiment_file(
    workspace: Path,
    value: str,
    profile: dict[str, Any],
    *,
    source: bool,
) -> tuple[PurePosixPath, Path]:
    relative = _safe_relative(
        value,
        suffix=profile["source_suffix"] if source else None,
    )
    if not _under_root(relative, profile["source_root"]):
        raise ValueError(
            f"experiment files for this profile must live under {profile['source_root']}"
        )
    path = (workspace / relative).resolve()
    if not path.is_file() or path.is_symlink() or not path.is_relative_to(workspace):
        raise ValueError(f"experiment file is missing or unsafe: {relative}")
    return relative, path


def _prepared_runtime(
    workspace: Path,
    profile_id: str,
    *,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    profile = _profile(profile_id)
    path = _prepared_path(workspace, profile_id)
    prepared = _read_object(path)
    if prepared.get("schema_version") != PREPARED_SCHEMA:
        raise ValueError(f"attempt has no supported runtime for {profile_id}")
    if prepared.get("profile_sha256") != _profile_sha256(profile_id, profile):
        raise ValueError(f"attempt runtime profile differs for {profile_id}")
    current = _probe_engines(profile_id, profile, timeout=timeout)
    if prepared.get("engines") != current:
        raise ValueError(f"attempt runtime engines differ for {profile_id}")
    return prepared, profile, path


def _input_closure(
    workspace: Path,
    source: str,
    inputs: list[str],
    profile: dict[str, Any],
) -> tuple[PurePosixPath, Path, list[dict[str, str]]]:
    source_relative, source_path = _experiment_file(
        workspace,
        source,
        profile,
        source=True,
    )
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in [source, *inputs]:
        relative, path = _experiment_file(workspace, value, profile, source=value == source)
        normalized = relative.as_posix()
        if normalized in seen:
            continue
        seen.add(normalized)
        entries.append({"path": normalized, "sha256": _sha256(path)})
    if len(entries) > 128:
        raise ValueError("a computation receipt may contain at most 128 input files")
    return source_relative, source_path, entries


def _validate_exact_output(payload: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != profile.get("output_schema"):
        errors.append("Sage exact output has an unsupported schema")
    if payload.get("status") != "passed":
        errors.append("Sage exact output did not pass")
    if payload.get("evidence_class") != profile["evidence_class"]:
        errors.append("Sage exact output has the wrong evidence class")
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("Sage exact output has no claims")
    else:
        for index, claim in enumerate(claims):
            if (
                not isinstance(claim, dict)
                or not isinstance(claim.get("claim_id"), str)
                or not claim["claim_id"]
                or not isinstance(claim.get("statement"), str)
                or not claim["statement"]
                or claim.get("exact") is not True
            ):
                errors.append(f"Sage exact claim {index} is not a typed exact claim")
    return errors


def _finite_decimal(value: Any) -> Decimal | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _validate_arb_output(payload: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != profile.get("output_schema"):
        errors.append("Arb output has an unsupported schema")
    if payload.get("status") != "passed":
        errors.append("Arb output did not pass")
    if payload.get("evidence_class") != profile["evidence_class"]:
        errors.append("Arb output has the wrong evidence class")
    certificates = payload.get("certificates")
    if not isinstance(certificates, list) or not certificates:
        return [*errors, "Arb output has no interval certificates"]
    for index, certificate in enumerate(certificates):
        if not isinstance(certificate, dict):
            errors.append(f"Arb certificate {index} must be an object")
            continue
        if (
            not isinstance(certificate.get("certificate_id"), str)
            or not certificate["certificate_id"]
            or not isinstance(certificate.get("statement"), str)
            or not certificate["statement"]
            or not isinstance(certificate.get("precision_bits"), int)
            or isinstance(certificate.get("precision_bits"), bool)
            or certificate["precision_bits"] < 53
        ):
            errors.append(f"Arb certificate {index} has invalid identity or precision")
        intervals = certificate.get("intervals")
        if not isinstance(intervals, list) or not intervals:
            errors.append(f"Arb certificate {index} has no intervals")
            continue
        for interval_index, interval in enumerate(intervals):
            if not isinstance(interval, dict) or not isinstance(interval.get("quantity"), str):
                errors.append(f"Arb certificate {index} interval {interval_index} is invalid")
                continue
            lower = _finite_decimal(interval.get("lower"))
            upper = _finite_decimal(interval.get("upper"))
            if lower is None or upper is None or lower > upper:
                errors.append(
                    f"Arb certificate {index} interval {interval_index} has invalid bounds"
                )
    return errors


def _run_sage(
    source_path: Path,
    profile: dict[str, Any],
    engines: list[dict[str, Any]],
    limits: ResourceLimits,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    executable = str(engines[0]["executable"])
    completed = run_guarded(
        [executable, str(source_path)],
        cwd=source_path.parent,
        limits=limits,
    )
    errors: list[str] = []
    if completed.timed_out:
        errors.append("Sage experiment exceeded its wall-time limit")
    if completed.output_overflow:
        errors.append("Sage experiment exceeded its captured-output limit")
    if completed.returncode != 0:
        errors.append(
            f"Sage experiment exited {completed.returncode}: "
            f"{(completed.stderr or completed.stdout)[-2000:]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        payload = {}
        errors.append(f"Sage experiment emitted invalid JSON: {exc}")
    if not isinstance(payload, dict):
        payload = {}
        errors.append("Sage experiment output must be a JSON object")
    if profile["mode"] == "sage-json":
        errors.extend(_validate_exact_output(payload, profile))
    else:
        errors.extend(_validate_arb_output(payload, profile))
    engine_runs = [
        {
            **engines[0],
            "returncode": completed.returncode,
            "stdout_sha256": _text_sha256(completed.stdout),
            "stderr_sha256": _text_sha256(completed.stderr),
        }
    ]
    return payload, engine_runs, errors


def _smt_decisions(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip() in DECISIONS]


def _run_smt(
    source_path: Path,
    engines: list[dict[str, Any]],
    limits: ResourceLimits,
    expected: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    engine_runs: list[dict[str, Any]] = []
    all_decisions: list[list[str]] = []
    per_engine_limits = replace(
        limits,
        cpu_seconds=max(1, limits.cpu_seconds // len(engines)),
        wall_seconds=max(1, limits.wall_seconds // len(engines)),
    )
    for engine in engines:
        engine_id = str(engine["engine_id"])
        executable = str(engine["executable"])
        command = (
            [executable, "-smt2", str(source_path)]
            if engine_id == "z3"
            else [executable, "--lang=smt2", str(source_path)]
        )
        completed = run_guarded(
            command,
            cwd=source_path.parent,
            limits=per_engine_limits,
        )
        decisions = _smt_decisions(completed.stdout)
        all_decisions.append(decisions)
        if completed.timed_out:
            errors.append(f"SMT engine {engine_id} exceeded its wall-time limit")
        if completed.output_overflow:
            errors.append(f"SMT engine {engine_id} exceeded its output limit")
        if completed.returncode != 0:
            errors.append(
                f"SMT engine {engine_id} exited {completed.returncode}: "
                f"{(completed.stderr or completed.stdout)[-2000:]}"
            )
        if not decisions:
            errors.append(f"SMT engine {engine_id} emitted no decision")
        engine_runs.append(
            {
                **engine,
                "returncode": completed.returncode,
                "decisions": decisions,
                "stdout_sha256": _text_sha256(completed.stdout),
                "stderr_sha256": _text_sha256(completed.stderr),
            }
        )
    consensus = bool(all_decisions) and all(
        decisions == all_decisions[0] for decisions in all_decisions[1:]
    )
    if not consensus:
        errors.append("Z3 and cvc5 did not reach the same SMT decision sequence")
    decisions = all_decisions[0] if all_decisions else []
    if expected and any(item != expected for item in decisions):
        errors.append(f"SMT decision differs from expected {expected}")
    return {
        "consensus": consensus,
        "decisions": decisions,
        "expected": expected,
        "scope": "finite or finitely encoded constraints only",
    }, engine_runs, errors


def _execute(
    workspace: Path,
    profile_id: str,
    *,
    source: str,
    inputs: list[str],
    timeout: int,
    expected: str | None,
) -> tuple[dict[str, Any], list[str]]:
    prepared, profile, prepared_path = _prepared_runtime(
        workspace,
        profile_id,
        timeout=timeout,
    )
    source_relative, source_path, input_entries = _input_closure(
        workspace,
        source,
        inputs,
        profile,
    )
    limits = _limits(profile, timeout)
    engines = prepared["engines"]
    if profile["mode"] in {"sage-json", "arb-json"}:
        result, engine_runs, errors = _run_sage(source_path, profile, engines, limits)
    else:
        result, engine_runs, errors = _run_smt(
            source_path,
            engines,
            limits,
            expected,
        )
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "run",
        "--profile",
        profile_id,
        "--workspace",
        str(workspace),
        "--source",
        source,
    ]
    for item in inputs:
        command.extend(["--input", item])
    if expected:
        command.extend(["--expect", expected])
    payload = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "passed" if not errors else "failed",
        "profile_id": profile_id,
        "evidence_class": profile["evidence_class"],
        "source": source_relative.as_posix(),
        "inputs": input_entries,
        "engines": engine_runs,
        "result": result,
        "command": command,
        "profile_sha256": _profile_sha256(profile_id, profile),
        "prepared_runtime_sha256": _sha256(prepared_path),
        "resource_limits": limits.to_dict(),
        "verified_at": _utc_now(),
    }
    return payload, errors


def run(
    workspace: Path,
    profile_id: str,
    *,
    source: str,
    inputs: list[str],
    receipt: str,
    timeout: int,
    expected: str | None,
) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    profile = _profile(profile_id)
    receipt_relative = _safe_relative(receipt, suffix=".json")
    if not _under_root(receipt_relative, profile["source_root"]):
        raise ValueError(
            f"computation receipt for this profile must live under {profile['source_root']}"
        )
    payload, errors = _execute(
        root,
        profile_id,
        source=source,
        inputs=inputs,
        timeout=timeout,
        expected=expected,
    )
    if errors:
        return {"valid": False, "errors": errors, "details": payload}
    path = _atomic_write_json(root / receipt_relative, payload)
    return {
        "valid": True,
        "errors": [],
        "receipt_path": str(path),
        "receipt_sha256": _sha256(path),
        "details": payload,
    }


def check_receipt(
    workspace: Path,
    receipt: str,
    *,
    replay: bool,
    timeout: int = 600,
) -> list[str]:
    root = workspace.expanduser().resolve()
    relative = _safe_relative(receipt, suffix=".json")
    path = (root / relative).resolve()
    if not path.is_file() or path.is_symlink() or not path.is_relative_to(root):
        return [f"mathematics computation receipt is missing or unsafe: {relative}"]
    try:
        value = _read_object(path)
        profile_id = str(value.get("profile_id") or "")
        prepared, profile, prepared_path = _prepared_runtime(
            root,
            profile_id,
            timeout=timeout,
        )
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    errors: list[str] = []
    if value.get("schema_version") != RECEIPT_SCHEMA or value.get("status") != "passed":
        errors.append("mathematics computation receipt is not a passed v1 receipt")
    if not _under_root(relative, profile["source_root"]):
        errors.append("mathematics computation receipt is outside its profile experiment root")
    if value.get("profile_sha256") != _profile_sha256(profile_id, profile):
        errors.append("mathematics computation receipt profile differs")
    if value.get("evidence_class") != profile["evidence_class"]:
        errors.append("mathematics computation receipt evidence class differs")
    if value.get("prepared_runtime_sha256") != _sha256(prepared_path):
        errors.append("mathematics computation prepared runtime differs")
    raw_inputs = value.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        errors.append("mathematics computation receipt has no input closure")
        raw_inputs = []
    for item in raw_inputs:
        if not isinstance(item, dict):
            errors.append("mathematics computation input must be an object")
            continue
        try:
            relative_input, input_path = _experiment_file(
                root,
                str(item.get("path") or ""),
                profile,
                source=item.get("path") == value.get("source"),
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if item.get("sha256") != _sha256(input_path):
            errors.append(f"mathematics computation input hash differs: {relative_input}")
    if not any(
        isinstance(item, dict) and item.get("path") == value.get("source")
        for item in raw_inputs
    ):
        errors.append("mathematics computation input closure omits its source")
    receipt_limits = value.get("resource_limits")
    prepared_limits = prepared.get("resource_limits")
    if not isinstance(receipt_limits, dict) or not isinstance(prepared_limits, dict):
        errors.append("mathematics computation resource limits are missing")
    elif any(
        not isinstance(receipt_limits.get(field), int)
        or receipt_limits[field] < 1
        or receipt_limits[field] > prepared_limits.get(field, 0)
        for field in (
            "memory_mib",
            "cpu_seconds",
            "wall_seconds",
            "file_mib",
            "open_files",
            "threads",
            "output_mib",
            "address_space_mib",
            "processes",
        )
    ):
        errors.append("mathematics computation resource limits exceed the prepared ceiling")
    if replay and not errors:
        inputs = [
            str(item["path"])
            for item in raw_inputs
            if isinstance(item, dict) and item.get("path") != value.get("source")
        ]
        expected = None
        result_value = value.get("result")
        if isinstance(result_value, dict) and isinstance(result_value.get("expected"), str):
            expected = result_value["expected"]
        replay_timeout = int(receipt_limits["wall_seconds"])
        replayed, replay_errors = _execute(
            root,
            profile_id,
            source=str(value.get("source") or ""),
            inputs=inputs,
            timeout=min(timeout, replay_timeout),
            expected=expected,
        )
        errors.extend(replay_errors)
        for field in ("inputs", "engines", "result", "resource_limits"):
            if replayed.get(field) != value.get(field):
                errors.append(f"mathematics computation replay differs: {field}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--profile", required=True)
    status.add_argument("--timeout", type=int, default=60)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--profile", required=True)
    prepare.add_argument("--agent-workspace", type=Path, required=True)
    prepare.add_argument("--timeout", type=int, default=60)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--profile", required=True)
    run_parser.add_argument("--workspace", type=Path, required=True)
    run_parser.add_argument("--source", required=True)
    run_parser.add_argument("--input", action="append", default=[])
    run_parser.add_argument("--receipt", required=True)
    run_parser.add_argument("--timeout", type=int, default=600)
    run_parser.add_argument("--expect", choices=sorted(DECISIONS))
    check = subparsers.add_parser("check")
    check.add_argument("--workspace", type=Path, required=True)
    check.add_argument("--receipt", required=True)
    check.add_argument("--replay", action="store_true")
    check.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    try:
        if args.command == "status":
            profile = _profile(args.profile)
            result = {
                "valid": True,
                "profile_id": args.profile,
                "evidence_class": profile["evidence_class"],
                "engines": _probe_engines(args.profile, profile, timeout=args.timeout),
                "resource_limits": _limits(
                    profile,
                    profile["resource_limits"]["wall_seconds"],
                ).to_dict(),
            }
        elif args.command == "prepare":
            result = prepare_attempt(
                args.agent_workspace,
                args.profile,
                timeout=args.timeout,
            )
        elif args.command == "run":
            result = run(
                args.workspace,
                args.profile,
                source=args.source,
                inputs=args.input,
                receipt=args.receipt,
                timeout=args.timeout,
                expected=args.expect,
            )
        else:
            errors = check_receipt(
                args.workspace,
                args.receipt,
                replay=args.replay,
                timeout=args.timeout,
            )
            result = {"valid": not errors, "errors": errors}
    except Exception as exc:  # noqa: BLE001 - CLI returns a typed fail-closed result.
        result = {"valid": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
