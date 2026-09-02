# Review record schema

Each independent reviewer writes one JSON object using schema `ara.paper_writing.review.v2`.
Scores are integers. Every source contains one role-specific high-standard opinion and one CAS
Zone 1 journal opinion. Under the default contract, after the fresh Codex reviewer finishes, write
one panel object using schema `openlabs.paper_writing.review.single.v1`; it preserves the common
review shape, contains the unchanged one-member coordinatewise and ordinal medians, and identifies
the sole immutable Codex source. When the registry explicitly selects the optional two-reviewer
contract, add the blind Packy Claude reviewer and write schema
`openlabs.paper_writing.review.v1`; that panel contains the exact conservative aggregation and
identifies both immutable source records.

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
    "isolated_process": true,
    "prior_reviews_hidden": true
  }
}
```

Only under the explicitly configured two-reviewer contract, for `reviewer-2` set
`provider: "packy"`, `model: "claude-opus-5"`, and
`panel_reviewer_id: "reviewer-2"`, and add `hidden_peer_review_sha256` with the frozen SHA-256 of
`reviewer-1.json`. The adapter hashes that file but never includes its content in Claude's prompt.
Both records must describe the same frozen manuscript and must not access sibling or historical
review content.

In the default one-reviewer mode, omit reviewer-2 and its hidden-peer binding. The sole source remains
`reviewer-1.json` with provider `openai-codex`; the panel uses
`openlabs.paper_writing.review.single.v1`, `panel_size: 1`,
`score_aggregation: coordinatewise_median`, and `decision_aggregation: ordinal_median`.

## Panel result

For the default contract, copy the common fields from `reviewer-1.json` into `review.json` without
altering any judgment, set `schema_version` to `openlabs.paper_writing.review.single.v1`, and add
this object inside `review_metadata`:

```json
{
  "review_panel": {
    "panel_size": 1,
    "score_aggregation": "coordinatewise_median",
    "decision_aggregation": "ordinal_median",
    "parallel_execution": false,
    "independent_contexts": true,
    "isolated_processes": true,
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
      }
    ]
  }
}
```

Omit `shared_objective_audits` when no formal-tool audit is in scope. When Lean/mathlib is in
scope, it contains exactly one PASS receipt created by the bounded objective checker. The panel
validator verifies the receipt hash, snapshot and support bindings, the formal-validation execution
over the hash-linked receipt chain, source hashes, dynamic host-memory headroom, and repository
resource ceilings. It does not rerun Lean.

For default panel metadata, use `model: "single-reviewer-median-panel"` and describe the mechanical
one-member aggregation in `reasoning_effort`. Under the optional two-reviewer contract instead use
schema `openlabs.paper_writing.review.v1`, `panel_size: 2`,
`score_aggregation: coordinatewise_minimum`, `decision_aggregation: strictest_decision`, and model
`codex-plus-claude-opus-5-conservative-panel`. Include both reviewer records, set every score to the
lower source value, take the less favorable decision, and retain the union of blockers and required
changes. The validator then verifies both provider/model identities, hashes, common snapshots, the
frozen-peer binding, score minima, and strictest decisions mechanically. Historical
`ara.paper_writing.review.v3` three-review median panels remain valid read-only records.

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
`openlabs.paper-writing.physics-explicit-highest-tier-venues.v1`, read
`physics-highest-tier-venues.md`, and use:

```json
{
  "leading_physics_journals": {
    "benchmark_id": "openlabs.physics-highest-tier-original-research.v1",
    "benchmark_venues": [
      "physical_review_letters",
      "physical_review_x",
      "nature_physics"
    ],
    "best_fit_venue": "physical_review_letters",
    "score": 5,
    "decision": "reject",
    "confidence": "medium",
    "rationale": "best-fit explanation after all three simulations",
    "venue_reviews": {
      "physical_review_letters": {
        "score": 5,
        "decision": "reject",
        "confidence": "high",
        "simulated_stage": "editorial_screen",
        "criterion_route": "none",
        "criteria_scores": {
          "novelty": 6,
          "importance": 5,
          "broad_interest": 4,
          "presentation": 6,
          "standalone_letter_fit": 5
        },
        "rationale": "PRL-specific explanation"
      },
      "physical_review_x": {
        "score": 4,
        "decision": "reject",
        "confidence": "high",
        "simulated_stage": "editorial_screen",
        "criterion_route": "none",
        "criteria_scores": {
          "innovation": 6,
          "quality": 7,
          "long_term_impact": 4,
          "broad_physics_interest": 4,
          "criterion_route_strength": 3
        },
        "rationale": "PRX-specific explanation"
      },
      "nature_physics": {
        "score": 3,
        "decision": "reject",
        "confidence": "high",
        "simulated_stage": "editorial_screen",
        "criterion_route": "none",
        "criteria_scores": {
          "originality": 6,
          "fundamental_or_applied_importance": 4,
          "expert_excitement": 5,
          "physics_breadth": 3,
          "long_term_importance": 4
        },
        "rationale": "Nature Physics-specific explanation"
      }
    }
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
