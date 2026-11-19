---
name: openlabs-paper-readability
description: Binding writing rules for every OpenLabs manuscript - story line first, main text versus appendix, a plain abstract, one layer of qualification, no revision history, revisions that do not grow the main text - plus the writer's own checks (narrative-check, reader-check) and the referee's reading. Read before drafting and before every revision; complaints of long, defensive, AI-sounding or incomprehensible papers come here.
---

# Writing a paper people read

These rules bind the writer of every OpenLabs manuscript (the topic owner, or a writer task)
from the first draft through every revision. The writer writes the whole paper in one session;
nothing here adds a task, a stage or a reviewer. The scripts named below are the writer's own
tools, run in the same session.

The target: an objective, plain, logically clear paper that tells one story - problem, approach,
experiment, result - which a specialist of the target venue can read once, straight through,
and retell. Readers and editors stop at length and defensiveness long before they reach the
evidence (2026-11: a single-star photometry paper reached 44 pages and 15,000 words because every
review round added qualifications and none removed any).

An AI-detector score, a word blacklist or polished tone cannot establish readability; a reader
who can retell the paper can.

## 1. Before drafting: one page of story line

Write `papers/<paper_id>/writing/storyline.md` (next to the manuscript directory, outside the
manuscript snapshot and the journal package) before the first sentence of the paper, and update
it when the result changes:

- **Reader**: who reads this (the venue and its regular readers), what they already know.
- **Main result**: one sentence, with its key number. This is the sentence the abstract,
  introduction and conclusions all end on.
- **Support**: three or four points that make the main result believable (the decisive data,
  the method, the key experiment or comparison, the check that rules out the obvious
  alternative). Each becomes one main-text section or subsection.
- **Main limitation**: the one limitation that changes how the result is read. It gets one
  paragraph in the limitations section, not a clause in every sentence.
- **What is not in the main text**: the robustness and secondary material that goes to the
  appendix or supplement.

Draft the main text from this page, section by section. If a passage serves none of the support
points, it goes to the appendix or out. If you cannot fill the page from the evidence, that is
a scientific gap to fix (or record), not a writing problem.

## 2. Main text and appendix

The main text carries only what the story line needs: the question and why it matters, the
method at the level needed to trust it, the key experiment(s), the main results, a short
discussion with the closest work, and one limitations paragraph.

Into the appendix or supplement, each replaced in the main text by one sentence with a reference
("The result does not depend on the mesh resolution (Appendix B)."):

- robustness checks, convergence and numerical-resolution tests;
- item-by-item sensitivity analyses and parameter scans;
- secondary comparisons, alternative models that were not adopted, null side analyses;
- long derivations, data-reduction details, per-subsample tables;
- the full error budget (the main text gives the total and its dominant term).

Keep negative results that bear on the main question in the main text; keep the rest of the
record (failed variants, all checks) in the appendix or supporting materials, never deleted.

Length limits are mechanical: `paper-writing narrative-check` fails a main text over its limit
(default 7,000 words for an article, 3,500 for a letter, 6,500 for a conference paper, 12,000
for a review, 14,000 for mathematics; captions count, tables, displayed mathematics, appendices,
references and declarations do not). The venue's own limit, recorded in the paper record as
`narrative_limits`, overrides the default.

## 3. Abstract

One question, one main result with the numbers that state it (value and uncertainty), one or
two sentences of method in plain words, and what it means for the field. Not in the abstract:
test thresholds and likelihood cut-offs (`ΔlnL ≤ 2`, `p < 0.05` used as a criterion), ranges per
subsample or per sector, sampler and pipeline names unless they are the contribution, internal
labels, and caveats in parentheses. `narrative-check` warns above 250 words, 10 numbers, any
test statistic or more than 3 parenthetical qualifiers.

## 4. Qualification, voice and the words to avoid

- **One layer of qualification per conclusion.** State the finding at the strength the evidence
  supports, then at most one limit. "The light curves allow negative third light down to -0.1."
  not "Within the geometries tested, and to the precision of the mesh at the sampled phases, the
  light curves alone do not exclude moderately negative dilution (sector 62)."
- **Limitations in one place.** One limitations paragraph or section says what the result does
  not cover. Do not repeat it after every result; a limitation stated once is stated.
- **No revision history.** The paper describes the analysis as it is, for a reader who never saw
  an earlier draft. Not "in the previous version", "after re-examination", "the high-resolution
  profiles replace the points that had previously been excluded", "as the referee requested",
  "此前版本", "经复核后", "根据审稿意见". History goes in the response letter and the revision
  record. `narrative-check` fails on these.
- **No invented labels.** Do not coin names ("the ridge diagnostic", "Route A", "the S62 bracket
  test") for ordinary operations; say what was done. Use the field's established terms.
- **No empty transitions or defensive asides.** Delete the phrase or state the logical link.

| Avoid (English) | Write instead |
|---|---|
| It is worth noting that the period increased. | The period increased. |
| Importantly, / Notably, / Interestingly, X holds. | X holds. (or: X holds, which means Y.) |
| In summary, / Overall, / Taken together, ... | (cut; the paragraph's last sentence is the summary) |
| We do not claim that ...; this should not be read as ... | (state what is shown; scope goes in Limitations) |
| This value is a heuristic summary, not a calibrated error. | The quoted width is the spread of the sector values (Sect. 4.3). |
| As requested by the referee, we have now added ... | (describe the analysis; answer the referee in the letter) |

| 避免（中文） | 改写为 |
|---|---|
| 值得注意的是，周期在增加。 | 周期在增加。 |
| 综上所述，本文…… / 总而言之，…… | （删去；段末一句本身就是总结） |
| 需要指出的是，该结果仅在所考察的几何条件下成立，并不意味着…… | 该结果适用于 X 条件（局限见第 6 节）。 |
| 经复核后，我们在本版中改用了…… | 我们采用……（修改经过写进回复信） |
| 此外，另外，与此同时，进一步地，…… 连用 | 用句子之间的因果或对比关系衔接，不靠过渡词 |
| 我们并不声称……，不宜解读为…… | 直接写证据支持的结论，适用范围写在局限一节 |

`narrative-check` counts hedges, sentences with stacked qualifiers, over-qualified conclusion
sentences and empty transitions in English and Chinese and lists them with line numbers; these
are warnings to read, not a score to optimise.

## 5. Revising after a review or a formal check

Reviews and formal checks ask for added qualifications, checks and explanations. By default:

- the added material goes in the **appendix or supplement**, and the answer goes in the
  **response letter** (`RESPONSE.md` / `--response`); the main text changes by at most one
  sentence per item (a pointer, or the one corrected conclusion);
- the main text does **not grow net** through a revision. Make room by cutting. The only
  exception is a request a referee explicitly placed in the main text (`placement: main_text`);
  `narrative-check` compares the main-text word count with the last reviewed version and warns
  when it grew without such a request;
- a "claim too strong" point is answered by changing the claim, never by adding a disclaimer;
- referees' and editors' cut requests (`placement: cut`) are done, not argued.

After each revision reread the abstract, introduction and conclusions against `storyline.md`:
the main result must still be the one sentence they end on.

## 6. The writer's own checks (same session)

Before returning a draft or a revision for review:

1. `paper-writing narrative-check --paper-id PID` (also part of `style-check`). Fix every failure
   (length, revision history); read every warning and fix what is real.
2. `paper-writing reader-check --paper-id PID`: a model in a fresh process, tools off, reads the
   title, abstract and main text once as a peer reader of the target venue and answers fixed
   questions - what the paper did in one sentence, the main result, where it would stop reading,
   which passages defend rather than state, what to cut. It is saved as
   `papers/<paper_id>/writing/reader-check.md` and `.json`; the unified review's editor reads it with the
   decision letter. It is the writer's tool call, not a review and not a task. Compare its
   one-sentence summary and main result with `storyline.md`: if they differ, the paper does not
   tell its story yet. Its model comes from `quality_gate.reader_check.role` (default: the
   review's worker tier); check `dispatch_allowed` first as for any other model call, and pass
   `--provider/--tool/--model` to choose another. If no model can be called, run
   `reader-check --prompt-only`, give the written packet to a fresh sub-agent with no other
   context, and file its JSON answer with `reader-check --record ANSWER.json`.
3. Then reread for fidelity: every changed number, quantifier, hypothesis, uncertainty and
   attribution still matches the evidence. Readability never changes what was shown.

## Diagnose before rewriting (substantial revisions)

Read the complete manuscript and the closest literature (the relevant passages, not abstracts),
and recover from the text the problem, assumptions, principal result, closest work, limitation
and argument, with locations. If they cannot be recovered, record the missing reasoning instead
of supplying plausible prose. Then revise in order: contribution and structure; argument (each
section and paragraph has a purpose in the reasoning, a proof roadmap matches the actual
dependencies); local exposition (define before use, explicit referents, separate assumptions,
results, observations and conjectures); fidelity. For mathematics, keep existence versus
uniformity and asymptotic versus all-parameter results distinct; a missing proof step is a
scientific issue, not a sentence to smooth over. For empirical work, connect question, method,
comparison, measured result and scope of inference; more datasets cannot replace that.

Keep the voice neutral and impersonal. Do not predict reader interest or editorial acceptance,
do not narrate drafting, self-review or revision negotiation, and do not replace these with
inflated importance language. Keep necessary methods, reproducibility information, negative
findings, citations and the truthful AI-use declaration. Save a private revision record
(version/hash, located issues, structural changes, fidelity checks, remaining gaps) outside the
paper and the review packet. A revised manuscript goes back through `review unified-run`.

## Referee mode: reconstruct without the author's explanation

Read the manuscript as a new specialist reader. Before scoring clarity, state the question, the
central result and its scope, the difference from the closest work and the main supporting
steps, with locations; say which parts cannot be recovered. Do not use the author's private
records, storyline, reader check, earlier scores or an editor's verdict to supply missing
explanations. For each material problem give location, the failed inference or missing
explanation and an acceptance condition, and its placement (main text only when the main line
needs it; otherwise appendix or response letter; or a cut). Ask for cuts where the main text
repeats limitations, stacks caveats or walks through secondary checks. Distinguish scientific
gaps, substantial exposition repairs, local corrections and optional preferences; a paper that
needs structural reconstruction of its abstract, introduction or central argument does not get
`minor_revision` merely because no new science is requested. Keep soundness and clarity distinct.

## Sources and limits

Consulted on 2026-09-26: [Humanizer](https://github.com/blader/humanizer/blob/main/SKILL.md)
for empty rhetoric and repetitive structure, and
[Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills) for scientific
writing and peer-review practice. They are editorial aids, not evidence that a manuscript was
AI-generated or that a revision is correct. Keep meaningful contrasts, technical hyphens, names
such as Erdős–Selfridge, and real uncertainty. Never optimise prose to evade authorship detection.
