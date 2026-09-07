#!/usr/bin/env python3
"""Launch through bin/openlabs-resource-guard; does not apply or publish results."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from paper_writing.review_delta_runner import run_delta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="high")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    print(json.dumps(run_delta(args.paper_id, root=args.root, model=args.model,
        effort=args.effort, timeout=args.timeout), indent=2))


if __name__ == "__main__":
    main()
