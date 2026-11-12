"""URL reuse within a run and evidence parts for one oversized passage."""
import json
from pathlib import Path

import httpx
import pytest

from paper_writing import formal_checks as formal

from tests.test_formal_checks import PRIMARY, ROLE, simulated_output

BODY = PRIMARY + " " + ("Documentation detail. " * 900)  # ~20 kB per source


def workspace(root, *, cite="s,t", printed_urls=False):
    manuscript = root / "papers/p/manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text(r"\begin{document}" + "\n\n" +
        r"For real $x$, $x^2\ge0$ by \cite{" + cite + "}." + "\n\n" + r"\end{document}")
    url = " https://publisher.example/{}." if printed_urls else ""
    (manuscript / "main.bbl").write_text(r"\begin{thebibliography}{2}"
        + r"\bibitem{s}Smith. Exact positivity. 2020." + url.format("s")
        + r"\bibitem{t}Taylor. Exact positivity again. 2021." + url.format("t")
        + r"\end{thebibliography}")
    return {"paper_id": "p", "version": "1.0", "manuscript_dir": "papers/p/manuscript",
            "formal_check": {"sources": [
                {"reference_keys": ["s"], "url": "https://publisher.example/s", "kind": "primary_text"},
                {"reference_keys": ["t"], "url": "https://publisher.example/t", "kind": "primary_text"}]}}


def http(monkeypatch, requests, body=BODY):
    def handler(request):
        requests.append(str(request.url))
        if request.url.host == "publisher.example":
            return httpx.Response(200, text=body, headers={"Content-Type": "text/plain"})
        return httpx.Response(404)
    client_class = httpx.Client
    monkeypatch.setattr(formal.httpx, "Client", lambda **kwargs: client_class(
        transport=httpx.MockTransport(handler), **kwargs))


def runner_factory(fail_key=None, packets=None):
    def runner(**kwargs):
        packet = json.loads(kwargs["user_prompt"])
        if packets is not None:
            packets.append(packet)
        output = simulated_output(packet)
        for row in output["passages"]:
            row["prerequisites"] = []
            for item in row["citations"]:
                own = [s for s in packet["retrieved_sources"] if item["key"] in s["reference_keys"]]
                item["evidence"] = [{"source_id": own[0]["id"], "locator": "Theorem 2",
                                     "quote": "for every real x, x squared is nonnegative"}]
                if item["key"] == fail_key:
                    item["status"] = "error"
                    row["status"] = "error"
        workdir = kwargs["workdir"]
        workdir.mkdir(parents=True)
        prompt = kwargs["system_prompt"] + "\n\n" + kwargs["user_prompt"]
        (workdir / "prompt.txt").write_text(prompt)
        (workdir / "system.txt").write_text(kwargs["system_prompt"])
        (workdir / "output.json").write_text(json.dumps(output))
        receipt = {"provider": ROLE["provider"], "model": ROLE["model"], "runtime_reported_models": [ROLE["model"]],
            "independent_context": True, "output_sha256": formal.sha((workdir / "output.json").read_bytes()),
            "prompt_sha256": formal.sha(prompt.encode()), "system_prompt_sha256": formal.sha(kwargs["system_prompt"].encode()),
            "schema_sha256": formal.sha(json.dumps(kwargs["schema"], sort_keys=True).encode())}
        (workdir / "receipt.json").write_text(json.dumps(receipt))
        return output, receipt
    return runner


def run(root, metadata, runner):
    directory = root / "reviews/p/run"
    directory.mkdir(parents=True)
    return formal.run_checks({"metadata": metadata}, root, directory, ROLE, 1, runner)


def test_same_url_is_fetched_once_and_reused(tmp_path, monkeypatch):
    metadata = workspace(tmp_path, printed_urls=True)
    requests = []
    http(monkeypatch, requests)
    docs, bib = formal.current_inputs(metadata, tmp_path)
    with formal.httpx.Client() as client:
        sources, errors = formal.collect_sources(formal.inventory(docs, bib), metadata, tmp_path,
                                                 tmp_path / "evidence", client)
    assert errors == []
    assert requests.count("https://publisher.example/s") == 1 and requests.count("https://publisher.example/t") == 1
    assert [s["kind"] for s in sources] == ["primary_text", "primary_text"]
    assert formal._normalized_url("HTTPS://Publisher.Example:443/s") == "https://publisher.example/s"


def test_oversized_passage_is_verified_in_evidence_parts(tmp_path, monkeypatch):
    monkeypatch.setattr(formal, "MAX_PACKET", 32_000)
    metadata = workspace(tmp_path)
    http(monkeypatch, [])
    packets = []
    binding = run(tmp_path, metadata, runner_factory(packets=packets))
    assert binding["valid"] is True, binding["blockers"]
    report = json.loads((tmp_path / binding["path"]).read_text())
    (pid, parts), = report["evidence_splits"].items()
    assert [p["citation_keys"] for p in parts] == [["s"], ["t"]]
    assert all(p["of"] == 2 and len(p["source_ids"]) == 1 for p in parts)
    passage_packets = [p for p in packets if p["scope"] == "passages"]
    assert len(passage_packets) == 2
    for packet, keys in zip(passage_packets, (["s"], ["t"])):
        item, = packet["items"]
        assert item["text"] == report["inventory"]["passages"][0]["text"]  # whole passage every time
        assert {c["key"] for c in item["citations"]} == set(keys)
        assert {k for s in packet["retrieved_sources"] for k in s["reference_keys"]} == set(keys)
        assert len(json.dumps(packet).encode()) <= formal.MAX_PACKET + 2000
    row, = report["report"]["passages"]
    assert row["status"] == "verified" and {c["key"] for c in row["citations"]} == {"s", "t"}
    assert formal.validate_binding(binding, metadata, tmp_path, ROLE) == []
    # The recorded partition is bound to the deterministic one.
    report["evidence_splits"][pid][0]["source_ids"] = []
    (tmp_path / binding["path"]).write_text(json.dumps(report))
    tampered = dict(binding, sha256=formal.sha((tmp_path / binding["path"]).read_bytes()))
    assert any("evidence parts" in b for b in formal.validate_binding(tampered, metadata, tmp_path, ROLE))


def test_one_failing_part_fails_the_passage(tmp_path, monkeypatch):
    monkeypatch.setattr(formal, "MAX_PACKET", 32_000)
    metadata = workspace(tmp_path)
    http(monkeypatch, [])
    binding = run(tmp_path, metadata, runner_factory(fail_key="t"))
    assert binding["valid"] is False
    report = json.loads((tmp_path / binding["path"]).read_text())
    row, = report["report"]["passages"]
    assert row["status"] == "error"


def test_merge_requires_every_part():
    rows = [{"passage_id": "P", "status": "verified", "coverage_rationale": "ok", "formulas": [],
             "citations": [{"citation_id": "c1", "key": "s"}], "prerequisites": []}]
    splits = {"P": [{"part": 1}, {"part": 2}]}
    merged, = formal.merge_evidence_parts(rows, splits)
    assert merged["status"] == "unchecked" and [c["key"] for c in merged["citations"]] == ["s"]


def test_single_source_over_budget_without_locator_stays_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(formal, "MAX_PACKET", 32_000)
    metadata = workspace(tmp_path, cite="s")
    http(monkeypatch, [], body=PRIMARY + " " + ("Documentation detail. " * 2000))  # ~44 kB, one source
    def unexpected(**kwargs):
        raise AssertionError("an oversized packet must not reach the verifier")
    binding = run(tmp_path, metadata, unexpected)
    assert binding["valid"] is False
    assert any("exceeds the context budget" in b for b in binding["blockers"])


def test_pdf_text_is_extracted_in_reading_order(tmp_path, monkeypatch):
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        Path(command[-1]).write_text("Column one sentence continues here. Column two.")
        class Done:
            returncode = 0
        return Done()
    from pathlib import Path
    monkeypatch.setattr(formal.subprocess, "run", fake_run)
    text = formal._text_document(b"%PDF-1.4 fixture", "application/pdf", tmp_path, "S1")
    assert calls and "-layout" not in calls[0] and calls[0][0] == "pdftotext"
    assert "Column one sentence continues here." in text
