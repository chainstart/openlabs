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
import Mathlib.Tactic

/-!
# Written on the Wall II - Conjecture 17

*Reference:*
[E. DeLaVina, Written on the Wall II, Conjectures of Graffiti.pc](http://cms.dt.uh.edu/faculty/delavinae/research/wowII/)
-/


namespace WrittenOnTheWallII.GraphConjecture17

open Classical SimpleGraph

variable {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]

set_option linter.unusedSectionVars false
set_option linter.unnecessarySimpa false

theorem pair_right_index_le_diam {D j : ℕ} (hj : j < (D + 2) / 3) :
    3 * j + 1 ≤ D := by
  omega

theorem pair_choices_have_gap {i j a b : ℕ}
    (hij : i < j) (ha0 : 3 * i ≤ a) (ha1 : a ≤ 3 * i + 1)
    (hb0 : 3 * j ≤ b) :
    a + 2 ≤ b := by
  omega

theorem path_adjacent_pair_not_both_in_indep
    {G : SimpleGraph α} {u v : α} (p : G.Walk u v) {i : ℕ}
    (hi : i < p.length) (I : Finset α) (hI : G.IsIndepSet (I : Set α)) :
    ¬ (p.getVert i ∈ I ∧ p.getVert (i + 1) ∈ I) := by
  rintro ⟨hiI, hi1I⟩
  have hadj : G.Adj (p.getVert i) (p.getVert (i + 1)) := p.adj_getVert_succ hi
  exact hI hiI hi1I hadj.ne hadj

theorem shortest_walk_no_forward_chord
    {G : SimpleGraph α} {u v : α} (p : G.Walk u v)
    (hp_len : p.length = G.dist u v) {i j : ℕ}
    (hi : i ≤ p.length) (hj : j ≤ p.length) (hgap : i + 1 < j) :
    ¬ G.Adj (p.getVert i) (p.getVert j) := by
  intro hadj
  let q : G.Walk u v := ((p.take i).concat hadj).append (p.drop j)
  have hq_len : q.length = i + 1 + (p.length - j) := by
    simp [q, SimpleGraph.Walk.length_append, SimpleGraph.Walk.length_concat,
      SimpleGraph.Walk.take_length, SimpleGraph.Walk.drop_length,
      Nat.min_eq_left hi]
  have hq_short : q.length < p.length := by
    rw [hq_len]
    omega
  have hdist_le : G.dist u v ≤ q.length := SimpleGraph.dist_le q
  omega

/-- Pick one vertex outside `I` from every diameter-geodesic pair
`(p.getVert (3*j), p.getVert (3*j+1))`. -/
theorem exists_diameter_pair_selection
    {G : SimpleGraph α} {u v : α} (p : G.Walk u v)
    (hp_path : p.IsPath) (hp_dist : p.length = G.dist u v)
    (hp_diam : p.length = G.diam)
    (I : Finset α) (hI : G.IsIndepSet (I : Set α)) :
    ∃ S : Finset α,
      S.card = (G.diam + 2) / 3 ∧
      Disjoint I S ∧
      G.IsIndepSet (S : Set α) := by
  classical
  let k : ℕ := (G.diam + 2) / 3
  let idx : Fin k → ℕ := fun j =>
    if p.getVert (3 * j.1) ∈ I then 3 * j.1 + 1 else 3 * j.1
  let pick : Fin k → α := fun j => p.getVert (idx j)
  let S : Finset α := Finset.univ.image pick
  have idx_bounds : ∀ j : Fin k, 3 * j.1 ≤ idx j ∧ idx j ≤ 3 * j.1 + 1 := by
    intro j
    dsimp [idx]
    by_cases hj : p.getVert (3 * j.1) ∈ I <;> simp [hj]
  have idx_le_length : ∀ j : Fin k, idx j ≤ p.length := by
    intro j
    have hright : 3 * j.1 + 1 ≤ G.diam := by
      exact pair_right_index_le_diam (D := G.diam) (j := j.1) (by simpa [k] using j.2)
    have hb := (idx_bounds j).2
    omega
  have pick_not_mem : ∀ j : Fin k, pick j ∉ I := by
    intro j
    have hright : 3 * j.1 + 1 ≤ G.diam := by
      exact pair_right_index_le_diam (D := G.diam) (j := j.1) (by simpa [k] using j.2)
    have hedge_index : 3 * j.1 < p.length := by omega
    dsimp [pick, idx]
    by_cases hj : p.getVert (3 * j.1) ∈ I
    · simp only [if_pos hj]
      intro hright_mem
      exact path_adjacent_pair_not_both_in_indep p hedge_index I hI ⟨hj, hright_mem⟩
    · simp only [if_neg hj]
      exact hj
  have pick_injective : Function.Injective pick := by
    intro a b hab
    apply Fin.ext
    by_contra hne
    have hidxeq : idx a = idx b := by
      exact hp_path.getVert_injOn (idx_le_length a) (idx_le_length b) hab
    have hlt_or_gt : a.1 < b.1 ∨ b.1 < a.1 := Nat.lt_or_gt_of_ne (by
      intro h
      exact hne h)
    rcases hlt_or_gt with hlt | hgt
    · have hgap : idx a + 2 ≤ idx b := by
        exact pair_choices_have_gap (i := a.1) (j := b.1) (a := idx a) (b := idx b)
          hlt (idx_bounds a).1 (idx_bounds a).2 (idx_bounds b).1
      omega
    · have hgap : idx b + 2 ≤ idx a := by
        exact pair_choices_have_gap (i := b.1) (j := a.1) (a := idx b) (b := idx a)
          hgt (idx_bounds b).1 (idx_bounds b).2 (idx_bounds a).1
      omega
  refine ⟨S, ?_, ?_, ?_⟩
  · dsimp [S]
    rw [Finset.card_image_of_injective _ pick_injective, Finset.card_univ, Fintype.card_fin]
  · rw [Finset.disjoint_left]
    intro x hxI hxS
    change x ∈ Finset.univ.image pick at hxS
    rw [Finset.mem_image] at hxS
    rcases hxS with ⟨j, _hj, rfl⟩
    exact pick_not_mem j hxI
  · intro x hxS y hyS hxy hadj
    change x ∈ Finset.univ.image pick at hxS
    change y ∈ Finset.univ.image pick at hyS
    rw [Finset.mem_image] at hxS hyS
    rcases hxS with ⟨a, _ha, rfl⟩
    rcases hyS with ⟨b, _hb, rfl⟩
    by_cases hab : a = b
    · subst hab
      exact hxy rfl
    have hlt_or_gt : a.1 < b.1 ∨ b.1 < a.1 := Nat.lt_or_gt_of_ne (by
      intro h
      exact hab (Fin.ext h))
    rcases hlt_or_gt with hlt | hgt
    · have hgap_le : idx a + 2 ≤ idx b := by
        exact pair_choices_have_gap (i := a.1) (j := b.1) (a := idx a) (b := idx b)
          hlt (idx_bounds a).1 (idx_bounds a).2 (idx_bounds b).1
      exact shortest_walk_no_forward_chord p hp_dist (idx_le_length a) (idx_le_length b)
        (by omega) hadj
    · have hgap_le : idx b + 2 ≤ idx a := by
        exact pair_choices_have_gap (i := b.1) (j := a.1) (a := idx b) (b := idx a)
          hgt (idx_bounds b).1 (idx_bounds b).2 (idx_bounds a).1
      exact shortest_walk_no_forward_chord p hp_dist (idx_le_length b) (idx_le_length a)
        (by omega) hadj.symm

theorem card_le_largestInducedBipartiteSubgraphSize
    (G : SimpleGraph α) (s : Finset α)
    (hs : (G.induce (s : Set α)).IsBipartite) :
    s.card ≤ largestInducedBipartiteSubgraphSize G := by
  unfold largestInducedBipartiteSubgraphSize
  apply le_csSup
  · exact ⟨Fintype.card α, by
      intro n hn
      rcases hn with ⟨t, _ht, rfl⟩
      exact Finset.card_le_univ t⟩
  · exact ⟨s, hs, rfl⟩

theorem induce_union_indep_isBipartite
    (G : SimpleGraph α) (A B : Finset α)
    (hA : G.IsIndepSet (A : Set α))
    (hB : G.IsIndepSet (B : Set α))
    (hdisj : Disjoint A B) :
    (G.induce ((A ∪ B : Finset α) : Set α)).IsBipartite := by
  classical
  let U : Set α := ((A ∪ B : Finset α) : Set α)
  let left : Set U := {x | x.1 ∈ A}
  let right : Set U := {x | x.1 ∈ B}
  change (G.induce U).IsBipartite
  refine (show (G.induce U).IsBipartiteWith left right from ?_).isBipartite
  constructor
  · rw [Set.disjoint_left]
    intro x hxA hxB
    exact (Finset.disjoint_left.mp hdisj hxA) hxB
  · intro x y hxy
    have hxmem : x.1 ∈ A ∪ B := x.2
    have hymem : y.1 ∈ A ∪ B := y.2
    rw [Finset.mem_union] at hxmem hymem
    rcases hxmem with hxA | hxB
    · rcases hymem with hyA | hyB
      · exact False.elim (hA hxA hyA (fun h => hxy.ne (Subtype.ext h)) hxy)
      · exact Or.inl ⟨hxA, hyB⟩
    · rcases hymem with hyA | hyB
      · exact Or.inr ⟨hxB, hyA⟩
      · exact False.elim (hB hxB hyB (fun h => hxy.ne (Subtype.ext h)) hxy)

theorem exists_indep_set_card_indepNum (G : SimpleGraph α) :
    ∃ I : Finset α, G.IsIndepSet (I : Set α) ∧ I.card = G.indepNum := by
  obtain ⟨I, hI⟩ := G.exists_isNIndepSet_indepNum
  rw [SimpleGraph.isNIndepSet_iff] at hI
  exact ⟨I, hI.1, hI.2⟩

theorem exists_diameter_path_with_dist
    (G : SimpleGraph α) (h : G.Connected) :
    ∃ u v : α, ∃ p : G.Walk u v,
      p.IsPath ∧ p.length = G.dist u v ∧ p.length = G.diam := by
  obtain ⟨u, v, huv⟩ := G.exists_dist_eq_diam
  obtain ⟨p, hp_path, hp_dist⟩ := (h u v).exists_path_of_dist
  exact ⟨u, v, p, hp_path, hp_dist, by rw [hp_dist, huv]⟩

theorem conjecture17_nat_bound
    (G : SimpleGraph α) (h : G.Connected) :
    G.indepNum + (G.diam + 2) / 3 ≤ largestInducedBipartiteSubgraphSize G := by
  classical
  obtain ⟨I, hI_indep, hI_card⟩ := exists_indep_set_card_indepNum G
  obtain ⟨u, v, p, hp_path, hp_dist, hp_diam⟩ := exists_diameter_path_with_dist G h
  obtain ⟨S, hS_card, hIS_disj, hS_indep⟩ :=
    exists_diameter_pair_selection p hp_path hp_dist hp_diam I hI_indep
  have hBip : (G.induce (((I ∪ S : Finset α) : Set α))).IsBipartite :=
    induce_union_indep_isBipartite G I S hI_indep hS_indep hIS_disj
  have hwitness :
      (I ∪ S).card ≤ largestInducedBipartiteSubgraphSize G :=
    card_le_largestInducedBipartiteSubgraphSize G (I ∪ S) hBip
  have hcard : (I ∪ S).card = G.indepNum + (G.diam + 2) / 3 := by
    rw [Finset.card_union_of_disjoint hIS_disj, hI_card, hS_card]
  exact hcard ▸ hwitness

theorem nat_ceil_div_three (D : ℕ) :
    ⌈(D : ℝ) / 3⌉₊ = (D + 2) / 3 := by
  by_cases hD : D = 0
  · subst D
    norm_num
  · rw [Nat.ceil_eq_iff]
    · constructor
      · have h1 : 3 * (((D + 2) / 3) - 1) < D := by omega
        have h1r : (3 : ℝ) * (((D + 2) / 3 - 1 : ℕ) : ℝ) < D := by
          exact_mod_cast h1
        nlinarith
      · have h2 : D ≤ 3 * ((D + 2) / 3) := by omega
        have h2r : (D : ℝ) ≤ (3 : ℝ) * (((D + 2) / 3 : ℕ) : ℝ) := by
          exact_mod_cast h2
        nlinarith
    · omega

theorem int_ceil_div_three_cast (D : ℕ) :
    ((⌈(D : ℝ) / 3⌉ : ℤ) : ℝ) = ((D + 2) / 3 : ℕ) := by
  have hnonneg : 0 ≤ (D : ℝ) / 3 := by positivity
  rw [← natCast_ceil_eq_intCast_ceil hnonneg]
  norm_cast
  exact nat_ceil_div_three D

theorem conjecture17_real_bound
    (G : SimpleGraph α) (h : G.Connected) :
    (G.indepNum : ℝ) + ⌈(G.diam : ℝ) / 3⌉ ≤ b G := by
  have hnat := conjecture17_nat_bound G h
  unfold b
  rw [int_ceil_div_three_cast G.diam]
  exact_mod_cast hnat

/--
WOWII [Conjecture 17](http://cms.dt.uh.edu/faculty/delavinae/research/wowII/)

For a simple connected graph `G`, the size `b(G)` of a largest induced bipartite subgraph
satisfies `b(G) ≥ α(G) + ⌈diam(G) / 3⌉`, where `α(G)` is the independence number of `G`
and `diam(G)` is the diameter of `G`.
-/
theorem conjecture17 (G : SimpleGraph α) (h : G.Connected) :
    (G.indepNum : ℝ) + ⌈(G.diam : ℝ) / 3⌉ ≤ b G := by
  exact conjecture17_real_bound G h

-- Sanity checks

/-- The invariant `b G` is nonneg (it's the cast of a natural number). -/
example (G : SimpleGraph (Fin 3)) : 0 ≤ b G := Nat.cast_nonneg _

/-- The independence number `α(K₂)` equals 1 (each independent set contains at most one vertex). -/
example : (⊤ : SimpleGraph (Fin 2)).edgeFinset.card = 1 := by decide +native

end WrittenOnTheWallII.GraphConjecture17
