# Target-specific editorial screen

The manuscript review tests validity, clarity, and the generic CAS Zone 1 standard. It does not
predict whether an editor at a named journal will send the paper to referees. After repeated
editorial rejections, journal release also requires a separate screen of **research contribution
and readership at the selected target**. This screen is a conservative internal decision, not an
acceptance forecast or external peer review.

## Procedure

1. Freeze the canonical source and PDF. Run the ordinary independent scientific review. Keep its
   full scores, including negative findings.
2. In a separate independent context, give the screener the current manuscript, exact selected
   journal, at least two recent articles from that journal, at least two closest research results,
   and **all available distinct editorial decision letters** for this paper or its predecessors.
   Label editor comments, internal interpretations, and absent reasons separately. The reviewer
   must inspect primary literature and state the exact advance under matching assumptions.
3. Test the title, abstract, theorem/experimental result, novelty, effect or theorem reach,
   and readership together. Record the strongest plausible reason for an editor to decline without
   review. A desk rejection for narrow scope is addressed only by a concrete new result or a
   supported demonstration of why the existing result matters to that journal's readers.
4. If new proof, analysis, data, experiments, comparison, or conceptual framing is required, set
   `decision: research_required`, list the work in `required_scientific_work`, and keep the paper
   out of `ready`. Do not turn a research requirement into a prose-only task or move to a lower
   ranked journal solely to obtain a passing record.
5. When the scientific case is complete, write a JSON receipt under `reviews/editorial-screens/`
   and register its data-root-relative path at `registry/papers/<paper_id>.yaml` under
   `editorial_screen.source`. Run `review apply` again. The gate binds the receipt hash to the
   manuscript snapshot; release handoff rechecks the record and hash.

The required receipt is an object with these fields:

```json
{
  "schema_version": "openlabs.paper_writing.editorial_screen.v1",
  "paper_id": "<registered paper ID>",
  "manuscript_snapshot_sha256": "<current canonical manuscript/PDF snapshot>",
  "target_journal": "<exact registered title>",
  "decision": "pass",
  "independent_context": true,
  "prior_rejections_reviewed": true,
  "reviewed_at_utc": "<UTC timestamp>",
  "reviewer_model": "<actual runtime model>",
  "contribution": "<specific new result under matching assumptions>",
  "why_target_readers_care": "<evidence-based audience case>",
  "research_depth": "<substantive reach beyond close work>",
  "editorial_risk": "<strongest remaining desk-reject risk>",
  "required_scientific_work": [],
  "closest_work": [
    {"source": "https://example.org/primary-paper-1", "known_result": "...", "advance": "..."},
    {"source": "https://example.org/primary-paper-2", "known_result": "...", "advance": "..."}
  ],
  "target_articles": [
    "https://example.org/target-article-1",
    "https://example.org/target-article-2"
  ],
  "rejection_responses": [
    {"decision_source": "<registered decision source or anticipated>",
     "concern": "<actual or anticipated editorial concern>",
     "current_evidence": "<specific revised result or comparison>",
     "remaining_limit": "<truthful limit>"}
  ]
}
```

The mechanical validator checks presence, target/snapshot binding, source URLs, and unresolved
work. It cannot establish that a cited result is accurately understood or that an editor agrees.
The screener must make that substantive judgment. Historical `ready` entries remain in the audit
trail; the current handoff rejects them until this screen is complete and bound by a new gate run.
