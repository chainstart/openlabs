---
name: openlabs-asset-retrospective
description: After a research-program topic reaches ready_queue or is frozen, propose the few reusable assets (scripts, pipelines, figure code, short lessons, negative results) that would save a later topic time. Use only in an OpenLabs topic_retrospective task.
---

# OpenLabs asset retrospective

The topic is finished. The packet at the input path names its workspace, its results, the
review and decision records, and the current asset index summary. Your job is to leave behind
what the next topic should not have to rediscover. Nothing here is a rule for later agents; it
is a shelf they may take from.

## What is worth keeping

Something a later topic would otherwise spend real time on: a data loader that handles the
source's quirks, an analysis or statistics template with the matched baseline already wired, a
figure script, an end-to-end pipeline, or a fact about the environment or a data source. Skip
anything specific to this one question, anything the index already has (improve that entry
instead by proposing a new version with the same kind and data sources), and anything you
would not trust yourself. Fewer, better entries; an empty `asset_proposals` is a valid result.

## How to write an entry

- `title` and `summary`: one line each. Someone scanning a list of forty must be able to tell
  whether it fits their data and question: say what goes in, what comes out, and the data source.
- `domains`, `data_sources` (DOI or URL, the same identifiers topic cards use), `methods`.
- Lessons and negative results state facts and their cause ("source X returns 403 from this
  host; the Y mirror serves the same version"), not instructions.
- Tool kinds (`data_loader`, `analysis`, `figure`, `pipeline`): `source_paths` inside the topic
  workspace, or `artifact:<artifact_id>` for a cleaned-up copy you return as a result artifact;
  `entrypoint` and `usage` (how to run it, one or two lines); `requirements` (packages, CPU,
  memory, network). Then run one minimal verification yourself, inside the resource guard and on
  a small sample, save `{"command": ..., "exit_code": ..., "output_tail": ...}` as a JSON file, add
  it as a hash-bound artifact, and set `verification: {command, receipt: {path, sha256}}`. A
  tool without a passing receipt is not registered.
- `lesson`: `body` of at most 1500 characters.
- `negative_result` (required when the topic was frozen): `negative: {question, attempted,
  why_failed, retry_when[]}`, where `retry_when` uses the ledger's reopen-condition types
  (`new_data_source`, `new_method`, `venue_policy_change`, `external_result`) and should match
  the topic's recorded `reopen_conditions`.

Do not change the topic workspace, the index or the registry; the control plane registers what
passes its checks and reports the rest.
