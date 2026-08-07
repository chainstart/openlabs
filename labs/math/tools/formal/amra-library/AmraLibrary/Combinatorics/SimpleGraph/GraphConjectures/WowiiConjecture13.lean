/-
Copyright 2026 AMRA contributors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-/

import AmraLibrary.Combinatorics.SimpleGraph.GraphConjectures.LargestInducedTree
import Mathlib.Combinatorics.SimpleGraph.Diam
import Mathlib.Data.Real.Basic
import Mathlib.Order.Interval.Finset.Nat
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.SuppressCompilation

suppress_compilation

/-!
# Formal support for WOWII Conjecture 13

This file is the active Lean proof loop for WOWII Conjecture 13.  The current
closed lemmas isolate the easy low-diameter branch and the reusable bridge from
a maximum local independent neighbourhood to the largest induced bipartite
subgraph.
-/

namespace SimpleGraph

open Classical

set_option linter.unusedSectionVars false

variable {α : Type*}

/-- The maximum local-neighbourhood independence number, as used in WOWII
Conjecture 13. -/
noncomputable def maxIndepNeighborsCard [Fintype α] [Nonempty α] (G : SimpleGraph α) : ℕ :=
  (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)

/-- A vertex attaining the maximum local-neighbourhood independence number gives
an induced bipartite star of order `max l(v) + 1`. -/
theorem maxIndepNeighborsCard_add_one_le_largestInducedBipartiteSubgraphSize
    [Fintype α] [Nonempty α] (G : SimpleGraph α) :
    maxIndepNeighborsCard G + 1 ≤ largestInducedBipartiteSubgraphSize G := by
  classical
  unfold maxIndepNeighborsCard
  have hmem :
      (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
        ∈ Finset.univ.image (fun v => indepNeighborsCard G v) :=
    Finset.max'_mem _ _
  rcases Finset.mem_image.mp hmem with ⟨v, _hv, hvmax⟩
  simpa [hvmax] using indepNeighborsCard_add_one_le_largestInducedBipartiteSubgraphSize
    (G := G) v

/-- The low-diameter branch of WOWII Conjecture 13.  If `diam(G) ≤ 2`, then the
induced star at a vertex maximizing `l(v)` is already large enough. -/
theorem diam_add_maxIndepNeighborsCard_sub_one_le_largestInducedBipartiteSubgraphSize
    [Fintype α] [Nonempty α] (G : SimpleGraph α) (hdiam : G.diam ≤ 2) :
    (G.diam : ℝ) + (maxIndepNeighborsCard G : ℝ) - 1
      ≤ (largestInducedBipartiteSubgraphSize G : ℝ) := by
  classical
  have hstar :=
    maxIndepNeighborsCard_add_one_le_largestInducedBipartiteSubgraphSize (G := G)
  have hstarR :
      ((maxIndepNeighborsCard G + 1 : ℕ) : ℝ)
        ≤ (largestInducedBipartiteSubgraphSize G : ℝ) := by
    exact_mod_cast hstar
  have hdiamR : (G.diam : ℝ) ≤ 2 := by
    exact_mod_cast hdiam
  have hleft :
      (G.diam : ℝ) + (maxIndepNeighborsCard G : ℝ) - 1
        ≤ ((maxIndepNeighborsCard G + 1 : ℕ) : ℝ) := by
    norm_num
    nlinarith
  exact le_trans hleft hstarR

/-- Reduction for the full Conjecture 13 target: it is enough to construct, for
each vertex `v`, an induced bipartite subgraph of size at least
`diam(G) + l(v) - 1`.  The maximum over `v` and the conversion to the largest
induced bipartite invariant are handled here. -/
theorem conjecture13_from_vertex_bipartite_witnesses
    [Fintype α] [Nonempty α] (G : SimpleGraph α)
    (hwit :
      ∀ v : α, ∃ s : Finset α,
        (G.induce (s : Set α)).IsBipartite ∧
          (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) - 1 ≤ (s.card : ℝ)) :
    (G.diam : ℝ) + (maxIndepNeighborsCard G : ℝ) - 1
      ≤ (largestInducedBipartiteSubgraphSize G : ℝ) := by
  classical
  unfold maxIndepNeighborsCard
  have hmem :
      (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
        ∈ Finset.univ.image (fun v => indepNeighborsCard G v) :=
    Finset.max'_mem _ _
  rcases Finset.mem_image.mp hmem with ⟨v, _hv, hvmax⟩
  obtain ⟨s, hs_bip, hs_card⟩ := hwit v
  have hs_largest :
      (s.card : ℝ) ≤ (largestInducedBipartiteSubgraphSize G : ℝ) := by
    exact_mod_cast
      (card_le_largestInducedBipartiteSubgraphSize_of_induce_isBipartite
        (G := G) (s := s) hs_bip)
  simpa [hvmax] using le_trans hs_card hs_largest

/-- The same reduction stated with the WOWII notation `b G`. -/
theorem conjecture13_from_vertex_bipartite_witnesses_b
    [Fintype α] [Nonempty α] (G : SimpleGraph α)
    (hwit :
      ∀ v : α, ∃ s : Finset α,
        (G.induce (s : Set α)).IsBipartite ∧
          (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) - 1 ≤ (s.card : ℝ)) :
    (G.diam : ℝ) + (maxIndepNeighborsCard G : ℝ) - 1 ≤ (b G : ℝ) := by
  simpa [b] using conjecture13_from_vertex_bipartite_witnesses (G := G) hwit

/-- The vertex-witness reduction in the exact `letI maxL` shape of the final
WOWII Conjecture 13 statement. -/
theorem conjecture13_from_vertex_bipartite_witnesses_final_shape
    [Fintype α] [Nonempty α] (G : SimpleGraph α) (_h : G.Connected)
    (hwit :
      ∀ v : α, ∃ s : Finset α,
        (G.induce (s : Set α)).IsBipartite ∧
          (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) - 1 ≤ (s.card : ℝ)) :
    letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    (G.diam : ℝ) + (maxL : ℝ) - 1 ≤ b G := by
  classical
  simpa [maxIndepNeighborsCard] using
    conjecture13_from_vertex_bipartite_witnesses_b (G := G) hwit

/-- The final WOWII Conjecture 13 statement in the already-closed
low-diameter branch.  The remaining final proof may split on `G.diam ≤ 2` and
use this theorem for the easy side. -/
theorem conjecture13_of_diam_le_two
    [Fintype α] [Nonempty α] (G : SimpleGraph α) (_h : G.Connected) (hdiam : G.diam ≤ 2) :
    letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    (G.diam : ℝ) + (maxL : ℝ) - 1 ≤ b G := by
  classical
  simpa [b, maxIndepNeighborsCard] using
    diam_add_maxIndepNeighborsCard_sub_one_le_largestInducedBipartiteSubgraphSize
      (G := G) hdiam

/-- A maximum independent subset of the neighbourhood of `v`, together with
`v`, is an explicit induced bipartite star of size `indepNeighborsCard G v + 1`. -/
theorem exists_indepNeighborsCard_add_one_bipartite_witness
    [Fintype α] {G : SimpleGraph α} (v : α) :
    ∃ s : Finset α,
      (G.induce (s : Set α)).IsBipartite ∧ s.card = indepNeighborsCard G v + 1 := by
  classical
  unfold indepNeighborsCard
  obtain ⟨s, hs⟩ := (G.induce (G.neighborSet v)).exists_isNIndepSet_indepNum
  rw [SimpleGraph.isNIndepSet_iff] at hs
  let e : G.neighborSet v ↪ α := Function.Embedding.subtype _
  let leaves : Finset α := s.map e
  let t : Finset α := insert v leaves
  refine ⟨t, ?_, ?_⟩
  · refine (SimpleGraph.IsBipartiteWith.isBipartite
        (s := {x : (t : Set α) | x.1 = v})
        (t := {x : (t : Set α) | x.1 ∈ leaves}) ?_)
    constructor
    · rw [Set.disjoint_left]
      intro x hxv hxleaf
      dsimp at hxv hxleaf
      rw [Finset.mem_map] at hxleaf
      rcases hxleaf with ⟨w, _hw, hwx⟩
      change w.1 = x.1 at hwx
      have hadj : G.Adj v w.1 := w.2
      have : G.Adj v v := by
        simp [hwx, hxv] at hadj
      exact G.irrefl this
    · intro x y hxy
      have hxyG : G.Adj x.1 y.1 := hxy
      have hxmem : x.1 ∈ t := x.2
      have hymem : y.1 ∈ t := y.2
      dsimp [t] at hxmem hymem
      rw [Finset.mem_insert] at hxmem hymem
      rcases hxmem with hxv | hxleaf
      · left
        constructor
        · exact hxv
        · rcases hymem with hyv | hyleaf
          · exfalso
            have : G.Adj v v := by
              simp [hxv, hyv] at hxyG
            exact G.irrefl this
          · exact hyleaf
      · rcases hymem with hyv | hyleaf
        · right
          exact ⟨hxleaf, hyv⟩
        · exfalso
          rw [Finset.mem_map] at hxleaf hyleaf
          rcases hxleaf with ⟨a, ha, hax⟩
          rcases hyleaf with ⟨b, hb, hby⟩
          change a.1 = x.1 at hax
          change b.1 = y.1 at hby
          have habAdj : (G.induce (G.neighborSet v)).Adj a b := by
            change G.Adj a.1 b.1
            rwa [hax, hby]
          by_cases hab : a = b
          · subst hab
            exact G.irrefl habAdj
          · exact (hs.1 ha hb (fun h => hab h)) habAdj
  · dsimp [t, leaves]
    rw [Finset.card_insert_of_notMem]
    · rw [Finset.card_map]
      exact congrArg Nat.succ hs.2
    · simp only [Finset.mem_map, not_exists, not_and]
      intro w _hw hwv
      change w.1 = v at hwv
      have hadj : G.Adj v w.1 := w.2
      have : G.Adj v v := by
        rwa [hwv] at hadj
      exact G.irrefl this

/-- There is a finite independent set in the neighbourhood of `v` whose
cardinality is exactly `indepNeighborsCard G v`. -/
theorem exists_indepNeighborsCard_neighbor_indepSet
    [Fintype α] {G : SimpleGraph α} (v : α) :
    ∃ A : Finset α,
      A.card = indepNeighborsCard G v ∧
        (∀ a ∈ A, G.Adj v a) ∧ G.IsIndepSet (A : Set α) := by
  classical
  unfold indepNeighborsCard
  obtain ⟨s, hs⟩ := (G.induce (G.neighborSet v)).exists_isNIndepSet_indepNum
  rw [SimpleGraph.isNIndepSet_iff] at hs
  let e : G.neighborSet v ↪ α := Function.Embedding.subtype _
  let A : Finset α := s.map e
  refine ⟨A, ?_, ?_, ?_⟩
  · dsimp [A]
    rw [Finset.card_map]
    exact hs.2
  · intro a ha
    dsimp [A] at ha
    rw [Finset.mem_map] at ha
    rcases ha with ⟨w, _hw, hwa⟩
    change w.1 = a at hwa
    simpa [hwa] using (SimpleGraph.mem_neighborSet (G := G) v w.1).mp w.2
  · intro a ha b hb hab hAdj
    have haA : a ∈ A := by simpa using ha
    have hbA : b ∈ A := by simpa using hb
    dsimp [A] at haA hbA
    rw [Finset.mem_map] at haA hbA
    rcases haA with ⟨wa, hwa_mem, hwa⟩
    rcases hbA with ⟨wb, hwb_mem, hwb⟩
    change wa.1 = a at hwa
    change wb.1 = b at hwb
    have hAdj' : (G.induce (G.neighborSet v)).Adj wa wb := by
      change G.Adj wa.1 wb.1
      rwa [hwa, hwb]
    have hw_ne : wa ≠ wb := by
      intro h
      apply hab
      rw [← hwa, ← hwb, h]
    exact (hs.1 hwa_mem hwb_mem hw_ne) hAdj'

/-- In the low-diameter case, the per-vertex witness required by the final
reduction is already the induced star at `v`. -/
theorem vertex_bipartite_witness_of_diam_le_two
    [Fintype α] (G : SimpleGraph α) (hdiam : G.diam ≤ 2) (v : α) :
    ∃ s : Finset α,
      (G.induce (s : Set α)).IsBipartite ∧
        (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) - 1 ≤ (s.card : ℝ) := by
  classical
  obtain ⟨s, hs_bip, hs_card⟩ :=
    exists_indepNeighborsCard_add_one_bipartite_witness (G := G) v
  refine ⟨s, hs_bip, ?_⟩
  rw [hs_card]
  have hdiamR : (G.diam : ℝ) ≤ 2 := by
    exact_mod_cast hdiam
  norm_num
  nlinarith

/-- In a finite connected graph there is a geodesic walk whose length realizes
the diameter. -/
theorem exists_diameter_walk_with_dist
    [Fintype α] [Nonempty α] (G : SimpleGraph α) (h : G.Connected) :
    ∃ u v : α, ∃ p : G.Walk u v,
      p.IsPath ∧ p.length = G.dist u v ∧ p.length = G.diam := by
  classical
  obtain ⟨u, v, huv⟩ := G.exists_dist_eq_diam
  obtain ⟨p, hp_path, hp_dist⟩ := (h u v).exists_path_of_dist
  exact ⟨u, v, p, hp_path, hp_dist, by rw [hp_dist, huv]⟩

/-- A prefix of a walk gives an explicit route from the start vertex to
`p.getVert i`, so the graph distance is at most `i`. -/
theorem dist_start_getVert_le
    {G : SimpleGraph α} {u v : α} (p : G.Walk u v) {i : ℕ}
    (hi : i ≤ p.length) :
    G.dist u (p.getVert i) ≤ i := by
  have hdist := SimpleGraph.dist_le (p.take i)
  simpa [SimpleGraph.Walk.take_length, Nat.min_eq_left hi] using hdist

/-- A suffix of a walk gives an explicit route from `p.getVert i` to the end
vertex, so the graph distance is at most `p.length - i`. -/
theorem dist_getVert_end_le
    {G : SimpleGraph α} {u v : α} (p : G.Walk u v) {i : ℕ} :
    G.dist (p.getVert i) v ≤ p.length - i := by
  have hdist := SimpleGraph.dist_le (p.drop i)
  simpa [SimpleGraph.Walk.drop_length] using hdist

/-- The segment of a walk from index `i` to index `j` gives a route of length
`j - i`, hence the graph distance between those indexed vertices is at most
`j - i`. -/
theorem dist_getVert_getVert_le_index_sub
    {G : SimpleGraph α} {u v : α} (p : G.Walk u v) {i j : ℕ}
    (hi : i ≤ j) (hj : j ≤ p.length) :
    G.dist (p.getVert i) (p.getVert j) ≤ j - i := by
  let q : G.Walk (p.getVert i) (p.getVert j) :=
    ((p.drop i).take (j - i)).copy rfl (by
      rw [SimpleGraph.Walk.drop_getVert]
      have hji : j - i ≤ p.length - i := Nat.sub_le_sub_right hj i
      rw [add_tsub_cancel_of_le hi])
  have hdist := SimpleGraph.dist_le q
  have hlen : q.length = j - i := by
    simp [q, SimpleGraph.Walk.take_length, SimpleGraph.Walk.drop_length,
      Nat.min_eq_left (Nat.sub_le_sub_right hj i)]
  simpa [hlen] using hdist

/-- Along a walk whose length realizes the endpoint distance, the distance
between two ordered indexed vertices is exactly the difference of the indices.
The reverse inequality is the usual splice argument: replacing the segment by a
shorter walk would shorten the whole endpoint walk. -/
theorem geodesic_getVert_dist_eq_index_sub
    {G : SimpleGraph α} {u w : α} (p : G.Walk u w)
    (hp : p.length = G.dist u w) {i j : ℕ}
    (hi : i ≤ j) (hj : j ≤ p.length) :
    G.dist (p.getVert i) (p.getVert j) = j - i := by
  have hupper := dist_getVert_getVert_le_index_sub (G := G) p hi hj
  refine le_antisymm hupper ?_
  have hi_len : i ≤ p.length := le_trans hi hj
  let q : G.Walk (p.getVert i) (p.getVert j) :=
    ((p.drop i).take (j - i)).copy rfl (by
      rw [SimpleGraph.Walk.drop_getVert]
      have hji : j - i ≤ p.length - i := Nat.sub_le_sub_right hj i
      rw [add_tsub_cancel_of_le hi])
  obtain ⟨s, hs_len⟩ := q.reachable.exists_walk_length_eq_dist
  let r : G.Walk u w := ((p.take i).append s).append (p.drop j)
  have hdist_le : p.length ≤ r.length := by
    simpa [hp] using SimpleGraph.dist_le r
  have hr_len :
      r.length = i + G.dist (p.getVert i) (p.getVert j) + (p.length - j) := by
    simp [r, hs_len, SimpleGraph.Walk.take_length, SimpleGraph.Walk.drop_length,
      Nat.min_eq_left hi_len]
  rw [hr_len] at hdist_le
  omega

/-- On a geodesic walk, any graph edge between two ordered indexed vertices
can only connect consecutive indices.  This is the induced-path exclusion used
when checking edges inside the selected path vertices. -/
theorem geodesic_getVert_adj_index_sub_eq_one
    {G : SimpleGraph α} {u w : α} (p : G.Walk u w)
    (hp : p.length = G.dist u w) {i j : ℕ}
    (hij : i < j) (hj : j ≤ p.length)
    (hadj : G.Adj (p.getVert i) (p.getVert j)) :
    j - i = 1 := by
  have hdist_eq :
      G.dist (p.getVert i) (p.getVert j) = j - i :=
    geodesic_getVert_dist_eq_index_sub (G := G) p hp (Nat.le_of_lt hij) hj
  have hdist_le_one :
      G.dist (p.getVert i) (p.getVert j) ≤ 1 := by
    simpa using SimpleGraph.dist_le hadj.toWalk
  have hpos : 0 < j - i := Nat.sub_pos_of_lt hij
  omega

/-- A finite set of natural-number indices has at most five elements if every
two comparable elements differ by at most four.  This is the arithmetic core of
the diameter-path short-window argument. -/
theorem Finset.card_le_five_of_pair_sub_le_four
    (Q : Finset ℕ)
    (hQ : ∀ i ∈ Q, ∀ j ∈ Q, i ≤ j → j - i ≤ 4) :
    Q.card ≤ 5 := by
  classical
  by_cases hne : Q.Nonempty
  · let m := Q.min' hne
    have hm : m ∈ Q := Finset.min'_mem Q hne
    have hsubset : Q ⊆ Finset.Icc m (m + 4) := by
      intro x hx
      have hmx : m ≤ x := Finset.min'_le Q x hx
      have hdiff : x - m ≤ 4 := hQ m hm x hx hmx
      simp only [Finset.mem_Icc]
      constructor
      · exact hmx
      · omega
    calc
      Q.card ≤ (Finset.Icc m (m + 4)).card := Finset.card_le_card hsubset
      _ = 5 := by
        rw [Nat.card_Icc]
        omega
  · have hQempty : Q = ∅ := Finset.not_nonempty_iff_eq_empty.mp hne
    simp [hQempty]

/-- A finite set of natural-number indices has at most three elements if every
two comparable elements differ by at most two. -/
theorem Finset.card_le_three_of_pair_sub_le_two
    (Q : Finset ℕ)
    (hQ : ∀ i ∈ Q, ∀ j ∈ Q, i ≤ j → j - i ≤ 2) :
    Q.card ≤ 3 := by
  classical
  by_cases hne : Q.Nonempty
  · let m := Q.min' hne
    have hm : m ∈ Q := Finset.min'_mem Q hne
    have hsubset : Q ⊆ Finset.Icc m (m + 2) := by
      intro x hx
      have hmx : m ≤ x := Finset.min'_le Q x hx
      have hdiff : x - m ≤ 2 := hQ m hm x hx hmx
      simp only [Finset.mem_Icc]
      constructor
      · exact hmx
      · omega
    calc
      Q.card ≤ (Finset.Icc m (m + 2)).card := Finset.card_le_card hsubset
      _ = 3 := by
        rw [Nat.card_Icc]
        omega
  · have hQempty : Q = ∅ := Finset.not_nonempty_iff_eq_empty.mp hne
    simp [hQempty]

/-- On a geodesic walk, all indices whose vertices lie within distance two of a
fixed vertex form a window of size at most five. -/
theorem geodesic_dist_le_two_index_set_card_le_five
    {G : SimpleGraph α} (hG : G.Connected) {u w x : α}
    (p : G.Walk u w) (hp : p.length = G.dist u w) :
    ((Finset.range (p.length + 1)).filter
      (fun i => G.dist x (p.getVert i) ≤ 2)).card ≤ 5 := by
  classical
  refine Finset.card_le_five_of_pair_sub_le_four _ ?_
  intro i hiQ j hjQ hij
  simp only [Finset.mem_filter, Finset.mem_range] at hiQ hjQ
  have hj_len : j ≤ p.length := Nat.lt_succ_iff.mp hjQ.1
  have hdist_eq :
      G.dist (p.getVert i) (p.getVert j) = j - i :=
    geodesic_getVert_dist_eq_index_sub (G := G) p hp hij hj_len
  have hxi : G.dist (p.getVert i) x ≤ 2 := by
    simpa [SimpleGraph.dist_comm] using hiQ.2
  have hxj : G.dist x (p.getVert j) ≤ 2 := hjQ.2
  have htri :
      G.dist (p.getVert i) (p.getVert j)
        ≤ G.dist (p.getVert i) x + G.dist x (p.getVert j) :=
    hG.dist_triangle
  have hdist_le_four : G.dist (p.getVert i) (p.getVert j) ≤ 4 := by
    exact le_trans htri (by omega)
  simpa [hdist_eq] using hdist_le_four

/-- If a path vertex is adjacent to a neighbour of `x`, then its index belongs
to the distance-two window around `x`.  This is the exclusion fact used when
deleting the short window from the diameter path. -/
theorem index_mem_dist_le_two_window_of_adj_neighbor
    {G : SimpleGraph α} (hG : G.Connected) {u w x a : α}
    (p : G.Walk u w) {i : ℕ} (hi : i ≤ p.length)
    (hxa : G.Adj x a) (hap : G.Adj a (p.getVert i)) :
    i ∈ (Finset.range (p.length + 1)).filter
      (fun i => G.dist x (p.getVert i) ≤ 2) := by
  classical
  simp only [Finset.mem_filter, Finset.mem_range]
  constructor
  · exact Nat.lt_succ_iff.mpr hi
  · have hxa_dist : G.dist x a ≤ 1 := by
      simpa using SimpleGraph.dist_le hxa.toWalk
    have hap_dist : G.dist a (p.getVert i) ≤ 1 := by
      simpa using SimpleGraph.dist_le hap.toWalk
    have htri : G.dist x (p.getVert i) ≤ G.dist x a + G.dist a (p.getVert i) :=
      hG.dist_triangle
    exact le_trans htri (by omega)

/-- A path vertex outside the distance-two window around `x` is not adjacent to
`x`. -/
theorem not_adj_center_of_index_not_mem_dist_le_two_window
    {G : SimpleGraph α} {u w x : α} (p : G.Walk u w) {i : ℕ}
    (hi : i ∈ Finset.range (p.length + 1) \ (Finset.range (p.length + 1)).filter
      (fun i => G.dist x (p.getVert i) ≤ 2)) :
    ¬ G.Adj x (p.getVert i) := by
  classical
  intro hadj
  have hdist_le_one : G.dist x (p.getVert i) ≤ 1 := by
    simpa using SimpleGraph.dist_le hadj.toWalk
  exact (Finset.mem_sdiff.mp hi).2
    (Finset.mem_filter.mpr ⟨(Finset.mem_sdiff.mp hi).1, by omega⟩)

/-- A path vertex outside the distance-two window around `x` is not adjacent to
any neighbour of `x`. -/
theorem not_adj_neighbor_of_index_not_mem_dist_le_two_window
    {G : SimpleGraph α} (hG : G.Connected) {u w x a : α}
    (p : G.Walk u w) {i : ℕ}
    (hi : i ∈ Finset.range (p.length + 1) \ (Finset.range (p.length + 1)).filter
      (fun i => G.dist x (p.getVert i) ≤ 2))
    (hxa : G.Adj x a) :
    ¬ G.Adj a (p.getVert i) := by
  classical
  intro hap
  have hi_len : i ≤ p.length :=
    Nat.lt_succ_iff.mp (Finset.mem_range.mp (Finset.mem_sdiff.mp hi).1)
  exact (Finset.mem_sdiff.mp hi).2
    (index_mem_dist_le_two_window_of_adj_neighbor (G := G) hG (p := p)
      hi_len hxa hap)

/-- If a short index window has at most five indices, one can add back at most
two of them while losing at most three indices overall.  This is the cardinal
bookkeeping used before imposing the extra distance/coloring constraints on the
actual add-back set. -/
theorem exists_short_window_addback_indices
    (Q : Finset ℕ) (hQcard : Q.card ≤ 5) :
    ∃ T : Finset ℕ,
      T ⊆ Q ∧ T.card + 3 ≥ Q.card ∧ T.card ≤ 2 := by
  classical
  by_cases hsmall : Q.card ≤ 3
  · refine ⟨∅, by simp, ?_, by simp⟩
    simp
    exact hsmall
  · have htake : Q.card - 3 ≤ Q.card := by omega
    obtain ⟨T, hTsub, hTcard⟩ := Finset.exists_subset_card_eq htake
    refine ⟨T, hTsub, ?_, ?_⟩
    · rw [hTcard]
      omega
    · rw [hTcard]
      omega

/-- In a geodesic distance-two index window, one can choose the add-back indices
from the vertices that are exactly distance two from the center. -/
theorem exists_short_window_addback_indices_with_dist_two
    {G : SimpleGraph α} (hG : G.Connected) {u w x : α}
    (p : G.Walk u w) (hp : p.length = G.dist u w) :
    let Q := (Finset.range (p.length + 1)).filter
      (fun i => G.dist x (p.getVert i) ≤ 2)
    ∃ T : Finset ℕ,
      T ⊆ Q ∧ T.card + 3 ≥ Q.card ∧ T.card ≤ 2 ∧
        ∀ i ∈ T, G.dist x (p.getVert i) = 2 := by
  classical
  let Q := (Finset.range (p.length + 1)).filter
    (fun i => G.dist x (p.getVert i) ≤ 2)
  change ∃ T : Finset ℕ,
      T ⊆ Q ∧ T.card + 3 ≥ Q.card ∧ T.card ≤ 2 ∧
        ∀ i ∈ T, G.dist x (p.getVert i) = 2
  let R := Q.filter (fun i => G.dist x (p.getVert i) ≤ 1)
  let D := Q.filter (fun i => G.dist x (p.getVert i) = 2)
  have hQcard : Q.card ≤ 5 := by
    simpa [Q] using
      geodesic_dist_le_two_index_set_card_le_five (G := G) hG (p := p) hp
  have hRcard : R.card ≤ 3 := by
    refine Finset.card_le_three_of_pair_sub_le_two R ?_
    intro i hiR j hjR hij
    simp only [R, Finset.mem_filter] at hiR hjR
    have hjQ := hjR.1
    simp only [Q, Finset.mem_filter, Finset.mem_range] at hjQ
    have hj_len : j ≤ p.length := Nat.lt_succ_iff.mp hjQ.1
    have hdist_eq :
        G.dist (p.getVert i) (p.getVert j) = j - i :=
      geodesic_getVert_dist_eq_index_sub (G := G) p hp hij hj_len
    have hxi : G.dist (p.getVert i) x ≤ 1 := by
      simpa [SimpleGraph.dist_comm] using hiR.2
    have hxj : G.dist x (p.getVert j) ≤ 1 := hjR.2
    have htri :
        G.dist (p.getVert i) (p.getVert j)
          ≤ G.dist (p.getVert i) x + G.dist x (p.getVert j) :=
      hG.dist_triangle
    have hdist_le_two : G.dist (p.getVert i) (p.getVert j) ≤ 2 := by
      exact le_trans htri (by omega)
    simpa [hdist_eq] using hdist_le_two
  have hDsubQ : D ⊆ Q := by
    intro i hiD
    exact (Finset.mem_filter.mp hiD).1
  have hcover : Q ⊆ R ∪ D := by
    intro i hiQ
    have hiQ' := hiQ
    simp only [Q, Finset.mem_filter, Finset.mem_range] at hiQ'
    by_cases hle_one : G.dist x (p.getVert i) ≤ 1
    · exact Finset.mem_union_left D (Finset.mem_filter.mpr ⟨hiQ, hle_one⟩)
    · have hdist_two : G.dist x (p.getVert i) = 2 := by
        omega
      exact Finset.mem_union_right R (Finset.mem_filter.mpr ⟨hiQ, hdist_two⟩)
  have hDlarge : Q.card - 3 ≤ D.card := by
    have hQ_le_union : Q.card ≤ (R ∪ D).card := Finset.card_le_card hcover
    have hUnion_le : (R ∪ D).card ≤ R.card + D.card := Finset.card_union_le R D
    have hQ_le : Q.card ≤ 3 + D.card := by
      exact le_trans hQ_le_union (le_trans hUnion_le (by omega))
    omega
  obtain ⟨T, hTsubD, hTcard⟩ := Finset.exists_subset_card_eq hDlarge
  refine ⟨T, ?_, ?_, ?_, ?_⟩
  · exact fun i hiT => hDsubQ (hTsubD hiT)
  · rw [hTcard]
    omega
  · rw [hTcard]
    omega
  · intro i hiT
    exact (Finset.mem_filter.mp (hTsubD hiT)).2

/-- In a geodesic distance-two index window, the add-back indices may be chosen
at distance exactly two from the center and with a common parity.  The parity
condition is the input needed for the eventual alternating coloring of the
selected path vertices together with the center star. -/
theorem exists_short_window_addback_indices_with_dist_two_same_parity
    {G : SimpleGraph α} (hG : G.Connected) {u w x : α}
    (p : G.Walk u w) (hp : p.length = G.dist u w) :
    let Q := (Finset.range (p.length + 1)).filter
      (fun i => G.dist x (p.getVert i) ≤ 2)
    ∃ T : Finset ℕ,
      T ⊆ Q ∧ T.card + 3 ≥ Q.card ∧ T.card ≤ 2 ∧
        (∀ i ∈ T, G.dist x (p.getVert i) = 2) ∧
          ∀ i ∈ T, ∀ j ∈ T, i % 2 = j % 2 := by
  classical
  let Q := (Finset.range (p.length + 1)).filter
    (fun i => G.dist x (p.getVert i) ≤ 2)
  change ∃ T : Finset ℕ,
      T ⊆ Q ∧ T.card + 3 ≥ Q.card ∧ T.card ≤ 2 ∧
        (∀ i ∈ T, G.dist x (p.getVert i) = 2) ∧
          ∀ i ∈ T, ∀ j ∈ T, i % 2 = j % 2
  have hQcard : Q.card ≤ 5 := by
    simpa [Q] using
      geodesic_dist_le_two_index_set_card_le_five (G := G) hG (p := p) hp
  by_cases hsmall : Q.card ≤ 3
  · refine ⟨∅, by simp, by simp [hsmall], by simp, by simp, by simp⟩
  by_cases hfive : Q.card = 5
  · have hne : Q.Nonempty := Finset.card_pos.mp (by omega)
    let m := Q.min' hne
    let M := Q.max' hne
    have hmQ : m ∈ Q := Finset.min'_mem Q hne
    have hMQ : M ∈ Q := Finset.max'_mem Q hne
    have hmM : m ≤ M := Finset.min'_le Q M hMQ
    have hQpair : ∀ i ∈ Q, ∀ j ∈ Q, i ≤ j → j - i ≤ 4 := by
      intro i hiQ j hjQ hij
      have hjQ' := hjQ
      simp only [Q, Finset.mem_filter, Finset.mem_range] at hiQ hjQ'
      have hj_len : j ≤ p.length := Nat.lt_succ_iff.mp hjQ'.1
      have hdist_eq :
          G.dist (p.getVert i) (p.getVert j) = j - i :=
        geodesic_getVert_dist_eq_index_sub (G := G) p hp hij hj_len
      have hxi : G.dist (p.getVert i) x ≤ 2 := by
        simpa [SimpleGraph.dist_comm] using hiQ.2
      have hxj : G.dist x (p.getVert j) ≤ 2 := hjQ'.2
      have htri :
          G.dist (p.getVert i) (p.getVert j)
            ≤ G.dist (p.getVert i) x + G.dist x (p.getVert j) :=
        hG.dist_triangle
      have hdist_le_four : G.dist (p.getVert i) (p.getVert j) ≤ 4 := by
        exact le_trans htri (by omega)
      simpa [hdist_eq] using hdist_le_four
    have hQsubIcc : Q ⊆ Finset.Icc m M := by
      intro y hy
      exact Finset.mem_Icc.mpr ⟨Finset.min'_le Q y hy, Finset.le_max' Q y hy⟩
    have hcard_le : Q.card ≤ (Finset.Icc m M).card := Finset.card_le_card hQsubIcc
    have hM_sub : M - m = 4 := by
      have hdiff_le : M - m ≤ 4 := hQpair m hmQ M hMQ hmM
      rw [hfive] at hcard_le
      rw [Nat.card_Icc] at hcard_le
      omega
    have hM_eq : M = m + 4 := by omega
    have hM_ne_m : M ≠ m := by omega
    have hMQ' := hMQ
    have hmQ' := hmQ
    simp only [Q, Finset.mem_filter, Finset.mem_range] at hMQ' hmQ'
    have hM_len : M ≤ p.length := Nat.lt_succ_iff.mp hMQ'.1
    have hdist_mM : G.dist (p.getVert m) (p.getVert M) = 4 := by
      have hdist_eq : G.dist (p.getVert m) (p.getVert M) = M - m :=
        geodesic_getVert_dist_eq_index_sub (G := G) p hp hmM hM_len
      rw [hdist_eq, hM_sub]
    have hm_dist_two : G.dist x (p.getVert m) = 2 := by
      by_contra hneq
      have hm_le_one : G.dist x (p.getVert m) ≤ 1 := by omega
      have hm_rev : G.dist (p.getVert m) x ≤ 1 := by
        simpa [SimpleGraph.dist_comm] using hm_le_one
      have htri :
          G.dist (p.getVert m) (p.getVert M)
            ≤ G.dist (p.getVert m) x + G.dist x (p.getVert M) :=
        hG.dist_triangle
      have : G.dist (p.getVert m) (p.getVert M) ≤ 3 := by
        exact le_trans htri (by omega)
      omega
    have hM_dist_two : G.dist x (p.getVert M) = 2 := by
      by_contra hneq
      have hM_le_one : G.dist x (p.getVert M) ≤ 1 := by omega
      have htri :
          G.dist (p.getVert m) (p.getVert M)
            ≤ G.dist (p.getVert m) x + G.dist x (p.getVert M) :=
        hG.dist_triangle
      have hm_rev : G.dist (p.getVert m) x ≤ 2 := by
        simpa [SimpleGraph.dist_comm] using hmQ'.2
      have : G.dist (p.getVert m) (p.getVert M) ≤ 3 := by
        exact le_trans htri (by omega)
      omega
    refine ⟨{m, M}, ?_, ?_, ?_, ?_, ?_⟩
    · intro y hy
      simp only [Finset.mem_insert, Finset.mem_singleton] at hy
      rcases hy with rfl | rfl
      · exact hmQ
      · exact hMQ
    · simp [hM_ne_m.symm, hfive]
    · simp [hM_ne_m.symm]
    · intro y hy
      simp only [Finset.mem_insert, Finset.mem_singleton] at hy
      rcases hy with rfl | rfl
      · exact hm_dist_two
      · exact hM_dist_two
    · intro i hi j hj
      simp only [Finset.mem_insert, Finset.mem_singleton] at hi hj
      rcases hi with rfl | rfl <;> rcases hj with rfl | rfl
      · rfl
      · omega
      · omega
      · rfl
  · have hfour : Q.card = 4 := by omega
    obtain ⟨T0, hT0sub, hT0card, _hT0le, hT0dist⟩ :=
      exists_short_window_addback_indices_with_dist_two (G := G) hG (p := p) hp
    have hT0ne : T0.Nonempty := by
      rw [hfour] at hT0card
      exact Finset.card_pos.mp (by omega)
    let i := T0.min' hT0ne
    have hiT0 : i ∈ T0 := Finset.min'_mem T0 hT0ne
    refine ⟨{i}, ?_, ?_, ?_, ?_, ?_⟩
    · intro y hy
      simp only [Finset.mem_singleton] at hy
      subst hy
      exact hT0sub hiT0
    · simp [hfour]
    · simp
    · intro y hy
      simp only [Finset.mem_singleton] at hy
      subst hy
      exact hT0dist i hiT0
    · intro y hy z hz
      simp only [Finset.mem_singleton] at hy hz
      subst hy
      subst hz
      rfl

/-- Mapping a finite set of indices along a path preserves cardinality. -/
theorem path_index_image_card_eq
    [DecidableEq α] {G : SimpleGraph α} {u w : α} (p : G.Walk u w) (hp : p.IsPath)
    (I : Finset ℕ) (hI : ∀ i ∈ I, i ≤ p.length) :
    (I.image fun i => p.getVert i).card = I.card := by
  classical
  refine Finset.card_image_of_injOn ?_
  intro i hi j hj hij
  exact hp.getVert_injOn (by simpa using hI i hi) (by simpa using hI j hj) hij

/-- If `T ⊆ Q` is added back after deleting an index window `Q` from a path,
then the selected path vertices have the expected cardinality. -/
theorem path_vertices_delete_window_addback_card
    [DecidableEq α] {G : SimpleGraph α} {u w : α} (p : G.Walk u w) (hp : p.IsPath)
    (Q T : Finset ℕ) (hQsub : Q ⊆ Finset.range (p.length + 1))
    (hTsub : T ⊆ Q) :
    (((Finset.range (p.length + 1) \ Q) ∪ T).image fun i => p.getVert i).card
      = p.length + 1 - Q.card + T.card := by
  classical
  have hIle :
      ∀ i ∈ (Finset.range (p.length + 1) \ Q) ∪ T, i ≤ p.length := by
    intro i hi
    rw [Finset.mem_union] at hi
    rcases hi with hi | hi
    · exact Nat.lt_succ_iff.mp (Finset.mem_range.mp (Finset.mem_sdiff.mp hi).1)
    · exact Nat.lt_succ_iff.mp (Finset.mem_range.mp (hQsub (hTsub hi)))
  rw [path_index_image_card_eq (G := G) p hp _ hIle]
  have hdisj : Disjoint (Finset.range (p.length + 1) \ Q) T := by
    rw [Finset.disjoint_left]
    intro i hi hiT
    exact (Finset.mem_sdiff.mp hi).2 (hTsub hiT)
  rw [Finset.card_union_of_disjoint hdisj]
  rw [Finset.card_sdiff_of_subset hQsub]
  rw [Finset.card_range]

/-- The add-back cardinal condition says that deleting the short window from a
path and adding back `T` loses at most three path vertices. -/
theorem path_vertices_delete_window_addback_card_add_three_ge
    [DecidableEq α] {G : SimpleGraph α} {u w : α} (p : G.Walk u w) (hp : p.IsPath)
    (Q T : Finset ℕ) (hQsub : Q ⊆ Finset.range (p.length + 1))
    (hTsub : T ⊆ Q) (hTcard : T.card + 3 ≥ Q.card) :
    (((Finset.range (p.length + 1) \ Q) ∪ T).image fun i => p.getVert i).card + 3
      ≥ p.length + 1 := by
  classical
  have hcard :=
    path_vertices_delete_window_addback_card (G := G) p hp Q T hQsub hTsub
  rw [hcard]
  omega

/-- A same-parity subset of a geodesic path is independent. -/
theorem geodesic_same_parity_path_vertices_indepSet
    {G : SimpleGraph α} {u w : α} (p : G.Walk u w)
    (hp : p.length = G.dist u w) (I : Finset ℕ)
    (hI : ∀ i ∈ I, i ≤ p.length) (c : ℕ) :
    G.IsIndepSet (((I.filter fun i => i % 2 = c).image fun i => p.getVert i) : Set α) := by
  classical
  intro x hx y hy hxy hAdj
  rw [Finset.mem_coe, Finset.mem_image] at hx hy
  rcases hx with ⟨i, hi, hix⟩
  rcases hy with ⟨j, hj, hjy⟩
  have hiI : i ∈ I := (Finset.mem_filter.mp hi).1
  have hjI : j ∈ I := (Finset.mem_filter.mp hj).1
  have hiParity : i % 2 = c := (Finset.mem_filter.mp hi).2
  have hjParity : j % 2 = c := (Finset.mem_filter.mp hj).2
  have hiLen : i ≤ p.length := hI i hiI
  have hjLen : j ≤ p.length := hI j hjI
  by_cases hij : i = j
  · exact hxy (by rw [← hix, ← hjy, hij])
  · rcases Nat.lt_or_gt_of_ne hij with hijlt | hjilt
    · have hAdjij : G.Adj (p.getVert i) (p.getVert j) := by
        simpa [hix, hjy] using hAdj
      have hsub : j - i = 1 :=
        geodesic_getVert_adj_index_sub_eq_one (G := G) p hp hijlt hjLen hAdjij
      have hpar : i % 2 = j % 2 := hiParity.trans hjParity.symm
      omega
    · have hAdjji : G.Adj (p.getVert j) (p.getVert i) := by
        simpa [hix, hjy] using hAdj.symm
      have hsub : i - j = 1 :=
        geodesic_getVert_adj_index_sub_eq_one (G := G) p hp hjilt hiLen hAdjji
      have hpar : j % 2 = i % 2 := hjParity.trans hiParity.symm
      omega

/-- The center vertex is not among the selected path vertices after deleting
the distance-two window and adding back vertices known to be exactly distance
two from the center. -/
theorem center_not_mem_path_vertices_delete_window_addback
    [DecidableEq α] {G : SimpleGraph α} {u w x : α} (p : G.Walk u w) (T : Finset ℕ)
    (_hTsub :
      T ⊆ (Finset.range (p.length + 1)).filter
        (fun i => G.dist x (p.getVert i) ≤ 2))
    (hTdist : ∀ i ∈ T, G.dist x (p.getVert i) = 2) :
    x ∉ ((((Finset.range (p.length + 1)) \
        (Finset.range (p.length + 1)).filter
          (fun i => G.dist x (p.getVert i) ≤ 2)) ∪ T).image fun i => p.getVert i) := by
  classical
  intro hx
  rw [Finset.mem_image] at hx
  rcases hx with ⟨i, hi, hix⟩
  rw [Finset.mem_union] at hi
  rcases hi with hi | hi
  · exact (Finset.mem_sdiff.mp hi).2
      (Finset.mem_filter.mpr ⟨(Finset.mem_sdiff.mp hi).1, by simp [hix]⟩)
  · have hdist : G.dist x x = 2 := by
      simpa [hix] using hTdist i hi
    simp at hdist

/-- A neighbourhood set of the center is disjoint from the selected path
vertices after deleting the distance-two window and adding back only vertices at
distance exactly two. -/
theorem neighbor_set_disjoint_path_vertices_delete_window_addback
    [DecidableEq α] {G : SimpleGraph α} {u w x : α} (p : G.Walk u w)
    (A : Finset α) (T : Finset ℕ)
    (hAadj : ∀ a ∈ A, G.Adj x a)
    (_hTsub :
      T ⊆ (Finset.range (p.length + 1)).filter
        (fun i => G.dist x (p.getVert i) ≤ 2))
    (hTdist : ∀ i ∈ T, G.dist x (p.getVert i) = 2) :
    Disjoint A
      ((((Finset.range (p.length + 1)) \
        (Finset.range (p.length + 1)).filter
          (fun i => G.dist x (p.getVert i) ≤ 2)) ∪ T).image fun i => p.getVert i) := by
  classical
  rw [Finset.disjoint_left]
  intro a ha hpath
  rw [Finset.mem_image] at hpath
  rcases hpath with ⟨i, hi, hia⟩
  have hdist_le_one : G.dist x (p.getVert i) ≤ 1 := by
    simpa [hia] using SimpleGraph.dist_le (hAadj a ha).toWalk
  rw [Finset.mem_union] at hi
  rcases hi with hi | hi
  · exact (Finset.mem_sdiff.mp hi).2
      (Finset.mem_filter.mpr ⟨(Finset.mem_sdiff.mp hi).1, by omega⟩)
  · have hdist_two : G.dist x (p.getVert i) = 2 := hTdist i hi
    omega

/-- The diameter-path window construction gives the per-vertex induced
bipartite witness needed for WOWII Conjecture 13. -/
theorem exists_diam_add_indepNeighborsCard_sub_one_bipartite_witness
    [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (hG : G.Connected) (v : α) :
    ∃ s : Finset α,
      (G.induce (s : Set α)).IsBipartite ∧
        (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) - 1 ≤ (s.card : ℝ) := by
  classical
  obtain ⟨A, hAcard, hAadj, hAind⟩ :=
    exists_indepNeighborsCard_neighbor_indepSet (G := G) v
  obtain ⟨u, w, p, hpPath, hpDist, hpDiam⟩ :=
    exists_diameter_walk_with_dist (G := G) hG
  let Q := (Finset.range (p.length + 1)).filter
    (fun i => G.dist v (p.getVert i) ≤ 2)
  obtain ⟨T, hTsub, hTcard, _hTle, hTdist, hTparity⟩ :=
    exists_short_window_addback_indices_with_dist_two_same_parity
      (G := G) hG (p := p) hpDist
  change
    ∃ s : Finset α,
      (G.induce (s : Set α)).IsBipartite ∧
        (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) - 1 ≤ (s.card : ℝ)
  let I := (Finset.range (p.length + 1) \ Q) ∪ T
  let c : ℕ := if hne : T.Nonempty then T.min' hne % 2 else 0
  let d : ℕ := (c + 1) % 2
  let P := I.image fun i => p.getVert i
  let P0 := (I.filter fun i => i % 2 = c).image fun i => p.getVert i
  let P1 := (I.filter fun i => i % 2 = d).image fun i => p.getVert i
  let L := A ∪ P1
  let R := insert v P0
  let S := L ∪ R
  have hQsub : Q ⊆ Finset.range (p.length + 1) := by
    intro i hi
    exact (Finset.mem_filter.mp hi).1
  have hIlen : ∀ i ∈ I, i ≤ p.length := by
    intro i hi
    change i ∈ (Finset.range (p.length + 1) \ Q) ∪ T at hi
    rw [Finset.mem_union] at hi
    rcases hi with hi | hi
    · exact Nat.lt_succ_iff.mp (Finset.mem_range.mp (Finset.mem_sdiff.mp hi).1)
    · exact Nat.lt_succ_iff.mp (Finset.mem_range.mp (hQsub (hTsub hi)))
  have hTc : ∀ i ∈ T, i % 2 = c := by
    intro i hi
    dsimp [c]
    by_cases hne : T.Nonempty
    · have hmin : T.min' hne ∈ T := Finset.min'_mem T hne
      simpa [hne] using hTparity i hi (T.min' hne) hmin
    · exact False.elim (hne ⟨i, hi⟩)
  have hc_lt : c < 2 := by
    dsimp [c]
    split_ifs with hne
    · exact Nat.mod_lt _ (by decide)
    · omega
  have hpar_cover : ∀ i : ℕ, i % 2 = c ∨ i % 2 = d := by
    intro i
    have hi_lt : i % 2 < 2 := Nat.mod_lt i (by decide)
    dsimp [d]
    omega
  have hcd_ne : c ≠ d := by
    dsimp [d]
    omega
  have hP0ind : G.IsIndepSet (P0 : Set α) := by
    simpa [P0] using
      geodesic_same_parity_path_vertices_indepSet (G := G) p hpDist I hIlen c
  have hP1ind : G.IsIndepSet (P1 : Set α) := by
    simpa [P1] using
      geodesic_same_parity_path_vertices_indepSet (G := G) p hpDist I hIlen d
  have hNoAdjCenterP0 : ∀ y ∈ P0, ¬ G.Adj v y := by
    intro y hy hyAdj
    change y ∈ ((I.filter fun i => i % 2 = c).image fun i => p.getVert i) at hy
    rw [Finset.mem_image] at hy
    rcases hy with ⟨i, hi, hiy⟩
    have hiI : i ∈ I := (Finset.mem_filter.mp hi).1
    change i ∈ (Finset.range (p.length + 1) \ Q) ∪ T at hiI
    rw [Finset.mem_union] at hiI
    rcases hiI with hiOutside | hiT
    · exact not_adj_center_of_index_not_mem_dist_le_two_window (G := G) p hiOutside
        (by simpa [hiy] using hyAdj)
    · have hdist_two : G.dist v (p.getVert i) = 2 := hTdist i hiT
      have hdist_le_one : G.dist v (p.getVert i) ≤ 1 := by
        simpa [hiy] using SimpleGraph.dist_le hyAdj.toWalk
      omega
  have hNoAdjAP1 : ∀ a ∈ A, ∀ y ∈ P1, ¬ G.Adj a y := by
    intro a ha y hy hay
    change y ∈ ((I.filter fun i => i % 2 = d).image fun i => p.getVert i) at hy
    rw [Finset.mem_image] at hy
    rcases hy with ⟨i, hi, hiy⟩
    have hiI : i ∈ I := (Finset.mem_filter.mp hi).1
    have hiParity : i % 2 = d := (Finset.mem_filter.mp hi).2
    change i ∈ (Finset.range (p.length + 1) \ Q) ∪ T at hiI
    rw [Finset.mem_union] at hiI
    rcases hiI with hiOutside | hiT
    · exact not_adj_neighbor_of_index_not_mem_dist_le_two_window (G := G) hG p
        hiOutside (hAadj a ha) (by simpa [hiy] using hay)
    · exact False.elim (hcd_ne ((hTc i hiT).symm.trans hiParity))
  have hLind : G.IsIndepSet (L : Set α) := by
    intro x hx y hy hxy hAdj
    change x ∈ A ∪ P1 at hx
    change y ∈ A ∪ P1 at hy
    rw [Finset.mem_union] at hx hy
    rcases hx with hxA | hxP
    · rcases hy with hyA | hyP
      · exact hAind hxA hyA hxy hAdj
      · exact hNoAdjAP1 x hxA y hyP hAdj
    · rcases hy with hyA | hyP
      · exact hNoAdjAP1 y hyA x hxP hAdj.symm
      · exact hP1ind hxP hyP hxy hAdj
  have hRind : G.IsIndepSet (R : Set α) := by
    intro x hx y hy hxy hAdj
    change x ∈ insert v P0 at hx
    change y ∈ insert v P0 at hy
    rw [Finset.mem_insert] at hx hy
    rcases hx with rfl | hxP
    · rcases hy with hyv | hyP
      · exact hxy hyv.symm
      · exact hNoAdjCenterP0 y hyP hAdj
    · rcases hy with rfl | hyP
      · exact hNoAdjCenterP0 x hxP hAdj.symm
      · exact hP0ind hxP hyP hxy hAdj
  have hBip : (G.induce (S : Set α)).IsBipartite := by
    change (G.induce (S : Set α)).Colorable 2
    refine ⟨SimpleGraph.Coloring.mk (fun x : (S : Set α) =>
      if x.1 ∈ L then (0 : Fin 2) else (1 : Fin 2)) ?_⟩
    intro x y hxy hcolor
    by_cases hxL : x.1 ∈ L <;> by_cases hyL : y.1 ∈ L
    · exact hLind hxL hyL (fun h => hxy.ne (Subtype.ext h)) hxy
    · simp [hxL, hyL] at hcolor
    · simp [hxL, hyL] at hcolor
    · have hxR : x.1 ∈ R := by
        have hxS : x.1 ∈ S := x.2
        change x.1 ∈ L ∪ R at hxS
        rw [Finset.mem_union] at hxS
        exact hxS.resolve_left hxL
      have hyR : y.1 ∈ R := by
        have hyS : y.1 ∈ S := y.2
        change y.1 ∈ L ∪ R at hyS
        rw [Finset.mem_union] at hyS
        exact hyS.resolve_left hyL
      exact hRind hxR hyR (fun h => hxy.ne (Subtype.ext h)) hxy
  have hCard :
      (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) - 1 ≤ (S.card : ℝ) := by
    let S0 := insert v (A ∪ P)
    have hPsub : P ⊆ P0 ∪ P1 := by
      intro y hy
      change y ∈ (I.image fun i => p.getVert i) at hy
      rw [Finset.mem_image] at hy
      rcases hy with ⟨i, hiI, hiy⟩
      rcases hpar_cover i with hiParity | hiParity
      · exact Finset.mem_union_left P1
          (Finset.mem_image.mpr ⟨i, Finset.mem_filter.mpr ⟨hiI, hiParity⟩, hiy⟩)
      · exact Finset.mem_union_right P0
          (Finset.mem_image.mpr ⟨i, Finset.mem_filter.mpr ⟨hiI, hiParity⟩, hiy⟩)
    have hS0sub : S0 ⊆ S := by
      intro x hx
      change x ∈ insert v (A ∪ P) at hx
      rw [Finset.mem_insert, Finset.mem_union] at hx
      change x ∈ L ∪ R
      rw [Finset.mem_union]
      change x ∈ A ∪ P1 ∨ x ∈ insert v P0
      rw [Finset.mem_union, Finset.mem_insert]
      rcases hx with rfl | hx
      · exact Or.inr (Or.inl rfl)
      · rcases hx with hxA | hxP
        · exact Or.inl (Or.inl hxA)
        · have hxP01 : x ∈ P0 ∪ P1 := hPsub hxP
          rw [Finset.mem_union] at hxP01
          rcases hxP01 with hxP0 | hxP1
          · exact Or.inr (Or.inr hxP0)
          · exact Or.inl (Or.inr hxP1)
    have hAdisjP : Disjoint A P := by
      simpa [P, I, Q] using
        neighbor_set_disjoint_path_vertices_delete_window_addback
          (G := G) p A T hAadj hTsub hTdist
    have hvnotA : v ∉ A := by
      intro hvA
      exact G.irrefl (hAadj v hvA)
    have hvnotP : v ∉ P := by
      simpa [P, I, Q] using
        center_not_mem_path_vertices_delete_window_addback
          (G := G) p T hTsub hTdist
    have hvnotAP : v ∉ A ∪ P := by
      simp [hvnotA, hvnotP]
    have hS0card : S0.card = A.card + P.card + 1 := by
      change (insert v (A ∪ P)).card = A.card + P.card + 1
      rw [Finset.card_insert_of_notMem hvnotAP]
      rw [Finset.card_union_of_disjoint hAdisjP]
    have hPcard :
        P.card = p.length + 1 - Q.card + T.card := by
      simpa [P, I, Q] using
        path_vertices_delete_window_addback_card (G := G) p hpPath Q T hQsub hTsub
    have hPadd : P.card + 3 ≥ p.length + 1 := by
      simpa [P, I, Q] using
        path_vertices_delete_window_addback_card_add_three_ge
          (G := G) p hpPath Q T hQsub hTsub hTcard
    have hS0leS : S0.card ≤ S.card := Finset.card_le_card hS0sub
    have hPaddR : (p.length + 1 : ℝ) ≤ (P.card + 3 : ℝ) := by
      exact_mod_cast hPadd
    have hS0leSR : (S0.card : ℝ) ≤ (S.card : ℝ) := by
      exact_mod_cast hS0leS
    have hmain : (p.length : ℝ) + (A.card : ℝ) - 1 ≤ (S0.card : ℝ) := by
      rw [hS0card]
      norm_num
      nlinarith [hPaddR]
    calc
      (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) - 1
          = (p.length : ℝ) + (A.card : ℝ) - 1 := by
            rw [hpDiam, hAcard]
      _ ≤ (S0.card : ℝ) := hmain
      _ ≤ (S.card : ℝ) := hS0leSR
  exact ⟨S, hBip, hCard⟩

/-- Per-vertex strengthening of WOWII Conjecture 13. -/
theorem diam_add_indepNeighborsCard_sub_one_le_largestInducedBipartiteSubgraphSize
    [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (hG : G.Connected) (v : α) :
    (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) - 1
      ≤ (largestInducedBipartiteSubgraphSize G : ℝ) := by
  classical
  obtain ⟨s, hs_bip, hs_card⟩ :=
    exists_diam_add_indepNeighborsCard_sub_one_bipartite_witness
      (G := G) hG v
  have hs_largest :
      (s.card : ℝ) ≤ (largestInducedBipartiteSubgraphSize G : ℝ) := by
    exact_mod_cast
      (card_le_largestInducedBipartiteSubgraphSize_of_induce_isBipartite
        (G := G) (s := s) hs_bip)
  exact le_trans hs_card hs_largest

variable [Fintype α] [DecidableEq α] [Nontrivial α]

/-- WOWII Conjecture 13, derived from the per-vertex strengthening. -/
theorem conjecture13 (G : SimpleGraph α) (h : G.Connected) :
    letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    (G.diam : ℝ) + (maxL : ℝ) - 1 ≤ b G := by
  classical
  refine conjecture13_from_vertex_bipartite_witnesses_final_shape (G := G) h ?_
  intro v
  exact exists_diam_add_indepNeighborsCard_sub_one_bipartite_witness (G := G) h v

end SimpleGraph
