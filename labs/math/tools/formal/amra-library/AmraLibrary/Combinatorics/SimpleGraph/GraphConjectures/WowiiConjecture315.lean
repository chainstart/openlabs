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
import AmraLibrary.Combinatorics.SimpleGraph.GraphConjectures.WellTotallyDominated
import Mathlib.Tactic

/-!
# Written on the Wall II - Conjecture 315

Formalization target for the natural-language support-vertex route identified
by AMRA.
-/

namespace SimpleGraph

open Classical

set_option linter.unusedSectionVars false
set_option linter.unnecessarySimpa false

variable {α : Type*} [Fintype α] [DecidableEq α]

private theorem walk_endpoint_eq_of_pendant_edge
    (G : SimpleGraph α) [DecidableRel G.Adj]
    {x y z : α} (hx : G.degree x = 1) (hy : G.degree y = 1)
    (hxy : G.Adj x y) (p : G.Walk x z) :
    z = x ∨ z = y := by
  classical
  have hxuniq : ∀ ⦃w : α⦄, G.Adj x w → w = y := by
    obtain ⟨_w, _hw, huniq⟩ := (degree_eq_one_iff_existsUnique_adj (G := G) (v := x)).mp hx
    intro w hw
    exact (huniq w hw).trans (huniq y hxy).symm
  have hyuniq : ∀ ⦃w : α⦄, G.Adj y w → w = x := by
    obtain ⟨_w, _hw, huniq⟩ := (degree_eq_one_iff_existsUnique_adj (G := G) (v := y)).mp hy
    intro w hw
    exact (huniq w hw).trans (huniq x hxy.symm).symm
  suffices h :
      ∀ {a b : α}, G.Walk a b → a = x ∨ a = y → b = x ∨ b = y from
    h p (Or.inl rfl)
  intro a b q
  induction q with
  | nil =>
      intro ha
      simpa using ha
  | @cons u v w huv q ih =>
      intro hu
      apply ih
      rcases hu with rfl | rfl
      · exact Or.inr (hxuniq huv)
      · exact Or.inl (hyuniq huv)

private theorem not_adj_of_mem_pendantVertices_of_indepNum_eq_pendant_card
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    (h : G.indepNum = (pendantVertices G).card)
    {x y : α} (hxP : x ∈ pendantVertices G) (hyP : y ∈ pendantVertices G) :
    ¬ G.Adj x y := by
  classical
  intro hxy
  have hxdeg : G.degree x = 1 := by
    simpa [pendantVertices] using hxP
  have hydeg : G.degree y = 1 := by
    simpa [pendantVertices] using hyP
  have hxyne : x ≠ y := hxy.ne
  have hall : ∀ z : α, z = x ∨ z = y := by
    intro z
    rcases hG x z with ⟨p⟩
    exact walk_endpoint_eq_of_pendant_edge G hxdeg hydeg hxy p
  have hindep_le_one : G.indepNum ≤ 1 := by
    obtain ⟨I, hI⟩ := G.exists_isNIndepSet_indepNum
    rw [SimpleGraph.isNIndepSet_iff] at hI
    rw [← hI.2]
    apply Finset.card_le_one_iff.mpr
    intro a b ha hb
    rcases hall a with rfl | rfl <;> rcases hall b with rfl | rfl
    · rfl
    · exact False.elim (hI.1 ha hb hxyne hxy)
    · exact False.elim (hI.1 ha hb hxyne.symm hxy.symm)
    · rfl
  have htwo_le_pendant : 2 ≤ (pendantVertices G).card := by
    have hsub : ({x, y} : Finset α) ⊆ pendantVertices G := by
      intro z hz
      simp only [Finset.mem_insert, Finset.mem_singleton] at hz
      rcases hz with rfl | rfl
      · exact hxP
      · exact hyP
    have hcard : ({x, y} : Finset α).card = 2 := by
      simp [hxyne]
    exact hcard ▸ Finset.card_le_card hsub
  have htwo_le_indep : 2 ≤ G.indepNum := by
    rw [h]
    exact htwo_le_pendant
  omega

private theorem pendantVertices_independent_of_indepNum_eq_pendant_card
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    (h : G.indepNum = (pendantVertices G).card) :
    G.IsIndepSet ((pendantVertices G : Finset α) : Set α) := by
  classical
  intro x hx y hy hxy_ne hxy
  exact not_adj_of_mem_pendantVertices_of_indepNum_eq_pendant_card G hG h hx hy hxy

/-- Under the equality `α(G)=|P|`, every non-pendant vertex is adjacent to a
pendant vertex. This is the first structural lemma in the proof of WOWII
Conjecture 315. -/
theorem nonpendant_adjacent_pendant_of_indepNum_eq_pendant_card
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    (h : G.indepNum = (pendantVertices G).card) :
    ∀ v : α, v ∉ pendantVertices G →
      ∃ l ∈ pendantVertices G, G.Adj v l := by
  classical
  intro v hvP
  by_contra hnone
  have hno :
      ∀ l : α, l ∈ pendantVertices G → ¬ G.Adj v l := by
    intro l hl hvl
    exact hnone ⟨l, hl, hvl⟩
  let S : Finset α := insert v (pendantVertices G)
  have hS_indep : G.IsIndepSet (S : Set α) := by
    have hP_indep := pendantVertices_independent_of_indepNum_eq_pendant_card G hG h
    intro x hx y hy hxy_ne hxy
    simp only [S, Finset.coe_insert, Set.mem_insert_iff] at hx hy
    rcases hx with rfl | hxP
    · rcases hy with rfl | hyP
      · exact hxy_ne rfl
      · exact hno y hyP hxy
    · rcases hy with rfl | hyP
      · exact hno x hxP hxy.symm
      · exact hP_indep hxP hyP hxy_ne hxy
  have hcard : S.card = (pendantVertices G).card + 1 := by
    simp [S, hvP, Nat.add_comm]
  have hle : S.card ≤ G.indepNum :=
    SimpleGraph.IsIndepSet.card_le_indepNum hS_indep
  rw [hcard, h] at hle
  omega

private theorem eq_of_adj_of_mem_pendantVertices
    (G : SimpleGraph α) [DecidableRel G.Adj]
    {l u w : α} (hlP : l ∈ pendantVertices G)
    (hlu : G.Adj l u) (hlw : G.Adj l w) :
    w = u := by
  classical
  have hldeg : G.degree l = 1 := by
    simpa [pendantVertices] using hlP
  obtain ⟨_x, _hx, huniq⟩ :=
    (degree_eq_one_iff_existsUnique_adj (G := G) (v := l)).mp hldeg
  exact (huniq w hlw).trans (huniq u hlu).symm

private theorem neighbor_notMem_pendantVertices_of_mem_pendantVertices
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    (h : G.indepNum = (pendantVertices G).card)
    {l u : α} (hlP : l ∈ pendantVertices G) (hlu : G.Adj l u) :
    u ∉ pendantVertices G := by
  intro huP
  exact not_adj_of_mem_pendantVertices_of_indepNum_eq_pendant_card G hG h hlP huP hlu

private theorem nonpendants_subset_of_isTotalDominatingSet
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    (h : G.indepNum = (pendantVertices G).card)
    {A : Finset α} (hA : IsTotalDominatingSet G A) :
    (Finset.univ \ pendantVertices G) ⊆ A := by
  classical
  intro v hv
  have hvP : v ∉ pendantVertices G := by
    simpa using hv
  obtain ⟨l, hlP, hvl⟩ :=
    nonpendant_adjacent_pendant_of_indepNum_eq_pendant_card G hG h v hvP
  obtain ⟨w, hwA, hlw⟩ := hA l
  have hwv : w = v :=
    eq_of_adj_of_mem_pendantVertices G hlP hvl.symm hlw
  simpa [hwv] using hwA

private theorem exists_nonpendant_neighbor_of_nonpendant_of_one_lt_card
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    {v : α}
    (hv : v ∈ Finset.univ \ pendantVertices G)
    (hcard : 1 < (Finset.univ \ pendantVertices G).card) :
    ∃ w ∈ Finset.univ \ pendantVertices G, G.Adj v w := by
  classical
  let N : Finset α := Finset.univ \ pendantVertices G
  have hvN : v ∈ N := hv
  have hNnontriv : N.Nontrivial := by
    exact Finset.one_lt_card_iff_nontrivial.mp hcard
  obtain ⟨b, hbN, hbv⟩ := hNnontriv.exists_ne v
  obtain ⟨p, hp_path, _hp_dist⟩ := (hG v b).exists_path_of_dist
  have hp_not_nil : ¬ p.Nil := Walk.not_nil_of_ne (by exact hbv.symm)
  refine ⟨p.snd, ?_, p.adj_snd hp_not_nil⟩
  have hp_snd_notP : p.snd ∉ pendantVertices G := by
    intro hsndP
    cases p with
    | nil =>
        exact hp_not_nil Walk.Nil.nil
    | cons hua q =>
        simp only [Walk.snd_cons] at hsndP
        rw [Walk.cons_isPath_iff] at hp_path
        cases q with
        | nil =>
            have hb_notP : b ∉ pendantVertices G := by
              simpa [N] using hbN
            exact hb_notP hsndP
        | cons hac r =>
            have hsnd_eq : (Walk.cons hac r).snd = v := by
              simpa [Walk.snd_cons] using
                eq_of_adj_of_mem_pendantVertices G hsndP hua.symm hac
            have hv_mem : v ∈ (Walk.cons hac r).support := by
              rw [← hsnd_eq]
              exact List.mem_of_mem_tail
                (Walk.snd_mem_tail_support (p := Walk.cons hac r) (by simp))
            exact hp_path.2 hv_mem
  simpa [N, hp_snd_notP]

private theorem nonpendants_isTotalDominatingSet_of_one_lt_card
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    (h : G.indepNum = (pendantVertices G).card)
    (hcard : 1 < (Finset.univ \ pendantVertices G).card) :
    IsTotalDominatingSet G (Finset.univ \ pendantVertices G) := by
  classical
  intro v
  by_cases hvP : v ∈ pendantVertices G
  · have hvdeg : G.degree v = 1 := by
      simpa [pendantVertices] using hvP
    obtain ⟨w, hvw, _huniq⟩ :=
      (degree_eq_one_iff_existsUnique_adj (G := G) (v := v)).mp hvdeg
    refine ⟨w, ?_, hvw⟩
    have hwP : w ∉ pendantVertices G :=
      neighbor_notMem_pendantVertices_of_mem_pendantVertices G hG h hvP hvw
    simpa [hwP]
  · have hvN : v ∈ Finset.univ \ pendantVertices G := by
      simp [hvP]
    exact exists_nonpendant_neighbor_of_nonpendant_of_one_lt_card G hG hvN hcard

private theorem minimal_tds_eq_nonpendants_of_one_lt_card
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    (h : G.indepNum = (pendantVertices G).card)
    {A : Finset α} (hA : IsMinimalTotalDominatingSet G A)
    (hcard : 1 < (Finset.univ \ pendantVertices G).card) :
    A = Finset.univ \ pendantVertices G := by
  classical
  let N : Finset α := Finset.univ \ pendantVertices G
  have hNA : N ⊆ A :=
    nonpendants_subset_of_isTotalDominatingSet G hG h hA.1
  have hNtds : IsTotalDominatingSet G N :=
    nonpendants_isTotalDominatingSet_of_one_lt_card G hG h hcard
  apply Finset.Subset.antisymm ?_ hNA
  intro a ha
  by_contra haN
  have hproper : N ⊂ A := by
    exact Finset.ssubset_iff_subset_ne.mpr
      ⟨hNA, by
        intro hEq
        exact haN (by simpa [hEq] using ha)⟩
  exact (hA.2 N hproper hNtds).elim

private theorem minimal_tds_card_eq_two_of_nonpendants_card_le_one
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    (h : G.indepNum = (pendantVertices G).card)
    {A : Finset α} (hA : IsMinimalTotalDominatingSet G A)
    (hcard : (Finset.univ \ pendantVertices G).card ≤ 1) :
    A.card = 2 := by
  classical
  let N : Finset α := Finset.univ \ pendantVertices G
  have hNA : N ⊆ A :=
    nonpendants_subset_of_isTotalDominatingSet G hG h hA.1
  obtain ⟨x⟩ := hG.nonempty
  have hN_nonempty : N.Nonempty := by
    by_cases hxP : x ∈ pendantVertices G
    · obtain ⟨y, _hyA, hxy⟩ := hA.1 x
      refine ⟨y, ?_⟩
      have hyP : y ∉ pendantVertices G :=
        neighbor_notMem_pendantVertices_of_mem_pendantVertices G hG h hxP hxy
      simpa [N, hyP]
    · exact ⟨x, by simp [N, hxP]⟩
  obtain ⟨c, hcN⟩ := hN_nonempty
  have hcA : c ∈ A := hNA hcN
  obtain ⟨w, hwA, hcw⟩ := hA.1 c
  have hwc_ne : w ≠ c := hcw.ne'
  let U : Finset α := {c, w}
  have hUA : U ⊆ A := by
    intro z hz
    simp only [U, Finset.mem_insert, Finset.mem_singleton] at hz
    rcases hz with rfl | rfl
    · exact hcA
    · exact hwA
  have hUtds : IsTotalDominatingSet G U := by
    intro z
    by_cases hzP : z ∈ pendantVertices G
    · have hzdeg : G.degree z = 1 := by
        simpa [pendantVertices] using hzP
      obtain ⟨u, hzu, _huniq⟩ :=
        (degree_eq_one_iff_existsUnique_adj (G := G) (v := z)).mp hzdeg
      have huP : u ∉ pendantVertices G :=
        neighbor_notMem_pendantVertices_of_mem_pendantVertices G hG h hzP hzu
      have huN : u ∈ N := by
        simp [N, huP]
      have huc : u = c :=
        (Finset.card_le_one.mp hcard) u huN c hcN
      refine ⟨c, ?_, ?_⟩
      · simp [U]
      · simpa [huc] using hzu
    · have hzN : z ∈ N := by
        simp [N, hzP]
      have hzc : z = c :=
        (Finset.card_le_one.mp hcard) z hzN c hcN
      refine ⟨w, ?_, ?_⟩
      · simp [U]
      · simpa [hzc] using hcw
  have hAU : A ⊆ U := by
    intro a ha
    by_contra haU
    have hproper : U ⊂ A := by
      exact Finset.ssubset_iff_subset_ne.mpr
        ⟨hUA, by
          intro hEq
          exact haU (by simpa [hEq] using ha)⟩
    exact (hA.2 U hproper hUtds).elim
  have hAeq : A = U := Finset.Subset.antisymm hAU hUA
  have hUcard : U.card = 2 := by
    have hcw_ne : c ≠ w := hcw.ne
    simp [U, hcw_ne]
  rw [hAeq, hUcard]

/--
WOWII Conjecture 315: if a connected graph has independence number equal to the
number of pendant vertices, then it is well totally dominated.
-/
theorem conjecture315 (G : SimpleGraph α) [DecidableRel G.Adj]
    (hG : G.Connected)
    (h : G.indepNum = (pendantVertices G).card) :
    IsWellTotallyDominated G := by
  classical
  intro S T hS hT
  by_cases hcard : 1 < (Finset.univ \ pendantVertices G).card
  · have hSeq := minimal_tds_eq_nonpendants_of_one_lt_card G hG h hS hcard
    have hTeq := minimal_tds_eq_nonpendants_of_one_lt_card G hG h hT hcard
    rw [hSeq, hTeq]
  · have hcard_le : (Finset.univ \ pendantVertices G).card ≤ 1 := by omega
    rw [minimal_tds_card_eq_two_of_nonpendants_card_le_one G hG h hS hcard_le,
      minimal_tds_card_eq_two_of_nonpendants_card_le_one G hG h hT hcard_le]

end SimpleGraph
