from paper_writing.review_flow import _reviewed_figure_branches, substantive_delta


def test_inactive_plot_requires_a_reviewed_image():
    image = r"\includegraphics{plot.png}"
    source = r"\IfFileExists{plot.pdf}{\includegraphics{plot.pdf}}{" + (
        r"\IfFileExists{plot.png}{" + image + r"}{\draw (1,2);}}")
    assert _reviewed_figure_branches(source, {"plot.png"}) == image
    assert _reviewed_figure_branches(source, set()) == source


def test_delivery_identifiers_are_ignored_and_specimen_counts_stay_significant():
    section = r"\section*{Data and code availability}"
    updated = "Zenodo version 0.1.0 (DOI 10.5281/zenodo.24400297)"
    assert substantive_delta(section + "Zenodo", section + updated)["numbers_added"] == []
    assert substantive_delta(section + "Zenodo", section + updated + " with 28 specimens")["numbers_added"] == ["28"]
    assert substantive_delta(r"\section{Methods}", r"\section{Methods}" + updated)["numbers_added"] == []
