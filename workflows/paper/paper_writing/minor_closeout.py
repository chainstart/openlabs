"""Explicitly authorized, hash-bound author-side minor-revision closeout.

This is not a review or a score. Raw reviews and their mechanical aggregates
remain immutable; only the release decision is refreshed. Authorization and
semantic inspection records document a human-authorized action, not proof of
the identity or truthfulness of their author.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from paper_writing.identifiers import PAPER_ID_PATTERN


SCHEMA = "ara.paper_writing.minor_closeout.v1"
AUTH_SCHEMA = "ara.paper_writing.minor_closeout_authorization.v1"
SCOPE = "cas_minor_text_closeout"
FIELD = "minor_revision_closeout"
CHECKS = {"clean_build", "pdf_visual_check", "scientific_content_unchanged"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_VENUE_ONLY = re.compile(
    r"Four-leading-journal (?:suitability|significance): [^\n]+\. "
    r"This is a venue-level limitation, not an "
    r"(?:unresolved correctness gap|identified correctness defect)\.\Z"
)
_SUPPORT_METADATA = {
    "ARA_SUPPORT_README.md", "ZENODO_MANIFEST.json", "SHA256SUMS",
    "README.md", "CITATION.cff", "AUTHORS.md", "PAYLOAD_MANIFEST.json",
    "PAYLOAD_SHA256SUMS", "evidence_bundle_manifest.json",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Minor closeout: {message}")


def _keys(obj: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(obj, Mapping) and set(obj) == keys, f"invalid {label} fields")
    return obj


def _timestamp(value: Any) -> None:
    try:
        stamp = datetime.fromisoformat(value)
        _require(stamp.tzinfo is not None and stamp <= datetime.now(UTC), "invalid timestamp")
    except (ValueError, TypeError) as exc:
        raise ValueError("Minor closeout: timestamp must be timezone-aware and not future-dated") from exc


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 16384


def _path(name: Any, root: Path, *, artifact: bool = False) -> Path:
    _require(isinstance(name, str), "path must be a string")
    relative = PurePosixPath(name)
    _require(not relative.is_absolute() and ".." not in relative.parts
             and "\\" not in name and name == relative.as_posix(), "unsafe relative path")
    base = root.parent / "openlabs-artifacts" if artifact else root
    path = base / relative
    _require(path.resolve() == path and path.is_file(), f"missing or symlinked file: {name}")
    return path


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def _binding(name: str, root: Path, *, artifact: bool = False) -> dict[str, str]:
    return {"path": name, "sha256": _sha(_path(name, root, artifact=artifact))}


def _bound(item: Any, root: Path, *, artifact: bool = False) -> Path:
    _keys(item, {"path", "sha256"}, "file binding")
    path = _path(item["path"], root, artifact=artifact)
    _require(isinstance(item["sha256"], str) and bool(_SHA.fullmatch(item["sha256"]))
             and _sha(path) == item["sha256"], f"file SHA mismatch: {item['path']}")
    return path


def _json(path: Path) -> dict:
    _require(path.stat().st_size <= 8 * 1024 * 1024, "oversized JSON record")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    _require(isinstance(value, dict), "JSON record must be an object")
    return value


def _archive(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        _require(len(members) <= 10000 and sum(i.file_size for i in members) <= 256 * 1024 * 1024,
                 "archive exceeds bounded inspection limits")
        result = {}
        for item in members:
            name = item.filename
            p = PurePosixPath(name)
            _require(not p.is_absolute() and ".." not in p.parts and "\\" not in name
                     and (item.external_attr >> 16) & 0o170000 != 0o120000,
                     "unsafe archive member")
            if item.is_dir():
                continue
            _require(name not in result, "duplicate archive member")
            result[name] = archive.read(item)
        return result


def _snapshot(sources: Mapping[str, bytes], pdf: bytes) -> str:
    _require("main.pdf" not in sources, "source archive must not contain canonical PDF")
    digest = hashlib.sha256()
    for name, content in sorted({**sources, "main.pdf": pdf}.items()):
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _members(values: Mapping[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(content).hexdigest() for name, content in sorted(values.items())}


def _complete_sources(old_packet: Mapping[str, bytes], new_packet: Mapping[str, bytes],
                      current: Mapping[str, bytes], old_pdf: bytes, old_hash: str) -> tuple[dict, list]:
    """Recover unchanged snapshot-only metadata without claiming it was reviewed.

    Journal source ZIPs may omit private manuscript notes even though the
    canonical snapshot includes them. Current note bytes are admissible only
    if they reconstruct the exact original raw-review snapshot hash.
    """
    _require(set(old_packet) == set(new_packet), "journal source ZIP member set changed")
    _require(all(name in current and current[name] == value for name, value in new_packet.items()),
             "journal source ZIP differs from current source bytes")
    extras = {name: value for name, value in current.items() if name not in new_packet}
    _require(all(PurePosixPath(name).suffix in {".md", ".json"}
                 or name == "cover_letter.tex" for name in extras),
             "only unchanged snapshot-only metadata or cover letter may be absent from source ZIP")
    original = {**old_packet, **extras}
    _require(_snapshot(original, old_pdf) == old_hash,
             "original complete source/PDF snapshot does not reconstruct")
    return original, [{"path": name, "sha256": sha, "in_review_packet": False}
                      for name, sha in _members(extras).items()]


def _legacy_sources(root: Path, source_run: str, paper_id: str, raw: dict,
                    raw_binding: dict, source: dict, applied: dict, version: str) -> tuple[dict, bytes, list]:
    """Read the original native math packet, never synthesize postvalidation.

    A separately recorded reconstruction may restore snapshot-only bytes. The
    complete historical snapshot must match the immutable raw review exactly;
    these ancillary bytes are explicitly NOT represented as reviewer inputs.
    """
    _require(source_run.startswith("staging/"), "unsupported legacy review layout")
    def bind(name):
        item = _binding(f"{source_run}/{name}", root, artifact=True)
        source[name] = item
        return _bound(item, root, artifact=True)
    snap = _json(bind("snapshot.json"))
    inputs = _json(bind("packet/input-binding.json"))
    manifest = _json(bind("packet-manifest.json"))
    old_hash = raw["review_metadata"]["manuscript_snapshot_sha256_before"]
    _require(snap == inputs and snap.get("paper_id") == paper_id
             and snap.get("version") == version
             and snap.get("manuscript_snapshot_sha256") == old_hash,
             "legacy input identity mismatch")
    run = root.parent / "openlabs-artifacts" / source_run
    validations = sorted(run.glob("panel-validation-*/summary.json"))
    _require(len(validations) == 1, "ambiguous legacy postvalidation")
    summary_name = validations[0].relative_to(run).as_posix()
    summary = _json(bind(summary_name))
    _require(summary.get("paper_id") == paper_id
             and summary.get("native_review_sha256") == raw_binding["sha256"]
             and summary.get("review_unchanged") is True
             and summary.get("all_steps_passed") is True
             and len(summary.get("steps", [])) == 4
             and all(s.get("exit_code") == 0 for s in summary["steps"]),
             "legacy native validation failed")
    original_apply = _json(bind(str(PurePosixPath(summary_name).parent / "3.stdout.txt")))
    _require(original_apply.get("quality_gate") == applied
             and applied.get("manuscript_snapshot_sha256") == old_hash,
             "legacy applied record differs from original native output")
    packet = run / "packet/manuscript"
    reviewed = {}
    for path in sorted(packet.rglob("*")):
        if path.is_file():
            name = path.relative_to(packet).as_posix()
            value = bind("packet/manuscript/" + name).read_bytes()
            _require(hashlib.sha256(value).hexdigest() == manifest.get("manuscript/" + name),
                     "legacy reviewed source differs from packet manifest")
            reviewed[name] = value
    _require(set(reviewed) == {n.removeprefix("manuscript/") for n in manifest if n.startswith("manuscript/")},
             "legacy reviewed source omitted")
    pdf_path = bind("packet/manuscript.pdf")
    _require(_sha(pdf_path) == snap.get("canonical_pdf_sha256") == manifest.get("manuscript.pdf"),
             "legacy PDF binding mismatch")
    support_name = snap.get("support_archive")
    _require(isinstance(support_name, str) and PurePosixPath(support_name).name == support_name,
             "unsafe legacy support filename")
    support = bind("packet/" + support_name)
    source["packet/support.zip"] = source["packet/" + support_name]
    _require(_sha(support) == snap.get("support_package_sha256") == manifest.get(support_name),
             "legacy support binding mismatch")
    recovery_name = str(PurePosixPath(source["review"]["path"]).parent / "snapshot-reconstruction.json")
    source["snapshot_reconstruction"] = _binding(recovery_name, root)
    recovery = _json(_bound(source["snapshot_reconstruction"], root))
    _keys(recovery, {"schema_version", "paper_id", "reconstructed_at", "provenance", "snapshot_only_sources"}, "snapshot reconstruction")
    _require(recovery["schema_version"] == "ara.paper_writing.legacy_snapshot_reconstruction.v1"
             and recovery["paper_id"] == paper_id and _text(recovery["provenance"]),
             "invalid legacy reconstruction provenance")
    _timestamp(recovery["reconstructed_at"])
    extra = recovery["snapshot_only_sources"]
    _require(isinstance(extra, dict) and not set(extra) & (set(reviewed) | {"main.pdf"}),
             "reconstruction cannot replace reviewed bytes")
    recovered = {}
    for name, item in extra.items():
        p = PurePosixPath(name)
        _require(not p.is_absolute() and ".." not in p.parts and "\\" not in name
                 and name == p.as_posix(), "unsafe recovered source name")
        recovered[name] = _bound(item, root, artifact=True).read_bytes()
    old = {**reviewed, **recovered}
    pdf = pdf_path.read_bytes()
    _require(_snapshot(old, pdf) == old_hash, "legacy complete snapshot does not reconstruct")
    return old, pdf, [{"path": n, "sha256": h, "in_review_packet": False}
                     for n, h in _members(recovered).items()]


def _support_members(values: Mapping[str, bytes], version: str) -> dict[str, bytes]:
    """Normalize only archive-root and versioned public-support directory names."""
    output = {}
    for name, content in values.items():
        parts = PurePosixPath(name).parts
        _require(len(parts) >= 2 and parts[0].endswith(f"-support-v{version}"), "support version mismatch")
        parts = tuple("public-support-v{version}" if p == f"public-support-v{version}" else p
                      for p in parts[1:])
        key = "/".join(parts)
        _require(key not in output, "normalized support path collision")
        output[key] = content
    return output


def _integrity_verifier_rebinding(name: str, old: bytes, new: bytes,
                                 before: Mapping[str, bytes], after: Mapping[str, bytes],
                                 source_version: str, target_version: str) -> bool:
    """Permit only version literals and a verified sibling-manifest hash rebind.

    No execution, predicate, scientific constant, file list or result may change.
    In particular, replacing the expected hash with an arbitrary value is rejected.
    """
    path = PurePosixPath(name)
    if path.name != "verify_support_bundle.py" or not source_version or source_version == target_version:
        return False
    manifest = str(path.parent / "evidence_bundle_manifest.json")
    if manifest not in before or manifest not in after:
        return False
    pattern = re.compile(rb'^EXPECTED_BUNDLE_MANIFEST_SHA256 = "([0-9a-f]{64})"$', re.MULTILINE)
    old_matches, new_matches = list(pattern.finditer(old)), list(pattern.finditer(new))
    if len(old_matches) != 1 or len(new_matches) != 1:
        return False
    old_hash = hashlib.sha256(before[manifest]).hexdigest().encode()
    new_hash = hashlib.sha256(after[manifest]).hexdigest().encode()
    if old_matches[0].group(1) != old_hash or new_matches[0].group(1) != new_hash:
        return False
    rebound = pattern.sub(lambda match: match.group(0).replace(old_hash, new_hash), old)
    return rebound.replace(source_version.encode(), target_version.encode()) == new


def _deltas(before: Mapping[str, bytes], after: Mapping[str, bytes], area: str,
            source_version: str = "", target_version: str = "",
            support_text_edits: list[dict] | None = None) -> list[dict]:
    result = []
    authorized_docs = {row["path"]: row for row in (support_text_edits or [])}
    used_docs = set()
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        # This bounded mechanism cannot authorize new/deleted science inputs or code changes.
        _require(old is not None and new is not None, f"added/deleted {area} file requires full review: {name}")
        allowed = (PurePosixPath(name).suffix in {".tex", ".bib", ".bbl", ".cls", ".sty"}
                   if area == "manuscript" else PurePosixPath(name).name in _SUPPORT_METADATA)
        version_only = (area == "support" and PurePosixPath(name).name in {"CLAIMS.yaml", "REPRODUCE.md", "claim_evidence_map.md"}
                        and source_version != target_version and bool(source_version)
                        and old.replace(source_version.encode(), target_version.encode()) == new)
        documented = area == "support" and name in authorized_docs
        if documented:
            row = authorized_docs[name]
            _require(PurePosixPath(name).name == "REPRODUCE.md"
                     and row["before_sha256"] == hashlib.sha256(old).hexdigest()
                     and row["after_sha256"] == hashlib.sha256(new).hexdigest(),
                     "reproduction-document delta differs from exact authorization")
            used_docs.add(name)
        integrity_only = area == "support" and _integrity_verifier_rebinding(
            name, old, new, before, after, source_version, target_version)
        allowed = allowed or version_only or documented or integrity_only
        _require(allowed, f"non-text or scientific support change cannot be closed out: {area}/{name}")
        old.decode("utf-8"); new.decode("utf-8")
        result.append({"path": f"{area}/{name}", "before_sha256": hashlib.sha256(old).hexdigest(),
                       "after_sha256": hashlib.sha256(new).hexdigest()})
    _require(used_docs == set(authorized_docs), "authorized reproduction-document delta is missing")
    return result


def _authorization(paper_id: str, item: Any, root: Path) -> tuple[dict, dict]:
    path = _bound(item, root)
    _require(path.parent == root / "registry/quality-gate-exceptions", "authorization must be in registry/quality-gate-exceptions")
    auth = _json(path)
    _keys(auth, {"schema_version", "scope", "actor", "confirmed", "confirmed_at", "source", "quote", "papers",
                 "minimum_score", "decision_standard", "minimum_decision"}, "authorization")
    _require(auth["schema_version"] == AUTH_SCHEMA and auth["scope"] == SCOPE
             and auth["actor"] == "user" and auth["confirmed"] is True, "explicit user authorization required")
    _timestamp(auth["confirmed_at"])
    _require(type(auth["minimum_score"]) in (int, float) and auth["minimum_score"] == 5
             and auth["decision_standard"] == "cas_zone_1_journal"
             and auth["minimum_decision"] == "minor_revision", "authorization cannot change acceptance thresholds")
    _require(_text(auth["source"]) and _text(auth["quote"]), "authorization provenance missing")
    papers = auth["papers"]
    _require(isinstance(papers, dict) and papers and all(PAPER_ID_PATTERN.fullmatch(k) for k in papers)
             and paper_id in papers, "paper is not explicitly authorized")
    entry = papers[paper_id]
    fields = {"source_version", "target_version", "source_review_sha256", "venue_suitability_blockers",
              "venue_suitability_change_requests", "venue_suitability_required_changes", "optional_not_required_change_requests"}
    _require(isinstance(entry, Mapping), "invalid paper authorization")
    _keys(entry, fields | ({"support_text_edits"} if "support_text_edits" in entry else set()), "paper authorization")
    documents = entry.get("support_text_edits", [])
    _require(isinstance(documents, list), "invalid reproduction-document authorizations")
    seen_documents = set()
    for document in documents:
        _keys(document, {"path", "before_sha256", "after_sha256"}, "reproduction-document authorization")
        name = document["path"]
        _require(isinstance(name, str), "invalid reproduction-document path")
        path = PurePosixPath(name)
        _require(not path.is_absolute() and ".." not in path.parts and "\\" not in name
                 and name == path.as_posix() and path.name == "REPRODUCE.md"
                 and name not in seen_documents, "only exact reproduction-guide edits may be authorized")
        _require(all(isinstance(document[k], str) and bool(_SHA.fullmatch(document[k]))
                     for k in ("before_sha256", "after_sha256")), "invalid reproduction-document hashes")
        _require(document["before_sha256"] != document["after_sha256"], "reproduction-document authorization requires a real delta")
        seen_documents.add(name)
    for key in ("source_version", "target_version"):
        _require(isinstance(entry[key], str) and bool(re.fullmatch(r"\d+\.\d+\.\d+", entry[key])), "invalid authorized version")
    _require(bool(_SHA.fullmatch(str(entry["source_review_sha256"]))), "invalid raw review hash")
    allowed = entry["venue_suitability_blockers"]
    _require(isinstance(allowed, list) and all(isinstance(b, str) and _VENUE_ONLY.fullmatch(b) for b in allowed)
             and len(allowed) == len(set(allowed)), "only explicit, self-qualified venue-suitability blockers may be set aside")
    for key in ("venue_suitability_change_requests", "venue_suitability_required_changes", "optional_not_required_change_requests"):
        items = entry[key]
        _require(isinstance(items, list) and all(_text(b) for b in items) and len(items) == len(set(items)), "invalid exact request classification")
    return auth, dict(entry)


def _request_plan(raw: dict, auth: dict) -> tuple[list, list, list]:
    requests = raw["change_requests"]
    venue = auth["venue_suitability_change_requests"]
    optional = auth["optional_not_required_change_requests"]
    _require(not set(venue) & set(optional), "request classifications overlap")
    _require(set(venue + optional) <= {r["request"] for r in requests}, "authorization lists an unknown request")
    needed, excluded = [], []
    for index, request in enumerate(requests):
        text = request["request"]
        if text in venue:
            _require(text.startswith("For reconsideration at the four-leading-journal standard,")
                     and text.endswith("This is a venue-specific requirement, not a repair needed for the stated theorem."),
                     "request is not explicitly limited to venue reconsideration")
            classification = "venue_suitability_only"
        elif text in optional:
            _require(raw["publishability_summary"]["text_ready"] is True and request.get("text_only") is True
                     and request.get("priority") == "low" and text.startswith("Optionally "),
                     "optional exclusion requires raw text_ready and explicitly optional low-priority text")
            classification = "optional_not_required"
        else:
            _require(request.get("text_only") is True, "non-text change request cannot be closed out")
            needed.append({"index": index, "request": text, "resolution": "", "evidence": None})
            continue
        excluded.append({"index": index, "request": text, "classification": classification})
    venue_required = auth["venue_suitability_required_changes"]
    _require(set(venue_required) <= set(raw["required_changes"]), "unknown classified required change")
    for text in venue_required:
        _require(text.startswith("For four-leading-journal reconsideration only,")
                 and text.endswith("No mandatory scientific repair is identified for ordinary publication of the stated results."),
                 "required change is not explicitly limited to venue reconsideration")
    required = [{"index": i, "request": text, "resolution": "", "evidence": None}
                for i, text in enumerate(raw["required_changes"]) if text not in venue_required]
    return needed, required, excluded


def inspect_minor_closeout(paper_id: str, *, authorization: str, source_run: str,
                          support_archive: str, root: str | Path) -> dict[str, Any]:
    """Return a hash-bound certificate TEMPLATE; it cannot pass until inspected.

    source_run is relative to the sibling openlabs-artifacts directory. No
    scientific calculation, network request, or file write is performed here.
"""
    from paper_writing.handoff import _source_files, _verified_journal_source_archive
    from paper_writing.operations import _review_workspace_fingerprints
    from paper_writing.registry import load_paper_metadata
    from paper_writing.review import validate_review_panel_files, reviewer_role_for_domain
    from paper_writing.support import verify_support_archive, resolve_support_sources, _record_version
    from paper_writing.zenodo import _verify_archive_sources

    root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, root)
    auth_binding = _binding(authorization, root)
    _, auth = _authorization(paper_id, auth_binding, root)
    _require(metadata.get("version") == auth["target_version"], "target version differs from authorization")
    _require(PurePosixPath(source_run).parts[-1] == paper_id, "review run must belong to this paper")
    projection = metadata.get("ara_llm_self_review", {})
    review_name = projection.get("source")
    review_path = _path(review_name, root)
    panel = _json(review_path)
    errors = validate_review_panel_files(panel, review_path=review_path, repo_root=root,
        expected_role=reviewer_role_for_domain(metadata.get("domain")), expected_paper_id=paper_id)
    _require(not errors, "invalid original review: " + "; ".join(errors))
    records = panel["review_metadata"]["review_panel"]["reviewer_records"]
    # Initial scope is intentionally one native reviewer; never silently select one from a panel.
    _require(len(records) == 1, "minor closeout currently requires one validated native reviewer")
    raw_binding = {"path": records[0]["source"], "sha256": records[0]["sha256"]}
    raw = _json(_bound(raw_binding, root))
    _require(raw_binding["sha256"] == auth["source_review_sha256"], "not the authorized original raw review")
    _require(raw["publishability_summary"]["scientific_ready"] is True, "scientific non-readiness cannot be waived")
    _require(raw["scores"]["overall"] >= 5 and raw["recommendations"]["cas_zone_1_journal"]["decision"] in {"minor_revision", "accept"},
             "raw review must meet >=5 and CAS minor_revision or better")
    _require(set(raw["unresolved_blockers"]) == set(auth["venue_suitability_blockers"]), "unclassified scientific/evidence/ethics blocker remains")
    requests, required_changes, excluded_requests = _request_plan(raw, auth)
    source = {"review": _binding(review_name, root), "raw": raw_binding,
              "applied": _binding(str(review_path.relative_to(root).parent / "apply-cli.json"), root)}
    applied = _json(_bound(source["applied"], root))["quality_gate"]
    old_hash = raw["review_metadata"]["manuscript_snapshot_sha256_before"]
    legacy = source_run.startswith("staging/")
    if legacy:
        old_sources, old_pdf, snapshot_only_sources = _legacy_sources(
            root, source_run, paper_id, raw, raw_binding, source, applied, auth["source_version"])
    else:
        for name in ("postvalidation.json", "snapshot.json", "packet/input-binding.json", "packet/source.zip", "packet/support.zip", "packet/main.pdf"):
            source[name] = _binding(f"{source_run}/{name}", root, artifact=True)
        snap = _json(_bound(source["snapshot.json"], root, artifact=True))
        post = _json(_bound(source["postvalidation.json"], root, artifact=True))
        bind = _json(_bound(source["packet/input-binding.json"], root, artifact=True))
        _require(post.get("valid") is True and post.get("errors") == [] and post.get("review_sha256") == raw_binding["sha256"]
                 and post.get("packet_sha256") == snap.get("packet_sha256"), "source review lacks matching valid postvalidation")
        _require(snap.get("paper_id") == paper_id and bind.get("paper_id") == paper_id
                 and snap.get("version") == bind.get("version") == auth["source_version"]
                 and snap.get("manuscript_snapshot_sha256") == bind.get("manuscript_snapshot_sha256") == old_hash,
                 "source version/snapshot binding mismatch")
        for file, field in (("source.zip", "source_archive_sha256"), ("support.zip", "support_package_sha256"), ("main.pdf", "canonical_pdf_sha256")):
            _require(source[f"packet/{file}"]["sha256"] == snap.get(field) == bind.get(field), "original artifact binding mismatch")
        old_sources = _archive(_bound(source["packet/source.zip"], root, artifact=True))
        old_pdf = _bound(source["packet/main.pdf"], root, artifact=True).read_bytes()
    _require(applied.get("paper_id") == paper_id and applied.get("manuscript_snapshot_sha256") == old_hash,
             "source apply identity mismatch")
    _require(applied.get("score") == raw["scores"]["overall"]
             and applied.get("decision") == raw["recommendations"]["cas_zone_1_journal"]["decision"], "applied scores differ from raw")
    rounds = applied.get("revision_rounds")
    _require(type(rounds) is int and rounds >= 1, "missing real completed-round count")
    manuscript = root / str(metadata["manuscript_dir"])
    pdf = _path(metadata["latest_pdf"], root)
    _require(pdf == manuscript / "main.pdf", "only a canonical main.pdf closeout is supported")
    files = list(_source_files(manuscript, pdf))
    for path in files:
        _require(path.resolve() == path and path.is_relative_to(root), "source symlink is forbidden")
    current_sources = {p.relative_to(manuscript).as_posix(): p.read_bytes() for p in files}
    archive = _verified_journal_source_archive(metadata, root, manuscript, files, None)
    _require(archive is not None, "current journal source archive is required")
    if legacy:
        _require(set(old_sources) == set(current_sources), "legacy source set changed")
        _require(all(current_sources.get(n) == v for n, v in _archive(archive[0]).items()),
                 "journal source ZIP differs from current source bytes")
    else:
        old_sources, snapshot_only_sources = _complete_sources(
            old_sources, _archive(archive[0]), current_sources, old_pdf, old_hash)
    support_path = _path(support_archive, root)
    support = verify_support_archive(support_path)
    _verify_archive_sources(support, resolve_support_sources(metadata, repo_root=root), root)
    target_support_version = _record_version(metadata)
    _require(support.get("paper_id") == paper_id and support.get("paper_version") == target_support_version, "support archive identity differs")
    _require(_sha(support_path) == metadata.get("support", {}).get("publication", {}).get("package_sha256"), "support draft package binding differs")
    old_support_path = _bound(source["packet/support.zip"], root, artifact=True)
    old_support_record = verify_support_archive(old_support_path)
    _require(old_support_record.get("paper_id") == paper_id, "original support paper identity differs")
    source_support_version = old_support_record.get("paper_version")
    _require(isinstance(source_support_version, str)
             and bool(re.fullmatch(r"\d+\.\d+\.\d+", source_support_version)), "invalid original support version")
    old_support = _support_members(_archive(old_support_path), source_support_version)
    new_support = _support_members(_archive(support_path), target_support_version)
    delta = _deltas(old_sources, current_sources, "manuscript") + _deltas(
        old_support, new_support, "support", source_support_version, target_support_version,
        auth.get("support_text_edits"))
    target = {"version": auth["target_version"], **_review_workspace_fingerprints(paper_id, metadata, root),
              "pdf": _binding(str(pdf.relative_to(root)), root),
              "source_archive": _binding(str(archive[0].relative_to(root)), root),
              "support_archive": _binding(support_archive, root)}
    return {"schema_version": SCHEMA, "paper_id": paper_id, "authorization": auth_binding,
            "source_run": source_run, "source": source, "source_version": auth["source_version"],
            "revision_rounds_completed": rounds, "target": target,
            "snapshot_only_sources": snapshot_only_sources,
            "source_files_before": _members(old_sources), "source_files_after": _members(current_sources),
            "support_files_before": _members(old_support), "support_files_after": _members(new_support),
            "delta": delta, "nonblocking_venue_findings": list(raw["unresolved_blockers"]),
            "request_resolutions": requests, "required_change_resolutions": required_changes,
            "nonblocking_change_requests": excluded_requests,
            "nonblocking_required_changes": auth["venue_suitability_required_changes"],
            "delta_resolutions": [{"path": d["path"], "classification": "text_only" if d["path"].startswith("manuscript/") else "release_metadata_only",
                                   "reason": "", "evidence": None} for d in delta],
            "checks": [{"kind": kind, "status": "PENDING", "evidence": None} for kind in sorted(CHECKS)],
            "verified_at": None, "verified_by": None,
            "new_independent_review": False, "scores_changed": False}


def validate_minor_closeout(paper_id: str, certificate: str | Path, *, root: str | Path,
                           metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Revalidate the authorization, complete delta, checks and final bytes."""
    from paper_writing.registry import load_paper_metadata, load_registry_settings
    from paper_writing.revision_policy import revision_round_policy
    from paper_writing.manuscript_style import audit_manuscript_style, manuscript_style_blockers
    from paper_writing.support_citations import audit_manuscript_support, support_audit_blockers
    root = Path(root).resolve()
    name = str(certificate)
    path = _path(name, root)
    cert = _json(path)
    expected = inspect_minor_closeout(paper_id, authorization=cert.get("authorization", {}).get("path"),
        source_run=cert.get("source_run", ""), support_archive=cert.get("target", {}).get("support_archive", {}).get("path"), root=root)
    editable = {"request_resolutions", "required_change_resolutions", "delta_resolutions", "checks", "verified_at", "verified_by"}
    _keys(cert, set(expected), "certificate")
    _require(all(cert[k] == v for k, v in expected.items() if k not in editable), "certificate source, target, delta or authorization is stale")
    _timestamp(cert["verified_at"])
    _require(_text(cert["verified_by"]), "author-side verifier identity required")
    evidence = [path, _bound(cert["authorization"], root)]
    for field, fixed, prose in (("request_resolutions", {"index", "request"}, "resolution"),
                                ("required_change_resolutions", {"index", "request"}, "resolution"),
                                ("delta_resolutions", {"path", "classification"}, "reason")):
        rows = cert[field]
        _require(isinstance(rows, list) and len(rows) == len(expected[field]), f"incomplete {field}")
        for actual, template in zip(rows, expected[field], strict=True):
            _keys(actual, set(template), field)
            _require(all(actual[k] == template[k] for k in fixed) and _text(actual[prose]), f"unresolved or reclassified {field}")
            evidence.append(_bound(actual["evidence"], root))
    _require(isinstance(cert["checks"], list) and len(cert["checks"]) == len(CHECKS), "missing closeout checks")
    _require({row.get("kind") for row in cert["checks"]} == CHECKS, "required closeout check omitted")
    for row in cert["checks"]:
        _keys(row, {"kind", "status", "evidence"}, "check")
        _require(row["status"] == "PASS", "closeout check did not pass")
        evidence.append(_bound(row["evidence"], root))
    current = dict(metadata) if metadata is not None else load_paper_metadata(paper_id, root)
    settings = load_registry_settings(root).get("quality_gate", {})
    _require(float(settings.get("minimum_score", 5)) == 5 and settings.get("decision_standard", "cas_zone_1_journal") == "cas_zone_1_journal"
             and settings.get("cas_zone_1_minimum_decision", "minor_revision") == "minor_revision", "configured gate conflicts with scoped authorization")
    maximum, exception = revision_round_policy(paper_id, current, settings, root=root)
    _require(cert["revision_rounds_completed"] <= maximum, "closeout cannot expand review-round budget")
    support_audit = audit_manuscript_support(paper_id, root=root)
    style_audit = audit_manuscript_style(paper_id, root=root, require_ai_declaration=True)
    blockers = support_audit_blockers(support_audit) + manuscript_style_blockers(style_audit)
    _require(not blockers, "deterministic safety gates failed: " + "; ".join(blockers))
    source = cert["source"]
    evidence.extend(_bound(source[key], root) for key in ("review", "raw", "applied"))
    if "snapshot_reconstruction" in source:
        evidence.append(_bound(source["snapshot_reconstruction"], root))
    return {"certificate": cert, "certificate_binding": _binding(name, root),
            "evidence_paths": list(dict.fromkeys(evidence)), "maximum_revision_rounds": maximum,
            "revision_exception": exception, "support_audit": support_audit, "style_audit": style_audit}


def validate_release_minor_closeout(paper_id: str, metadata: Mapping[str, Any], *, root: str | Path) -> list[Path]:
    """Release-time replay; changing the closeout or any bound byte fails closed."""
    root = Path(root).resolve()
    release = metadata.get("writing_release", {})
    pointer = release.get(FIELD)
    if pointer is None:
        return []
    _keys(pointer, {"path", "sha256", "classification", "closed_at", "source_snapshot_sha256", "new_independent_review", "rounds_added"}, "release closeout")
    _bound({k: pointer[k] for k in ("path", "sha256")}, root)
    checked = validate_minor_closeout(paper_id, pointer["path"], root=root, metadata=metadata)
    cert = checked["certificate"]
    raw = _json(_bound(cert["source"]["raw"], root))
    _require(pointer["classification"] == SCOPE and pointer["new_independent_review"] is False
             and type(pointer["rounds_added"]) is int and pointer["rounds_added"] == 0
             and pointer["closed_at"] == cert["verified_at"]
             and pointer["source_snapshot_sha256"] == raw["review_metadata"]["manuscript_snapshot_sha256_before"], "invalid closeout provenance")
    _require(release.get("revision_rounds_completed") == cert["revision_rounds_completed"]
             and release.get("score") == raw["scores"]["overall"]
             and release.get("decision") == raw["recommendations"]["cas_zone_1_journal"]["decision"]
             and release.get("manuscript_version") == cert["target"]["version"], "release altered score, count, decision or version")
    for key in ("manuscript_snapshot_sha256", "review_content_sha256", "registry_review_content_sha256", "support_sources_sha256"):
        _require(release.get(key) == cert["target"][key], "release fingerprint differs from closeout")
    _require(not release.get("unresolved_review_blockers") and release.get("nonblocking_venue_findings") == cert["nonblocking_venue_findings"], "release lost blocker classification")
    return checked["evidence_paths"]


def apply_minor_closeout(paper_id: str, *, certificate: str, root: str | Path) -> dict[str, Any]:
    """Apply a checked author-side closeout without editing reviews or counting a round."""
    from paper_writing.registry import load_paper_metadata, write_paper_metadata
    from paper_writing.revision_policy import EXCEPTION_FIELD
    root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, root)
    checked = validate_minor_closeout(paper_id, certificate, root=root, metadata=metadata)
    cert = checked["certificate"]
    original = _json(_bound(cert["source"]["raw"], root))
    target = cert["target"]
    release = {"status": "ready", "target_score": 5.0, "score": original["scores"]["overall"],
               "venue_type": "journal", "decision_standard": "cas_zone_1_journal",
               "decision": original["recommendations"]["cas_zone_1_journal"]["decision"], "minimum_decision": "minor_revision",
               "revision_rounds_completed": cert["revision_rounds_completed"], "max_revision_rounds": checked["maximum_revision_rounds"],
               "reviewed_at": original["review_metadata"]["reviewed_at_utc"], "manuscript_version": target["version"],
               **{k: target[k] for k in ("manuscript_snapshot_sha256", "review_content_sha256", "registry_review_content_sha256", "support_sources_sha256")},
               "support_package_sha256": target["support_archive"]["sha256"],
               FIELD: {**checked["certificate_binding"], "classification": SCOPE, "closed_at": cert["verified_at"],
                       "source_snapshot_sha256": original["review_metadata"]["manuscript_snapshot_sha256_before"],
                       "new_independent_review": False, "rounds_added": 0},
               "nonblocking_venue_findings": cert["nonblocking_venue_findings"],
               "source_quality_gate": _json(_bound(cert["source"]["applied"], root))["quality_gate"]}
    if checked["revision_exception"] is not None:
        release[EXCEPTION_FIELD] = checked["revision_exception"]
    # ara_llm_self_review deliberately remains bound to its ORIGINAL snapshot.
    metadata["writing_release"] = release
    metadata["status_updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    write_paper_metadata(paper_id, metadata, root)
    return {"paper_id": paper_id, "status": "ready", "passed": True, "new_independent_review": False,
            "rounds_added": 0, "quality_gate": release}
