---
name: openlabs-paper-figures
description: Plan, draw, check and caption the schematic figures of an OpenLabs manuscript (concept, framework, architecture, flow, mechanism, geometry, algorithm, study design, timeline) as vector figures from committed source code, with the paper-writing figures tools and the shared templates and styles. The writer's own reference; it adds no gate.
---

# Figures that carry the paper's key points

A reader should be able to see the paper's key structure without reading every paragraph: the
mechanism, the geometry, the method's parts and interfaces, the algorithm's loop, the study
design. Results figures show the evidence for the primary endpoint; schematics show what the
words struggle to convey. Both are drawn from source code, rebuilt with one command and judged by
the unified review's referees, who see the rendered figures.

In OpenLabs this skill overrides the sentence in the vendored `scientific-writing` component
("This skill does not generate images or schematics"): the writer does draw schematics, with the
tools below. Everything else in that component's figure section (provenance, units, sample sizes,
accessibility) still applies.

This is a reference for the writer, not a gate: there is no required number of figures. A paper
with one clear schematic and two result figures is better than one with six figures nobody needs.

## 1. Figure plan: part of the story line

Plan the figures when you write `writing/storyline.md`, not after the text. Add a short
`Figures` section there: for each figure, the one point it makes for the reader, the story-line
step it serves, and its kind (schematic or result). Then draw only what the plan needs.

- **Reader's entry schematic** (usually one): at the end of the Introduction or at the start of
  Methods, the picture that makes the rest of the paper easy to follow -- the mechanism (how
  half-hour averaging hides a five-minute spike), the geometry (why the eclipse depth constrains
  the inclination), the study design (sources, exclusions, splits, endpoint with n at each step),
  or the method's architecture.
- **Mechanism or algorithm figure** when the method has a loop, branch or physical process the
  text would need a page to explain.
- **Result figures** serve the primary endpoint and the main comparison; secondary checks go to
  the appendix as tables or small multiples.

A schematic earns its place only if it carries structure that prose cannot carry as well:
spatial arrangement, timing, flow with quantities, correspondences between panels. If the boxes
would just hold sentences from the text, cut the figure (the PFAS overview figure of 2026-11-13,
about 250 words in boxes, was removed at the user's request for exactly this reason).

The research-to-writing handover lists suggested schematic points; treat them as candidates for
the plan, not as orders.

## 2. Choosing the figure

| The reader must see | Draw | Template (`figures new --template`) | Source |
|---|---|---|---|
| data sources, exclusions, n per step, endpoint | study-design flow | `study-design` | TikZ |
| modules, layers, what flows between them | architecture with interface labels | `method-architecture` | TikZ |
| iteration, stopping rule, update | flow + numbered pseudo-code | `algorithm-loop` | TikZ |
| physical geometry that produces the observable | geometry panels + computed curve | `binary-eclipse-geometry` | Python |
| timing rule, settlement or sampling interval | one worked interval, both rules | `settlement-timing` | TikZ |
| degradation, thresholds, prognostic quantities | curve, band, threshold, RUL arrow | `degradation-rul` | Python |
| train/validation/holdout, rolling backtest | windows on one calendar axis | `rolling-evaluation` | SVG |
| method A versus B, one decisive difference | two panels on the same toy case | `concept-contrast` | TikZ |
| a physical object or device | code-drawn object with gradients | `li-ion-cell` | SVG |

`paper-writing figures new --list` shows the catalogue (`workflows/paper/figure-templates/`).
Geometry, curves and anything computed belong in Python so the drawing follows from the model;
boxes, arrows and annotations are easiest in TikZ; SVG/HTML suits object drawings and dense
layouts. Domain tools: rdkit for molecules, astropy/matplotlib for sky coordinates, circuitikz
for circuits, chemfig for structural formulas, pgfplots for plots inside TikZ.

### Objects that should look real (medicine, biology, materials, Nature/Science-type venues)

In order of preference: (1) render from data -- molecules with rdkit, crystal structures from
CIF/POSCAR, proteins from PDB, sky images from FITS; (2) licensed vector icons composed in SVG
(put each file in `figure-src/assets/` or the shared library `$OPENLABS_FIG_ASSETS` with a
`<name>.license.json`: `source`, `license`, `attribution`, `url`; recolour with
`paper-writing figures recolor` or `openlabs_fig.recolor_svg`; credit CC BY assets in the caption
or acknowledgments -- `figures check` reports missing licences, NC/ND terms and missing credits);
(3) draw the object in code with gradients (`li-ion-cell` shows the level of finish to aim
for); (4) a generated bitmap only as a last resort and only where the target journal's policy
allows it, declared under the `artwork_disclosures` rules -- Nature Portfolio, Science and
Elsevier do not accept generative-AI images in figures.

## 3. Style

- Draw at the printed width: 88 mm single column, 120 mm one-and-a-half, 180 mm double
  (`\olSingleColumn`, `\olOneHalfColumn`, `\olDoubleColumn`; `olf.figure("single")`). Include it
  at that width (`\includegraphics[width=\linewidth]` for a column figure) so nothing is scaled.
- Text 7-8 pt, never below 6 pt after scaling; one sans face (TeX Gyre Heros/Arial) in all figures.
- Colours from the shared palette (Okabe-Ito; blue, orange, wine, green are also distinct in
  grey). Colour is never the only cue: label directly, or add a pattern or line style.
- Label things where they are; prefer direct labels to legends. No figure title repeating the
  caption; panel letters a, b, c in bold at the top left.
- Arrows start and end at box edges and never run through text; route orthogonally, merge on a
  shared bus, keep spacing even. One arrow style per meaning (flow solid, training/feedback dashed).
- Numbers in a schematic are real (from the claim-evidence map) or clearly illustrative; never
  invent a value that looks like a result.
- No internal vocabulary, file paths, job ids, model or AI-tool names inside figures.

## 4. Tools

```bash
paper-writing figures new   <paper_id> NAME --template study-design   # or --kind tikz|py|svg|html
paper-writing figures build <paper_id> [--only NAME]                   # -> manuscript/figures/NAME.pdf
paper-writing figures check <paper_id>                                 # blocking / advisory findings
paper-writing figures sheet <paper_id>                                 # one PNG of all figures
paper-writing figures recolor in.svg out.svg [--map '#ff0000=vermilion']
```

- Sources live in `manuscript/figure-src/` (`<stem>.tex|.py|.svg|.html`, optional `<stem>.json`
  with `purpose`, `key_point`, `kind` schematic|result, `data_inputs`). The output is
  `manuscript/figures/<stem>.pdf`: vector, one page, cropped, byte-stable (rebuilding an unchanged
  source gives the same SHA-256, which the review's delta rule compares). Previews go to
  `papers/<id>/build/figures/` -- never put PNGs in `manuscript/`, the review would flag them as
  unused sources. `figure-src/` itself is excluded from the journal source archive.
- `.tex`: a TikZ fragment (wrapped and cropped automatically; `openlabs-fig.sty` loaded; extra
  preamble lines as `%!preamble \usepackage{...}`) or a full document. Engine `lualatex`
  (`"engine": "pdflatex"` in the sidecar to change it).
- `.py`: run with `paperfig-python`, style `openlabs.mplstyle` applied, `import openlabs_fig as
  olf`; write the PDF to `$FIG_OUT` (`olf.save(fig)`) or an SVG to `$FIG_SVG`.
- `.svg`/`.html`: printed by `chromium-pdf` (1 px = 0.75 pt). Filters (blur, drop-shadow) are
  rasterized by Chromium: use gradients and semi-transparent shapes instead.
- Producing a figure elsewhere (an analysis script)? Put `{"source": "../../analysis/plot.py",
  "kind": "result"}` in `figure-src/<stem>.json` so the check knows where it comes from.
- `build` refreshes `production/figure-artifacts.json`; commit it with the sources (the PDFs are
  Git-ignored and bound by that manifest).
- Configuration: `OPENLABS_FIG_PYTHON`, `OPENLABS_FIG_CHROMIUM_PDF`, `OPENLABS_FIG_TEX_ENGINE`,
  `OPENLABS_FIG_ASSETS`. Missing tools fail with a message naming the variable.

`check` blocks on: no source or a source that does not rebuild, a bitmap posing as a vector
figure, text below 6 pt at the printed width (it reads the `\includegraphics` width and probes the
manuscript's text width), overlapping or clipped text, internal words, paths, job ids or AI-tool
names in the figure, a figure without caption or never referenced, an asset without a usable
licence or credit. It advises on stale PDFs, lines through text, colours that merge in grey,
upscaled drawings and raster schematics.

## 5. Look before you hand over

After every build, open each preview PNG (both Codex and Claude can view images) and look at it
as a reader: is the point visible in five seconds, is anything crowded, misaligned, cut off or
crossing text? Fix and rebuild until it is right, then run `figures check`. The unified review
shows the referees the same rendered figures; they judge whether the key mechanism has a clear
schematic and whether the figures agree with the results.

## 6. Captions

A caption is readable without the text: the first sentence states what the figure shows and its
point ("Half-hour settlement pays the block mean, so a five-minute spike is diluted six-fold");
then define panels, symbols, colours and line styles, give n, units and what the bands mean.
No "Schematic diagram of ..." filler, no method narration, no internal names. Credit licensed
assets here or in the acknowledgments as their licence requires.
