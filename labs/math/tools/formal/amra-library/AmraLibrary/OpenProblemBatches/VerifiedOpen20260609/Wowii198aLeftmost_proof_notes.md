# Wowii198a Leftmost Proof Notes

## 2026-06-18 component attachment certificate

- External web or literature sources used: none.
- Tool check: a bounded Python enumeration checked all connected graphs on
  `2 <= n <= 6` whose deletion of any one vertex remains connected. Among the
  non-Hamiltonian cases found through `n = 6`, every longest path and missed
  vertex satisfied the component-attachment certificate shape: two outside
  vertices in the missed vertex's outside component attach to internal vertices
  of the longest path with indices `0 < ii`, `ii + 1 < jj`, `jj < p.length`.
- Result: no counterexample through six vertices. This is route evidence only;
  it is not part of the Lean proof.

## 2026-06-18 round 2 formalizer note

- External web or literature sources used: none.
- Lean probe: a temporary local file `lean_probe_support_take.lean` checked the
  helper shape
  `support_take_disjoint_of_getVert_prefix`, using
  `Walk.mem_support_iff_exists_getVert`, `Walk.take_length`, and
  `Walk.take_getVert`. The temporary probe was deleted after verification.
- Implemented progress: the component certificate now proves that the left
  first-entry prefix, its reverse, the right first-entry prefix, and their
  appended raw outside walk have support disjoint from `p.support`.
- Remaining formal gap: package the raw outside walk as a simple path through
  `v` and prove the separated-index inequality `jL + 1 < jR` from longest-path
  maximality.
