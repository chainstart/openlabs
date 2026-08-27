---
name: amra-research-loop
description: Run mechanism-first, stateful mathematics research campaigns with explicit closure contracts, information-loss diagnosis, representation search, adversarial falsification, decisive-lemma promotion, and independent audit. Use for selecting, starting, continuing, reviewing, promoting, or freezing an AMRA open-problem research campaign, especially when existing work is accumulating local lemmas without moving the original theorem, main term, or exponent.
---

# AMRA Research Loop

Use this package as the mathematics lab's mechanism-first research supervisor. The package is
immutable code; keep mutable campaign state in the task's declared OpenLabs campaign directory,
normally `$OPENLABS_WORKSPACE/openlabs-data/workspaces/math/<campaign-id>/`. Never write campaign state into
this Skill directory and never write directly to the factory SQLite database.

## Start or resume

1. Locate the package root from this `SKILL.md`.
2. Read the OpenLabs task file and use its `input_path` as the campaign directory. If the task is
   explicitly an initialization task, create that directory with `scripts/research_loop.py init`.
3. Read `campaign_state.json` and every artifact required by the current phase.
4. Read [phase-gates.md](references/phase-gates.md) before changing phase.
5. Execute only work allowed in the current phase.
6. Persist claims, mechanisms, kill tests, evidence, and decisions as structured JSON.
7. Run `validate` before `advance`. Treat a failed gate as a research result, not as permission to weaken the contract.

The adjacent `authority-policy.json` is the machine-readable role boundary consumed by both the
Codex Stop hook and the scheduler. In particular, entering `independent_audit` transfers authority
to a blank `reviewer`; never try to continue that phase in the creator session.

Use:

```bash
python3 "$OPENLABS_WORKSPACE/openlabs/labs/math/skills/amra-research-loop/scripts/research_loop.py" status \
  --campaign "$OPENLABS_WORKSPACE/openlabs-data/workspaces/math/<campaign-id>"

python3 "$OPENLABS_WORKSPACE/openlabs/labs/math/skills/amra-research-loop/scripts/research_loop.py" validate \
  --campaign "$OPENLABS_WORKSPACE/openlabs-data/workspaces/math/<campaign-id>"
```

## Follow the state machine

Work through exactly one transition at a time:

```text
target_selection
  -> obstruction_analysis
  -> representation_search
  -> mechanism_falsification
  -> survivor_deepening
  -> independent_audit
  -> promotion
```

Freeze from any nonterminal phase when no surviving route justifies further allocation. Never skip a phase or edit `campaign_state.json` to bypass a failed gate.

The OpenLabs task is one bounded research episode. Protocol phases are durable recovery and audit
records, not process boundaries. Within one researcher or experimenter authority, autonomously
perform multiple derivations, representation checks, kill tests, and validated phase transitions
for as long as useful work and the task wall budget remain. Do not stop merely because a phase
advanced. Stop at an epistemic-role boundary, a terminal outcome, a genuine blocker, or when the
remaining wall budget is needed to persist a recoverable checkpoint. Never cross into independent
audit in the creator session. At the end, atomically write the required
`openlabs.result_bundle.v1` file. Refer to changed campaign files and computational evidence by URI
and SHA-256; the orchestrator alone decides the factory task transition.

## Enforce the research contract

- Preserve the exact public statement, source, quantifiers, and success conditions.
- Identify the precise step where inherited methods lose information before extending them.
- Generate mechanisms from genuinely different representation families. Read [mechanism-archetypes.md](references/mechanism-archetypes.md) during representation search.
- Give every mechanism a decisive claim, claimed closure effect, and first kill test.
- Falsify aggressively and retain at most three mechanisms.
- Promote only an original-problem closure, main-term or main-exponent improvement, global-interface closure, or standalone decisive lemma.
- Require independent reconstruction and statement, dependency, and novelty checks before promotion.
- Apply [evidence-policy.md](references/evidence-policy.md) whenever classifying a result.

For a major open problem, make a paper-scale intermediate theorem the default research target.
Before representation search, write a research memo containing the frozen theorem statement,
published comparator, admissible analytic inputs, expected closure effect, and at least one explicit
false-world control where the proposed mechanism must fail. Explore genuinely different mechanisms
in isolation and preserve a survivor ledger, but allow a failed mechanism to be inverted when the
failure exposes a new provable quantity. Once a theorem candidate appears, stop broad ideation and
run disjoint hostile checks: blind re-derivation, hypothesis/prime-side audit, linear-algebra or
counting audit, counterexample search, and live literature comparison. Formalization is an
additional validation layer after the mathematical statement stabilizes; it never replaces
novelty or analytic-input checks.

For Lean-capable statements, follow [lean-verification.md](references/lean-verification.md). Keep
project `.lean` sources and receipts in the active AMRA campaign's `formal/lean/` directory. A
formalization may be marked `passed` only from an `openlabs.lean_verification.v1` receipt produced by
the trusted verifier; the domain protocol will replay it before promotion. Never treat an imported
Lean theorem, a source-code search, or an LLM assertion as a kernel check.

For exact algebra, certified numerics, and finite constraint solving, follow
[computation-verification.md](references/computation-verification.md). Use the prepared Sage, Arb,
or dual-SMT profile and preserve its v1 receipt. Never call a floating-point run exact, treat a ball
enclosure as coverage of an unproved analytic tail, or promote an SMT answer beyond the proved
encoding scope.

Do not count file volume, test count, agent-hours, finite examples, another local branch, a conditional bridge, or another normal form as mathematical promotion.

## Modify artifacts safely

Read [campaign-schema.md](references/campaign-schema.md) before editing state artifacts. Prefer the CLI for initialization, phase transitions, mechanism creation, mechanism status changes, and freezing. Directly edit mathematical content files only when the CLI has no content-entry command, then run `validate`.

Keep computational evidence in `evidence/` and independent audit material in `audit/`. Do not overwrite author evidence during blind reconstruction.

Keep small sources, typed receipts, proof text, and audit summaries in those campaign directories.
Put raw solver output, bulk enumeration, large JSON/JSONL, arrays, archives, and binary payloads in
`transaction.artifact_staging_root`. Every staged payload must be declared with URI and SHA-256 in
the result; never write it directly to the live artifact store.

## End each research turn

Report:

- current phase;
- artifacts changed;
- mechanisms killed or retained and why;
- exact gate result;
- next permitted action;
- whether the original problem, main term, or main exponent changed.

If no promotion condition moved, say so explicitly.
