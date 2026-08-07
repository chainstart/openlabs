#!/usr/bin/env python3
"""CLI for the standalone AMRA research loop package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from loop_core import (
    CampaignError,
    add_mechanism,
    advance_campaign,
    freeze_campaign,
    init_campaign,
    load_campaign,
    set_mechanism_status,
    validate_campaign,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Mechanism-first mathematics campaign state machine")
    commands = result.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="initialize a campaign")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--campaign-id", required=True)
    init.add_argument("--problem-id", required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--statement", required=True)
    init.add_argument("--source", required=True)

    for name in ("status", "validate"):
        command = commands.add_parser(name)
        command.add_argument("--campaign", type=Path, required=True)

    advance = commands.add_parser("advance", help="advance through one validated phase")
    advance.add_argument("--campaign", type=Path, required=True)
    advance.add_argument("--to", required=True)

    add = commands.add_parser("add-mechanism", help="append one structured mechanism")
    add.add_argument("--campaign", type=Path, required=True)
    add.add_argument("--id", required=True)
    add.add_argument("--representation-id", required=True)
    add.add_argument("--family", required=True)
    add.add_argument("--claim", required=True)
    add.add_argument("--would-close", action="append", required=True)
    add.add_argument("--kill-test", required=True)

    mark = commands.add_parser("set-mechanism-status")
    mark.add_argument("--campaign", type=Path, required=True)
    mark.add_argument("--id", required=True)
    mark.add_argument("--status", required=True)
    mark.add_argument("--evidence", required=True)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--campaign", type=Path, required=True)
    freeze.add_argument("--reason", required=True)
    freeze.add_argument("--evidence", action="append", default=[])
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            path = init_campaign(
                args.root,
                campaign_id=args.campaign_id,
                problem_id=args.problem_id,
                title=args.title,
                exact_statement=args.statement,
                source=args.source,
            )
            print(path)
        elif args.command == "status":
            state, _ = load_campaign(args.campaign)
            print(json.dumps(state, indent=2, ensure_ascii=False))
        elif args.command == "validate":
            errors = validate_campaign(args.campaign)
            print(json.dumps({"valid": not errors, "errors": errors}, indent=2, ensure_ascii=False))
            return 1 if errors else 0
        elif args.command == "advance":
            print(json.dumps(advance_campaign(args.campaign, args.to), indent=2, ensure_ascii=False))
        elif args.command == "add-mechanism":
            add_mechanism(args.campaign, {
                "id": args.id,
                "representation_id": args.representation_id,
                "family": args.family,
                "decisive_claim": args.claim,
                "would_close": args.would_close,
                "kill_test": args.kill_test,
            })
        elif args.command == "set-mechanism-status":
            set_mechanism_status(args.campaign, args.id, args.status, args.evidence)
        elif args.command == "freeze":
            print(json.dumps(freeze_campaign(args.campaign, args.reason, args.evidence), indent=2, ensure_ascii=False))
    except CampaignError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
