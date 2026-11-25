---
name: openlabs-paper-figures
description: Plan, draw, check and caption the schematic figures of an OpenLabs manuscript (concept, framework, architecture, flow, mechanism, geometry, algorithm, study design, timeline) as vector figures from committed source code, with the paper-writing figures tools and the shared templates and styles. Used by the writer and the pre-review figure repair seat.
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

Choose an observation, comparison or schematic that makes the design intelligible.
Use only figures that serve the story line.

## 1. Figure plan: part of the story line

Draw the decisive comparison before writing Results. An optional plan template uses
`paper_type` (`method`, `mechanism`, `study_design` or `other`) and a `figures` array:

```json
{
  "paper_type": "study_design",
  "manuscript_type": "rank_audit",
  "supplement_coverage": {"alternative splits": "Figure S1"},
  "figures": [{
    "figure": "fig-design",
    "kind": "schematic",
    "evidence_stages": ["protocol", "split"],
    "panels": 2,
    "figure_type": "cohort and split diagram",
    "point": "See which records enter each split and where the endpoint is measured",
    "data_source": "registered cohort counts in evidence/cohort.csv",
    "source": "figure-src/fig-design.tex"
  }]
}
```

Use the output filename stem for `figure` and `schematic`, `result` or `object` for
`kind`. Name the registered results or source data. A conceptual diagram with no
empirical values may name the manuscript method section. Use an object composition where
readers need to recognise the instrument, material, specimen or device. Run `figures build`,
inspect the PNGs and run `figures check` before returning `ready_for_review`.
The dispatcher checks `blocking` and `repair_required` before unified review.

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

The research owner records two to four reader-facing points and proposed figure types in
`OWNER_HANDOVER.md`. The writer uses those suggestions to choose the final figures.

## 2. Choosing the figure

| The reader must see | Draw | Template (`figures new --template`) | Source |
|---|---|---|---|
| data sources, exclusions, n per step, endpoint | study-design flow | `study-design` | TikZ |
| modules, layers, what flows between them | architecture with interface labels | `method-architecture` | TikZ |
| iteration, stopping rule, update | flow + numbered pseudo-code | `algorithm-loop` | TikZ |
| detached binary with separate photospheres | geometry panels + computed curve | `binary-eclipse-geometry` | Python |
| contact binary with a common envelope | Roche equipotential, inclination and projected flux | `contact-roche` | Python |
| timing rule, settlement or sampling interval | one worked interval, both rules | `settlement-timing` | TikZ |
| degradation, thresholds, prognostic quantities | curve, band, threshold, RUL arrow | `degradation-rul` | Python |
| train/validation/holdout, rolling backtest | windows on one calendar axis | `rolling-evaluation` | SVG |
| method A versus B, one decisive difference | two panels on the same toy case | `concept-contrast` | TikZ |
| a physical object or device | code-drawn object with gradients | `li-ion-cell` | SVG |
| any system, pipeline or mechanism built from objects | cards, groups, icons, sized connectors | `schematic-flow` | HTML |
| PV/storage plant at a grid connection | power flows sized by MW + one-day inset | `pv-storage-grid` | HTML |
| contact binary, observer, light curve | computed Roche section, sky views, light-curve insets | `contact-binary` | HTML |
| run-to-failure rig and the path to RUL | rig objects, sensor/data paths, HI and RUL insets | `bearing-testbed` | HTML |
| isolates from reservoirs to cases; lab or clinical sample pipelines | sources, lab steps, tree and attribution insets | `isolate-tracing` | HTML |

`paper-writing figures new --list` shows the catalogue (`workflows/paper/figure-templates/`).

**Which route draws what.**
- **Result figures: matplotlib** (`.py`). Axes, uncertainty, many points: the plot comes from the
  data file, so it is re-drawn when the numbers change.
- **Principle, mechanism and system schematics: SVG/HTML with the element library first**
  (`.html`, template `schematic-flow` and the field examples). HTML+CSS does the layout (grids,
  groups, cards that size to their text), `<img class="ol-icon" src="asset:FIELD/NAME.svg">`
  places a licensed vector object, `.ol-flow` connectors route themselves between boxes and their
  width can carry a quantity (MW, share, sample count), and `<img class="ol-inset" src="inset:NAME">`
  embeds a small matplotlib curve computed from data. Find objects with
  `paper-writing figures assets WORDS [--field F]`.
- **Formula-dense theory diagrams: TikZ** (`.tex`): commutative diagrams, derivation flows, labelled
  geometry with many symbols, circuits (circuitikz), chemical formulas (chemfig).
- **Geometry computed from a model** stays in Python (or a Python inset inside an HTML figure) so
  the drawing follows from the model.

A schematic shows the mechanism with objects, colour and line weight, not with sentences or
equations: one or two words per label, numbers with units, at most one short formula. Domain
tools: rdkit for molecules, astropy/matplotlib for sky coordinates, circuitikz for circuits,
chemfig for structural formulas, pgfplots for plots inside TikZ.

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
Elsevier do not accept generative-AI images in figures. For a Nature Portfolio target (NC,
Scientific Reports, Nature, npj, Communications journals) never generate an image or
illustration with an image model (Codex image tool, GPT Image, DALL-E, ...): Springer Nature
does not permit AI visual content made from text prompts. `figures check` blocks it
(`FIG-AI-IMAGE-NATURE`: generation records `*.provenance.json`, `ai_generated` assets,
`artwork_disclosures`). Allowed: figures drawn in code from data, renders from data in domain
software, and licensed library assets.

## 3. Style

- Build at the measured column width in the [journal proof catalog](../../templates/journal-proofs/README.md). Building by paper ID selects the registered target; a source sidecar may select a named profile for a preview. Python uses `olf.figure("single")` or `"double"`, TikZ uses the matching column lengths. Match the float width in the manuscript.
- Place each figure environment right after the paragraph that first cites it. In a single-column layout (elsarticle `preprint`, `onecolumn`) write `\begin{figure}[!htbp]`: `figure*` and `[t]` alone may only go to a page top, and once those slots fill every later figure drifts to the end. `figures check` and the delivery floor fail a figure printed more than one page from its first mention (`paper-writing figures placement`).
- Apply the profile's body, tick and panel sizes. Anchor panel letters at the upper left. Inspect the final PDF's measured placements, embedded fonts, thinnest strokes and effective raster resolution. Repair unreadable encodings at source.
- Keep a stable colour and second cue per group. The shared palette extends Okabe–Ito. Preserve measured image colours and colour scales. Opt in to recolouring only for schematic assets.
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
paper-writing figures assets solar battery [--field energy] [--no-credit]  # search the element library
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
  rasterized by Chromium: use gradients and semi-transparent shapes instead. Before printing, the
  build inlines `asset:` references (HTML `<img src>`, SVG `<image href>`) as vector `<svg>`
  (`data-recolor` maps colours to the palette, `data-stroke` thins outline icons), runs the
  sidecar's `"insets": {"NAME": "_script.py"}` scripts (`$FIG_OUT` is an SVG, `$FIG_INSET` the
  name; draw the inset at its printed size) and, for HTML, injects `style/openlabs-fig.css`, the
  journal profile as CSS variables (`--ol-single`, `--ol-double`, `--ol-body`, `--ol-small`,
  `--ol-panel`) and `openlabs-fig.js` (the connectors). Text is set in Liberation Sans (Arial
  metrics, TrueType) so the PDF embeds real fonts; CFF/OpenType text would become Type 3 fonts.
- Element library: `$OPENLABS_FIG_ASSETS` (default `/workspace/openlabs/build/figure-assets`),
  about 290 licensed objects and icons by field (general, energy, reliability, astronomy,
  biomedical) from Tabler, Material Symbols, Phosphor, Bioicons/Servier, Reactome and OpenLabs
  drawings, each with `.license.json`; `catalog.json` indexes them. Rebuild or extend it with
  `workflows/paper/figure-assets/fetch_assets.py` (downloads only through the WSL bridge; record
  new sources in that directory's `SOURCES.md`).
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

## Evidence plan before drawing

Use the genre profiles as design references. At final column width, check units, sample, intervals and visual encodings. Anchor results in traceable study outputs.


|模式|适用问题|画面要素与阅读顺序|评审时怎么辨别|
|---|---|---|---|
|计算链与单元展开|模型把物理先验和数据拟合放在不同环节|首个面板标输入、状态、预测量；次面板展开唯一需要解释的计算单元，标出训练和预测时可见的数据|遮住正文，读者能否指出哪些量来自观测、哪些由模型产生？|
|总体性能与失效位置|天气、时空预测、跨场站或跨扇区外推|同图排列按预测时长或样本分组的误差、空间差值或逐组差值；保持基线、误差方向和色标一致|读者能否从总体改善追到一个具体失效区域或时段？|
|轨道几何与光变证据|用全食形态约束质量比、倾角或第三光|共用相位零点；标主次食、接触点或平底区，在相邻面板给观测点、模型和残差；仅在几何来自拟合时写明模型条件|能否从几何解释找到对应数据段，再看到该段的误差？示意的几何不能被当作独立观测。|
|单目标拟合到跨观测复现|多扇区 TESS、跨管线重提取、异质噪声|选取预先说明的代表扇区，主曲线下对齐残差；下一图按同一参数轴画全部扇区的区间，编码提取流程和公共区间|区间、固定参数、单位、置信或似然约定能否逐项找回？不同扇区的离散是否被合并均值掩盖？|
|观测轨道与竞争解|轨道周期变化、光时效应、质量转移|按时间绘极小时刻的 O−C，注明历表与单位；下排并列候选模型的残差或剔除一组数据后的变化|纵轴量级是否足以分辨模型；只有数据允许时，才把周期项解释为物理伴星。|
|接入结构与配对收益|同一场站比较两种储能拓扑或结算规则|两张结构图用相同符号和边界标可充电路径、电表和出口限制；对应结果用同一场站年的配对差、零线和汇总区间|两种设计是否只改声称改变的条件？图上能否找出收益来源及收益变号的场站？|
|排名迁移与分歧定位|验证人工扰动是否预测真实工况|首图标同一模型集、人工/实测两路、分组与留出；结果并排显示完整排名与相关系数及区间，特别标异常对照|能否辨别“整体顺序近似”“第一名能否迁移”和“区间是否跨判据”这三个命题？|
|主张与敏感性预算|结论依赖食深提取、阈值、调度策略或筛选规则|正文展示能够改变结论的扰动，附录展开逐项扰动、全样本图谱和额外残差；标题或图注给出和正文的对应图号|把敏感性图删除后，读者是否会误认结论确定性？若会，应移入正文。|





|适用问题|图中要素与组合方式|本地产线的落点|
|---|---|---|
|同一资产的两种结算或接线规则|左右保留相同资产、时段和约束，只高亮改变的价格、流向或上限；下方用一个真实结算时段核算两种结果|结算稿可展示相同调度怎样得到两种现金流；光储稿可把越限和回收的时段连到收益分解|
|年度收入由少数尖峰驱动|同横轴叠排价格、可用功率、SOC 与现金流；旁列全年配对效应及区间，交代选日规则|结算稿已有滚动区间和收入集中度表，可验证“典型日是否代表全年”|
|总收益掩盖分配差异|依次呈现总体分母、受益或受损组、区域差异；不同地域比较固定色标，空间位置不重要时用排序点图|光储稿按站点、年份同时识别；小站点数优先保留站名，避免着色地图制造连续覆盖的印象|
|模型能否跨噪声或跨域保持排序|左为训练与留出单位，右为同一模型序列在基准与挑战集上的排名连线或矩阵；下方绘秩相关和配对区间|轴承稿把 5×8 排名与已有相关图连起来，标出发生反转的模型对及其误差范围|
|寿命预测对测试单元失效|上排传感器原始量与健康指标，下排预测寿命与参考终点；并排普通试件与按预先规则选出的失败试件|区分跨试件泛化、临近失效时间窗和不同预测起点；保留试件号与时间单位|
|多个场景共用一个模型|主图一对面板固定比较对象，再依次展开参数或地点；每次只改变一个维度，减少读者来回找色标的成本|用丹麦／法国复版、不同季节同轴、不同噪声形态同模型顺序等结构检验异质性|

For applied schematics, compose recognizable objects from the shared SVG library, label the key quantities and units, and include any credit line generated by the asset checker in the caption or acknowledgments.
