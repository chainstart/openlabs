"""Register the authors' response recomputations as revision evidence.

``support.publication.source_files`` is the reviewed support set: its names and
bytes form ``support_sources_sha256``, which every unified decision binds. A
script or result made only to answer an archived decision (a resynthesis reply
or a factual rebuttal, neither of which opens a review round) belongs in
``support.publication.revision_evidence`` instead. It stays in the repository
and is cited by path and SHA-256 from the reply, but it is not part of the
support package and does not change the reviewed fingerprint.

``register`` records such files, and moves entries that were registered in
``source_files`` by mistake. It writes only the registry record; the files and
the manuscript are untouched. A move is refused while the current support
digest still equals the one the basis decision reviewed (the files were then
part of what the referees saw).
"""

import json
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "openlabs.revision_evidence.v1"


def _latest_decision(root, paper_id, metadata):
    from paper_writing import review_flow as flow

    target = metadata.get("target_conference" if metadata.get("venue_type") == "conference" else "target_journal")
    rows = [row for row in flow.completed_rounds(root, paper_id, str(target or ""))
            if row.get("stage_reached") == "decision" and row.get("review_mode", "full") == "full"]
    return rows[-1]["_path"] if rows else None


def register(paper_id, *, root, paths, actor, reason, decision=None):
    from paper_writing.registry import load_paper_metadata, require_not_frozen, write_paper_metadata
    from paper_writing.support import sha256_file, support_sources_snapshot_sha256

    for key, value in (("actor", actor), ("reason", reason)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Provide a nonempty {key}")
    if not paths:
        raise ValueError("Name at least one file")
    root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, root)
    require_not_frozen(metadata, paper_id)
    workspace = str(metadata.get("workspace") or f"papers/{paper_id}").strip("/")
    support = dict(metadata.get("support") or {})
    publication = dict(support.get("publication") or {})
    sources = list(publication.get("source_files") or [])
    entries = [dict(row) for row in publication.get("revision_evidence") or []]
    now = datetime.now(UTC).isoformat(timespec="seconds")
    moved, added = [], []
    for raw in paths:
        relative = Path(str(raw)).as_posix().strip("/")
        path = root / relative
        if (Path(raw).is_absolute() or ".." in Path(relative).parts
                or not relative.startswith(f"{workspace}/revisions/")):
            raise ValueError(f"{raw}: revision evidence lies under {workspace}/revisions/")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{raw}: not a regular file")
        listed = [item for item in sources if Path(str(item)).as_posix().strip("/") == relative]
        sources = [item for item in sources if item not in listed]
        (moved if listed else added).append(relative)
        entries = [row for row in entries if row.get("path") != relative]
        entries.append({"path": relative, "sha256": sha256_file(path), "registered_at": now,
                        "actor": actor, "reason": reason,
                        "removed_from_support_sources": bool(listed)})
    before = support_sources_snapshot_sha256(metadata, repo_root=root)
    basis = Path(decision) if decision else _latest_decision(root, paper_id, metadata)
    reviewed = None
    if basis is not None:
        basis = basis if basis.is_absolute() else root / basis
        if basis.is_dir():
            basis /= "decision.json"
        reviewed = (json.loads(basis.read_text()).get("fingerprints") or {}).get("support_sources_sha256")
    if moved and reviewed is not None and before == reviewed:
        raise ValueError("The current support sources are those the basis decision reviewed; "
                         "moving files out would unbind that review")
    publication["source_files"] = sources
    publication["revision_evidence"] = entries
    support["publication"] = publication
    updated = {**metadata, "support": support}
    after = support_sources_snapshot_sha256(updated, repo_root=root)
    write_paper_metadata(paper_id, updated, root)
    return {"schema": SCHEMA, "paper_id": paper_id, "status": "registered",
            "moved_from_support_sources": moved, "added": added,
            "support_sources_sha256_before": before, "support_sources_sha256": after,
            "basis_decision": basis.relative_to(root).as_posix() if basis is not None else None,
            "reviewed_support_sources_sha256": reviewed,
            "matches_review": (after == reviewed) if reviewed is not None else None}
