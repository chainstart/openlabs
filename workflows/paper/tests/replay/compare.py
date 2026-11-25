"""Compare two replay outputs (``run_replay.py``) item by item.

    python tests/replay/compare.py before.json after.json > changes.json
"""
from __future__ import annotations

import json
import sys


def compare(before: dict, after: dict) -> list[dict]:
    rows = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key, {}), after.get(key, {})
        if "error" in old or "error" in new:
            rows.append({"decision": key, "change": "error", "before": old.get("error"), "after": new.get("error")})
            continue
        if old.get("outcome") != new.get("outcome"):
            rows.append({"decision": key, "change": "outcome", "before": old.get("outcome"),
                         "after": new.get("outcome")})
        if old.get("next_action") != new.get("next_action"):
            rows.append({"decision": key, "change": "next_action", "before": old.get("next_action"),
                         "after": new.get("next_action")})
        items_old, items_new = old.get("items", {}), new.get("items", {})
        for item in sorted(set(items_old) | set(items_new)):
            a, b = items_old.get(item), items_new.get(item)
            if a != b:
                rows.append({"decision": key, "change": "item", "item": item, "before": a, "after": b,
                             "reason_before": old.get("reasons", {}).get(item),
                             "reason_after": new.get("reasons", {}).get(item)})
    return rows


def main() -> int:
    before, after = (json.load(open(path)) for path in sys.argv[1:3])
    json.dump(compare(before, after), sys.stdout, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
