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
# Written on the Wall II - Conjecture 141

*Reference:*
[E. DeLaVina, Written on the Wall II, Conjectures of Graffiti.pc](http://cms.dt.uh.edu/faculty/delavinae/research/wowII/)
-/

namespace WrittenOnTheWallII.GraphConjecture141

open Classical SimpleGraph

variable {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]

/--
WOWII [Conjecture 141](http://cms.dt.uh.edu/faculty/delavinae/research/wowII/)

For a simple connected graph `G`,
`tree(G) ≥ ⌈girth(G) / 2⌉ - 1 + max_v l(v)`
where `tree(G)` is the number of vertices of a largest induced tree subgraph,
`girth(G)` is the length of the shortest cycle (0 if acyclic), and
`l(v) = indepNeighbors G v` is the independence number of the neighbourhood of `v`.
-/
theorem conjecture141_strong (G : SimpleGraph α) (h : G.Connected) :
    (G.girth + 1) / 2 - 1 + (Finset.univ.sup (indepNeighborsCard G)) ≤
    largestInducedTreeSize G := by
  classical
  by_cases hacyc : G.IsAcyclic
  · have hwhole : Fintype.card α ≤ largestInducedTreeSize G := by
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
          rcases h x.1 y.1 with ⟨p⟩
          exact ⟨p.induce ((Finset.univ : Finset α) : Set α) (by intro z hz; simp)⟩
        · simpa using hacyc.induce (((Finset.univ : Finset α) : Set α))
    have hmax : (Finset.univ.sup (indepNeighborsCard G)) ≤ Fintype.card α := by
      apply Finset.sup_le
      intro v _hv
      unfold indepNeighborsCard SimpleGraph.indepNum
      apply csSup_le
      · exact ⟨0, by simp [SimpleGraph.isNIndepSet_iff]⟩
      · intro n hn
        rcases hn with ⟨s, hs⟩
        rw [SimpleGraph.isNIndepSet_iff] at hs
        rw [← hs.2]
        exact (Finset.card_le_univ s).trans (Fintype.card_subtype_le _)
    rw [hacyc.girth_eq_zero]
    simpa using hmax.trans hwhole
  · have htriangleFree_of_girth : 4 ≤ G.girth → G.CliqueFree 3 := by
      intro hg t ht
      obtain ⟨_u, w, hwc, hlen⟩ :=
        SimpleGraph.is3Clique_iff_exists_cycle_length_three.mp ⟨t, ht⟩
      have hgle : G.girth ≤ w.length := G.girth_le_length hwc
      omega
    have hindep_neighbor_of_girth :
        4 ≤ G.girth → ∀ v, G.IsIndepSet (G.neighborSet v) := by
      intro hg v
      exact G.isIndepSet_neighborSet_of_triangleFree (htriangleFree_of_girth hg) v
    have hstar : ∀ v, indepNeighborsCard G v + 1 ≤ largestInducedTreeSize G := by
      intro v
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
            intro w hw hww
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
    by_cases hsmall : (G.girth + 1) / 2 - 1 ≤ 1
    · have hLpos : 0 < largestInducedTreeSize G := by
        have := hstar (Classical.choice inferInstance)
        omega
      have hsup_lt :
          (Finset.univ.sup (indepNeighborsCard G)) < largestInducedTreeSize G := by
        rw [Finset.sup_lt_iff hLpos]
        intro v _hv
        exact Nat.lt_of_succ_le (hstar v)
      have hsup_succ :
          (Finset.univ.sup (indepNeighborsCard G)) + 1 ≤ largestInducedTreeSize G :=
        Nat.succ_le_iff.mpr hsup_lt
      omega
    · have hg5 : 5 ≤ G.girth := by omega
      have hneighbor_eq_card :
          ∀ v, indepNeighborsCard G v = Fintype.card (G.neighborSet v) := by
        intro v
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
            exact (hindep_neighbor_of_girth (by omega) v) x.2 y.2
              (fun h => hxy (Subtype.ext h)) hAdj
          simpa using SimpleGraph.IsIndepSet.card_le_indepNum hInd
      have hlarge_tree :
          ∀ v, (G.girth + 1) / 2 - 1 + Fintype.card (G.neighborSet v) ≤
            largestInducedTreeSize G := by
        intro v
        let r := (G.girth + 1) / 2 - 1
        have hlong_path : ∃ w, ∃ p : G.Walk v w, p.IsPath ∧ r ≤ p.length := by
          obtain ⟨T, hTG, hTtree⟩ := h.exists_isTree_le
          by_contra hno
          push_neg at hno
          have hedge : ∃ x y, G.Adj x y ∧ ¬ T.Adj x y := by
            by_contra hnone
            push_neg at hnone
            have hGT : G ≤ T := by
              intro x y hxy
              exact hnone x y hxy
            exact hacyc (SimpleGraph.IsAcyclic.anti hGT hTtree.IsAcyclic)
          obtain ⟨x, y, hxyG, hxyT⟩ := hedge
          obtain ⟨pxy, hpxy_path, hpxy_len⟩ :=
            hTtree.isConnected.exists_path_of_dist x y
          have hnot_edge : s(x, y) ∉ (pxy.reverse.mapLe hTG).edges := by
            intro he
            have heT : s(x, y) ∈ pxy.edges := by
              simpa [SimpleGraph.Walk.edges_mapLe_eq_edges, SimpleGraph.Walk.edges_reverse] using he
            exact hxyT (pxy.adj_of_mem_edges heT)
          let cyc : G.Walk x x := (pxy.reverse.mapLe hTG).cons hxyG
          have hcyc : cyc.IsCycle := by
            dsimp [cyc]
            rw [SimpleGraph.Walk.cons_isCycle_iff]
            constructor
            · exact hpxy_path.reverse.mapLe hTG
            · exact hnot_edge
          have hg_le : G.girth ≤ cyc.length := G.girth_le_length hcyc
          obtain ⟨px, hpx_path, hpx_len⟩ := hTtree.isConnected.exists_path_of_dist v x
          obtain ⟨py, hpy_path, hpy_len⟩ := hTtree.isConnected.exists_path_of_dist v y
          have hxlt : T.dist v x < r := by
            have := hno x (px.mapLe hTG) (hpx_path.mapLe hTG)
            simpa [hpx_len] using this
          have hylt : T.dist v y < r := by
            have := hno y (py.mapLe hTG) (hpy_path.mapLe hTG)
            simpa [hpy_len] using this
          have hxy_len_le : pxy.length ≤ (r - 1) + (r - 1) := by
            rw [hpxy_len]
            have htri := hTtree.isConnected.dist_triangle (u := x) (v := v) (w := y)
            have hxlt' : T.dist x v < r := by
              rwa [SimpleGraph.dist_comm]
            omega
          have hcyc_len : cyc.length = pxy.length + 1 := by
            simp [cyc]
          have hshort : cyc.length < G.girth := by
            rw [hcyc_len]
            dsimp [r] at hxy_len_le ⊢
            omega
          omega
        -- It remains to build the induced tree on `G.neighborSet v` together with
        -- the first `r` edges of `hlong_path`.
        obtain ⟨w, p, hp_path, hrp⟩ := hlong_path
        let q : G.Walk v (p.getVert r) := p.take r
        have hq_path : q.IsPath := by
          rw [SimpleGraph.Walk.isPath_def]
          rw [SimpleGraph.Walk.take_support_eq_support_take_succ]
          exact hp_path.support_nodup.take
        have hq_len : q.length = r := by
          change (p.take r).length = r
          rw [SimpleGraph.Walk.take_length]
          exact Nat.min_eq_left hrp
        have hq_getVert_inj :
            Set.InjOn q.getVert {i | i ≤ r} := by
          intro i hi j hj hij
          exact hq_path.getVert_injOn (by simpa [hq_len] using hi)
            (by simpa [hq_len] using hj) hij
        have hroot_neighbor_support :
            ∀ x, x ∈ q.support.toFinset → x ∈ G.neighborFinset v → x = q.getVert 1 := by
          intro x hxq hxn
          rw [List.mem_toFinset] at hxq
          obtain ⟨i, hix, hiq⟩ := SimpleGraph.Walk.mem_support_iff_exists_getVert.mp hxq
          have hadj : G.Adj v x := (G.mem_neighborFinset v x).mp hxn
          subst x
          by_cases hi0 : i = 0
          · subst i
            simp only [SimpleGraph.Walk.getVert_zero] at hadj
            exact False.elim (G.irrefl hadj)
          by_cases hi1 : i = 1
          · simp [hi1]
          have hi2 : 2 ≤ i := by omega
          let qi : G.Walk v (q.getVert i) := q.take i
          have hqi_path : qi.IsPath := by
            rw [SimpleGraph.Walk.isPath_def]
            rw [SimpleGraph.Walk.take_support_eq_support_take_succ]
            exact hq_path.support_nodup.take
          have hqi_len : qi.length = i := by
            change (q.take i).length = i
            rw [SimpleGraph.Walk.take_length]
            exact Nat.min_eq_left (by simpa [hq_len] using hiq)
          have hedge_not : s(q.getVert i, v) ∉ qi.edges := by
            intro he
            have he' : s(v, q.getVert i) ∈ qi.edges := by
              simpa [Sym2.eq_swap] using he
            have hend_eq_snd : q.getVert i = qi.snd := hqi_path.eq_snd_of_mem_edges he'
            have hsnd : qi.snd = q.getVert 1 := by
              change (q.take i).getVert 1 = q.getVert 1
              rw [SimpleGraph.Walk.take_getVert]
              simp [Nat.min_eq_right (by omega : 1 ≤ i)]
            have hiq_r : i ≤ r := by simpa [hq_len] using hiq
            have hii : i = 1 := hq_getVert_inj hiq_r
              (by dsimp [r]; omega) (hend_eq_snd.trans hsnd)
            exact hi1 hii
          let cyc : G.Walk (q.getVert i) (q.getVert i) := qi.cons hadj.symm
          have hcyc : cyc.IsCycle := by
            dsimp [cyc]
            rw [SimpleGraph.Walk.cons_isCycle_iff]
            exact ⟨hqi_path, hedge_not⟩
          have hg_le : G.girth ≤ cyc.length := G.girth_le_length hcyc
          have hcyc_len : cyc.length = i + 1 := by
            simp [cyc, qi, hqi_len]
          have hshort : cyc.length < G.girth := by
            rw [hcyc_len]
            dsimp [r] at hiq
            omega
          omega
        let t : Finset α := G.neighborFinset v ∪ q.support.toFinset
        have ht_card : t.card = Fintype.card (G.neighborSet v) + r := by
          have h_inter :
              G.neighborFinset v ∩ q.support.toFinset = {q.getVert 1} := by
            ext x
            constructor
            · intro hx
              rw [Finset.mem_inter] at hx
              exact Finset.mem_singleton.mpr (hroot_neighbor_support x hx.2 hx.1)
            · intro hx
              rw [Finset.mem_singleton] at hx
              subst x
              rw [Finset.mem_inter]
              constructor
              · rw [G.mem_neighborFinset]
                have hr_pos : 0 < r := by dsimp [r]; omega
                have hadj01 : G.Adj (q.getVert 0) (q.getVert (0 + 1)) :=
                  q.adj_getVert_succ (by simpa [hq_len] using hr_pos)
                simpa [SimpleGraph.Walk.getVert_zero] using hadj01
              · rw [List.mem_toFinset]
                exact q.getVert_mem_support 1
          have hsupport_card : q.support.toFinset.card = r + 1 := by
            rw [List.toFinset_card_of_nodup hq_path.support_nodup, q.length_support, hq_len]
          have hneighbor_card :
              (G.neighborFinset v).card = Fintype.card (G.neighborSet v) := by
            rw [SimpleGraph.neighborFinset_def]
            exact Set.toFinset_card (G.neighborSet v)
          dsimp [t]
          rw [Finset.card_union, h_inter, hsupport_card, hneighbor_card]
          simp
        unfold largestInducedTreeSize
        apply le_csSup
        · exact ⟨Fintype.card α, by
            intro n hn
            rcases hn with ⟨s, rfl, _ht⟩
            exact Finset.card_le_univ s⟩
        · refine ⟨t, ?_, ?_⟩
          · rw [ht_card]
            omega
          · constructor
            have hv_t : v ∈ t := by
              dsimp [t]
              rw [Finset.mem_union]
              exact Or.inr (List.mem_toFinset.mpr q.start_mem_support)
            haveI : Nonempty (↥((t : Finset α) : Set α)) := ⟨⟨v, hv_t⟩⟩
            · refine ⟨fun x y ↦ ?_⟩
              let cv : (t : Set α) := ⟨v, hv_t⟩
              have hto_center :
                  ∀ z : (t : Set α), (G.induce (t : Set α)).Reachable z cv := by
                intro z
                have hzmem : z.1 ∈ t := z.2
                dsimp [t] at hzmem
                rw [Finset.mem_union] at hzmem
                rcases hzmem with hzN | hzq
                · have hadj : G.Adj z.1 v := ((G.mem_neighborFinset v z.1).mp hzN).symm
                  exact ⟨(show (G.induce (t : Set α)).Adj z cv from hadj).toWalk⟩
                · rw [List.mem_toFinset] at hzq
                  have hsub :
                      ∀ a, a ∈ (q.takeUntil z.1 hzq).support → a ∈ (t : Set α) := by
                    intro a ha
                    change a ∈ t
                    dsimp [t]
                    rw [Finset.mem_union]
                    exact Or.inr (List.mem_toFinset.mpr (q.support_takeUntil_subset hzq ha))
                  exact (show (G.induce (t : Set α)).Reachable cv z from
                    ⟨(q.takeUntil z.1 hzq).induce (t : Set α) hsub⟩).symm
              exact (hto_center x).trans (hto_center y).symm
            · have hcycle_short_of_support_q :
                  ∀ {u : (t : Set α)} (c : (G.induce (t : Set α)).Walk u u),
                    c.IsCycle → (∀ z ∈ c.support, z.1 ∈ q.support.toFinset) →
                    c.length < G.girth := by
                intro u c hc hcsupp
                let f := (Embedding.induce (G := G) ((t : Finset α) : Set α)).toHom
                have hcG : (c.map f).IsCycle :=
                  hc.map (Embedding.induce (G := G) ((t : Finset α) : Set α)).injective
                have hg_le : G.girth ≤ (c.map f).length := G.girth_le_length hcG
                rw [SimpleGraph.Walk.length_map] at hg_le
                have hc_def := (SimpleGraph.Walk.isCycle_def c).mp hc
                have htail_nodup : (c.support.tail.map Subtype.val).Nodup :=
                  List.Nodup.map Subtype.val_injective hc_def.2.2
                have htail_card :
                    (c.support.tail.map Subtype.val).toFinset.card =
                      (c.support.tail.map Subtype.val).length :=
                  List.toFinset_card_of_nodup htail_nodup
                have htail_subset :
                    (c.support.tail.map Subtype.val).toFinset ⊆ q.support.toFinset := by
                  intro x hx
                  rw [List.mem_toFinset] at hx
                  rcases List.mem_map.mp hx with ⟨z, hz, rfl⟩
                  exact hcsupp z (List.mem_of_mem_tail hz)
                have htail_len : (c.support.tail.map Subtype.val).length = c.length := by
                  rw [List.length_map, List.length_tail]
                  have hsupp_ne : c.support ≠ [] := SimpleGraph.Walk.support_ne_nil c
                  rw [SimpleGraph.Walk.length_support]
                  omega
                have hsupport_card : q.support.toFinset.card = r + 1 := by
                  rw [List.toFinset_card_of_nodup hq_path.support_nodup, q.length_support, hq_len]
                have hlen_le : c.length ≤ r + 1 := by
                  rw [← htail_len, ← htail_card]
                  exact (Finset.card_le_card htail_subset).trans_eq hsupport_card
                dsimp [r] at hlen_le
                omega
              have hneighbor_path_edge_center :
                  ∀ {z x : α}, z ∈ G.neighborFinset v → z ∉ q.support.toFinset →
                    x ∈ q.support.toFinset → G.Adj z x → x = v := by
                intro z x hzN hz_not_q hxq hzx
                rw [List.mem_toFinset] at hxq
                obtain ⟨i, hix, hiq⟩ := SimpleGraph.Walk.mem_support_iff_exists_getVert.mp hxq
                subst x
                by_cases hi0 : i = 0
                · simp [hi0]
                have hi_le_r : i ≤ r := by simpa [hq_len] using hiq
                have hqi_ne_v : q.getVert i ≠ v := by
                  intro hqiv
                  have hii : i = 0 := hq_getVert_inj hi_le_r (Nat.zero_le _) (by
                    simpa [SimpleGraph.Walk.getVert_zero] using hqiv)
                  exact hi0 hii
                let qi : G.Walk v (q.getVert i) := q.take i
                have hqi_path : qi.IsPath := by
                  rw [SimpleGraph.Walk.isPath_def]
                  rw [SimpleGraph.Walk.take_support_eq_support_take_succ]
                  exact hq_path.support_nodup.take
                have hqi_len : qi.length = i := by
                  change (q.take i).length = i
                  rw [SimpleGraph.Walk.take_length]
                  exact Nat.min_eq_left (by simpa [hq_len] using hiq)
                have hz_not_qi : z ∉ qi.support := by
                  intro hzqi
                  exact hz_not_q (List.mem_toFinset.mpr (by
                    rw [SimpleGraph.Walk.take_support_eq_support_take_succ] at hzqi
                    exact List.mem_of_mem_take hzqi))
                have hzv : G.Adj z v := ((G.mem_neighborFinset v z).mp hzN).symm
                let pz : G.Walk z (q.getVert i) := qi.cons hzv
                have hpz_path : pz.IsPath := by
                  dsimp [pz]
                  exact hqi_path.cons hz_not_qi
                have hedge_not : s(q.getVert i, z) ∉ pz.edges := by
                  intro he
                  have he' : s(z, q.getVert i) ∈ pz.edges := by
                    simpa [Sym2.eq_swap] using he
                  have hget : q.getVert i = pz.snd := hpz_path.eq_snd_of_mem_edges he'
                  have hsnd : pz.snd = v := by
                    dsimp [pz]
                    simp
                  exact hqi_ne_v (hget.trans hsnd)
                let cyc : G.Walk (q.getVert i) (q.getVert i) := pz.cons hzx.symm
                have hcyc : cyc.IsCycle := by
                  dsimp [cyc]
                  rw [SimpleGraph.Walk.cons_isCycle_iff]
                  exact ⟨hpz_path, hedge_not⟩
                have hg_le : G.girth ≤ cyc.length := G.girth_le_length hcyc
                have hcyc_len : cyc.length = i + 2 := by
                  simp [cyc, pz, qi, hqi_len]
                have hshort : cyc.length < G.girth := by
                  rw [hcyc_len]
                  dsimp [r] at hi_le_r
                  omega
                omega
              have hleaf_adj_center :
                  ∀ (z w : (t : Set α)), z.1 ∈ G.neighborFinset v →
                    z.1 ∉ q.support.toFinset →
                    (G.induce (t : Set α)).Adj z w → w.1 = v := by
                intro z w hzN hz_not_q hzw
                have hwmem : w.1 ∈ t := w.2
                dsimp [t] at hwmem
                rw [Finset.mem_union] at hwmem
                rcases hwmem with hwN | hwq
                · have hzSet : z.1 ∈ G.neighborSet v := (G.mem_neighborFinset v z.1).mp hzN
                  have hwSet : w.1 ∈ G.neighborSet v := (G.mem_neighborFinset v w.1).mp hwN
                  have hzne : z.1 ≠ w.1 := fun h => hzw.ne (Subtype.ext h)
                  exact False.elim ((hindep_neighbor_of_girth (by omega) v)
                    hzSet hwSet hzne hzw)
                · exact hneighbor_path_edge_center hzN hz_not_q hwq hzw
              intro u c hc
              by_cases hcsupp : ∀ z ∈ c.support, z.1 ∈ q.support.toFinset
              · have hshort := hcycle_short_of_support_q c hc hcsupp
                let f := (Embedding.induce (G := G) ((t : Finset α) : Set α)).toHom
                have hcG : (c.map f).IsCycle :=
                  hc.map (Embedding.induce (G := G) ((t : Finset α) : Set α)).injective
                have hg_le : G.girth ≤ (c.map f).length := G.girth_le_length hcG
                rw [SimpleGraph.Walk.length_map] at hg_le
                omega
              · push_neg at hcsupp
                obtain ⟨z, hzc, hz_not_q⟩ := hcsupp
                have hzmem : z.1 ∈ t := z.2
                dsimp [t] at hzmem
                rw [Finset.mem_union] at hzmem
                have hzN : z.1 ∈ G.neighborFinset v := by
                  rcases hzmem with hzN | hzq
                  · exact hzN
                  · exact False.elim (hz_not_q hzq)
                have no_cycle_at_leaf :
                    ∀ {u : (t : Set α)} (c : (G.induce (t : Set α)).Walk u u),
                      c.IsCycle → u.1 ∈ G.neighborFinset v →
                      u.1 ∉ q.support.toFinset → False := by
                  intro u c hc huN hu_not_q
                  have hsnd : c.snd.1 = v :=
                    hleaf_adj_center u c.snd huN hu_not_q (c.adj_snd hc.not_nil)
                  have hpen : c.penultimate.1 = v :=
                    hleaf_adj_center u c.penultimate huN hu_not_q
                      (c.adj_penultimate hc.not_nil).symm
                  exact hc.snd_ne_penultimate (Subtype.ext (hsnd.trans hpen.symm))
                exact no_cycle_at_leaf (c.rotate hzc) (hc.rotate hzc) hzN hz_not_q
      obtain ⟨v, _hv, hv⟩ := Finset.exists_mem_eq_sup (Finset.univ : Finset α)
        (Finset.univ_nonempty) (indepNeighborsCard G)
      rw [hv, hneighbor_eq_card v]
      exact hlarge_tree v

-- Sanity checks

/-- The `largestInducedTreeSize` invariant is a natural number (nonneg). -/
example (G : SimpleGraph (Fin 3)) : 0 ≤ largestInducedTreeSize G := Nat.zero_le _

end WrittenOnTheWallII.GraphConjecture141
