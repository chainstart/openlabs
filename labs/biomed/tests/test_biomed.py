from __future__ import annotations

import csv
import hashlib
import json

import pytest
from protocols.public_data_pilot import validate
from tools.common import LAB_ROOT, atomic_json, sha256
from tools.init_project import initialize
from tools.split_audit import audit

from tools import dataset_intake


def sample_csv(root, rows=None):
    path = root / "samples.csv"
    rows = rows or [
        ["a", "train", "m1", "s1"],
        ["b", "validation", "m2", "s2"],
        ["c", "test", "m3", "s3"],
    ]
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "split", "molecule_id", "scaffold_id"])
        writer.writerows(rows)
    return path


def split_report(root):
    return audit(
        sample_csv(root),
        independent_unit="molecule",
        group_columns=["molecule_id", "scaffold_id"],
        strategy="scaffold",
        project_root=root,
    )


def bind(root, name):
    return {"path": name, "sha256": sha256(root / name)}


def pilot(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    plan = {
        "stage": "exploratory_pilot",
        "independent_unit": "molecule",
        "primary_outcomes": ["RMSE"],
        "baselines": ["median"],
        "split_strategy": "scaffold",
        "group_columns": ["molecule_id", "scaffold_id"],
        "leakage_controls": ["training-only fitting"],
        "stop_conditions": ["three trials"],
        "max_trials": 3,
        "confirmatory_holdout": "unseen later study, not downloaded",
        "resource_budget": {"cpu_threads": 2, "memory_mib": 1024, "scratch_mib": 128},
    }
    atomic_json(root / "plan.json", plan)
    (root / "environment.lock").write_text("# fixture only, no scientific environment\n")
    state = {
        "schema_version": "openlabs.biomed_pilot_state.v1",
        "project_id": "fixture",
        "workstream_id": "pilot",
        "status": "configured",
        "paper_candidate": False,
        "research_question": "Fixture: test protocol rejection",
        "independent_unit": "molecule",
        "next_experiment": "Fixture only",
        "plan": bind(root, "plan.json"),
        "environment": bind(root, "environment.lock"),
        "datasets": [],
        "evidence": [],
        "claims": [],
    }
    project = {
        "schema_version": "openlabs.project.v1",
        "project_id": "fixture",
        "domain": "biology",
        "status": "paused",
        "protocol": {"id": "biomed-public-data-pilot", "primary_skill": "biomed-research-loop"},
        "workstreams": [
            {"workstream_id": "pilot", "state_path": "state.json", "startup": "paused"}
        ],
    }
    atomic_json(root / "project.json", project)
    atomic_json(root / "state.json", state)
    return root, state


def complete_pilot(tmp_path):
    root, state = pilot(tmp_path)
    stage = tmp_path / "artifact-stage"
    stage.mkdir()
    payload = stage / "fixture.txt"
    payload.write_text("Synthetic test fixture, never scientific evidence\n")
    dataset = {
        "schema_version": "openlabs.biomed_dataset.v1",
        "dataset_id": "fixture",
        "source_id": "chembl",
        "release_or_accession": "fixture-not-a-real-release",
        "independent_unit": "molecule",
        "source_url": "https://www.ebi.ac.uk/fixture",
        "final_url": "https://www.ebi.ac.uk/fixture",
        "terms_url": "https://www.ebi.ac.uk/fixture",
        "reuse_basis": "synthetic software test fixture",
        "citation": "not a real dataset",
        "retrieved_at_utc": "2026-10-20T00:00:00+00:00",
        "upstream_study_ids": ["fixture"],
        "access_scope": "public",
        "raw_immutable": True,
        "staging_root": str(stage),
        "artifact_uri": payload.as_uri(),
        "sha256": sha256(payload),
        "bytes": payload.stat().st_size,
    }
    atomic_json(root / "dataset.json", dataset)
    atomic_json(root / "split.json", split_report(root))
    results = {
        "stage": "exploratory_pilot",
        "independent_unit": "molecule",
        "metrics": {"RMSE": 1.0},
        "baselines": {"median": {"RMSE": 2.0}},
        "trials_run": 1,
        "limitations": ["Synthetic fixture only"],
        "run": {
            "command": "synthetic fixture",
            "code_revision": "fixture",
            "seed": 1,
            "environment_sha256": state["environment"]["sha256"],
        },
    }
    atomic_json(root / "results.json", results)
    state.update(
        status="completed",
        datasets=[bind(root, "dataset.json")],
        split_audit=bind(root, "split.json"),
        results=bind(root, "results.json"),
        evidence=[bind(root, "results.json")],
    )
    atomic_json(root / "state.json", state)
    return root, state, payload


def test_configured_and_completed_protocol_pass_both_modes(tmp_path):
    root, state, payload = complete_pilot(tmp_path)
    for mode in ("discovery", "commit"):
        assert validate(root / "project.json", root / "state.json", mode) == []


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"paper_candidate": True}, "paper candidate"),
        ({"status": "completed"}, "dataset manifests"),
        ({"project_id": "other"}, "identity mismatch"),
        ({"claims": [{"text": "claim", "status": "verified"}]}, "hypothesis/provisional/refuted"),
        ({"claims": [{"text": "claim", "status": "provisional"}]}, "requires hash-bound evidence"),
    ],
)
def test_protocol_rejects_unsupported_promotions(tmp_path, change, reason):
    root, state = pilot(tmp_path)
    state.update(change)
    atomic_json(root / "state.json", state)
    assert any(reason in error for error in validate(root / "project.json", root / "state.json"))


def test_plan_tampering_and_evidence_path_escape_rejected(tmp_path):
    root, state = pilot(tmp_path)
    (root / "plan.json").write_text("{}")
    assert any("SHA-256" in error for error in validate(root / "project.json", root / "state.json"))
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    state["environment"] = {"path": "../outside.txt", "sha256": sha256(outside)}
    atomic_json(root / "state.json", state)
    assert any(
        "path escape" in error for error in validate(root / "project.json", root / "state.json")
    )


def test_completed_protocol_rehashes_payload(tmp_path):
    root, state, payload = complete_pilot(tmp_path)
    payload.write_text("tampered")
    assert any("payload" in error for error in validate(root / "project.json", root / "state.json"))


def test_completed_protocol_recomputes_even_a_rehashed_forged_audit(tmp_path):
    root, state, payload = complete_pilot(tmp_path)
    report = json.loads((root / "split.json").read_text())
    report["counts"]["test"] = 999
    atomic_json(root / "split.json", report)
    state["split_audit"] = bind(root, "split.json")
    atomic_json(root / "state.json", state)
    assert any(
        "recomputation" in error for error in validate(root / "project.json", root / "state.json")
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"trials_run": 4}, "max_trials"),
        ({"baselines": {}}, "all planned baselines"),
        ({"metrics": {"RMSE": True}}, "finite result metrics"),
        ({"limitations": []}, "limitations"),
    ],
)
def test_results_require_complete_bounded_record(tmp_path, change, reason):
    root, state, payload = complete_pilot(tmp_path)
    results = json.loads((root / "results.json").read_text())
    results.update(change)
    atomic_json(root / "results.json", results)
    state["results"] = bind(root, "results.json")
    state["evidence"] = [state["results"]]
    atomic_json(root / "state.json", state)
    assert any(reason in error for error in validate(root / "project.json", root / "state.json"))


@pytest.mark.parametrize(
    "column,value", [("molecule_id", "m1"), ("scaffold_id", "s1"), ("sample_id", "a")]
)
def test_split_detects_cross_partition_overlap(tmp_path, column, value):
    path = sample_csv(tmp_path)
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[-1][column] = value
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    result = audit(
        path,
        independent_unit="molecule",
        strategy="scaffold",
        group_columns=["molecule_id", "scaffold_id"],
    )
    assert not result["valid"]
    assert any(column in error for error in result["errors"])


def test_split_rejects_missing_units_empty_partitions_and_row_budget(tmp_path):
    path = sample_csv(tmp_path, [["a", "train", "", "s1"]])
    result = audit(
        path, independent_unit="molecule", strategy="group", group_columns=["molecule_id"]
    )
    assert not result["valid"]
    with pytest.raises(ValueError, match="row ceiling"):
        audit(
            sample_csv(tmp_path),
            independent_unit="molecule",
            strategy="group",
            group_columns=["molecule_id"],
            max_rows=1,
        )
    with pytest.raises(ValueError, match="requires grouping"):
        audit(path, independent_unit="donor", strategy="group", group_columns=["molecule_id"])


class Response:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = {"Content-Type": "application/octet-stream", **(headers or {})}
        self.url = "https://www.ebi.ac.uk/fixture"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        body, self.body = self.body[:size], self.body[size:]
        return body


def intake_kwargs(tmp_path):
    return dict(
        source_id="chembl",
        url="https://www.ebi.ac.uk/fixture",
        staging_root=tmp_path,
        dataset_id="fixture",
        release_or_accession="test-fixture",
        independent_unit="molecule",
        terms_url="https://www.ebi.ac.uk/terms",
        reuse_basis="synthetic test fixture",
        citation="fixture",
        upstream_study_ids=["fixture"],
        filename="data.txt",
        retries=0,
    )


def mock_http(monkeypatch, responses):
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return responses.pop(0)

    monkeypatch.setattr(dataset_intake.urllib.request, "build_opener", lambda handler: Opener())
    monkeypatch.setattr(dataset_intake.time, "sleep", lambda seconds: None)
    return requests


def test_intake_streams_binds_and_refuses_overwrite(tmp_path, monkeypatch):
    mock_http(monkeypatch, [Response(b"actual test bytes")])
    manifest = dataset_intake.download(**intake_kwargs(tmp_path))
    assert manifest["sha256"] == hashlib.sha256(b"actual test bytes").hexdigest()
    assert dataset_intake.validate_manifest(manifest, verify_payload=True) == []
    with pytest.raises(FileExistsError):
        dataset_intake.download(**intake_kwargs(tmp_path))


@pytest.mark.parametrize(
    "headers,body,change,reason",
    [
        ({"Content-Type": "text/html"}, b"login", {}, "HTML"),
        ({}, b"abcdef", {"max_bytes": 3}, "byte ceiling"),
        ({}, b"abcdef", {"expected_sha256": "0" * 64}, "SHA-256"),
    ],
)
def test_intake_rejects_bad_downloads_without_completed_manifest(
    tmp_path,
    monkeypatch,
    headers,
    body,
    change,
    reason,
):
    mock_http(monkeypatch, [Response(body, headers=headers)])
    kwargs = {**intake_kwargs(tmp_path), **change}
    with pytest.raises(ValueError, match=reason):
        dataset_intake.download(**kwargs)
    assert not list(tmp_path.rglob("manifest.json"))
    assert not list(tmp_path.rglob(".download-*"))


def test_intake_resumes_only_with_matching_http_validator(tmp_path, monkeypatch):
    requests = mock_http(
        monkeypatch,
        [
            Response(b"abc", headers={"Content-Length": "6", "ETag": '"v1"'}),
            Response(
                b"def",
                status=206,
                headers={"Content-Length": "3", "Content-Range": "bytes 3-5/6", "ETag": '"v1"'},
            ),
        ],
    )
    kwargs = {**intake_kwargs(tmp_path), "retries": 1}
    manifest = dataset_intake.download(**kwargs)
    assert manifest["sha256"] == hashlib.sha256(b"abcdef").hexdigest()
    assert requests[1].get_header("Range") == "bytes=3-"
    assert requests[1].get_header("If-range") == '"v1"'


def test_intake_restarts_when_server_ignores_range(tmp_path, monkeypatch):
    mock_http(
        monkeypatch,
        [
            Response(b"abc", headers={"Content-Length": "6", "ETag": '"v1"'}),
            Response(b"abcdef", headers={"Content-Length": "6", "ETag": '"v2"'}),
        ],
    )
    manifest = dataset_intake.download(**{**intake_kwargs(tmp_path), "retries": 1})
    assert manifest["sha256"] == hashlib.sha256(b"abcdef").hexdigest()


def test_public_release_signed_redirect_does_not_persist_query_credentials(tmp_path, monkeypatch):
    response = Response(b"public release bytes")
    response.url = "https://www.ebi.ac.uk/fixture?X-Amz-Signature=temporary-secret"
    mock_http(monkeypatch, [response])
    manifest = dataset_intake.download(**intake_kwargs(tmp_path))
    assert manifest["final_url_query_redacted"] is True
    assert "temporary-secret" not in json.dumps(manifest)
    assert dataset_intake.validate_manifest(manifest, verify_payload=True) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://www.ebi.ac.uk/x",
        "https://evil.example/x",
        "https://user:pass@www.ebi.ac.uk/x",
        "https://www.ebi.ac.uk/x?api_key=secret",
    ],
)
def test_intake_rejects_unregistered_or_credential_bearing_urls(tmp_path, url):
    with pytest.raises(ValueError):
        dataset_intake.download(**{**intake_kwargs(tmp_path), "url": url})


def test_redirect_revalidates_destination():
    redirect = dataset_intake.PublicRedirect(["www.ebi.ac.uk"])
    with pytest.raises(ValueError, match="not registered"):
        redirect.redirect_request(None, None, 302, "", {}, "https://evil.example/x")


def test_generated_project_stays_paused_and_is_protocol_valid(tmp_path, monkeypatch):
    # Exercise generation without requiring a freshly installed environment in CI.
    fake_lab = tmp_path / "lab"
    fake_lab.mkdir()
    (fake_lab / "uv.lock").write_text("version = 1\n")
    monkeypatch.setattr("tools.init_project.LAB_ROOT", fake_lab)
    path = initialize(tmp_path / "data", "test-project")
    project = json.loads(path.read_text())
    assert project["status"] == project["workstreams"][0]["startup"] == "paused"
    assert validate(path, path.parent / "research_state.json") == []
    with pytest.raises(FileExistsError):
        initialize(tmp_path / "data", "test-project")


def test_lab_manifest_and_real_protocol_subprocess(tmp_path):
    import subprocess
    import sys

    from jsonschema import validate as schema_validate

    code_root = LAB_ROOT.parents[1]
    manifest = json.loads((LAB_ROOT / "lab.json").read_text())
    schema = json.loads(
        (code_root / "packages/contracts/schemas/openlabs.lab.v1.schema.json").read_text()
    )
    schema_validate(manifest, schema)
    root, state = pilot(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(LAB_ROOT / "protocols/public_data_pilot.py"),
            "--project",
            str(root / "project.json"),
            "--workstream",
            str(root / "state.json"),
            "--mode",
            "discovery",
        ],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"]
