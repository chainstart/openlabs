import Mathlib.NumberTheory.ArithmeticFunction.Carmichael

/-!
Reusable Korselt-criterion formalization extracted from the ARA
`korselt-criterion-campaign-20260430` project.

This module packages the local Fermat-style Carmichael-number predicate, the
bridge to `ArithmeticFunction.Carmichael`, squarefreeness extraction, and the
project-facing classical Korselt criterion.
-/

namespace AraLibrary

open scoped ArithmeticFunction.Carmichael

/--
Project-facing Carmichael-number predicate.

The side conditions `1 < n` and `¬ n.Prime` are kept explicit so downstream
uses do not drift into the easier `λ n ∣ n - 1` variant.
-/
def IsCarmichaelNumber (n : ℕ) : Prop :=
  1 < n ∧ ¬ n.Prime ∧ ∀ a, Nat.Coprime a n → a ^ (n - 1) ≡ 1 [MOD n]

/--
The Carmichael function of `n` divides `n - 1`.
-/
def CarmichaelDividesSubOne (n : ℕ) : Prop :=
  ArithmeticFunction.Carmichael n ∣ n - 1

/--
Prime-divisor conclusion in Korselt's criterion.
-/
def PrimeSubOneDividesSubOne (n : ℕ) : Prop :=
  ∀ p ∈ n.primeFactors, p - 1 ∣ n - 1

/--
Prime-power checkpoint imported from the Carmichael factorization formula:
if `λ n ∣ n - 1`, then every prime-power component of `n` has Carmichael value
dividing `n - 1`.
-/
theorem korselt_criterion_lemmas {n p : ℕ} [NeZero n]
    (hCarmichael : CarmichaelDividesSubOne n)
    (hp : p ∈ n.primeFactors) :
    ArithmeticFunction.Carmichael (p ^ n.factorization p) ∣ n - 1 := by
  have hComponent : ArithmeticFunction.Carmichael (p ^ n.factorization p) ∣
      ArithmeticFunction.Carmichael n := by
    rw [ArithmeticFunction.carmichael_factorization n]
    exact Finset.dvd_lcm hp
  exact dvd_trans hComponent hCarmichael

/--
Squarefree-specialized forward bridge: under `λ n ∣ n - 1`, each prime divisor
of a squarefree `n` satisfies the Korselt prime-divisor condition.
-/
theorem prime_subone_of_squarefree_carmichael_divides {n : ℕ} [NeZero n]
    (hsq : Squarefree n)
    (hCarmichael : CarmichaelDividesSubOne n) :
    PrimeSubOneDividesSubOne n := by
  intro p hp
  have hpp : p.Prime := Nat.prime_of_mem_primeFactors hp
  have hpow : n.factorization p = 1 :=
    Nat.factorization_eq_one_of_squarefree hsq hpp (Nat.dvd_of_mem_primeFactors hp)
  by_cases hp2 : p = 2
  · subst hp2
    simp
  · have hPrimePower := korselt_criterion_lemmas (n := n) (p := p) hCarmichael hp
    rw [hpow, ArithmeticFunction.carmichael_pow_of_prime_ne_two (p := p) 1 hpp hp2, pow_one,
      Nat.totient_prime hpp] at hPrimePower
    simpa using hPrimePower

/--
Converse squarefree-specialized bridge. Under the prime-divisor condition in
Korselt's criterion, every prime-power Carmichael component divides `n - 1`, so
their lcm, `ArithmeticFunction.Carmichael n`, divides `n - 1`.
-/
theorem carmichael_divides_of_squarefree_prime_subone {n : ℕ} [NeZero n]
    (hsq : Squarefree n)
    (hPrimeDivides : PrimeSubOneDividesSubOne n) :
    CarmichaelDividesSubOne n := by
  unfold CarmichaelDividesSubOne
  rw [ArithmeticFunction.carmichael_factorization n]
  refine Finset.lcm_dvd ?_
  intro p hp
  have hpp : p.Prime := Nat.prime_of_mem_primeFactors hp
  have hpow : n.factorization p = 1 :=
    Nat.factorization_eq_one_of_squarefree hsq hpp (Nat.dvd_of_mem_primeFactors hp)
  by_cases hp2 : p = 2
  · subst hp2
    rw [hpow]
    have hlambda_two_pow : ArithmeticFunction.Carmichael (2 ^ 1) = 1 := by
      simpa using (ArithmeticFunction.carmichael_two_pow_of_le_two (n := 1) (by decide))
    rw [hlambda_two_pow]
    exact one_dvd _
  · rw [hpow, ArithmeticFunction.carmichael_pow_of_prime_ne_two (p := p) 1 hpp hp2,
      pow_one, Nat.totient_prime hpp]
    exact hPrimeDivides p hp

/--
For squarefree `n`, the Carmichael-function divisibility formulation is
equivalent to the prime-divisor formulation in Korselt's criterion.
-/
theorem carmichael_divides_subone_iff_prime_subone_of_squarefree {n : ℕ} [NeZero n]
    (hsq : Squarefree n) :
    CarmichaelDividesSubOne n ↔ PrimeSubOneDividesSubOne n := by
  constructor
  · exact prime_subone_of_squarefree_carmichael_divides hsq
  · exact carmichael_divides_of_squarefree_prime_subone hsq

/--
Forward bridge from the Fermat-style Carmichael predicate to Carmichael-function
divisibility, expressed through `ArithmeticFunction.carmichael_eq_exponent`.
-/
theorem carmichael_divides_subone_of_isCarmichaelNumber {n : ℕ} [NeZero n]
    (h : IsCarmichaelNumber n) :
    CarmichaelDividesSubOne n := by
  rcases h with ⟨hn_gt_one, _hnotprime, hpow⟩
  unfold CarmichaelDividesSubOne
  rw [ArithmeticFunction.carmichael_eq_exponent (n := n) (NeZero.ne n)]
  refine Monoid.exponent_dvd_of_forall_pow_eq_one ?_
  intro u
  apply Units.ext
  change ((u : ZMod n) ^ (n - 1) = 1)
  let a : ℕ := u.1.val
  have hu : ((a : ℕ) : ZMod n) = (u : ZMod n) := by
    simpa [a] using (ZMod.natCast_zmod_val (a := (u : ZMod n)))
  have haisunit : IsUnit ((a : ℕ) : ZMod n) := by
    rw [hu]
    exact u.isUnit
  have hcop : Nat.Coprime a n := (ZMod.isUnit_iff_coprime a n).mp haisunit
  have hmod : a ^ (n - 1) ≡ 1 [MOD n] := hpow a hcop
  have ha_pos : 0 < a := by
    apply Nat.pos_of_ne_zero
    intro ha_zero
    have hn_eq_one : n = 1 := by
      rw [ha_zero] at hcop
      exact (Nat.coprime_zero_left n).mp hcop
    omega
  have hpow_ge : 1 ≤ a ^ (n - 1) :=
    Nat.succ_le_of_lt (pow_pos ha_pos _)
  have hsub : a ^ (n - 1) - 1 ≡ 0 [MOD n] := by
    simpa using Nat.ModEq.sub_right (a := 1) hpow_ge (by decide : 1 ≤ 1) hmod
  have hz : ((((a ^ (n - 1)) - 1 : ℕ) : ZMod n) = 0) := by
    exact (ZMod.natCast_eq_zero_iff _ _).2 (Nat.modEq_zero_iff_dvd.mp hsub)
  rw [← hu]
  rw [Nat.cast_sub hpow_ge] at hz
  simpa using sub_eq_zero.mp hz

/--
Forward squarefreeness extraction. If a prime square divided `n`, then the
corresponding prime-power Carmichael component would also divide `n - 1`,
forcing the same prime to divide both `n` and `n - 1`.
-/
theorem squarefree_of_carmichael_divides_subone {n : ℕ} [NeZero n]
    (hn_gt_one : 1 < n)
    (hdiv : CarmichaelDividesSubOne n) :
    Squarefree n := by
  rw [Nat.squarefree_iff_factorization_le_one (NeZero.ne n)]
  intro p
  by_cases hpp : p.Prime
  · by_contra hnotle
    have hfac_ge_two : 2 ≤ n.factorization p := by omega
    have hcop_consecutive : Nat.Coprime n (n - 1) := by
      rw [Nat.coprime_self_sub_right (m := 1) (n := n) (Nat.one_le_of_lt hn_gt_one)]
      simp
    have hp_dvd_n : p ∣ n :=
      hpp.dvd_iff_one_le_factorization (NeZero.ne n) |>.2 (by omega)
    have hp_mem : p ∈ n.primeFactors := by
      exact Nat.mem_primeFactors.2 ⟨hpp, hp_dvd_n, NeZero.ne n⟩
    have hcomp := korselt_criterion_lemmas (n := n) (p := p) hdiv hp_mem
    by_cases hp2 : p = 2
    · subst hp2
      have htwo_dvd_lambda : 2 ∣ ArithmeticFunction.Carmichael (2 ^ n.factorization 2) := by
        by_cases hfac_eq_two : n.factorization 2 = 2
        · rw [hfac_eq_two, ArithmeticFunction.carmichael_two_pow_of_le_two (n := 2) (by decide)]
          simp
        · have hfac_ge_three : 3 ≤ n.factorization 2 := by omega
          rw [ArithmeticFunction.carmichael_two_pow_of_ne_two (n := n.factorization 2) hfac_eq_two]
          exact dvd_pow_self 2 (by omega)
      have htwo_dvd_nm1 : 2 ∣ n - 1 := dvd_trans htwo_dvd_lambda hcomp
      have htwo_eq_one : 2 = 1 := Nat.eq_one_of_dvd_coprimes hcop_consecutive hp_dvd_n htwo_dvd_nm1
      exact Nat.prime_two.ne_one htwo_eq_one
    · have hfac_pos : 0 < n.factorization p := by omega
      have hp_dvd_lambda : p ∣ ArithmeticFunction.Carmichael (p ^ n.factorization p) := by
        rw [ArithmeticFunction.carmichael_pow_of_prime_ne_two (p := p) (n := n.factorization p) hpp hp2,
          Nat.totient_prime_pow hpp hfac_pos]
        exact dvd_mul_of_dvd_left (dvd_pow_self p (by omega)) (p - 1)
      have hp_dvd_nm1 : p ∣ n - 1 := dvd_trans hp_dvd_lambda hcomp
      exact hpp.ne_one (Nat.eq_one_of_dvd_coprimes hcop_consecutive hp_dvd_n hp_dvd_nm1)
  · simp [Nat.factorization_eq_zero_of_not_prime _ hpp]

/--
Forward squarefreeness extraction specialized to the Fermat-style Carmichael
predicate.
-/
theorem squarefree_of_isCarmichaelNumber {n : ℕ} [NeZero n]
    (h : IsCarmichaelNumber n) :
    Squarefree n := by
  exact squarefree_of_carmichael_divides_subone h.1
    (carmichael_divides_subone_of_isCarmichaelNumber h)

/--
Converse bridge: once the Carmichael exponent of `(ZMod n)ˣ` divides `n - 1`,
the universal Fermat-style congruence follows for every base coprime to `n`.
-/
theorem isCarmichaelNumber_of_nonprime_carmichael_divides_subone {n : ℕ} [NeZero n]
    (hn_gt_one : 1 < n)
    (hnotprime : ¬ n.Prime)
    (hdiv : CarmichaelDividesSubOne n) :
    IsCarmichaelNumber n := by
  refine ⟨hn_gt_one, hnotprime, ?_⟩
  intro a hcop
  unfold CarmichaelDividesSubOne at hdiv
  rw [ArithmeticFunction.carmichael_eq_exponent (n := n) (NeZero.ne n)] at hdiv
  have hpowUnits : ∀ u : (ZMod n)ˣ, u ^ (n - 1) = 1 :=
    (Monoid.exponent_dvd_iff_forall_pow_eq_one).mp hdiv
  rw [← ZMod.natCast_eq_natCast_iff]
  have hu : ((ZMod.unitOfCoprime a hcop : (ZMod n)ˣ) ^ (n - 1) : (ZMod n)ˣ) = 1 :=
    hpowUnits (ZMod.unitOfCoprime a hcop)
  apply_fun (fun u : (ZMod n)ˣ => (u : ZMod n)) at hu
  simpa only [Nat.cast_pow, Nat.cast_one, Units.val_one, Units.val_pow_eq_pow_val,
    ZMod.coe_unitOfCoprime] using hu

/--
Squarefree converse packaging toward Korselt's criterion.
-/
theorem isCarmichaelNumber_of_squarefree_prime_subone {n : ℕ} [NeZero n]
    (hn_gt_one : 1 < n)
    (hnotprime : ¬ n.Prime)
    (hsq : Squarefree n)
    (hPrimeDivides : PrimeSubOneDividesSubOne n) :
    IsCarmichaelNumber n := by
  exact isCarmichaelNumber_of_nonprime_carmichael_divides_subone hn_gt_one hnotprime
    (carmichael_divides_of_squarefree_prime_subone hsq hPrimeDivides)

/--
The squarefree lambda-function bridge behind Korselt's criterion.
-/
theorem korselt_criterion_squarefree_lambda_bridge {n : ℕ} [NeZero n]
    (hsq : Squarefree n) :
    CarmichaelDividesSubOne n ↔ PrimeSubOneDividesSubOne n := by
  exact carmichael_divides_subone_iff_prime_subone_of_squarefree hsq

/--
Project-level packaging of the predicate-to-`λ` bridge.
-/
theorem carmichael_predicate_implies_lambda_bridge {n : ℕ} [NeZero n]
    (hCarmichael : IsCarmichaelNumber n) :
    CarmichaelDividesSubOne n := by
  exact carmichael_divides_subone_of_isCarmichaelNumber hCarmichael

/--
Squarefree Korselt packaging.
-/
theorem korselt_criterion_main {n : ℕ} [NeZero n]
    (hn_gt_one : 1 < n)
    (hnotprime : ¬ n.Prime)
    (hsq : Squarefree n) :
    IsCarmichaelNumber n ↔ PrimeSubOneDividesSubOne n := by
  constructor
  · intro hCarmichael
    exact korselt_criterion_squarefree_lambda_bridge (n := n) hsq |>.mp
      (carmichael_predicate_implies_lambda_bridge hCarmichael)
  · intro hPrimeDivides
    exact isCarmichaelNumber_of_squarefree_prime_subone hn_gt_one hnotprime hsq hPrimeDivides

/--
Classical project-facing Korselt criterion: the Fermat-style Carmichael
predicate is equivalent to squarefreeness plus the prime-divisor condition,
assuming the explicit compositeness side conditions `1 < n` and `¬ n.Prime`.
-/
theorem korselt_criterion_classical {n : ℕ} [NeZero n]
    (hn_gt_one : 1 < n)
    (hnotprime : ¬ n.Prime) :
    IsCarmichaelNumber n ↔ Squarefree n ∧ PrimeSubOneDividesSubOne n := by
  constructor
  · intro hCarmichael
    refine ⟨squarefree_of_isCarmichaelNumber hCarmichael, ?_⟩
    exact korselt_criterion_main (n := n) hn_gt_one hnotprime
      (squarefree_of_isCarmichaelNumber hCarmichael) |>.mp hCarmichael
  · rintro ⟨hsq, hPrimeDivides⟩
    exact (korselt_criterion_main (n := n) hn_gt_one hnotprime hsq).2 hPrimeDivides

end AraLibrary
