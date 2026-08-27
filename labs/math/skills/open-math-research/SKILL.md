---
name: open-math-research
description: Apply the complete original OpenAI Cycle Double Cover (CDC) prompt, embedded verbatim in this skill, to an open mathematical problem through persistent dynamic multi-agent proof search and adversarial audit. Use only when a project explicitly selects the open-math-research protocol, the user invokes $open-math-research, asks to use the original CDC prompt or CDC method, or asks Codex to attack an open conjecture continuously.
---

# Open Math Research

Treat the user's current open-problem statement and the complete original CDC
prompt below as one active input to Codex. Start the research run directly when
the statement is sufficiently precise.

## OpenLabs runtime binding

- This is an independent mathematics protocol, not an implicit extension of
  `amra-math` or `autonomous-math`. Activate it only through the matching
  protocol or an explicit user request.
- The OpenLabs attempt, resource guard, evidence archive, and hard wall deadline
  are operational boundaries, not scientific stopping criteria. A worker that
  reaches its hard deadline must atomically checkpoint the approach registry,
  proved facts, failed routes, exact gap, and next actions so the same logical
  research role can resume without treating the conjecture as abandoned.
- Configure every formal run with at least eight hours of Agent wall budget and
  a provider timeout that can honor it. The number of concurrent agents is
  bounded by the capacity actually available to the worker and the aggregate
  OpenLabs resource guard; the original prompt's 64 agents is an upper bound,
  not permission to bypass resource admission.
- Preserve verification receipts for any exact computation used in a claimed
  proof. The original rule against Lean remains in force unless the user
  separately requests formalization.
- Keep proof state, registries, small source and receipts in the staged campaign.
  Put SAT/SMT transcripts, bulk searches, large JSON/JSONL, archives and other
  generated payloads under `transaction.artifact_staging_root`, and declare
  every such file by URI and SHA-256 in the result. Never write new payloads
  directly to the live artifact tree.

## Bind the current problem

- Treat the user's supplied definitions, hypotheses, quantifiers, boundary
  cases, and conclusion as the active `Current task statement`.
- Keep the original prompt block below unchanged. For a problem other than CDC,
  bind CDC-specific mathematical referents, near-miss examples, and adversarial
  checks semantically to their exact analogues in the current problem.
- Change only those problem-specific referents during execution. Preserve every
  task-independent condition with its original force, including the affirmative
  proof premise, full-resolution threshold, dynamic multi-agent instructions,
  approach registry, blocked-route policy, adversarial auditing, persistence,
  final-return rule, minimum time, and public-search restriction.
- Do not add a status-check phase, novelty search, calibrated abstention, early
  exit, or alternative success criterion.
- Produce ordinary mathematical-language reasoning and proof. Do not run Lean
  unless the user separately requests formalization.
- Continue the run according to the original prompt's stopping condition. A new
  user message that explicitly changes or stops the task takes precedence.

## Original CDC prompt — verbatim

The text between the tags is the complete textual content of Section 1,
`Prompt`, from `references/cdc_prompt.pdf`. Only PDF page-layout artifacts and
line wrapping have been removed. Do not edit this block.

<cdc-original-prompt>

Current task statement

A graph here is a finite loopless undirected multigraph: parallel edges are allowed and are
distinct. A bridge is an edge whose deletion increases the number of connected components. A
cycle is a connected 2-regular submultigraph; thus two parallel edges form a cycle of length
two. A cycle double cover of G is a finite multiset of cycles of G such that every edge of G
occurs in exactly two members of the multiset, counted with multiplicity.

Resolve the Cycle Double Cover Conjecture completely:

Every finite bridgeless loopless multigraph has a cycle double cover.

Disconnected graphs are permitted, and the edgeless graph has the empty cycle double cover.
Cycles in the cover need not be induced or edge-disjoint from one another; the requirement
is exactly two total occurrences of each edge.

Assume for purposes of this task that a complete affirmative proof exists. A complete
solution must prove exactly the following:

Every finite loopless multigraph with no bridge possesses a cycle double cover, without
additional assumptions such as cubicity, planarity, connectivity, or higher
edge-connectivity.

Partial progress does not count unless it implies exactly the resolution above. In
particular, proofs for special graph classes, constructions of cycle covers with some edges
covered other than twice, bounded-length or prescribed-cycle variants, reductions to another
unproved conjecture, computational verification through any fixed graph size, and candidate
counterexamples without a complete nonexistence certificate are insufficient.

Use multiagent v2 aggressively and dynamically. You have up to 64 concurrent agents
available. Do not use a fixed assignment such as “N agents for strategy X.” Instead, manage
the search using the following heuristics:

- Begin with a genuinely diverse portfolio of approaches. Agents should explore
substantially different formulations, invariants, reductions, algebraic viewpoints,
structural inductions, decompositions, flow formulations, transition systems, embeddings,
extremal arguments, and computational sanity checks.

- Do not tell most agents the currently favored approach. Preserve independence during early
rounds so that agents do not all converge to the same attractive but incomplete reduction.

- Maintain an explicit registry of approach families. Group agents by the mathematical idea
they are using, not by superficial wording. If many agents converge to one family, redirect
some of them toward underexplored formulations.

- Do not allow one approach to dominate merely because it gives elegant reductions. A route
that ends at a lemma equivalent in strength to the original conjecture is not close to
completion unless it supplies a genuinely new proof of that lemma.

- When an approach stalls at a theorem-strength missing lemma, mark that route as blocked.
Only continue assigning agents to it if someone proposes a materially new mechanism,
invariant, or construction.

- Keep several incompatible proof routes alive through multiple rounds. Cross-pollinate
ideas only after independent agents have developed them far enough to expose their real
strengths and gaps.

- Use adversarial agents throughout: every candidate proof must be checked for exact-two
multiplicity, repeated-edge closed trails masquerading as cycles, parallel-edge 2-cycles,
disconnected graphs, cutvertices, bridges introduced by reductions, and circular use of an
equivalent CDC statement.

- Require agents to return concrete lemmas, constructions, equations, or counterexamples to
proposed sublemmas. Reject status reports, vague optimism, and claims that an unproved
global compatibility statement is “routine.”

- The root agent should repeatedly synthesize, challenge, redirect, and launch new rounds.
Do not stop after the first wave fails. Produce a complete proof if one survives audit;
otherwise report only the strongest rigorously proved derivation and its exact remaining
gap.

Do not return merely because current approaches fail or agents report theorem-strength gaps.
Continue launching new rounds, reopening blocked approaches only when there is a genuinely
new mechanism, and searching for fresh formulations.

Return only when a complete affirmative proof has been found and survives adversarial audit.
Do not return a reduction, partial result, isolated missing lemma, “best effort” summary, or
explanation of why the problem is difficult.

Spend at least 8 hours on this before even thinking of returning or giving up.

Public search may be used only for ordinary mathematical background or standard named
theorems, not to search for a solution to this exact conjecture or benchmark. Do not search
the public web merely to determine whether CDC is open, and do not answer that it is open.

</cdc-original-prompt>

## Source integrity

Use the bundled official PDF to audit the embedded text when needed:

- File: `references/cdc_prompt.pdf`
- SHA-256: `0e48deee28caba82ee5b4191d4c5c6ec4d62e5d27890fa7f0d2c8868f8b758f3`
- Official source:
  <https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_prompt.pdf>
