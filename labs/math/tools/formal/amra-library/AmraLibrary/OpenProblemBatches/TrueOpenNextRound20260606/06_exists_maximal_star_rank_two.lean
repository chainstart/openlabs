import Mathlib.Data.Finset.Card
import Mathlib.Data.Finset.Max
import Mathlib.Data.Finset.Union
import Mathlib.Data.Fintype.Basic

private lemma exists_pair_eq_with_mem_of_card_two {β : Type*} [DecidableEq β]
    {S : Finset β} (hS : S.card = 2) {x : β} (hx : x ∈ S) :
    ∃ y : β, x ≠ y ∧ S = {x, y} := by
  obtain ⟨u, v, huv, hSuv⟩ := Finset.card_eq_two.mp hS
  have hxuv : x = u ∨ x = v := by
    have : x ∈ ({u, v} : Finset β) := by simpa [hSuv] using hx
    simpa using this
  cases hxuv with
  | inl hxu =>
      refine ⟨v, ?_, ?_⟩
      · simpa [hxu] using huv
      · simpa [hxu] using hSuv
  | inr hxv =>
      refine ⟨u, ?_, ?_⟩
      · intro hxu
        exact huv (hxu.symm.trans hxv)
      · simpa [hxv, Finset.pair_comm] using hSuv

private lemma second_mem_of_pair_inter_nonempty {β : Type*} [DecidableEq β]
    {x y : β} {e f : Finset β}
    (he : e = {x, y}) (hcross : (e ∩ f).Nonempty) (hxf : x ∉ f) :
    y ∈ f := by
  obtain ⟨z, hz⟩ := hcross
  have hze : z ∈ e := (Finset.mem_inter.mp hz).1
  have hzf : z ∈ f := (Finset.mem_inter.mp hz).2
  have hzxy : z = x ∨ z = y := by
    have : z ∈ ({x, y} : Finset β) := by simpa [he] using hze
    simpa using this
  rcases hzxy with rfl | rfl
  · exact False.elim (hxf hzf)
  · exact hzf

lemma three_spokes_crossing_edge_contains_center
    {β : Type*} [DecidableEq β]
    {x : β} {e1 e2 e3 f : Finset β}
    (he1card : e1.card = 2) (he2card : e2.card = 2) (he3card : e3.card = 2)
    (hfcard : f.card = 2)
    (hx1 : x ∈ e1) (hx2 : x ∈ e2) (hx3 : x ∈ e3)
    (h12 : e1 ≠ e2) (h13 : e1 ≠ e3) (h23 : e2 ≠ e3)
    (hcross1 : (e1 ∩ f).Nonempty)
    (hcross2 : (e2 ∩ f).Nonempty)
    (hcross3 : (e3 ∩ f).Nonempty) :
    x ∈ f := by
  by_contra hxf
  obtain ⟨a1, _hxa1, he1⟩ := exists_pair_eq_with_mem_of_card_two he1card hx1
  obtain ⟨a2, _hxa2, he2⟩ := exists_pair_eq_with_mem_of_card_two he2card hx2
  obtain ⟨a3, _hxa3, he3⟩ := exists_pair_eq_with_mem_of_card_two he3card hx3
  have ha1f : a1 ∈ f := second_mem_of_pair_inter_nonempty he1 hcross1 hxf
  have ha2f : a2 ∈ f := second_mem_of_pair_inter_nonempty he2 hcross2 hxf
  have ha3f : a3 ∈ f := second_mem_of_pair_inter_nonempty he3 hcross3 hxf
  have ha12 : a1 ≠ a2 := by
    intro h
    apply h12
    rw [he1, he2, h]
  have ha13 : a1 ≠ a3 := by
    intro h
    apply h13
    rw [he1, he3, h]
  have ha23 : a2 ≠ a3 := by
    intro h
    apply h23
    rw [he2, he3, h]
  have hsubset : ({a1, a2, a3} : Finset β) ⊆ f := by
    intro y hy
    simp only [Finset.mem_insert, Finset.mem_singleton] at hy
    rcases hy with rfl | rfl | rfl
    · exact ha1f
    · exact ha2f
    · exact ha3f
  have hthree : ({a1, a2, a3} : Finset β).card = 3 := by
    have ha1_not : a1 ∉ ({a2, a3} : Finset β) := by
      intro ha1mem
      simp only [Finset.mem_insert, Finset.mem_singleton] at ha1mem
      rcases ha1mem with h | h
      · exact ha12 h
      · exact ha13 h
    have ha2_not : a2 ∉ ({a3} : Finset β) := by
      intro ha2mem
      simp only [Finset.mem_singleton] at ha2mem
      exact ha23 ha2mem
    rw [Finset.card_insert_of_notMem ha1_not, Finset.card_insert_of_notMem ha2_not]
    simp
  have hle : 3 ≤ f.card := by
    rw [← hthree]
    exact Finset.card_le_card hsubset
  have hle_two : 3 ≤ 2 := by simpa [hfcard] using hle
  exact (by decide : ¬ 3 ≤ 2) hle_two

private lemma pair_eq_of_mem_card_two' {β : Type*} [DecidableEq β]
    {S : Finset β} (hS : S.card = 2) {x y : β}
    (hx : x ∈ S) (hy : y ∈ S) (hxy : x ≠ y) : S = {x, y} := by
  obtain ⟨u, v, huv, rfl⟩ := Finset.card_eq_two.mp hS
  have hsub : ({x, y} : Finset β) ⊆ {u, v} := by
    intro z hz
    simp only [Finset.mem_insert, Finset.mem_singleton] at hz
    rcases hz with rfl | rfl
    · exact hx
    · exact hy
  have hcard_le : ({u, v} : Finset β).card ≤ ({x, y} : Finset β).card := by
    have huv_card : ({u, v} : Finset β).card = 2 := by simpa [huv]
    have hxy_card : ({x, y} : Finset β).card = 2 := by simpa [hxy]
    rw [huv_card, hxy_card]
  exact (Finset.eq_of_subset_of_card_le hsub hcard_le).symm

theorem rank_three_tau_three_trace_graph_degree_le_two
    {β : Type*} [DecidableEq β]
    (H : Fin 3 → Finset (Finset β)) (K : Fin 3 → Finset β)
    (hedge : ∀ i e, e ∈ H i → e.card = 2)
    (hcross :
      ∀ i j, i ≠ j →
        ∀ e ∈ H i, ∀ f ∈ H j, (e ∩ f).Nonempty)
    (hKcore : ∀ i x, x ∈ K i → ∀ e ∈ H i, x ∈ e)
    (hno_two :
      let V := fun i => (H i).biUnion fun e => e
      let used := Finset.univ.biUnion fun i : Fin 3 => V i ∪ K i
      ∀ i x, x ∈ used →
        ((K i).erase x).Nonempty ∨
          ∃ j, j ≠ i ∧ ∃ e ∈ H j, x ∉ e) :
    ∀ i x, ({e ∈ H i | x ∈ e}.card ≤ 2) := by
  classical
  intro i x
  by_contra hle
  let S : Finset (Finset β) := {e ∈ H i | x ∈ e}
  have hSlarge : 3 ≤ S.card := Nat.succ_le_of_lt (Nat.lt_of_not_ge hle)
  obtain ⟨T, hTS, hTcard⟩ := Finset.exists_subset_card_eq hSlarge
  obtain ⟨e1, e2, e3, h12, h13, h23, hT⟩ := Finset.card_eq_three.mp hTcard
  have he1S : e1 ∈ S := hTS (by simp [hT])
  have he2S : e2 ∈ S := hTS (by simp [hT])
  have he3S : e3 ∈ S := hTS (by simp [hT])
  have he1S' : e1 ∈ H i ∧ x ∈ e1 := by simpa [S] using he1S
  have he2S' : e2 ∈ H i ∧ x ∈ e2 := by simpa [S] using he2S
  have he3S' : e3 ∈ H i ∧ x ∈ e3 := by simpa [S] using he3S
  have he1H : e1 ∈ H i := he1S'.1
  have he2H : e2 ∈ H i := he2S'.1
  have he3H : e3 ∈ H i := he3S'.1
  have hx1 : x ∈ e1 := he1S'.2
  have hx2 : x ∈ e2 := he2S'.2
  have hx3 : x ∈ e3 := he3S'.2
  have hx_cross : ∀ j, j ≠ i → ∀ f ∈ H j, x ∈ f := by
    intro j hji f hf
    exact three_spokes_crossing_edge_contains_center
      (hedge i e1 he1H) (hedge i e2 he2H) (hedge i e3 he3H) (hedge j f hf)
      hx1 hx2 hx3 h12 h13 h23
      (hcross i j (fun hij => hji hij.symm) e1 he1H f hf)
      (hcross i j (fun hij => hji hij.symm) e2 he2H f hf)
      (hcross i j (fun hij => hji hij.symm) e3 he3H f hf)
  have hx_used :
      x ∈ (Finset.univ.biUnion fun r : Fin 3 =>
        ((H r).biUnion fun e => e) ∪ K r) := by
    apply Finset.mem_biUnion.mpr
    refine ⟨i, Finset.mem_univ i, ?_⟩
    apply Finset.mem_union.mpr
    left
    exact Finset.mem_biUnion.mpr ⟨e1, he1H, hx1⟩
  rcases hno_two i x hx_used with hK | hmissing
  · obtain ⟨y, hyerase⟩ := hK
    have hyK : y ∈ K i := (Finset.mem_erase.mp hyerase).2
    have hyx : y ≠ x := (Finset.mem_erase.mp hyerase).1
    have hy1 : y ∈ e1 := hKcore i y hyK e1 he1H
    have hy2 : y ∈ e2 := hKcore i y hyK e2 he2H
    have hy3 : y ∈ e3 := hKcore i y hyK e3 he3H
    have he1xy : e1 = {x, y} :=
      pair_eq_of_mem_card_two' (hedge i e1 he1H) hx1 hy1 hyx.symm
    have he2xy : e2 = {x, y} :=
      pair_eq_of_mem_card_two' (hedge i e2 he2H) hx2 hy2 hyx.symm
    have he3xy : e3 = {x, y} :=
      pair_eq_of_mem_card_two' (hedge i e3 he3H) hx3 hy3 hyx.symm
    exact h12 (he1xy.trans he2xy.symm)
  · obtain ⟨j, hji, f, hfH, hxf⟩ := hmissing
    exact hxf (hx_cross j hji f hfH)

theorem four_edge_degree_two_crossing_family_card_le_two
    {β : Type} [Fintype β] [DecidableEq β]
    (E J : Finset (Finset β))
    (hEcard : E.card = 4)
    (hEedge : ∀ e ∈ E, e.card = 2)
    (hJedge : ∀ f ∈ J, f.card = 2)
    (hEdeg : ∀ x, ({e ∈ E | x ∈ e}.card ≤ 2))
    (hcross : ∀ f ∈ J, ∀ e ∈ E, (f ∩ e).Nonempty) :
    J.card ≤ 2 := by
  classical
  by_cases hJempty : J = ∅
  · simp [hJempty]
  · have hJnonempty : J.Nonempty := Finset.nonempty_iff_ne_empty.mpr hJempty
    obtain ⟨f, hfJ⟩ := hJnonempty
    obtain ⟨a, b, hab, hf_pair⟩ := Finset.card_eq_two.mp (hJedge f hfJ)
    let Ea : Finset (Finset β) := {e ∈ E | a ∈ e}
    let Eb : Finset (Finset β) := {e ∈ E | b ∈ e}
    have hEeq : E = Ea ∪ Eb := by
      apply Finset.Subset.antisymm
      · intro e heE
        obtain ⟨x, hx⟩ := hcross f hfJ e heE
        have hxf : x ∈ f := (Finset.mem_inter.mp hx).1
        have hxe : x ∈ e := (Finset.mem_inter.mp hx).2
        have hxab : x = a ∨ x = b := by
          have : x ∈ ({a, b} : Finset β) := by simpa [hf_pair] using hxf
          simpa using this
        rcases hxab with rfl | rfl
        · exact Finset.mem_union_left _ (by simp [Ea, heE, hxe])
        · exact Finset.mem_union_right _ (by simp [Eb, heE, hxe])
      · intro e he
        simp only [Ea, Eb, Finset.mem_union, Finset.mem_filter] at he
        exact he.elim (fun h => h.1) (fun h => h.1)
    have hEa_le : Ea.card ≤ 2 := by simpa [Ea] using hEdeg a
    have hEb_le : Eb.card ≤ 2 := by simpa [Eb] using hEdeg b
    have hUnion_card : (Ea ∪ Eb).card = 4 := by simpa [← hEeq] using hEcard
    have hUnion_add_inter := Finset.card_union_add_card_inter Ea Eb
    have hEa_card : Ea.card = 2 := by
      omega
    have hEb_card : Eb.card = 2 := by
      omega
    have hInter_card : (Ea ∩ Eb).card = 0 := by
      omega
    have hInter_empty : Ea ∩ Eb = ∅ := Finset.card_eq_zero.mp hInter_card
    obtain ⟨e1, e2, he12, hEa_pair⟩ := Finset.card_eq_two.mp hEa_card
    obtain ⟨eb1, eb2, heb12, hEb_pair⟩ := Finset.card_eq_two.mp hEb_card
    have he1Ea : e1 ∈ Ea := by simp [hEa_pair]
    have he2Ea : e2 ∈ Ea := by simp [hEa_pair]
    have heb1Eb : eb1 ∈ Eb := by simp [hEb_pair]
    have heb2Eb : eb2 ∈ Eb := by simp [hEb_pair]
    have he1E : e1 ∈ E := by
      have h := he1Ea
      exact (by simpa [Ea] using h : e1 ∈ E ∧ a ∈ e1).1
    have he2E : e2 ∈ E := by
      have h := he2Ea
      exact (by simpa [Ea] using h : e2 ∈ E ∧ a ∈ e2).1
    have heb1E : eb1 ∈ E := by
      have h := heb1Eb
      exact (by simpa [Eb] using h : eb1 ∈ E ∧ b ∈ eb1).1
    have heb2E : eb2 ∈ E := by
      have h := heb2Eb
      exact (by simpa [Eb] using h : eb2 ∈ E ∧ b ∈ eb2).1
    have ha1 : a ∈ e1 := by
      have h := he1Ea
      exact (by simpa [Ea] using h : e1 ∈ E ∧ a ∈ e1).2
    have ha2 : a ∈ e2 := by
      have h := he2Ea
      exact (by simpa [Ea] using h : e2 ∈ E ∧ a ∈ e2).2
    have hb_eb1 : b ∈ eb1 := by
      have h := heb1Eb
      exact (by simpa [Eb] using h : eb1 ∈ E ∧ b ∈ eb1).2
    have hb_eb2 : b ∈ eb2 := by
      have h := heb2Eb
      exact (by simpa [Eb] using h : eb2 ∈ E ∧ b ∈ eb2).2
    have ha_not_eb1 : a ∉ eb1 := by
      intro ha
      have heb1Ea : eb1 ∈ Ea := by simpa [Ea, heb1E, ha]
      have : eb1 ∈ Ea ∩ Eb := by simp [heb1Ea, heb1Eb]
      simpa [hInter_empty] using this
    have ha_not_eb2 : a ∉ eb2 := by
      intro ha
      have heb2Ea : eb2 ∈ Ea := by simpa [Ea, heb2E, ha]
      have : eb2 ∈ Ea ∩ Eb := by simp [heb2Ea, heb2Eb]
      simpa [hInter_empty] using this
    obtain ⟨c, hac, he1_pair⟩ :=
      exists_pair_eq_with_mem_of_card_two (hEedge e1 he1E) ha1
    obtain ⟨d, _had, he2_pair⟩ :=
      exists_pair_eq_with_mem_of_card_two (hEedge e2 he2E) ha2
    have hcd : c ≠ d := by
      intro hcd
      apply he12
      rw [he1_pair, he2_pair, hcd]
    let opposite : Finset β := {c, d}
    have hJsub : J ⊆ ({f, opposite} : Finset (Finset β)) := by
      intro g hgJ
      by_cases hag : a ∈ g
      · have hbg : b ∈ g := by
          by_contra hb_not_g
          obtain ⟨t, hat, hg_pair⟩ :=
            exists_pair_eq_with_mem_of_card_two (hJedge g hgJ) hag
          have hbt : b ≠ t := by
            intro hbt
            apply hb_not_g
            rw [hg_pair]
            simp [hbt]
          have ht_eb1 : t ∈ eb1 := by
            obtain ⟨x, hx⟩ := hcross g hgJ eb1 heb1E
            have hxg : x ∈ g := (Finset.mem_inter.mp hx).1
            have hxeb1 : x ∈ eb1 := (Finset.mem_inter.mp hx).2
            have hxa : x = a ∨ x = t := by
              have : x ∈ ({a, t} : Finset β) := by simpa [hg_pair] using hxg
              simpa using this
            rcases hxa with rfl | rfl
            · exact False.elim (ha_not_eb1 hxeb1)
            · exact hxeb1
          have ht_eb2 : t ∈ eb2 := by
            obtain ⟨x, hx⟩ := hcross g hgJ eb2 heb2E
            have hxg : x ∈ g := (Finset.mem_inter.mp hx).1
            have hxeb2 : x ∈ eb2 := (Finset.mem_inter.mp hx).2
            have hxa : x = a ∨ x = t := by
              have : x ∈ ({a, t} : Finset β) := by simpa [hg_pair] using hxg
              simpa using this
            rcases hxa with rfl | rfl
            · exact False.elim (ha_not_eb2 hxeb2)
            · exact hxeb2
          have heb1_eq : eb1 = {b, t} :=
            pair_eq_of_mem_card_two' (hEedge eb1 heb1E) hb_eb1 ht_eb1 hbt
          have heb2_eq : eb2 = {b, t} :=
            pair_eq_of_mem_card_two' (hEedge eb2 heb2E) hb_eb2 ht_eb2 hbt
          exact False.elim (heb12 (heb1_eq.trans heb2_eq.symm))
        have hg_eq : g = f := by
          have : g = {a, b} :=
            pair_eq_of_mem_card_two' (hJedge g hgJ) hag hbg hab
          exact this.trans hf_pair.symm
        simp [hg_eq]
      · have hcg : c ∈ g := by
          obtain ⟨x, hx⟩ := hcross g hgJ e1 he1E
          have hxg : x ∈ g := (Finset.mem_inter.mp hx).1
          have hxe1 : x ∈ e1 := (Finset.mem_inter.mp hx).2
          have hxac : x = a ∨ x = c := by
            have : x ∈ ({a, c} : Finset β) := by simpa [he1_pair] using hxe1
            simpa using this
          rcases hxac with rfl | rfl
          · exact False.elim (hag hxg)
          · exact hxg
        have hdg : d ∈ g := by
          obtain ⟨x, hx⟩ := hcross g hgJ e2 he2E
          have hxg : x ∈ g := (Finset.mem_inter.mp hx).1
          have hxe2 : x ∈ e2 := (Finset.mem_inter.mp hx).2
          have hxad : x = a ∨ x = d := by
            have : x ∈ ({a, d} : Finset β) := by simpa [he2_pair] using hxe2
            simpa using this
          rcases hxad with rfl | rfl
          · exact False.elim (hag hxg)
          · exact hxg
        have hg_eq : g = opposite := by
          have : g = {c, d} :=
            pair_eq_of_mem_card_two' (hJedge g hgJ) hcg hdg hcd
          simpa [opposite] using this
        simp [hg_eq]
    have hcover_card : ({f, opposite} : Finset (Finset β)).card ≤ 2 := by
      by_cases hfo : f = opposite
      · simp [hfo]
      · have : ({f, opposite} : Finset (Finset β)).card = 2 := by simpa [hfo]
        exact this.le
    exact le_trans (Finset.card_le_card hJsub) hcover_card

namespace ChvatalLeanBatch20260527

open Classical

variable {α : Type} [Fintype α] [DecidableEq α] [Nonempty α]

def Intersecting (F : Finset (Finset α)) : Prop :=
  ∀ A ∈ F, ∀ B ∈ F, A ∩ B ≠ ∅

omit [Fintype α] [Nonempty α] in
private lemma pair_eq_of_mem_card_two {S : Finset α} (hS : S.card = 2) {x y : α}
    (hx : x ∈ S) (hy : y ∈ S) (hxy : x ≠ y) : S = {x, y} := by
  obtain ⟨u, v, huv, rfl⟩ := Finset.card_eq_two.mp hS
  have hsub : ({x, y} : Finset α) ⊆ {u, v} := by
    intro z hz
    simp only [Finset.mem_insert, Finset.mem_singleton] at hz
    rcases hz with rfl | rfl
    · exact hx
    · exact hy
  have hcard_le : ({u, v} : Finset α).card ≤ ({x, y} : Finset α).card := by
    have huv_card : ({u, v} : Finset α).card = 2 := by simpa [huv]
    have hxy_card : ({x, y} : Finset α).card = 2 := by simpa [hxy]
    rw [huv_card, hxy_card]
  exact (Finset.eq_of_subset_of_card_le hsub hcard_le).symm

omit [Fintype α] [Nonempty α] in
private lemma exists_pair_eq_with_mem {S : Finset α} (hS : S.card = 2) {x : α}
    (hx : x ∈ S) : ∃ y : α, x ≠ y ∧ S = {x, y} := by
  obtain ⟨u, v, huv, hSuv⟩ := Finset.card_eq_two.mp hS
  have hxuv : x = u ∨ x = v := by
    have : x ∈ ({u, v} : Finset α) := by simpa [hSuv] using hx
    simpa using this
  cases hxuv with
  | inl hxu =>
      refine ⟨v, ?_, ?_⟩
      · simpa [hxu] using huv
      · simpa [hxu] using hSuv
  | inr hxv =>
      refine ⟨u, ?_, ?_⟩
      · intro hxu
        exact huv (hxu.symm.trans hxv)
      · simpa [hxv, Finset.pair_comm] using hSuv

omit [Fintype α] [Nonempty α] in
private lemma mem_second_of_inter_pair_not_first {T S : Finset α} {a b : α}
    (hS : S = {a, b}) (hinter : T ∩ S ≠ ∅) (haT : a ∉ T) : b ∈ T := by
  have hnon : (T ∩ S).Nonempty := by
    simpa [Finset.nonempty_iff_ne_empty] using hinter
  obtain ⟨x, hx⟩ := hnon
  have hxT : x ∈ T := (Finset.mem_inter.mp hx).1
  have hxS : x ∈ S := (Finset.mem_inter.mp hx).2
  have hxab : x = a ∨ x = b := by
    have : x ∈ ({a, b} : Finset α) := by simpa [hS] using hxS
    simpa using this
  cases hxab with
  | inl hxa => exact False.elim (haT (by simpa [hxa] using hxT))
  | inr hxb => simpa [hxb] using hxT

omit [Fintype α] [Nonempty α] in
private lemma triangle_side_of_card_two_inter {V : Finset α} {a b c : α}
    (hab : a ≠ b) (hac : a ≠ c) (hbc : b ≠ c)
    (hV : V.card = 2)
    (hVab : V ∩ ({a, b} : Finset α) ≠ ∅)
    (hVac : V ∩ ({a, c} : Finset α) ≠ ∅)
    (hVbc : V ∩ ({b, c} : Finset α) ≠ ∅) :
    V = {a, b} ∨ V = {a, c} ∨ V = {b, c} := by
  have hnab : (V ∩ ({a, b} : Finset α)).Nonempty := by
    simpa [Finset.nonempty_iff_ne_empty] using hVab
  obtain ⟨p, hp⟩ := hnab
  have hpV : p ∈ V := (Finset.mem_inter.mp hp).1
  have hpab : p = a ∨ p = b := by
    have : p ∈ ({a, b} : Finset α) := (Finset.mem_inter.mp hp).2
    simpa using this
  cases hpab with
  | inl hpa =>
      have hnbc : (V ∩ ({b, c} : Finset α)).Nonempty := by
        simpa [Finset.nonempty_iff_ne_empty] using hVbc
      obtain ⟨q, hq⟩ := hnbc
      have hqV : q ∈ V := (Finset.mem_inter.mp hq).1
      have hqbc : q = b ∨ q = c := by
        have : q ∈ ({b, c} : Finset α) := (Finset.mem_inter.mp hq).2
        simpa using this
      cases hqbc with
      | inl hqb =>
          left
          exact pair_eq_of_mem_card_two hV (by simpa [hpa] using hpV)
            (by simpa [hqb] using hqV) hab
      | inr hqc =>
          right; left
          exact pair_eq_of_mem_card_two hV (by simpa [hpa] using hpV)
            (by simpa [hqc] using hqV) hac
  | inr hpb =>
      have hnac : (V ∩ ({a, c} : Finset α)).Nonempty := by
        simpa [Finset.nonempty_iff_ne_empty] using hVac
      obtain ⟨q, hq⟩ := hnac
      have hqV : q ∈ V := (Finset.mem_inter.mp hq).1
      have hqac : q = a ∨ q = c := by
        have : q ∈ ({a, c} : Finset α) := (Finset.mem_inter.mp hq).2
        simpa using this
      cases hqac with
      | inl hqa =>
          left
          exact pair_eq_of_mem_card_two hV (by simpa [hqa] using hqV)
            (by simpa [hpb] using hpV) hab
      | inr hqc =>
          right; right
          exact pair_eq_of_mem_card_two hV (by simpa [hpb] using hpV)
            (by simpa [hqc] using hqV) hbc

theorem pairwise_intersecting_two_sets_common_vertex_or_triangle
    (E : Finset (Finset α))
    (h2 : ∀ A ∈ E, A.card = 2)
    (hI : Intersecting E) :
    (∃ x : α, ∀ A ∈ E, x ∈ A) ∨
      ∃ a b c : α,
        a ≠ b ∧ b ≠ c ∧ a ≠ c ∧
        E = ({ {a, b}, {a, c}, {b, c} } : Finset (Finset α)) := by
  classical
  by_cases hstar : ∃ x : α, ∀ A ∈ E, x ∈ A
  · exact Or.inl hstar
  · right
    have hEne : E.Nonempty := by
      by_contra hempty
      apply hstar
      obtain ⟨x0⟩ := (inferInstance : Nonempty α)
      refine ⟨x0, ?_⟩
      intro A hAE
      exact False.elim (hempty ⟨A, hAE⟩)
    obtain ⟨S, hSE⟩ := hEne
    obtain ⟨a, b, hab, hS⟩ := Finset.card_eq_two.mp (h2 S hSE)
    have hnot_all_a : ¬ (∀ A ∈ E, a ∈ A) := by
      intro ha
      exact hstar ⟨a, ha⟩
    obtain ⟨T, hTE, haT⟩ : ∃ T ∈ E, a ∉ T := by
      by_contra h
      apply hnot_all_a
      intro A hAE
      by_contra haA
      exact h ⟨A, hAE, haA⟩
    have hbT : b ∈ T :=
      mem_second_of_inter_pair_not_first hS (hI T hTE S hSE) haT
    obtain ⟨c, hbc, hT⟩ := exists_pair_eq_with_mem (h2 T hTE) hbT
    have hac : a ≠ c := by
      intro hac_eq
      apply haT
      rw [hT]
      simp [hac_eq]
    have hnot_all_b : ¬ (∀ A ∈ E, b ∈ A) := by
      intro hb
      exact hstar ⟨b, hb⟩
    obtain ⟨U, hUE, hbU⟩ : ∃ U ∈ E, b ∉ U := by
      by_contra h
      apply hnot_all_b
      intro A hAE
      by_contra hbA
      exact h ⟨A, hAE, hbA⟩
    have hSba : S = {b, a} := by
      rw [hS, Finset.pair_comm]
    have haU : a ∈ U :=
      mem_second_of_inter_pair_not_first hSba (hI U hUE S hSE) hbU
    obtain ⟨d, _had, hUad⟩ := exists_pair_eq_with_mem (h2 U hUE) haU
    have hdc : d = c := by
      have hnon : (T ∩ U).Nonempty := by
        simpa [Finset.nonempty_iff_ne_empty] using hI T hTE U hUE
      obtain ⟨x, hx⟩ := hnon
      have hxT : x ∈ T := (Finset.mem_inter.mp hx).1
      have hxU : x ∈ U := (Finset.mem_inter.mp hx).2
      have hxbc : x = b ∨ x = c := by
        have : x ∈ ({b, c} : Finset α) := by simpa [hT] using hxT
        simpa using this
      have hxad : x = a ∨ x = d := by
        have : x ∈ ({a, d} : Finset α) := by simpa [hUad] using hxU
        simpa using this
      cases hxbc with
      | inl hxb => exact False.elim (hbU (by simpa [hxb] using hxU))
      | inr hxc =>
          cases hxad with
          | inl hxa => exact False.elim (haT (by simpa [hxa] using hxT))
          | inr hxd => exact hxd.symm.trans hxc
    have hU : U = {a, c} := by
      simpa [hdc] using hUad
    refine ⟨a, b, c, hab, hbc, hac, ?_⟩
    ext V
    constructor
    · intro hVE
      have hside : V = {a, b} ∨ V = {a, c} ∨ V = {b, c} :=
        triangle_side_of_card_two_inter hab hac hbc (h2 V hVE)
          (by simpa [← hS] using hI V hVE S hSE)
          (by simpa [← hU] using hI V hVE U hUE)
          (by simpa [← hT] using hI V hVE T hTE)
      rcases hside with hV | hV | hV
      · simp [hV]
      · simp [hV]
      · simp [hV]
    · intro hVtri
      simp only [Finset.mem_insert, Finset.mem_singleton] at hVtri
      rcases hVtri with hV | hV | hV
      · simpa [hV, ← hS] using hSE
      · simpa [hV, ← hU] using hUE
      · simpa [hV, ← hT] using hTE

end ChvatalLeanBatch20260527


namespace ChvatalRankTwoNextRound20260606

open Classical

variable {α : Type} [Fintype α] [DecidableEq α] [Nonempty α]

def Decreasing (F : Finset (Finset α)) : Prop :=
  ∀ A B : Finset α, B ⊆ A → A ∈ F → B ∈ F

def Intersecting (F : Finset (Finset α)) : Prop :=
  ∀ A ∈ F, ∀ B ∈ F, A ∩ B ≠ ∅

theorem rank_two_intersecting_no_common_vertex_all_card_two
    (F G : Finset (Finset α)) (hGF : G ⊆ F)
    (hI : Intersecting G)
    (hrank : ∀ A ∈ F, A.card ≤ 2)
    (hno_common : ¬ ∃ x : α, ∀ A ∈ G, x ∈ A) :
    ∀ A ∈ G, A.card = 2 := by
  intro A hA
  have hle : A.card ≤ 2 := hrank A (hGF hA)
  have hcard_ne_zero : A.card ≠ 0 := by
    intro h0
    have hAempty : A = ∅ := Finset.card_eq_zero.mp h0
    exact hI A hA A hA (by simp [hAempty])
  have hcard_ne_one : A.card ≠ 1 := by
    intro h1
    obtain ⟨x, hAeq⟩ := Finset.card_eq_one.mp h1
    apply hno_common
    refine ⟨x, ?_⟩
    intro B hB
    have hBA : (B ∩ A).Nonempty := by
      simpa [Finset.nonempty_iff_ne_empty] using hI B hB A hA
    obtain ⟨y, hyBA⟩ := hBA
    have hyB : y ∈ B := (Finset.mem_inter.mp hyBA).1
    have hyA : y ∈ A := (Finset.mem_inter.mp hyBA).2
    have hyx : y = x := by
      have : y ∈ ({x} : Finset α) := by
        simpa [hAeq] using hyA
      simpa using this
    simpa [hyx] using hyB
  cases hcard : A.card with
  | zero =>
      exact False.elim (hcard_ne_zero hcard)
  | succ n =>
      cases n with
      | zero =>
          exact False.elim (hcard_ne_one hcard)
      | succ m =>
          cases m with
          | zero =>
              simpa [hcard]
          | succ k =>
              have hthree_le : 3 ≤ A.card := by
                rw [hcard]
                simp
              have hle_two : 3 ≤ 2 := le_trans hthree_le hle
              exact False.elim ((by decide : ¬ 3 ≤ 2) hle_two)

theorem exists_star_maximizer
    (F : Finset (Finset α)) :
    ∃ x : α, ∀ y : α,
      ({A ∈ F | y ∈ A}.card ≤ {A ∈ F | x ∈ A}.card) := by
  classical
  have huniv : (Finset.univ : Finset α).Nonempty := by
    obtain ⟨x0⟩ := (inferInstance : Nonempty α)
    exact ⟨x0, Finset.mem_univ x0⟩
  obtain ⟨x, _hxuniv, hxmax⟩ :=
    Finset.exists_max_image (Finset.univ : Finset α)
      (fun y : α => ({A ∈ F | y ∈ A}.card)) huniv
  refine ⟨x, ?_⟩
  intro y
  exact hxmax y (Finset.mem_univ y)

theorem triangle_star_three_of_decreasing
    (F : Finset (Finset α)) (hdec : Decreasing F)
    {a b c : α} (hab : a ≠ b) (hac : a ≠ c) (hbc : b ≠ c)
    (habF : ({a, b} : Finset α) ∈ F)
    (hacF : ({a, c} : Finset α) ∈ F) :
    3 ≤ ({A ∈ F | a ∈ A}).card := by
  classical
  have haF : ({a} : Finset α) ∈ F := by
    exact hdec ({a, b} : Finset α) ({a} : Finset α) (by simp) habF
  have hsub :
      ({{a}, {a, b}, {a, c}} : Finset (Finset α)) ⊆ {A ∈ F | a ∈ A} := by
    intro S hS
    simp only [Finset.mem_insert, Finset.mem_singleton] at hS
    rcases hS with hS | hS | hS
    · subst S
      simp [haF]
    · subst S
      simp [habF]
    · subst S
      simp [hacF]
  have hcard : ({{a}, {a, b}, {a, c}} : Finset (Finset α)).card = 3 := by
    have h_a_ab : ({a} : Finset α) ≠ {a, b} := by
      intro h
      have hb : b ∈ ({a} : Finset α) := by
        rw [h]
        simp
      simp only [Finset.mem_singleton] at hb
      exact hab hb.symm
    have h_a_ac : ({a} : Finset α) ≠ {a, c} := by
      intro h
      have hc : c ∈ ({a} : Finset α) := by
        rw [h]
        simp
      simp only [Finset.mem_singleton] at hc
      exact hac hc.symm
    have h_ab_ac : ({a, b} : Finset α) ≠ {a, c} := by
      intro h
      have hc : c ∈ ({a, b} : Finset α) := by
        rw [h]
        simp
      simp only [Finset.mem_insert, Finset.mem_singleton] at hc
      rcases hc with hca | hcb
      · exact hac hca.symm
      · exact hbc hcb.symm
    have h_not_a : ({a} : Finset α) ∉ ({ {a, b}, {a, c} } : Finset (Finset α)) := by
      intro hm
      simp only [Finset.mem_insert, Finset.mem_singleton] at hm
      rcases hm with hm | hm
      · exact h_a_ab hm
      · exact h_a_ac hm
    have h_not_ab : ({a, b} : Finset α) ∉ ({ {a, c} } : Finset (Finset α)) := by
      intro hm
      exact h_ab_ac (by simpa using hm)
    rw [Finset.card_insert_of_notMem h_not_a, Finset.card_insert_of_notMem h_not_ab]
    simp
  simpa [hcard] using Finset.card_le_card hsub

theorem rank_two_intersecting_no_common_vertex_triangle
    (F G : Finset (Finset α)) (hGF : G ⊆ F)
    (hI : Intersecting G)
    (hrank : ∀ A ∈ F, A.card ≤ 2)
    (hno_common : ¬ ∃ x : α, ∀ A ∈ G, x ∈ A) :
    ∃ a b c : α,
      a ≠ b ∧ b ≠ c ∧ a ≠ c ∧
      G = ({ {a, b}, {a, c}, {b, c} } : Finset (Finset α)) := by
  have h2 : ∀ A ∈ G, A.card = 2 :=
    rank_two_intersecting_no_common_vertex_all_card_two F G hGF hI hrank hno_common
  have hI' : ChvatalLeanBatch20260527.Intersecting G := by
    intro A hA B hB
    exact hI A hA B hB
  rcases ChvatalLeanBatch20260527.pairwise_intersecting_two_sets_common_vertex_or_triangle
      G h2 hI' with hcommon | htri
  · exact False.elim (hno_common hcommon)
  · exact htri

theorem triangle_edge_family_card
    {a b c : α} (hab : a ≠ b) (hac : a ≠ c) (hbc : b ≠ c) :
    ({ {a, b}, {a, c}, {b, c} } : Finset (Finset α)).card = 3 := by
  have h_ab_ac : ({a, b} : Finset α) ≠ {a, c} := by
    intro h
    have hc : c ∈ ({a, b} : Finset α) := by
      rw [h]
      simp
    simp only [Finset.mem_insert, Finset.mem_singleton] at hc
    rcases hc with hca | hcb
    · exact hac hca.symm
    · exact hbc hcb.symm
  have h_ab_bc : ({a, b} : Finset α) ≠ {b, c} := by
    intro h
    have hc : c ∈ ({a, b} : Finset α) := by
      rw [h]
      simp
    simp only [Finset.mem_insert, Finset.mem_singleton] at hc
    rcases hc with hca | hcb
    · exact hac hca.symm
    · exact hbc hcb.symm
  have h_ac_bc : ({a, c} : Finset α) ≠ {b, c} := by
    intro h
    have hb : b ∈ ({a, c} : Finset α) := by
      rw [h]
      simp
    simp only [Finset.mem_insert, Finset.mem_singleton] at hb
    rcases hb with hba | hbc_eq
    · exact hab hba.symm
    · exact hbc hbc_eq
  have h_not_ab : ({a, b} : Finset α) ∉ ({ {a, c}, {b, c} } : Finset (Finset α)) := by
    intro hm
    simp only [Finset.mem_insert, Finset.mem_singleton] at hm
    rcases hm with hm | hm
    · exact h_ab_ac hm
    · exact h_ab_bc hm
  have h_not_ac : ({a, c} : Finset α) ∉ ({ {b, c} } : Finset (Finset α)) := by
    intro hm
    exact h_ac_bc (by simpa using hm)
  rw [Finset.card_insert_of_notMem h_not_ab, Finset.card_insert_of_notMem h_not_ac]
  simp

theorem exists_maximal_star_rank_two
    (F : Finset (Finset α)) (hdec : Decreasing F)
    (hrank : ∀ A ∈ F, A.card ≤ 2) :
    ∃ x : α, ∀ G, G ⊆ F → Intersecting G →
      G.card ≤ { A ∈ F | x ∈ A }.card := by
  classical
  obtain ⟨x, hxmax⟩ := exists_star_maximizer F
  refine ⟨x, ?_⟩
  intro G hGF hI
  by_cases hcommon : ∃ y : α, ∀ A ∈ G, y ∈ A
  · obtain ⟨y, hy⟩ := hcommon
    have hG_le_y : G.card ≤ {A ∈ F | y ∈ A}.card := by
      apply Finset.card_le_card
      intro A hA
      simp [hGF hA, hy A hA]
    exact le_trans hG_le_y (hxmax y)
  · obtain ⟨a, b, c, hab, hbc, hac, hGtri⟩ :=
      rank_two_intersecting_no_common_vertex_triangle F G hGF hI hrank hcommon
    have habF : ({a, b} : Finset α) ∈ F := by
      apply hGF
      rw [hGtri]
      simp
    have hacF : ({a, c} : Finset α) ∈ F := by
      apply hGF
      rw [hGtri]
      simp
    have hstar_a : 3 ≤ {A ∈ F | a ∈ A}.card :=
      triangle_star_three_of_decreasing F hdec hab hac hbc habF hacF
    have hGcard : G.card = 3 := by
      rw [hGtri]
      exact triangle_edge_family_card hab hac hbc
    have hG_le_a : G.card ≤ {A ∈ F | a ∈ A}.card := by
      rw [hGcard]
      exact hstar_a
    exact le_trans hG_le_a (hxmax a)

theorem exists_maximal_star_rank_two_original_quantifier_shape :
    ∀ F : Finset (Finset α), Decreasing F →
      (∀ A ∈ F, A.card ≤ 2) →
        ∃ x : α, ∀ G, G ⊆ F → Intersecting G →
          G.card ≤ { A ∈ F | x ∈ A }.card := by
  intro F hdec hrank
  exact exists_maximal_star_rank_two F hdec hrank

end ChvatalRankTwoNextRound20260606
