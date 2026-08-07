# WOWII198a branch tool checks

Date: 2026-06-12

Scope: local evidence for the `b G = G.diam + 2` branch in
`Wowii198aLeftmost.lean`.

External sources relied on: none. This note records local Python checks only.

Checks performed:

- Enumerated NetworkX graph atlas connected graphs on 2 through 7 vertices.
  Among graphs satisfying `diam = 2`, all vertex eccentricities equal `2`,
  and largest induced bipartite subgraph order `b = 4`, 69 candidates were
  found and all had Hamiltonian paths.
- Randomly sampled connected diameter-two graphs on 8 through 12 vertices.
  Among 341 sampled graphs satisfying the same branch constraints, no graph
  without a Hamiltonian path was found.

Interpretation: these checks did not find a counterexample to the branch, but
they are not proof certificates. The Lean blocker remains the structural bridge:
from connected finite `G`, `G.diam = 2`, all eccentricities equal `2`, and
`b G = 4`, construct a Hamiltonian walk/path.

Additional check on 2026-06-13:

- Exhaustively enumerated all labeled simple graphs on 2 through 6 vertices and
  sampled the first 200,000 labeled graphs on 7 vertices. Among 233,866 checked
  graphs, 43,628 satisfied connectedness, one-vertex-deletion connectedness,
  and independence number at most 3. All such candidates had a Hamiltonian
  path by direct permutation search.

Interpretation: this supports the Chvatal-Erdos traceability target
`chvatal_erdos_two_connected_indepNum_le_three_traceable`, but it is still only
finite evidence. The Lean proof still needs a formal Chvatal-Erdos theorem or a
complete specialized longest-path proof.
