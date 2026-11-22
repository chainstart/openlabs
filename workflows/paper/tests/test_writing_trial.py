import json

from paper_writing import writing_trial


def test_comparison_keeps_sources_and_reader_blind(tmp_path, monkeypatch):
    packets = []
    def call(**kwargs):
        role = kwargs["role_name"]
        prompt = kwargs["user_prompt"]
        if role == "author":
            packets.append(prompt)
            return dict.fromkeys(["title", "abstract", "figure_sequence", "results"], "draft"), {}
        if role == "reader":
            assert "evidence secret" not in prompt and "writer-a" not in prompt
            return dict.fromkeys(["question", "comparison", "answer", "meaning"], "recall"), {}
        return dict(question="accurate", comparison="missing", answer="misread", meaning="accurate", reasoning="supported"), {}
    monkeypatch.setattr(writing_trial, "run_role", call)
    evidence = tmp_path / "numbers.txt"
    evidence.write_text("evidence secret")
    output = tmp_path / "trial"
    writing_trial.run([evidence], output, ["writer-a", "writer-b"], "reader")
    result = json.loads((output / "scores.json").read_text())
    assert packets[0] == packets[1]
    assert [row["score"] for row in result["results"]] == [1, 1]


def test_historical_calibration_keeps_answer_key_and_author_out_of_seats(tmp_path, monkeypatch):
    def call(slot, role, model, instruction, body, schema):
        assert "private-id" not in body and "private-author" not in body
        assert "expected_science" not in body
        if role == "science":
            return {"verdict": "pass", "reasoning": "reason"}
        if role == "reader":
            assert "private-evidence" not in body
            return dict.fromkeys(writing_trial.POINTS, "recall")
        return {**dict.fromkeys(writing_trial.POINTS, "misread"), "reasoning": "reason"}

    monkeypatch.setattr(writing_trial, "call", call)
    draft = {**dict.fromkeys(("title", "abstract", "results", "figures"), "draft"),
             "author": "private-author"}
    output = tmp_path / "calibration"
    writing_trial.calibrate([{"id": "private-id", "expected_science": "return",
                             "evidence": "private-evidence", "draft": draft}],
                            output, "science", "reader")
    report = json.loads((output / "scores.json").read_text())
    assert report["science_false_pass"] == 1
    assert report["science_false_return"] == 0
    assert report["reader_misread_cases"] == 1
    assert report["reader_misread_points"] == 4
