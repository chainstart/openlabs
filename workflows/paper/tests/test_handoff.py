import json
import subprocess
import zipfile
from pathlib import Path

import httpx
import pytest

from paper_writing.handoff import (
    HandoffError,
    ManageApiClient,
    _paper_projection,
    build_handoff_package,
    build_writing_projection,
    changed_registry_paper_ids,
    execute_ready_handoff_plan,
    load_handoff_manifest,
    manuscript_review_content_sha256,
    manuscript_snapshot_sha256,
    plan_ready_handoffs,
    sync_writing_metadata_batch,
    validate_release_preconditions,
)


def test_review_content_fingerprint_ignores_only_preamble_author_metadata(
    tmp_path: Path,
) -> None:
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    main = manuscript / "main.tex"
    pdf = manuscript / "main.pdf"
    bibliography = manuscript / "references.bib"
    main.write_text(
        """\\documentclass{article}
\\title{A physical result}
\\author[a]{First Author}
\\affiliation[a]{First Institute}
\\emailAdd{first@example.test}
\\begin{document}
The invariant is $E=mc^2$.
\\noindent\\textbf{Author contributions.}
First Author performed the analysis.
\\noindent\\textbf{Funding.}
No external funding.
\\end{document}
""",
        encoding="utf-8",
    )
    bibliography.write_text("@article{x, title={Evidence}}\n", encoding="utf-8")
    pdf.write_bytes(b"%PDF original")
    review_digest = manuscript_review_content_sha256(manuscript, pdf)
    full_digest = manuscript_snapshot_sha256(manuscript, pdf)

    main.write_text(
        """\\documentclass{article}
\\title{A physical result}
\\author[a]{First Author}
\\affiliation[a]{First Institute}
\\author[b]{Second Author}
\\affiliation[b]{Second Institute}
\\emailAdd{second@example.test}
\\note{Corresponding author}
\\begin{document}
The invariant is $E=mc^2$.
\\noindent\\textbf{Author contributions.}
First and Second Author performed the analysis. Correspondence: Second Author.
\\noindent\\textbf{Funding.}
No external funding.
\\end{document}
""",
        encoding="utf-8",
    )
    pdf.write_bytes(b"%PDF rebuilt with new author list")
    assert manuscript_review_content_sha256(manuscript, pdf) == review_digest
    assert manuscript_snapshot_sha256(manuscript, pdf) != full_digest

    main.write_text(
        main.read_text(encoding="utf-8").replace("E=mc^2", "E=0"),
        encoding="utf-8",
    )
    assert manuscript_review_content_sha256(manuscript, pdf) != review_digest

    main.write_text(
        main.read_text(encoding="utf-8").replace("E=0", "E=mc^2"),
        encoding="utf-8",
    )
    bibliography.write_text("@article{x, title={Different evidence}}\n", encoding="utf-8")
    assert manuscript_review_content_sha256(manuscript, pdf) != review_digest


def test_manuscript_fingerprints_ignore_generated_spl(tmp_path: Path) -> None:
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    (manuscript / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}Result\\end{document}\n",
        encoding="utf-8",
    )
    pdf = manuscript / "main.pdf"
    pdf.write_bytes(b"%PDF stable")
    snapshot = manuscript_snapshot_sha256(manuscript, pdf)
    review_content = manuscript_review_content_sha256(manuscript, pdf)

    generated = manuscript / "main.spl"
    generated.write_text("generated front-matter scratch data\n", encoding="utf-8")

    assert manuscript_snapshot_sha256(manuscript, pdf) == snapshot
    assert manuscript_review_content_sha256(manuscript, pdf) == review_content


def test_paper_projection_only_clears_an_explicit_target_journal() -> None:
    base = {"title": "Test", "version": "1.0.0"}

    assert "target_journal" not in _paper_projection(
        "20260721aillm0001", base, origin_commit="a" * 40
    )
    assert _paper_projection(
        "20260721aillm0001",
        {**base, "target_journal": None},
        origin_commit="a" * 40,
    )["target_journal"] is None


def test_writing_projection_exposes_simulated_reviews_and_quality_gate() -> None:
    projection = build_writing_projection(
        "20260805-math-graph-reviewed-paper",
        {
            "title": "Reviewed graph paper",
            "ara_llm_self_review": {
                "scores": {
                    "clarity": 7,
                    "soundness": 6,
                    "significance": 5,
                    "novelty": 5,
                    "overall": 6,
                },
                "reviewer_role": "math",
                "rubric_id": "ara.paper-writing.math-four-journals.v1",
                "high_standard_view": "four_top_math_journals",
                "high_standard_decision": "reject",
                "high_standard_confidence": "high",
                "cas_zone_1_decision": "minor_revision",
                "cas_zone_1_confidence": "medium",
                "cas_zone_1_basis": {"scope": "major_category"},
                "reviewed_at": "2026-08-05T00:00:00Z",
                "source": "reviews/example/review.json",
            },
            "writing_release": {
                "status": "revision_required",
                "target_score": 6.0,
                "score": 6,
                "decision_standard": "cas_zone_1_journal",
                "decision": "minor_revision",
                "minimum_decision": "minor_revision",
                "revision_rounds_completed": 2,
                "max_revision_rounds": 3,
                "unresolved_review_blockers": ["Resolve evidence mismatch."],
            },
        },
        origin_commit="a" * 40,
    )

    review = projection["internal_review"]
    assert review["simulated_venue_decisions"] is True
    assert review["not_external_peer_review"] is True
    assert review["high_standard"] == {
        "view": "four_top_math_journals",
        "decision": "reject",
        "confidence": "high",
    }
    assert review["cas_zone_1_journal"]["decision"] == "minor_revision"
    assert review["scores"]["overall"] == 6
    gate = projection["llm_revision"]
    assert projection["display_id"] == "20260805-math-graph-reviewed-paper"
    assert gate["target_score"] == 6.0
    assert gate["decision_standard"] == "cas_zone_1_journal"
    assert gate["minimum_decision"] == "minor_revision"
    assert gate["unresolved_review_blockers"] == ["Resolve evidence mismatch."]


def test_build_handoff_contains_sources_images_and_pdf(tmp_path: Path) -> None:
    paper_id = "20260721aillm0001"
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    figures = manuscript / "figures"
    figures.mkdir(parents=True)
    (manuscript / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
    (manuscript / "main.aux").write_text("generated", encoding="utf-8")
    (manuscript / "main.spl").write_text("generated", encoding="utf-8")
    (manuscript / "main.pdf").write_bytes(b"%PDF-1.4 test")
    (manuscript / "main.zh.pdf").write_bytes(b"%PDF-1.4 translated output")
    (manuscript / "cover_letter.pdf").write_bytes(b"%PDF-1.4 cover letter")
    (figures / "result.png").write_bytes(b"png")
    (figures / "result.pdf").write_bytes(b"%PDF-1.4 figure")
    supplement = manuscript / "supplement"
    supplement.mkdir()
    (supplement / "data.zip").write_bytes(b"support artifact")
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    paper_registry = registry / f"{paper_id}.yaml"
    paper_registry.write_text(
        f"""paper_id: {paper_id}
title: Test
version: 1.2.3
created_at: 2026-07-21
domain: ai
subdomain: llm
display_id: 20260721-ai-llm-reliability-audit
work_id: erdos866-pairwise-sum-bounds
target_journal: Acta Arithmetica
target_journal_section: Combinatorial Number Theory
manuscript_dir: papers/{paper_id}/manuscript
latest_pdf: papers/{paper_id}/manuscript/main.pdf
authors:
  - name: Test Author
    email: private@example.edu
""",
        encoding="utf-8",
    )

    package_dir = tmp_path / "dist"
    result = build_handoff_package(
        paper_id,
        root=tmp_path,
        output=package_dir,
        revision_request_id="rrq_example",
    )
    with zipfile.ZipFile(package_dir / "source.zip") as archive:
        assert archive.namelist() == [
            "figures/result.pdf",
            "figures/result.png",
            "main.tex",
        ]
    assert result["revision_request_id"] == "rrq_example"
    assert result["schema_version"] == "ara.paper_writing.handoff.v2"
    assert result["paper"]["writing_metadata"]["authors"]["names"] == ["Test Author"]
    assert "email" not in result["paper"]["writing_metadata"]["authors"]["people"][0]
    assert result["paper"]["target_journal"] == "Acta Arithmetica"
    assert result["paper"]["writing_metadata"]["work_id"] == (
        "erdos866-pairwise-sum-bounds"
    )
    assert result["paper"]["writing_metadata"]["display_id"] == (
        "20260721-ai-llm-reliability-audit"
    )
    assert result["paper"]["writing_metadata"]["target_journal"] == {
        "name": "Acta Arithmetica",
        "section": "Combinatorial Number Theory",
        "source": "ara-paper-writing registry",
    }
    assert result["source"]["file_count"] == 3
    assert result["source"]["path"] == "source.zip"
    assert result["pdf"]["path"] == "paper.pdf"
    loaded = load_handoff_manifest(package_dir / "handoff.json")
    assert loaded["package_id"] == result["package_id"]
    assert loaded["source"]["path"] == str((package_dir / "source.zip").resolve())
    assert loaded["pdf"]["path"] == str((package_dir / "paper.pdf").resolve())


def test_handoff_manifest_detects_modified_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    pdf = tmp_path / "paper.pdf"
    source.write_bytes(b"source")
    pdf.write_bytes(b"pdf")
    manifest = {
        "schema_version": "ara.paper_writing.handoff.v1",
        "source": {"path": source.name, "sha256": "0" * 64},
        "pdf": {"path": pdf.name, "sha256": "0" * 64},
    }
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        load_handoff_manifest(path)
    except Exception as error:
        assert "SHA-256" in str(error)
    else:
        raise AssertionError("modified artifact should fail validation")


def test_signed_upload_normalizes_cloudbase_gateway_path(tmp_path: Path) -> None:
    artifact = tmp_path / "source.zip"
    artifact.write_bytes(b"source")

    def upload(request: httpx.Request) -> httpx.Response:
        assert request.url.path == (
            "/v1/storages/object/upload/sign/ara-paper-artifacts/"
            "papers/example/source.zip"
        )
        assert request.url.params["token"] == "signed-token"
        assert request.headers["content-length"] == str(artifact.stat().st_size)
        assert request.read() == b"source"
        return httpx.Response(200, json={"Key": "papers/example/source.zip"})

    http_client = httpx.Client(transport=httpx.MockTransport(upload))
    try:
        client = ManageApiClient(
            "https://manage.example",
            "ara_test_secret",
            client=http_client,
        )
        client._put_signed(
            {
                "fullSignedURL": (
                    "https://env.api.tcloudbasegateway.com/"
                    "v1/storages/v1/storages/object/upload/sign/"
                    "ara-paper-artifacts/papers/example/source.zip"
                    "?token=signed-token"
                )
            },
            artifact,
            "application/zip",
        )
    finally:
        http_client.close()


def _upload_manifest(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "source.zip"
    pdf = tmp_path / "paper.pdf"
    source.write_bytes(b"source")
    pdf.write_bytes(b"pdf")
    return {
        "paper_id": "20260721aillm0001",
        "package_id": "pkg_example",
        "version": "1.0.0",
        "origin_repository": "chainstart/ara-paper-writing",
        "origin_commit": "a" * 40,
        "release": {"status": "ready", "score": 7, "target_score": 6},
        "source": {
            "path": str(source),
            "sha256": "b" * 64,
            "size": source.stat().st_size,
        },
        "pdf": {
            "path": str(pdf),
            "sha256": "c" * 64,
            "size": pdf.stat().st_size,
        },
    }


def _signed_uploads(registration: int) -> dict[str, object]:
    return {
        "data": {
            "upload": {
                "source": {
                    "url": (
                        "https://storage.example/upload/source"
                        f"?token=source-{registration}"
                    )
                },
                "pdf": {
                    "url": (
                        "https://storage.example/upload/pdf"
                        f"?token=pdf-{registration}"
                    )
                },
            }
        }
    }


def _expired_upload_response() -> httpx.Response:
    return httpx.Response(
        401,
        json={
            "code": "STORAGE_INVALID_JWT",
            "message": "token has invalid claims: token is expired",
        },
    )


def _aborted_upload_response() -> httpx.Response:
    return httpx.Response(
        400,
        json={
            "code": "STORAGE_ABORTED",
            "message": "socket connection timed out before storage completed",
        },
    )


def test_manage_client_resigns_expired_source_upload_once(tmp_path: Path) -> None:
    manifest = _upload_manifest(tmp_path)
    registrations = 0
    registration_keys: list[str] = []
    upload_tokens: list[str] = []

    def api(request: httpx.Request) -> httpx.Response:
        nonlocal registrations
        if request.method == "POST" and request.url.path.endswith("/packages"):
            registrations += 1
            registration_keys.append(request.headers["idempotency-key"])
            return httpx.Response(200, json=_signed_uploads(registrations))
        if request.method == "PUT":
            token = request.url.params["token"]
            upload_tokens.append(token)
            if token == "source-1":
                return _expired_upload_response()
            return httpx.Response(200, json={"uploaded": True})
        if request.method == "POST" and request.url.path.endswith("/complete"):
            return httpx.Response(
                200,
                json={"data": {"package_id": "pkg_example", "status": "ready"}},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example", "ara_test_secret", client=http_client
        )
        result = client.push_package(manifest)
    finally:
        http_client.close()

    assert result["status"] == "ready"
    assert registrations == 2
    assert registration_keys == [
        "package:pkg_example:register",
        "package:pkg_example:register",
    ]
    assert upload_tokens == ["source-1", "source-2", "pdf-2"]


def test_manage_client_resigns_aborted_source_upload_once(tmp_path: Path) -> None:
    manifest = _upload_manifest(tmp_path)
    registrations = 0
    upload_tokens: list[str] = []

    def api(request: httpx.Request) -> httpx.Response:
        nonlocal registrations
        if request.method == "POST" and request.url.path.endswith("/packages"):
            registrations += 1
            return httpx.Response(200, json=_signed_uploads(registrations))
        if request.method == "PUT":
            token = request.url.params["token"]
            upload_tokens.append(token)
            if token == "source-1":
                return _aborted_upload_response()
            return httpx.Response(200, json={"uploaded": True})
        if request.method == "POST" and request.url.path.endswith("/complete"):
            return httpx.Response(
                200,
                json={"data": {"package_id": "pkg_example", "status": "ready"}},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example", "ara_test_secret", client=http_client
        )
        result = client.push_package(manifest)
    finally:
        http_client.close()

    assert result["status"] == "ready"
    assert registrations == 2
    assert upload_tokens == ["source-1", "source-2", "pdf-2"]


def test_manage_client_resigns_only_pdf_after_source_upload(tmp_path: Path) -> None:
    manifest = _upload_manifest(tmp_path)
    registrations = 0
    upload_tokens: list[str] = []

    def api(request: httpx.Request) -> httpx.Response:
        nonlocal registrations
        if request.method == "POST" and request.url.path.endswith("/packages"):
            registrations += 1
            response = _signed_uploads(registrations)
            if registrations == 2:
                response["data"]["upload"]["source"] = None
            return httpx.Response(200, json=response)
        if request.method == "PUT":
            token = request.url.params["token"]
            upload_tokens.append(token)
            if token == "pdf-1":
                return _expired_upload_response()
            return httpx.Response(200, json={"uploaded": True})
        if request.method == "POST" and request.url.path.endswith("/complete"):
            return httpx.Response(
                200,
                json={"data": {"package_id": "pkg_example", "status": "ready"}},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example", "ara_test_secret", client=http_client
        )
        result = client.push_package(manifest)
    finally:
        http_client.close()

    assert result["status"] == "ready"
    assert registrations == 2
    assert upload_tokens == ["source-1", "pdf-1", "pdf-2"]


def test_manage_client_skips_server_verified_existing_uploads(tmp_path: Path) -> None:
    manifest = _upload_manifest(tmp_path)
    upload_tokens: list[str] = []

    def api(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/packages"):
            response = _signed_uploads(1)
            response["data"]["upload"]["source"] = None
            return httpx.Response(200, json=response)
        if request.method == "PUT":
            upload_tokens.append(request.url.params["token"])
            return httpx.Response(200, json={"uploaded": True})
        if request.method == "POST" and request.url.path.endswith("/complete"):
            return httpx.Response(
                200,
                json={"data": {"package_id": "pkg_example", "status": "ready"}},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example", "ara_test_secret", client=http_client
        )
        result = client.push_package(manifest)
    finally:
        http_client.close()

    assert result["status"] == "ready"
    assert upload_tokens == ["pdf-1"]


def test_manage_client_accepts_verified_upload_after_expired_response(
    tmp_path: Path,
) -> None:
    manifest = _upload_manifest(tmp_path)
    registrations = 0
    upload_tokens: list[str] = []

    def api(request: httpx.Request) -> httpx.Response:
        nonlocal registrations
        if request.method == "POST" and request.url.path.endswith("/packages"):
            registrations += 1
            response = _signed_uploads(registrations)
            if registrations == 2:
                response["data"]["upload"]["source"] = None
            return httpx.Response(200, json=response)
        if request.method == "PUT":
            upload_tokens.append(request.url.params["token"])
            if request.url.params["token"] == "source-1":
                return _expired_upload_response()
            return httpx.Response(200, json={"uploaded": True})
        if request.method == "POST" and request.url.path.endswith("/complete"):
            return httpx.Response(
                200,
                json={"data": {"package_id": "pkg_example", "status": "ready"}},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example", "ara_test_secret", client=http_client
        )
        result = client.push_package(manifest)
    finally:
        http_client.close()

    assert result["status"] == "ready"
    assert registrations == 2
    assert upload_tokens == ["source-1", "pdf-2"]


def test_manage_client_stops_after_one_resign_for_an_artifact(tmp_path: Path) -> None:
    manifest = _upload_manifest(tmp_path)
    registrations = 0
    upload_tokens: list[str] = []

    def api(request: httpx.Request) -> httpx.Response:
        nonlocal registrations
        if request.method == "POST" and request.url.path.endswith("/packages"):
            registrations += 1
            return httpx.Response(200, json=_signed_uploads(registrations))
        if request.method == "PUT":
            upload_tokens.append(request.url.params["token"])
            return _expired_upload_response()
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example", "ara_test_secret", client=http_client
        )
        with pytest.raises(HandoffError, match="token is expired"):
            client.push_package(manifest)
    finally:
        http_client.close()

    assert registrations == 2
    assert upload_tokens == ["source-1", "source-2"]


def test_manage_client_does_not_resign_other_upload_failures(tmp_path: Path) -> None:
    manifest = _upload_manifest(tmp_path)
    registrations = 0

    def api(request: httpx.Request) -> httpx.Response:
        nonlocal registrations
        if request.method == "POST" and request.url.path.endswith("/packages"):
            registrations += 1
            return httpx.Response(200, json=_signed_uploads(registrations))
        if request.method == "PUT":
            return httpx.Response(
                401,
                json={
                    "code": "STORAGE_INVALID_JWT",
                    "message": "token signature is invalid",
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example", "ara_test_secret", client=http_client
        )
        with pytest.raises(HandoffError, match="signature is invalid"):
            client.push_package(manifest)
    finally:
        http_client.close()

    assert registrations == 1


def test_release_requires_current_gate_and_git_frozen_snapshot(tmp_path: Path) -> None:
    paper_id = "20260721aillm0001"
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    manuscript.mkdir(parents=True)
    source = manuscript / "main.tex"
    pdf = manuscript / "main.pdf"
    source.write_text("\\documentclass{article}", encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.4 frozen")
    snapshot = manuscript_snapshot_sha256(manuscript, pdf)
    cache = manuscript / "figures" / "__pycache__" / "figure.cpython-312.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"generated bytecode must not affect the manuscript snapshot")
    assert manuscript_snapshot_sha256(manuscript, pdf) == snapshot
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (tmp_path / "registry" / "settings.yaml").write_text(
        """schema_version: ara.paper_writing.registry.v1
quality_gate:
  minimum_score: 6.0
  maximum_revision_rounds: 3
  decision_standard: cas_zone_1_journal
  cas_zone_1_minimum_decision: minor_revision
  conference_minimum_decision: weak_accept
  journal_minimum_decision: minor_revision
""",
        encoding="utf-8",
    )
    paper_registry = registry / f"{paper_id}.yaml"
    paper_registry.write_text(
        f"""paper_id: {paper_id}
title: Frozen paper
version: 1.0.0
manuscript_dir: papers/{paper_id}/manuscript
latest_pdf: papers/{paper_id}/manuscript/main.pdf
writing_release:
  status: ready
  target_score: 6.0
  score: 6.0
  venue_type: journal
  decision_standard: cas_zone_1_journal
  decision: minor_revision
  reviewed_at: '2026-08-03T00:00:00+00:00'
  manuscript_snapshot_sha256: {snapshot}
  manuscript_version: 1.0.0
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "registry", "papers"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "freeze paper",
        ],
        cwd=tmp_path,
        check=True,
    )

    result = validate_release_preconditions(paper_id, root=tmp_path)
    assert result["score"] == 6.0
    assert result["manuscript_snapshot_sha256"] == snapshot

    class FakeManageClient:
        base_url = "https://manage.example"

        def __init__(self):
            self.sync_calls = 0
            self.push_calls = 0
            self.synced_targets = []

        def sync_paper(self, manifest):
            self.sync_calls += 1
            self.synced_targets.append(manifest["paper"].get("target_journal"))
            assert manifest["paper"]["paper_id"] == paper_id
            return {"paper_id": paper_id, "lifecycle_status": "backlog"}

        def push_package(self, manifest):
            self.push_calls += 1
            assert Path(manifest["source"]["path"]).is_file()
            assert Path(manifest["pdf"]["path"]).is_file()
            return {"package_id": manifest["package_id"], "status": "ready"}

    client = FakeManageClient()
    initial_plan = plan_ready_handoffs([paper_id], root=tmp_path)
    assert initial_plan["errors"] == []
    assert initial_plan["pending"][0]["paper_id"] == paper_id
    synchronized = execute_ready_handoff_plan(
        initial_plan,
        root=tmp_path,
        client=client,
    )
    assert synchronized["ok"] is True
    assert synchronized["released"][0]["manage_package_status"] == "ready"
    assert Path(synchronized["released"][0]["receipt"]).is_file()

    updated_registry = paper_registry.read_text(encoding="utf-8").replace(
        "  score: 6.0\n", "  score: 7.0\n", 1
    )
    paper_registry.write_text(
        updated_registry + "target_journal: Acta Arithmetica\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(paper_registry)], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "select target journal",
        ],
        cwd=tmp_path,
        check=True,
    )

    retry_plan = plan_ready_handoffs([paper_id], root=tmp_path)
    assert retry_plan["errors"] == []
    assert retry_plan["pending"][0]["mode"] == "metadata_only"
    retry = execute_ready_handoff_plan(retry_plan, root=tmp_path, client=client)
    assert retry["ok"] is True
    assert retry["released"] == []
    assert retry["metadata_synced"][0]["paper_id"] == paper_id
    assert client.sync_calls == 2
    assert client.push_calls == 1
    assert client.synced_targets == [None, "Acta Arithmetica"]

    source.write_text("\\documentclass{book}", encoding="utf-8")
    with pytest.raises(HandoffError, match="changed after the quality review"):
        validate_release_preconditions(paper_id, root=tmp_path)


def test_release_rejects_gate_from_pre_cas_decision_standard(tmp_path: Path) -> None:
    paper_id = "20260804aillm0001"
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (tmp_path / "registry" / "settings.yaml").write_text(
        """schema_version: ara.paper_writing.registry.v1
quality_gate:
  minimum_score: 6.0
  decision_standard: cas_zone_1_journal
  cas_zone_1_minimum_decision: minor_revision
""",
        encoding="utf-8",
    )
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
writing_release:
  status: ready
  target_score: 6.0
  score: 7.0
  venue_type: conference
  decision: weak_accept
""",
        encoding="utf-8",
    )

    with pytest.raises(HandoffError, match="stale decision standard"):
        validate_release_preconditions(paper_id, root=tmp_path)


def test_changed_registry_paper_ids_ignores_non_registry_commits(tmp_path: Path) -> None:
    paper_id = "20260721aillm0001"
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    paper = registry / f"{paper_id}.yaml"
    paper.write_text(
        f"paper_id: {paper_id}\nwriting_release:\n  status: draft\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        cwd=tmp_path,
        check=True,
    )
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    assert changed_registry_paper_ids(root=tmp_path, base="0" * 40, head=base) == [
        paper_id
    ]

    paper.write_text(
        f"paper_id: {paper_id}\nwriting_release:\n  status: ready\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(paper)], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "pass gate",
        ],
        cwd=tmp_path,
        check=True,
    )
    gated = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    assert changed_registry_paper_ids(root=tmp_path, base=base, head=gated) == [paper_id]

    (tmp_path / "README.md").write_text("documentation only\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "docs",
        ],
        cwd=tmp_path,
        check=True,
    )
    documented = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    assert changed_registry_paper_ids(root=tmp_path, base=gated, head=documented) == []


def test_changed_registry_paper_ids_accepts_descriptive_ids(tmp_path: Path) -> None:
    paper_id = "20260802-math-graph-opg1757-active-newton"
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    paper = registry / f"{paper_id}.yaml"
    paper.write_text(
        f"paper_id: {paper_id}\nwriting_release:\n  status: draft\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "add descriptive paper",
        ],
        cwd=tmp_path,
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert changed_registry_paper_ids(root=tmp_path, base="0" * 40, head=head) == [
        paper_id
    ]


def test_manage_client_syncs_projection_and_release_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    pdf = tmp_path / "paper.pdf"
    source.write_bytes(b"source")
    pdf.write_bytes(b"pdf")
    seen: list[tuple[str, str, dict[str, object]]] = []

    def api(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read()) if request.content else {}
        seen.append((request.method, request.url.path, body))
        if request.method == "POST" and request.url.path == "/v1/papers":
            return httpx.Response(200, json={"data": {"paper_id": body["paper_id"]}})
        if request.method == "PATCH":
            return httpx.Response(200, json={"data": {"paper_id": "20260721aillm0001"}})
        if request.url.path.endswith("/complete"):
            return httpx.Response(
                200,
                json={"data": {"package_id": "pkg_example", "status": "ready"}},
            )
        return httpx.Response(200, json={"data": {"upload": None}})

    manifest = {
        "paper_id": "20260721aillm0001",
        "package_id": "pkg_example",
        "version": "1.0.0",
        "origin_repository": "chainstart/ara-paper-writing",
        "origin_commit": "a" * 40,
        "paper": {
            "paper_id": "20260721aillm0001",
            "title": "Test paper",
            "writing_metadata": {"self_review": {"score": 7}},
        },
        "release": {"status": "ready", "score": 7, "target_score": 6},
        "source": {
            "path": str(source),
            "sha256": "b" * 64,
            "size": source.stat().st_size,
        },
        "pdf": {
            "path": str(pdf),
            "sha256": "c" * 64,
            "size": pdf.stat().st_size,
        },
    }
    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient("https://manage.example", "ara_test_secret", client=http_client)
        client.sync_paper(manifest)
        result = client.push_package(manifest)
    finally:
        http_client.close()

    assert result["status"] == "ready"
    assert seen[0][0:2] == ("POST", "/v1/papers")
    assert seen[1][0:2] == ("PATCH", "/v1/papers/20260721aillm0001")
    package_call = next(item for item in seen if item[1].endswith("/packages"))
    assert package_call[2]["release_metadata"] == manifest["release"]


def test_manage_client_writing_projection_only_patches_existing_paper() -> None:
    seen: list[tuple[str, str, dict[str, object], str | None]] = []

    def api(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read()) if request.content else {}
        seen.append(
            (
                request.method,
                request.url.path,
                body,
                request.headers.get("Idempotency-Key"),
            )
        )
        return httpx.Response(
            200,
            json={"data": {"paper_id": "20260721aillm0001", "lifecycle_status": "closed"}},
        )

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example", "ara_test_secret", client=http_client
        )
        result = client.sync_writing_projection(
            "20260721aillm0001",
            {
                "paper_id": "20260721aillm0001",
                "title": "Reviewed paper",
                "writing_metadata": {"self_review": {"score": 6}},
            },
            origin_commit="a" * 40,
        )
    finally:
        http_client.close()

    assert result is not None
    assert result["lifecycle_status"] == "closed"
    assert seen[0][0:2] == ("PATCH", "/v1/papers/20260721aillm0001")
    assert seen[0][2]["writing_metadata"]["self_review"]["score"] == 6
    assert seen[0][3] is not None and ":writing:" in seen[0][3]


def test_manage_client_retries_idempotent_transport_failures() -> None:
    attempts = 0

    def api(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectTimeout("temporary route failure", request=request)
        return httpx.Response(
            200,
            json={"data": {"paper_id": "20260721aillm0001"}},
        )

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example",
            "ara_test_secret",
            client=http_client,
            retry_delays=(0.0, 0.0),
        )
        result = client.sync_writing_projection(
            "20260721aillm0001",
            {
                "paper_id": "20260721aillm0001",
                "title": "Reviewed paper",
            },
            origin_commit="a" * 40,
        )
    finally:
        http_client.close()

    assert result is not None
    assert attempts == 3


def test_manage_client_bounds_idempotent_transport_retries() -> None:
    attempts = 0

    def api(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectTimeout("route unavailable", request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(api))
    try:
        client = ManageApiClient(
            "https://manage.example",
            "ara_test_secret",
            client=http_client,
            retry_delays=(0.0, 0.0),
        )
        with pytest.raises(HandoffError, match="after 3 attempt"):
            client.sync_writing_projection(
                "20260721aillm0001",
                {
                    "paper_id": "20260721aillm0001",
                    "title": "Reviewed paper",
                },
                origin_commit="a" * 40,
            )
    finally:
        http_client.close()

    assert attempts == 3


def test_sync_writing_metadata_allows_non_ready_gate_but_requires_git_clean(
    tmp_path: Path,
) -> None:
    paper_id = "20260721aillm0001"
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    paper = registry / f"{paper_id}.yaml"
    paper.write_text(
        f"""paper_id: {paper_id}
title: Reviewed paper
version: 1.0.0
writing_release:
  status: revision_required
  score: 4
  decision: reject
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "registry"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "record review",
        ],
        cwd=tmp_path,
        check=True,
    )

    class FakeManageClient:
        def sync_writing_projection(self, candidate, projection, *, origin_commit):
            assert candidate == paper_id
            assert projection["writing_metadata"]["self_review"]["score"] == 4
            assert len(origin_commit) == 40
            return {"paper_id": paper_id, "lifecycle_status": "ready_to_submit"}

    result = sync_writing_metadata_batch(
        [paper_id], root=tmp_path, client=FakeManageClient()
    )
    assert result["ok"] is True
    assert result["synchronized"][0]["score"] == 4

    paper.write_text(paper.read_text(encoding="utf-8") + "subdomain: llm\n", encoding="utf-8")
    dirty = sync_writing_metadata_batch(
        [paper_id], root=tmp_path, client=FakeManageClient()
    )
    assert dirty["ok"] is False
    assert "differs from Git HEAD" in dirty["errors"][0]["error"]
