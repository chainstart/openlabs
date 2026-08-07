"""Execute a versioned, resumable matrix of molecular-dynamics runs."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .mlipmd import MDConfig, run_series
from .provenance import atomic_write_json, sha256_file

RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
TUPLE_FIELDS = {"temperatures", "supercell"}


@dataclass(frozen=True)
class CampaignRun:
    run_id: str
    stage: str
    purpose: str
    enabled: bool
    run_dir: Path
    config: MDConfig


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    protocol_path: Path
    protocol_sha256: str
    root_dir: Path
    runs: tuple[CampaignRun, ...]
    gates: tuple[dict[str, Any], ...]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_campaign(path: Path | str) -> Campaign:
    """Validate and materialize every run without importing GPU dependencies."""
    protocol_path = Path(path).resolve()
    payload = json.loads(protocol_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("campaign schema_version must be '1.0'")
    campaign_id = payload.get("campaign_id")
    if not isinstance(campaign_id, str) or not RUN_ID.fullmatch(campaign_id):
        raise ValueError("campaign_id must be a safe lowercase identifier")

    root_dir = Path(payload.get("root_dir", f"runs/campaigns/{campaign_id}"))
    if not root_dir.is_absolute():
        root_dir = (_project_root() / root_dir).resolve()
    base = payload.get("base_config")
    if not isinstance(base, dict):
        raise ValueError("base_config must be an object")
    run_specs = payload.get("runs")
    if not isinstance(run_specs, list) or not run_specs:
        raise ValueError("campaign must contain at least one run")

    protocol_sha = sha256_file(protocol_path)
    seen: set[str] = set()
    runs: list[CampaignRun] = []
    for spec in run_specs:
        if not isinstance(spec, dict):
            raise ValueError("each campaign run must be an object")
        run_id = spec.get("run_id")
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError(f"unsafe run_id {run_id!r}")
        if run_id in seen:
            raise ValueError(f"duplicate run_id {run_id!r}")
        seen.add(run_id)

        overrides = spec.get("config", {})
        if not isinstance(overrides, dict):
            raise ValueError(f"config for {run_id} must be an object")
        values = {**base, **overrides}
        provenance = dict(values.get("provenance") or {})
        provenance.update(
            campaign_id=campaign_id,
            campaign_protocol_sha256=protocol_sha,
            campaign_run_id=run_id,
            campaign_stage=str(spec.get("stage", "unspecified")),
        )
        values["provenance"] = provenance
        for field_name in TUPLE_FIELDS:
            if field_name in values:
                values[field_name] = tuple(values[field_name])
        try:
            config = MDConfig(**values)
        except TypeError as exc:
            raise ValueError(f"invalid config for {run_id}: {exc}") from exc
        config.validate()
        runs.append(
            CampaignRun(
                run_id=run_id,
                stage=str(spec.get("stage", "unspecified")),
                purpose=str(spec.get("purpose", "")),
                enabled=bool(spec.get("enabled", False)),
                run_dir=root_dir / run_id,
                config=config,
            )
        )

    gates = payload.get("gates", [])
    if not isinstance(gates, list) or any(not isinstance(gate, dict) for gate in gates):
        raise ValueError("gates must be a list of objects")
    return Campaign(
        campaign_id=campaign_id,
        protocol_path=protocol_path,
        protocol_sha256=protocol_sha,
        root_dir=root_dir,
        runs=tuple(runs),
        gates=tuple(gates),
    )


def campaign_summary(campaign: Campaign) -> dict[str, Any]:
    return {
        "campaign_id": campaign.campaign_id,
        "protocol_path": str(campaign.protocol_path),
        "protocol_sha256": campaign.protocol_sha256,
        "root_dir": str(campaign.root_dir),
        "gates": list(campaign.gates),
        "runs": [
            {
                "run_id": item.run_id,
                "stage": item.stage,
                "purpose": item.purpose,
                "enabled": item.enabled,
                "run_dir": str(item.run_dir),
                "config": item.config.as_dict(),
            }
            for item in campaign.runs
        ],
    }


def _selected_runs(
    campaign: Campaign, run_ids: set[str] | None
) -> list[CampaignRun]:
    by_id = {item.run_id: item for item in campaign.runs}
    if run_ids is not None:
        missing = sorted(run_ids - by_id.keys())
        if missing:
            raise ValueError("unknown campaign run(s): " + ", ".join(missing))
        return [item for item in campaign.runs if item.run_id in run_ids]
    return [item for item in campaign.runs if item.enabled]


def run_campaign(
    path: Path | str,
    *,
    run_ids: set[str] | None = None,
    quiet: bool = False,
    runner: Callable[..., dict[str, Any]] = run_series,
) -> dict[str, Any]:
    """Run selected entries sequentially and atomically checkpoint campaign state."""
    campaign = load_campaign(path)
    selected = _selected_runs(campaign, run_ids)
    if not selected:
        raise ValueError("no enabled campaign runs were selected")
    campaign.root_dir.mkdir(parents=True, exist_ok=True)
    state_path = campaign.root_dir / "campaign_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("protocol_sha256") != campaign.protocol_sha256:
            raise RuntimeError(
                "campaign protocol changed after state was created; use a new "
                "campaign_id/root_dir instead of mixing protocols"
            )
    else:
        state = {
            "schema_version": "1.0",
            "campaign_id": campaign.campaign_id,
            "protocol_path": str(campaign.protocol_path),
            "protocol_sha256": campaign.protocol_sha256,
            "created_unix_time": time.time(),
            "runs": {},
        }

    for item in selected:
        state["runs"][item.run_id] = {
            "stage": item.stage,
            "run_dir": str(item.run_dir),
            "status": "running",
            "started_unix_time": time.time(),
        }
        state["updated_unix_time"] = time.time()
        atomic_write_json(state_path, state)
        if not quiet:
            print(f"[{item.stage}] {item.run_id}: {item.purpose}")
        try:
            result = runner(item.config, run_dir=item.run_dir, quiet=quiet)
        except BaseException as exc:
            state["runs"][item.run_id].update(
                status="failed",
                finished_unix_time=time.time(),
                error=f"{type(exc).__name__}: {exc}",
            )
            state["updated_unix_time"] = time.time()
            atomic_write_json(state_path, state)
            raise
        state["runs"][item.run_id].update(
            status=result.get("status", "complete_unknown"),
            finished_unix_time=time.time(),
            protocol_fingerprint=result.get("protocol_fingerprint"),
            result_path=str(item.run_dir / "result.json"),
        )
        state["updated_unix_time"] = time.time()
        atomic_write_json(state_path, state)
    return state


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--run", action="append", default=None)
    parser.add_argument("--list", action="store_true", dest="list_only")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    campaign = load_campaign(args.protocol)
    if args.list_only:
        print(json.dumps(campaign_summary(campaign), indent=2))
        return
    state = run_campaign(
        args.protocol,
        run_ids=set(args.run) if args.run else None,
        quiet=args.quiet,
    )
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
