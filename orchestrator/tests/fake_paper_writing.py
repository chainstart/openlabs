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


def _no_remote_network() -> None:
    """``FAKE_LOOPBACK_ONLY=1``: any connection to a non-loopback address fails at once."""

    import socket

    original = socket.socket.connect

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if self.family in (socket.AF_INET, socket.AF_INET6) and host not in {
                "127.0.0.1", "::1", "localhost"}:
            raise OSError(f"fake paper-writing: refusing a non-loopback connection to {host}")
        return original(self, address)

    socket.socket.connect = connect


def _service(base: str, method: str, path: str, *, token: str, body: bytes | None = None,
             content_type: str = "application/json") -> dict:
    """One request to a fake service (loopback only; never through a proxy)."""

    import urllib.request
    from urllib.parse import urlsplit

    url = base.rstrip("/") + path
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(f"fake paper-writing only talks to loopback services, not {url}")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": content_type})
    with opener.open(request, timeout=10) as response:
        text = response.read().decode() or "{}"
    return json.loads(text)


def _loopback(url: str | None) -> bool:
    return bool(url) and str(url).startswith(("http://127.0.0.1", "http://localhost"))


def main(argv: list[str]) -> int:
    if os.environ.get("FAKE_LOOPBACK_ONLY") == "1":
        _no_remote_network()
    if argv[:2] == ["review", "round-usage"]:
        # The tick's read-only round report (B4): not part of the release pipeline, not logged.
        print(json.dumps({"schema_version": "openlabs.review_round_usage.v1", "papers": [],
                          "cross_journal_budget": None}))
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("words", nargs="+")
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--environment")
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--confirm-paper-id")
    parser.add_argument("--delta-only", action="store_true")
    parser.add_argument("--source")
    parser.add_argument("--artifact-manifest", action="append", default=[])
    parser.add_argument("--reason")
    parser.add_argument("--decided-by")
    args = parser.parse_args(argv)
    root = Path(args.root)
    command = " ".join(args.words)
    registry = root / "registry" / "papers" / f"{args.paper_id}.json"
    external = os.environ.get("OPENLABS_ENABLE_EXTERNAL_WRITES") == "1"
    with open(os.environ["FAKE_PAPER_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"command": command, "external_writes": external,
                              "argv": argv,
                              # Names only (tests check which credentials a child got).
                              "credentials": sorted(
                                  name for name in ("ARA_PAPER_MANAGE_API_URL",
                                                    "ARA_PAPER_MANAGE_API_KEY",
                                                    "ZENODO_ACCESS_TOKEN")
                                  if os.environ.get(name)),
                              "api_url": os.environ.get("ARA_PAPER_MANAGE_API_URL")}) + "\n")
    if command == "program adopt":
        # The paper lives in the campaign workspace: copy it (registry + paper tree).
        source = Path(args.source)
        if (source / "LAYOUT-UNSUPPORTED").is_file():
            print(json.dumps({"status": "blocked", "reason": "layout_unsupported",
                              "detail": "manuscript_dir is 'manuscript', outside papers/<id>/"}))
            return 0
        if not (source / "registry" / "papers" / f"{args.paper_id}.json").is_file():
            print(json.dumps({"status": "failed", "error": "no workspace registry record"}))
            return 1
        import shutil

        for relative in (f"registry/papers/{args.paper_id}.json", f"papers/{args.paper_id}"):
            origin, target = source / relative, root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if origin.is_dir():
                shutil.copytree(origin, target, dirs_exist_ok=True)
            else:
                shutil.copy2(origin, target)
        print(json.dumps({"status": "adopted", "paper_id": args.paper_id, "copied": 2,
                          "evidence_restored": 0, "evidence_missing": [],
                          "pdf_restored": None}))
        return 0
    paper = json.loads(registry.read_text())
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
            "release_artifacts_unbound": paper.get("unbound_artifacts", []),
            "oversize_payloads_unbound": paper.get("oversize_payloads", []),
            "support_sources_unadopted": paper.get("unadopted_sources", []),
            "commit_paths": _paths(root, args.paper_id),
            "git": {"dirty": _git_dirty(root, _paths(root, args.paper_id))},
            # Delivered means: the current version (a newer one needs a new delivery).
            "delivered": bool((paper.get("delivery") or {}).get("package_id"))
                         and paper["delivery"].get("version") == paper["version"],
            "delivery": paper.get("delivery"),
            "submission_materials": paper.get("submission_materials"),
        }))
        return 0
    if command == "submission prepare":
        # Drafts the cover letter and checks the LaTeX; "stuck" simulates a run that writes
        # no receipt (the pipeline must not call it again for the same version).
        materials = paper.get("submission_materials") or {}
        if not materials.get("stuck"):
            materials["pending"] = False
        paper["submission_materials"] = materials
        save()
        print(json.dumps({"ok": True, "flatten": {"status": "verified"},
                          "draft": {"status": "drafted", "reviewers_kept": 3}}))
        return 0
    if command == "program bind-release-artifacts":
        assert not external
        files = paper.pop("unbound_artifacts", [])
        manifest = root / "papers" / args.paper_id / "production" / "release-artifacts.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"files": files}))
        paper["submission_package"] = {"artifact_manifest": {"path": str(manifest.relative_to(root))}}
        save()
        print(json.dumps({"status": "bound" if files else "not_needed", "files": files,
                          "manifest": str(manifest.relative_to(root))}))
        return 0
    if command == "program relocate-support-sources":
        assert not external
        moved = paper.pop("unadopted_sources", [])
        save()
        print(json.dumps({"status": "relocated" if moved else "not_needed",
                          "relocated": [{"from": item, "to": item} for item in moved],
                          "matches_review": True if moved else None}))
        return 0
    if command == "program bind-oversize-payloads":
        assert not external
        files = paper.pop("oversize_payloads", [])
        manifest = root / "papers" / args.paper_id / "production" / "payload-artifacts.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"files": [{"path": item} for item in files]}))
        for item in files:
            ignore = (root / item).parent / ".gitignore"
            ignore.write_text("/" + Path(item).name + "\n")
        save()
        print(json.dumps({"status": "bound" if files else "not_needed",
                          "files": [{"path": item} for item in files],
                          "manifest": str(manifest.relative_to(root))}))
        return 0
    if command == "program waive-support":
        assert not external and args.reason and args.decided_by
        if support["status"] == "not_required":
            print(json.dumps({"status": "unchanged", "mode": "not_required"}))
            return 0
        if support["status"] != "planned":
            print(json.dumps({"status": "blocked", "reason": "support_record_exists",
                              "detail": f"support status {support['status']}"}))
            return 0
        if paper.get("cites_deposit"):
            print(json.dumps({"status": "blocked", "reason": "manuscript_cites_deposit",
                              "detail": "the data-availability section names a Zenodo deposit"}))
            return 0
        support.update({"status": "not_required", "not_required_reason": args.reason,
                        "not_required_recorded_by": args.decided_by})
        paper["issues"] = [i for i in paper["issues"] if i["remedy"] != "zenodo_prepare"]
        save()
        print(json.dumps({"status": "waived", "mode": "not_required", "reason": args.reason}))
        return 0
    if command == "zenodo prepare":
        assert external and args.confirm_production and args.environment == "production"
        support.update({"status": "draft", "doi": "10.5281/zenodo.17000001",
                        "package_sha": "a" * 64})
        zenodo = os.environ.get("FAKE_ZENODO_URL")
        if zenodo:
            # Like the real client: a draft deposition, then the archive into its bucket.
            token = os.environ.get("ZENODO_ACCESS_TOKEN", "")
            if not token:
                print("Zenodo error: ZENODO_ACCESS_TOKEN is not set")
                return 2
            draft = _service(zenodo, "POST", "/api/deposit/depositions", token=token,
                             body=json.dumps({"metadata": {"title": args.paper_id}}).encode())
            archive = (root / "papers" / args.paper_id / "main.tex").read_bytes()
            bucket = draft["links"]["bucket"].split("/api/", 1)[1]
            _service(zenodo, "PUT", f"/api/{bucket}/support.zip", token=token, body=archive,
                     content_type="application/octet-stream")
            support.update({"doi": draft["metadata"]["prereserve_doi"]["doi"],
                            "deposition_id": draft["id"],
                            "package_sha": hashlib.sha256(archive).hexdigest()})
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
        if paper.get("delta_outcome"):
            # A preflight/verification result (preflight_failed, formal_check_blocked, ...).
            print(json.dumps({"outcome": paper["delta_outcome"], "review_mode": "delta",
                              "run_dir": "reviews/unified/blocked"}))
            return 0
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
        if paper.get("unbound_artifacts"):
            # The real gate: every release file (ignored PDF/.bbl too) in Git or bound.
            print("Zenodo error: Support release files are not committed to Git: "
                  + ", ".join(paper["unbound_artifacts"]))
            return 2
        if _git_dirty(root, _paths(root, args.paper_id)):
            print("Zenodo error: Release files differ from Git HEAD")
            return 2
        concept = "10.5281/zenodo.17000000"
        zenodo = os.environ.get("FAKE_ZENODO_URL")
        if zenodo:
            published = _service(zenodo, "POST", f"/api/deposit/depositions/"
                                 f"{support['deposition_id']}/actions/publish",
                                 token=os.environ.get("ZENODO_ACCESS_TOKEN", ""))
            support["doi"], concept = published["doi"], published["conceptdoi"]
        support["status"] = "published"
        save()
        print(json.dumps({"status": "published", "version_doi": support["doi"],
                          "concept_doi": concept, "receipt": "r.json"}))
        return 0
    if command == "program deliver":
        assert external
        dirty = _git_dirty(root, _paths(root, args.paper_id))
        if paper.get("unbound_artifacts"):
            print(json.dumps({"status": "failed",
                              "error": "Release files are not committed to Git"}))
            return 1
        if dirty or paper["issues"] or support["status"] not in {"published", "not_required"}:
            print(json.dumps({"status": "failed", "error": f"not deliverable: {dirty}"}))
            return 1
        if paper.get("deliver_error_once"):
            # A failure of the command itself, behind the resource guard's stderr banner
            # (the wrapper prints it): the JSON error on stdout is what must be recorded.
            error = paper.pop("deliver_error_once")
            save()
            print(json.dumps({"status": "failed", "error": error}))
            return 1
        package = f"pkg-{paper['version']}" if paper.get("delivery") else "pkg-1"
        manage = os.environ.get("ARA_PAPER_MANAGE_API_URL")
        if _loopback(manage):
            created = _service(manage, "POST", "/api/packages",
                               token=os.environ.get("ARA_PAPER_MANAGE_API_KEY", ""),
                               body=json.dumps({"paper_id": args.paper_id,
                                                "version": paper["version"],
                                                "support_doi": support.get("doi"),
                                                "submission_handler": None}).encode())
            package = created["package_id"]
        paper["delivery"] = {"awaiting_owner_review": True, "package_id": package,
                             "version": paper["version"], "submission_handler": None}
        save()
        print(json.dumps({"status": "delivered", "paper_id": args.paper_id, "package_id": package,
                          "awaiting_owner_review": True, "submission_handler": None}))
        return 0
    print(f"unsupported fake command {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
