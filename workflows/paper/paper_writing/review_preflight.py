"""Referee-side runtime preflight: can an independent review runtime open and run the materials?

``paper-writing review runtime-preflight --paper-id P`` starts one Codex referee process
the way the unified review starts its referees (same launcher, same isolation choice:
native ``-s read-only`` when bubblewrap works, otherwise the hashed read-only copy). The
process is asked to re-hash every registered support source (and, with ``--attachment``,
every member listed in the attachment's ``SHA256SUMS``) and to run the replication
verifier. The launcher independently checks the copy before and after, recomputes the
registered ``support_sources_sha256`` over it, and compares the attachment's members with
the registered sources. The result is one JSON receipt (``preflight.json``) with flat
fields a reopen condition can test, e.g. ``ok == true``.

It does not review the manuscript and records no decision; it only shows whether the
referee runtime works for this paper.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from paper_writing import review_sandbox

SCHEMA = "openlabs.review_runtime_preflight.v1"
REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["files_checked", "checksums_matched", "mismatches", "verifier_command",
                 "verifier_exit_code", "verifier_output_tail", "attachment_opened", "notes"],
    "properties": {
        "files_checked": {"type": "integer", "minimum": 0},
        "checksums_matched": {"type": "integer", "minimum": 0},
        "mismatches": {"type": "array", "items": {"type": "string"}},
        "verifier_command": {"type": "string"},
        "verifier_exit_code": {"type": "integer"},
        "verifier_output_tail": {"type": "string", "maxLength": 4000},
        "attachment_opened": {"type": "boolean"},
        "notes": {"type": "string", "maxLength": 2000},
    },
}
SYSTEM = (
    "You are the runtime preflight of an independent referee. You do not judge the science. "
    "Use the shell to do exactly the checks requested, report what the commands actually "
    "returned, and never invent results. Do not modify any input file."
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def attachment_sums(path: Path) -> dict[str, str]:
    """``{member name: sha256}`` from the ``SHA256SUMS`` member of a ZIP attachment."""
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if Path(n).name == "SHA256SUMS"]
        if len(names) != 1:
            raise ValueError(f"{path.name}: expected one SHA256SUMS member, found {len(names)}")
        # Names in SHA256SUMS are relative to its own directory inside the archive.
        prefix = names[0][: -len("SHA256SUMS")]
        sums: dict[str, str] = {}
        for line in archive.read(names[0]).decode("utf-8").splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                sums[parts[1].lstrip("*").strip()] = parts[0].lower()
        members = {}
        for name in archive.namelist():
            if name.endswith("/") or Path(name).name == "SHA256SUMS" or not name.startswith(prefix):
                continue
            members[name[len(prefix):]] = hashlib.sha256(archive.read(name)).hexdigest()
    return {"sums": sums, "members": members}


def latest_registered_sha256(root: Path, paper_id: str) -> tuple[str | None, str | None]:
    """``support_sources_sha256`` of the latest unified decision record, with its path."""
    base = root / "reviews" / "unified" / paper_id
    for decision in sorted(base.glob("*/decision.json"), reverse=True):
        try:
            value = (json.loads(decision.read_text()).get("fingerprints") or {}).get("support_sources_sha256")
        except (OSError, ValueError):
            continue
        if value:
            return value, str(decision.relative_to(root))
    return None, None


def _prompt(materials: review_sandbox.ReviewMaterials, attachment: Path | None, verifier: str) -> str:
    lines = ["## Registered support sources (open each one and compute its SHA-256)"]
    for name in sorted(materials.files):
        if name in materials.extras:
            continue
        lines.append(f"- {materials.files[name]}")
    if attachment is not None:
        lines += ["", "## Frozen attachment",
                  f"- {materials.files['@attachment']}",
                  "Open it (for example with Python's zipfile), read its SHA256SUMS member and check that "
                  "every listed member hashes to the listed value and equals the registered source file of "
                  "the same name."]
    lines += ["", "## Verifier",
              f"Run `{verifier}` in the directory that holds the registered replication files "
              "(the directory of the verifier script). Report the exact command, its exit code and the "
              "last lines of its output.",
              "", "Return files_checked (registered sources you hashed), checksums_matched (how many "
              "matched the attachment's SHA256SUMS, or, without an attachment, how many you could hash), "
              "mismatches, attachment_opened, and the verifier fields."]
    return "\n".join(lines) + "\n"


def run_preflight(paper_id: str, root: Path, out: Path, *, role: Mapping[str, Any],
                  attachment: Path | None = None, verifier: str = "python verify_primary.py",
                  registered_sha256: str | None = None, timeout: int = 1800,
                  runner: Callable[..., tuple[dict[str, Any], dict[str, Any]]] | None = None) -> dict[str, Any]:
    from paper_writing.registry import load_paper_metadata
    from paper_writing.review_launcher import LaunchError, run_role

    runner = runner or run_role
    root = root.resolve()
    metadata = load_paper_metadata(paper_id, root)
    source = "argument"
    if registered_sha256 is None:
        registered_sha256, source = latest_registered_sha256(root, paper_id)
    materials = review_sandbox.materials_from_support(metadata, root, registered_sha256=registered_sha256)
    if materials is None:
        raise ValueError(f"{paper_id}: no registered support sources (support.publication.source_files)")
    record: dict[str, Any] = {"schema_version": SCHEMA, "paper_id": paper_id, "started_at": _now(),
                              "root": str(root), "registered_sha256": registered_sha256,
                              "registered_sha256_source": source,
                              "registered_files": len(materials.files)}
    attachment_check = None
    if attachment is not None:
        attachment = attachment.resolve()
        listed = attachment_sums(attachment)
        by_name = {Path(rel).name: materials.files[name] for name, rel in materials.relative.items()}
        matched = [name for name, digest in listed["sums"].items()
                   if listed["members"].get(name) == digest and name in by_name
                   and review_sandbox.sha256_file(by_name[name]) == digest]
        attachment_check = {"path": str(attachment), "sha256": review_sandbox.sha256_file(attachment),
                            "listed": len(listed["sums"]), "matched_registered_sources": len(matched),
                            "unmatched": sorted(set(listed["sums"]) - set(matched)),
                            "all_registered_sources_listed": set(by_name) <= set(listed["sums"])}
        materials = replace(materials, files={**materials.files, "@attachment": attachment},
                            relative={**materials.relative, "@attachment": f"attachment/{attachment.name}"},
                            extras=materials.extras | {"@attachment"})
    record["attachment"] = attachment_check
    out.mkdir(parents=True, exist_ok=False)
    try:
        report, receipt = runner(role_name="runtime_preflight", role=role, system_prompt=SYSTEM,
                                 user_prompt=_prompt(materials, attachment, verifier), schema=REPORT_SCHEMA,
                                 workdir=out / "runtime_preflight", timeout=timeout, materials=materials)
        record |= {"runtime_started": True, "report": report, "receipt": receipt, "error": None}
    except LaunchError as exc:
        record |= {"runtime_started": False, "report": None, "receipt": None, "error": str(exc)}
        report, receipt = None, {}
    copy = (receipt or {}).get("readonly_copy") or {}
    registered = copy.get("registered_sources") or {}
    expected = len(materials.files) - len(materials.extras)
    record |= {
        "sandbox_mode": (receipt or {}).get("sandbox_mode"),
        "isolation": (receipt or {}).get("isolation"),
        "native_sandbox_probe": (receipt or {}).get("native_sandbox_probe"),
        "model": (receipt or {}).get("model"),
        "copy_valid": copy.get("valid") if copy else None,
        "registered_sources_match": registered.get("matches") if copy else None,
        "verifier_command": (report or {}).get("verifier_command"),
        "verifier_exit_code": (report or {}).get("verifier_exit_code"),
        "runtime_checksums_matched": (report or {}).get("checksums_matched"),
        "expected_checksums": expected,
        "finished_at": _now(),
    }
    native = record["isolation"] == "codex_bwrap_read_only"
    if native:
        from paper_writing.support import support_sources_digest

        registered_files = {n: f for n, f in materials.files.items() if n not in materials.extras}
        record["registered_sources_match"] = (registered_sha256 is not None and
                                              support_sources_digest(registered_files) == registered_sha256)
    record["ok"] = bool(
        record["runtime_started"]
        and record["verifier_exit_code"] == 0
        and record["runtime_checksums_matched"] == expected
        and not (report or {}).get("mismatches")
        and record["registered_sources_match"] is True
        and (native or record["copy_valid"] is True)
        and (attachment_check is None or (attachment_check["matched_registered_sources"] == expected
                                          and attachment_check["all_registered_sources_listed"]
                                          and (report or {}).get("attachment_opened") is True)))
    text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    (out / "preflight.json").write_text(text)
    return record
