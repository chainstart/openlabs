"""Command line entry point for the OpenLabs paper workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from paper_writing.bundles import validate_result_bundle
from paper_writing.inventory import (
    build_inventory,
    default_config_path,
    default_output_path,
    default_repo_root,
    load_config,
    write_inventory,
)
from paper_writing.operations import (
    apply_review_record,
    canonical_public_manuscript_filename,
    create_paper,
    record_quality_gate,
    reuse_review_for_metadata_only_revision,
    start_revision,
    validate_repository,
)
from paper_writing.manuscript_style import audit_manuscript_style
from paper_writing.support_citations import audit_manuscript_support


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper-writing",
        description="Evidence-backed manuscript writing, revision, and immutable handoff.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Build the derived inventory snapshot.")
    _common_arguments(scan)
    scan.add_argument("--output", default=str(default_output_path()))
    scan.add_argument("--stdout", action="store_true")

    validate = subparsers.add_parser("validate", help="Validate registry, workspaces and references.")
    _common_arguments(validate)
    validate.add_argument("--json", action="store_true")

    support_check = subparsers.add_parser(
        "support-check",
        help="Audit reader-facing support citations against the current Zenodo record.",
    )
    support_check.add_argument("--paper-id", required=True)
    support_check.add_argument("--root", default=str(default_repo_root()))
    support_check.add_argument("--json", action="store_true")

    style_check = subparsers.add_parser(
        "style-check",
        help="Audit manuscript voice, workflow residue, funding eligibility, and AI disclosure.",
    )
    style_check.add_argument("--paper-id", required=True)
    style_check.add_argument("--root", default=str(default_repo_root()))
    style_check.add_argument("--json", action="store_true")

    bundle = subparsers.add_parser("bundle", help="Validate one result bundle.")
    bundle.add_argument("path")
    bundle.add_argument("--json", action="store_true")

    paper = subparsers.add_parser("paper", help="Create a paper workspace or start a revision.")
    paper_commands = paper.add_subparsers(dest="paper_command", required=True)
    create = paper_commands.add_parser("create", help="Create a registered empty manuscript workspace.")
    create.add_argument(
        "--paper-id",
        required=True,
        help=(
            "Descriptive immutable ID: YYYYMMDD-domain-subdomain-keywords, "
            "for example 20260802-math-graph-opg1757-active-newton"
        ),
    )
    create.add_argument("--title", required=True)
    create.add_argument(
        "--project-name",
        help="Optional project name; defaults to the domain-subdomain-keywords suffix.",
    )
    create.add_argument("--created-at", required=True)
    create.add_argument("--domain", required=True)
    create.add_argument("--subdomain", required=True)
    create.add_argument("--venue-type", choices=("conference", "journal"), default="journal")
    create.add_argument("--target-journal")
    create.add_argument("--root", default=str(default_repo_root()))

    revision = paper_commands.add_parser("start-revision", help="Open the next revision record.")
    revision.add_argument("--paper-id", required=True)
    revision.add_argument("--reason", required=True)
    revision.add_argument("--root", default=str(default_repo_root()))

    public_name = paper_commands.add_parser(
        "public-name",
        help="Print the policy-compliant reader-facing PDF filename.",
    )
    public_name.add_argument("--paper-id", required=True)
    public_name.add_argument("--root", default=str(default_repo_root()))

    quality = subparsers.add_parser("quality-gate", help="Record and evaluate an LLM review result.")
    quality.add_argument("--paper-id", required=True)
    quality.add_argument(
        "--venue-type",
        choices=("conference", "journal"),
        required=True,
        help="Actual target venue type; the configured review standard selects the decision vocabulary.",
    )
    quality.add_argument("--score", type=float, required=True)
    quality.add_argument(
        "--decision",
        required=True,
        help="Decision from the configured gate view (currently cas_zone_1_journal).",
    )
    quality.add_argument("--revision-rounds", type=int, default=0)
    quality.add_argument("--root", default=str(default_repo_root()))

    review = subparsers.add_parser(
        "review",
        help="Validate and register a skill-authored review record.",
    )
    review_commands = review.add_subparsers(dest="review_command", required=True)
    review_apply = review_commands.add_parser(
        "apply",
        help="Register one immutable review and apply the configured quality gate.",
    )
    review_apply.add_argument("--paper-id", required=True)
    review_apply.add_argument("--review", required=True)
    review_apply.add_argument(
        "--venue-type", choices=("conference", "journal"), required=True
    )
    review_apply.add_argument(
        "--revision-rounds",
        type=int,
        help="Defaults to the paper's existing completed-round count.",
    )
    review_apply.add_argument("--root", default=str(default_repo_root()))
    review_reuse = review_commands.add_parser(
        "reuse-metadata",
        help=(
            "Reuse a passing review only when scientific manuscript and support "
            "fingerprints are unchanged."
        ),
    )
    review_reuse.add_argument("--paper-id", required=True)
    review_reuse.add_argument("--root", default=str(default_repo_root()))

    zenodo = subparsers.add_parser(
        "zenodo",
        help="Plan or perform a Zenodo deposit; `release` is authorized by the quality gate.",
    )
    zenodo_commands = zenodo.add_subparsers(dest="zenodo_command", required=True)
    plan = zenodo_commands.add_parser("plan", help="Validate metadata and files without using an account.")
    _zenodo_paper_arguments(plan, include_files=True)
    create_draft = zenodo_commands.add_parser("create-draft", help="Create a reversible Zenodo draft.")
    _zenodo_paper_arguments(create_draft, include_files=True)
    create_draft.add_argument("--confirm-production", action="store_true")
    new_version = zenodo_commands.add_parser("new-version", help="Create a new version draft.")
    _zenodo_paper_arguments(new_version, include_files=True)
    new_version.add_argument("--deposition-id", required=True)
    new_version.add_argument("--confirm-production", action="store_true")
    prepare = zenodo_commands.add_parser(
        "prepare",
        help="Build support materials, upload a draft, and reserve its Version DOI.",
    )
    _zenodo_release_arguments(prepare, include_sources=True)
    prepare.add_argument("--output")
    prepare.add_argument("--deposition-id")
    prepare.add_argument("--license")
    prepare.add_argument("--confirm-production", action="store_true")
    verify_draft = zenodo_commands.add_parser(
        "verify-draft",
        help=(
            "Read back a prepared draft and verify metadata and uploaded files "
            "without mutation."
        ),
    )
    _zenodo_paper_arguments(verify_draft, include_files=False)
    release = zenodo_commands.add_parser(
        "release",
        help=(
            "Gate-check and irreversibly publish the prepared Zenodo draft. A passing "
            "quality gate authorizes this; no interactive confirmation is required."
        ),
    )
    _zenodo_release_arguments(release, include_sources=False)
    release.add_argument("--deposition-id")
    release.add_argument(
        "--confirm-paper-id",
        help="Optional; when given it must match --paper-id exactly.",
    )
    release.add_argument(
        "--confirm-production",
        action="store_true",
        help="Accepted for compatibility; the quality gate already authorizes release.",
    )
    publish = zenodo_commands.add_parser("publish", help="Irreversibly publish an existing draft.")
    _zenodo_paper_arguments(publish, include_files=False)
    publish.add_argument("--deposition-id", required=True)
    publish.add_argument("--confirm-paper-id", required=True)
    publish.add_argument("--confirm-production", action="store_true")

    handoff = subparsers.add_parser(
        "handoff",
        help="Build/push immutable manuscript packages or pull external revision requests.",
    )
    handoff_commands = handoff.add_subparsers(dest="handoff_command", required=True)
    handoff_build = handoff_commands.add_parser("build", help="Build source.zip, paper.pdf, and handoff.json.")
    handoff_build.add_argument("--paper-id", required=True)
    handoff_build.add_argument("--output", required=True)
    handoff_build.add_argument("--revision-request-id")
    handoff_build.add_argument("--root", default=str(default_repo_root()))
    handoff_push = handoff_commands.add_parser("push", help="Upload and activate a built handoff package.")
    handoff_push.add_argument("--manifest", required=True)
    handoff_push.add_argument("--api-url", required=True)
    handoff_push.add_argument("--key-env", default="ARA_PAPER_MANAGE_API_KEY")
    handoff_release = handoff_commands.add_parser(
        "release",
        help="Gate, package, synchronize and receipt one Git-frozen paper version.",
    )
    handoff_release.add_argument("--paper-id", required=True)
    handoff_release.add_argument(
        "--api-url",
        default=os.environ.get("ARA_PAPER_MANAGE_API_URL"),
    )
    handoff_release.add_argument("--key-env", default="ARA_PAPER_MANAGE_API_KEY")
    handoff_release.add_argument("--revision-request-id")
    handoff_release.add_argument("--receipt-dir")
    handoff_release.add_argument("--root", default=str(default_repo_root()))
    handoff_sync = handoff_commands.add_parser(
        "sync-ready",
        help="Synchronize changed, Git-frozen ready papers and write release receipts.",
    )
    handoff_sync.add_argument(
        "--paper-id",
        action="append",
        default=[],
        help="Explicit ready paper to synchronize; may be repeated.",
    )
    handoff_sync.add_argument("--base", help="Base Git commit for changed-paper discovery.")
    handoff_sync.add_argument("--head", help="Head Git commit for changed-paper discovery.")
    handoff_sync.add_argument(
        "--api-url",
        default=os.environ.get("ARA_PAPER_MANAGE_API_URL"),
    )
    handoff_sync.add_argument("--key-env", default="ARA_PAPER_MANAGE_API_KEY")
    handoff_sync.add_argument("--root", default=str(default_repo_root()))
    handoff_metadata = handoff_commands.add_parser(
        "sync-metadata",
        help=(
            "Synchronize committed Writing-owned metadata for existing Manage "
            "papers without uploading packages or sending submission-state updates."
        ),
    )
    handoff_metadata.add_argument(
        "--paper-id",
        action="append",
        default=[],
        help="Explicit paper to synchronize; may be repeated.",
    )
    handoff_metadata.add_argument(
        "--base", help="Base Git commit for changed-paper discovery."
    )
    handoff_metadata.add_argument(
        "--head", help="Head Git commit for changed-paper discovery."
    )
    handoff_metadata.add_argument(
        "--api-url",
        default=os.environ.get("ARA_PAPER_MANAGE_API_URL"),
    )
    handoff_metadata.add_argument(
        "--key-env", default="ARA_PAPER_MANAGE_API_KEY"
    )
    handoff_metadata.add_argument("--root", default=str(default_repo_root()))
    handoff_pull = handoff_commands.add_parser("pull-revisions", help="Pull open revision requests into paper workspaces.")
    handoff_pull.add_argument("--api-url", required=True)
    handoff_pull.add_argument("--key-env", default="ARA_PAPER_MANAGE_API_KEY")
    handoff_pull.add_argument("--paper-id")
    handoff_pull.add_argument("--status", default="open")
    handoff_pull.add_argument("--root", default=str(default_repo_root()))
    handoff_claim = handoff_commands.add_parser("claim-revision", help="Claim one external revision request.")
    handoff_claim.add_argument("--api-url", required=True)
    handoff_claim.add_argument("--key-env", default="ARA_PAPER_MANAGE_API_KEY")
    handoff_claim.add_argument("--request-id", required=True)
    handoff_claim.add_argument("--claimed-by", required=True)
    return parser


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(default_repo_root()))
    parser.add_argument("--config", default=str(default_config_path()))


def _zenodo_paper_arguments(parser: argparse.ArgumentParser, *, include_files: bool) -> None:
    _common_arguments(parser)
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    if include_files:
        parser.add_argument("--file", action="append", default=[])


def _zenodo_release_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_sources: bool,
) -> None:
    _common_arguments(parser)
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    if include_sources:
        parser.add_argument(
            "--source",
            action="append",
            default=[],
            help="Repository-owned source file or directory; may be repeated.",
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        payload = build_inventory(args.root, config=load_config(args.config))
        output = write_inventory(payload, args.output)
        summary = payload["summary"]
        print(f"Scanned {summary['total']} papers; {summary['needs_attention']} need attention. Snapshot: {output}")
        if args.stdout:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        result = validate_repository(args.root, settings=args.config)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Registry: {'valid' if result['valid'] else 'invalid'}; papers={result['papers']}")
            for message in result["errors"]:
                print(f"ERROR: {message}")
            for message in result["warnings"]:
                print(f"WARNING: {message}")
        return 0 if result["valid"] else 1
    if args.command == "support-check":
        result = audit_manuscript_support(args.paper_id, root=args.root)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(
                f"Support citations: {'valid' if result['valid'] else 'invalid'}; "
                f"paper={result['paper_id']}; DOI={result['current_version_doi']}"
            )
            for issue in result["errors"]:
                location = issue.get("path", "")
                if issue.get("line") is not None:
                    location = f"{location}:{issue['line']}"
                print(f"ERROR {issue['code']}: {location}: {issue['message']}")
        return 0 if result["valid"] else 1
    if args.command == "style-check":
        result = audit_manuscript_style(args.paper_id, root=args.root)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(
                f"Manuscript style: {'valid' if result['valid'] else 'invalid'}; "
                f"paper={result['paper_id']}; files={len(result['checked_files'])}"
            )
            for issue in result["errors"]:
                location = issue.get("path", "")
                if issue.get("line") is not None:
                    location = f"{location}:{issue['line']}"
                print(f"ERROR {issue['code']}: {location}: {issue['message']}")
        return 0 if result["valid"] else 1
    if args.command == "bundle":
        result = validate_result_bundle(args.path).to_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _bundle_summary(result))
        return 0 if result["valid"] else 1
    if args.command == "paper" and args.paper_command == "create":
        path = create_paper(
            root=args.root,
            paper_id=args.paper_id,
            title=args.title,
            project_name=args.project_name,
            created_at=args.created_at,
            domain=args.domain,
            subdomain=args.subdomain,
            venue_type=args.venue_type,
            target_journal=args.target_journal,
        )
        print(path)
        return 0
    if args.command == "paper" and args.paper_command == "start-revision":
        result = start_revision(args.paper_id, args.reason, root=args.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "paper" and args.paper_command == "public-name":
        print(canonical_public_manuscript_filename(args.paper_id, root=args.root))
        return 0
    if args.command == "quality-gate":
        result = record_quality_gate(
            args.paper_id,
            venue_type=args.venue_type,
            score=args.score,
            decision=args.decision,
            revision_rounds=args.revision_rounds,
            root=args.root,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "review" and args.review_command == "apply":
        result = apply_review_record(
            args.paper_id,
            review=args.review,
            venue_type=args.venue_type,
            revision_rounds=args.revision_rounds,
            root=args.root,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "review" and args.review_command == "reuse-metadata":
        result = reuse_review_for_metadata_only_revision(
            args.paper_id,
            root=args.root,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "zenodo":
        return _run_zenodo(args)
    if args.command == "handoff":
        return _run_handoff(args)
    return 2


def _bundle_summary(result: dict[str, object]) -> str:
    state = "valid" if result["valid"] else "invalid"
    summary = f"Bundle {state}; artifacts={result['checked_artifacts']}; claims={result['checked_claims']}"
    if result.get("producer_repository") and result.get("producer_commit"):
        summary += f"; producer={result['producer_repository']}@{result['producer_commit']}"
    if result.get("manifest_sha256"):
        summary += f"; manifest_sha256={result['manifest_sha256']}"
    return summary


def _run_zenodo(args: argparse.Namespace) -> int:
    from paper_writing.zenodo import (
        ZenodoClient, ZenodoError, build_deposit_plan, create_draft_with_files,
        create_version_with_files, find_paper_record, prepare_zenodo_release,
        publication_registration, publish_zenodo_release, token_from_environment,
        verify_prepared_zenodo_draft,
    )
    from paper_writing.support import SupportPackageError

    try:
        if args.zenodo_command in {"create-draft", "new-version", "prepare", "publish"}:
            if os.environ.get("OPENLABS_ENABLE_EXTERNAL_WRITES") != "1":
                raise ZenodoError(
                    "External writes are disabled. An administrator must explicitly set "
                    "OPENLABS_ENABLE_EXTERNAL_WRITES=1 for this one operation."
                )
        record = find_paper_record(args.paper_id, repo_root=args.root, config_path=args.config)
        configured = record.get("support", {}).get("publication", {}).get("zenodo", {}).get("environment")
        environment = args.environment or os.environ.get("ZENODO_ENVIRONMENT") or configured or "sandbox"
        if args.zenodo_command == "plan":
            result = build_deposit_plan(record, args.file, environment=environment, repo_root=args.root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ready"] else 1
        # `release` is authorized by the passing quality gate that
        # `publish_zenodo_release` revalidates, so it needs no interactive
        # production confirmation.  Every other production mutation still does.
        if (
            environment == "production"
            and args.zenodo_command not in {"release", "verify-draft"}
            and not args.confirm_production
        ):
            raise ZenodoError("Production access requires --confirm-production; test in sandbox first.")
        token = token_from_environment(environment)
        if args.zenodo_command == "create-draft":
            result = create_draft_with_files(record, args.file, environment=environment, token=token, repo_root=args.root)
        elif args.zenodo_command == "new-version":
            result = create_version_with_files(record, args.deposition_id, args.file, environment=environment, token=token, repo_root=args.root)
        elif args.zenodo_command == "prepare":
            result = prepare_zenodo_release(
                args.paper_id,
                args.source,
                environment=environment,
                token=token,
                repo_root=args.root,
                config_path=args.config,
                output=args.output,
                deposition_id=args.deposition_id,
                license_id=args.license,
            )
        elif args.zenodo_command == "release":
            if args.confirm_paper_id is not None and args.confirm_paper_id != args.paper_id:
                raise ZenodoError("--confirm-paper-id must exactly match --paper-id")
            result = publish_zenodo_release(
                args.paper_id,
                environment=environment,
                token=token,
                repo_root=args.root,
                config_path=args.config,
                deposition_id=args.deposition_id,
            )
        elif args.zenodo_command == "verify-draft":
            result = verify_prepared_zenodo_draft(
                args.paper_id,
                environment=environment,
                token=token,
                repo_root=args.root,
                config_path=args.config,
            )
        elif args.zenodo_command == "publish":
            if environment == "production":
                raise ZenodoError(
                    "Direct production publish is disabled; use `zenodo release` so the "
                    "quality gate, Git snapshot and package hashes are revalidated"
                )
            if args.confirm_paper_id != args.paper_id:
                raise ZenodoError("--confirm-paper-id must exactly match --paper-id")
            with ZenodoClient(environment, token) as client:
                draft = client.get_deposition(args.deposition_id)
                if draft.get("submitted") is True:
                    raise ZenodoError("The selected deposition is already published")
                response = client.publish(args.deposition_id)
            result = {"published": response, "config_registration": publication_registration(record, response, environment)}
        else:
            raise ZenodoError(f"Unsupported Zenodo command: {args.zenodo_command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ZenodoError, SupportPackageError) as exc:
        print(f"Zenodo error: {exc}")
        return 2


def _run_handoff(args: argparse.Namespace) -> int:
    from paper_writing.handoff import (
        HandoffError,
        ManageApiClient,
        build_handoff_package,
        changed_registry_paper_ids,
        execute_ready_handoff_plan,
        load_handoff_manifest,
        plan_ready_handoffs,
        release_handoff,
        save_revision_requests,
        sync_writing_metadata_batch,
    )

    try:
        if args.handoff_command != "build" and os.environ.get("OPENLABS_ENABLE_EXTERNAL_WRITES") != "1":
            raise HandoffError(
                "Remote handoff is disabled. An administrator must explicitly set "
                "OPENLABS_ENABLE_EXTERNAL_WRITES=1 for this one operation."
            )
        if args.handoff_command == "build":
            result = build_handoff_package(
                args.paper_id,
                root=args.root,
                output=args.output,
                revision_request_id=args.revision_request_id,
            )
        elif args.handoff_command == "push":
            manifest = load_handoff_manifest(args.manifest)
            with ManageApiClient.from_environment(
                args.api_url, key_environment=args.key_env
            ) as client:
                result = client.push_package(manifest)
        elif args.handoff_command == "release":
            if not args.api_url:
                raise HandoffError(
                    "Missing --api-url or ARA_PAPER_MANAGE_API_URL"
                )
            with ManageApiClient.from_environment(
                args.api_url, key_environment=args.key_env
            ) as client:
                result = release_handoff(
                    args.paper_id,
                    root=args.root,
                    client=client,
                    revision_request_id=args.revision_request_id,
                    receipt_dir=args.receipt_dir,
                )
        elif args.handoff_command == "sync-ready":
            if bool(args.base) != bool(args.head):
                raise HandoffError("--base and --head must be provided together")
            paper_ids = list(args.paper_id)
            if args.base and args.head:
                paper_ids.extend(
                    changed_registry_paper_ids(
                        root=args.root,
                        base=args.base,
                        head=args.head,
                    )
                )
            if not paper_ids and not (args.base and args.head):
                raise HandoffError(
                    "Provide --paper-id or both --base and --head"
                )
            plan = plan_ready_handoffs(paper_ids, root=args.root)
            if not plan["pending"]:
                result = {
                    "candidates": plan["candidates"],
                    "released": [],
                    "metadata_synced": [],
                    "skipped": plan["skipped"],
                    "errors": plan["errors"],
                    "ok": not plan["errors"],
                }
            else:
                if not args.api_url:
                    raise HandoffError(
                        "Missing --api-url or ARA_PAPER_MANAGE_API_URL"
                    )
                with ManageApiClient.from_environment(
                    args.api_url, key_environment=args.key_env
                ) as client:
                    result = execute_ready_handoff_plan(
                        plan,
                        root=args.root,
                        client=client,
                    )
        elif args.handoff_command == "sync-metadata":
            if bool(args.base) != bool(args.head):
                raise HandoffError("--base and --head must be provided together")
            paper_ids = list(args.paper_id)
            if args.base and args.head:
                paper_ids.extend(
                    changed_registry_paper_ids(
                        root=args.root,
                        base=args.base,
                        head=args.head,
                    )
                )
            if not paper_ids and not (args.base and args.head):
                raise HandoffError(
                    "Provide --paper-id or both --base and --head"
                )
            if not args.api_url:
                raise HandoffError(
                    "Missing --api-url or ARA_PAPER_MANAGE_API_URL"
                )
            with ManageApiClient.from_environment(
                args.api_url, key_environment=args.key_env
            ) as client:
                result = sync_writing_metadata_batch(
                    paper_ids,
                    root=args.root,
                    client=client,
                )
        elif args.handoff_command == "pull-revisions":
            with ManageApiClient.from_environment(
                args.api_url, key_environment=args.key_env
            ) as client:
                requests = client.list_revision_requests(
                    status=args.status, paper_id=args.paper_id
                )
            written = save_revision_requests(requests, root=args.root)
            result = {
                "requests": len(requests),
                "files": [str(path) for path in written],
            }
        elif args.handoff_command == "claim-revision":
            with ManageApiClient.from_environment(
                args.api_url, key_environment=args.key_env
            ) as client:
                result = client.claim_revision(
                    args.request_id, claimed_by=args.claimed_by
                )
        else:
            raise HandoffError(f"Unsupported handoff command: {args.handoff_command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not isinstance(result, dict) or result.get("ok", True) else 2
    except (HandoffError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Handoff error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
