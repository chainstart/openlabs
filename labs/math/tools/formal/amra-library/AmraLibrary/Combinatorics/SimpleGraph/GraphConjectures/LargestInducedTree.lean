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

import Mathlib.Combinatorics.SimpleGraph.Acyclic
import Mathlib.Combinatorics.SimpleGraph.Clique
import Mathlib.Combinatorics.SimpleGraph.Finite
import Mathlib.Combinatorics.SimpleGraph.Girth
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.SuppressCompilation

suppress_compilation

/-!
# Largest induced trees and local neighbourhood independence

Reusable graph-conjecture lemmas extracted from the formal proof of WOWII
Conjecture 141.
-/

namespace SimpleGraph

open Classical

set_option linter.unusedSectionVars false
set_option linter.unnecessarySimpa false

variable {α : Type*} [Fintype α] [DecidableEq α]

/-- `largestInducedTreeSize G` is the number of vertices in a largest induced
subtree of `G`. A tree is a connected acyclic graph; an induced tree is an
induced subgraph that is a tree. -/
noncomputable def largestInducedTreeSize (G : SimpleGraph α) : ℕ :=
  sSup { n | ∃ s : Finset α, s.card = n ∧ (G.induce (s : Set α)).IsTree }

/-- `largestInducedBipartiteSubgraphSize G` is the number of vertices in a
largest induced bipartite subgraph of `G`. -/
noncomputable def largestInducedBipartiteSubgraphSize (G : SimpleGraph α) : ℕ :=
  sSup { n | ∃ s : Finset α, (G.induce (s : Set α)).IsBipartite ∧ s.card = n }

/-- WOWII notation for the order of a largest induced bipartite subgraph. -/
noncomputable abbrev b (G : SimpleGraph α) : ℕ :=
  largestInducedBipartiteSubgraphSize G

/-- `largestInducedForestSize G` is the number of vertices in a largest induced
forest of `G`. -/
noncomputable def largestInducedForestSize (G : SimpleGraph α) : ℕ :=
  sSup { n | ∃ s : Finset α, (G.induce (s : Set α)).IsAcyclic ∧ s.card = n }

/-- Independence number of the neighbourhood of `v`. -/
noncomputable def indepNeighborsCard (G : SimpleGraph α) (v : α) : ℕ :=
  (G.induce (G.neighborSet v)).indepNum

/-- Sum of the local neighbourhood independence numbers. -/
noncomputable def l_sum (G : SimpleGraph α) : ℕ :=
  ∑ v : α, indepNeighborsCard G v

/-- Average local neighbourhood independence number, in the rational form used
by the WOWII conjecture statements. -/
noncomputable def l_avg (G : SimpleGraph α) : ℚ :=
  (G.l_sum : ℚ) / Fintype.card α

/-- If a finite connected graph is acyclic, the whole vertex set is an induced tree. -/
theorem card_le_largestInducedTreeSize_of_connected_acyclic
    {G : SimpleGraph α} [Nonempty α] (hconn : G.Connected) (hacyc : G.IsAcyclic) :
    Fintype.card α ≤ largestInducedTreeSize G := by
  classical
  unfold largestInducedTreeSize
  apply le_csSup
  · exact ⟨Fintype.card α, by
      intro n hn
      rcases hn with ⟨t, rfl, _ht⟩
      exact Finset.card_le_univ t⟩
  · refine ⟨Finset.univ, by simp, ?_⟩
    haveI : Nonempty (↥(((Finset.univ : Finset α) : Set α))) := by
      exact ⟨⟨Classical.choice inferInstance, by simp⟩⟩
    constructor
    · refine ⟨fun x y ↦ ?_⟩
      rcases hconn x.1 y.1 with ⟨p⟩
      exact ⟨p.induce ((Finset.univ : Finset α) : Set α) (by intro z hz; simp)⟩
    · simpa using hacyc.induce (((Finset.univ : Finset α) : Set α))

/-- Girth at least four rules out triangles. -/
theorem cliqueFree_three_of_four_le_girth {G : SimpleGraph α} (hg : 4 ≤ G.girth) :
    G.CliqueFree 3 := by
  intro t ht
  obtain ⟨_u, w, hwc, _hlen⟩ :=
    SimpleGraph.is3Clique_iff_exists_cycle_length_three.mp ⟨t, ht⟩
  have hgle : G.girth ≤ w.length := G.girth_le_length hwc
  omega

/-- In a graph of girth at least four, every open neighbourhood is independent. -/
theorem isIndepSet_neighborSet_of_four_le_girth {G : SimpleGraph α} (hg : 4 ≤ G.girth)
    (v : α) :
    G.IsIndepSet (G.neighborSet v) := by
  exact G.isIndepSet_neighborSet_of_triangleFree (cliqueFree_three_of_four_le_girth hg) v

/-- In a graph of girth at least four, the neighbourhood independence number is
the whole neighbourhood size. -/
theorem indepNeighborsCard_eq_card_neighborSet_of_four_le_girth {G : SimpleGraph α}
    (hg : 4 ≤ G.girth) (v : α) :
    indepNeighborsCard G v = Fintype.card (G.neighborSet v) := by
  classical
  unfold indepNeighborsCard
  apply le_antisymm
  · unfold SimpleGraph.indepNum
    apply csSup_le
    · exact ⟨0, by simp [SimpleGraph.isNIndepSet_iff]⟩
    · intro n hn
      rcases hn with ⟨s, hs⟩
      rw [SimpleGraph.isNIndepSet_iff] at hs
      rw [← hs.2]
      exact Finset.card_le_univ s
  · have hInd : (G.induce (G.neighborSet v)).IsIndepSet
        (Finset.univ : Finset (G.neighborSet v)) := by
      intro x _hx y _hy hxy hAdj
      exact (isIndepSet_neighborSet_of_four_le_girth hg v) x.2 y.2
        (fun h => hxy (Subtype.ext h)) hAdj
    simpa using SimpleGraph.IsIndepSet.card_le_indepNum hInd

/-- A vertex together with any maximum independent subset of its neighbourhood
induces a star, so it gives an induced tree of size `indepNeighborsCard G v + 1`. -/
theorem indepNeighborsCard_add_one_le_largestInducedTreeSize
    {G : SimpleGraph α} (v : α) :
    indepNeighborsCard G v + 1 ≤ largestInducedTreeSize G := by
  classical
  unfold largestInducedTreeSize
  apply le_csSup
  · exact ⟨Fintype.card α, by
      intro n hn
      rcases hn with ⟨t, rfl, _ht⟩
      exact Finset.card_le_univ t⟩
  · unfold indepNeighborsCard
    obtain ⟨s, hs⟩ := (G.induce (G.neighborSet v)).exists_isNIndepSet_indepNum
    rw [SimpleGraph.isNIndepSet_iff] at hs
    let e : G.neighborSet v ↪ α := Function.Embedding.subtype _
    let t : Finset α := insert v (s.map e)
    refine ⟨t, ?_, ?_⟩
    · simp only [t]
      rw [Finset.card_insert_of_notMem]
      · rw [Finset.card_map]
        exact congrArg Nat.succ hs.2
      · simp only [Finset.mem_map, not_exists, not_and]
        intro w _hw hww
        have hadj : G.Adj v w.1 := w.2
        change w.1 = v at hww
        have hadjvv : G.Adj v v := by
          rwa [hww] at hadj
        exact G.irrefl hadjvv
    · constructor
      · refine ⟨fun x y => ?_⟩
        let cv : (t : Set α) := ⟨v, by simp [t]⟩
        have hto_center :
            ∀ z : (t : Set α), (G.induce (t : Set α)).Reachable z cv := by
          intro z
          by_cases hzv : z.1 = v
          · exact (Subtype.ext (by simpa [cv] using hzv) : z = cv) ▸ Reachable.refl z
          · have hzmap : z.1 ∈ s.map e := by
              have hzmem : z.1 ∈ t := z.2
              simp only [t, Finset.mem_insert] at hzmem
              exact hzmem.resolve_left hzv
            rw [Finset.mem_map] at hzmap
            rcases hzmap with ⟨w, _hw, hwz⟩
            have hadj : G.Adj z.1 v := by
              rw [← hwz]
              exact (w.2 : G.Adj v w.1).symm
            exact ⟨(show (G.induce (t : Set α)).Adj z cv from hadj).toWalk⟩
        exact (hto_center x).trans (hto_center y).symm
      · intro u c hc
        have leaf_adj_center :
            ∀ (z w : (t : Set α)), z.1 ≠ v →
              (G.induce (t : Set α)).Adj z w → w.1 = v := by
          intro z w hzv hzw
          have hzmap : z.1 ∈ s.map e := by
            have hzmem : z.1 ∈ t := z.2
            simp only [t, Finset.mem_insert] at hzmem
            exact hzmem.resolve_left hzv
          rw [Finset.mem_map] at hzmap
          rcases hzmap with ⟨a, ha, haz⟩
          change a.1 = z.1 at haz
          by_cases hwv : w.1 = v
          · exact hwv
          have hwmap : w.1 ∈ s.map e := by
            have hwmem : w.1 ∈ t := w.2
            simp only [t, Finset.mem_insert] at hwmem
            exact hwmem.resolve_left hwv
          rw [Finset.mem_map] at hwmap
          rcases hwmap with ⟨b, hb, hbw⟩
          change b.1 = w.1 at hbw
          have habadj : (G.induce (G.neighborSet v)).Adj a b := by
            change G.Adj a.1 b.1
            rw [haz, hbw]
            exact hzw
          by_cases hab : a = b
          · subst hab
            exact False.elim (G.irrefl habadj)
          · exact False.elim ((hs.1 ha hb (fun h => hab h)) habadj)
        have no_cycle_at_leaf :
            ∀ {u : (t : Set α)} (c : (G.induce (t : Set α)).Walk u u),
              c.IsCycle → u.1 ≠ v → False := by
          intro u c hc huv
          have hsnd : c.snd.1 = v :=
            leaf_adj_center u c.snd huv (c.adj_snd hc.not_nil)
          have hpen : c.penultimate.1 = v :=
            leaf_adj_center u c.penultimate huv (c.adj_penultimate hc.not_nil).symm
          exact hc.snd_ne_penultimate (Subtype.ext (hsnd.trans hpen.symm))
        by_cases huv : u.1 = v
        · have hsnd_ne : c.snd.1 ≠ v := by
            intro hsnd
            have hadj : (G.induce (t : Set α)).Adj u c.snd := c.adj_snd hc.not_nil
            have hadjG : G.Adj u.1 c.snd.1 := hadj
            have : G.Adj v v := by
              rw [huv, hsnd] at hadjG
              exact hadjG
            exact G.irrefl this
          have hmem : c.snd ∈ c.support :=
            List.mem_of_mem_tail (c.snd_mem_tail_support hc.not_nil)
          exact no_cycle_at_leaf (c.rotate hmem) (hc.rotate hmem) hsnd_ne
        · exact no_cycle_at_leaf c hc huv

/-- Any explicit induced forest gives a lower bound for
`largestInducedForestSize`. -/
theorem card_le_largestInducedForestSize_of_induce_isAcyclic
    {G : SimpleGraph α} {s : Finset α}
    (hs : (G.induce (s : Set α)).IsAcyclic) :
    s.card ≤ largestInducedForestSize G := by
  classical
  unfold largestInducedForestSize
  apply le_csSup
  · exact ⟨Fintype.card α, by
      intro n hn
      rcases hn with ⟨t, _ht, rfl⟩
      exact Finset.card_le_univ t⟩
  · exact ⟨s, hs, rfl⟩

/-- Any explicit induced tree gives a lower bound for
`largestInducedForestSize`. -/
theorem card_le_largestInducedForestSize_of_induce_isTree
    {G : SimpleGraph α} {s : Finset α}
    (hs : (G.induce (s : Set α)).IsTree) :
    s.card ≤ largestInducedForestSize G :=
  card_le_largestInducedForestSize_of_induce_isAcyclic hs.IsAcyclic

/-- A graph containing an explicit triangle is not acyclic. -/
theorem not_isAcyclic_of_triangle {G : SimpleGraph α} {x y z : α}
    (hxy : G.Adj x y) (hyz : G.Adj y z) (hzx : G.Adj z x)
    (hxy_ne : x ≠ y) (hyz_ne : y ≠ z) (hzx_ne : z ≠ x) :
    ¬ G.IsAcyclic := by
  intro hacyc
  let p : G.Walk x x := Walk.cons hxy (Walk.cons hyz (Walk.cons hzx Walk.nil))
  have hp : p.IsCycle := by
    simp [p, Walk.cons_isCycle_iff, Walk.cons_isPath_iff,
      hxy_ne, hyz_ne, hzx_ne, hxy_ne.symm, hzx_ne.symm]
  exact hacyc p hp

/-- A graph containing an explicit 4-cycle is not acyclic. -/
theorem not_isAcyclic_of_four_cycle {G : SimpleGraph α} {w x y z : α}
    (hwx : G.Adj w x) (hxy : G.Adj x y) (hyz : G.Adj y z) (hzw : G.Adj z w)
    (hwx_ne : w ≠ x) (hwy_ne : w ≠ y) (hwz_ne : w ≠ z)
    (hxy_ne : x ≠ y) (hxz_ne : x ≠ z) (hyz_ne : y ≠ z) :
    ¬ G.IsAcyclic := by
  intro hacyc
  let p : G.Walk w w := Walk.cons hwx (Walk.cons hxy (Walk.cons hyz (Walk.cons hzw Walk.nil)))
  have hp : p.IsCycle := by
    simp [p, Walk.cons_isCycle_iff, Walk.cons_isPath_iff,
      hwx_ne, hwy_ne, hwz_ne, hxy_ne, hxz_ne, hyz_ne,
      hwx_ne.symm, hwy_ne.symm, hwz_ne.symm]
  exact hacyc p hp

/-- To prove an upper bound on the largest induced forest size, it is enough to
bound the cardinality of every finset whose induced subgraph is acyclic. -/
theorem largestInducedForestSize_le_of_forall_induce_isAcyclic
    {G : SimpleGraph α} {N : ℕ}
    (h : ∀ s : Finset α, (G.induce (s : Set α)).IsAcyclic → s.card ≤ N) :
    largestInducedForestSize G ≤ N := by
  classical
  unfold largestInducedForestSize
  apply csSup_le
  · refine ⟨0, ?_⟩
    refine ⟨∅, ?_, by simp⟩
    haveI : Subsingleton (↥(((∅ : Finset α) : Set α))) := by
      constructor
      intro x _y
      exfalso
      simpa using x.2
    exact SimpleGraph.IsAcyclic.of_subsingleton
  · intro n hn
    rcases hn with ⟨s, hsacyc, rfl⟩
    exact h s hsacyc

/-- The largest induced tree size is bounded by the largest induced forest size. -/
theorem largestInducedTreeSize_le_largestInducedForestSize [Nonempty α]
    (G : SimpleGraph α) :
    largestInducedTreeSize G ≤ largestInducedForestSize G := by
  classical
  unfold largestInducedTreeSize
  apply csSup_le
  · let v : α := Classical.choice inferInstance
    refine ⟨1, ?_⟩
    refine ⟨{v}, by simp, ?_⟩
    haveI : Nonempty (↥((({v} : Finset α) : Set α))) := ⟨⟨v, by simp⟩⟩
    haveI : Subsingleton (↥((({v} : Finset α) : Set α))) := by
      constructor
      intro a b
      apply Subtype.ext
      have ha : a.1 = v := by simpa using a.2
      have hb : b.1 = v := by simpa using b.2
      exact ha.trans hb.symm
    exact SimpleGraph.IsTree.of_subsingleton
  · intro n hn
    rcases hn with ⟨s, hcard, hs⟩
    rw [← hcard]
    exact card_le_largestInducedForestSize_of_induce_isTree hs

/-- Any explicit induced bipartite subgraph gives a lower bound for
`largestInducedBipartiteSubgraphSize`. -/
theorem card_le_largestInducedBipartiteSubgraphSize_of_induce_isBipartite
    {G : SimpleGraph α} {s : Finset α}
    (hs : (G.induce (s : Set α)).IsBipartite) :
    s.card ≤ largestInducedBipartiteSubgraphSize G := by
  classical
  unfold largestInducedBipartiteSubgraphSize
  apply le_csSup
  · exact ⟨Fintype.card α, by
      intro n hn
      rcases hn with ⟨t, _ht, rfl⟩
      exact Finset.card_le_univ t⟩
  · exact ⟨s, hs, rfl⟩

/-- Two disjoint independent finsets induce a bipartite graph on their union. -/
theorem induce_union_indep_isBipartite
    {G : SimpleGraph α} {A B : Finset α}
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

/-- A shortest walk has no chord that skips at least one internal edge. -/
theorem shortest_walk_no_forward_chord
    {G : SimpleGraph α} {u v : α} (p : G.Walk u v)
    (hp_len : p.length = G.dist u v) {i j : ℕ}
    (hi : i ≤ p.length) (_hj : j ≤ p.length) (hgap : i + 1 < j) :
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

/-- A vertex together with any maximum independent subset of its neighbourhood
induces a bipartite star, giving a lower bound for the largest induced
bipartite subgraph. -/
theorem indepNeighborsCard_add_one_le_largestInducedBipartiteSubgraphSize
    {G : SimpleGraph α} (v : α) :
    indepNeighborsCard G v + 1 ≤ largestInducedBipartiteSubgraphSize G := by
  classical
  unfold largestInducedBipartiteSubgraphSize
  apply le_csSup
  · exact ⟨Fintype.card α, by
      intro n hn
      rcases hn with ⟨t, _ht, rfl⟩
      exact Finset.card_le_univ t⟩
  · unfold indepNeighborsCard
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
          simpa [hwx, hxv] using hadj
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
                simpa [hxv, hyv] using hxyG
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

end SimpleGraph
