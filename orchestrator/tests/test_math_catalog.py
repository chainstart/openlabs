from __future__ import annotations

import json

import pytest

from openlabs import __main__ as cli
from openlabs import math_catalog
from openlabs.config import workspace_paths
from openlabs.contracts import atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.math_catalog import (
    BUNDLE_SCHEMA, MAX_BUNDLE_BYTES, NAMESPACE, CatalogValidationError,
    catalog_stats, ingest_bundle, load_bundle, parse_metadata_filters, show_catalog,
)


@pytest.fixture
def catalog(tmp_path):
    paths = workspace_paths(tmp_path)
    db = FactoryDB(paths.database_file)
    db.initialize()
    return paths, db


def record(record_id="math-catalog:problem:test", kind="math_problem", **updates):
    result = {
        "record_id": record_id, "kind": kind, "domain": "math", "title": "Test question",
        "status": "open_in_source", "source_path": "registry/math-problems/catalog.json",
        "metadata": {"entity_id": "test", "selection_eligible": True,
                     "provenance": {"revision": "v1"}},
    }
    result.update(updates)
    return result


def bundle(paths, records=None, **updates):
    payload = {"schema_version": BUNDLE_SCHEMA, "namespace": NAMESPACE,
               "generated_at": "2026-09-05T12:00:00Z", "records": records if records is not None else [record()]}
    payload.update(updates)
    path = atomic_write_json(paths.data / "registry/math-problems/bundle.json", payload)
    return path, sha256_file(path)


def ingest(paths, db, records=None, **updates):
    path, digest = bundle(paths, records, **updates)
    return ingest_bundle(db, data_root=paths.data, bundle=path, expected_sha256=digest)


def events(db):
    with db.connect() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM events ORDER BY event_id")]


def test_import_is_idempotent_and_preserves_old_business(catalog):
    paths, db = catalog
    db.upsert_research_record("old-problem", kind="problem", domain="math", title="Existing",
                             status="open", source_path="labs/math/problems/old.md")
    first = ingest(paths, db)
    before = db.research_records()
    second = ingest(paths, db)
    assert first["counts"] == {"inserted": 1, "updated": 0, "unchanged": 0}
    assert second["counts"] == {"inserted": 0, "updated": 0, "unchanged": 1}
    assert before == db.research_records()
    assert catalog_stats(db)["total"] == 1
    assert db.campaigns() == []
    assert db.status_counts() == {}
    row_events = [event for event in events(db) if event["event_type"].startswith("math_catalog_record_")]
    assert len(row_events) == 1
    assert first["bundle"]["sha256"] == second["bundle"]["sha256"]


def test_update_audits_previous_and_current_and_keeps_created_at(catalog):
    paths, db = catalog
    ingest(paths, db)
    original = show_catalog(db)["records"][0]
    receipt = ingest(paths, db, [record(title="Revised question", status="review_required")])
    updated = show_catalog(db)["records"][0]
    assert receipt["counts"]["updated"] == 1
    assert updated["created_at"] == original["created_at"]
    update_event = next(event for event in events(db) if event["event_type"] == "math_catalog_record_updated")
    payload = json.loads(update_event["payload_json"])
    assert payload["previous"] == original
    assert payload["current"]["title"] == "Revised question"
    assert payload["bundle"]["sha256"] == receipt["bundle"]["sha256"]


@pytest.mark.parametrize("update", [
    {"schema_version": "wrong"}, {"namespace": "problem"}, {"records": {}},
    {"generated_at": "2026-09-05"}, {"generated_at": "not-a-time"},
    {"records": [record(), record()]}, {"records": [None]},
    {"records": [record(record_id="ordinary-problem")]},
    {"records": [record(kind="paper")]}, {"records": [record(domain="physics")]},
    {"records": [record(kind=[])]},
    {"records": [record(metadata=[])]}, {"records": [record(title="")]},
    {"records": [record(metadata={"record_references": "math-catalog:x"})]},
    {"records": [record(metadata={"record_references": ["https://example.org"]})]},
])
def test_invalid_schema_never_changes_database(catalog, update):
    paths, db = catalog
    with pytest.raises(CatalogValidationError):
        ingest(paths, db, **update)
    assert db.research_records() == []
    assert events(db) == []


@pytest.mark.parametrize("source_path", [
    "/registry/math-problems/a.json", "../registry/math-problems/a.json",
    "registry/math-problems/../../papers/a.json", "registry/math-problems-evil/a.json",
    "registry/math-problems", "registry/math-problems//a.json",
    "registry/math-problems/./a.json", "registry\\math-problems\\a.json",
    "workspaces/math/other/a.json",
])
def test_source_path_boundaries(catalog, source_path):
    paths, db = catalog
    with pytest.raises(CatalogValidationError):
        ingest(paths, db, [record(source_path=source_path)])
    assert db.research_records() == []


def test_symlink_escape_and_bundle_outside_catalog_rejected(catalog, tmp_path):
    paths, db = catalog
    outside = tmp_path / "outside"
    outside.mkdir()
    path, digest = bundle(paths)
    (paths.data / "registry/math-problems/escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CatalogValidationError, match="symlink"):
        ingest(paths, db, [record(source_path="registry/math-problems/escape/a.json")])
    outside_bundle = atomic_write_json(outside / "bundle.json", {})
    with pytest.raises(CatalogValidationError, match="inside"):
        load_bundle(outside_bundle, data_root=paths.data, expected_sha256=sha256_file(outside_bundle))
    linked = paths.data / "registry/math-problems/linked.json"
    linked.symlink_to(outside_bundle)
    with pytest.raises(CatalogValidationError, match="symlink"):
        load_bundle(linked, data_root=paths.data, expected_sha256=digest)


def test_hash_mismatch_and_duplicate_json_keys_rejected(catalog):
    paths, db = catalog
    path, digest = bundle(paths)
    with pytest.raises(CatalogValidationError, match="SHA256"):
        ingest_bundle(db, data_root=paths.data, bundle=path, expected_sha256="0" * 64)
    path.write_text('{"schema_version": "a", "schema_version": "b"}', encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="duplicate JSON key"):
        ingest_bundle(db, data_root=paths.data, bundle=path, expected_sha256=sha256_file(path))
    assert db.research_records() == []
    assert MAX_BUNDLE_BYTES >= 128 * 1024 * 1024


def test_size_limit_and_nonfinite_metadata_fail_before_writing(catalog, monkeypatch):
    paths, db = catalog
    path, digest = bundle(paths)
    with monkeypatch.context() as scoped:
        scoped.setattr(math_catalog, "MAX_BUNDLE_BYTES", 10)
        with pytest.raises(CatalogValidationError, match="exceeds"):
            ingest_bundle(db, data_root=paths.data, bundle=path, expected_sha256=digest)
    with pytest.raises(CatalogValidationError, match="nonfinite"):
        ingest(paths, db, [record(metadata={"score": float("nan")})])
    assert db.research_records() == []


def test_large_bundle_and_external_catalog_reference(catalog):
    paths, db = catalog
    records = [record(f"math-catalog:problem:{index}") for index in range(8_000)]
    receipt = ingest(paths, db, records)
    assert receipt["counts"]["inserted"] == 8_000
    assert catalog_stats(db)["total"] == 8_000
    assert ingest(paths, db, records)["counts"]["unchanged"] == 8_000
    assert len(show_catalog(db, limit=10_000)["records"]) == 8_000


def test_catalog_root_symlink_cannot_move_authority_outside_data(tmp_path):
    paths = workspace_paths(tmp_path)
    (paths.data / "registry").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (paths.data / "registry/math-problems").symlink_to(outside, target_is_directory=True)
    path, digest = bundle(paths)
    with pytest.raises(CatalogValidationError, match="symlink"):
        load_bundle(path, data_root=paths.data, expected_sha256=digest)


def test_forward_existing_and_semantic_references(catalog):
    paths, db = catalog
    source = record("math-catalog:source:test", "math_source", metadata={"source_id": "test", "references": ["https://example.org/paper"]})
    problem = record(metadata={"source_ids": [source["record_id"]], "statement_ids": ["math-catalog:statement:test"]})
    statement = record("math-catalog:statement:test", "math_statement", metadata={
        "problem_id": problem["record_id"], "source_id": source["record_id"],
        "record_references": [source["record_id"], problem["record_id"]],
    })
    assert ingest(paths, db, [problem, statement, source])["counts"]["inserted"] == 3
    progress = record("math-catalog:progress:test", "math_progress", metadata={"problem_id": problem["record_id"]})
    assert ingest(paths, db, [progress])["counts"]["inserted"] == 1
    before = db.research_records()
    for key, value in (("problem_id", "math-catalog:missing"), ("record_references", ["math-catalog:missing"])):
        with pytest.raises(CatalogValidationError, match="unresolved"):
            ingest(paths, db, [record(title="Must not commit"), record("math-catalog:bad", metadata={key: value})])
        assert db.research_records() == before


@pytest.mark.parametrize("kind,domain,source", [
    ("paper", "math", "registry/math-problems/a.json"),
    ("math_problem", "physics", "registry/math-problems/a.json"),
    ("math_problem", "math", "papers/existing.json"),
    ("math_review", "math", "registry/math-problems/a.json"),
])
def test_preexisting_foreign_or_wrong_kind_records_cannot_be_overwritten(catalog, kind, domain, source):
    paths, db = catalog
    db.upsert_research_record("math-catalog:problem:test", kind=kind, domain=domain,
                             title="Protected", status="old", source_path=source)
    before = db.research_records()
    with pytest.raises(CatalogValidationError, match="refusing"):
        ingest(paths, db, [record("math-catalog:new"), record()])
    assert db.research_records() == before


def test_write_failure_rolls_back_entire_batch_and_events(catalog, monkeypatch):
    paths, db = catalog
    original_event = db._event

    def fail_second(connection, entity_type, entity_id, event_type, payload=None):
        if entity_id == "math-catalog:second":
            raise RuntimeError("simulated event failure")
        original_event(connection, entity_type, entity_id, event_type, payload)

    monkeypatch.setattr(db, "_event", fail_second)
    with pytest.raises(RuntimeError, match="simulated"):
        ingest(paths, db, [record(), record("math-catalog:second")])
    assert db.research_records() == []
    assert events(db) == []


def test_query_filters_pagination_and_stats(catalog):
    paths, db = catalog
    second = record("math-catalog:problem:second", status="review_required", metadata={"selection_eligible": False})
    third = record("math-catalog:progress:first", "math_progress", metadata={"selection_eligible": 1})
    ingest(paths, db, [record(), second, third])
    filters = parse_metadata_filters(["selection_eligible=true", "provenance.revision=v1"])
    result = show_catalog(db, kind="math_problem", metadata_filters=filters)
    assert [row["record_id"] for row in result["records"]] == [record()["record_id"]]
    assert catalog_stats(db)["by_kind"] == {"math_problem": 2, "math_progress": 1}
    assert catalog_stats(db, status="review_required")["total"] == 1
    assert show_catalog(db, limit=1, offset=1)["total"] == 3
    assert len(show_catalog(db, limit=1, offset=1)["records"]) == 1
    assert show_catalog(db, record_id="math-catalog:missing")["total"] == 0
    with pytest.raises(CatalogValidationError):
        show_catalog(db, limit=0)
    with pytest.raises(CatalogValidationError):
        parse_metadata_filters(["x"])
    with pytest.raises(CatalogValidationError):
        parse_metadata_filters(["x=true", "x=false"])


def test_cli_never_initializes_or_schedules(catalog, monkeypatch, capsys):
    paths, db = catalog
    path, digest = bundle(paths)
    monkeypatch.setattr(cli, "load_local_environment", lambda: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("catalog must not initialize or schedule")

    monkeypatch.setattr(FactoryDB, "initialize", forbidden)
    monkeypatch.setattr(cli, "tick", forbidden)
    base = ["--workspace", str(paths.workspace), "math-catalog"]
    assert cli.main([*base, "ingest", "--bundle", str(path), "--expected-sha256", digest]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["inserted"] == 1
    assert cli.main([*base, "show", "--metadata", "selection_eligible=true"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1
    assert cli.main([*base, "stats", "--kind", "math_problem"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1
    assert cli.main([*base, "ingest", "--bundle", str(path), "--expected-sha256", "bad"]) == 65
    assert json.loads(capsys.readouterr().err)["status"] == "rejected"


def test_queries_and_ingestion_do_not_create_missing_database(tmp_path, monkeypatch, capsys):
    paths = workspace_paths(tmp_path)
    db = FactoryDB(paths.database_file)
    with pytest.raises(CatalogValidationError, match="existing"):
        show_catalog(db)
    with pytest.raises(CatalogValidationError, match="existing"):
        ingest(paths, db)
    monkeypatch.setattr(cli, "load_local_environment", lambda: None)
    assert cli.main(["--workspace", str(tmp_path), "math-catalog", "stats"]) == 65
    assert not paths.database.exists()
    assert not paths.job_inbox.exists()
    assert json.loads(capsys.readouterr().err)["status"] == "rejected"


def test_cli_full_receipt_saved_with_compact_stdout(catalog, monkeypatch, capsys):
    paths, db = catalog
    path, digest = bundle(paths)
    monkeypatch.setattr(cli, "load_local_environment", lambda: None)
    relative = "registry/math-problems/receipts/import.json"
    arguments = ["--workspace", str(paths.workspace), "math-catalog", "ingest",
                 "--bundle", str(path), "--expected-sha256", digest, "--receipt", relative]
    assert cli.main(arguments) == 0
    summary = json.loads(capsys.readouterr().out)
    complete = json.loads((paths.data / relative).read_text())
    assert "record_ids" not in summary
    assert summary["receipt_path"] == relative
    assert complete["record_ids"] == [record()["record_id"]]
    assert complete["counts"] == summary["counts"]
    assert cli.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["unchanged"] == 1


def test_cli_receipt_path_rejected_before_import(catalog, monkeypatch, capsys, tmp_path):
    paths, db = catalog
    path, digest = bundle(paths)
    monkeypatch.setattr(cli, "load_local_environment", lambda: None)
    outside = tmp_path / "outside"
    outside.mkdir()
    (paths.data / "registry/math-problems/escape").symlink_to(outside, target_is_directory=True)
    invalid = [str(tmp_path / "receipt.json"), "registry/math-problems/../../papers/receipt.json",
               "registry/math-problems/escape/receipt.json", str(path)]
    original_bundle = path.read_bytes()
    for destination in invalid:
        assert cli.main(["--workspace", str(paths.workspace), "math-catalog", "ingest",
                         "--bundle", str(path), "--expected-sha256", digest,
                         "--receipt", destination]) == 65
        assert json.loads(capsys.readouterr().err)["status"] == "rejected"
    assert db.research_records() == []
    assert path.read_bytes() == original_bundle
    assert not (outside / "receipt.json").exists()


def test_cli_reports_committed_import_if_receipt_write_fails(catalog, monkeypatch, capsys):
    paths, db = catalog
    path, digest = bundle(paths)
    monkeypatch.setattr(cli, "load_local_environment", lambda: None)

    def failed_write(*args, **kwargs):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(cli, "atomic_write_json", failed_write)
    assert cli.main(["--workspace", str(paths.workspace), "math-catalog", "ingest",
                     "--bundle", str(path), "--expected-sha256", digest,
                     "--receipt", "registry/math-problems/receipts/import.json"]) == 74
    report = json.loads(capsys.readouterr().err)
    assert report["status"] == "imported_receipt_write_failed"
    assert report["receipt_summary"]["counts"]["inserted"] == 1
    assert "record_ids" not in report["receipt_summary"]
    assert catalog_stats(db)["total"] == 1
    assert any(event["event_type"] == "math_catalog_ingested" for event in events(db))
