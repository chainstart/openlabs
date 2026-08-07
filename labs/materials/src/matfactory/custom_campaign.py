"""Run a campaign with the hash-locked CHGNet artifact embedded in its protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .campaign import load_campaign, run_campaign
from .mlipmd import _model_metadata
from .provenance import fingerprint, sha256_file


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def validate_custom_campaign(
    protocol_path: Path | str, run_ids: set[str] | None = None
) -> dict[str, Any]:
    """Verify the derived protocol, training report, artifact, and run configs."""
    from chgnet.model import CHGNet

    source = Path(protocol_path).resolve()
    payload = _read_json(source)
    stored_derivation = payload.get("derivation_fingerprint")
    unsigned = dict(payload)
    unsigned.pop("derivation_fingerprint", None)
    if stored_derivation != fingerprint(unsigned):
        raise RuntimeError("custom campaign derivation fingerprint mismatch")
    artifact = payload.get("derived_model_artifact")
    if not isinstance(artifact, dict):
        raise ValueError("custom campaign has no derived model artifact")
    artifact_path = Path(artifact["path"]).resolve()
    report_path = Path(artifact["training_report_path"]).resolve()
    if sha256_file(artifact_path) != artifact.get("sha256"):
        raise RuntimeError("custom campaign model artifact changed")
    if sha256_file(report_path) != artifact.get("training_report_sha256"):
        raise RuntimeError("custom campaign training report changed")
    report = _read_json(report_path)
    report_unsigned = dict(report)
    report_fingerprint = report_unsigned.pop("report_fingerprint", None)
    if (
        report_fingerprint != fingerprint(report_unsigned)
        or report_fingerprint != artifact.get("training_report_fingerprint")
    ):
        raise RuntimeError("custom campaign training report fingerprint mismatch")
    model = CHGNet.from_file(str(artifact_path))
    model_metadata = _model_metadata(model, payload["base_config"]["model_name"])
    if model_metadata["state_dict_sha256"] != artifact.get("state_dict_sha256"):
        raise RuntimeError("custom campaign model state dictionary changed")
    campaign = load_campaign(source)
    selected = [
        run
        for run in campaign.runs
        if (run_ids is None and run.enabled)
        or (run_ids is not None and run.run_id in run_ids)
    ]
    if run_ids is not None:
        missing = run_ids - {run.run_id for run in campaign.runs}
        if missing:
            raise ValueError("unknown custom campaign run(s): " + ", ".join(sorted(missing)))
    if not selected:
        raise ValueError("no custom campaign runs selected")
    for run in selected:
        if (
            run.config.expected_model_state_dict_sha256
            != artifact["state_dict_sha256"]
            or run.config.model_name == "CHGNet-default"
        ):
            raise RuntimeError(f"custom model identity mismatch: {run.run_id}")
    return {
        "protocol_path": str(source),
        "protocol_sha256": campaign.protocol_sha256,
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact["sha256"],
        "model_state_dict_sha256": artifact["state_dict_sha256"],
        "selected_run_ids": [run.run_id for run in selected],
    }


def run_custom_campaign(
    protocol_path: Path | str,
    *,
    run_ids: set[str] | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """Patch only CHGNet.load during one campaign to return the locked artifact."""
    from chgnet.model import CHGNet

    validation = validate_custom_campaign(protocol_path, run_ids)
    artifact_path = validation["artifact_path"]

    def load_locked_model(cls, *args: Any, **kwargs: Any) -> Any:
        del cls, args
        kwargs.pop("model_name", None)
        kwargs.pop("use_device", None)
        kwargs.pop("check_cuda_mem", None)
        kwargs.pop("verbose", None)
        if kwargs:
            raise ValueError(f"unexpected custom CHGNet load options: {sorted(kwargs)}")
        return CHGNet.from_file(artifact_path)

    with patch.object(CHGNet, "load", new=classmethod(load_locked_model)):
        return run_campaign(
            protocol_path,
            run_ids=run_ids,
            quiet=quiet,
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--run", action="append", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    result = run_custom_campaign(
        args.protocol,
        run_ids=set(args.run) if args.run else None,
        quiet=args.quiet,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
