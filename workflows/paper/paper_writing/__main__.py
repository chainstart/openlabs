"""Command line entry point for the OpenLabs paper workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from paper_writing.bundles import validate_result_bundle
from paper_writing.inventory import (
    build_inventory,
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

    history = subparsers.add_parser("journal-history", help="Refresh/query shared team rejection history before journal selection.")
    history_commands = history.add_subparsers(dest="history_command", required=True)
    history_sync = history_commands.add_parser("sync", help="Read management-site history and atomically refresh the local ledger and table.")
    history_sync.add_argument("--root", default=str(default_repo_root()))
    history_sync.add_argument("--snapshot", help="Import a previously captured full management-site JSON snapshot instead of using the API.")
    history_check = history_commands.add_parser("check", help="Check a candidate; three distinct rejected papers exclude it by default.")
    history_check.add_argument("--root", default=str(default_repo_root()))
    history_check.add_argument("--journal", required=True)
    history_summary = history_commands.add_parser("summary", help="Show the generated per-journal table.")
    history_summary.add_argument("--root", default=str(default_repo_root()))

    venue = subparsers.add_parser(
        "venue",
        help="Local registry of verified journals (registry/verified-venues.yaml): read it "
             "before checking a journal online.",
    )
    venue_commands = venue.add_subparsers(dest="venue_command", required=True)
    venue_lookup = venue_commands.add_parser(
        "lookup", help="Is the journal verified and eligible (exit 0), pending or not eligible "
                       "(1), or not registered (3)?")
    venue_lookup.add_argument("--journal")
    venue_lookup.add_argument("--issn")
    venue_alternatives = venue_commands.add_parser(
        "alternatives", help="Verified, eligible journals of the registry.")
    venue_alternatives.add_argument("--zone", type=int, action="append", default=[],
                                    help="2025 CAS zone (repeatable).")
    venue_alternatives.add_argument("--category", help="Part of the CAS major category name.")
    venue_alternatives.add_argument("--exclude", help="A journal to leave out (the current one).")
    venue_pending = venue_commands.add_parser(
        "mark-pending",
        help="Record a journal whose evidence could not be read (HTTP 403/406 ...) as "
             "pending_verification; never downgrades a verified entry.")
    venue_pending.add_argument("--journal", required=True)
    venue_pending.add_argument("--issn")
    venue_pending.add_argument("--url", help="The page that refused the request.")
    venue_pending.add_argument("--http-status", type=int)
    venue_pending.add_argument("--reason", required=True)
    venue_pending.add_argument("--by", required=True, help="Model or person recording it.")
    for command in (venue_lookup, venue_alternatives, venue_pending):
        command.add_argument("--root", default=str(default_repo_root()))
    cadence = subparsers.add_parser("cadence", help="Check team submission spacing before an actual submission.")
    cadence_commands = cadence.add_subparsers(dest="cadence_command", required=True)
    cadence_check = cadence_commands.add_parser("check", help="Exit 0 when allowed, 1 when blocked, 2 when the ledger is unusable.")
    cadence_check.add_argument("--root", default=str(default_repo_root()))
    cadence_check.add_argument("--venue", required=True, help="Journal or conference name.")
    cadence_check.add_argument("--paper-id", required=True)

    submissions = subparsers.add_parser("submissions", help="Read-only monitoring of ongoing submissions.")
    submission_commands = submissions.add_subparsers(dest="submissions_command", required=True)
    monitor = submission_commands.add_parser("monitor", help="Report revision deadlines, stale attempts and missing letters.")
    monitor.add_argument("--snapshot", help="Full management-site paper-detail JSON; default reads the API (GET only).")
    monitor.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")

    rewrite = subparsers.add_parser("rewrite", help="Editor-facing rewrite pass before the unified review.")
    rewrite_commands = rewrite.add_subparsers(dest="rewrite_command", required=True)
    rewrite_run = rewrite_commands.add_parser("run", help="Rewrite abstract/Introduction/closing with every configured model and select blind.")
    rewrite_run.add_argument("paper_id")
    rewrite_run.add_argument("--root", default=str(default_repo_root()))
    rewrite_run.add_argument("--rewriter", action="append", help="Limit to these configured rewriters.")
    rewrite_run.add_argument("--apply", action="store_true", help="Write the selected candidate into the sources.")
    rewrite_apply = rewrite_commands.add_parser("apply", help="Apply the selection of an earlier run.")
    rewrite_apply.add_argument("paper_id")
    rewrite_apply.add_argument("run_dir")
    rewrite_apply.add_argument("--root", default=str(default_repo_root()))
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

    narrative = subparsers.add_parser(
        "narrative-check",
        help="Main-text length, abstract, hedging, stacked qualifiers, revision history and empty "
             "transitions, with line numbers (also part of style-check).",
    )
    narrative_target = narrative.add_mutually_exclusive_group(required=True)
    narrative_target.add_argument("--paper-id")
    narrative_target.add_argument("--tex", help="Check one TeX file (with its inputs) without a registry record.")
    narrative.add_argument("--root", default=str(default_repo_root()))
    narrative.add_argument("--line", help="Research line whose paper_narrative limits apply.")
    narrative.add_argument("--json", action="store_true")
    narrative.add_argument("--out", help="Also write the Markdown report to this file.")

    floor = subparsers.add_parser("delivery-floor", help="Audit the mechanical delivery minimums without editing files.")
    floor.add_argument("--paper-id", required=True)
    floor.add_argument("--root", default=str(default_repo_root()))
    floor.add_argument("--author", action="store_true", help="Check author-controlled items before independent review.")

    story = subparsers.add_parser("story-review", help="Have the active editor read the one-page storyline.")
    story.add_argument("--paper-id", required=True)
    story.add_argument("--root", default=str(default_repo_root()))

    reader = subparsers.add_parser(
        "reader-check",
        help="One-pass simulated reader of the main text in a fresh model process (writer's own "
             "check; saved to papers/<id>/writing/reader-check.md).",
    )
    reader.add_argument("--paper-id", required=True)
    reader.add_argument("--root", default=str(default_repo_root()))
    reader.add_argument("--provider", help="anthropic or openai-codex (with --tool and --model).")
    reader.add_argument("--tool", help="Claude Code or Codex.")
    reader.add_argument("--model")
    reader.add_argument("--timeout", type=int, default=1800)
    reader_mode = reader.add_mutually_exclusive_group()
    reader_mode.add_argument("--prompt-only", action="store_true",
                             help="Write the reader packet for a sub-agent instead of calling a model.")
    reader_mode.add_argument("--record", help="File a sub-agent's JSON answer to the --prompt-only packet.")
    reader.add_argument("--json", action="store_true")

    figures = subparsers.add_parser(
        "figures",
        help="Figure sources in manuscript/figure-src/ -> vector PDFs in manuscript/figures/ "
             "(build, check, placement, sheet, new).",
    )
    figure_commands = figures.add_subparsers(dest="figures_command", required=True)

    def _figure_target(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("paper_id", nargs="?", help="Paper id (registry record or papers/<id>/manuscript).")
        sub.add_argument("--root", default=str(default_repo_root()))
        sub.add_argument("--manuscript", help="A manuscript directory instead of a paper id (no manifest).")
        sub.add_argument("--preview-dir", help="Where PNG previews go (default papers/<id>/build/figures).")
        sub.add_argument("--json", action="store_true")

    figures_build = figure_commands.add_parser(
        "build", help="Render every source (or --only NAME) to manuscript/figures/<stem>.pdf, write PNG "
                      "previews and refresh production/figure-artifacts.json.")
    _figure_target(figures_build)
    figures_build.add_argument("--only", action="append", help="Figure stem (repeatable).")
    figures_build.add_argument("--no-manifest", action="store_true",
                               help="Do not refresh production/figure-artifacts.json.")
    figures_check = figure_commands.add_parser(
        "check", help="Source and rebuild, vector, printed font size, text overlap/clipping, internal "
                      "words, caption and citation, figure-plan coverage, plot conventions and asset licences.")
    _figure_target(figures_check)
    figures_check.add_argument("--no-rebuild", action="store_true", help="Skip the rebuild comparison.")
    figures_check.add_argument("--text-width", help="Printed text width (e.g. 160mm) instead of probing.")
    figures_check.add_argument("--min-font", type=float, default=6.0)
    figures_check.add_argument("--out", help="Also write the JSON result to this file.")
    figures_placement = figure_commands.add_parser(
        "placement", help="Compiled main.pdf: each body figure must print within one page of its first mention.")
    _figure_target(figures_placement)
    figures_sheet = figure_commands.add_parser("sheet", help="One contact-sheet PNG of all figures.")
    _figure_target(figures_sheet)
    figures_sheet.add_argument("--out", help="PNG path (default <preview-dir>/contact-sheet.png).")
    figures_new = figure_commands.add_parser("new", help="Start figure-src/fig-NAME.* from a template.")
    figures_new.add_argument("paper_id", nargs="?")
    figures_new.add_argument("name", nargs="?")
    figures_new.add_argument("--root", default=str(default_repo_root()))
    figures_new.add_argument("--manuscript")
    figures_new.add_argument("--kind", choices=["tikz", "py", "svg", "html"])
    figures_new.add_argument("--template")
    figures_new.add_argument("--force", action="store_true")
    figures_new.add_argument("--list", action="store_true", help="List the templates and exit.")
    figures_new.add_argument("--json", action="store_true")
    figures_recolor = figure_commands.add_parser(
        "recolor", help="Map an SVG asset's colours onto the shared palette.")
    figures_recolor.add_argument("source")
    figures_recolor.add_argument("target")
    figures_recolor.add_argument("--map", action="append", default=[],
                                 help="Explicit mapping '#ff0000=vermilion' (repeatable).")
    figures_assets = figure_commands.add_parser(
        "assets", help="Search the licensed asset library (icons and objects for SVG/HTML schematics).")
    figures_assets.add_argument("query", nargs="*", help="Words matched against name, keywords and path.")
    figures_assets.add_argument("--field", help="energy, reliability, astronomy, biomedical or general.")
    figures_assets.add_argument("--library", help="tabler, material, phosphor, bioicons, reactome or openlabs.")
    figures_assets.add_argument("--no-credit", action="store_true", help="Only assets that need no credit line.")
    figures_assets.add_argument("--limit", type=int, default=40)
    figures_assets.add_argument("--json", action="store_true")

    formal_check = subparsers.add_parser("formal-check", help="Inspect or run mandatory reference/prerequisite verification without changing a paper gate.")
    formal_check.add_argument("--paper-id", required=True)
    formal_check.add_argument("--root", default=str(default_repo_root()))
    formal_check.add_argument("--inventory", action="store_true", help="Print deterministic coverage and primary-source plan; no network/model.")

    bundle = subparsers.add_parser("bundle", help="Validate one result bundle.")
    bundle.add_argument("path")
    bundle.add_argument("--json", action="store_true")

    paper = subparsers.add_parser("paper", help="Create a paper workspace or start a revision.")
    paper_commands = paper.add_subparsers(dest="paper_command", required=True)
    create = paper_commands.add_parser("create", help="Create a registered empty manuscript workspace.")
    create.add_argument(
        "--paper-id",
        help=(
            "Descriptive immutable ID: YYYYMMDD-domain-subdomain-keywords, "
            "for example 20260802-math-graph-opg1757-active-newton"
        ),
    )
    create.add_argument("--slug", help="Scientific keywords for the field-bound paper ID")
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

    unified = review_commands.add_parser(
        "unified-run",
        help="Run the unified editor-and-referee review (the only path to ready).",
    )
    unified.add_argument("--paper-id", required=True)
    unified.add_argument("--response", help="Decision-bound JSON response for a full review, formal-only recheck or presentation review.")
    unified.add_argument("--no-apply", action="store_true", help="Record the decision without updating the registry.")
    review_mode = unified.add_mutually_exclusive_group()
    review_mode.add_argument("--formal-only", action="store_true",
                             help="Recheck formal verification after a formal-check-only block.")
    review_mode.add_argument("--delta-only", action="store_true",
                         help="Only the post-ready delta review; report full_review_required instead of "
                              "starting the editor and referees.")
    review_mode.add_argument("--presentation", action="store_true",
                             help="Presentation-only revision (2026-11-23): deterministic science-invariance "
                                  "check against the last ready decision plus one independent light review; "
                                  "no scientific round. --response is the openlabs.presentation_revision.v1 "
                                  "request. Any scientific change reports full_review_required.")
    unified.add_argument("--root", default=str(default_repo_root()))
    replay = review_commands.add_parser("resynthesize", help="Replay a bound archived review offline.")
    for name in ("paper-id", "decision", "response", "actor", "reason"):
        replay.add_argument("--" + name, required=True)
    replay.add_argument("--no-apply", action="store_true", help="Record a replay without updating the registry.")
    replay.add_argument("--dry-run", action="store_true",
                        help="Only report what the replay would conclude; write nothing (actor/reason unused).")
    replay.add_argument("--root", default=str(default_repo_root()))
    rebut = review_commands.add_parser(
        "rebut",
        help="Adjudicate a factual rebuttal of one archived blocker (deterministic check first, "
             "then one independent model session); cite the record in a resynthesize reply.")
    for name in ("paper-id", "decision", "rebuttal", "actor", "reason"):
        rebut.add_argument("--" + name, required=True)
    rebut.add_argument("--adjudicator-role", help="Configured review role to adjudicate (default: chosen "
                                                  "for independence from the item's author and the writer).")
    rebut.add_argument("--check-resynthesis", metavar="RESPONSE",
                       help="After the adjudication, add it to this resynthesize reply, save the draft next "
                            "to the adjudication and dry-run the resynthesis (nothing is applied).")
    rebut.add_argument("--no-model", action="store_true",
                       help="Record 'undetermined' instead of starting a model when the checks cannot decide.")
    rebut.add_argument("--root", default=str(default_repo_root()))
    runtime_preflight = review_commands.add_parser(
        "runtime-preflight",
        help="Check that an independent referee runtime can open the registered materials, "
             "match their checksums and run the verifier (no review, no decision).",
    )
    runtime_preflight.add_argument("--paper-id", required=True)
    runtime_preflight.add_argument("--attachment", help="Frozen attachment ZIP with a SHA256SUMS member.")
    runtime_preflight.add_argument("--verifier", default="python verify_primary.py",
                                   help="Verifier command the runtime runs in the replication directory.")
    runtime_preflight.add_argument("--registered-sha256",
                                   help="Registered support_sources_sha256 (default: latest unified decision).")
    runtime_preflight.add_argument("--role", default=None,
                                   help="Review role whose model runs the preflight (default: first Codex referee).")
    runtime_preflight.add_argument("--out", help="Output directory (default: reviews/runtime-preflight/...).")
    runtime_preflight.add_argument("--root", default=str(default_repo_root()))
    round_usage = review_commands.add_parser(
        "round-usage",
        help="Rounds used per paper: at the target journal, its limit (round grants and their "
             "expiry), and the cross-journal total (reported only; read-only).",
    )
    round_usage.add_argument("--paper-id", action="append", default=[],
                             help="Paper to report (repeatable); default: every paper with a round grant.")
    round_usage.add_argument("--with-grants", action="store_true",
                             help="Also report every paper with a round grant.")
    round_usage.add_argument("--json", action="store_true", help="Accepted for the orchestrator; output is JSON.")
    round_usage.add_argument("--root", default=str(default_repo_root()))
    calibration = review_commands.add_parser(
        "calibration",
        help="Compare unified editor decisions with real journal outcomes (read-only).",
    )
    calibration.add_argument("--root", default=str(default_repo_root()))

    zenodo = subparsers.add_parser(
        "zenodo",
        help=(
            "Plan or perform a Zenodo deposit; production mutations require "
            "explicit confirmation."
        ),
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
            "Gate-check and irreversibly publish the prepared Zenodo draft after "
            "explicit human authorization."
        ),
    )
    _zenodo_release_arguments(release, include_sources=False)
    release.add_argument("--deposition-id")
    release.add_argument(
        "--confirm-paper-id",
        help="Required for release and must match --paper-id exactly.",
    )
    release.add_argument(
        "--confirm-production",
        action="store_true",
        help="Explicitly confirm the irreversible production release.",
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

    program = subparsers.add_parser(
        "program",
        help="Research-program steps called by the orchestrator (escalation, delivery, handler).",
    )
    program_commands = program.add_subparsers(dest="program_command", required=True)
    program_escalation = program_commands.add_parser(
        "register-escalation",
        help="Record an admission-gate escalation target as target_escalation: provisional.",
    )
    program_escalation.add_argument("--paper-id", required=True)
    program_escalation.add_argument("--venue", required=True)
    program_escalation.add_argument("--admission-task-id", required=True)
    program_escalation.add_argument("--admission-record", required=True)
    program_escalation.add_argument("--fallback-venue", required=True)
    program_escalation.add_argument(
        "--fallback-evidence", required=True,
        help="JSON/YAML eligibility evidence for the fallback venue (SCIE, 2025 CAS major-category "
             "zone, fee policy covering page/colour/submission charges, with sources).",
    )
    program_fallback = program_commands.add_parser(
        "check-fallback",
        help="Before falling back, complete and verify the registered fallback venue's eligibility.",
    )
    program_fallback.add_argument("--paper-id", required=True)
    program_fallback.add_argument("--fallback-evidence")
    program_confirm = program_commands.add_parser(
        "confirm-escalation",
        help="Approve a provisional escalation whose ready unified review meets the score bar.",
    )
    program_confirm.add_argument("--paper-id", required=True)
    program_deliver = program_commands.add_parser(
        "deliver",
        help="Hand a ready paper to the management site without a submission handler.",
    )
    program_deliver.add_argument("--paper-id", required=True)
    program_deliver.add_argument("--api-url", default=os.environ.get("ARA_PAPER_MANAGE_API_URL"))
    program_deliver.add_argument("--key-env", default="ARA_PAPER_MANAGE_API_KEY")
    program_supplement = program_commands.add_parser(
        "supplement-package",
        help="A delivered, not yet submitted version delivered with source.zip gets its submission "
             "package (投稿包) as a new package of the same version (user 2026-11-26). Needs "
             "`submission prepare` drafts for the version and no submission attempt on the site.",
    )
    program_supplement.add_argument("--paper-id", required=True)
    program_supplement.add_argument("--api-url", default=os.environ.get("ARA_PAPER_MANAGE_API_URL"))
    program_supplement.add_argument("--key-env", default="ARA_PAPER_MANAGE_API_KEY")
    program_assign = program_commands.add_parser(
        "assign-handler",
        help="After the owner's review, record the submission handler (default second author).",
    )
    program_assign.add_argument("--paper-id", required=True)
    program_assign.add_argument("--handler", default="second_author")
    program_site = program_commands.add_parser(
        "sync-site-assignments",
        help="Submitter assignments on the site follow readiness (2026-11-23): a paper that is "
             "not ready to submit holds none (placeholder: the admin service account), a ready "
             "one gets its recorded original submitter, else the second author. Dry run "
             "unless --apply.",
    )
    program_site.add_argument("--paper-id", action="append", default=[])
    program_site.add_argument("--apply", action="store_true")
    program_site.add_argument("--log", help="Append applied changes (JSON lines) to this file")
    program_site.add_argument("--api-url", default=os.environ.get("ARA_PAPER_MANAGE_API_URL"))
    program_site.add_argument("--key-env", default="ARA_PAPER_MANAGE_API_KEY")
    program_submission = program_commands.add_parser(
        "sync-submission-status",
        help="The registry follows the site's submission status (2026-11-26): external_submission "
             "from the latest attempt, stale portal_status / not_submitted corrected. Reads the "
             "site only (GET); writes the registry with --apply, else prints the plan.",
    )
    program_submission.add_argument("--paper-id", action="append", default=[])
    program_submission.add_argument("--apply", action="store_true")
    program_submission.add_argument("--snapshot", type=Path,
                                    help="A captured JSON list of site paper details instead of the API")
    program_correspondence = program_commands.add_parser(
        "journal-correspondence",
        help="Keep one journal letter matched by journal_mail in the paper's registry record "
             "(papers without a topic in the topic ledger; idempotent by message key).",
    )
    program_correspondence.add_argument("--paper-id", required=True)
    program_correspondence.add_argument("--message-key", required=True)
    program_correspondence.add_argument("--status", required=True,
                                        choices=("revision_requested", "submitted", "accepted", "rejected", "proofs"))
    program_correspondence.add_argument("--manuscript-id", default="")
    program_correspondence.add_argument("--due")
    program_correspondence.add_argument("--round", type=int)
    program_correspondence.add_argument("--letter-file", type=Path,
                                        help="A rejection's verbatim letter (journal-mail dispatcher)")
    program_status = program_commands.add_parser(
        "release-status",
        help="Read-only: what is left between review ready and delivery (release pipeline).",
    )
    program_status.add_argument("--paper-id", required=True)
    program_metadata = program_commands.add_parser(
        "prepare-publication-metadata", help="Project the verified draft DOI into a ready release.")
    program_metadata.add_argument("--paper-id", required=True)
    program_adopt = program_commands.add_parser(
        "adopt",
        help="Copy a campaign-workspace paper into the data repository (never overwrites).",
    )
    program_adopt.add_argument("--paper-id", required=True)
    program_adopt.add_argument("--previous-package", help="Promote a reviewed successor of this delivery")
    program_adopt.add_argument("--source", required=True, help="Campaign workspace root.")
    program_adopt.add_argument(
        "--artifact-manifest", action="append", default=[],
        help="Archived result-bundle manifest.json of the review task (repeatable); hash-bound "
             "files missing from the workspace (PDF, formal-check evidence) are restored from it.",
    )
    program_waive = program_commands.add_parser(
        "waive-support",
        help="Record support.publication.mode not_required (no public deposit) with its reason.",
    )
    program_waive.add_argument("--paper-id", required=True)
    program_waive.add_argument("--reason", required=True)
    program_waive.add_argument("--decided-by", required=True)
    program_unwaive = program_commands.add_parser(
        "unwaive-support",
        help="Undo a not_required support waiver (back to the configured public deposit mode).",
    )
    program_unwaive.add_argument("--paper-id", required=True)
    program_unwaive.add_argument("--reason", required=True)
    program_unwaive.add_argument("--by", required=True)
    program_unwaive.add_argument("--mode", help="Default: settings support_publication.default_mode")
    program_bind = program_commands.add_parser(
        "bind-release-artifacts",
        help="Freeze the ignored release PDF/.bbl through papers/<id>/production/"
             "release-artifacts.json (content-addressed copies; commit before delivery).",
    )
    program_bind.add_argument("--paper-id", required=True)
    program_bind_payloads = program_commands.add_parser(
        "bind-oversize-payloads",
        help="Keep the paper's files over the Git payload limit (5 MiB) out of Git: copy them "
             "to the content-addressed artifact store, record path/size/SHA-256/URI in "
             "papers/<id>/production/payload-artifacts.json and ignore the local copies.",
    )
    program_bind_payloads.add_argument("--paper-id", required=True)
    program_declarations = program_commands.add_parser("apply-default-declarations")
    program_declarations.add_argument("--paper-id", required=True)
    program_declarations.add_argument("--contributions-only", action="store_true")
    program_relocate = program_commands.add_parser(
        "relocate-support-sources",
        help="Point support.publication.source_files at the papers/<id>/support-materials/ "
             "copies program adopt made (reviewed names kept in adopted_sources).",
    )
    program_relocate.add_argument("--paper-id", required=True)
    program_revision_evidence = program_commands.add_parser(
        "register-revision-evidence",
        help="Register response recomputations under papers/<id>/revisions/ as revision evidence "
             "(support.publication.revision_evidence, outside support_sources_sha256); moves "
             "entries mistakenly listed in support.publication.source_files. Registry only.",
    )
    program_revision_evidence.add_argument("--paper-id", required=True)
    program_revision_evidence.add_argument("--path", action="append", required=True,
                                           help="Repository-relative file; repeat for several.")
    program_revision_evidence.add_argument("--actor", required=True)
    program_revision_evidence.add_argument("--reason", required=True)
    program_revision_evidence.add_argument("--decision",
                                           help="Basis decision (default: latest full unified decision).")
    for command in (program_escalation, program_fallback, program_confirm, program_deliver, program_supplement,
                    program_site, program_submission, program_correspondence,
                    program_assign, program_status, program_metadata, program_adopt, program_waive, program_bind,
                    program_unwaive, program_bind_payloads, program_relocate, program_declarations,
                    program_revision_evidence):
        command.add_argument("--root", default=str(default_repo_root()))
        command.add_argument("--json", action="store_true", help="Print one JSON object.")
    return parser


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(default_repo_root()))
    # None: <--root>/registry/settings.yaml, resolved after parsing. A default fixed at
    # parser build time followed OPENLABS_WORKSPACE instead of --root, so `zenodo prepare
    # --root <data>` read <workspace>/data/registry/settings.yaml (2026-11-20, PMB-13B).
    parser.add_argument("--config", default=None,
                        help="Registry settings (default: <--root>/registry/settings.yaml)")


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
    argv = list(sys.argv[1:] if argv is None else argv)
    # The submission package (投稿包) and the single-file LaTeX flattener have their own parsers.
    if argv[:1] == ["submission"]:
        from paper_writing.submission_bundle import main as submission_main

        return submission_main(argv[1:])
    if argv[:1] == ["flatten"]:
        from paper_writing.flatten_tex import main as flatten_main

        return flatten_main(argv[1:])
    args = build_parser().parse_args(argv)
    if hasattr(args, "config") and args.config is None:
        args.config = str(Path(args.root) / "registry" / "settings.yaml")
    if args.command == "journal-history":
        from paper_writing import journal_history
        root = Path(args.root).resolve()
        try:
            if args.history_command == "sync":
                if args.snapshot:
                    path = Path(args.snapshot).resolve()
                    result = journal_history.refresh_history(root, json.loads(path.read_text()), source="management_site_snapshot_import")
                else:
                    result = journal_history.sync_from_site(root)
                print(json.dumps({k: v for k, v in result.items() if k != "journals"}, ensure_ascii=False, indent=2))
                return 0
            if args.history_command == "check":
                result = journal_history.check_journal(root, args.journal)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["eligible"] else 1
            config = journal_history._policy(root)
            path = journal_history._path(root, config)
            journal_history.load_history(path)
            print(path.with_suffix(".md").read_text())
            return 0
        except (OSError, ValueError, KeyError) as exc:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
            return 2
    if args.command == "venue":
        from paper_writing import venue_registry

        try:
            if args.venue_command == "lookup":
                result = venue_registry.lookup(args.root, journal=args.journal, issn=args.issn)
                code = 0 if result["eligible"] else (1 if result["found"] else 3)
            elif args.venue_command == "alternatives":
                result = venue_registry.alternatives(args.root, zones=args.zone,
                                                     category=args.category,
                                                     exclude=args.exclude)
                code = 0
            else:
                result = venue_registry.mark_pending(
                    args.root, journal=args.journal, issn=args.issn, url=args.url,
                    http_status=args.http_status, reason=args.reason, by=args.by)
                code = 0
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    if args.command == "cadence":
        from paper_writing.submission_cadence import check_cadence
        try:
            result = check_cadence(Path(args.root).resolve(), venue=args.venue, paper_id=args.paper_id)
        except (OSError, ValueError, KeyError) as exc:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ok" else 1
    if args.command == "submissions":
        from paper_writing import submission_monitor
        try:
            if args.snapshot:
                papers = submission_monitor.load_snapshot(Path(args.snapshot).resolve())
            else:
                from paper_writing.journal_history import fetch_site_papers
                papers = fetch_site_papers()
            report = submission_monitor.build_report(papers)
        except (OSError, ValueError, KeyError) as exc:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else submission_monitor.format_report(report))
        return 0
    if args.command == "rewrite":
        from paper_writing import editorial_rewrite
        root = Path(args.root).resolve()
        try:
            if args.rewrite_command == "run":
                record = editorial_rewrite.run_rewrite(args.paper_id, root=root, rewriters=args.rewriter)
                summary = {k: record.get(k) for k in ("run_dir", "outcome", "rewriter_failures", "deterministic_problems")}
                summary["selected"] = (record.get("selection") or {}).get("selected", "original")
                summary["rejected_candidates"] = (record.get("selection") or {}).get("rejected_candidates")
                if args.apply and record["outcome"] == "candidate_selected":
                    summary["applied"] = editorial_rewrite.apply_rewrite(args.paper_id, root=root, run_dir=record["run_dir"])
            else:
                summary = editorial_rewrite.apply_rewrite(args.paper_id, root=root, run_dir=args.run_dir)
        except (OSError, ValueError, KeyError) as exc:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
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
    if args.command == "formal-check":
        from datetime import UTC, datetime
        from paper_writing import formal_checks
        from paper_writing.registry import load_paper_metadata
        from paper_writing.review_flow import formal_role, review_config
        from paper_writing.review_launcher import run_role
        root = Path(args.root).resolve()
        metadata = load_paper_metadata(args.paper_id, root)
        documents, bibliography = formal_checks.current_inputs(metadata, root)
        if args.inventory:
            print(json.dumps({"inventory": formal_checks.inventory(documents, bibliography),
                              "source_plan": formal_checks.source_plan(metadata)}, ensure_ascii=False, indent=2))
            return 0
        config = review_config(root)
        role = formal_role(config["roles"])
        from paper_writing.review_launcher import FORMAL_PROVIDERS
        if not role or role.get("provider") not in FORMAL_PROVIDERS:
            raise ValueError("Formal verification requires an independent Codex or Antigravity process")
        run = root / "reviews/formal-check" / args.paper_id / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        run.mkdir(parents=True, exist_ok=False)
        result = formal_checks.run_checks({"metadata": metadata}, root, run, role, config["timeout_seconds"], run_role)
        if result["valid"]:
            errors = formal_checks.validate_binding(result, metadata, root, role)
            result = dict(result, valid=not errors, blockers=errors)
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
            for issue in result.get("narrative_warnings", []):
                location = f"{issue.get('path', '')}:{issue.get('line')}" if issue.get("path") else ""
                print(f"WARNING {issue['code']}: {location}: {issue['message']}")
            metrics = (result.get("narrative") or {}).get("metrics") or {}
            limits = (result.get("narrative") or {}).get("limits") or {}
            if metrics:
                print(f"Main text: {metrics.get('body_words')} words (limit {limits.get('max_body_words')}); "
                      "full report: paper-writing narrative-check --paper-id " + args.paper_id)
        return 0 if result["valid"] else 1
    if args.command == "narrative-check":
        from paper_writing import narrative_check

        if args.paper_id:
            result = narrative_check.check_paper(args.paper_id, root=args.root, line_id=args.line)
        else:
            tex = Path(args.tex).resolve()
            line = narrative_check._research_line(Path(args.root), args.line) if args.line else None
            limits, sources = narrative_check.resolve_limits({}, line=line)
            result = {"main_tex": str(tex), "limit_sources": sources,
                      **narrative_check.analyze(narrative_check.flatten_tex(tex, tex.parent), limits)}
        report = narrative_check.render_report(result)
        if args.out:
            Path(args.out).write_text(report, encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else report, end="" if not args.json else "\n")
        return 0 if result["valid"] else 1
    if args.command == "delivery-floor":
        from paper_writing.delivery_floor import audit

        result = audit(args.paper_id, args.root, author=args.author)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(bool(result["issues"]))
    if args.command == "story-review":
        from paper_writing.reader_check import review_story
        print(json.dumps(review_story(args.paper_id, Path(args.root)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "reader-check":
        from paper_writing import reader_check

        role = ({"provider": args.provider, "tool": args.tool, "model": args.model}
                if args.model else None)
        result = reader_check.run(args.paper_id, root=args.root, role=role, prompt_only=args.prompt_only,
                                  record=args.record, timeout=args.timeout)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif "answer" in result:
            print(reader_check.render(result), end="")
            print("Saved: " + ", ".join(result["paths"]))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "figures":
        return _figures_command(args)
    if args.command == "bundle":
        result = validate_result_bundle(args.path).to_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _bundle_summary(result))
        return 0 if result["valid"] else 1
    if args.command == "paper" and args.paper_command == "create":
        path = create_paper(
            root=args.root,
            paper_id=args.paper_id,
            slug=args.slug,
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
        from paper_writing.registry import PaperFrozenError

        try:
            result = start_revision(args.paper_id, args.reason, root=args.root)
        except PaperFrozenError as exc:
            print(json.dumps({"valid": False, "frozen": True, "error": str(exc)}, ensure_ascii=False))
            return 2
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
    if args.command == "review" and args.review_command == "resynthesize":
        from paper_writing import resynthesis
        from paper_writing.registry import PaperFrozenError

        if args.dry_run:
            try:
                result = resynthesis.preview(args.paper_id, root=args.root, decision=args.decision,
                                             response=args.response)
            except (ValueError, OSError) as exc:
                print(json.dumps({"error": str(exc)}, ensure_ascii=False))
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["outcome"] == "ready" else 2
        try:
            result = resynthesis.run(args.paper_id, root=args.root, decision=args.decision,
                                     response=args.response, actor=args.actor, reason=args.reason,
                                     apply=not args.no_apply)
        except (ValueError, OSError, PaperFrozenError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps({
            "run_dir": result.get("run_dir"),
            "decision_sha256": result.get("decision_sha256"),
            "round_for_target": result.get("round_for_target"),
            "outcome": result["merged"]["outcome"],
            "full_review_reasons": result["merged"].get("full_review_reasons", []),
        }, ensure_ascii=False, indent=2))
        return 0 if result["merged"]["outcome"] == "ready" else 2
    if args.command == "review" and args.review_command == "rebut":
        from paper_writing import rebuttal
        from paper_writing.review_launcher import LaunchError

        try:
            result = rebuttal.run(args.paper_id, root=args.root, decision=args.decision,
                                  rebuttal=args.rebuttal, actor=args.actor, reason=args.reason,
                                  adjudicator_role=args.adjudicator_role, allow_model=not args.no_model)
        except (ValueError, OSError, KeyError, LaunchError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            return 2
        if "run_dir" not in result:  # another review holds the paper lock
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        summary = {key: result.get(key) for key in (
            "run_dir", "adjudication_sha256", "verdict", "decided_by", "reason_for_verdict", "adjudicator")}
        summary["adjudication"] = f"{result['run_dir']}/adjudication.json"
        if args.check_resynthesis and result["verdict"] == "sustained":
            from paper_writing import resynthesis

            try:
                draft = json.loads(Path(args.check_resynthesis).read_text())
                cited = list(draft.get("rebuttals") or [])
                if not any(isinstance(r, dict) and r.get("adjudication") == summary["adjudication"] for r in cited):
                    cited.append({"adjudication": summary["adjudication"], "sha256": result["adjudication_sha256"]})
                draft["rebuttals"] = cited
                draft_path = Path(args.root) / result["run_dir"] / "resynthesis-response.draft.json"
                draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2))
                summary["resynthesis_draft"] = draft_path.relative_to(Path(args.root)).as_posix()
                summary["resynthesis_dry_run"] = resynthesis.preview(
                    args.paper_id, root=args.root, decision=args.decision, response=draft)
            except (ValueError, OSError) as exc:
                summary["resynthesis_dry_run"] = {"error": str(exc)}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if result["verdict"] == "sustained" else 2
    if args.command == "review" and args.review_command == "unified-run":
        from paper_writing.registry import PaperFrozenError
        from paper_writing.review_flow import run_review

        try:
            result = run_review(args.paper_id, root=args.root, response_letter=args.response,
                                apply=not args.no_apply, delta_only=args.delta_only, formal_only=args.formal_only,
                                presentation=args.presentation)
        except PaperFrozenError as exc:
            print(json.dumps({"valid": False, "frozen": True, "error": str(exc)}, ensure_ascii=False))
            return 2
        summary = {key: result.get(key) for key in ("paper_id", "run_dir", "target_journal", "stage_reached",
                                                    "round_for_target", "decision_sha256")}
        summary["outcome"] = result["merged"]["outcome"]
        summary["next_action"] = result["merged"].get("next_action")
        if result.get("review_outcome"):
            summary["review_outcome"] = result["review_outcome"]
        if result["merged"].get("round_guard"):
            summary["round_guard"] = result["merged"]["round_guard"]
        summary["editor_decision"] = (result.get("editor_screen") or {}).get("decision")
        summary["recommendation"] = result["merged"].get("recommendation")
        summary["review_mode"] = result.get("review_mode", "full")
        summary["stalled"] = bool(result["merged"].get("stalled"))
        if result["merged"].get("full_review_reasons"):
            summary["full_review_reasons"] = result["merged"]["full_review_reasons"]
        if result.get("writer_model_note"):
            summary["writer_model_note"] = result["writer_model_note"]
        if result["merged"].get("direction_context"):
            summary["direction_context"] = result["merged"]["direction_context"]
        # Formal findings deferred to delivery; details are in the decision record.
        summary["preparation_advisories"] = len(result.get("preparation_advisories") or [])
        access = (result.get("formal_check") or {}).get("unverifiable_source_access")
        if access:
            summary["unverifiable_source_access"] = sorted((access.get("references") or {}))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.command == "review" and args.review_command == "runtime-preflight":
        from datetime import UTC, datetime
        from paper_writing.review_flow import review_config
        from paper_writing.review_preflight import run_preflight
        root = Path(args.root).resolve()
        config = review_config(root)
        names = [args.role] if args.role else [*config["referee_roles"], "referee_a", "referee_b"]
        role = next((config["roles"][n] for n in names
                     if (config["roles"].get(n) or {}).get("provider") == "openai-codex"), None)
        if role is None:
            raise ValueError("runtime-preflight needs a Codex review role")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out = Path(args.out) if args.out else root / "reviews/runtime-preflight" / args.paper_id / stamp
        record = run_preflight(args.paper_id, root, out, role=role,
                               attachment=Path(args.attachment) if args.attachment else None,
                               verifier=args.verifier, registered_sha256=args.registered_sha256,
                               timeout=int(config["timeout_seconds"]))
        print(json.dumps({k: v for k, v in record.items() if k not in {"receipt", "report"}} | {"out": str(out)},
                         ensure_ascii=False, indent=2))
        return 0 if record["ok"] else 1
    if args.command == "review" and args.review_command == "round-usage":
        from paper_writing.review_flow import round_usage_report

        print(json.dumps(round_usage_report(args.root, args.paper_id, with_grants=args.with_grants),
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == "review" and args.review_command == "calibration":
        from paper_writing.review_flow import calibration as review_calibration

        print(json.dumps(review_calibration(args.root), ensure_ascii=False, indent=2))
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
    if args.command == "program":
        return _run_program(args)
    return 2


def _run_program(args: argparse.Namespace) -> int:
    from paper_writing import program_delivery
    from paper_writing.handoff import HandoffError, ManageApiClient
    from paper_writing.program_adopt import AdoptError

    try:
        if args.program_command == "register-escalation":
            result = program_delivery.register_provisional_escalation(
                args.paper_id, root=args.root, venue=args.venue,
                admission_task_id=args.admission_task_id,
                admission_record=args.admission_record, fallback_venue=args.fallback_venue,
                fallback_evidence=args.fallback_evidence,
            )
        elif args.program_command == "check-fallback":
            result = program_delivery.check_fallback(
                args.paper_id, root=args.root, fallback_evidence=args.fallback_evidence,
            )
        elif args.program_command == "release-status":
            from paper_writing.release_pipeline import release_status

            result = release_status(args.paper_id, root=args.root)
        elif args.program_command == "prepare-publication-metadata":
            from paper_writing.publication_metadata import prepare

            result = prepare(args.paper_id, root=args.root)
        elif args.program_command == "adopt":
            from paper_writing.program_adopt import adopt

            if args.previous_package:
                from paper_writing.program_adopt import adopt_revision
                result = adopt_revision(args.paper_id, root=args.root, source=args.source,
                                        previous_package=args.previous_package,
                                        artifact_manifests=args.artifact_manifest)
            else:
                result = adopt(args.paper_id, root=args.root, source=args.source,
                               artifact_manifests=args.artifact_manifest)
        elif args.program_command == "bind-release-artifacts":
            from paper_writing.program_adopt import bind_release_artifacts

            result = bind_release_artifacts(args.paper_id, root=args.root)
        elif args.program_command == "apply-default-declarations":
            from paper_writing.declarations import apply_default_declarations

            result = apply_default_declarations(args.paper_id, Path(args.root), contributions_only=args.contributions_only)
        elif args.program_command == "relocate-support-sources":
            from paper_writing.program_adopt import relocate_support_sources

            result = relocate_support_sources(args.paper_id, root=args.root)
        elif args.program_command == "register-revision-evidence":
            from paper_writing import revision_evidence

            result = revision_evidence.register(args.paper_id, root=args.root, paths=args.path,
                                                actor=args.actor, reason=args.reason,
                                                decision=args.decision)
        elif args.program_command == "bind-oversize-payloads":
            from paper_writing.program_adopt import bind_oversize_payloads

            result = bind_oversize_payloads(args.paper_id, root=args.root)
        elif args.program_command == "unwaive-support":
            from paper_writing.program_adopt import unwaive_support

            result = unwaive_support(args.paper_id, root=args.root, reason=args.reason,
                                     by=args.by, mode=args.mode)
        elif args.program_command == "waive-support":
            from paper_writing.program_adopt import waive_support

            result = waive_support(args.paper_id, root=args.root, reason=args.reason,
                                   decided_by=args.decided_by)
        elif args.program_command == "confirm-escalation":
            result = program_delivery.confirm_escalation(args.paper_id, root=args.root)
        elif args.program_command == "sync-site-assignments":
            from paper_writing.site_assignments import sync_site_assignments

            if args.apply and os.environ.get("OPENLABS_ENABLE_EXTERNAL_WRITES") != "1":
                raise HandoffError(
                    "Site assignment changes are disabled. Set OPENLABS_ENABLE_EXTERNAL_WRITES=1 "
                    "for this one operation (or omit --apply for the plan)."
                )
            if not args.api_url:
                raise HandoffError("Missing --api-url or ARA_PAPER_MANAGE_API_URL")
            with ManageApiClient.from_environment(
                args.api_url, key_environment=args.key_env
            ) as client:
                result = sync_site_assignments(client, root=args.root, paper_ids=args.paper_id,
                                               apply=args.apply, log_path=args.log)
        elif args.program_command == "sync-submission-status":
            from paper_writing import submission_status
            from paper_writing.journal_history import fetch_site_papers

            papers = (json.loads(args.snapshot.read_text(encoding="utf-8")) if args.snapshot
                      else fetch_site_papers())
            result = submission_status.reconcile(args.root, papers, paper_ids=args.paper_id,
                                                 apply=args.apply)
        elif args.program_command == "journal-correspondence":
            from paper_writing import submission_status

            result = submission_status.record_correspondence(
                args.root, args.paper_id, message_key=args.message_key, status=args.status,
                manuscript_id=args.manuscript_id, due=args.due, round_no=args.round,
                letter_file=args.letter_file)
        elif args.program_command == "deliver":
            # Same explicit switch as `handoff release`; the orchestrator sets it for
            # this one call only when [program] auto_handoff is enabled.
            if os.environ.get("OPENLABS_ENABLE_EXTERNAL_WRITES") != "1":
                raise HandoffError(
                    "Remote handoff is disabled. Set OPENLABS_ENABLE_EXTERNAL_WRITES=1 "
                    "for this one operation."
                )
            if not args.api_url:
                raise HandoffError("Missing --api-url or ARA_PAPER_MANAGE_API_URL")
            with ManageApiClient.from_environment(
                args.api_url, key_environment=args.key_env
            ) as client:
                result = program_delivery.deliver(args.paper_id, root=args.root, client=client)
        elif args.program_command == "supplement-package":
            if os.environ.get("OPENLABS_ENABLE_EXTERNAL_WRITES") != "1":
                raise HandoffError(
                    "Remote handoff is disabled. Set OPENLABS_ENABLE_EXTERNAL_WRITES=1 "
                    "for this one operation."
                )
            if not args.api_url:
                raise HandoffError("Missing --api-url or ARA_PAPER_MANAGE_API_URL")
            with ManageApiClient.from_environment(
                args.api_url, key_environment=args.key_env
            ) as client:
                result = program_delivery.supplement_submission_package(
                    args.paper_id, root=args.root, client=client)
        else:
            result = program_delivery.assign_handler(
                args.paper_id, root=args.root, handler=args.handler
            )
    except (HandoffError, program_delivery.ProgramDeliveryError, OSError, ValueError, RuntimeError,
            KeyError, AdoptError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=None if args.json else 2))
    return 0


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
        if args.zenodo_command in {
            "create-draft",
            "new-version",
            "prepare",
            "release",
            "publish",
        }:
            from paper_writing.registry import freeze_block_reason, load_paper_metadata

            frozen = freeze_block_reason(load_paper_metadata(args.paper_id, args.root), args.paper_id)
            if frozen:
                raise ZenodoError(frozen)
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
        if (
            environment == "production"
            and args.zenodo_command != "verify-draft"
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
            if args.confirm_paper_id != args.paper_id:
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




def _figures_command(args: argparse.Namespace) -> int:
    from paper_writing import figures as fig

    try:
        if args.figures_command == "recolor":
            mapping = dict(item.split("=", 1) for item in args.map)
            print(fig.recolor_file(Path(args.source), Path(args.target), mapping))
            return 0
        if args.figures_command == "assets":
            found = fig.search_assets(args.query, field=args.field, library=args.library,
                                      no_credit=args.no_credit)
            if args.json:
                print(json.dumps(found[:args.limit], ensure_ascii=False, indent=2))
                return 0
            for item in found[:args.limit]:
                credit = "credit: " + item["attribution"] if item.get("credit_required") else "no credit needed"
                print(f"asset:{item['path']:<52} {item['license']:<11} {credit}")
            print(f"{len(found)} match(es) in {fig.asset_library()}; use <img class=\"ol-icon\" src=\"asset:PATH\"> "
                  "in an HTML figure or <image href=\"asset:PATH\"> in an SVG one")
            return 0
        if args.figures_command == "new" and args.list:
            for entry in fig.template_catalog():
                print(f"{entry['name']:<28} {Path(entry['file']).suffix:<6} {entry['use_when']}")
            return 0
        paper_id = args.paper_id
        if args.figures_command == "new" and args.manuscript and args.name is None:
            paper_id, args.name = None, args.paper_id  # `new --manuscript DIR NAME`
        ws = fig.workspace(None if args.manuscript else paper_id, root=args.root, manuscript=args.manuscript,
                           preview_dir=getattr(args, "preview_dir", None))
        if args.figures_command == "build":
            result = fig.build(ws, only=args.only, manifest=not args.no_manifest)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                for item in result["built"]:
                    print(f"built {item['figure']}: {item['width_mm']} x {item['height_mm']} mm -> {item['pdf']}")
                    print(f"      preview {item['preview']}" + "".join(f"; {n}" for n in item["notes"]))
                for item in result["failed"]:
                    print(f"FAILED {item['figure']}: {item['error']}")
                if result.get("manifest"):
                    print(f"manifest {result['manifest']}")
                print("Look at each preview PNG, then run: paper-writing figures check")
            return 0 if not result["failed"] else 1
        if args.figures_command == "check":
            result = fig.check(ws, rebuild=not args.no_rebuild, text_width=args.text_width,
                               min_font_pt=args.min_font)
            if args.out:
                Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else fig.render_check(result),
                  end="" if not args.json else "\n")
            return 0 if result["valid"] else 1
        if args.figures_command == "placement":
            from paper_writing.float_placement import check as placement_check
            result = placement_check(ws.manuscript, pdf=fig.proof_pdf(ws))
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"Float placement: {result['status']} ({result['pdf']})")
                for item in result["figures"]:
                    print(f"- Figure {item['number']}: page {item.get('figure_page')}, first mention page "
                          f"{item.get('first_reference_page')}")
                for item in result["errors"]:
                    print(f"  BLOCK {item['code']} [{item['figure']}]: {item['message']}")
                for note in result["notes"]:
                    print(f"  NOTE {note}")
            return 1 if result["errors"] else 0
        if args.figures_command == "sheet":
            print(fig.contact_sheet(ws, Path(args.out) if args.out else None))
            return 0
        if args.figures_command == "new":
            if not args.name:
                raise fig.FigureToolError("Give the figure NAME (and --template or --kind)")
            result = fig.new_figure(ws, args.name, template=args.template, kind=args.kind, force=args.force)
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
                  f"created {result['source']}\n        {result['sidecar']} (fill in purpose and key_point)")
            return 0
    except fig.FigureToolError as exc:
        print(f"ERROR: {exc}")
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
