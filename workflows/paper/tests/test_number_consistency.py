from paper_writing.number_consistency import check


def test_definite_conflict_is_an_error_and_qualified_differences_are_advice():
    tex = (r"\begin{abstract}Our classifier is accurate. The external validation AUROC was 0.91 "
           r"overall.\end{abstract}" "\n"
           r"\section{Results} Results are shown. The external validation AUROC was 0.89 in "
           r"this study.")
    report = check(tex)
    assert report["errors"] == 1
    assert report["findings"][0]["label"] == "external validation auroc"
    qualified = tex.replace("0.89 in", "0.89 compared with the baseline in")
    report = check(qualified)
    assert report["errors"] == 0 and report["advice"] == 1


def test_same_value_everywhere_is_clean():
    tex = (r"\begin{abstract}We analysed 472 gauging stations worldwide.\end{abstract}"
           r"\section{Data} The sample has 472 gauging stations worldwide."
           r"\begin{figure}\caption{Map of 472 gauging stations worldwide.}\end{figure}")
    assert check(tex)["findings"] == []
