"""Round-two intake seals, status boundaries and offline literature regression tests.

All writes are isolated under pytest's temporary directory. No live source,
catalog snapshot, database, scientific campaign or network is touched.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
STAMP = "2026-09-05T09:00:00.000001+00:00"
SOURCE = "clay-millennium"
PROBLEM = "math-catalog:problem:round2"
STATEMENT = "math-catalog:statement:round2"
RANK_MOTHER = "math-catalog:problem:rank-conditioned-graphic-forest-rayleigh"


def module(name):
    spec = importlib.util.spec_from_file_location("round2_test_" + name, TOOLS / (name + ".py"))
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


catalog = module("problem_catalog")
intake = module("problem_catalog_intake")
literature = module("problem_catalog_literature")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))

    def reject_network(*args, **kwargs):
        raise AssertionError("round-two regression tests must not access the network")

    monkeypatch.setattr(catalog.urllib.request, "urlopen", reject_network)


@pytest.fixture
def paths(tmp_path):
    paths = SimpleNamespace(data=tmp_path / "data", artifacts=tmp_path / "artifacts")
    (paths.data / intake.ROOT / "intake-batches").mkdir(parents=True)
    return paths


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def statement(**patch):
    result = {
        "statement_id": STATEMENT, "problem_id": PROBLEM, "source_id": SOURCE,
        "language": "natural_language", "statement_text": "For every n ≥ 1, P(n) holds.",
        "source_revision": "a" * 40, "file_sha256": "b" * 64,
        "source_sha256": "c" * 64, "evidence": ["https://example.org/problem"],
    }
    result.update(patch)
    return result


def statement_record(**patch):
    return catalog.record("math_statement", "round2", "A quantified statement", "source_unverified", statement(**patch))


def review(**patch):
    result = {
        "problem_id": PROBLEM, "reviewed_statement_ids": [STATEMENT],
        "scope_review": "passed", "influence_status": "review_passed",
        "reviewed_at": STAMP, "reason": "Exact domain and quantifiers checked against the cited source.",
        "evidence": ["https://example.org/problem"],
        "require_statement_bindings": True,
        "statement_bindings": {STATEMENT: intake.statement_binding(statement())},
    }
    result.update(patch)
    return result


def fixture_records(status="open_in_source"):
    p = catalog.new_problem("round2", "Mother question", SOURCE, status)
    p["metadata"]["statement_ids"] = [STATEMENT]
    p["metadata"]["statement_status"] = "imported_natural_language"
    sources = {
        catalog.sid(SOURCE): catalog.record("math_source", SOURCE, "Official source", "approved", {})
    }
    return {PROBLEM: p}, {STATEMENT: statement_record()}, sources


def finalize(problems, statements):
    for problem in problems.values():
        catalog.finalize_problem(problem, statements)
    return problems[PROBLEM]["metadata"]


def seed_batch(paths, *, new_statement=False, **patch):
    existing = [] if new_statement else [statement_record()]
    write_json(paths.data / intake.ROOT / "catalog-bundle.json", {"records": existing})
    body = {"batch_id": "round2-v1", "problems": [],
            "statements": [statement()] if new_statement else [],
            "reviews": [review()], "identity_decisions": []}
    body.update(patch)
    path = paths.data / intake.ROOT / "intake-batches/round2-v1.json"
    write_json(path, body)
    return path, body


@pytest.mark.parametrize("field", ["statement_text", "language", "source_revision", "file_sha256", "source_sha256"])
def test_binding_changes_when_text_or_definition_provenance_changes(field):
    original = statement()
    assert intake.statement_binding(original) != intake.statement_binding({**original, field: "changed"})


def test_binding_matches_wrapped_record_and_ignores_display_only_edits():
    original = statement()
    assert intake.statement_binding(original) == intake.statement_binding({"metadata": original})
    assert intake.statement_binding(original) == intake.statement_binding({**original, "title": "Retitled"})


@pytest.mark.parametrize("new_statement", [False, True])
def test_seal_pins_existing_or_new_exact_statement_and_is_idempotent(paths, new_statement):
    path, original = seed_batch(paths, new_statement=new_statement)
    result = intake.seal_batch(paths, path, write_json)
    saved = json.loads((paths.data / result["path"]).read_text())
    assert saved["_seal"]["source_body_sha256"] == intake.canonical_digest(original)
    sealed_review, = saved["reviews"]
    assert sealed_review["require_statement_bindings"] is True
    assert sealed_review["statement_bindings"] == {STATEMENT: intake.statement_binding(statement())}
    assert intake.load_reviewed_batches(paths) == [saved]
    assert intake.seal_batch(paths, path, write_json)["unchanged"] is True
    assert json.loads(path.read_text()) == original


@pytest.mark.parametrize("mode", ["empty_scope", "missing_statement", "overwrite_statement"])
def test_seal_refuses_unbound_scope_or_existing_statement_overwrite(paths, mode):
    path, body = seed_batch(paths)
    if mode == "empty_scope":
        body["reviews"][0]["reviewed_statement_ids"] = []
    elif mode == "missing_statement":
        body["reviews"][0]["reviewed_statement_ids"] = ["math-catalog:statement:absent"]
    else:
        body["statements"] = [statement()]
    write_json(path, body)
    with pytest.raises(ValueError):
        intake.seal_batch(paths, path, write_json)
    assert not (paths.data / intake.ROOT / "reviewed-batches/round2-v1.json").exists()


def test_changed_unsealed_batch_requires_a_new_revision_filename(paths):
    path, body = seed_batch(paths)
    result = intake.seal_batch(paths, path, write_json)
    original = (paths.data / result["path"]).read_bytes()
    body["reviews"][0]["reason"] = "Changed review evidence."
    write_json(path, body)
    with pytest.raises(ValueError, match="new revision"):
        intake.seal_batch(paths, path, write_json)
    assert (paths.data / result["path"]).read_bytes() == original


def test_load_refuses_tampered_review_body(paths):
    path, _ = seed_batch(paths)
    result = intake.seal_batch(paths, path, write_json)
    saved_path = paths.data / result["path"]
    saved = json.loads(saved_path.read_text())
    saved["reviews"][0]["scope_review"] = "forged"
    write_json(saved_path, saved)
    with pytest.raises(ValueError, match="hash mismatch"):
        intake.load_reviewed_batches(paths)


def test_load_refuses_duplicate_batch_identity_under_different_filenames(paths):
    path, _ = seed_batch(paths)
    result = intake.seal_batch(paths, path, write_json)
    saved = json.loads((paths.data / result["path"]).read_text())
    write_json(paths.data / intake.ROOT / "reviewed-batches/duplicate.json", saved)
    with pytest.raises(ValueError, match="duplicate reviewed batch ID"):
        intake.load_reviewed_batches(paths)


def test_review_revision_selection_retains_older_assessment_as_history():
    old = review(reviewed_at="2026-09-04T23:00:00Z", reason="Earlier assessment.")
    new = review(reviewed_at="2026-09-05T08:00:00+08:00", reason="Later assessment.")
    active, history = intake.current_reviews([new, old])
    assert active == [new]
    assert history == [{**old, "superseded_by_reviewed_at": new["reviewed_at"]}]
    assert "superseded_by_reviewed_at" not in old


def test_equivalent_absolute_timestamps_cannot_select_an_arbitrary_review():
    with pytest.raises(ValueError, match="same latest timestamp"):
        intake.current_reviews([review(reviewed_at="2026-09-05T00:00:00Z"),
                                review(reviewed_at="2026-09-05T08:00:00+08:00")])


def test_review_revision_selection_rejects_timezone_free_dates():
    with pytest.raises(ValueError, match="timezone"):
        intake.current_reviews([review(reviewed_at="2026-09-05T00:00:00")])


@pytest.mark.parametrize("mode", ["outside", "symlink", "wrong_suffix"])
def test_seal_input_is_a_bounded_json_file_inside_intake_directory(paths, mode):
    path, body = seed_batch(paths)
    if mode == "outside":
        target = paths.data / "outside.json"
        write_json(target, body)
    elif mode == "symlink":
        target = path.with_name("link.json")
        target.symlink_to(path)
    else:
        target = path.with_suffix(".txt")
        write_json(target, body)
    with pytest.raises(ValueError, match="inside intake-batches"):
        intake.seal_batch(paths, target, write_json)


@pytest.mark.parametrize("field", ["statement_text", "language", "source_revision", "file_sha256", "source_sha256"])
def test_changed_statement_binding_revokes_selection_even_with_legacy_review(field):
    problems, statements, records = fixture_records()
    problems[PROBLEM]["metadata"].update({"legacy_review_retained": True,
        "statement_status": "reviewed_natural_language", "explicit_intake_review_passed": True,
        "quantifier_review": "reviewed_in_local_intake"})
    statements[STATEMENT]["metadata"][field] = "changed"
    catalog.apply_intake_reviews(problems, statements, records, [review()])
    meta = finalize(problems, statements)
    assert not meta["selection_eligible"]
    assert not meta["explicit_intake_review_passed"]
    assert meta["quantifier_review"] == "stale_statement_version_requires_review"
    evidence = [r for r in records.values() if r["kind"] == "math_review"]
    assert len(evidence) == 1 and evidence[0]["metadata"]["statement_bindings_stale"]


def test_missing_required_statement_pin_cannot_pass_scope_review():
    problems, statements, records = fixture_records()
    catalog.apply_intake_reviews(problems, statements, records, [review(statement_bindings={})])
    meta = finalize(problems, statements)
    assert not meta["selection_eligible"]
    assert meta["quantifier_review"] == "stale_statement_version_requires_review"


def status_claim():
    return {"status": "public_resolution_claim", "checked_at": STAMP,
            "evidence": ["https://example.org/unreviewed-proof-preprint"]}


def test_public_resolution_claim_is_quarantined_and_never_certifies_a_proof():
    problems, statements, records = fixture_records()
    before = deepcopy(statements)
    catalog.apply_intake_reviews(problems, statements, records, [review(scientific_status_review=status_claim())])
    meta = finalize(problems, statements)
    assert meta["scientific_status"] == "public_resolution_claim"
    assert not meta["screening_eligible"] and not meta["selection_eligible"]
    assert meta["resolution_claim_not_independently_proof_audited"]
    assert "scientific_status_review" in meta["next_actions"]
    assert statements == before


@pytest.mark.parametrize("status", ["solved_in_source", "disproved_in_source", "independent_of_zfc_in_source"])
def test_public_claim_cannot_erase_an_existing_definitive_source_state(status):
    problems, statements, records = fixture_records(status)
    catalog.apply_intake_reviews(problems, statements, records, [review(scientific_status_review=status_claim())])
    meta = finalize(problems, statements)
    assert meta["scientific_status"] in {status, "source_status_conflict"}
    assert not meta["screening_eligible"] and not meta["selection_eligible"]


def test_stale_scope_cannot_promote_a_public_claim_to_the_mother():
    problems, statements, records = fixture_records()
    statements[STATEMENT]["metadata"]["source_revision"] = "new revision"
    catalog.apply_intake_reviews(problems, statements, records, [review(scientific_status_review=status_claim())])
    meta = finalize(problems, statements)
    assert meta["scientific_status"] != "public_resolution_claim"
    assert not meta["selection_eligible"]


def batch(**patch):
    result = {"batch_id": "round2-v1", "_seal": {"review_body_sha256": "d" * 64},
              "problems": [], "statements": [], "statement_observations": []}
    result.update(patch)
    return result


def source_observation(**patch):
    result = {"problem_id": PROBLEM, "source_id": SOURCE, "source_item_id": "round2",
        "title": "Mother question", "scientific_status": "open_in_source",
        "source_url": "https://example.org/problem", "checked_at": STAMP,
        "evidence": ["https://example.org/problem"], "influence_status": "review_passed",
        "source_summary": "An explanatory overview, not an exact mathematical statement."}
    result.update(patch)
    return result


@pytest.mark.parametrize("status", ["open_in_source", "solved_in_source"])
def test_metadata_summary_alone_never_unlocks_selection(status):
    _, _, records = fixture_records()
    problems, statements = {}, {}
    catalog.apply_batch_items([batch(problems=[source_observation(scientific_status=status)])], problems, statements, records)
    meta = finalize(problems, statements)
    assert meta["scientific_status"] == status
    assert meta["statement_status"] == "summary_only"
    assert not meta["selection_eligible"] and not meta["research_ready"]
    assert meta["statement_ids"] == []


def test_conflicting_source_observation_does_not_silently_reopen_a_closed_mother():
    problems, statements, records = fixture_records("solved_in_source")
    catalog.apply_batch_items([batch(problems=[source_observation()])], problems, statements, records)
    meta = finalize(problems, statements)
    assert meta["scientific_status"] == "source_status_conflict"
    assert not meta["selection_eligible"]
    assert meta["source_catalog_items"][0]["scientific_status"] == "open_in_source"


def test_scoped_statement_resolution_is_not_a_mother_resolution():
    problems, statements, records = fixture_records()
    observation = {"statement_id": STATEMENT, "status": "solved_in_source",
                   "affects_entire_mother": False, "evidence": ["https://example.org/scoped-proof"]}
    catalog.apply_batch_items([batch(statement_observations=[observation])], problems, statements, records)
    assert finalize(problems, statements)["scientific_status"] == "open_in_source"
    assert statements[STATEMENT]["metadata"]["source_status_review_required"]
    progress = next(r for r in records.values() if r["kind"] == "math_progress")
    assert progress["metadata"]["automatically_closes_problem"] is False


@pytest.mark.parametrize("scope", [None, True])
def test_statement_observation_requires_explicitly_nonmother_scope(scope):
    problems, statements, records = fixture_records()
    observation = {"statement_id": STATEMENT, "affects_entire_mother": scope,
                   "evidence": ["https://example.org/scoped-proof"]}
    with pytest.raises(ValueError, match="explicitly scoped effect"):
        catalog.apply_batch_items([batch(statement_observations=[observation])], problems, statements, records)


def test_natural_statement_import_cannot_smuggle_verification_flags():
    problems, _, records = fixture_records()
    problems[PROBLEM]["metadata"]["statement_ids"] = []
    statements = {}
    incoming = statement(verified=True, local_elaboration_checked=True)
    catalog.apply_batch_items([batch(statements=[incoming])], problems, statements, records)
    meta = statements[STATEMENT]["metadata"]
    assert meta["verified"] is False and meta["local_elaboration_checked"] is False
    assert not finalize(problems, statements)["selection_eligible"]


@pytest.mark.parametrize("kind", ["problems", "statements"])
def test_excluded_source_cannot_enter_via_either_batch_entity_type(kind):
    problems, _, records = fixture_records()
    records[catalog.sid(SOURCE)]["status"] = "excluded"
    problems[PROBLEM]["metadata"]["statement_ids"] = []
    incoming = source_observation() if kind == "problems" else statement()
    with pytest.raises(ValueError, match="excluded source"):
        catalog.apply_batch_items([batch(**{kind: [incoming]})], problems, {}, records)


def atom(*ids):
    entries = []
    for source_id in ids:
        entries.append(f"""<entry><id>{source_id}</id><title>  Claimed\n result </title>
          <summary> A\n short abstract. </summary><updated>2026-09-04T00:00:00Z</updated>
          <published>2026-08-01T00:00:00Z</published><author><name>A. Author</name></author>
          <arxiv:doi>10.0000/fixture</arxiv:doi></entry>""")
    return ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">'
            + "".join(entries) + "</feed>").encode()


@pytest.mark.parametrize("url,expected", [
    ("http://arxiv.org/abs/2609.01234v2", "2609.01234"),
    ("https://arxiv.org/abs/0704.0001v1", "0704.0001"),
    ("http://arxiv.org/abs/math/0309136v3", "math/0309136"),
    ("http://arxiv.org/abs/hep-th/9901001v2", "hep-th/9901001"),
])
def test_atom_parser_normalizes_old_and_new_ids_without_losing_version(url, expected):
    entry, = literature.parse_feed(atom(url))
    assert entry["id"] == expected and entry["version_url"] == url
    assert entry["title"] == "Claimed result" and entry["summary"] == "A short abstract."
    assert entry["authors"] == ["A. Author"]
    assert entry["doi"] == "10.0000/fixture"


@pytest.mark.parametrize("url", [
    "https://notarxiv.org/abs/2609.01234", "https://arxiv.org/abs/2609.012345",
    "https://arxiv.org/abs/hep-th/99010012", "https://arxiv.org/abs/2609.01234garbage",
])
def test_arxiv_identity_requires_valid_host_and_complete_id_not_a_prefix(url):
    assert literature.parse_feed(atom(url)) == []


def plan_path(paths, queries):
    path = paths.data / literature.ROOT / "literature-plans/round2.json"
    write_json(path, {"plan_id": "round2", "queries": queries})
    return path


def run_plan(paths, path, fetch, stamp=STAMP):
    result = literature.search_plan(paths, path, fetch, catalog.immutable_bytes, write_json, lambda: stamp)
    return result, json.loads((paths.data / result["path"]).read_text())


def query(**patch):
    result = {"query_id": "q1", "search_query": 'ti:"precise question"',
              "problem_ids": [PROBLEM], "max_results": 3}
    result.update(patch)
    return result


def test_zero_results_preserves_query_and_atom_but_makes_no_resolution_claim(paths):
    path = plan_path(paths, [query()])
    captured = []

    def fetch(endpoint, **kwargs):
        captured.append((endpoint, kwargs))
        return atom(), {"http_status": 200}

    _, result = run_plan(paths, path, fetch)
    item, = result["queries"]
    assert item["status"] == "no_results" and item["entries"] == []
    assert item["search_query"] == 'ti:"precise question"'
    assert (paths.artifacts / item["artifact_path"]).read_bytes() == atom()
    assert result["automatically_closes_problems"] is False
    params = parse_qs(urlsplit(captured[0][0]).query)
    assert params["search_query"] == ['ti:"precise question"']
    assert params["sortBy"] == ["lastUpdatedDate"]
    assert captured[0][1]["max_bytes"] == 8 * 1024 * 1024


def test_failed_rerun_preserves_successful_run_and_its_raw_evidence(paths):
    path = plan_path(paths, [query()])
    first, successful = run_plan(paths, path, lambda *a, **k: (atom("http://arxiv.org/abs/2609.01234v1"), {}))

    def failure(*args, **kwargs):
        raise OSError("fixture network unavailable")

    second, failed = run_plan(paths, path, failure, "2026-09-05T09:00:01.000002+00:00")
    assert first["path"] != second["path"]
    assert json.loads((paths.data / first["path"]).read_text()) == successful
    item, = failed["queries"]
    assert item["status"] == "lookup_failed" and "unavailable" in item["error"]
    entry, = successful["queries"][0]["entries"]
    assert entry["relevance"] == "query_candidate_unassessed"
    assert entry["problem_ids"] == [PROBLEM]
    assert (paths.artifacts / entry["artifact_path"]).is_file()


def test_malformed_feed_failure_keeps_auditable_raw_artifact_and_provenance(paths):
    path = plan_path(paths, [query()])
    raw = b"<feed><malformed"
    _, result = run_plan(paths, path, lambda *a, **k: (raw, {"http_status": 200}))
    item, = result["queries"]
    assert item["status"] == "lookup_failed"
    assert item["provenance"]["http_status"] == 200
    assert (paths.artifacts / item["artifact_path"]).read_bytes() == raw


def test_arxiv_error_atom_is_a_lookup_failure_not_a_zero_result(paths):
    path = plan_path(paths, [query()])
    raw = atom("http://arxiv.org/api/errors#incorrect_id_format_for_1234")
    _, result = run_plan(paths, path, lambda *a, **k: (raw, {"http_status": 200}))
    item, = result["queries"]
    assert item["status"] == "lookup_failed"
    assert "error" in item


def test_non_atom_xml_response_is_a_lookup_failure_not_a_zero_result(paths):
    path = plan_path(paths, [query()])
    raw = b"<html><body>Temporary service unavailable</body></html>"
    _, result = run_plan(paths, path, lambda *a, **k: (raw, {"http_status": 200}))
    item, = result["queries"]
    assert item["status"] == "lookup_failed"
    assert (paths.artifacts / item["artifact_path"]).read_bytes() == raw


def test_versioned_exact_id_is_not_falsely_reported_missing(paths):
    path = plan_path(paths, [query(id_list=["2609.01234v2"])])
    _, result = run_plan(paths, path, lambda *a, **k: (atom("http://arxiv.org/abs/2609.01234v2"), {}))
    assert result["queries"][0]["missing_ids"] == []


def test_different_returned_version_does_not_satisfy_an_exact_version_request(paths):
    path = plan_path(paths, [query(id_list=["2609.01234v2"])])
    _, result = run_plan(paths, path, lambda *a, **k: (atom("http://arxiv.org/abs/2609.01234v1"), {}))
    assert result["queries"][0]["missing_ids"] == ["2609.01234v2"]


def test_rate_limit_applies_between_failed_and_successful_requests(paths, monkeypatch):
    path = plan_path(paths, [query(query_id="q1"), query(query_id="q2"), query(query_id="q3")])
    clock = {"t": 0.0}
    sleeps, starts = [], []
    monkeypatch.setattr(literature.time, "monotonic", lambda: clock["t"])

    def sleep(duration):
        sleeps.append(duration)
        clock["t"] += duration

    monkeypatch.setattr(literature.time, "sleep", sleep)

    def fetch(*args, **kwargs):
        starts.append(clock["t"])
        if len(starts) == 1:
            raise OSError("first request fails")
        return atom(), {}

    _, result = run_plan(paths, path, fetch)
    assert len(sleeps) == 2
    assert all(b - a >= 3.2 for a, b in zip(starts, starts[1:]))
    assert [q["status"] for q in result["queries"]] == ["lookup_failed", "no_results", "no_results"]


@pytest.mark.parametrize("invalid", [0, 101, -1, "3"])
def test_plan_rejects_invalid_result_bounds_before_any_network(paths, invalid):
    path = plan_path(paths, [query(max_results=invalid)])

    def forbidden_fetch(*args, **kwargs):
        pytest.fail("invalid query reached network")

    with pytest.raises(ValueError, match="1-100"):
        run_plan(paths, path, forbidden_fetch)


@pytest.fixture
def finite_refutation(paths):
    # Invoke the actual bounded fixed-graph implementation; never substitute a
    # mocked True result for verify_certificate. The fixture lives only in tmp.
    checker = module("check_rank_forest_counterexample")
    certificate = checker.make_certificate()
    relative = intake.ROOT / "intake-batches/evidence/round2-certificate.json"
    path = paths.data / relative
    write_json(path, certificate)
    evidence = {
        "protocol": "rank-forest-seymour-winkler-sudan-v1",
        "certificate_path": relative.as_posix(),
        "certificate_sha256": catalog.digest(path.read_bytes()),
        "checker_sha256": catalog.digest((TOOLS / "check_rank_forest_counterexample.py").read_bytes()),
    }
    assessment = review(problem_id=RANK_MOTHER, local_refutation_evidence=evidence,
        scientific_status_review={"status": "refuted", "checked_at": STAMP,
                                  "evidence": [relative.as_posix()]})
    return path, certificate, assessment


def rank_fixture_records():
    problems, statements, records = fixture_records()
    rank_problem = problems.pop(PROBLEM)
    rank_problem["record_id"] = RANK_MOTHER
    rank_problem["metadata"]["entity_id"] = "rank-conditioned-graphic-forest-rayleigh"
    problems[RANK_MOTHER] = rank_problem
    statements[STATEMENT]["metadata"]["problem_id"] = RANK_MOTHER
    return problems, statements, records


def test_correct_finite_certificate_is_actually_replayed_not_just_hash_accepted(paths, finite_refutation):
    _, certificate, assessment = finite_refutation
    verified = catalog.verify_local_refutations(paths, [assessment])
    assert set(verified) == {RANK_MOTHER}
    assert verified[RANK_MOTHER]["verification"] == "exact_replay_of_published_counterexample"
    assert verified[RANK_MOTHER]["not_an_original_discovery"] is True
    assert certificate["enumeration"]["examined_subsets"] == 924
    assert certificate["counts"]["total"] == 384
    assert certificate["counts"]["e_present"] == 112
    assert certificate["counts"]["f_present"] == 272
    assert certificate["counts"]["both_present"] == 80
    assert certificate["rayleigh_difference_at_all_ones"] == -256


@pytest.mark.parametrize("mode", ["wrong_protocol", "wrong_mother", "certificate_hash", "checker_hash", "forged_counts_with_matching_hash"])
def test_finite_refutation_rejects_wrong_scope_hashes_and_mathematically_false_certificate(paths, finite_refutation, mode):
    path, certificate, assessment = finite_refutation
    evidence = assessment["local_refutation_evidence"]
    if mode == "wrong_protocol":
        evidence["protocol"] = "unrecognized-protocol"
    elif mode == "wrong_mother":
        assessment["problem_id"] = "math-catalog:problem:all-graph-weighted-forest-rayleigh"
    elif mode == "certificate_hash":
        evidence["certificate_sha256"] = "0" * 64
    elif mode == "checker_hash":
        evidence["checker_sha256"] = "0" * 64
    else:
        certificate["counts"]["both_present"] = 81
        write_json(path, certificate)
        # Even a self-consistent file hash cannot replace finite replay.
        evidence["certificate_sha256"] = catalog.digest(path.read_bytes())
    with pytest.raises(ValueError):
        catalog.verify_local_refutations(paths, [assessment])


def test_plain_review_cannot_self_declare_an_independently_verified_refutation(finite_refutation):
    _, _, assessment = finite_refutation
    assessment["scientific_status_review"]["local_exact_counterexample_replayed"] = True
    problems, statements, records = rank_fixture_records()
    catalog.apply_intake_reviews(problems, statements, records, [assessment])
    meta = problems[RANK_MOTHER]["metadata"]
    assert meta["scientific_status"] != "refuted"
    assert meta["local_research_status"] != "refuted"
    assert "verified_literature_counterexample" not in meta


def test_verified_exact_refutation_closes_only_the_correct_mother(paths, finite_refutation):
    _, _, assessment = finite_refutation
    verified = catalog.verify_local_refutations(paths, [assessment])
    problems, statements, records = rank_fixture_records()
    other = catalog.new_problem("all-graph-weighted-forest-rayleigh", "All-ranks-mixed forest mother", SOURCE, "open_in_source")
    original_other = deepcopy(other)
    problems[other["record_id"]] = other
    catalog.apply_intake_reviews(problems, statements, records, [assessment], verified_refutations=verified)
    meta = problems[RANK_MOTHER]["metadata"]
    assert meta["scientific_status"] == meta["local_research_status"] == "refuted"
    assert meta["verified_literature_counterexample"] == verified[RANK_MOTHER]
    assert other == original_other
    catalog.finalize_problem(problems[RANK_MOTHER], statements)
    assert not meta["selection_eligible"] and not meta["screening_eligible"]


@pytest.mark.parametrize("mode", ["pending_scope", "stale_pin", "missing_pins", "other_mother_mapping"])
def test_verified_certificate_still_requires_current_scope_and_binding_for_that_mother(paths, finite_refutation, mode):
    _, _, assessment = finite_refutation
    verified = catalog.verify_local_refutations(paths, [assessment])
    problems, statements, records = rank_fixture_records()
    if mode == "pending_scope":
        assessment["scope_review"] = "pending"
    elif mode == "stale_pin":
        statements[STATEMENT]["metadata"]["source_revision"] = "definitions changed"
    elif mode == "missing_pins":
        assessment.pop("require_statement_bindings")
        assessment.pop("statement_bindings")
    else:
        verified = {"math-catalog:problem:another-mother": verified[RANK_MOTHER]}
    catalog.apply_intake_reviews(problems, statements, records, [assessment], verified_refutations=verified)
    meta = problems[RANK_MOTHER]["metadata"]
    assert meta["scientific_status"] != "refuted"
    assert meta["local_research_status"] != "refuted"
    assert "verified_literature_counterexample" not in meta
    recorded = next(r for r in records.values() if r["kind"] == "math_review")
    assert recorded["metadata"]["does_not_certify_lean_or_close_problem"] is True


def test_evidence_and_status_updates_can_sort_before_the_batch_that_introduces_the_statement():
    problems, _, records = fixture_records()
    problems[PROBLEM]["metadata"]["statement_ids"] = []
    statements = {}
    evidence_update = {"statement_id": STATEMENT, "evidence": ["https://example.org/new-source"]}
    status_update = {"statement_id": STATEMENT, "status": "solved_in_source",
                     "affects_entire_mother": False, "evidence": ["https://example.org/scoped-resolution"]}
    early = batch(batch_id="a-evidence-update", source_statement_evidence_updates=[evidence_update],
                  statement_observations=[status_update])
    later = batch(batch_id="z-original-statement", statements=[statement()])
    catalog.apply_batch_items([early, later], problems, statements, records)
    meta = statements[STATEMENT]["metadata"]
    assert meta["evidence_updates"][0]["evidence"] == evidence_update["evidence"]
    assert meta["evidence_updates"][0]["provenance"]["batch_id"] == "a-evidence-update"
    assert meta["status_review_observations"] == [status_update]
    assert problems[PROBLEM]["metadata"]["scientific_status"] == "open_in_source"
