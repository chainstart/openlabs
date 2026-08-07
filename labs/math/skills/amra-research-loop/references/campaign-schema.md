# Campaign schema

## Canonical files

- `campaign_state.json`: Identity, current phase, gate thresholds, artifact map, and append-only transition history.
- `closure_contract.json`: Exact statement, source, success conditions, and outcomes that do not count.
- `information_loss_map.json`: Inherited methods and their precise information losses.
- `representations.json`: Candidate representations with new information and first test.
- `mechanisms.json`: Decisive candidate claims and their status.
- `kill_tests.json`: Evidenced falsification records keyed by mechanism id.
- `survivors.json`: One to three selected mechanisms and rationale.
- `decisive_lemma.json`: Strongest deepened claim, status, closure effect, evidence, and gaps.
- `audit.json`: Independent reconstruction and statement, dependency, and novelty checks.
- `decision.json`: Promotion or freeze decision tied to the closure contract.

## Core commands

Initialize:

```bash
python3 amra-research-loop/scripts/research_loop.py init \
  --root amra-research-loop/campaigns \
  --campaign-id erdos-809-potential \
  --problem-id erdos-809 \
  --title "Global reserve potential" \
  --statement "Exact public statement" \
  --source "Primary source URL or repository path"
```

Validate and advance:

```bash
python3 amra-research-loop/scripts/research_loop.py validate --campaign <path>
python3 amra-research-loop/scripts/research_loop.py advance --campaign <path> --to <next-phase>
```

Record mechanisms through `add-mechanism`; use `set-mechanism-status` after an evidenced test. When marking a mechanism `killed`, add a matching entry to `kill_tests.json` with `outcome: "killed"` and nonempty `evidence`.

Freeze through the CLI so transition history and `decision.json` remain synchronized.
