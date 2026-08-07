import AmraLibrary.Combinatorics.SimpleGraph.GraphConjectures.WowiiConjecture13
import Mathlib.Algebra.Order.Floor.Ring
import Mathlib.Data.Real.Archimedean
import Mathlib.Tactic.IntervalCases
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SuppressCompilation

set_option Elab.async false

suppress_compilation

namespace SimpleGraph

open Classical

variable {α : Type*} [Fintype α] [DecidableEq α]

theorem not_adj_neighbor_geodesic_vertex_of_index_ge_three
    {G : SimpleGraph α} {x y a : α} (p : G.Walk x y)
    (hp : p.length = G.dist x y) {i : ℕ}
    (hi3 : 3 ≤ i) (hi : i ≤ p.length)
    (hxa : G.Adj x a) :
    ¬ G.Adj a (p.getVert i) := by
  intro hap
  have hdist_eq : G.dist x (p.getVert i) = i := by
    have hdist_zero :
        G.dist (p.getVert 0) (p.getVert i) = i - 0 :=
      geodesic_getVert_dist_eq_index_sub (G := G) p hp (Nat.zero_le i) hi
    simpa [SimpleGraph.Walk.getVert_zero] using hdist_zero
  let q : G.Walk x (p.getVert i) := hxa.toWalk.append hap.toWalk
  have hdist_le_two : G.dist x (p.getVert i) ≤ 2 := by
    simpa [q] using SimpleGraph.dist_le q
  omega

end SimpleGraph

namespace SimpleGraph

open Classical

variable {α : Type*}

noncomputable def vertexEccentricityNat [Fintype α] [Nonempty α]
    (G : SimpleGraph α) (v : α) : ℕ :=
  (Finset.univ.image fun w : α => G.dist v w).max' (by simp)

noncomputable def averageVertexEccentricity [Fintype α] [Nonempty α]
    (G : SimpleGraph α) : ℝ :=
  (∑ v : α, (vertexEccentricityNat G v : ℝ)) / (Fintype.card α : ℝ)

theorem vertexEccentricityNat_le_diam
    [Fintype α] [Nonempty α] {G : SimpleGraph α} (hG : G.Connected) (v : α) :
    vertexEccentricityNat G v ≤ G.diam := by
  classical
  unfold vertexEccentricityNat
  refine Finset.max'_le
    (s := Finset.univ.image fun w : α => G.dist v w) (H := by simp) (x := G.diam) ?_
  intro n hn
  rcases Finset.mem_image.mp hn with ⟨w, _hw, rfl⟩
  exact G.dist_le_diam (SimpleGraph.connected_iff_ediam_ne_top.mp hG)

theorem averageVertexEccentricity_le_diam
    [Fintype α] [Nonempty α] {G : SimpleGraph α} (hG : G.Connected) :
    averageVertexEccentricity G ≤ (G.diam : ℝ) := by
  classical
  unfold averageVertexEccentricity
  have hsum :
      (∑ v : α, (vertexEccentricityNat G v : ℝ))
        ≤ ∑ _v : α, (G.diam : ℝ) := by
    exact Finset.sum_le_sum fun v _hv => by
      exact_mod_cast vertexEccentricityNat_le_diam (G := G) hG v
  have hcard_pos : 0 < (Fintype.card α : ℝ) := by
    exact_mod_cast Fintype.card_pos
  rw [Finset.sum_const, Finset.card_univ, nsmul_eq_mul] at hsum
  rw [div_le_iff₀ hcard_pos]
  nlinarith [hsum]

theorem vertexEccentricityNat_eq_diam_of_average_eq_diam
    [Fintype α] [Nonempty α] {G : SimpleGraph α} (hG : G.Connected)
    (havg : averageVertexEccentricity G = (G.diam : ℝ)) :
    ∀ v : α, vertexEccentricityNat G v = G.diam := by
  classical
  have hcard_pos : 0 < (Fintype.card α : ℝ) := by
    exact_mod_cast Fintype.card_pos
  have hsum_eq :
      (∑ v : α, (vertexEccentricityNat G v : ℝ))
        = (Fintype.card α : ℝ) * (G.diam : ℝ) := by
    unfold averageVertexEccentricity at havg
    rw [div_eq_iff hcard_pos.ne'] at havg
    nlinarith
  have hdef_sum_zero :
      ∑ v : α, ((G.diam : ℝ) - (vertexEccentricityNat G v : ℝ)) = 0 := by
    rw [Finset.sum_sub_distrib, Finset.sum_const, Finset.card_univ, nsmul_eq_mul]
    nlinarith
  have hdef_each :
      ∀ v : α, (G.diam : ℝ) - (vertexEccentricityNat G v : ℝ) = 0 := by
    simpa using
      (Finset.sum_eq_zero_iff_of_nonneg
        (s := Finset.univ)
        (f := fun v : α => (G.diam : ℝ) - (vertexEccentricityNat G v : ℝ))
        (by
          intro v _hv
          exact sub_nonneg.mpr (by
            exact_mod_cast vertexEccentricityNat_le_diam (G := G) hG v))).mp hdef_sum_zero
  intro v
  have hvzero := hdef_each v
  exact_mod_cast (sub_eq_zero.mp hvzero).symm

theorem exists_dist_eq_diam_from_vertexEccentricityNat_eq_diam
    [Fintype α] [Nonempty α] {G : SimpleGraph α} {v : α}
    (hv : vertexEccentricityNat G v = G.diam) :
    ∃ y : α, G.dist v y = G.diam := by
  classical
  unfold vertexEccentricityNat at hv
  have hmem :
      (Finset.univ.image fun w : α => G.dist v w).max' (by simp)
        ∈ Finset.univ.image fun w : α => G.dist v w :=
    Finset.max'_mem _ _
  rw [hv] at hmem
  rcases Finset.mem_image.mp hmem with ⟨y, _hy, hy⟩
  exact ⟨y, hy⟩

theorem maxIndepNeighborsCard_exists_vertex
    [Fintype α] [Nonempty α] (G : SimpleGraph α) :
    ∃ v : α, indepNeighborsCard G v = maxIndepNeighborsCard G := by
  classical
  unfold maxIndepNeighborsCard
  have hmem :
      (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
        ∈ Finset.univ.image (fun v => indepNeighborsCard G v) :=
    Finset.max'_mem _ _
  rcases Finset.mem_image.mp hmem with ⟨v, _hv, hv⟩
  exact ⟨v, hv⟩

theorem floor_lt_nat_add_cast_le_sub_one
    {x : ℝ} {m n : ℕ} (h : x < (m : ℝ)) :
    ((⌊x + (n : ℝ)⌋ : ℤ) : ℝ) ≤ (m : ℝ) + (n : ℝ) - 1 := by
  have hlt : x + (n : ℝ) < ((m + n : ℕ) : ℤ) := by
    norm_num [Nat.cast_add]
    linarith
  have hfloor :
      ⌊x + (n : ℝ)⌋ ≤ ((m + n : ℕ) : ℤ) - 1 := by
    rw [Int.floor_le_sub_one_iff]
    simpa using hlt
  exact_mod_cast hfloor

end SimpleGraph


namespace SimpleGraph

open Classical

variable {α : Type*} [Fintype α] [DecidableEq α] [Nonempty α]

theorem path_vertices_erase_one_card_eq_length
    {G : SimpleGraph α} {u w : α} (p : G.Walk u w)
    (hpPath : p.IsPath) (hpLen : 1 ≤ p.length) :
    (((Finset.range (p.length + 1)).erase 1).image fun i => p.getVert i).card =
      p.length := by
  have hIle :
      ∀ i ∈ (Finset.range (p.length + 1)).erase 1, i ≤ p.length := by
    intro i hi
    exact Nat.lt_succ_iff.mp (Finset.mem_range.mp (Finset.mem_erase.mp hi).2)
  rw [path_index_image_card_eq (G := G) p hpPath _ hIle]
  have hmem : 1 ∈ Finset.range (p.length + 1) := by
    rw [Finset.mem_range]
    omega
  rw [Finset.card_erase_of_mem hmem, Finset.card_range]
  omega

theorem diam_geodesic_neighbor_path_witness_disjoint
    {G : SimpleGraph α} {v y : α} (p : G.Walk v y)
    (hpDist : p.length = G.dist v y)
    (A : Finset α)
    (hAadj : ∀ a ∈ A, G.Adj v a) :
    Disjoint A
      (((Finset.range (p.length + 1)).erase 1).image fun i => p.getVert i) := by
  rw [Finset.disjoint_left]
  intro a ha hP
  rcases Finset.mem_image.mp hP with ⟨i, hiErase, hia⟩
  have hi_ne_one : i ≠ 1 := (Finset.mem_erase.mp hiErase).1
  have hi_le : i ≤ p.length := by
    exact Nat.lt_succ_iff.mp (Finset.mem_range.mp (Finset.mem_erase.mp hiErase).2)
  by_cases hi0 : i = 0
  · subst i
    have ha_eq_v : a = v := by
      simpa [SimpleGraph.Walk.getVert_zero] using hia.symm
    exact G.irrefl (v := v) (by
      simpa [ha_eq_v] using hAadj a ha)
  · have hi_pos : 0 < i := Nat.pos_of_ne_zero hi0
    have hadj : G.Adj (p.getVert 0) (p.getVert i) := by
      simpa [SimpleGraph.Walk.getVert_zero, hia.symm] using hAadj a ha
    have hsub :
        i - 0 = 1 :=
      geodesic_getVert_adj_index_sub_eq_one (G := G) p hpDist hi_pos hi_le hadj
    omega

theorem diam_geodesic_neighbor_path_witness_card
    {G : SimpleGraph α} {v y : α} (p : G.Walk v y)
    (hpPath : p.IsPath)
    (hpDist : p.length = G.dist v y)
    (hpLen : 1 ≤ p.length)
    (A : Finset α)
    (hAadj : ∀ a ∈ A, G.Adj v a) :
    (A ∪ (((Finset.range (p.length + 1)).erase 1).image fun i => p.getVert i)).card =
      A.card + p.length := by
  rw [Finset.card_union_of_disjoint
    (diam_geodesic_neighbor_path_witness_disjoint (G := G) p hpDist A hAadj)]
  rw [path_vertices_erase_one_card_eq_length (G := G) p hpPath hpLen]

theorem diam_geodesic_neighbor_path_witness_bipartite
    {G : SimpleGraph α} {v y : α} (p : G.Walk v y)
    (hpDist : p.length = G.dist v y)
    (A : Finset α)
    (hAadj : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set α)) :
    (G.induce
      ((A ∪ (((Finset.range (p.length + 1)).erase 1).image fun i => p.getVert i)) :
        Set α)).IsBipartite := by
  classical
  let E := (Finset.range (p.length + 1)).erase 1
  let P := E.image fun i => p.getVert i
  let P0 := (E.filter fun i => i % 2 = 0).image fun i => p.getVert i
  let P1 := (E.filter fun i => i % 2 = 1).image fun i => p.getVert i
  suffices (G.induce (((A ∪ P) : Finset α) : Set α)).IsBipartite by
    rw [Finset.coe_union] at this
    simpa [P, E] using this
  have hElen : ∀ i ∈ E, i ≤ p.length := by
    intro i hi
    exact Nat.lt_succ_iff.mp (Finset.mem_range.mp (Finset.mem_erase.mp hi).2)
  have hP0ind : G.IsIndepSet (P0 : Set α) := by
    simpa [P0] using
      geodesic_same_parity_path_vertices_indepSet (G := G) p hpDist E hElen 0
  have hP1ind : G.IsIndepSet (P1 : Set α) := by
    simpa [P1] using
      geodesic_same_parity_path_vertices_indepSet (G := G) p hpDist E hElen 1
  have hNoAdjAP1 : ∀ a ∈ A, ∀ z ∈ P1, ¬ G.Adj a z := by
    intro a ha z hz haz
    change z ∈ ((E.filter fun i => i % 2 = 1).image fun i => p.getVert i) at hz
    rw [Finset.mem_image] at hz
    rcases hz with ⟨i, hi, hiz⟩
    have hiE : i ∈ E := (Finset.mem_filter.mp hi).1
    have hiParity : i % 2 = 1 := (Finset.mem_filter.mp hi).2
    have hi_ne_one : i ≠ 1 := (Finset.mem_erase.mp hiE).1
    have hi_le : i ≤ p.length := hElen i hiE
    have hi3 : 3 ≤ i := by
      by_contra hlt
      have hi_le_two : i ≤ 2 := Nat.lt_succ_iff.mp (Nat.lt_of_not_ge hlt)
      interval_cases i
      · simp at hiParity
      · exact hi_ne_one rfl
      · simp at hiParity
    exact not_adj_neighbor_geodesic_vertex_of_index_ge_three
      (G := G) p hpDist hi3 hi_le (hAadj a ha) (by simpa [hiz] using haz)
  have hLind : G.IsIndepSet ((A ∪ P1 : Finset α) : Set α) := by
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
  have hP1P0disj : Disjoint P1 P0 := by
    rw [Finset.disjoint_left]
    intro z hz1 hz0
    change z ∈ ((E.filter fun i => i % 2 = 1).image fun i => p.getVert i) at hz1
    change z ∈ ((E.filter fun i => i % 2 = 0).image fun i => p.getVert i) at hz0
    rw [Finset.mem_image] at hz1 hz0
    rcases hz1 with ⟨i, hi, hiz⟩
    rcases hz0 with ⟨j, hj, hjz⟩
    have hiE : i ∈ E := (Finset.mem_filter.mp hi).1
    have hjE : j ∈ E := (Finset.mem_filter.mp hj).1
    have hiParity : i % 2 = 1 := (Finset.mem_filter.mp hi).2
    have hjParity : j % 2 = 0 := (Finset.mem_filter.mp hj).2
    have hi_le : i ≤ p.length := hElen i hiE
    have hj_le : j ≤ p.length := hElen j hjE
    have hdi : G.dist v z = i := by
      have hdist :
          G.dist (p.getVert 0) (p.getVert i) = i - 0 :=
        geodesic_getVert_dist_eq_index_sub (G := G) p hpDist (Nat.zero_le i) hi_le
      simpa [SimpleGraph.Walk.getVert_zero, hiz] using hdist
    have hdj : G.dist v z = j := by
      have hdist :
          G.dist (p.getVert 0) (p.getVert j) = j - 0 :=
        geodesic_getVert_dist_eq_index_sub (G := G) p hpDist (Nat.zero_le j) hj_le
      simpa [SimpleGraph.Walk.getVert_zero, hjz] using hdist
    have hij : i = j := hdi.symm.trans hdj
    rw [hij, hjParity] at hiParity
    norm_num at hiParity
  have hAP0disj : Disjoint A P0 := by
    rw [Finset.disjoint_left]
    intro a ha haP0
    have haP : a ∈ P := by
      change a ∈ ((E.filter fun i => i % 2 = 0).image fun i => p.getVert i) at haP0
      rw [Finset.mem_image] at haP0
      rcases haP0 with ⟨i, hi, hia⟩
      exact Finset.mem_image.mpr ⟨i, (Finset.mem_filter.mp hi).1, hia⟩
    exact Finset.disjoint_left.mp
      (diam_geodesic_neighbor_path_witness_disjoint (G := G) p hpDist A hAadj) ha haP
  have hdisj : Disjoint (A ∪ P1) P0 := by
    rw [Finset.disjoint_left]
    intro z hz hz0
    rw [Finset.mem_union] at hz
    rcases hz with hzA | hzP1
    · exact Finset.disjoint_left.mp hAP0disj hzA hz0
    · exact Finset.disjoint_left.mp hP1P0disj hzP1 hz0
  have hBip :
      (G.induce (((A ∪ P1) ∪ P0 : Finset α) : Set α)).IsBipartite :=
    induce_union_indep_isBipartite (G := G) hLind hP0ind hdisj
  have hS : A ∪ P = (A ∪ P1) ∪ P0 := by
    ext z
    constructor
    · intro hz
      change z ∈ A ∪ P at hz
      rw [Finset.mem_union] at hz
      rcases hz with hzA | hzP
      · rw [Finset.mem_union, Finset.mem_union]
        exact Or.inl (Or.inl hzA)
      · change z ∈ (E.image fun i => p.getVert i) at hzP
        rw [Finset.mem_image] at hzP
        rcases hzP with ⟨i, hiE, hiz⟩
        have hpar : i % 2 = 0 ∨ i % 2 = 1 := Nat.mod_two_eq_zero_or_one i
        rcases hpar with hpar | hpar
        · rw [Finset.mem_union]
          exact Or.inr (Finset.mem_image.mpr
            ⟨i, Finset.mem_filter.mpr ⟨hiE, hpar⟩, hiz⟩)
        · rw [Finset.mem_union, Finset.mem_union]
          exact Or.inl (Or.inr (Finset.mem_image.mpr
            ⟨i, Finset.mem_filter.mpr ⟨hiE, hpar⟩, hiz⟩))
    · intro hz
      rw [Finset.mem_union] at hz
      rcases hz with hzL | hzP0
      · rw [Finset.mem_union] at hzL
        rcases hzL with hzA | hzP1
        · change z ∈ A ∪ P
          rw [Finset.mem_union]
          exact Or.inl hzA
        · change z ∈ A ∪ P
          rw [Finset.mem_union]
          right
          change z ∈ ((E.filter fun i => i % 2 = 1).image fun i => p.getVert i) at hzP1
          rw [Finset.mem_image] at hzP1
          rcases hzP1 with ⟨i, hi, hiz⟩
          exact Finset.mem_image.mpr ⟨i, (Finset.mem_filter.mp hi).1, hiz⟩
      · change z ∈ A ∪ P
        rw [Finset.mem_union]
        right
        change z ∈ ((E.filter fun i => i % 2 = 0).image fun i => p.getVert i) at hzP0
        rw [Finset.mem_image] at hzP0
        rcases hzP0 with ⟨i, hi, hiz⟩
        exact Finset.mem_image.mpr ⟨i, (Finset.mem_filter.mp hi).1, hiz⟩
  rw [hS]
  exact hBip

theorem exists_diam_add_indepNeighborsCard_bipartite_witness_of_diam_geodesic_from
    {G : SimpleGraph α} (hG : G.Connected) {v y : α} (p : G.Walk v y)
    (hpPath : p.IsPath)
    (hpDist : p.length = G.dist v y)
    (hpDiam : p.length = G.diam) :
    ∃ s : Finset α,
      (G.induce (s : Set α)).IsBipartite ∧
        (G.diam : ℝ) + (indepNeighborsCard G v : ℝ) ≤ (s.card : ℝ) := by
  classical
  by_cases hpLen : 1 ≤ p.length
  · obtain ⟨A, hAcard, hAadj, hAind⟩ :=
      exists_indepNeighborsCard_neighbor_indepSet (G := G) v
    let S := A ∪ (((Finset.range (p.length + 1)).erase 1).image fun i => p.getVert i)
    refine ⟨S, ?_, ?_⟩
    · dsimp [S]
      have hBip :=
        diam_geodesic_neighbor_path_witness_bipartite
          (G := G) p hpDist A hAadj hAind
      rw [← Finset.coe_union] at hBip
      exact hBip
    · have hScard :
          S.card = A.card + p.length := by
        simpa [S] using
          diam_geodesic_neighbor_path_witness_card
            (G := G) p hpPath hpDist hpLen A hAadj
      calc
        (G.diam : ℝ) + (indepNeighborsCard G v : ℝ)
            = (p.length : ℝ) + (A.card : ℝ) := by
              rw [← hpDiam, ← hAcard]
        _ = ((A.card + p.length : ℕ) : ℝ) := by
              norm_num [Nat.cast_add, add_comm]
        _ = (S.card : ℝ) := by
              exact_mod_cast hScard.symm
        _ ≤ (S.card : ℝ) := le_rfl
  · have hpZero : p.length = 0 := by omega
    obtain ⟨s, hsBip, hsCard⟩ :=
      exists_indepNeighborsCard_add_one_bipartite_witness (G := G) v
    refine ⟨s, hsBip, ?_⟩
    calc
      (G.diam : ℝ) + (indepNeighborsCard G v : ℝ)
          = (indepNeighborsCard G v : ℝ) := by
            rw [← hpDiam, hpZero]
            norm_num
      _ ≤ ((indepNeighborsCard G v + 1 : ℕ) : ℝ) := by
            exact_mod_cast Nat.le_succ (indepNeighborsCard G v)
      _ = (s.card : ℝ) := by
            exact_mod_cast hsCard.symm

end SimpleGraph


namespace SimpleGraph

open Classical

variable {α : Type*}

noncomputable def indepNeighborsReal [Fintype α]
    (G : SimpleGraph α) (v : α) : ℝ :=
  (indepNeighborsCard G v : ℝ)

noncomputable def indepNeighbors [Fintype α]
    (G : SimpleGraph α) (v : α) : ℝ :=
  indepNeighborsReal G v

noncomputable def eccentricity (G : SimpleGraph α) (v : α) : ℕ∞ :=
  G.eccent v

theorem eccentricity_toNat_eq_vertexEccentricityNat
    [Fintype α] [Nonempty α] {G : SimpleGraph α} (hG : G.Connected) (v : α) :
    (eccentricity G v).toNat = vertexEccentricityNat G v := by
  classical
  apply le_antisymm
  · obtain ⟨w, hw⟩ := G.exists_edist_eq_eccent_of_finite v
    calc
      (eccentricity G v).toNat = (G.edist v w).toNat := by
        rw [eccentricity, ← hw]
      _ = G.dist v w := rfl
      _ ≤ vertexEccentricityNat G v := by
        unfold vertexEccentricityNat
        exact Finset.le_max' _
          _ (Finset.mem_image.mpr ⟨w, Finset.mem_univ w, rfl⟩)
  · unfold vertexEccentricityNat
    refine Finset.max'_le
      (s := Finset.univ.image fun w : α => G.dist v w) (H := by simp)
      (x := (eccentricity G v).toNat) ?_
    intro n hn
    rcases Finset.mem_image.mp hn with ⟨w, _hw, rfl⟩
    have hle :
        (G.dist v w : ℕ∞) ≤ eccentricity G v := by
      rw [(hG v w).coe_dist_eq_edist]
      simpa [eccentricity] using
        (SimpleGraph.edist_le_eccent (G := G) (u := v) (v := w))
    have hne : eccentricity G v ≠ ⊤ := by
      obtain ⟨w, hw⟩ := G.exists_edist_eq_eccent_of_finite v
      have hw_ne : G.edist v w ≠ ⊤ :=
        SimpleGraph.edist_ne_top_iff_reachable.mpr (hG v w)
      simpa [eccentricity, ← hw] using hw_ne
    simpa using ENat.toNat_le_toNat hle hne

theorem indepNeighborsCard_le_maxIndepNeighborsCard
    [Fintype α] [Nonempty α] (G : SimpleGraph α) (v : α) :
    indepNeighborsCard G v ≤ maxIndepNeighborsCard G := by
  classical
  unfold maxIndepNeighborsCard
  exact Finset.le_max' _ _ (Finset.mem_image.mpr ⟨v, Finset.mem_univ v, rfl⟩)

theorem sSup_range_indepNeighborsReal_eq_maxIndepNeighborsCard
    [Fintype α] [Nonempty α] (G : SimpleGraph α) :
    sSup (Set.range (indepNeighborsReal G)) = (maxIndepNeighborsCard G : ℝ) := by
  classical
  apply le_antisymm
  · apply csSup_le
    · exact Set.range_nonempty (indepNeighborsReal G)
    · rintro x ⟨v, rfl⟩
      simpa [indepNeighborsReal] using
        (show (indepNeighborsCard G v : ℝ) ≤
            (maxIndepNeighborsCard G : ℝ) by
          exact_mod_cast indepNeighborsCard_le_maxIndepNeighborsCard (G := G) v)
  · obtain ⟨v, hv⟩ := maxIndepNeighborsCard_exists_vertex (G := G)
    rw [← hv]
    apply le_csSup
    · exact (Set.finite_range (indepNeighborsReal G)).bddAbove
    · exact ⟨v, by simp [indepNeighborsReal]⟩

theorem wowii19_normalized_distEcc_maxCard
    [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (hG : G.Connected) :
    ((⌊averageVertexEccentricity G +
        (maxIndepNeighborsCard G : ℝ)⌋ : ℤ) : ℝ) ≤ (b G : ℝ) := by
  classical
  have havg_le : averageVertexEccentricity G ≤ (G.diam : ℝ) :=
    averageVertexEccentricity_le_diam (G := G) hG
  by_cases hlt : averageVertexEccentricity G < (G.diam : ℝ)
  · have hfloor :
        ((⌊averageVertexEccentricity G +
            (maxIndepNeighborsCard G : ℝ)⌋ : ℤ) : ℝ)
          ≤ (G.diam : ℝ) + (maxIndepNeighborsCard G : ℝ) - 1 :=
      floor_lt_nat_add_cast_le_sub_one
        (m := G.diam) (n := maxIndepNeighborsCard G) hlt
    have h13 :
        (G.diam : ℝ) + (maxIndepNeighborsCard G : ℝ) - 1 ≤ (b G : ℝ) := by
      simpa [maxIndepNeighborsCard] using SimpleGraph.conjecture13 (G := G) hG
    exact le_trans hfloor h13
  · have havg_eq : averageVertexEccentricity G = (G.diam : ℝ) :=
      le_antisymm havg_le (le_of_not_gt hlt)
    obtain ⟨v, hvmax⟩ := maxIndepNeighborsCard_exists_vertex (G := G)
    have hvdiam : vertexEccentricityNat G v = G.diam :=
      vertexEccentricityNat_eq_diam_of_average_eq_diam (G := G) hG havg_eq v
    obtain ⟨y, hydist⟩ :=
      exists_dist_eq_diam_from_vertexEccentricityNat_eq_diam (G := G) hvdiam
    obtain ⟨p, hpPath, hpDist⟩ := (hG v y).exists_path_of_dist
    have hpDiam : p.length = G.diam := by
      rw [hpDist, hydist]
    obtain ⟨s, hsBip, hsCard⟩ :=
      exists_diam_add_indepNeighborsCard_bipartite_witness_of_diam_geodesic_from
        (G := G) hG p hpPath hpDist hpDiam
    have hsLargest :
        (s.card : ℝ) ≤ (b G : ℝ) := by
      have hsLargestNat :
          s.card ≤ largestInducedBipartiteSubgraphSize G :=
        card_le_largestInducedBipartiteSubgraphSize_of_induce_isBipartite
          (G := G) (s := s) hsBip
      simpa [b] using (show (s.card : ℝ) ≤
          (largestInducedBipartiteSubgraphSize G : ℝ) by exact_mod_cast hsLargestNat)
    have hdiam_max_le_b :
        (G.diam : ℝ) + (maxIndepNeighborsCard G : ℝ) ≤ (b G : ℝ) := by
      have hsCard' :
          (G.diam : ℝ) + (maxIndepNeighborsCard G : ℝ) ≤ (s.card : ℝ) := by
        simpa [hvmax] using hsCard
      exact le_trans hsCard' hsLargest
    have hfloor_arg :
        ((⌊averageVertexEccentricity G +
            (maxIndepNeighborsCard G : ℝ)⌋ : ℤ) : ℝ)
          ≤ averageVertexEccentricity G + (maxIndepNeighborsCard G : ℝ) :=
      Int.floor_le _
    exact le_trans hfloor_arg (by simpa [havg_eq] using hdiam_max_le_b)

theorem wowii19_distEcc_sSup_indepNeighborsReal
    [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (hG : G.Connected) :
    ((⌊(∑ v : α, (vertexEccentricityNat G v : ℝ)) / (Fintype.card α : ℝ) +
        sSup (Set.range (indepNeighborsReal G))⌋ : ℤ) : ℝ) ≤ (b G : ℝ) := by
  classical
  have hsSup :
      sSup (Set.range (indepNeighborsReal G)) =
        (maxIndepNeighborsCard G : ℝ) :=
    sSup_range_indepNeighborsReal_eq_maxIndepNeighborsCard (G := G)
  simpa [averageVertexEccentricity, hsSup] using
    wowii19_normalized_distEcc_maxCard (G := G) hG

end SimpleGraph

open Classical
open SimpleGraph

theorem wowii19_formal_conjectures_original_shape
    [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (h_conn : G.Connected) :
    ⌊(∑ v ∈ Finset.univ, ((eccentricity G v).toNat : ℝ)) / (Fintype.card α : ℝ) +
      sSup (Set.range (indepNeighbors G))⌋ ≤ (b G : ℝ) := by
  classical
  simpa [SimpleGraph.indepNeighbors,
    SimpleGraph.eccentricity_toNat_eq_vertexEccentricityNat (G := G) h_conn] using
    SimpleGraph.wowii19_distEcc_sSup_indepNeighborsReal (G := G) h_conn
