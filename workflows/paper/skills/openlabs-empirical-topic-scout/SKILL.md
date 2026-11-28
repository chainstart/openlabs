---
name: openlabs-empirical-topic-scout
description: Scout computational, real-data research topics and write a <=1-page Proposal Brief plus 6 minimal machine fields for independent cross-family review. Use only in an OpenLabs topic_scout task.
---

# Topic Proposal Brief (<= 1 page)

Read the scout packet at the input path (`ledger_snapshot`, `research_line_summary`, `line_tools`, `data_catalog`, and — on templated lines — `queue_candidates`). Return up to `max_proposals` proposals in `topic_proposals[]`. An empty list is valid if nothing clears the bar. Do not start the full study.

You are explicitly authorized to start helper sub-agents in parallel to survey several fields or directions. Use the tools available in your runtime (Codex `spawn_agent` or `codex exec`, the Claude Agent tool, or Antigravity `invoke_subagent`) and return the best proposals.

## Rules
- **Templated lines with `queue_candidates`**: draw from `queue_candidates` FIRST using the line's `line_tools` and `data_catalog`. Set `queue_entry_id` to the candidate's `entry_id` (and `reopens` if reopening a listed topic). Propose outside the queue only if the candidates are unsuitable.
- **Open lines without `queue_candidates`**: search recent literature and `data_catalog` broadly; aim for high-ambition, broad-significance computational questions (Nature Communications level of ambition).
- **Computational & free data only**: never propose wet-lab work, paid datasets, or `restricted` sources. Free registration-gated sources (`form_or_registration`) are allowed if you record `registration` so the user can register them (and note whether the kill test can run on directly available data).
- **No duplicates**: check `ledger_snapshot`; do not repeat active, admitted, proposed, or judged-rejected questions unless citing `reopens`.

## Proposal Brief Template (`brief`, <= 6000 chars)

Write concise, honest natural language covering these 6 sections (do not fill legacy 30-field schemas or predict journal tiers):

```markdown
## 1. Research Question
One clear, falsifiable sentence stating what you want to establish or test.

## 2. Why It Matters (and to Whom)
What decision, consensus, or scientific understanding changes if the answer is yes or no, and which research or policy community cares. Aim high (Nature Communications level of ambition on open lines; sound systematic contribution on templated lines).

## 3. Closest Prior Work & What Is New
Name the 2–5 closest published papers or recent preprints (with DOI/URL and year), what each already showed, and the concrete increment this study adds beyond them.

## 4. Data Sources & Access
List every decisive dataset: name, URL/DOI or catalogue ID, how it is obtained (`direct` / `form_or_registration` / `restricted`), whether it is free, and explicitly note any decisive field/variable that is missing or uncertain in the public release. Never propose paid or restricted sources. If a free source needs registration, state what to register and whether the first test can run on directly available data.

## 5. First Decisive Test (Kill Test)
The cheapest real-data computation (typically <= 2–4 CPU core-hours or <= 30 min GPU on a subset/sample) the topic owner should run first to verify that the data, key signal, and baseline comparison actually work before spending heavy compute.

## 6. What Result Would Kill This Topic
One concrete, quantitative stop condition: what observed outcome in the first decisive test (missing key field, null/baseline explaining the signal, failure to reproduce control, or negligible effect) immediately freezes the topic.
```

## Output (`openlabs.result_bundle.v1`, status `succeeded`)

Return `topic_proposals`: array of objects, each with **6 minimal fields**:
```json
{
  "schema_version": "openlabs.topic_proposal.v1",
  "research_line": "<line_id>",
  "question": "One-sentence falsifiable research question.",
  "brief": "## 1. Research Question\n...",
  "data_sources": [
    {"id_or_url": "https://...", "access": "direct | form_or_registration", "catalog_id": "optional", "registration": "optional"}
  ],
  "compute_estimate": {"locations": ["container_cpu"], "data_gb": 5, "agent_hours": 8},
  "queue_entry_id": null,
  "reopens": null
}
```
Leave `paper_candidate: false` and `next_actions: []`.
