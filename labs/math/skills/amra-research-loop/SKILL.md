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

The OpenLabs task is one bounded research episode, not permission to run the whole phase graph. You
may autonomously perform multiple derivations, representation checks, and kill tests inside the
current phase, but cross at most one formal phase boundary and never cross an epistemic-role
boundary. At the end, atomically write the required `openlabs.result_bundle.v1` file. Refer to
changed campaign files and computational evidence by URI and SHA-256; the orchestrator alone
decides the factory task transition.

## Enforce the research contract

- Preserve the exact public statement, source, quantifiers, and success conditions.
- Identify the precise step where inherited methods lose information before extending them.
- Generate mechanisms from genuinely different representation families. Read [mechanism-archetypes.md](references/mechanism-archetypes.md) during representation search.
- Give every mechanism a decisive claim, claimed closure effect, and first kill test.
- Falsify aggressively and retain at most three mechanisms.
- Promote only an original-problem closure, main-term or main-exponent improvement, global-interface closure, or standalone decisive lemma.
- Require independent reconstruction and statement, dependency, and novelty checks before promotion.
- Apply [evidence-policy.md](references/evidence-policy.md) whenever classifying a result.

Do not count file volume, test count, agent-hours, finite examples, another local branch, a conditional bridge, or another normal form as mathematical promotion.

## Modify artifacts safely

Read [campaign-schema.md](references/campaign-schema.md) before editing state artifacts. Prefer the CLI for initialization, phase transitions, mechanism creation, mechanism status changes, and freezing. Directly edit mathematical content files only when the CLI has no content-entry command, then run `validate`.

Keep computational evidence in `evidence/` and independent audit material in `audit/`. Do not overwrite author evidence during blind reconstruction.

## End each research turn

Report:

- current phase;
- artifacts changed;
- mechanisms killed or retained and why;
- exact gate result;
- next permitted action;
- whether the original problem, main term, or main exponent changed.

If no promotion condition moved, say so explicitly.
