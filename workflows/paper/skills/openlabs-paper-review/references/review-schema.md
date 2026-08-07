# Review record schema

Each independent agent writes one JSON object using schema `ara.paper_writing.review.v2`. Scores
are integers. Every source review contains one role-specific high-standard opinion and one CAS
Zone 1 journal opinion. After all three agents finish, write one panel object using schema
`ara.paper_writing.review.v3`; it preserves the common review shape, contains the exact medians,
and identifies the three immutable source records.

The individual record shape is:

```json
{
  "schema_version": "ara.paper_writing.review.v2",
  "scores": {
    "clarity": 1,
    "soundness": 1,
    "significance": 1,
    "novelty": 1,
    "overall": 1
  },
  "strengths": ["specific strength"],
  "weaknesses": ["specific weakness"],
  "section_feedback": {
    "introduction": "specific feedback using the manuscript's actual section keys"
  },
  "required_changes": ["concrete required change"],
  "change_requests": [
    {
      "request": "concrete request",
      "category": "text_only",
      "priority": "high",
      "targets": ["introduction"],
      "rationale": "why it matters",
      "text_only": true
    }
  ],
  "unresolved_blockers": [],
  "recommendations": {},
  "publishability_summary": {
    "text_ready": false,
    "scientific_ready": false,
    "blocking_reason": "empty only when no blocker remains"
  },
  "review_metadata": {
    "paper_id": "<paper_id>",
    "reviewer_role": "<role>",
    "score_kind": "ara_llm_self_review",
    "rubric_id": "<role-specific rubric ID>",
    "recommendation_schema_version": "ara.review_recommendations.v2",
    "cas_zone_1_basis": {
      "scope": "major_category",
      "mode": "generic_standard",
      "target_journal": null,
      "classification_source": null,
      "classification_checked_at": null
    },
    "not_external_peer_review": true,
    "simulated_venue_decisions": true,
    "review_only": true,
    "model": "<model>",
    "reasoning_effort": "<effort>",
    "reviewed_at_utc": "<ISO-8601 UTC>",
    "main_tex_sha256": "<64 lowercase hexadecimal characters>",
    "manuscript_snapshot_sha256_before": "<hash>",
    "manuscript_snapshot_sha256_after": "<same hash when unchanged>",
    "manuscript_unchanged": true,
    "panel_reviewer_id": "reviewer-1",
    "independent_context": true,
    "prior_reviews_hidden": true
  }
}
```

Use the same shape for `reviewer-2` and `reviewer-3`, changing only each reviewer's independent
judgments, metadata, and stable reviewer ID. All three records must describe the same frozen
manuscript snapshot and must be produced in parallel without access to sibling or historical
reviews.

## Panel result

Copy the common fields into `review.json`, set `schema_version` to
`ara.paper_writing.review.v3`, and set every score to the coordinate-wise median of the three
individual values. Set each role-specific decision to its ordinal median using the decision order
in the rubric. The coordinating context writes evidence-based consensus prose and retains every
confirmed or unresolved blocker. Add this object inside `review_metadata`:

```json
{
  "review_panel": {
    "panel_size": 3,
    "score_aggregation": "coordinatewise_median",
    "decision_aggregation": "ordinal_median",
    "parallel_execution": true,
    "independent_contexts": true,
    "prior_reviews_hidden": true,
    "shared_objective_audits": [
      {
        "kind": "lean_mathlib",
        "source": "reviews/objective-audits/<paper_id>/<snapshot>/lean.json",
        "sha256": "<SHA-256 of the immutable receipt>",
        "status": "PASS",
        "manuscript_snapshot_sha256": "<same frozen snapshot>",
        "support_package_sha256": "<current support archive SHA-256>"
      }
    ],
    "reviewer_records": [
      {
        "reviewer_id": "reviewer-1",
        "source": "reviews/<run>/<paper_id>/reviewer-1.json",
        "sha256": "<SHA-256 of reviewer-1.json>"
      },
      {
        "reviewer_id": "reviewer-2",
        "source": "reviews/<run>/<paper_id>/reviewer-2.json",
        "sha256": "<SHA-256 of reviewer-2.json>"
      },
      {
        "reviewer_id": "reviewer-3",
        "source": "reviews/<run>/<paper_id>/reviewer-3.json",
        "sha256": "<SHA-256 of reviewer-3.json>"
      }
    ]
  }
}
```

Omit `shared_objective_audits` when no formal-tool audit is in scope. When Lean/mathlib is in
scope, it contains exactly one PASS receipt created by the bounded objective checker. The panel
validator verifies the receipt hash, snapshot and support bindings, one formal-validation execution
over the hash-linked receipt chain, source hashes, two sequential commands, dynamic host-memory
headroom, and repository resource ceilings. It does not rerun Lean.

For the panel metadata, use `model: "three-agent-median-panel"` and describe the coordinating
aggregation in `reasoning_effort`. Do not claim the coordinator is a fourth independent reviewer.
The validator loads the three sources, verifies their hashes and common snapshots, and checks all
score and decision medians mechanically.

For `ai`, `cs`, and `se`, set `reviewer_role` to `cs_top_tier`, set `rubric_id` to
`ara.revision-agent.cs-top-tier.v1`, and replace `recommendations` with:

```json
{
  "top_conference": {
    "seven_point": {
      "decision": "borderline",
      "confidence": "medium",
      "rationale": "top-conference-specific explanation"
    }
  },
  "cas_zone_1_journal": {
    "decision": "minor_revision",
    "confidence": "medium",
    "rationale": "independent CAS Zone 1 journal explanation"
  }
}
```

For `math`, set `reviewer_role` to `math`, set `rubric_id` to
`ara.paper-writing.math-four-journals.v1`, and replace `recommendations` with:

```json
{
  "four_top_math_journals": {
    "decision": "reject",
    "confidence": "high",
    "rationale": "four-leading-journal-specific explanation"
  },
  "cas_zone_1_journal": {
    "decision": "major_revision",
    "confidence": "medium",
    "rationale": "independent CAS Zone 1 journal explanation"
  }
}
```

Mathematics records must not contain `top_conference` or legacy `conference` recommendations.
High-standard and CAS Zone 1 decisions are independent; they need not differ, and no deterministic
offset is permitted.

For `materials`, set `reviewer_role` to `materials`, set `rubric_id` to
`openlabs.paper-writing.materials-leading-journals.v1`, and use:

```json
{
  "leading_materials_journals": {
    "decision": "major_revision",
    "confidence": "medium",
    "rationale": "materials-evidence-specific explanation"
  },
  "cas_zone_1_journal": {
    "decision": "minor_revision",
    "confidence": "medium",
    "rationale": "independent CAS Zone 1 explanation"
  }
}
```

Use `cas_zone_1_basis.mode: generic_standard` when no particular journal's current classification
has been verified. Use `verified_target` only with non-empty `target_journal`,
`classification_source`, and `classification_checked_at`. A formatting target is not classification
evidence.

Confidence must be `high`, `medium`, or `low`. Priorities must be `high`, `medium`, or `low`.
`text_only` is true only when no new proof work, experiment, data, quantitative analysis, figure, or
formalization artifact is required. AI/computing request categories may include `text_only`,
`title_abstract_scope`, `related_work`, `method_clarification`, `new_experiment`, `new_analysis`,
`new_figure`, `new_data_or_model`, and `missing_baseline`. Mathematics may additionally use
`proof_exposition`, `proof_gap`, `theorem_scope`, `formalization_artifact`, and
`submission_compliance`.
