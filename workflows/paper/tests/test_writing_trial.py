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
        return dict(question="accurate", comparison="missing", answer="misread", meaning="accurate"), {}
    monkeypatch.setattr(writing_trial, "run_role", call)
    evidence = tmp_path / "numbers.txt"
    evidence.write_text("evidence secret")
    output = tmp_path / "trial"
    writing_trial.run([evidence], output, ["writer-a", "writer-b"], "reader",)
    result = json.loads((output / "scores.json").read_text())
    assert packets[0] == packets[1]
    assert [row["score"] for row in result["results"]] == [1, 1]
