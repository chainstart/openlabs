#!/usr/bin/env python3
"""Provision and verify attempt-local Lean proofs against a pinned Mathlib runtime."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


PROFILE_SCHEMA = "openlabs.lean_profile.v1"
RUNTIME_SCHEMA = "openlabs.lean_runtime.v1"
PREPARED_SCHEMA = "openlabs.lean_runtime_prepared.v1"
RECEIPT_SCHEMA = "openlabs.lean_verification.v1"
FORMAL_ROOT = PurePosixPath("formal/lean")
SCRIPT_PATH = Path(__file__).resolve()
FORMAL_TOOL_ROOT = SCRIPT_PATH.parent
MATH_TOOLS_ROOT = FORMAL_TOOL_ROOT.parent
PROFILE_PATH = FORMAL_TOOL_ROOT / "lean-profile.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
sys.path.insert(0, str(MATH_TOOLS_ROOT))

from runtime_guard import (  # noqa: E402
    GuardedResult,
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


def _profile() -> dict[str, Any]:
    value = _read_object(PROFILE_PATH)
    if value.get("schema_version") != PROFILE_SCHEMA:
        raise ValueError("unsupported Lean profile schema")
    for field in ("profile_id", "toolchain", "mathlib_revision", "template"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"Lean profile {field} is required")
    axioms = value.get("allowed_axioms")
    if not isinstance(axioms, list) or any(not isinstance(item, str) for item in axioms):
        raise ValueError("Lean profile allowed_axioms must be a string array")
    limits = value.get("resource_limits")
    if not isinstance(limits, dict):
        raise ValueError("Lean profile resource_limits must be an object")
    for phase in ("verification", "provisioning"):
        configured = limits.get(phase)
        if not isinstance(configured, dict):
            raise ValueError(f"Lean profile has invalid {phase} resource limits")
        if any(
            not isinstance(configured.get(field), int)
            or isinstance(configured.get(field), bool)
            or configured[field] < 1
            for field in ("cpu_seconds", "wall_seconds", "file_mib", "output_mib")
        ):
            raise ValueError(f"Lean profile has invalid {phase} resource limits")
        for absolute, fractional in (
            ("memory_mib", "memory_fraction_of_host"),
            ("threads", "threads_fraction_of_host"),
        ):
            absolute_value = configured.get(absolute)
            fraction_value = configured.get(fractional)
            absolute_valid = (
                isinstance(absolute_value, int)
                and not isinstance(absolute_value, bool)
                and absolute_value > 0
            )
            fraction_valid = (
                isinstance(fraction_value, (int, float))
                and not isinstance(fraction_value, bool)
                and 0 < float(fraction_value) <= 0.8
            )
            if not absolute_valid and not fraction_valid:
                raise ValueError(
                    f"Lean profile {phase} requires a valid {absolute} or {fractional}"
                )
    return value


def _resource_limits(
    profile: dict[str, Any],
    phase: str,
    wall_seconds: int,
):
    configured = profile["resource_limits"][phase]
    return limits_from_environment(
        wall_seconds=min(wall_seconds, configured["wall_seconds"]),
        max_memory_mib=configured.get("memory_mib"),
        memory_fraction_of_host=configured.get("memory_fraction_of_host"),
        max_cpu_seconds=configured["cpu_seconds"],
        max_file_mib=configured["file_mib"],
        max_threads=configured.get("threads"),
        threads_fraction_of_host=configured.get("threads_fraction_of_host"),
        output_mib=configured["output_mib"],
        # Task resources are scheduler reservations. Lean has its own host-relative
        # cgroup ceiling and must not be hard-capped by a routine 4 GiB reservation.
        respect_task_reservations=False,
    )


def _default_artifacts_root() -> Path:
    configured = os.environ.get("OPENLABS_ARTIFACTS_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    code_root = FORMAL_TOOL_ROOT.parents[3]
    return (code_root.parent / "openlabs-artifacts").resolve()


def _runtime_root(artifacts_root: Path, profile: dict[str, Any]) -> Path:
    return artifacts_root.expanduser().resolve() / "toolchains" / str(profile["profile_id"])


def _runtime_metadata_path(runtime: Path) -> Path:
    return runtime / "openlabs-lean-runtime.json"


def _runtime_errors(runtime: Path, profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    template = (FORMAL_TOOL_ROOT / str(profile["template"])).resolve()
    metadata_path = _runtime_metadata_path(runtime)
    try:
        metadata = _read_object(metadata_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [f"missing or invalid Lean runtime metadata: {exc}"]
    if metadata.get("schema_version") != RUNTIME_SCHEMA:
        errors.append("unsupported Lean runtime schema")
    if metadata.get("profile_sha256") != _sha256(PROFILE_PATH):
        errors.append("Lean runtime profile hash differs from the trusted profile")
    if metadata.get("profile_id") != profile["profile_id"]:
        errors.append("Lean runtime profile id differs")
    required = (
        runtime / "lean-toolchain",
        runtime / "lakefile.lean",
        runtime / "lake-manifest.json",
        runtime / ".lake" / "packages" / "mathlib" / "Mathlib.lean",
        runtime
        / ".lake"
        / "packages"
        / "mathlib"
        / ".lake"
        / "build"
        / "lib"
        / "lean"
        / "Mathlib.olean",
    )
    for path in required:
        if not path.is_file():
            errors.append(f"Lean runtime file is missing: {path}")
    for name in ("lean-toolchain", "lakefile.lean", "lake-manifest.json"):
        path = runtime / name
        expected = (metadata.get("config_sha256") or {}).get(name)
        invalid_hash = path.is_file() and (
            not SHA256.fullmatch(str(expected or "")) or _sha256(path) != expected
        )
        if invalid_hash:
            errors.append(f"Lean runtime config hash differs: {name}")
    for name in ("lean-toolchain", "lakefile.lean"):
        path = runtime / name
        trusted = template / name
        if path.is_file() and trusted.is_file() and _sha256(path) != _sha256(trusted):
            errors.append(f"Lean runtime differs from the trusted template: {name}")
    try:
        runtime_manifest = _read_object(runtime / "lake-manifest.json")
        trusted_manifest = _read_object(template / "lake-manifest.json")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Lean runtime manifest comparison failed: {exc}")
    else:
        if runtime_manifest != trusted_manifest:
            errors.append("Lean runtime manifest differs from the trusted template")
        expected_mathlib = next(
            (
                item.get("rev")
                for item in trusted_manifest.get("packages", [])
                if isinstance(item, dict) and item.get("name") == "mathlib"
            ),
            None,
        )
        mathlib_root = runtime / ".lake" / "packages" / "mathlib"
        git = shutil.which("git")
        if not isinstance(expected_mathlib, str) or not expected_mathlib:
            errors.append("trusted Lean manifest has no exact Mathlib commit")
        elif git is None:
            errors.append("git is unavailable for Mathlib commit verification")
        elif mathlib_root.is_dir():
            completed = subprocess.run(
                [git, "rev-parse", "HEAD"],
                cwd=mathlib_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if completed.returncode != 0 or completed.stdout.strip() != expected_mathlib:
                errors.append("installed Mathlib commit differs from the trusted manifest")
    return errors


def _run_checked(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    environment: dict[str, str] | None = None,
    provisioning: bool = False,
) -> GuardedResult:
    limits = _resource_limits(
        _profile(),
        "provisioning" if provisioning else "verification",
        timeout,
    )
    completed = run_guarded(
        command,
        cwd=cwd,
        limits=limits,
        environment=environment,
    )
    if completed.returncode != 0 or completed.timed_out or completed.output_overflow:
        detail = (completed.stderr or completed.stdout).strip()
        failure = "wall timeout" if completed.timed_out else f"exit {completed.returncode}"
        if completed.output_overflow:
            failure += ", output limit exceeded"
        raise RuntimeError(
            f"command failed ({failure}): {' '.join(command)}: {detail[-2000:]}"
        )
    return completed


def provision_runtime(artifacts_root: Path, *, timeout: int = 1800) -> dict[str, Any]:
    """Materialize one content-pinned shared runtime, serialized across workers."""

    profile = _profile()
    runtime = _runtime_root(artifacts_root, profile)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    lock_path = runtime.parent / f".{profile['profile_id']}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        errors = _runtime_errors(runtime, profile) if runtime.exists() else ["not provisioned"]
        if errors == ["Lean runtime profile hash differs from the trusted profile"]:
            metadata = _read_object(_runtime_metadata_path(runtime))
            metadata["profile_sha256"] = _sha256(PROFILE_PATH)
            metadata["policy_refreshed_at"] = _utc_now()
            _atomic_write_json(_runtime_metadata_path(runtime), metadata)
            errors = _runtime_errors(runtime, profile)
        if not errors:
            return {
                "valid": True,
                "profile_id": profile["profile_id"],
                "runtime_root": str(runtime),
                "reused": True,
            }
        if runtime.exists():
            raise RuntimeError("existing Lean runtime is invalid: " + "; ".join(errors))
        elan = shutil.which("elan")
        if elan is None:
            raise RuntimeError("elan is unavailable")
        template = FORMAL_TOOL_ROOT / str(profile["template"])
        staging = Path(tempfile.mkdtemp(prefix=f".{profile['profile_id']}.", dir=runtime.parent))
        try:
            for name in ("lean-toolchain", "lakefile.lean", "lake-manifest.json"):
                shutil.copy2(template / name, staging / name)
            environment = dict(os.environ)
            environment.setdefault("LEAN_NUM_THREADS", "2")
            environment.setdefault("OMP_NUM_THREADS", "2")
            toolchain = str(profile["toolchain"])
            version = _run_checked(
                [elan, "run", toolchain, "lean", "--version"],
                cwd=staging,
                timeout=60,
                environment=environment,
                provisioning=True,
            ).stdout.strip()
            _run_checked(
                [elan, "run", toolchain, "lake", "update"],
                cwd=staging,
                timeout=timeout,
                environment=environment,
                provisioning=True,
            )
            cache = _run_checked(
                [elan, "run", toolchain, "lake", "exe", "cache", "get"],
                cwd=staging,
                timeout=timeout,
                environment=environment,
                provisioning=True,
            )
            metadata = {
                "schema_version": RUNTIME_SCHEMA,
                "profile_id": profile["profile_id"],
                "profile_sha256": _sha256(PROFILE_PATH),
                "toolchain": toolchain,
                "lean_version": version,
                "mathlib_revision": profile["mathlib_revision"],
                "config_sha256": {
                    name: _sha256(staging / name)
                    for name in ("lean-toolchain", "lakefile.lean", "lake-manifest.json")
                },
                "cache_stdout_sha256": _text_sha256(cache.stdout),
                "cache_stderr_sha256": _text_sha256(cache.stderr),
                "provisioned_at": _utc_now(),
            }
            _atomic_write_json(_runtime_metadata_path(staging), metadata)
            os.replace(staging, runtime)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        final_errors = _runtime_errors(runtime, profile)
        if final_errors:
            raise RuntimeError("provisioned Lean runtime is incomplete: " + "; ".join(final_errors))
        return {
            "valid": True,
            "profile_id": profile["profile_id"],
            "runtime_root": str(runtime),
            "reused": False,
        }


def prepare_attempt(agent_workspace: Path, artifacts_root: Path, *, timeout: int) -> dict[str, Any]:
    workspace = agent_workspace.expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"agent workspace does not exist: {workspace}")
    provisioned = provision_runtime(artifacts_root, timeout=timeout)
    profile = _profile()
    runtime = Path(str(provisioned["runtime_root"])).resolve()
    metadata = _read_object(_runtime_metadata_path(runtime))
    receipt = {
        "schema_version": PREPARED_SCHEMA,
        "profile_id": profile["profile_id"],
        "profile_sha256": _sha256(PROFILE_PATH),
        "runtime_root": str(runtime),
        "runtime_sha256": _sha256(_runtime_metadata_path(runtime)),
        "toolchain": profile["toolchain"],
        "mathlib_revision": profile["mathlib_revision"],
        "lean_version": metadata["lean_version"],
        "verifier": str(SCRIPT_PATH),
        "source_root": "formal/lean",
        "resource_limits": _resource_limits(
            profile,
            "verification",
            profile["resource_limits"]["verification"]["wall_seconds"],
        ).to_dict(),
        "prepared_at": _utc_now(),
    }
    receipt_path = _atomic_write_json(
        workspace / ".openlabs" / "tools" / "lean-runtime.json",
        receipt,
    )
    return {
        "valid": True,
        "profile_id": profile["profile_id"],
        "receipt_path": str(receipt_path),
        "runtime_root": str(runtime),
        "lean_version": metadata["lean_version"],
        "mathlib_revision": profile["mathlib_revision"],
        "resource_limits": receipt["resource_limits"],
        "reused": provisioned["reused"],
    }


def _safe_relative(value: str, *, suffix: str | None = None) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value.strip() or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must be workspace-relative: {value!r}")
    if suffix is not None and path.suffix != suffix:
        raise ValueError(f"path must end in {suffix}: {value!r}")
    return path


def _formal_source(workspace: Path, value: str) -> tuple[PurePosixPath, Path]:
    relative = _safe_relative(value, suffix=".lean")
    if not any(
        relative.parts[index : index + 2] == FORMAL_ROOT.parts
        for index in range(max(0, len(relative.parts) - 1))
    ):
        raise ValueError("Lean sources must live in a formal/lean directory")
    path = (workspace / relative).resolve()
    if not path.is_file() or path.is_symlink() or not path.is_relative_to(workspace):
        raise ValueError(f"Lean source is missing or unsafe: {relative}")
    return relative, path


def _formal_root(relative: PurePosixPath) -> PurePosixPath:
    for index in range(len(relative.parts) - 1):
        if relative.parts[index : index + 2] == FORMAL_ROOT.parts:
            return PurePosixPath(*relative.parts[: index + 2])
    raise ValueError(f"Lean source is outside a formal/lean directory: {relative}")


def _prepared_runtime(workspace: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    prepared = _read_object(workspace / ".openlabs" / "tools" / "lean-runtime.json")
    profile = _profile()
    if prepared.get("schema_version") != PREPARED_SCHEMA:
        raise ValueError("attempt has no supported Lean runtime receipt")
    if prepared.get("profile_sha256") != _sha256(PROFILE_PATH):
        raise ValueError("attempt Lean profile hash differs")
    runtime = Path(str(prepared.get("runtime_root") or "")).resolve()
    errors = _runtime_errors(runtime, profile)
    if errors:
        raise ValueError("Lean runtime is invalid: " + "; ".join(errors))
    if prepared.get("runtime_sha256") != _sha256(_runtime_metadata_path(runtime)):
        raise ValueError("attempt Lean runtime metadata hash differs")
    return prepared, profile, runtime


def _lake_environment(runtime: Path, profile: dict[str, Any]) -> dict[str, str]:
    elan = shutil.which("elan")
    if elan is None:
        raise RuntimeError("elan is unavailable")
    command = [
        elan,
        "run",
        str(profile["toolchain"]),
        "lake",
        "env",
        sys.executable,
        "-c",
        "import json,os; print(json.dumps(dict(os.environ), sort_keys=True))",
    ]
    completed = _run_checked(command, cwd=runtime, timeout=60)
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("lake environment probe did not return an object")
    return {str(key): str(item) for key, item in value.items()}


def _verify_payload_unlocked(
    workspace: Path,
    *,
    main_source: str,
    inputs: list[str],
    declarations: list[str],
    timeout: int,
) -> tuple[dict[str, Any], list[str]]:
    prepared, profile, runtime = _prepared_runtime(workspace)
    main_relative, main_path = _formal_source(workspace, main_source)
    source_root_relative = _formal_root(main_relative)
    source_entries: list[dict[str, str]] = []
    ordered_sources: list[tuple[PurePosixPath, Path]] = []
    seen: set[str] = set()
    for value in [*inputs, main_source]:
        relative, path = _formal_source(workspace, value)
        if value in inputs and relative == main_relative:
            raise ValueError("the main Lean source cannot also be listed as an input")
        if _formal_root(relative) != source_root_relative:
            raise ValueError("all Lean inputs must share the main source's formal/lean root")
        normalized = relative.as_posix()
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered_sources.append((relative, path))
        source_entries.append({"path": normalized, "sha256": _sha256(path)})
    if len(ordered_sources) > 64:
        raise ValueError("a Lean verification may contain at most 64 source files")
    if not declarations or any(not item.strip() for item in declarations):
        raise ValueError("at least one fully qualified Lean declaration is required")
    if len(declarations) != len(set(declarations)):
        raise ValueError("Lean declarations cannot be duplicated")
    environment = _lake_environment(runtime, profile)
    environment["LEAN_NUM_THREADS"] = os.environ.get("LEAN_NUM_THREADS", "2")
    environment["OMP_NUM_THREADS"] = environment["LEAN_NUM_THREADS"]
    elan = shutil.which("elan")
    if elan is None:
        raise RuntimeError("elan is unavailable")
    outputs: list[GuardedResult] = []
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix="openlabs-lean-audit-") as temporary:
        audit_root = Path(temporary).resolve()
        for relative, path in ordered_sources:
            local = relative.relative_to(source_root_relative)
            target = audit_root / local
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        audit_path = audit_root / main_relative.relative_to(source_root_relative)
        audit_path.write_text(
            main_path.read_text(encoding="utf-8")
            + "\n"
            + "\n".join(f"#print axioms {item.strip()}" for item in declarations)
            + "\n",
            encoding="utf-8",
        )
        prior_lean_path = environment.get("LEAN_PATH", "")
        environment["LEAN_PATH"] = (
            str(audit_root) + (os.pathsep + prior_lean_path if prior_lean_path else "")
        )
        initial_limits = _resource_limits(profile, "verification", timeout)
        base_command = [
            elan,
            "run",
            str(profile["toolchain"]),
            "lean",
            "-E",
            "lean.sorry",
            "--json",
            "-M",
            str(initial_limits.memory_mib),
            "-j",
            str(initial_limits.threads),
            f"--root={audit_root}",
        ]
        for relative, _ in ordered_sources[:-1]:
            local = relative.relative_to(source_root_relative)
            source_path = audit_root / local
            output_path = source_path.with_suffix(".olean")
            remaining = max(1, int(deadline - time.monotonic()))
            completed_input = run_guarded(
                [*base_command, "-o", str(output_path), str(source_path)],
                cwd=audit_root,
                limits=_resource_limits(profile, "verification", remaining),
                environment=environment,
            )
            outputs.append(completed_input)
            if (
                completed_input.returncode != 0
                or completed_input.timed_out
                or completed_input.output_overflow
            ):
                break
        else:
            remaining = max(1, int(deadline - time.monotonic()))
            outputs.append(
                run_guarded(
                    [*base_command, str(audit_path)],
                    cwd=audit_root,
                    limits=_resource_limits(profile, "verification", remaining),
                    environment=environment,
                )
            )
    combined_stdout = "\n".join(item.stdout for item in outputs)
    combined_stderr = "\n".join(item.stderr for item in outputs)
    combined = combined_stdout + "\n" + combined_stderr
    errors: list[str] = []
    failed = next((item for item in outputs if item.returncode != 0), None)
    if failed is not None:
        detail = (failed.stderr or failed.stdout).strip()
        suffix = f": {detail[-2000:]}" if detail else ""
        errors.append(f"Lean kernel check exited {failed.returncode}{suffix}")
    if any(item.timed_out for item in outputs):
        errors.append("Lean kernel check exceeded its wall-time limit")
    if any(item.output_overflow for item in outputs):
        errors.append("Lean kernel check exceeded its captured-output limit")
    observed_axioms: set[str] = set()
    for match in re.finditer(r"depends on axioms:\s*\[([^\]]*)\]", combined):
        observed_axioms.update(
            item.strip().strip("'\"")
            for item in match.group(1).split(",")
            if item.strip()
        )
    allowed_axioms = {str(item) for item in profile["allowed_axioms"]}
    forbidden_axioms = observed_axioms - allowed_axioms
    if forbidden_axioms:
        errors.append("forbidden Lean axioms: " + ", ".join(sorted(forbidden_axioms)))
    if "sorryAx" in combined:
        errors.append("Lean proof depends on sorryAx")
    for declaration in declarations:
        if declaration not in combined:
            errors.append(f"Lean emitted no axiom audit for declaration {declaration}")
    runtime_metadata = _read_object(_runtime_metadata_path(runtime))
    verify_command = [
        sys.executable,
        str(SCRIPT_PATH),
        "verify",
        "--workspace",
        str(workspace),
        "--source",
        main_source,
    ]
    for value in inputs:
        verify_command.extend(["--input", value])
    for declaration in declarations:
        verify_command.extend(["--declaration", declaration])
    payload = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "passed" if not errors else "failed",
        "profile_id": profile["profile_id"],
        "toolchain": profile["toolchain"],
        "lean_version": prepared["lean_version"],
        "mathlib_revision": profile["mathlib_revision"],
        "main_source": main_relative.as_posix(),
        "inputs": source_entries,
        "declarations": [item.strip() for item in declarations],
        "allowed_axioms": sorted(allowed_axioms),
        "observed_axioms": sorted(observed_axioms),
        "command": verify_command,
        "profile_sha256": _sha256(PROFILE_PATH),
        "runtime_sha256": _sha256(_runtime_metadata_path(runtime)),
        "runtime_config_sha256": runtime_metadata["config_sha256"],
        "resource_limits": initial_limits.to_dict(),
        "stdout_sha256": _text_sha256(combined_stdout),
        "stderr_sha256": _text_sha256(combined_stderr),
        "verified_at": _utc_now(),
    }
    return payload, errors


def _verify_payload(
    workspace: Path,
    *,
    main_source: str,
    inputs: list[str],
    declarations: list[str],
    timeout: int,
) -> tuple[dict[str, Any], list[str]]:
    """Serialize high-memory Lean checks while leaving other research concurrent."""

    _, profile, _ = _prepared_runtime(workspace)
    lock_path = Path(tempfile.gettempdir()) / (
        f"openlabs-lean-{os.getuid()}-{profile['profile_id']}.lock"
    )
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _verify_payload_unlocked(
            workspace,
            main_source=main_source,
            inputs=inputs,
            declarations=declarations,
            timeout=timeout,
        )


def verify(
    workspace: Path,
    *,
    source: str,
    inputs: list[str],
    declarations: list[str],
    receipt: str,
    timeout: int,
) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    receipt_relative = _safe_relative(receipt, suffix=".json")
    if not any(
        receipt_relative.parts[index : index + 2] == FORMAL_ROOT.parts
        for index in range(max(0, len(receipt_relative.parts) - 1))
    ):
        raise ValueError("Lean verification receipt must live in a formal/lean directory")
    payload, errors = _verify_payload(
        root,
        main_source=source,
        inputs=inputs,
        declarations=declarations,
        timeout=timeout,
    )
    if errors:
        return {"valid": False, "errors": errors, "details": payload}
    receipt_path = _atomic_write_json(root / receipt_relative, payload)
    return {
        "valid": True,
        "errors": [],
        "receipt_path": str(receipt_path),
        "receipt_sha256": _sha256(receipt_path),
        "details": payload,
    }


def check_receipt(
    workspace: Path,
    receipt: str,
    *,
    replay: bool,
    timeout: int = 300,
) -> list[str]:
    root = workspace.expanduser().resolve()
    relative = _safe_relative(receipt, suffix=".json")
    if not any(
        relative.parts[index : index + 2] == FORMAL_ROOT.parts
        for index in range(max(0, len(relative.parts) - 1))
    ):
        return ["Lean receipt must live in a formal/lean directory"]
    path = (root / relative).resolve()
    if not path.is_file() or path.is_symlink() or not path.is_relative_to(root):
        return [f"Lean receipt is missing or unsafe: {relative}"]
    try:
        value = _read_object(path)
        prepared, profile, runtime = _prepared_runtime(root)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    errors: list[str] = []
    if value.get("schema_version") != RECEIPT_SCHEMA or value.get("status") != "passed":
        errors.append("Lean receipt is not a passed v1 receipt")
    if value.get("profile_sha256") != _sha256(PROFILE_PATH):
        errors.append("Lean receipt profile hash differs")
    if value.get("profile_id") != profile.get("profile_id"):
        errors.append("Lean receipt profile id differs")
    if value.get("toolchain") != profile.get("toolchain"):
        errors.append("Lean receipt toolchain differs")
    if value.get("mathlib_revision") != profile.get("mathlib_revision"):
        errors.append("Lean receipt Mathlib revision differs")
    if value.get("runtime_sha256") != _sha256(_runtime_metadata_path(runtime)):
        errors.append("Lean receipt runtime hash differs")
    if value.get("lean_version") != prepared.get("lean_version"):
        errors.append("Lean receipt compiler version differs")
    runtime_metadata = _read_object(_runtime_metadata_path(runtime))
    if value.get("runtime_config_sha256") != runtime_metadata.get("config_sha256"):
        errors.append("Lean receipt runtime configuration differs")
    allowed_axioms = value.get("allowed_axioms")
    if allowed_axioms != sorted(str(item) for item in profile["allowed_axioms"]):
        errors.append("Lean receipt allowed-axiom policy differs")
    observed_axioms = value.get("observed_axioms")
    if not isinstance(observed_axioms, list) or any(
        not isinstance(item, str) for item in observed_axioms
    ):
        errors.append("Lean receipt observed axioms must be a string array")
    elif set(observed_axioms) - set(profile["allowed_axioms"]):
        errors.append("Lean receipt contains a forbidden axiom")
    receipt_limits = value.get("resource_limits")
    prepared_limits = prepared.get("resource_limits")
    if not isinstance(receipt_limits, dict) or not isinstance(prepared_limits, dict):
        errors.append("Lean receipt resource limits are missing")
    elif any(
        not isinstance(receipt_limits.get(field), int)
        or receipt_limits[field] < 1
        or receipt_limits[field] > prepared_limits.get(field, 0)
        for field in prepared_limits
    ):
        errors.append("Lean receipt resource limits exceed the prepared ceiling")
    raw_inputs = value.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        errors.append("Lean receipt has no input closure")
        raw_inputs = []
    for item in raw_inputs:
        if not isinstance(item, dict):
            errors.append("Lean receipt input must be an object")
            continue
        try:
            input_relative, input_path = _formal_source(root, str(item.get("path") or ""))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if item.get("sha256") != _sha256(input_path):
            errors.append(f"Lean input hash differs: {input_relative}")
    if not any(
        isinstance(item, dict) and item.get("path") == value.get("main_source")
        for item in raw_inputs
    ):
        errors.append("Lean receipt input closure does not contain its main source")
    declarations = value.get("declarations")
    if not isinstance(declarations, list) or any(not isinstance(item, str) for item in declarations):
        errors.append("Lean receipt declarations must be a string array")
        declarations = []
    if replay and not errors:
        inputs = [
            str(item["path"])
            for item in raw_inputs
            if isinstance(item, dict) and item.get("path") != value.get("main_source")
        ]
        try:
            replayed, replay_errors = _verify_payload(
                root,
                main_source=str(value.get("main_source") or ""),
                inputs=inputs,
                declarations=[str(item) for item in declarations],
                timeout=min(timeout, int(receipt_limits["wall_seconds"])),
            )
        except (OSError, RuntimeError, TypeError, ValueError, subprocess.TimeoutExpired) as exc:
            errors.append(f"Lean replay failed: {exc}")
        else:
            errors.extend(replay_errors)
            if replayed["inputs"] != value.get("inputs"):
                errors.append("Lean replay input closure differs from the receipt")
            if replayed["observed_axioms"] != value.get("observed_axioms"):
                errors.append("Lean replay axiom set differs from the receipt")
            if replayed["resource_limits"] != value.get("resource_limits"):
                errors.append("Lean replay resource limits differ from the receipt")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "provision"):
        command = subparsers.add_parser(name)
        command.add_argument("--artifacts-root", type=Path, default=_default_artifacts_root())
        command.add_argument("--timeout", type=int, default=1800)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--agent-workspace", type=Path, required=True)
    prepare.add_argument("--artifacts-root", type=Path, default=_default_artifacts_root())
    prepare.add_argument("--timeout", type=int, default=1800)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--workspace", type=Path, required=True)
    verify_parser.add_argument("--source", required=True)
    verify_parser.add_argument("--input", action="append", default=[])
    verify_parser.add_argument("--declaration", action="append", default=[])
    verify_parser.add_argument("--receipt", default="formal/lean/verification.json")
    verify_parser.add_argument("--timeout", type=int, default=300)
    check = subparsers.add_parser("check")
    check.add_argument("--workspace", type=Path, required=True)
    check.add_argument("--receipt", required=True)
    check.add_argument("--replay", action="store_true")
    check.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    try:
        if args.command == "status":
            profile = _profile()
            runtime = _runtime_root(args.artifacts_root, profile)
            errors = _runtime_errors(runtime, profile)
            result = {
                "valid": not errors,
                "errors": errors,
                "profile_id": profile["profile_id"],
                "runtime_root": str(runtime),
            }
        elif args.command == "provision":
            result = provision_runtime(args.artifacts_root, timeout=args.timeout)
        elif args.command == "prepare":
            result = prepare_attempt(
                args.agent_workspace,
                args.artifacts_root,
                timeout=args.timeout,
            )
        elif args.command == "verify":
            result = verify(
                args.workspace,
                source=args.source,
                inputs=args.input,
                declarations=args.declaration,
                receipt=args.receipt,
                timeout=args.timeout,
            )
        else:
            errors = check_receipt(
                args.workspace,
                args.receipt,
                replay=args.replay,
                timeout=args.timeout,
            )
            result = {"valid": not errors, "errors": errors}
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        result = {"valid": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
