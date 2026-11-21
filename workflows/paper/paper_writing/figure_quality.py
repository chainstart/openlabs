"""Figure-plan coverage and conservative diagnostics for vector plots."""

import json
import re


PLAN_NAME = "figure-plan.json"
PAPER_TYPES = {"method", "mechanism", "study_design", "other"}
PLOT_FINDINGS = {
    "FIG-PANEL-LABELS", "FIG-LEGEND-OVERLAP", "FIG-REFERENCE-LABEL",
    "FIG-AXIS-UNITS", "FIG-RASTER-RESULT", "FIG-LINE-THROUGH-TEXT",
}


def read_plan(manuscript):
    path = manuscript / PLAN_NAME
    if not path.is_file():
        return {}, "Write figure-plan.json before drafting, linked from the story line."
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(plan, dict) or plan.get("paper_type") not in PAPER_TYPES:
            raise ValueError("paper_type must be method, mechanism, study_design or other")
        figures = plan.get("figures")
        if not isinstance(figures, list) or not figures:
            raise ValueError("list the intended figures")
        names = set()
        for item in figures:
            if not isinstance(item, dict):
                raise ValueError("each figure must be an object")
            name = item.get("figure")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or name in names:
                raise ValueError("each figure needs a unique output filename stem")
            names.add(name)
            if item.get("kind") not in ("schematic", "result", "object"):
                raise ValueError(f"{name}: kind must be schematic, result or object")
            for field in ("point", "figure_type", "data_source", "source"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ValueError(f"{name}: supply {field}")
        return plan, None
    except (OSError, ValueError) as exc:
        return {}, str(exc)


def plot_findings(fitz, drawings, lines, segments, hits):
    """Inspect physical marks in the PDF. Findings ask for a visual check."""
    def straight(a, b):
        return abs(a[0] - b[0]) < 0.3 or abs(a[1] - b[1]) < 0.3

    paths = [(drawing, segments(drawing)) for drawing in drawings]
    axes = []
    sides = []
    for drawing, parts in paths:
        rect = drawing["rect"]
        if drawing.get("type") not in ("s", "fs"):
            continue
        if (rect.width >= 25 and rect.height >= 22 and len(drawing["items"]) == 1
                and drawing["items"][0][0] == "re"):
            axes.append(rect)
        if len(parts) == 1 and straight(*parts[0]):
            a, b = parts[0]
            if max(abs(a[0] - b[0]), abs(a[1] - b[1])) >= 22:
                sides.append((a, b))
    # Matplotlib often exports bottom and left spines as separate paths.
    for a, b in sides:
        if abs(a[1] - b[1]) > 0.3 or abs(a[0] - b[0]) < 25:
            continue
        left, right = sorted((a[0], b[0]))
        bottom = a[1]
        for c, d in sides:
            if (abs(c[0] - d[0]) < 0.3 and abs(c[0] - left) < 0.6
                    and abs(max(c[1], d[1]) - bottom) < 0.6 and abs(c[1] - d[1]) >= 22):
                axes.append(fitz.Rect(left, min(c[1], d[1]), right, bottom))
                break
    # Keep full, distinct plot frames, excluding tick/grid fragments.
    frames = []
    for rect in sorted(axes, key=lambda box: -box.get_area()):
        if all((rect & old).get_area() < 0.7 * rect.get_area() for old in frames):
            frames.append(rect)

    findings = []
    labels = {line["text"].strip("(). ").lower() for line in lines
              if re.fullmatch(r"(?:\([a-zA-Z]\)|[a-zA-Z][.)])", line["text"])}
    if len(frames) > 1 and not {chr(97 + i) for i in range(min(len(frames), 26))} <= labels:
        findings.append(("FIG-PANEL-LABELS", f"{len(frames)} plot panels detected. Verify distinct panel letters."))

    missing_units = set()
    unlabelled_reference = False
    overlap = False
    for rect in frames:
        for line in lines:
            box, label = line["bbox"], line["text"]
            below = (0 <= box.y0 - rect.y1 <= 38 and rect.x0 <= (box.x0 + box.x1) / 2 <= rect.x1)
            left = (line["rotated"] and 0 <= rect.x0 - box.x1 <= 38
                    and rect.y0 <= (box.y0 + box.y1) / 2 <= rect.y1)
            if (below or left) and re.fullmatch(
                r"(?:elapsed |relative )?(?:time|frequency|voltage|temperature|current|distance|power|energy|"
                r"duration|period|amplitude|capacity|revenue|profit|cost|noise level|snr)", label, re.I
            ):
                missing_units.add(label)

        inset = [d for d in drawings if d.get("fill") is not None
                 and d.get("fill_opacity", 1) < 0.98 and d["rect"] in rect
                 and 16 <= d["rect"].width < rect.width * 0.95 and 9 <= d["rect"].height < rect.height * 0.7
                 and any(line["bbox"] in d["rect"] for line in lines)]
        for legend in inset:
            box = legend["rect"]
            inner = fitz.Rect(box.x0 + 2, box.y0 + 2, box.x1 - 2, box.y1 - 2)
            if any(d.get("color") and d.get("seqno", 0) < legend.get("seqno", 0)
                   and any(hits(a, b, inner) for a, b in parts) for d, parts in paths):
                overlap = True

        # Frame-free legends still leave a short swatch immediately left of a label.
        # Include the swatch in the box so a line cutting across the key is flagged.
        for line in lines:
            box = line["bbox"]
            if box not in rect or line["rotated"] or not re.search(r"[A-Za-z]{2}", line["text"]):
                continue
            keys = [d for d in drawings if d["rect"] in rect and (d.get("color") or d.get("fill"))
                    and 3 <= d["rect"].width <= 25 and d["rect"].height <= 8
                    and 1 <= box.x0 - d["rect"].x1 <= 8
                    and abs((d["rect"].y0 + d["rect"].y1 - box.y0 - box.y1) / 2) <= 3]
            for key in keys:
                entry = fitz.Rect(key["rect"].x0, box.y0 + 2, box.x1, box.y1 - 2)
                if any(d.get("color") and d["rect"].width >= 28 and d["rect"].height >= 1
                       and d.get("seqno", 0) < key.get("seqno", 0)
                       and any(hits(a, b, entry) for a, b in parts) for d, parts in paths):
                    overlap = True

        frame = fitz.Rect(rect.x0 - .75, rect.y0 - .75, rect.x1 + .75, rect.y1 + .75)
        for drawing, parts in paths:
            dash = drawing.get("dashes")
            if len(parts) != 1 or drawing.get("type") not in ("s", "fs"):
                continue
            color = drawing.get("color") or ()
            grey = len(color) == 3 and max(color) - min(color) < 0.08
            dashed = bool(dash and dash.split("]")[0].strip("[ "))
            if (grey and min(color) >= 0.55) or not (dashed or (grey and 0.2 <= min(color) <= .5)):
                continue
            a, b = parts[0]
            if not straight(a, b) or a not in frame or b not in frame:
                continue
            horizontal = abs(a[1] - b[1]) < 0.3 and abs(a[0] - b[0]) >= rect.width * 0.85
            vertical = abs(a[0] - b[0]) < 0.3 and abs(a[1] - b[1]) >= rect.height * 0.85
            interior = (rect.y0 + 1 < a[1] < rect.y1 - 1 if horizontal else
                        rect.x0 + 1 < a[0] < rect.x1 - 1)
            if not (horizontal or vertical) or not interior:
                continue
            sample = any(d.get("dashes") == dash and d.get("color") == drawing.get("color")
                         and abs((d.get("width") or 0) - (drawing.get("width") or 0)) <= .1
                         and 6 <= d["rect"].width <= min(30, rect.width * .4) and d["rect"].height < 1
                         for d in drawings)
            direct = any(
                line["bbox"] in rect and re.search(r"[A-Za-z]{2}", line["text"])
                and (abs(line["bbox"].y1 - a[1]) < 8 and line["bbox"].x1 >= rect.x1 - rect.width * .3
                     if horizontal else abs(line["bbox"].x0 - a[0]) < 8
                     and line["bbox"].y0 <= rect.y0 + rect.height * .25)
                for line in lines
            )
            if not sample and not direct:
                unlabelled_reference = True
    if missing_units:
        findings.append(("FIG-AXIS-UNITS", "Verify units on axis labels: " + ", ".join(sorted(missing_units)) + "."))
    if overlap:
        findings.append(("FIG-LEGEND-OVERLAP", "Data crosses a legend key or box. Move the legend clear of the data."))
    if unlabelled_reference:
        findings.append(("FIG-REFERENCE-LABEL", "A reference line has no detected legend key or direct label."))
    return findings
