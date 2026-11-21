from paper_writing.figure_standard import findings


def test_main_environment_counts_once_and_supplement_cannot_fill_gap():
    plan = dict(manuscript_type="rank_audit", figures=[
        dict(figure="rank", kind="result", panels=1, evidence_stages=["aggregate"]),
        dict(figure="split", kind="schematic", panels=2, evidence_stages=["split"]),
    ])
    tex = r"""\begin{figure}\IfFileExists{rank.pdf}{\includegraphics{rank.pdf}}{\includegraphics{rank.png}}
    \caption{Summary.}\end{figure}\appendix
    \begin{figure}\includegraphics{split}\caption{Design}\end{figure}"""
    issues = findings(plan, tex)
    assert any("1 main figures" in row["message"] for row in issues)
    codes = {row["code"] for row in issues}
    for code in ("TYPE", "MAPPING"):
        assert "FIG-STANDARD-" + code not in codes
    for code in ("COUNT", "FIRST", "GROUP", "CAPTION", "ENCODING", "STAGE", "SUPPLEMENT"):
        assert "FIG-STANDARD-" + code in codes
    assert any("to split." in row["message"] for row in issues)
    plan.update(count_reason="Short communication combines comparisons.")
    plan["figures"][0]["single_panel_reason"] = "All contrasts share one axis."
    assert not {"FIG-STANDARD-COUNT","FIG-STANDARD-GROUP"} & {row["code"] for row in findings(plan,tex)}
