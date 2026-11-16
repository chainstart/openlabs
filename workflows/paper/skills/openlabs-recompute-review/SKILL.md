---
name: openlabs-recompute-review
description: "Independent recompute review of a topic owner's manuscript: take the data and result files it cites, recompute the core results yourself along the research line's checklist, and return a structured verdict (accept, minor, major, reject) with required items and your recompute scripts."
---

# OpenLabs recompute review

You review a manuscript written by a topic owner of another model (family). You are not the
author and you start from a fresh session. This review is the quality loop inside the owner's
work; the unified review (`paper-writing review unified-run`, skill `openlabs-paper-review`)
comes afterwards and is the formal gate before delivery. Do not run it, and do not edit the
manuscript, the campaign workspace or the registry.

The input packet names the owner's result, the campaign workspace (read only), the research
state with the pre-registration, the line specification, the checklist and the earlier rounds
with the author's response.

## What to do

1. Do not start from the manuscript's prose. Find the data and result files the manuscript
   cites (time series, posterior chains, profile files, tables, scripts) and recompute the core
   results with your own scripts, item by item along `checklist` (the line's own list when it
   has one, otherwise the generic list).
2. For every item write one outcome: `reproduced`, `not_reproduced` (by how much) or
   `could_not_reproduce` (what is missing). A value you could not check goes in `unverified`;
   never mark it reproduced.
3. In a later round, check each `required` item of `previous_rounds` against the author's
   response (`owner_response`) and the current files: resolved, partly, not resolved.
4. Keep the scripts and their outputs in your large-outputs directory; list their paths in
   `scripts`. Long jobs go to ailab (`bin/openlabs-remote`) like any other heavy work.
5. Out of scope here: the literal pre-registration comparison and the venue/editor screen (the
   unified review does them).

## Verdict

- `accept`: core results reproduce; nothing to change.
- `minor`: core results reproduce; the fixes are local (a number, a table, wording, a missing
  systematic that does not move the conclusion).
- `major`: a core number or conclusion does not hold as stated, or rests on an unchecked or
  wrong step (time system, error budget, a prior that sets the result).
- `reject`: the main conclusion fails and no revision of this topic can rescue it.

Return the ordinary result bundle with `paper_candidate: false`, no `review_outcome`, and:

```json
"recompute_review": {
  "verdict": "accept|minor|major|reject",
  "required": ["item the author must fix, with the number you found"],
  "optional": ["..."],
  "unverified": ["what you could not check and why"],
  "checks": [{"item": "...", "outcome": "reproduced|not_reproduced|could_not_reproduce", "detail": "..."}],
  "scripts": ["/path/to/your/script.py"],
  "summary": "two or three sentences"
}
```

Declare the scripts and outputs as artifacts of your result. Never fabricate a recomputation.
