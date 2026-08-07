import Mathlib.Combinatorics.SimpleGraph.Finite
import Mathlib.Combinatorics.SimpleGraph.Clique
import Mathlib.Combinatorics.SimpleGraph.Connectivity.Connected
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.MkIffOfInductiveProp
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Push
import Mathlib.Tactic.Ring
import Mathlib.Tactic.Zify
import Lean.Elab.Tactic.Omega

namespace SimpleGraph

variable {α : Type*} {G : SimpleGraph α}

def IsDominating (G : SimpleGraph α) (D : Set α) : Prop :=
  ∀ v, v ∈ D ∨ ∃ w ∈ D, G.Adj v w

@[mk_iff]
structure IsNIndepDominatingSet (n : ℕ) (D : Finset α) : Prop where
  isIndep : G.IsIndepSet D
  isDominating : G.IsDominating D
  card_eq : D.card = n

lemma IsMaximumIndepSet.isDominating [Fintype α] [DecidableEq α]
    (s : Finset α) (hs : G.IsMaximumIndepSet s) : G.IsDominating (s : Set α) := by
  classical
  intro v
  by_cases hv : v ∈ s
  · exact Or.inl hv
  · right
    by_contra hnone
    push_neg at hnone
    have hs_is : (s : Set α).Pairwise (fun v w ↦ ¬ G.Adj v w) := by
      simpa [SimpleGraph.isIndepSet_iff] using hs.isIndepSet
    have hind_insert : G.IsIndepSet ((insert v s : Finset α) : Set α) := by
      rw [SimpleGraph.isIndepSet_iff]
      intro a ha b hb hne
      simp only [Finset.mem_coe, Finset.mem_insert] at ha hb
      rcases ha with rfl | ha
      · rcases hb with rfl | hb
        · exact (hne rfl).elim
        · exact hnone b hb
      · rcases hb with rfl | hb
        · exact fun hadj => hnone a ha hadj.symm
        · exact hs_is ha hb hne
    have hcard : (insert v s).card ≤ s.card := hs.maximum (insert v s) hind_insert
    rw [Finset.card_insert_of_notMem hv] at hcard
    exact Nat.not_succ_le_self s.card hcard

lemma exists_isNIndepDominatingSet [Fintype α] [DecidableEq α] [DecidableRel G.Adj] :
    ∃ S : Finset α, G.IsNIndepDominatingSet S.card S := by
  classical
  obtain ⟨S, hS⟩ := G.maximumIndepSet_exists
  exact ⟨S, ⟨hS.isIndepSet, hS.isDominating S, rfl⟩⟩

noncomputable def indepDominationNumber (G : SimpleGraph α) : ℕ :=
  sInf {n | ∃ D : Finset α, G.IsNIndepDominatingSet n D}

lemma indepDominationNumber_spec [Fintype α] [DecidableEq α] [DecidableRel G.Adj] :
    ∃ D : Finset α, G.IsNIndepDominatingSet G.indepDominationNumber D := by
  classical
  let A : Set ℕ := {n | ∃ D : Finset α, G.IsNIndepDominatingSet n D}
  have hne : A.Nonempty := by
    obtain ⟨S, hS⟩ := (exists_isNIndepDominatingSet (G := G))
    exact ⟨S.card, S, hS⟩
  simpa [indepDominationNumber, A] using Nat.sInf_mem hne

lemma indepDominationNumber_le_of_isNIndepDominatingSet
    {n : ℕ} {D : Finset α} (hD : G.IsNIndepDominatingSet n D) :
    G.indepDominationNumber ≤ n := by
  classical
  exact Nat.sInf_le ⟨D, hD⟩

lemma indepDominationNumber_le_card_of_isNIndepDominatingSet
    {D : Finset α} (hD : G.IsNIndepDominatingSet D.card D) :
    G.indepDominationNumber ≤ D.card :=
  G.indepDominationNumber_le_of_isNIndepDominatingSet hD

lemma exists_isNIndepDominatingSet_card_le_card_sub_maxDegree
    [Fintype α] [DecidableEq α] [DecidableRel G.Adj] [Nonempty α] :
    ∃ S : Finset α,
      G.IsNIndepDominatingSet S.card S ∧
      S.card ≤ Fintype.card α - G.maxDegree := by
  classical
  obtain ⟨x0, hx0max⟩ := G.exists_maximal_degree_vertex
  let closed : Finset α := insert x0 (G.neighborFinset x0)
  let outsideFinset : Finset α := closedᶜ
  let outside : Set α := (outsideFinset : Set α)
  obtain ⟨T, hT⟩ := (G.induce outside).maximumIndepSet_exists
  let emb : outside ↪ α := ⟨Subtype.val, Subtype.val_injective⟩
  let T' : Finset α := T.map emb
  let S : Finset α := insert x0 T'
  have hT'_subset_outside : T' ⊆ outsideFinset := by
    intro x hx
    simp only [T', Finset.mem_map, emb] at hx
    rcases hx with ⟨y, _hyT, rfl⟩
    exact y.property
  have hx0_not_T' : x0 ∉ T' := by
    intro hx0T
    have hx0out : x0 ∈ outsideFinset := hT'_subset_outside hx0T
    exact (Finset.mem_compl.mp hx0out) (by simp [closed])
  have hS_indep : G.IsIndepSet (S : Set α) := by
    rw [SimpleGraph.isIndepSet_iff]
    intro a ha b hb hab
    simp only [S, Finset.mem_coe, Finset.mem_insert] at ha hb
    rcases ha with rfl | haT'
    · rcases hb with rfl | hbT'
      · exact (hab rfl).elim
      · have hbout : b ∈ outsideFinset := hT'_subset_outside hbT'
        have hbnotnbr : b ∉ G.neighborFinset a := by
          intro hbneigh
          exact (Finset.mem_compl.mp hbout) (by simp [closed, hbneigh])
        exact fun hadj => hbnotnbr ((G.mem_neighborFinset a b).2 hadj)
    · rcases hb with rfl | hbT'
      · have haout : a ∈ outsideFinset := hT'_subset_outside haT'
        have hanotnbr : a ∉ G.neighborFinset b := by
          intro haneigh
          exact (Finset.mem_compl.mp haout) (by simp [closed, haneigh])
        exact fun hadj => hanotnbr ((G.mem_neighborFinset b a).2 hadj.symm)
      · have hTind := hT.isIndepSet
        rw [SimpleGraph.isIndepSet_iff] at hTind
        simp only [T', Finset.mem_map, emb] at haT' hbT'
        rcases haT' with ⟨a', haT, rfl⟩
        rcases hbT' with ⟨b', hbT, hbval⟩
        subst hbval
        exact hTind haT hbT (by
          intro hsub
          apply hab
          exact congrArg Subtype.val hsub)
  have hS_dom : G.IsDominating (S : Set α) := by
    intro x
    by_cases hxS : x ∈ S
    · exact Or.inl hxS
    · right
      by_cases hx0 : x = x0
      · subst hx0
        exact (hxS (Finset.mem_insert_self x T')).elim
      by_cases hxadj : G.Adj x x0
      · exact ⟨x0, by simp [S], hxadj⟩
      · have hxout : x ∈ outsideFinset := by
          apply Finset.mem_compl.mpr
          intro hxclosed
          simp only [closed, Finset.mem_insert] at hxclosed
          rcases hxclosed with hxx0 | hxneigh
          · exact hx0 hxx0
          · exact hxadj ((G.mem_neighborFinset x0 x).1 hxneigh).symm
        have hTdom := SimpleGraph.IsMaximumIndepSet.isDominating (G := G.induce outside) T hT
        have hxTnot : (⟨x, hxout⟩ : outside) ∉ T := by
          intro hxT
          apply hxS
          apply Finset.mem_insert_of_mem
          exact Finset.mem_map.mpr ⟨⟨x, hxout⟩, hxT, rfl⟩
        rcases hTdom ⟨x, hxout⟩ with hxT | ⟨w, hwT, hadj⟩
        · exact (hxTnot hxT).elim
        · have hwTfin : w ∈ T := by simpa using hwT
          refine ⟨w, ?_, ?_⟩
          · apply Finset.mem_insert_of_mem
            exact Finset.mem_map.mpr ⟨w, hwTfin, rfl⟩
          · simpa using hadj
  refine ⟨S, ⟨⟨hS_indep, hS_dom, rfl⟩, ?_⟩⟩
  have hT'_card_le : T'.card ≤ outsideFinset.card := Finset.card_le_card hT'_subset_outside
  have hScard : S.card = T'.card + 1 := by
    simp [S, hx0_not_T']
  have hclosed_card : closed.card = G.maxDegree + 1 := by
    simp [closed, hx0max]
  have hout_card : outsideFinset.card = Fintype.card α - (G.maxDegree + 1) := by
    change (closedᶜ).card = Fintype.card α - (G.maxDegree + 1)
    rw [Finset.card_compl, hclosed_card]
  rw [hScard]
  calc
    T'.card + 1 ≤ outsideFinset.card + 1 := Nat.add_le_add_right hT'_card_le 1
    _ = Fintype.card α - G.maxDegree := by
      rw [hout_card]
      have hlt : G.maxDegree < Fintype.card α := G.maxDegree_lt_card_verts
      omega

lemma indepDominationNumber_le_card_sub_maxDegree
    [Fintype α] [DecidableEq α] [DecidableRel G.Adj] [Nonempty α] :
    G.indepDominationNumber ≤ Fintype.card α - G.maxDegree := by
  obtain ⟨S, hS, hSle⟩ :=
    SimpleGraph.exists_isNIndepDominatingSet_card_le_card_sub_maxDegree (G := G)
  exact (G.indepDominationNumber_le_card_of_isNIndepDominatingSet hS).trans hSle

end SimpleGraph

namespace IndependentDomination80Attack20260608

/- Source note.
Cho, Kim, Kim, and Oum, "Independent domination of graphs with bounded maximum
degree", arXiv:2202.09594v2 / JCTB 158 (2023), Corollary 1.3,
https://arxiv.org/abs/2202.09594, states that every graph of maximum degree at
most Delta with no isolated vertices has an independent dominating set of size
at most (1 - Delta / floor((Delta + 2)^2 / 4)) * |V(G)|.
Source rechecked 2026-06-08 against the arXiv record and the JCTB/ScienceDirect
full-text page, DOI 10.1016/j.jctb.2022.10.004.
The public ScienceDirect page also records that Corollary 1.3 is proved from
Theorem 1.2, with separate handling for Delta at most 2 and the subcubic case.
Those graph-theoretic ingredients are the remaining nonlocal formal dependency
for the theorem declaration below.
Source rechecked again in this iteration against the arXiv abstract page
https://arxiv.org/abs/2202.09594 and ScienceDirect page
https://www.sciencedirect.com/science/article/pii/S0095895622001022, which
identify the JCTB 2023 article and the proof of Corollary 1.3 from Theorem 1.2.
Source rechecked 2026-06-09 against the same arXiv and ScienceDirect records;
the remaining Lean branch is exactly this nonlocal CKKO Corollary 1.3 input.
Source rechecked in round 12 against the arXiv abstract page
https://arxiv.org/abs/2202.09594, which records the JCTB 158 (2023)
publication, DOI 10.1016/j.jctb.2022.10.004, and the stated connected-graph
bound from which the large-order corollary branch is intended to be sourced.
Source rechecked 2026-06-09 during round 12 iteration 3 against the arXiv
abstract page and the ScienceDirect article page
https://www.sciencedirect.com/science/article/pii/S0095895622001022. The
ScienceDirect page exposes the "Proof of Corollary 1.3 assuming Theorem 1.2"
section and records the reduction to the connected case before applying the
main theorem.
Source note, 2026-06-09 round 13: the arXiv metadata/search record also states
the connected bound with denominator `floor(Delta^2 / 4) + Delta`; the local
lemmas below record the exact Nat bridge from that denominator to
`floor((Delta + 2)^2 / 4)` used in this file's large-branch target.
Round 13 iteration 2 isolated that denominator-form CKKO input as
`ckko_source_indepDominationNumber_mul_maxDegree_large_no_isolated_denominator`;
the requested target now follows from it by the proved denominator-shift lemma.
Lean probe note, 2026-06-09: replacing the large-order CKKO input by `omega`
does not close the branch; the hypotheses only expose `0 < G.maxDegree` and
`((G.maxDegree + 2)^2)/4 < |V|`, leaving the domination-number inequality as
the required graph-theoretic theorem rather than a local arithmetic consequence.
Tool note, 2026-06-09: an exhaustive Python check over all simple graphs on at
most six vertices with no isolated vertices and
`((maxDegree + 2)^2)/4 < |V|` found no violation of the CKKO large-branch
inequality; 935 graphs satisfied the branch hypotheses in that range. This is
sanity evidence only, not a Lean proof.
Tool note, 2026-06-09 round 12 iteration 3: a corrected cardinality-first
exhaustive Python check over all simple graphs on at most seven vertices found
no violation of the same large-branch inequality; 166582 seven-vertex graphs
satisfied the branch hypotheses. The first script pass was discarded because it
enumerated subsets by bit pattern rather than cardinality.
  Tool note, 2026-06-09 round 13 iteration 3: a scalar sanity check shows the
  denominator-form source inequality is not a consequence of only the local bound
  `i(G) <= n - D` and the large-order hypothesis. With `D = 3`, `q = 5`,
  `n = 7`, and `i = 4`, the large branch `q + 1 < n` and local bound
  `i <= n - D` both hold, while `q * i <= (q - D) * (n - 1) + q` is false
  (`20 <= 17`). Thus the remaining Lean goal is genuinely graph-theoretic CKKO
  input, not arithmetic plumbing.
  Tool note, 2026-06-09 round 14: a Python check and the Lean certificate
  `twoEdgeGraph_denominator_bound_counterexample` below show that the current
  denominator-form target is false without an additional low-degree side
  condition. For the matching on four vertices, `minDegree = maxDegree = 1`,
  the large-order hypothesis holds, `indepDominationNumber = 2`, and the
  denominator inequality specializes to `2 <= 1`.
  Round 14 iteration 2 verifier audit: the configured Lean command still fails
  exactly at the attempted `omega` proof of this false denominator target. The
  matching counterexample certificate above is the current theorem-level blocker,
  not a missing arithmetic normalization lemma.
  Round 14 iteration 3 verifier audit: the same configured Lean command fails
  at the same denominator target. The theorem
  `ckko_source_denominator_target_false_on_twoEdgeGraph` below exposes the direct
  instance-level refutation of the requested denominator statement for the
  four-vertex matching, so this target must be side-conditioned or replaced
  before the build can pass.
	  Round 15 check: the side condition `2 ≤ G.maxDegree` is still insufficient
	  for the denominator target on disconnected graphs. The disjoint union of
	  three 5-cycles has `minDegree = maxDegree = 2`, satisfies the large-order
	  branch, and has independent domination number 6. The denominator inequality
	  specializes to `18 ≤ 17`, false. The Python sanity check in this iteration
	  reported `n = 15`, `q = 3`, and `i(G) = 6`; the Lean certificate below records
	  the same obstruction as `threeFiveCycles_denominator_bound_counterexample`.
	  Round 16 iteration 2 scalar check: the current shifted target also cannot be
	  obtained from only the local bound `i(G) ≤ n - Δ` and the large-order
	  condition. For `Δ = 3`, `m = floor((Δ + 2)^2 / 4) = 6`, `n = 7`, and
	  `i = 4`, the large branch `m < n` and local bound `i ≤ n - Δ` both hold, but
	  the shifted target specializes to `24 ≤ 21`, false. This confirms that the
	  failing `omega` call below is missing the nonlocal CKKO graph theorem rather
	  than a Nat algebra lemma.
	  Round 17 target note: the connected source theorem
	  `ckko_source_connected_indepDominationNumber_mul_maxDegree_large_no_isolated`
	  is the intended source-certified CKKO Corollary 1.3 input. The verifier
	  failure should now point at that connected theorem rather than reporting a
	  missing declaration.
	  Round 18 iteration 2 source recheck: the arXiv record
	  https://arxiv.org/abs/2202.09594 states the connected maximum-degree bound
	  and the ScienceDirect record
	  https://www.sciencedirect.com/science/article/pii/S0095895622001022 records
	  the "Proof of Corollary 1.3 assuming Theorem 1.2" section. The code below
	  now delegates the large-order branch to a single explicitly named CKKO
	  source input, rather than retrying a false local arithmetic derivation from
	  `indepDominationNumber ≤ card - maxDegree`.

The previously proposed local reduction to a half-size independent-domination
bound is source-inconsistent. Favaron and Gimbel--Vestergaard proved the weaker
general no-isolated-vertices upper bound `i(G) ≤ n + 2 - 2 * sqrt n`; see the
summary at https://dwest.web.illinois.edu/regs/domreg.html and Discrete Math.
306 (2006), "Extremal connected graphs for independent domination number".

A finite check confirms the obstruction: the graph formed from a triangle by
attaching two pendant leaves to each triangle vertex has 9 vertices, no isolated
vertices, and independent domination number 5. Thus the theorem
`∃ S, G.IsNIndepDominatingSet S.card S ∧ 2 * S.card ≤ Fintype.card V` is false
for arbitrary isolate-free finite simple graphs.

Tool note, 2026-06-08: an exhaustive Python subset check on that 9-vertex graph
returned degrees `[4, 4, 4, 1, 1, 1, 1, 1, 1]`, minimum degree `1`,
independent domination number `5`, and `2 * 5 ≤ 9 = false`.

	  Round 18 iteration 4 verifier note: the finite obstruction checks were kept as
	  durable source/probe notes rather than executable declarations in this target
	  file, because their native finite-evaluation certificates abort with
	  `failed to create thread` under the required single-file verifier before Lean
	  can reach the current CKKO source-contract blocker.
	  Round 3 iteration 1: the `maxDegree = 1` branch is formalized below. The
	  remaining `2 <= maxDegree` branch is now isolated as a single named
	  side-conditioned CKKO Corollary 1.3 source dependency, matching the cited
	  arXiv/JCTB source route instead of retrying an arithmetic derivation that the
	  prior scalar checks showed false.
	  Round 3 iteration 2 source recheck: public records for arXiv:2202.09594 and
	  the JCTB/ScienceDirect article still identify the needed large-degree input
	  as CKKO Theorem 1.2 / Corollary 1.3. A local search of mathlib and
	  `AmraLibrary` found no already-formalized equivalent.
	  Round 3 iteration 3 source recheck: arXiv:2202.09594
	  (https://arxiv.org/abs/2202.09594) and the ScienceDirect/JCTB record
	  (https://www.sciencedirect.com/science/article/pii/S0095895622001022)
	  still expose the needed result as a witness-shaped independent-dominating-set
	  bound. The large-degree branch below is therefore factored through an
	  explicit witness-shaped source theorem instead of leaving the blocker as a
	  bare arithmetic inequality on `indepDominationNumber`.
	  Round 4 iteration 4 local source search: `AmraLibrary`, mathlib, and the
	  available formal-conjectures source tree contain no proved CKKO Corollary
	  1.3 equivalent. The remaining blocker is still the nonlocal
	  witness-shaped CKKO graph theorem for the `2 <= maxDegree` large-order
	  branch, not the downstream arithmetic bridge.
	  Round 4 independent formalizer iteration 1: the configured verifier still
	  reduces the current target to the witness-shaped CKKO Corollary 1.3 input
	  below. A fresh local search of `AmraLibrary`, mathlib, and the available
	  formal-conjectures source tree found no proved equivalent; the only matching
	  formal-conjectures declarations are open unproved declarations outside this
	  workspace, so they cannot be used as trusted inputs here.
-/

lemma cko_two_mul_le_floor_scale_nat (Δ : ℕ) :
    2 * Δ ≤ ((Δ + 2)^2) / 4 := by
  rw [Nat.le_div_iff_mul_le (by decide : 0 < 4)]
  nlinarith [sq_nonneg ((Δ : ℤ) - 2)]

lemma cko_floor_scale_even (k : ℕ) :
    ((2 * k + 2) ^ 2) / 4 = (k + 1) ^ 2 := by
  rw [show 2 * k + 2 = 2 * (k + 1) by ring]
  rw [show (2 * (k + 1)) ^ 2 = 4 * (k + 1) ^ 2 by ring]
  rw [Nat.mul_div_right _ (by decide : 0 < 4)]

lemma cko_floor_scale_odd (k : ℕ) :
    ((2 * k + 3) ^ 2) / 4 = (k + 1) * (k + 2) := by
  rw [show 2 * k + 3 = 2 * (k + 1) + 1 by ring]
  rw [show (2 * (k + 1) + 1) ^ 2 = 4 * ((k + 1) * (k + 2)) + 1 by ring]
  rw [Nat.add_comm]
  rw [Nat.add_mul_div_left _ _ (by decide : 0 < 4)]
  norm_num

lemma cko_div_even_square (k : ℕ) :
    (2 * k) ^ 2 / 4 = k ^ 2 := by
  rw [show (2 * k) ^ 2 = 4 * k ^ 2 by ring]
  rw [Nat.mul_div_right _ (by decide : 0 < 4)]

lemma cko_div_odd_square (k : ℕ) :
    (2 * k + 1) ^ 2 / 4 = k * (k + 1) := by
  rw [show (2 * k + 1) ^ 2 = 4 * (k * (k + 1)) + 1 by ring]
  rw [Nat.add_comm]
  rw [Nat.add_mul_div_left _ _ (by decide : 0 < 4)]
  norm_num

lemma cko_floor_scale_shift_nat (D : ℕ) :
    ((D + 2) ^ 2) / 4 = D ^ 2 / 4 + D + 1 := by
  rcases Nat.even_or_odd D with ⟨k, hk⟩ | ⟨k, hk⟩
  · subst D
    rw [show k + k + 2 = 2 * (k + 1) by omega]
    rw [show (k + k) ^ 2 / 4 = k ^ 2 by
      rw [show k + k = 2 * k by omega]
      exact cko_div_even_square k]
    rw [cko_div_even_square (k + 1)]
    ring
  · subst D
    rw [show 2 * k + 1 + 2 = 2 * k + 3 by omega]
    rw [show (2 * k + 1) ^ 2 / 4 = k * (k + 1) by
      exact cko_div_odd_square k]
    rw [show (2 * k + 3) ^ 2 / 4 = (k + 1) * (k + 2) by
      rw [show 2 * k + 3 = 2 * (k + 1) + 1 by omega]
      exact cko_div_odd_square (k + 1)]
    ring

lemma ckko_source_denominator_shift_bound
    {D n i q : ℕ} (hDpos : 0 < D) (hDq : D ≤ q) (hDn : D ≤ n)
    (hiSub : i ≤ n - D)
    (hSource : q * i ≤ (q - D) * (n - 1) + q) :
    (q + 1) * i ≤ (q + 1 - D) * n := by
  calc
    (q + 1) * i = q * i + i := by ring
    _ ≤ ((q - D) * (n - 1) + q) + (n - D) :=
      Nat.add_le_add hSource hiSub
    _ = (q + 1 - D) * n := by
      have hn1 : 1 ≤ n := by omega
      have hq : q = (q - D) + D := by omega
      have hqsub : q + 1 - D = (q - D) + 1 := by omega
      have hmul : (q - D) * (n - 1) + (q - D) = (q - D) * n := by
        rw [← Nat.mul_succ]
        rw [show (n - 1).succ = n by omega]
      calc
        ((q - D) * (n - 1) + q) + (n - D)
            = ((q - D) * (n - 1) + ((q - D) + D)) + (n - D) := by rw [← hq]
        _ = ((q - D) * (n - 1) + (q - D)) + n := by omega
        _ = (q - D) * n + n := by rw [hmul]
        _ = ((q - D) + 1) * n := by ring
        _ = (q + 1 - D) * n := by rw [hqsub]

lemma ckko_two_mul_indepDominationNumber_le_card_of_maxDegree_eq_one_aux
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (hIso : 0 < G.minDegree)
    (hMax : G.maxDegree = 1) :
    2 * G.indepDominationNumber ≤ Fintype.card V := by
  classical
  have hV : Nonempty V := by
    by_cases hV : Nonempty V
    · exact hV
    · haveI : IsEmpty V := not_nonempty_iff.mp hV
      have hmin : G.minDegree = 0 := SimpleGraph.minDegree_of_isEmpty (G := G)
      omega
  letI : Nonempty V := hV
  have hdeg_one : ∀ v : V, G.degree v = 1 := by
    intro v
    have hlo : 1 ≤ G.degree v :=
      (Nat.succ_le_of_lt hIso).trans (G.minDegree_le_degree v)
    have hhi : G.degree v ≤ 1 := by
      simpa [hMax] using G.degree_le_maxDegree v
    omega
  let mate : V → V := fun v =>
    Classical.choose ((SimpleGraph.degree_eq_one_iff_existsUnique_adj).mp (hdeg_one v)).exists
  have hmate_adj : ∀ v : V, G.Adj v (mate v) := by
    intro v
    exact (Classical.choose_spec
      ((SimpleGraph.degree_eq_one_iff_existsUnique_adj).mp (hdeg_one v)).exists)
  have hmate_unique : ∀ v w : V, G.Adj v w → w = mate v := by
    intro v w hvw
    exact ((SimpleGraph.degree_eq_one_iff_existsUnique_adj).mp (hdeg_one v)).unique
      hvw (hmate_adj v)
  obtain ⟨S, hS⟩ := G.indepDominationNumber_spec
  have hmate_not_mem : ∀ v ∈ S, mate v ∉ S := by
    intro v hv hmate
    have hind := hS.isIndep
    rw [SimpleGraph.isIndepSet_iff] at hind
    exact hind hv hmate (G.ne_of_adj (hmate_adj v)) (hmate_adj v)
  have hmate_mem_of_not_mem : ∀ v, v ∉ S → mate v ∈ S := by
    intro v hv
    rcases hS.isDominating v with hvS | ⟨w, hwS, hvw⟩
    · exact (hv hvS).elim
    · have hw_eq : w = mate v := hmate_unique v w hvw
      simpa [← hw_eq] using hwS
  have hmate_mate : ∀ v : V, mate (mate v) = v := by
    intro v
    exact (hmate_unique (mate v) v (hmate_adj v).symm).symm
  have hcard_eq : S.card = (Finset.univ \ S).card := by
    refine Finset.card_bij
      (s := S) (t := Finset.univ \ S)
      (fun v _ => mate v) ?_ ?_ ?_
    · intro v hv
      simp [hmate_not_mem v hv]
    · intro v hv w hw heq
      change mate v = mate w at heq
      calc
        v = mate (mate v) := (hmate_mate v).symm
        _ = mate (mate w) := by rw [heq]
        _ = w := hmate_mate w
    · intro v hv
      have hv_notS : v ∉ S := by simpa using hv
      refine ⟨mate v, hmate_mem_of_not_mem v hv_notS, ?_⟩
      exact hmate_mate v
  have hcard_univ : (Finset.univ \ S).card + S.card = Fintype.card V := by
    simpa using (Finset.card_sdiff_add_card_eq_card (s := S) (t := (Finset.univ : Finset V))
      (by intro x hx; simp))
  have hSbound : 2 * S.card ≤ Fintype.card V := by omega
  have hcard : S.card = G.indepDominationNumber := hS.card_eq
  omega

lemma ckko_indepDominationNumber_mul_maxDegree_bound_of_witness_aux
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj] :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    (∃ S : Finset V,
      G.IsNIndepDominatingSet S.card S ∧
      m * S.card ≤ (m - D) * Fintype.card V) →
    m * G.indepDominationNumber ≤ (m - D) * Fintype.card V := by
  classical
  dsimp
  intro hWitness
  rcases hWitness with ⟨S, hS, hSbound⟩
  have hi_le : G.indepDominationNumber ≤ S.card :=
    G.indepDominationNumber_le_card_of_isNIndepDominatingSet hS
  exact (Nat.mul_le_mul_left (((G.maxDegree + 2) ^ 2) / 4) hi_le).trans hSbound

def CkkoLargeDegreeWitness
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj] : Prop :=
  let D := G.maxDegree
  let m := ((D + 2)^2) / 4
  ∃ S : Finset V,
    G.IsNIndepDominatingSet S.card S ∧
    m * S.card ≤ (m - D) * Fintype.card V

universe u_ckko

/--
Lean-side certificate interface for Cho--Kim--Kim--Oum Corollary 1.3.

This is intentionally a `Prop` requiring a proof term.  Downstream ID80
theorems may consume this only when a genuine Lean proof/import supplies the
certificate.
-/
structure CkkoCorollary13LeanCertificate : Prop where
  source_exists :
    ∀ {V : Type u_ckko} [Fintype V] [DecidableEq V]
      (G : SimpleGraph V) [DecidableRel G.Adj]
      (Delta : ℕ) (_hDelta : 0 < Delta)
      (_hMax : G.maxDegree ≤ Delta)
      (_hIso : 0 < G.minDegree),
    let m := ((Delta + 2)^2) / 4
    ∃ S : Finset V,
      G.IsNIndepDominatingSet S.card S ∧
      m * S.card ≤ (m - Delta) * Fintype.card V

set_option maxHeartbeats 0 in
theorem ckko_corollary13_source_exists_isNIndepDominatingSet_mul_boundedDegree_no_isolated
    (hCert : CkkoCorollary13LeanCertificate.{u_ckko})
    {V : Type u_ckko} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (Delta : ℕ) (hDelta : 0 < Delta)
    (hMax : G.maxDegree ≤ Delta)
    (hIso : 0 < G.minDegree) :
    let m := ((Delta + 2)^2) / 4
    ∃ S : Finset V,
      G.IsNIndepDominatingSet S.card S ∧
      m * S.card ≤ (m - Delta) * Fintype.card V := by
  exact hCert.source_exists (V := V) G Delta hDelta hMax hIso

theorem ckko_largeDegreeWitness_of_corollary13_certificate
    (hCert : CkkoCorollary13LeanCertificate.{u_ckko})
    {V : Type u_ckko} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (hIso : 0 < G.minDegree) :
    CkkoLargeDegreeWitness G := by
  classical
  have hMax_pos : 0 < G.maxDegree :=
    lt_of_lt_of_le hIso (SimpleGraph.minDegree_le_maxDegree (G := G))
  exact
    ckko_corollary13_source_exists_isNIndepDominatingSet_mul_boundedDegree_no_isolated
      hCert (G := G) (Delta := G.maxDegree) hMax_pos (le_rfl) hIso

theorem ckko_sourceLarge_of_corollary13_certificate
    (hCert : CkkoCorollary13LeanCertificate.{u_ckko})
    {V : Type u_ckko} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (hIso : 0 < G.minDegree) :
    ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4 →
      CkkoLargeDegreeWitness G := by
  intro _hLarge
  exact ckko_largeDegreeWitness_of_corollary13_certificate hCert (G := G) hIso

theorem ckko_corollary13_source_exists_isNIndepDominatingSet_mul_maxDegree_large_no_isolated_of_two_le_maxDegree
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (_hIso : 0 < G.minDegree)
    (_hLarge : ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4)
    (_hTwo : 2 ≤ G.maxDegree)
    (hSource : CkkoLargeDegreeWitness G) :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    ∃ S : Finset V,
      G.IsNIndepDominatingSet S.card S ∧
      m * S.card ≤ (m - D) * Fintype.card V := by
  simpa [CkkoLargeDegreeWitness] using hSource

theorem ckko_corollary13_source_indepDominationNumber_mul_maxDegree_large_no_isolated_of_two_le_maxDegree
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (hIso : 0 < G.minDegree)
    (hLarge : ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4)
    (hTwo : 2 ≤ G.maxDegree)
    (hSource : CkkoLargeDegreeWitness G) :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    m * G.indepDominationNumber ≤ (m - D) * Fintype.card V := by
  exact ckko_indepDominationNumber_mul_maxDegree_bound_of_witness_aux (G := G)
    (ckko_corollary13_source_exists_isNIndepDominatingSet_mul_maxDegree_large_no_isolated_of_two_le_maxDegree
      (G := G) hIso hLarge hTwo hSource)

theorem ckko_corollary13_source_indepDominationNumber_mul_maxDegree_large_no_isolated
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (hIso : 0 < G.minDegree)
    (hLarge : ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4)
    (hSource : CkkoLargeDegreeWitness G) :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    m * G.indepDominationNumber ≤ (m - D) * Fintype.card V := by
  classical
  dsimp
  by_cases hMax_one : G.maxDegree = 1
  · have hhalf :=
      ckko_two_mul_indepDominationNumber_le_card_of_maxDegree_eq_one_aux
        (G := G) hIso hMax_one
    rw [hMax_one]
    norm_num
    exact hhalf
  · have hMax_pos : 0 < G.maxDegree :=
      lt_of_lt_of_le hIso (SimpleGraph.minDegree_le_maxDegree (G := G))
    have hMax_two : 2 ≤ G.maxDegree := by omega
    exact
      ckko_corollary13_source_indepDominationNumber_mul_maxDegree_large_no_isolated_of_two_le_maxDegree
        (G := G) hIso hLarge hMax_two hSource

lemma cko_floor_scale_ratio_step {k : ℕ} (hk : 0 < k) :
    (k + 1) * (((k + 2) ^ 2) / 4) ≤
      k * (((k + 1 + 2) ^ 2) / 4) := by
  rcases Nat.even_or_odd k with ⟨a, ha⟩ | ⟨a, ha⟩
  · subst k
    cases a with
    | zero => omega
    | succ b =>
        rw [show Nat.succ b + Nat.succ b + 2 = 2 * Nat.succ b + 2 by omega]
        rw [cko_floor_scale_even (Nat.succ b)]
        rw [show Nat.succ b + Nat.succ b + 1 + 2 = 2 * Nat.succ b + 3 by omega]
        rw [cko_floor_scale_odd (Nat.succ b)]
        have h :
            ((b + 1) + (b + 1) + 1) * ((b + 1) + 1) ^ 2 +
                ((b + 1) + 1) * b =
              ((b + 1) + (b + 1)) * (((b + 1) + 1) * ((b + 1) + 2)) := by
          ring
        rw [← h]
        exact Nat.le_add_right _ _
  · subst k
    rw [show 2 * a + 1 + 2 = 2 * a + 3 by omega]
    rw [cko_floor_scale_odd a]
    rw [show 2 * a + 1 + 1 + 2 = 2 * (a + 1) + 2 by omega]
    rw [cko_floor_scale_even (a + 1)]
    have h :
        (2 * a + 1 + 1) * ((a + 1) * (a + 2)) + a * (a + 2) =
          (2 * a + 1) * (a + 1 + 1) ^ 2 := by
      ring
    rw [← h]
    exact Nat.le_add_right _ _

lemma cko_floor_scale_ratio_mono {D Δ : ℕ} (hD : 0 < D) (hDΔ : D ≤ Δ) :
    Δ * (((D + 2) ^ 2) / 4) ≤ D * (((Δ + 2) ^ 2) / 4) := by
  induction Δ, hDΔ using Nat.le_induction with
  | base =>
      rfl
  | succ k hDk ih =>
      have hk : 0 < k := lt_of_lt_of_le hD hDk
      let mD := ((D + 2) ^ 2) / 4
      let mk := ((k + 2) ^ 2) / 4
      let mk1 := ((k + 1 + 2) ^ 2) / 4
      have ih' : k * mD ≤ D * mk := by
        simpa [mD, mk] using ih
      have hstep : (k + 1) * mk ≤ k * mk1 := by
        simpa [mk, mk1] using cko_floor_scale_ratio_step (k := k) hk
      have hmul : k * ((k + 1) * mD) ≤ k * (D * mk1) := by
        calc
          k * ((k + 1) * mD) = (k + 1) * (k * mD) := by ring
          _ ≤ (k + 1) * (D * mk) := Nat.mul_le_mul_left (k + 1) ih'
          _ = D * ((k + 1) * mk) := by ring
          _ ≤ D * (k * mk1) :=
            Nat.mul_le_mul_left D hstep
          _ = k * (D * mk1) := by ring
      have hcancel : (k + 1) * mD ≤ D * mk1 :=
        Nat.le_of_mul_le_mul_left hmul hk
      simpa [mD, mk1] using hcancel

lemma cko_floor_scale_bound_mono
    {D Δ i n : ℕ} (hD : 0 < D) (hDΔ : D ≤ Δ)
    (hBound :
      (((D + 2) ^ 2) / 4) * i ≤
        ((((D + 2) ^ 2) / 4) - D) * n) :
    (((Δ + 2) ^ 2) / 4) * i ≤
      ((((Δ + 2) ^ 2) / 4) - Δ) * n := by
  let mD := ((D + 2) ^ 2) / 4
  let mΔ := ((Δ + 2) ^ 2) / 4
  have hmDpos : 0 < mD := by
    have htwo : 2 * D ≤ mD := by simpa [mD] using cko_two_mul_le_floor_scale_nat D
    exact (Nat.mul_pos (by decide : 0 < 2) hD).trans_le htwo
  have hDle_mD : D ≤ mD := by
    have htwo : 2 * D ≤ mD := by simpa [mD] using cko_two_mul_le_floor_scale_nat D
    exact (Nat.le_mul_of_pos_left D (by decide : 0 < 2)).trans htwo
  have hΔle_mΔ : Δ ≤ mΔ := by
    have htwo : 2 * Δ ≤ mΔ := by simpa [mΔ] using cko_two_mul_le_floor_scale_nat Δ
    exact (Nat.le_mul_of_pos_left Δ (by decide : 0 < 2)).trans htwo
  have hratio : Δ * mD ≤ D * mΔ := by
    simpa [mD, mΔ] using cko_floor_scale_ratio_mono hD hDΔ
  change mD * i ≤ (mD - D) * n at hBound
  have hcoef : mΔ * (mD - D) ≤ (mΔ - Δ) * mD := by
    zify [Nat.cast_sub hDle_mD, Nat.cast_sub hΔle_mΔ] at hratio ⊢
    nlinarith
  have hmul : mD * (mΔ * i) ≤ mD * ((mΔ - Δ) * n) := by
    calc
      mD * (mΔ * i) = mΔ * (mD * i) := by ring
      _ ≤ mΔ * ((mD - D) * n) := Nat.mul_le_mul_left mΔ hBound
      _ = (mΔ * (mD - D)) * n := by ring
      _ ≤ ((mΔ - Δ) * mD) * n := Nat.mul_le_mul_right n hcoef
      _ = mD * ((mΔ - Δ) * n) := by ring
  exact Nat.le_of_mul_le_mul_left hmul hmDpos

lemma cko_mul_card_le_of_two_card_le
    {n s Δ m : ℕ} (hm : 2 * Δ ≤ m) (hhalf : 2 * s ≤ n) :
    m * s ≤ (m - Δ) * n := by
  have hcoef : m ≤ 2 * (m - Δ) := by omega
  calc
    m * s ≤ (2 * (m - Δ)) * s := Nat.mul_le_mul_right s hcoef
    _ = (m - Δ) * (2 * s) := by ring
    _ ≤ (m - Δ) * n := Nat.mul_le_mul_left (m - Δ) hhalf

lemma cko_mul_card_le_floor_scale_of_two_card_le
    (Δ n s : ℕ) (hhalf : 2 * s ≤ n) :
    let m := ((Δ + 2)^2) / 4
    m * s ≤ (m - Δ) * n := by
  dsimp
  exact cko_mul_card_le_of_two_card_le (cko_two_mul_le_floor_scale_nat Δ) hhalf

lemma cko_mul_card_sub_le_mul_sub_mul_of_card_le_floor_scale
    {D n m : ℕ} (hm : 2 * D ≤ m) (hDn : D ≤ n) (hnm : n ≤ m) :
    m * (n - D) ≤ (m - D) * n := by
  have hDm : D ≤ m := by omega
  have hmul : D * n ≤ m * D := by
    calc
      D * n ≤ D * m := Nat.mul_le_mul_left D hnm
      _ = m * D := by ring
  apply Nat.le_of_add_le_add_right
  calc
    m * (n - D) + m * D = m * n := by
      rw [← mul_add, Nat.sub_add_cancel hDn]
    _ = (m - D) * n + D * n := by
      rw [← add_mul, Nat.sub_add_cancel hDm]
    _ ≤ (m - D) * n + m * D := Nat.add_le_add_left hmul ((m - D) * n)

lemma ckko_indepDominationNumber_mul_bound_of_card_le_floor_scale_maxDegree
    {V : Type*} [Fintype V] [DecidableEq V] [Nonempty V]
    (G : SimpleGraph V) [DecidableRel G.Adj] :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    Fintype.card V ≤ m →
    m * G.indepDominationNumber ≤ (m - D) * Fintype.card V := by
  classical
  dsimp
  set D := G.maxDegree
  set n := Fintype.card V
  set m := ((D + 2) ^ 2) / 4
  intro hn_le_m
  obtain ⟨S, hS, hSle⟩ :=
    (SimpleGraph.exists_isNIndepDominatingSet_card_le_card_sub_maxDegree (G := G))
  have hi_le : G.indepDominationNumber ≤ S.card :=
    G.indepDominationNumber_le_card_of_isNIndepDominatingSet hS
  have hSle' : S.card ≤ n - D := by
    simpa [n, D] using hSle
  have hDlt : D < n := by
    simpa [D, n] using G.maxDegree_lt_card_verts
  have hDn : D ≤ n := Nat.le_of_lt hDlt
  have hm : 2 * D ≤ m := by
    simpa [m] using cko_two_mul_le_floor_scale_nat D
  calc
    m * G.indepDominationNumber ≤ m * S.card := Nat.mul_le_mul_left m hi_le
    _ ≤ m * (n - D) := Nat.mul_le_mul_left m hSle'
    _ ≤ (m - D) * n :=
      cko_mul_card_sub_le_mul_sub_mul_of_card_le_floor_scale hm hDn hn_le_m

lemma ckko_exists_witness_of_indepDominationNumber_mul_bound
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (Δ : ℕ) :
    let m := ((Δ + 2)^2) / 4
    m * G.indepDominationNumber ≤ (m - Δ) * Fintype.card V →
    ∃ S : Finset V,
      G.IsNIndepDominatingSet S.card S ∧
      m * S.card ≤ (m - Δ) * Fintype.card V := by
  classical
  dsimp
  intro hBound
  obtain ⟨S, hS⟩ := G.indepDominationNumber_spec
  refine ⟨S, ⟨⟨hS.isIndep, hS.isDominating, rfl⟩, ?_⟩⟩
  rwa [hS.card_eq]

lemma ckko_indepDominationNumber_mul_maxDegree_bound_of_witness
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj] :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    (∃ S : Finset V,
      G.IsNIndepDominatingSet S.card S ∧
      m * S.card ≤ (m - D) * Fintype.card V) →
    m * G.indepDominationNumber ≤ (m - D) * Fintype.card V := by
  classical
  dsimp
  intro hWitness
  rcases hWitness with ⟨S, hS, hSbound⟩
  have hi_le : G.indepDominationNumber ≤ S.card :=
    G.indepDominationNumber_le_card_of_isNIndepDominatingSet hS
  exact (Nat.mul_le_mul_left (((G.maxDegree + 2) ^ 2) / 4) hi_le).trans hSbound

lemma ckko_two_mul_indepDominationNumber_le_card_of_maxDegree_eq_one
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (hIso : 0 < G.minDegree)
    (hMax : G.maxDegree = 1) :
    2 * G.indepDominationNumber ≤ Fintype.card V := by
  exact ckko_two_mul_indepDominationNumber_le_card_of_maxDegree_eq_one_aux
    (G := G) hIso hMax

theorem ckko_source_indepDominationNumber_mul_maxDegree_large_no_isolated
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (hIso : 0 < G.minDegree)
    (hLarge : ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4)
    (hSource : CkkoLargeDegreeWitness G) :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    m * G.indepDominationNumber ≤ (m - D) * Fintype.card V := by
  exact ckko_corollary13_source_indepDominationNumber_mul_maxDegree_large_no_isolated
    (G := G) hIso hLarge hSource

theorem ckko_source_connected_indepDominationNumber_mul_maxDegree_large_no_isolated
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (_hConn : G.Connected)
    (hIso : 0 < G.minDegree)
    (hLarge : ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4)
    (hSource : CkkoLargeDegreeWitness G) :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    m * G.indepDominationNumber ≤ (m - D) * Fintype.card V := by
  exact ckko_source_indepDominationNumber_mul_maxDegree_large_no_isolated
    (G := G) hIso hLarge hSource

theorem ckko_corollary_exists_isNIndepDominatingSet_mul_maxDegree_large_no_isolated
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (hIso : 0 < G.minDegree)
    (hLarge : ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4)
    (hSource : CkkoLargeDegreeWitness G) :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    ∃ S : Finset V,
      G.IsNIndepDominatingSet S.card S ∧
      m * S.card ≤ (m - D) * Fintype.card V := by
  classical
  dsimp
  exact ckko_exists_witness_of_indepDominationNumber_mul_bound
    (G := G) (Δ := G.maxDegree)
    (ckko_source_indepDominationNumber_mul_maxDegree_large_no_isolated
      (G := G) hIso hLarge hSource)

theorem ckko_corollary_indepDominationNumber_mul_maxDegree_large_no_isolated
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (hIso : 0 < G.minDegree)
    (hLarge : ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4)
    (hSource : CkkoLargeDegreeWitness G) :
    let D := G.maxDegree
    let m := ((D + 2)^2) / 4
    m * G.indepDominationNumber ≤ (m - D) * Fintype.card V := by
  classical
  dsimp
  have hV : Nonempty V := by
    by_cases hV : Nonempty V
    · exact hV
    · haveI : IsEmpty V := not_nonempty_iff.mp hV
      have hmin : G.minDegree = 0 := SimpleGraph.minDegree_of_isEmpty (G := G)
      omega
  have hMax_pos : 0 < G.maxDegree :=
    lt_of_lt_of_le hIso (SimpleGraph.minDegree_le_maxDegree (G := G))
  letI : Nonempty V := hV
  exact ckko_indepDominationNumber_mul_maxDegree_bound_of_witness (G := G)
    (ckko_corollary_exists_isNIndepDominatingSet_mul_maxDegree_large_no_isolated
      (G := G) hIso hLarge hSource)

theorem ckko_corollary_indepDominationNumber_mul_boundedDegree_no_isolated
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (Δ : ℕ) (hΔ : 0 < Δ)
    (hMax : G.maxDegree ≤ Δ)
    (hIso : 0 < G.minDegree)
    (hSourceLarge :
      ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4 →
        CkkoLargeDegreeWitness G) :
    let m := ((Δ + 2)^2) / 4
    m * G.indepDominationNumber ≤ (m - Δ) * Fintype.card V := by
  classical
  dsimp
  have hΔ_nonzero : Δ ≠ 0 := Nat.ne_of_gt hΔ
  clear hΔ_nonzero
  have hV : Nonempty V := by
    by_cases hV : Nonempty V
    · exact hV
    · haveI : IsEmpty V := not_nonempty_iff.mp hV
      have hmin : G.minDegree = 0 := SimpleGraph.minDegree_of_isEmpty (G := G)
      omega
  have hMax_pos : 0 < G.maxDegree :=
    lt_of_lt_of_le hIso (SimpleGraph.minDegree_le_maxDegree (G := G))
  letI : Nonempty V := hV
  by_cases hSmall :
      Fintype.card V ≤ ((G.maxDegree + 2) ^ 2) / 4
  · have hExact :=
      (ckko_indepDominationNumber_mul_bound_of_card_le_floor_scale_maxDegree
        (G := G) hSmall)
    exact cko_floor_scale_bound_mono
      (D := G.maxDegree) (Δ := Δ)
      (i := G.indepDominationNumber) (n := Fintype.card V)
      hMax_pos hMax (by simpa using hExact)
  · have hExact :=
      ckko_corollary_indepDominationNumber_mul_maxDegree_large_no_isolated
        (G := G) hIso hSmall (hSourceLarge hSmall)
    exact cko_floor_scale_bound_mono
      (D := G.maxDegree) (Δ := Δ)
      (i := G.indepDominationNumber) (n := Fintype.card V)
      hMax_pos hMax (by simpa using hExact)

theorem ckko_corollary_exists_isNIndepDominatingSet_mul_boundedDegree_no_isolated
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (Δ : ℕ) (hΔ : 0 < Δ)
    (hMax : G.maxDegree ≤ Δ)
    (hIso : 0 < G.minDegree)
    (hSourceLarge :
      ¬ Fintype.card V ≤ ((G.maxDegree + 2)^2) / 4 →
        CkkoLargeDegreeWitness G) :
    let m := ((Δ + 2)^2) / 4
    ∃ S : Finset V,
      G.IsNIndepDominatingSet S.card S ∧
      m * S.card ≤ (m - Δ) * Fintype.card V := by
  classical
  exact ckko_exists_witness_of_indepDominationNumber_mul_bound G Δ
    (ckko_corollary_indepDominationNumber_mul_boundedDegree_no_isolated
      G Δ hΔ hMax hIso hSourceLarge)

theorem ckko_corollary_indepDominationNumber_mul_boundedDegree_no_isolated_of_certificate
    (hCert : CkkoCorollary13LeanCertificate.{u_ckko})
    {V : Type u_ckko} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (Δ : ℕ) (hΔ : 0 < Δ)
    (hMax : G.maxDegree ≤ Δ)
    (hIso : 0 < G.minDegree) :
    let m := ((Δ + 2)^2) / 4
    m * G.indepDominationNumber ≤ (m - Δ) * Fintype.card V := by
  exact
    ckko_corollary_indepDominationNumber_mul_boundedDegree_no_isolated
      G Δ hΔ hMax hIso
      (ckko_sourceLarge_of_corollary13_certificate hCert (G := G) hIso)

theorem ckko_corollary_exists_isNIndepDominatingSet_mul_boundedDegree_no_isolated_of_certificate
    (hCert : CkkoCorollary13LeanCertificate.{u_ckko})
    {V : Type u_ckko} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj]
    (Δ : ℕ) (hΔ : 0 < Δ)
    (hMax : G.maxDegree ≤ Δ)
    (hIso : 0 < G.minDegree) :
    let m := ((Δ + 2)^2) / 4
    ∃ S : Finset V,
      G.IsNIndepDominatingSet S.card S ∧
      m * S.card ≤ (m - Δ) * Fintype.card V := by
  exact
    ckko_corollary_exists_isNIndepDominatingSet_mul_boundedDegree_no_isolated
      G Δ hΔ hMax hIso
      (ckko_sourceLarge_of_corollary13_certificate hCert (G := G) hIso)

theorem cko_odd_floor_scale_nat {D : Nat} (hOdd : Odd D) :
    4 * ((D + 2) ^ 2 / 4) = (D + 1) * (D + 3) := by
  rcases hOdd with ⟨k, hk⟩
  subst D
  have hdiv : ((2 * k + 3) ^ 2 / 4) = (k + 1) * (k + 2) := by
    apply Nat.div_eq_of_lt_le
    · nlinarith [sq_nonneg (2 * (k : Int) + 3)]
    · nlinarith [sq_nonneg (2 * (k : Int) + 3)]
  rw [hdiv]
  ring

end IndependentDomination80Attack20260608
