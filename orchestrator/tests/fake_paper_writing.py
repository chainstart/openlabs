"""Stand-in for the ``paper-writing`` CLI in release-pipeline tests (no network, no models).

The paper is a JSON file ``registry/papers/<id>.json`` in a real Git data
repository. It holds the state the real commands would derive from the YAML
registry and the manuscript: open delivery-exit issues (with their remedy), the
support record, the manuscript hash the ready decision is bound to, and the
delivery block. Each call is appended to ``$FAKE_PAPER_LOG`` (outside the
repository) together with whether the external-write switch was set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _paths(root: Path, paper_id: str) -> list[str]:
    return [f"registry/papers/{paper_id}.json", f"papers/{paper_id}", f"reviews/unified/{paper_id}"]


def _manuscript_hash(root: Path, paper_id: str) -> str:
    return hashlib.sha256((root / "papers" / paper_id / "main.tex").read_bytes()).hexdigest()


def _git_dirty(root: Path, paths: list[str]) -> list[str]:
    output = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all", "--", *paths],
                            cwd=root, capture_output=True, text=True, check=True).stdout
    return [line for line in output.splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("words", nargs="+")
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--environment")
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--confirm-paper-id")
    parser.add_argument("--delta-only", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)
    command = " ".join(args.words)
    registry = root / "registry" / "papers" / f"{args.paper_id}.json"
    paper = json.loads(registry.read_text())
    external = os.environ.get("OPENLABS_ENABLE_EXTERNAL_WRITES") == "1"
    with open(os.environ["FAKE_PAPER_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"command": command, "external_writes": external,
                              "argv": argv}) + "\n")
    failures = paper.get("fail", {})
    if failures.get(command, 0) > 0:
        failures[command] -= 1
        registry.write_text(json.dumps(paper, indent=2))
        print(f"{command} failed (simulated)")
        return 2

    def save() -> None:
        registry.write_text(json.dumps(paper, indent=2, sort_keys=True))

    support = paper["support"]
    if command == "program release-status":
        current = (paper["review"]["snapshot"] == _manuscript_hash(root, args.paper_id)
                   and (support["status"] == "not_required"
                        or paper["review"].get("support_sha") == support.get("package_sha")))
        required = support["status"] != "not_required"
        print(json.dumps({
            "paper_id": args.paper_id, "version": paper["version"],
            "review": {"ready": paper["review"]["ready"], "current": current, "problems": []},
            "support": {"required": required, "status": support["status"],
                        "prepare_needed": required and support["status"] == "planned",
                        "release_needed": required and support["status"] == "draft",
                        "standing_production_release_authorization": paper["authorization"]},
            "issues": paper["issues"], "notes": paper.get("notes", []),
            "writer_scope": "Fix only the listed problems.",
            "commit_paths": _paths(root, args.paper_id),
            "git": {"dirty": _git_dirty(root, _paths(root, args.paper_id))},
            "delivered": bool(paper.get("delivery")), "delivery": paper.get("delivery"),
        }))
        return 0
    if command == "zenodo prepare":
        assert external and args.confirm_production and args.environment == "production"
        support.update({"status": "draft", "doi": "10.5281/zenodo.17000001",
                        "package_sha": "a" * 64})
        paper["issues"] = [i for i in paper["issues"] if i["remedy"] != "zenodo_prepare"]
        paper["issues"] += paper.pop("after_prepare_issues", [])
        save()
        print(json.dumps({"status": "draft", "reserved_version_doi": support["doi"],
                          "archive_sha256": support["package_sha"]}))
        return 0
    if command == "support-check":
        print(json.dumps({"valid": True, "errors": []}))
        return 0
    if command == "review unified-run":
        assert args.delta_only
        if not paper.get("delta_eligible", True):
            print(json.dumps({"outcome": "full_review_required", "review_mode": "delta_check",
                              "full_review_reasons": ["title changed"], "run_dir": "reviews/unified/x"}))
            return 0
        paper["review"].update({"snapshot": _manuscript_hash(root, args.paper_id),
                                "support_sha": support.get("package_sha"), "mode": "delta"})
        run = root / "reviews" / "unified" / args.paper_id / f"delta-{len(paper['review'])}"
        run.mkdir(parents=True, exist_ok=True)
        (run / "decision.json").write_text(json.dumps({"review_mode": "delta"}))
        save()
        print(json.dumps({"outcome": "ready", "review_mode": "delta",
                          "run_dir": str(run.relative_to(root)), "decision_sha256": "d" * 64}))
        return 0
    if command == "zenodo release":
        assert external and args.confirm_paper_id == args.paper_id
        if _git_dirty(root, _paths(root, args.paper_id)):
            print("Zenodo error: Release files differ from Git HEAD")
            return 2
        support["status"] = "published"
        save()
        print(json.dumps({"status": "published", "version_doi": support["doi"],
                          "concept_doi": "10.5281/zenodo.17000000", "receipt": "r.json"}))
        return 0
    if command == "program deliver":
        assert external
        dirty = _git_dirty(root, _paths(root, args.paper_id))
        if dirty or paper["issues"] or support["status"] not in {"published", "not_required"}:
            print(json.dumps({"status": "failed", "error": f"not deliverable: {dirty}"}))
            return 1
        paper["delivery"] = {"awaiting_owner_review": True, "package_id": "pkg-1",
                             "version": paper["version"], "submission_handler": None}
        save()
        print(json.dumps({"status": "delivered", "paper_id": args.paper_id, "package_id": "pkg-1",
                          "awaiting_owner_review": True, "submission_handler": None}))
        return 0
    print(f"unsupported fake command {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
