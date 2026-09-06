#!/usr/bin/env python3
"""Source-owned mathematics catalog: fetch, normalize, and emit ingestion bundles.

This lab tool never opens SQLite. The orchestrator validates and ingests its
durable result bundle. Upstream Lean is data only: no lake, plugins, or source
code from a downloaded repository are executed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CODE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CODE / "orchestrator/src"))
from openlabs.config import workspace_paths
from openlabs.contracts import atomic_write_json

SCHEMA = "openlabs.math_problem_catalog_bundle.v1"
PREFIX = "math-catalog:"
DATA_SUBDIR = Path("registry/math-problems")
ART_SUBDIR = Path("math-problem-catalog/snapshots")
USER_AGENT = "OpenLabs-Math-Source-Catalog/1.0 (read-only scholarly metadata collector)"
REPOSITORIES = {"erdos-problems": "teorth/erdosproblems",
                "formal-conjectures": "google-deepmind/formal-conjectures"}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def short_id(value):
    return digest(value.encode())[:24]


def sid(source):
    return PREFIX + "source:" + source


def pid(value):
    return PREFIX + "problem:" + value


def fetch(url, *, max_bytes=96 * 1024 * 1024):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/vnd.github+json, */*"})
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError(f"source exceeds byte limit: {url}")
        return raw, {"url": url, "final_url": response.url,
                     "retrieved_at": now(), "sha256": digest(raw),
                     "bytes": len(raw), "http_status": response.status,
                     "etag": response.headers.get("ETag"),
                     "last_modified": response.headers.get("Last-Modified")}


def immutable_bytes(path, raw):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"refusing to replace immutable snapshot: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".catalog-", delete=False) as handle:
        handle.write(raw)
        temporary = Path(handle.name)
    temporary.replace(path)


def unpack_source_archive(raw, destination):
    """Extract bounded regular source files; reject traversal and links entirely."""
    destination = Path(destination).resolve()
    inventory, total, members = [], 0, 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            members += 1
            total += member.size
            if member.size > 8 * 1024 * 1024 or total > 128 * 1024 * 1024 or members > 20000:
                raise ValueError("source archive exceeds extraction limits")
            parts = PurePosixPath(member.name).parts
            if member.name.startswith("/") or ".." in parts:
                raise ValueError("unsafe archive path")
            if member.issym() or member.islnk():
                raise ValueError("source archive contains a link")
            if not member.isfile() or len(parts) < 2:
                continue
            relative = Path(*parts[1:])
            if relative.suffix not in {".lean", ".md", ".json", ".toml", ".yaml", ".yml"} and relative.name not in {"LICENSE", "AUTHORS", "lean-toolchain"}:
                continue
            if len(inventory) >= 15000:
                raise ValueError("source archive exceeds extraction limits")
            target = destination / relative
            if not target.resolve().is_relative_to(destination):
                raise ValueError("source extraction escaped destination")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("unreadable source member")
            content = stream.read()
            immutable_bytes(target, content)
            inventory.append({"path": relative.as_posix(), "sha256": digest(content), "bytes": len(content)})
    return inventory


def fetch_snapshot(paths, source):
    repository = REPOSITORIES[source]
    commit_raw, commit_fetch = fetch(f"https://api.github.com/repos/{repository}/commits/main", max_bytes=8*1024*1024)
    commit = json.loads(commit_raw)["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid upstream commit")
    root = paths.artifacts / ART_SUBDIR / source / commit
    existing = root / "snapshot.json"
    if existing.exists():
        manifest = json.loads(existing.read_text())
        for item in manifest["files"]:
            if digest((root / "tree" / item["path"]).read_bytes()) != item["sha256"]:
                raise ValueError("stored immutable snapshot has changed")
    else:
        archive_url = f"https://codeload.github.com/{repository}/tar.gz/{commit}"
        archive_raw, archive_fetch = fetch(archive_url)
        files = unpack_source_archive(archive_raw, root / "tree")
        immutable_bytes(root / "source.tar.gz", archive_raw)
        immutable_bytes(root / "commit.json", commit_raw)
        manifest = {"schema_version": "openlabs.math_source_snapshot.v1", "source_id": source,
                    "repository": repository, "revision": commit, "retrieved_at": archive_fetch["retrieved_at"],
                    "fetches": [commit_fetch, archive_fetch], "files": files,
                    "execution_policy": "source data only; no upstream code executed"}
        atomic_write_json(existing, manifest)
    pointer = {"source_id": source, "revision": commit, "checked_at": now(),
               "retrieved_at": manifest["retrieved_at"],
               "manifest_path": str(existing.relative_to(paths.artifacts)),
               "manifest_sha256": digest(existing.read_bytes()),
               "tree_path": str((root / "tree").relative_to(paths.artifacts)),
               "revision_check": commit_fetch}
    atomic_write_json(paths.data / DATA_SUBDIR / "snapshots" / (source + ".json"), pointer)
    return pointer


def load_snapshot(paths, source):
    pointer = json.loads((paths.data / DATA_SUBDIR / "snapshots" / (source + ".json")).read_text())
    manifest_path = paths.artifacts / pointer["manifest_path"]
    if digest(manifest_path.read_bytes()) != pointer["manifest_sha256"]:
        raise ValueError("snapshot manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text())
    tree = paths.artifacts / pointer["tree_path"]
    for item in manifest["files"]:
        if digest((tree / item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError(f"snapshot file hash mismatch: {item['path']}")
    return pointer, manifest, tree


def normalize_status(raw):
    status = str(raw or "").lower().strip()
    if status == "independent":
        return "independent_of_zfc_in_source"
    if status in {"not provable", "not disprovable"}:
        return "axiomatic_obstruction_in_source"
    if status in {"open", "verifiable", "falsifiable", "decidable"}:
        return "open_in_source"
    if status in {"disproved", "refuted", "disproved (lean)"}:
        return "disproved_in_source"
    if status in {"proved", "solved", "solved (lean)"}:
        return "solved_in_source"
    return "unknown"


def record(kind, entity_id, title, status, metadata):
    return {"record_id": PREFIX + kind.removeprefix("math_") + ":" + entity_id,
            "kind": kind, "domain": "math", "title": title, "status": status,
            "source_path": (DATA_SUBDIR / "catalog-bundle.json").as_posix(),
            "metadata": metadata}


def new_problem(key, title, source, status="unknown", *, entity_type="mother_problem"):
    return record("math_problem", key, title, status, {
        "entity_id": key, "entity_type": entity_type, "source_ids": [sid(source)],
        "statement_ids": [], "scientific_status": status,
        "influence_status": "pending_review", "statement_status": "missing",
        "formalization_status": "not_checked", "local_research_status": "not_assessed",
        "selection_eligible": False, "screening_eligible": False,
        "review_required": True, "quantifier_review": "pending",
        "literature_review_status": "not_exhaustively_checked", "references": [],
        "status_observations": [], "record_references": [sid(source)],
    })


def load_erdos_rows(tree):
    import yaml
    payload = yaml.safe_load((tree / "data/problems.yaml").read_text())
    if not isinstance(payload, list):
        raise ValueError("Erdos source schema changed: expected list")
    rows = json.loads(json.dumps(payload, default=str))
    ids = [str(r["number"]) for r in rows]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[1-9][0-9]*", n) for n in ids):
        raise ValueError("invalid or duplicate Erdos numbers")
    return rows


def canonical_formal_key(entry):
    number = entry.get("canonical_erdos_id")
    if number is not None:
        return "erdos-" + str(number)
    # A file or a matching title is NOT an equivalence certificate. Until an
    # explicit reviewed identity is supplied, keep independent source IDs.
    return "fc-" + short_id(entry["source_item_id"])


def finalize_problem(problem, statements):
    meta = problem["metadata"]
    ids = sorted(set(meta["statement_ids"]))
    meta["statement_ids"] = ids
    lean = [statements[s] for s in ids if statements[s]["metadata"].get("language") == "lean4"]
    if lean:
        meta["formalization_status"] = "lean_source_present_not_locally_verified"
        meta["lean_statement_count"] = len(lean)
        if meta["statement_status"] == "missing":
            meta["statement_status"] = "lean_variants_available_scope_review_required"
    passed = meta["influence_status"] in {"benchmark_passed", "review_passed"}
    open_status = meta["scientific_status"] == "open_in_source"
    closed_local = meta["local_research_status"] in {"locally_resolved", "refuted", "solved_in_literature"}
    approved = meta.get("source_admission_allows_screening", True)
    ambiguous = bool(meta.get("source_ambiguity_flag"))
    meta["screening_eligible"] = bool(passed and open_status and approved and not closed_local
                                      and not ambiguous and not meta.get("canonical_alias_of"))
    meta["selection_eligible"] = bool(meta["screening_eligible"]
                                      and (meta.get("legacy_review_retained") or meta.get("explicit_intake_review_passed"))
                                      and meta["statement_status"] in {"reviewed_natural_language", "reviewed_lean_statement"}
                                      and meta.get("quantifier_review") in {"reviewed_in_local_intake", "reviewed_explicit_intake"})
    meta["review_required"] = not meta["selection_eligible"]
    meta["priority_statement_review"] = bool(meta["screening_eligible"] and meta.get("legacy_review_retained") and meta["review_required"])
    meta["short_horizon_feasibility"] = "not_assessed"
    meta["research_ready"] = False  # Import never authorizes a research campaign.
    needs = []
    if not passed:
        needs.append("influence_review")
    if ambiguous:
        needs.append("resolve_source_statement_ambiguity")
    if meta["statement_status"] == "missing":
        needs.append("recover_exact_statement")
    elif meta["statement_status"] not in {"reviewed_natural_language", "reviewed_lean_statement"}:
        needs.append("quantifier_and_variant_scope_review")
    if meta["scientific_status"] in {"unknown", "source_status_conflict", "axiomatic_obstruction_in_source", "public_resolution_claim", "public_refutation_claim"}:
        needs.append("scientific_status_review")
    if lean:
        needs.append("lean_elaboration_and_faithfulness_check_not_run")
    needs.append("update_problem_specific_literature_before_research")
    meta["next_actions"] = needs
    meta["source_ids"] = sorted(set(meta["source_ids"]))
    meta["record_references"] = sorted(set(meta["source_ids"] + ids))
    if meta.get("canonical_alias_of"):
        meta["record_references"].append(meta["canonical_alias_of"])
    meta["references"] = sorted(set(meta["references"]))
    problem["status"] = meta["scientific_status"]


def apply_intake_reviews(problems, statements, records, reviews, *, verified_refutations=None):
    """Scope reviews, with closure only via separately replayed finite evidence."""
    seen = set()
    verified_refutations = verified_refutations or {}
    for review in reviews:
        problem_id = review["problem_id"]
        if problem_id in seen or problem_id not in problems:
            raise ValueError("missing or multiply reviewed intake problem")
        seen.add(problem_id)
        if not review.get("evidence") or not review.get("reviewed_at") or not review.get("reason"):
            raise ValueError("intake review requires evidence, date and reason")
        meta = problems[problem_id]["metadata"]
        accepted_refutation = False
        influence = review.get("influence_status", meta["influence_status"])
        if influence not in {"benchmark_passed", "review_passed", "specialist_archive", "pending_review"}:
            raise ValueError("unsupported intake influence judgment")
        meta["influence_status"] = influence
        reviewed_ids = review.get("reviewed_statement_ids", [])
        bindings_stale = False
        if review.get("require_statement_bindings"):
            from problem_catalog_intake import statement_binding
            bindings = review.get("statement_bindings", {})
            bindings_stale = any(s not in statements or bindings.get(s) != statement_binding(statements[s]) for s in reviewed_ids)
            if bindings_stale:
                meta["quantifier_review"] = "stale_statement_version_requires_review"
                meta["explicit_intake_review_passed"] = False
        if review.get("scope_review") == "passed" and not bindings_stale:
            if not reviewed_ids or any(s not in meta["statement_ids"] or s not in statements for s in reviewed_ids):
                raise ValueError("scope review must name existing statements for this mother")
            languages = {statements[s]["metadata"]["language"] for s in reviewed_ids}
            meta["statement_status"] = "reviewed_natural_language" if "natural_language" in languages else "reviewed_lean_statement"
            meta["quantifier_review"] = "reviewed_explicit_intake"
            meta["explicit_intake_review_passed"] = True
            meta["reviewed_statement_ids"] = reviewed_ids
            # Individual influence evidence can admit an otherwise mixed-source record.
            meta["source_admission_allows_screening"] = influence in {"benchmark_passed", "review_passed"}
        status_review = review.get("scientific_status_review")
        if status_review:
            if not status_review.get("evidence") or not status_review.get("checked_at"):
                raise ValueError("scientific status review requires evidence and date")
            meta.setdefault("scientific_status_reviews", []).append(status_review)
            if status_review.get("status") == "refuted" and problem_id in verified_refutations and review.get("scope_review") == "passed" and review.get("require_statement_bindings") and reviewed_ids and not bindings_stale:
                meta["scientific_status"] = "refuted"
                meta["local_research_status"] = "refuted"
                meta["verified_literature_counterexample"] = verified_refutations[problem_id]
                accepted_refutation = True
            elif status_review.get("status") in {"public_resolution_claim", "public_refutation_claim"}:
                if meta["scientific_status"] in {"open_in_source", "unknown", "source_status_conflict"} and review.get("scope_review") == "passed" and not bindings_stale:
                    meta["scientific_status"] = status_review["status"]
                    meta["resolution_claim_not_independently_proof_audited"] = True
                else:
                    meta["resolution_claim_did_not_override_existing_status"] = True
            elif status_review.get("status") not in {None, "unknown", meta["scientific_status"]}:
                # A review can raise a conflict; it cannot erase a closure or
                # declare a manuscript claim to be a verified theorem.
                meta["scientific_status"] = "source_status_conflict"
                meta["intake_status_conflict_requires_review"] = True
        item = record("math_review", "intake-" + short_id(problem_id + review["reviewed_at"]),
                      problems[problem_id]["title"], "explicit_intake_review", {
                          **review, "record_references": [problem_id] + [s for s in reviewed_ids if s in statements],
                          "statement_bindings_stale": bindings_stale,
                          "does_not_certify_lean_or_close_problem": not accepted_refutation,
                          "verified_refutation_evidence": verified_refutations.get(problem_id) if accepted_refutation else None})
        records[item["record_id"]] = item


def verify_local_refutations(paths, reviews):
    verified = {}
    for review in reviews:
        evidence = review.get("local_refutation_evidence")
        if not evidence:
            continue
        if evidence.get("protocol") != "rank-forest-seymour-winkler-sudan-v1" or review["problem_id"] != pid("rank-conditioned-graphic-forest-rayleigh"):
            raise ValueError("unrecognized finite-refutation protocol or mother scope")
        path = paths.data / evidence["certificate_path"]
        allowed = paths.data / DATA_SUBDIR / "intake-batches/evidence"
        if path.is_symlink() or not path.resolve().is_relative_to(allowed.resolve()) or path.stat().st_size > 1_000_000:
            raise ValueError("unsafe finite counterexample certificate")
        raw = path.read_bytes()
        checker = CODE / "labs/math/tools/check_rank_forest_counterexample.py"
        if digest(raw) != evidence["certificate_sha256"] or digest(checker.read_bytes()) != evidence["checker_sha256"]:
            raise ValueError("counterexample certificate or checker hash changed")
        from check_rank_forest_counterexample import verify_certificate
        if not verify_certificate(json.loads(raw)):
            raise ValueError("finite counterexample replay failed")
        verified[review["problem_id"]] = {**evidence, "verification": "exact_replay_of_published_counterexample",
                                          "not_an_original_discovery": True}
    return verified


def apply_batch_items(batches, problems, statements, records):
    """Add reviewed source metadata and exact statements without title matching."""
    for batch in batches:
        provenance = {"batch_id": batch["batch_id"], **batch["_seal"]}
        for item in batch.get("problems", []):
            problem_id, source = item["problem_id"], item["source_id"]
            if not problem_id.startswith(PREFIX + "problem:") or sid(source) not in records:
                raise ValueError("batch references an unregistered source or invalid mother ID")
            if records[sid(source)]["status"] == "excluded":
                raise ValueError("excluded source cannot add mother problems")
            if not item.get("evidence") or not item.get("source_url") or not item.get("checked_at"):
                raise ValueError("new source observation lacks evidence, URL or date")
            status = item["scientific_status"]
            if status not in {"open_in_source", "solved_in_source", "disproved_in_source", "unknown"}:
                raise ValueError("unsupported source status in metadata intake")
            if problem_id not in problems:
                problems[problem_id] = new_problem(problem_id.removeprefix(PREFIX + "problem:"), item["title"], source, status)
            meta = problems[problem_id]["metadata"]
            meta["source_ids"].append(sid(source))
            meta["references"].extend(item["evidence"])
            meta.setdefault("source_catalog_items", []).append({**item, "provenance": provenance})
            if status != meta["scientific_status"]:
                meta["scientific_status"] = "source_status_conflict"
            if item.get("influence_status") == "review_passed":
                meta["influence_status"] = "review_passed"
            if meta["statement_status"] == "missing" and item.get("source_summary"):
                meta["statement_status"] = "summary_only"
            source_meta = records[sid(source)]["metadata"]
            source_meta["ingestion_status"] = "reviewed_metadata_imported"
            source_meta["last_checked_at"] = item["checked_at"]
            source_meta["reviewed_problem_count"] = source_meta.get("reviewed_problem_count", 0) + 1
            progress = record("math_progress", "batch-source-" + short_id(batch["batch_id"] + problem_id),
                              item["title"], "reviewed_primary_source_metadata", {
                                  **item, "problem_id": problem_id, "source_record_id": sid(source),
                                  "record_references": [problem_id, sid(source)], "provenance": provenance,
                                  "verification_level": "source_status_not_independent_proof_audit"})
            records[progress["record_id"]] = progress
        for item in batch.get("statements", []):
            statement_id, problem_id, source = item["statement_id"], item["problem_id"], item["source_id"]
            if not statement_id.startswith(PREFIX + "statement:") or statement_id in statements:
                raise ValueError("duplicate or invalid intake statement ID")
            if problem_id not in problems or sid(source) not in records:
                raise ValueError("intake statement has missing mother or source")
            if records[sid(source)]["status"] == "excluded":
                raise ValueError("excluded source cannot add intake statements")
            if item.get("language") != "natural_language" or not item.get("statement_text") or not item.get("evidence"):
                raise ValueError("intake must provide an evidence-bearing natural-language statement")
            st = record("math_statement", statement_id.removeprefix(PREFIX + "statement:"),
                        problems[problem_id]["title"], "reviewed_intake_statement", {
                            **item, "source_record_id": sid(source), "provenance": provenance,
                            "verified": False, "local_elaboration_checked": False,
                            "record_references": [problem_id, sid(source)]})
            statements[statement_id] = st
            problems[problem_id]["metadata"]["statement_ids"].append(statement_id)
            problems[problem_id]["metadata"]["source_ids"].append(sid(source))
            problems[problem_id]["metadata"]["references"].extend(item["evidence"])
            problems[problem_id]["metadata"]["statement_status"] = "imported_natural_language"
    # Review-only updates may sort before their original intake filename.
    # Resolve them only after all batches have added their statements.
    for batch in batches:
        provenance = {"batch_id": batch["batch_id"], **batch["_seal"]}
        for review in batch.get("discovery_reviews", []):
            source = sid(review["source_id"])
            if source not in records or records[source]["kind"] != "math_source":
                raise ValueError("discovery review has an unregistered source")
            if review.get("decision") not in {
                "excluded_placeholder", "closed_in_literature", "historical_solved_in_source",
                "candidate_identity_pending", "candidate_scope_pending",
            }:
                raise ValueError("unsupported discovery review decision")
            if (not review.get("source_item_id") or not review.get("source_url")
                    or not review.get("evidence") or not review.get("reason")
                    or not review.get("reviewed_at") or review.get("automatic_problem_admission") is not False):
                raise ValueError("discovery review lacks provenance or safe admission boundary")
            reviewed_at = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
            if reviewed_at.tzinfo is None:
                raise ValueError("discovery review timestamp must include timezone")
            references = [source]
            collection = review.get("collection_source_id")
            if collection:
                if collection not in records or records[collection]["kind"] != "math_source" or records[collection]["metadata"].get("parent_source_id") != source:
                    raise ValueError("discovery review has a mismatched source collection")
                references.append(collection)
            candidate = review.get("candidate_problem_id")
            if candidate:
                if candidate not in problems:
                    raise ValueError("discovery review has a missing candidate identity")
                references.append(candidate)
            key = json.dumps([batch["batch_id"], source, review["source_item_id"]], ensure_ascii=False)
            item = record("math_review", "discovery-" + short_id(key),
                          review.get("title", review["source_item_id"]), "source_discovery_review", {
                              **review, "provenance": provenance, "record_references": references,
                              "selection_eligible": False, "research_ready": False,
                              "automatically_closes_problems": False,
                              "creates_or_merges_problem_identity": False})
            if item["record_id"] in records:
                raise ValueError("duplicate discovery review item in batch")
            records[item["record_id"]] = item
        for observation in batch.get("statement_observations", []):
            statement_id = observation["statement_id"]
            if statement_id not in statements or not observation.get("evidence") or observation.get("affects_entire_mother") is not False:
                raise ValueError("statement status review must identify evidence and explicitly scoped effect")
            meta = statements[statement_id]["metadata"]
            meta.setdefault("status_review_observations", []).append(observation)
            meta["source_status_review_required"] = True
            progress = record("math_progress", "statement-status-" + short_id(batch["batch_id"] + statement_id),
                              statements[statement_id]["title"], "statement_status_discrepancy", {
                                  **observation, "problem_id": meta["problem_id"],
                                  "record_references": [statement_id, meta["problem_id"]], "provenance": provenance,
                                  "automatically_closes_problem": False})
            records[progress["record_id"]] = progress
        for update in batch.get("source_statement_evidence_updates", []):
            statement_id = update["statement_id"]
            if statement_id not in statements or not update.get("evidence"):
                raise ValueError("evidence update has missing statement or sources")
            statements[statement_id]["metadata"].setdefault("evidence_updates", []).append({**update, "provenance": provenance})


def build_catalog(paths):
    from problem_catalog_formal import parse_formal_tree
    root = paths.data / DATA_SUBDIR
    registry = json.loads((root / "source-registry.json").read_text())
    records, problems, statements = {}, {}, {}
    sources = {s["source_id"]: s for s in registry["sources"]}
    for source in registry["sources"]:
        value = dict(source)
        value["ingestion_status"] = "registered_not_bulk_harvested"
        item = record("math_source", source["source_id"], source["name"], source["admission"], value)
        records[item["record_id"]] = item
    local_source = record("math_source", "openlabs-reviewed-intake", "OpenLabs 2026-09-05逐题初筛", "local_review", {
        "source_id": "openlabs-reviewed-intake", "role": "local_review",
        "admission": "conditional", "default_bulk_admission": False,
        "reason_zh": "保留既有逐题评议和负面结果，不作为额外的权威上游题库。",
        "source_path": "workspaces/math/problem-curation-20260905/catalog.json"})
    records[local_source["record_id"]] = local_source
    discovery_path = root / "AIM-discovery-r2.json"
    discovery = json.loads(discovery_path.read_text()) if discovery_path.exists() else {"collections": []}
    for collection in discovery["collections"]:
        source = collection["source_id"]
        if sid(source) not in records or not collection.get("evidence") or collection.get("automatic_problem_admission") is not False:
            raise ValueError("collection discovery lacks registered parent or safe admission policy")
        child = record("math_source", "collection-" + collection["collection_id"], collection["title"], "discovery_only", {
            **collection, "entry_type": "collection_not_problem", "parent_source_id": sid(source),
            "checked_at": discovery["checked_at"], "admission": "discovery_only",
            "default_bulk_admission": False, "record_references": [sid(source)],
            "discovery_path": str(discovery_path.relative_to(paths.data)),
            "discovery_sha256": digest(discovery_path.read_bytes())})
        if child["record_id"] in records:
            raise ValueError("duplicate source collection identity")
        records[child["record_id"]] = child
    if discovery["collections"]:
        records[sid("aim-problem-lists")]["metadata"]["discovered_collection_count"] = len(discovery["collections"])
        records[sid("aim-problem-lists")]["metadata"]["ingestion_status"] = "collection_discovery_only"
    pointers = {}
    for source in REPOSITORIES:
        if sources[source]["admission"] == "excluded":
            raise ValueError(f"source is excluded: {source}")
        pointer, manifest, tree = load_snapshot(paths, source)
        pointers[source] = (pointer, manifest, tree)
        records[sid(source)]["metadata"]["ingestion_status"] = "snapshot_imported"
        records[sid(source)]["metadata"]["last_checked_at"] = pointer["checked_at"]
        snapshot = record("math_snapshot", source + ":" + pointer["revision"], source + " immutable snapshot", "verified_hashes", {
            **pointer, "file_count": len(manifest["files"]), "source_record_id": sid(source),
            "record_references": [sid(source)], "upstream_code_executed": False})
        records[snapshot["record_id"]] = snapshot

    ep, em, et = pointers["erdos-problems"]
    erdos_rows = load_erdos_rows(et)
    erdos_yaml_sha256 = digest((et / "data/problems.yaml").read_bytes())
    for row in erdos_rows:
        number = str(row["number"])
        key = "erdos-" + number
        raw_status = row.get("informal_status", row.get("status", {})).get("state")
        status = normalize_status(raw_status)
        problem = new_problem(key, "Erdős #" + number, "erdos-problems", status)
        meta = problem["metadata"]
        meta.update({"canonical_source_key": "erdosproblems.com/" + number,
                     "canonical_erdos_id": number, "influence_status": "benchmark_passed",
                     "influence_reason_zh": "用户以Erdős问题集为参照；官方母题身份通过，子问/技术变体不继承独立母题地位。",
                     "source_status": raw_status, "source_status_checked_at": ep["checked_at"],
                     "source_status_last_update": row.get("informal_status", {}).get("last_update"),
                     "source_formal_proof_status": row.get("formal_status"),
                     "source_statement_formalized_flag": row.get("formalized"),
                     "source_ambiguity_flag": "ambiguous statement" in str(row.get("comments", "")).lower(),
                     "references": [f"https://www.erdosproblems.com/{number}"],
                     "source_metadata": row, "tags": row.get("tags", []),
                     "provenance": {"revision": ep["revision"], "retrieved_at": ep["retrieved_at"],
                                    "source_file": "data/problems.yaml", "sha256": erdos_yaml_sha256},
                     "status_observations": [{"source": sid("erdos-problems"), "status": raw_status,
                                               "scope": "official_numbered_problem", "checked_at": ep["checked_at"]}]})
        problems[problem["record_id"]] = problem
        # Source-reported status is progress metadata, not an independent proof audit.
        progress = record("math_progress", key + ":source-status:" + short_id(json.dumps(row, sort_keys=True)),
                          "Erdős #" + number + " upstream status observation", "source_report_only", {
            "problem_id": problem["record_id"], "source_record_id": sid("erdos-problems"),
            "source_status": raw_status, "reported_update": row.get("informal_status", {}).get("last_update"),
            "checked_at": ep["checked_at"], "comments": row.get("comments"),
            "verification_level": "upstream_metadata_not_independent_proof_audit",
            "record_references": [problem["record_id"], sid("erdos-problems")],
            "references": meta["references"], "provenance": meta["provenance"]})
        records[progress["record_id"]] = progress

    fp, fm, ft = pointers["formal-conjectures"]
    entries = parse_formal_tree(ft, fp["revision"], fp["retrieved_at"])
    seen_formal = set()
    for entry in entries:
        identity = entry["source_item_id"]
        if identity in seen_formal:
            raise ValueError("duplicate qualified formal identity: " + identity)
        seen_formal.add(identity)
        key = canonical_formal_key(entry)
        problem_id = pid(key)
        normalized = normalize_status(entry.get("source_status"))
        if problem_id not in problems:
            problems[problem_id] = new_problem(key, entry["title"], "formal-conjectures", normalized,
                                              entity_type="unmerged_source_statement")
        problem = problems[problem_id]
        meta = problem["metadata"]
        family = PurePosixPath(entry["source_file"]).parts[1]
        meta.setdefault("formal_source_families", []).append(family)
        if key.startswith("fc-"):
            meta["source_family_admission"] = "requires_individual_influence_review"
            meta["source_admission_allows_screening"] = False
            if family in {"Paper", "Arxiv", "Mathoverflow", "OEIS", "Other"}:
                meta["source_family_review_note"] = "来源入口不足以证明影响力；需原始出处及社区影响证据。不得将此目录所有题目一概判为冷门，也不得自动准入。"
            if entry.get("declaration_kind") == "def":
                meta["source_declaration_note"] = "research 分类的定义声明；尚未确认其是否构成独立开放问题。"
        meta["source_ids"].append(sid("formal-conjectures"))
        meta["references"].extend(entry.get("references", []))
        meta["status_observations"].append({"source": sid("formal-conjectures"), "status": entry.get("source_status"),
                                            "scope": "individual_lean_declaration_not_whole_mother_problem",
                                            "source_item_id": identity, "checked_at": fp["checked_at"]})
        statement_id = PREFIX + "statement:fc-" + short_id(identity)
        statement_meta = {k: v for k, v in entry.items()
                          if k not in {"file_context", "source_context", "source_context_text", "full_source", "file_content", "source_text"}}
        statement_meta.update({"problem_id": problem_id, "source_record_id": sid("formal-conjectures"),
                               "language": "lean4", "statement_text": entry["statement_text"],
                               "formalization_status": "lean_source_present_not_locally_verified",
                               "context_artifact_path": str(Path(fp["tree_path"]) / entry["source_file"]),
                               "toolchain": (ft / "lean-toolchain").read_text().strip() if (ft / "lean-toolchain").exists() else None,
                               "local_elaboration_checked": False, "faithfulness_checked": False,
                               "source_proof_label_is_not_local_verification": True,
                               "record_references": [problem_id, sid("formal-conjectures")]})
        item = record("math_statement", "fc-" + short_id(identity), entry["title"], "lean_source_unverified", statement_meta)
        statements[statement_id] = item
        meta["statement_ids"].append(statement_id)
        relation = record("math_relation", "fc-mother-" + short_id(identity), "Source statement associated with mother/problem identity", "source_link_only", {
            "from_id": statement_id, "to_id": problem_id,
            "relation_type": entry.get("relation", "unclassified"),
            "verified_equivalence": False, "scope_note": "same source problem number does not make all variants equivalent",
            "record_references": [statement_id, problem_id]})
        records[relation["record_id"]] = relation

    # Link earlier work without rewriting its historical judgments or files.
    legacy_path = paths.data / "workspaces/math/problem-curation-20260905/catalog.json"
    legacy = json.loads(legacy_path.read_text())
    legacy_map = {}
    for brief in legacy["entries"]:
        item_path = paths.data / brief["storage_path"]
        reviewed = json.loads(item_path.read_text())
        key = reviewed["curation_id"]
        problem_id = pid(key)
        legacy_map[key] = problem_id
        if problem_id not in problems:
            problems[problem_id] = new_problem(key, reviewed["title"], "openlabs-reviewed-intake", reviewed["scientific_status"])
        problem = problems[problem_id]
        problem["title"] = reviewed["title"]
        meta = problem["metadata"]
        meta["source_ids"].append(sid("openlabs-reviewed-intake"))
        meta["legacy_curation_category"] = reviewed["category"]
        meta["legacy_review_retained"] = reviewed["category"] == "retained"
        meta["legacy_review_path"] = str(item_path.relative_to(paths.data))
        meta["legacy_review_sha256"] = digest(item_path.read_bytes())
        meta["legacy_statement_reference"] = reviewed.get("statement_reference")
        meta["local_research_status"] = reviewed["scientific_status"] if reviewed["scientific_status"] in {"locally_resolved", "refuted", "solved_in_literature"} else "not_assessed"
        if meta["influence_status"] != "benchmark_passed":
            meta["influence_status"] = "review_passed" if reviewed["category"] == "retained" else reviewed["category"]
        meta["references"].extend(x for x in reviewed.get("evidence", []) if isinstance(x, str) and x.startswith("http"))
        if reviewed.get("statement") and not reviewed.get("statement_requires_source_read"):
            statement_id = PREFIX + "statement:local-" + short_id(key)
            st = record("math_statement", "local-" + short_id(key), reviewed["title"], "local_intake_statement", {
                "problem_id": problem_id, "source_record_id": sid("openlabs-reviewed-intake"),
                "statement_text": reviewed["statement"], "language": "natural_language",
                "source_path": reviewed["source_path"], "source_sha256": reviewed["source_sha256"],
                "faithfulness_checked": "local_intake_only", "record_references": [problem_id, sid("openlabs-reviewed-intake")]})
            statements[statement_id] = st
            meta["statement_ids"].append(statement_id)
            meta["statement_status"] = "imported_natural_language"
            meta["quantifier_review"] = "pending_independent_scope_review"
        review = record("math_review", "legacy-" + key, reviewed["title"], reviewed["category"], {
            "problem_id": problem_id, "review": reviewed.get("reason_zh"),
            "review_path": reviewed["review_path"], "review_sha256": meta["legacy_review_sha256"],
            "scientific_status_at_review": reviewed["scientific_status"],
            "latest_source_status_wins_for_official_mother": key.startswith("erdos-"),
            "record_references": [problem_id], "references": reviewed.get("evidence", [])})
        records[review["record_id"]] = review

    from problem_catalog_intake import load_reviewed_batches
    batches = load_reviewed_batches(paths)
    apply_batch_items(batches, problems, statements, records)
    # Human-specified aliases are evidence-bearing links, never title heuristics.
    aliases_path = root / "identity-reviews.json"
    identity_reviews = json.loads(aliases_path.read_text()) if aliases_path.exists() else {"decisions": []}
    identity_reviews["decisions"].extend(d for batch in batches for d in batch.get("identity_decisions", []))
    alias_targets = {}
    for decision in identity_reviews["decisions"]:
        left, right = decision["from_id"], decision["to_id"]
        if left == right or decision["relation_type"] not in {"same_problem", "variant_of", "generalization_of", "weakening_of", "implies", "related_to"}:
            raise ValueError("invalid or self-referential identity review")
        if decision["relation_type"] == "same_problem":
            if left in alias_targets and alias_targets[left] != right:
                raise ValueError("conflicting canonical alias targets")
            alias_targets[left] = right
    for start in alias_targets:
        visited, current = set(), start
        while current in alias_targets:
            if current in visited:
                raise ValueError("cyclic canonical alias review")
            visited.add(current)
            current = alias_targets[current]
        alias_targets[start] = current
    for decision in identity_reviews["decisions"]:
        left, right = decision["from_id"], decision["to_id"]
        if left not in problems or right not in problems or not decision.get("evidence"):
            raise ValueError("identity review references missing problem or evidence")
        relation = record("math_relation", "reviewed-" + short_id(left + right + decision["relation_type"]),
                          "Reviewed problem identity relationship", "reviewed", {**decision, "record_references": [left, right]})
        records[relation["record_id"]] = relation
        if decision["relation_type"] == "same_problem":
            canonical = alias_targets[left]
            lm, rm = problems[left]["metadata"], problems[canonical]["metadata"]
            lm["canonical_alias_of"] = canonical
            lm["influence_status"] = "alias_not_independent"
            rm["statement_ids"].extend(lm["statement_ids"])
            rm["source_ids"].extend(lm["source_ids"])
            rm["references"].extend(lm["references"])
            rm.setdefault("reviewed_alias_ids", []).append(left)
            rm["status_observations"].extend(lm["status_observations"])
            if lm["scientific_status"] != rm["scientific_status"] or lm["local_research_status"] in {"locally_resolved", "refuted", "solved_in_literature"}:
                rm["scientific_status"] = "source_status_conflict"
                rm["identity_status_conflict_requires_review"] = True

    progress_path = root / "literature-observations.json"
    literature = json.loads(progress_path.read_text()) if progress_path.exists() else {"entries": []}
    search_runs = [json.loads(path.read_text()) for path in sorted((root / "literature-searches").glob("*.json"))]
    literature_entries = list(literature["entries"])
    for run in search_runs:
        for query in run["queries"]:
            linked = [p for p in query.get("problem_ids", []) if p in problems]
            lookup = record("math_progress", "lookup-" + short_id(run["plan_id"] + query["query_id"] + run["queried_at"]),
                            query["query_id"], query["status"], {
                                **{k: v for k, v in query.items() if k != "entries"},
                                "record_references": linked, "problem_ids": linked,
                                "returned_entry_count": len(query["entries"]),
                                "automatically_closes_problem": False})
            records[lookup["record_id"]] = lookup
            for entry in query["entries"]:
                literature_entries.append({**entry, "queried_at": query["queried_at"]})
    merged_literature = {}
    for observation in literature_entries:
        key = (observation["id"], observation.get("updated", ""))
        if key not in merged_literature:
            merged_literature[key] = {**observation, "problem_ids": list(observation.get("problem_ids", [])), "query_contexts": []}
        item = merged_literature[key]
        item["problem_ids"] = sorted(set(item["problem_ids"] + observation.get("problem_ids", [])))
        if observation.get("query_id"):
            item["query_contexts"].append({"query_id": observation["query_id"], "provenance": observation["provenance"], "relevance": "unassessed"})
        item["queried_at"] = max(item.get("queried_at", ""), observation.get("queried_at", ""))
    for observation in merged_literature.values():
        linked = [p for p in observation.get("problem_ids", []) if p in problems]
        identity = short_id(observation["id"] + observation.get("updated", ""))
        progress = record("math_progress", "arxiv-" + identity, observation["title"], "literature_candidate_unassessed", {
            **observation, "problem_ids": linked, "record_references": linked,
            "verification_level": "bibliographic_metadata_only", "effect_on_problem": "unassessed",
            "automatically_closes_problem": False})
        records[progress["record_id"]] = progress
        for p in linked:
            problems[p]["metadata"].setdefault("literature_observation_ids", []).append(progress["record_id"])
            problems[p]["metadata"]["literature_last_lookup_at"] = observation.get("queried_at") or literature.get("queried_at")

    intake_path = root / "problem-reviews.json"
    intake_reviews = json.loads(intake_path.read_text()).get("reviews", []) if intake_path.exists() else []
    intake_reviews.extend(r for batch in batches for r in batch.get("reviews", []))
    from problem_catalog_intake import current_reviews
    active_reviews, historical_reviews = current_reviews(intake_reviews)
    for review in historical_reviews:
        problem_id = review["problem_id"]
        if problem_id not in problems:
            raise ValueError("historical intake review has no mother identity")
        item = record("math_review", "intake-" + short_id(problem_id + review["reviewed_at"]),
                      problems[problem_id]["title"], "superseded_intake_review", {
                          **review, "record_references": [problem_id],
                          "active_assessment": False, "does_not_certify_lean_or_close_problem": True})
        records[item["record_id"]] = item
    verified_refutations = verify_local_refutations(paths, active_reviews)
    apply_intake_reviews(problems, statements, records, active_reviews, verified_refutations=verified_refutations)
    title_path = root / "problem-title-reviews.json"
    title_reviews = json.loads(title_path.read_text()).get("reviews", []) if title_path.exists() else []
    for review in title_reviews:
        if review["problem_id"] not in problems or not review.get("title") or not review.get("evidence") or not review.get("reason"):
            raise ValueError("invalid display-title review")
        problem = problems[review["problem_id"]]
        problem["metadata"]["legacy_display_title"] = problem["title"]
        problem["metadata"]["display_title_review"] = review
        problem["title"] = review["title"]
    for problem in problems.values():
        finalize_problem(problem, statements)
    records.update(problems)
    records.update(statements)
    for item in records.values():
        for ref in item["metadata"].get("record_references", []):
            if ref not in records:
                raise ValueError("dangling normalized record reference: " + ref)
    records_list = [records[k] for k in sorted(records)]
    summary = {
        "source_registry_entries": len(sources), "source_snapshots_imported": len(pointers),
        "source_subcollections_discovered": len(discovery["collections"]),
        "erdos_mother_problems": len(erdos_rows), "formal_research_declarations": len(entries),
        "formal_declarations_linked_to_erdos": sum(e.get("canonical_erdos_id") is not None for e in entries),
        "formal_erdos_mother_ids": len({e["canonical_erdos_id"] for e in entries if e.get("canonical_erdos_id") is not None}),
        "legacy_review_entries": len(legacy["entries"]), "problem_identity_records": len(problems),
        "unmerged_formal_source_statements": sum(p["metadata"]["entity_type"] == "unmerged_source_statement" for p in problems.values()),
        "record_counts": dict(Counter(r["kind"] for r in records_list)),
        "scientific_status_counts": dict(Counter(p["metadata"]["scientific_status"] for p in problems.values())),
        "screening_eligible": sum(p["metadata"]["screening_eligible"] for p in problems.values()),
        "selection_eligible": sum(p["metadata"]["selection_eligible"] for p in problems.values()),
        "problems_with_lean_source": sum(bool(p["metadata"].get("lean_statement_count")) for p in problems.values()),
        "statements_locally_lean_verified": 0,
        "formal_source_family_counts": dict(Counter(PurePosixPath(e["source_file"]).parts[1] for e in entries)),
        "reviewed_identity_relations": len({(d["from_id"], d["to_id"], d["relation_type"]) for d in identity_reviews["decisions"]}),
        "identity_review_observations": len(identity_reviews["decisions"]),
        "explicit_intake_reviews": len(intake_reviews),
        "active_intake_reviews": len(active_reviews),
        "historical_intake_reviews": len(historical_reviews),
        "reviewed_intake_batches": len(batches),
        "reviewed_source_problem_observations": sum(len(b.get("problems", [])) for b in batches),
        "source_discovery_reviews": sum(len(b.get("discovery_reviews", [])) for b in batches),
        "statement_status_discrepancies": sum(len(b.get("statement_observations", [])) for b in batches),
        "independently_replayed_literature_refutations": len(verified_refutations),
        "canonical_alias_records": sum("canonical_alias_of" in p["metadata"] for p in problems.values()),
        "literature_observations": len(merged_literature),
        "literature_search_queries": sum(len(run["queries"]) for run in search_runs),
        "literature_refresh_status": literature.get("status", "not_run"),
        "problem_count_semantics": "母题身份与尚未合并的来源声明条目；不是全部独立、重要、仍未解猜想数。",
    }
    bundle = {"schema_version": SCHEMA, "namespace": "math-problem-catalog", "generated_at": now(),
              "source_registry_sha256": digest((root / "source-registry.json").read_bytes()),
              "summary": summary, "records": records_list}
    return bundle


def validate_catalog(paths, bundle_path=None):
    from openlabs.math_catalog import load_bundle
    path = bundle_path or paths.data / DATA_SUBDIR / "catalog-bundle.json"
    raw = path.read_bytes()
    loaded = load_bundle(path, data_root=paths.data, expected_sha256=digest(raw))
    records = {r["record_id"]: r for r in loaded["records"]}
    for item in records.values():
        for ref in item["metadata"].get("record_references", []):
            if ref not in records:
                raise ValueError("dangling catalog reference: " + ref)
        if item["kind"] == "math_problem":
            meta = item["metadata"]
            if meta["selection_eligible"] and (meta["scientific_status"] != "open_in_source" or meta.get("source_ambiguity_flag") or meta.get("canonical_alias_of")):
                raise ValueError("unsafe selection gate: " + item["record_id"])
        if item["kind"] == "math_statement" and item["metadata"].get("language") == "lean4":
            meta = item["metadata"]
            if meta.get("local_elaboration_checked") or meta.get("verified"):
                raise ValueError("lexical ingestion cannot claim Lean verification")
            source = paths.artifacts / meta["context_artifact_path"]
            if not source.resolve().is_relative_to(paths.artifacts.resolve()) or digest(source.read_bytes()) != meta["file_sha256"]:
                raise ValueError("Lean context hash mismatch")
    return {"schema_version": "openlabs.math_catalog_validation.v1", "valid": True,
            "bundle_sha256": digest(raw), "bundle_bytes": len(raw), "records": len(records),
            "checks": ["orchestrator_contract", "record_references", "selection_gates", "lean_context_hashes", "no_false_local_proof_verification"]}


def write_catalog(paths):
    bundle = build_catalog(paths)
    root = paths.data / DATA_SUBDIR
    candidate = root / "catalog-bundle.pending.json"
    atomic_write_json(candidate, bundle)
    validation = validate_catalog(paths, candidate)
    immutable_bytes(paths.artifacts / "math-problem-catalog/catalog-bundles" / (validation["bundle_sha256"] + ".json"), candidate.read_bytes())
    candidate.replace(root / "catalog-bundle.json")
    summary = {"generated_at": bundle["generated_at"], **bundle["summary"], **validation}
    atomic_write_json(root / "catalog-summary.json", summary)
    queues = {key: [] for key in ("screening", "selection", "quarantine", "statement_review", "identity_review")}
    for item in bundle["records"]:
        if item["kind"] != "math_problem":
            continue
        meta = item["metadata"]
        brief = {"record_id": item["record_id"], "title": item["title"], "status": item["status"],
                 "influence_status": meta["influence_status"], "next_actions": meta["next_actions"]}
        if meta["screening_eligible"]:
            queues["screening"].append(brief)
        if meta["selection_eligible"]:
            queues["selection"].append(brief)
        if not meta["screening_eligible"]:
            queues["quarantine"].append(brief)
        if meta["screening_eligible"] and not meta["selection_eligible"]:
            queues["statement_review"].append(brief)
        if meta["entity_type"] == "unmerged_source_statement" and not meta.get("canonical_alias_of"):
            queues["identity_review"].append(brief)
    atomic_write_json(root / "review-queues.json", {"generated_at": bundle["generated_at"],
                      "note": "队列可交叠；隔离区也包含已解/状态待核验条目，不等于全部冷门。", **queues})
    return summary


def refresh_literature(paths):
    """Refresh known arXiv references, not an exhaustive proof/status survey."""
    root = paths.data / DATA_SUBDIR
    legacy = json.loads((paths.data / "workspaces/math/problem-curation-20260905/catalog.json").read_text())
    targets = defaultdict(set)
    targets["2605.13171"]  # Formal Conjectures methodology, not problem closure.
    pattern = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?")
    for brief in legacy["entries"]:
        if brief["category"] != "retained":
            continue
        reviewed = json.loads((paths.data / brief["storage_path"]).read_text())
        for identifier in pattern.findall(json.dumps(reviewed.get("evidence", []))):
            targets[identifier].add(pid(reviewed["curation_id"]))
    if len(targets) > 100:
        raise ValueError("reference refresh exceeds single-batch limit; use a reviewed smaller intake")
    endpoint = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({
        "id_list": ",".join(sorted(targets)), "max_results": len(targets)})
    result = {"schema_version": "openlabs.math_literature_observations.v1", "queried_at": now(),
              "status": "pending", "endpoint": endpoint, "requested_ids": sorted(targets),
              "scope": "known arXiv references in retained legacy intake plus source methodology; not exhaustive new-paper search",
              "entries": [], "automatically_closes_problems": False}
    try:
        raw, provenance = fetch(endpoint, max_bytes=8*1024*1024)
        artifact = Path("math-problem-catalog/literature") / (digest(raw) + ".atom.xml")
        immutable_bytes(paths.artifacts / artifact, raw)
        xml = ET.fromstring(raw)
        ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
        for entry in xml.findall("a:entry", ns):
            url = entry.findtext("a:id", "", ns)
            match = pattern.search(url)
            if not match:
                continue
            identifier = match.group(1)
            if identifier not in targets:
                raise ValueError("arXiv returned an unrequested identifier")
            result["entries"].append({"id": identifier, "version_url": url,
                "title": " ".join(entry.findtext("a:title", "", ns).split()),
                "summary": " ".join(entry.findtext("a:summary", "", ns).split()),
                "updated": entry.findtext("a:updated", "", ns),
                "published": entry.findtext("a:published", "", ns),
                "authors": [a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)],
                "doi": entry.findtext("x:doi", None, ns),
                "problem_ids": sorted(targets[identifier]),
                "references": [url], "artifact_path": artifact.as_posix(), "provenance": provenance})
        result["missing_ids"] = sorted(set(targets) - {e["id"] for e in result["entries"]})
        result["status"] = "complete_known_id_lookup" if not result["missing_ids"] else "partial_known_id_lookup"
    except (OSError, ValueError, ET.ParseError) as exc:
        result["status"] = "lookup_failed"
        result["error"] = str(exc)
        # A transient fetch failure must not destroy earlier useful observations.
        previous = root / "literature-observations.json"
        if previous.exists():
            result["entries"] = json.loads(previous.read_text()).get("entries", [])
            result["retained_previous_observations"] = True
    atomic_write_json(root / "literature-observations.json", result)
    return {key: value for key, value in result.items() if key != "entries"} | {"entry_count": len(result["entries"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=str(CODE.parent))
    sub = parser.add_subparsers(dest="command", required=True)
    request = sub.add_parser("fetch")
    request.add_argument("--source", choices=list(REPOSITORIES) + ["all"], default="all")
    sub.add_parser("build")
    sub.add_parser("validate")
    sub.add_parser("refresh-literature")
    seal = sub.add_parser("seal-batch")
    seal.add_argument("--batch", required=True)
    search = sub.add_parser("search-literature")
    search.add_argument("--plan", required=True)
    args = parser.parse_args()
    paths = workspace_paths(args.workspace)
    if args.command == "fetch":
        sources = list(REPOSITORIES) if args.source == "all" else [args.source]
        for source in sources:
            print(json.dumps(fetch_snapshot(paths, source), ensure_ascii=False), flush=True)
    elif args.command == "build":
        print(json.dumps(write_catalog(paths), ensure_ascii=False, indent=2))
    elif args.command == "validate":
        print(json.dumps(validate_catalog(paths), ensure_ascii=False, indent=2))
    elif args.command == "refresh-literature":
        print(json.dumps(refresh_literature(paths), ensure_ascii=False, indent=2))
    elif args.command == "seal-batch":
        from problem_catalog_intake import seal_batch
        print(json.dumps(seal_batch(paths, args.batch, atomic_write_json), ensure_ascii=False, indent=2))
    elif args.command == "search-literature":
        from problem_catalog_literature import search_plan
        print(json.dumps(search_plan(paths, args.plan, fetch, immutable_bytes, atomic_write_json, now), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
