# Review record schema

Each independent reviewer writes one JSON object using schema `ara.paper_writing.review.v2`.
Scores are integers. Every source contains one role-specific high-standard opinion and one CAS
Zone 1 journal opinion. Under the default contract, after the Codex and Packy Claude reviewers
finish, write one panel object using schema `openlabs.paper_writing.review.v1`; it preserves the
common review shape, contains the exact conservative aggregation, and identifies both immutable
source records. When the paper-local registry explicitly selects a one-reviewer panel, write schema
`openlabs.paper_writing.review.single.v1`; it contains the unchanged one-member coordinatewise and
ordinal medians and identifies the sole immutable Codex source.

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
    "provider": "openai-codex",
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

For `reviewer-2`, set `provider: "packy"`, `model: "claude-opus-5"`, and
`panel_reviewer_id: "reviewer-2"`, and add `hidden_peer_review_sha256` with the frozen SHA-256 of
`reviewer-1.json`. The adapter hashes that file but never includes its content in Claude's prompt.
Both records must describe the same frozen manuscript and must not access sibling or historical
review content.

In one-reviewer mode, omit reviewer-2 and its hidden-peer binding. The sole source remains
`reviewer-1.json` with provider `openai-codex`; the panel uses
`openlabs.paper_writing.review.single.v1`, `panel_size: 1`,
`score_aggregation: coordinatewise_median`, and `decision_aggregation: ordinal_median`.

## Panel result

Copy the common fields into `review.json`, set `schema_version` to
`openlabs.paper_writing.review.v1`, and set every score to the lower of the two individual values.
Set each role-specific decision to the less favorable of the two using the decision order in the
rubric. Retain every distinct blocker and required change. Add this object inside
`review_metadata`:

```json
{
  "review_panel": {
    "panel_size": 2,
    "score_aggregation": "coordinatewise_minimum",
    "decision_aggregation": "strictest_decision",
    "parallel_execution": false,
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
        "provider": "openai-codex",
        "model": "<actual Codex model>",
        "source": "reviews/<run>/<paper_id>/reviewer-1.json",
        "sha256": "<SHA-256 of reviewer-1.json>"
      },
      {
        "reviewer_id": "reviewer-2",
        "provider": "packy",
        "model": "claude-opus-5",
        "source": "reviews/<run>/<paper_id>/reviewer-2.json",
        "sha256": "<SHA-256 of reviewer-2.json>"
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

For panel metadata, use `model: "codex-plus-claude-opus-5-conservative-panel"` and describe the
mechanical aggregation in `reasoning_effort`. The validator loads both sources, verifies their
provider/model identities, hashes, common snapshots, and the frozen-peer binding, then checks all
score minima and strictest decisions mechanically. Historical `ara.paper_writing.review.v3`
three-review median panels remain valid read-only records.

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

For `quant`, set `reviewer_role` to `quant_finance`, set `rubric_id` to
`openlabs.paper-writing.quant-finance-leading-journals.v1`, and use:

```json
{
  "leading_quant_finance_journals": {
    "decision": "major_revision",
    "confidence": "medium",
    "rationale": "point-in-time, search, execution, and finance-contribution explanation"
  },
  "cas_zone_1_journal": {
    "decision": "minor_revision",
    "confidence": "medium",
    "rationale": "independent CAS Zone 1 explanation"
  }
}
```

For `physics`, set `reviewer_role` to `physics`, set `rubric_id` to
`openlabs.paper-writing.physics-leading-journals.v1`, and use:

```json
{
  "leading_physics_journals": {
    "decision": "major_revision",
    "confidence": "medium",
    "rationale": "physics-correctness, evidence, novelty, and significance explanation"
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
`submission_compliance`. Quantitative-finance requests may additionally use `data_vintage`,
`search_multiplicity`, `execution_assumptions`, `capacity`, `factor_exposure`, and
`independent_replication`.
