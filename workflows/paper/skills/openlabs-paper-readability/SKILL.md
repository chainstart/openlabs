---
name: openlabs-paper-readability
description: Review and revise scientific manuscripts for intelligible contributions, logical exposition, and precise prose. Use for paper drafting, substantial revisions, and complaints of incomprehensible or AI-sounding writing; preserve scientific meaning and truthful AI disclosures.
---

# Scientific readability and exposition

Use this as the shared paper-writing overlay, within the existing writer and referee
roles. It does not create another scored reviewer or change review budgets.
The goal is a paper that its intended specialist reader can understand and evaluate.
An AI detector score, word blacklist, or polished tone cannot establish that result.

## Author mode: diagnose before rewriting

Read the complete manuscript and identify the intended readership. From the actual
statements and evidence, make a private outline of the problem, assumptions, principal
result, closest literature, limitation, and argument supporting the result. Cite locations.
If these cannot be recovered, record the missing reasoning instead of supplying plausible prose.

Read the relevant passages of the closest literature, not just abstracts or citation
metadata. Compare like with like: quantifiers, regimes, hypotheses, data, baselines and
strength of conclusions. Learn conventional terminology and exposition without copying
sentences. Better presentation does not increase the mathematical or empirical contribution.

Then revise in this order:

1. **Contribution and structure.** Give the abstract one intelligible principal result.
   Introduce the object, question and scope before technical method labels. Include
   secondary results only when their relation to that principal result is clear. In the
   introduction explain what prior work establishes and the precise remaining difference.
2. **Argument.** Give each section and paragraph a purpose in the reasoning. Explain why
   each main lemma, experiment or construction is needed and how its conclusion is used.
   Replace a list of named techniques with an explanation of the obstacle and the steps
   that overcome it. A proof roadmap must match actual dependencies in the proof.
3. **Local exposition.** Define unfamiliar objects before use; make pronouns, comparisons
   and inference words refer to explicit statements. Separate assumptions, proved results,
   empirical observations and conjectures. Remove unsupported importance claims, repeated
   summaries, empty transitions and invented labels that hide a simple operation.
4. **Fidelity.** Compare the old and new text against the underlying statements and evidence.
   Check every affected quantifier, hypothesis, constant, direction of inequality, asymptotic
   qualifier, uncertainty statement and attribution. Preserve established terms and notation.
   Do not replace technical words with unusual synonyms, invent examples or citations,
   manufacture a human voice, or remove truthful AI-use declarations.

For mathematics, explicitly distinguish existence from uniformity and asymptotic results
from all-parameter results. Check symbol overload, exceptional cases and the distinction
between a prescribed object and a minimum over objects. Do not turn an unexplained proof
step into a confident sentence: missing justification is a scientific issue.

For empirical work, the narrative must connect the research question to the method,
comparison, measured result and scope of inference. More datasets or implementation detail
cannot replace that connection or justify unsupported generality.

## Final manuscript voice after repeated revision

Write the final manuscript in a neutral, objective, impersonal scientific voice. Present
the problem, results, evidence and limitations as a coherent account for a reader who has
never seen the drafting or review history. Do not expose the author's internal dialogue,
abandoned drafting plans, repeated revision negotiations or responses to a local self-review.
In particular, exclude claims such as "this should interest readers", "this should pass
editorial screening", "this revision adds ...", or "this satisfies the self-review requirement".
State the demonstrated scientific difference and its consequences instead of predicting
reader interest or editorial acceptance. Do not replace these claims with inflated importance
language.

Keep revision chronology, item-by-item review responses, author checklists and editorial
strategy in private records or response letters, outside the scientific manuscript. Retain
scientifically necessary methods, reproducibility information, limitations, negative findings,
citations and truthful AI/author disclosures; removing process narration must not hide evidence
or uncertainty. Before freezing each revised manuscript, reread its abstract, introduction,
body, discussion and conclusion for this boundary, including text inherited from earlier rounds.
Record located defects and repairs in the private revision record. Independent reviewers must
check the current manuscript itself and require repair when this narration remains.

Save a private revision record with the manuscript version/hash, located issues, structural
changes, before/after passages where useful, fidelity checks and remaining gaps. Keep it
outside the public paper and fresh full-review packet. Follow the repository review router
for any revised manuscript; an author's readability pass is not an independent gate pass.

## Referee mode: reconstruct without the author's explanation

Read the manuscript as a new specialist reader. Before scoring clarity, independently
state the question, central result and scope, difference from the closest work, and the
main steps supporting the result. Attach manuscript locations to that reconstruction.
Explicitly say which parts cannot be recovered. Do not use the author's private checklist,
earlier scores or an editor's verdict to supply missing explanations.

Inspect the abstract, introduction, central argument and conclusion for agreement. For
each material problem give its location, the failed inference or missing explanation,
and a concrete acceptance condition. Distinguish:

- scientific gaps requiring evidence or a changed claim;
- substantial exposition repairs required to understand or assess an existing argument;
- bounded local corrections;
- optional stylistic preferences.

Record the reconstruction and findings in `section_feedback` using the existing schema;
put required repairs in `required_changes` and unresolved blockers in `unresolved_blockers`.
Set `text_ready: false` when substantial exposition repairs remain. For journal decisions,
a paper needing structural reconstruction of its abstract, introduction or central argument
cannot receive `minor_revision` merely because no new science was requested. Do not infer
that a proof is false solely because its exposition is poor; keep soundness and clarity distinct.
Apply the existing significance standard separately. Stop at the configured review budget.

## Sources and limits

Consulted on 2026-09-26: [Humanizer](https://github.com/blader/humanizer/blob/main/SKILL.md)
for identifying empty rhetoric and repetitive structure, and
[Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills)
for scientific writing and peer-review practices. These are editorial aids, not evidence
that a manuscript was AI-generated or that a revision is correct. This skill is an original
paper-specific procedure; it does not import upstream hooks or blanket punctuation rules.
Keep meaningful contrasts, technical hyphens, names such as Erdős–Selfridge, and legitimate
uncertainty. Never optimize prose to evade authorship detection.
