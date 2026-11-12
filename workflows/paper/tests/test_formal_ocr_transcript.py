"""A registered OCR transcription of a scanned original PDF as primary evidence."""
import hashlib

import httpx
import pytest

from paper_writing import formal_checks as formal

from tests.test_formal_checks import fixture_workspace

SCAN = b"%PDF-1.4\n% scanned pages without a text layer\n%%EOF\n"
TEXT = ("[OCR transcription of original PDF pages 1-2; RapidOCR; not the publisher's text layer]\n"
        "Theorem 2: for every real x, x squared is nonnegative.\n")


def setup(root, *, text=TEXT, original=SCAN, **overrides):
    metadata = fixture_workspace(root)
    path = root / "papers/p/evidence/ocr.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    source = {"reference_keys": ["s"], "url": "https://publisher.example/original.pdf", "kind": "primary_text",
              "pages": [1, 2], "extraction_method": "ocr_transcript",
              "transcript": {"path": "papers/p/evidence/ocr.txt", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "original_sha256": hashlib.sha256(original).hexdigest(),
                             "tool": "rapidocr-onnxruntime", "tool_version": "1.0"}}
    source.update(overrides)
    metadata["formal_check"]["sources"] = [source]
    return metadata


def collect(root, metadata, body=SCAN):
    def handler(request):
        if request.url.host == "publisher.example":
            return httpx.Response(200, content=body, headers={"Content-Type": "application/pdf"})
        return httpx.Response(404)
    docs, bib = formal.current_inputs(metadata, root)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return formal.collect_sources(formal.inventory(docs, bib), metadata, root, root / "evidence", client)


def test_bound_transcript_is_primary_text(tmp_path):
    metadata = setup(tmp_path)
    sources, errors = collect(tmp_path, metadata)
    primary = [s for s in sources if s["kind"] == "primary_text"]
    assert errors == [] and len(primary) == 1
    assert primary[0]["text"] == TEXT and primary[0]["extraction_method"] == "ocr_transcript"
    assert primary[0]["ocr_transcript"]["tool"] == "rapidocr-onnxruntime"
    assert primary[0]["body_sha256"] == hashlib.sha256(SCAN).hexdigest()


@pytest.mark.parametrize("fault", ["other_original", "changed_transcript", "no_header"])
def test_unbound_transcript_is_refused(tmp_path, fault):
    if fault == "no_header":
        metadata = setup(tmp_path, text="Theorem 2: for every real x, x squared is nonnegative.\n")
        body = SCAN
    else:
        metadata = setup(tmp_path)
        body = SCAN + b"different" if fault == "other_original" else SCAN
        if fault == "changed_transcript":
            (tmp_path / "papers/p/evidence/ocr.txt").write_text(TEXT + "edited\n")
    sources, errors = collect(tmp_path, metadata, body)
    assert all(s["kind"] != "primary_text" for s in sources)
    assert "Declared primary source unavailable" in (tmp_path / "evidence/retrieval-failures.json").read_text()


@pytest.mark.parametrize("overrides", [{"pages": None}, {"kind": "publisher_catalog"},
                                       {"extraction_method": "text"}])
def test_invalid_transcript_declarations(tmp_path, overrides):
    metadata = setup(tmp_path)
    source = metadata["formal_check"]["sources"][0]
    for key, value in overrides.items():
        if value is None:
            source.pop(key)
        else:
            source[key] = value
    with pytest.raises(ValueError):
        formal.source_plan(metadata)
    metadata = setup(tmp_path / "second")
    metadata["formal_check"]["sources"][0]["transcript"]["path"] = "elsewhere/ocr.txt"
    with pytest.raises(ValueError):
        formal.source_plan(metadata)
