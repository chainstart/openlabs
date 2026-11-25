"""Build the replay fixture ``decisions.json.gz`` from the archived unified decisions.

Usage (read-only on the data repository):

    python tests/replay/build_fixture.py /workspace/openlabs/openlabs-data [--limit 100]

Selection: every archived ``materiality_v1`` decision that reached synthesis with role reports
for the papers named in the 2026-11-23 convergence audit; then the most recent decisions of
other papers (at most ``--others``); then the most recent earlier-standard decisions of the
audited papers until the limit. TIC 260161938 is excluded (another agent owned its files on
2026-11-25).
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_lib import FIXTURE, snapshot  # noqa: E402

AUDITED = ("20261109-biology-exposure-pfas-mixture-distribution",
           "20261113-biology-genetics-campylobacter-source-forward-validation",
           "20261114-physics-binaries-tic421871796",
           "20261119-quant-energy-nem-settlement-storage",
           "20261120-quant-power-nem-solar-battery",
           "20261121-physics-photometry-tic236779149")
EXCLUDED = ("20261119-physics-photometry-tic260161938",)


def candidates(root: Path):
    for path in sorted((root / "reviews" / "unified").glob("*/*/decision.json")):
        paper = path.parent.parent.name
        if paper in EXCLUDED:
            continue
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if record.get("stage_reached") != "decision" or not record.get("referee_reports") \
                or not record.get("editor_screen"):
            continue
        yield paper, path.parent.name, record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--others", type=int, default=20)
    parser.add_argument("--output", type=Path, default=FIXTURE)
    args = parser.parse_args()
    from paper_writing import review_flow as flow

    rows = list(candidates(args.root))

    def standard(row):
        return (row[2].get("editor_screen") or {}).get("review_standard") == "materiality_v1"

    audited = [row for row in rows if row[0] in AUDITED and standard(row)]
    others = sorted((row for row in rows if row[0] not in AUDITED), key=lambda row: row[1], reverse=True)
    others = others[:min(args.others, max(0, args.limit - len(audited)))]
    earlier = sorted((row for row in rows if row[0] in AUDITED and not standard(row)), key=lambda row: row[1],
                     reverse=True)
    chosen = audited + others + earlier[:max(0, args.limit - len(audited) - len(others))]
    snaps = []
    for paper, run, record in chosen:
        formal = record.get("formal_check") or {}
        kinds = flow.formal_report_kinds(formal, args.root) if formal.get("path") else {}
        snaps.append(snapshot(record, args.root, kinds))
    snaps.sort(key=lambda s: (s["paper_id"] or "", s["run_id"] or ""))
    with gzip.open(args.output, "wt", encoding="utf-8") as handle:
        json.dump(snaps, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"{len(snaps)} decisions ({len(audited)} audited materiality_v1, {len(others)} other papers) -> {args.output} "
          f"({args.output.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
