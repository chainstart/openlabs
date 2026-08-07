import Mathlib.Analysis.SpecialFunctions.Log.Basic
import Mathlib.Analysis.SpecialFunctions.Log.Deriv
import Mathlib.Analysis.SpecialFunctions.Sqrt
import Mathlib.Analysis.SpecialFunctions.Trigonometric.Basic
import Mathlib.Analysis.Calculus.Deriv.Mul
import Mathlib.Analysis.Calculus.Deriv.Pow
import Mathlib.Analysis.Convex.Deriv
import Mathlib.MeasureTheory.Integral.IntervalIntegral.FundThmCalculus
import Mathlib.MeasureTheory.Integral.IntervalAverage

/-!
Lean side certificate for the public FrontierMath Tier 4 BMO probe.

The final declaration below exposes the original public benchmark as a
supremum over actual real functions on the unit interval. The remaining
Bellman upper bound and stopped-log/cup lower bound are isolated as
function-level propositions over those interval integrals.
-/

namespace AraLibrary.Analysis

noncomputable section

open MeasureTheory
open scoped Interval

theorem bmo_contact_exponent_identity
    (s : ℝ) (hs : s ^ 2 = 3) (hs0 : s ≠ 0) :
    (10 + s / 36) / (s / 6) = 20 * s + (1 / 6 : ℝ) := by
  have hden : s / 6 ≠ 0 := div_ne_zero hs0 (by norm_num)
  apply mul_right_cancel₀ hden
  calc
    ((10 + s / 36) / (s / 6)) * (s / 6) = 10 + s / 36 := by
      exact div_mul_cancel₀ _ hden
    _ = (20 * s + (1 / 6 : ℝ)) * (s / 6) := by
      calc
        10 + s / 36 = (10 / 3) * s ^ 2 + s / 36 := by rw [hs]; norm_num
        _ = (20 * s + (1 / 6 : ℝ)) * (s / 6) := by ring

theorem bmo_contact_cubic_identity
    (s : ℝ) (hs : s ^ 2 = 3) :
    2 * (s / 6) ^ 3 = s / 36 := by
  have hs3 : s ^ 3 = 3 * s := by
    calc
      s ^ 3 = s * s ^ 2 := by ring
      _ = s * 3 := by rw [hs]
      _ = 3 * s := by ring
  calc
    2 * (s / 6) ^ 3 = s ^ 3 / 108 := by ring
    _ = (3 * s) / 108 := by rw [hs3]
    _ = s / 36 := by ring

theorem bmo_contact_value_identity
    (s : ℝ) (hs : s ^ 2 = 3) (hs0 : s ≠ 0) :
    2 * (s / 6) ^ 3 + (s / 6) * Real.exp (-((10 + s / 36) / (s / 6))) =
      s / 36 + (s / 6) * Real.exp (-(20 * s + (1 / 6 : ℝ))) := by
  rw [bmo_contact_cubic_identity s hs, bmo_contact_exponent_identity s hs hs0]

def frontierBMOPublicAnswer : ℝ :=
  1 / (12 * Real.sqrt 3) +
    (Real.sqrt 3 / 6) * Real.exp (-(20 * Real.sqrt 3 + (1 / 6 : ℝ)))

def frontierBMOOriginalSupremumValue : ℝ :=
  frontierBMOPublicAnswer - (1985 / 2 : ℝ)

def frontierBMOOriginalMeanIntegral (f : ℝ → ℝ) : ℝ :=
  ∫ t in (0 : ℝ)..1, f t

def frontierBMOOriginalSecondMomentIntegral (f : ℝ → ℝ) : ℝ :=
  ∫ t in (0 : ℝ)..1, (f t) ^ 2

def frontierBMOOriginalObjectiveIntegral (f : ℝ → ℝ) : ℝ :=
  ∫ t in (0 : ℝ)..1, (f t) ^ 3 + |f t|

def frontierBMOIntervalMean (f : ℝ → ℝ) (a b : ℝ) : ℝ :=
  (∫ t in a..b, f t) / (b - a)

def frontierBMOIntervalVariance (f : ℝ → ℝ) (a b : ℝ) : ℝ :=
  (∫ t in a..b, (f t - frontierBMOIntervalMean f a b) ^ 2) / (b - a)

def frontierBMOOriginalFunctionAdmissible (f : ℝ → ℝ) : Prop :=
  IntervalIntegrable f volume (0 : ℝ) 1 ∧
    IntervalIntegrable (fun t ↦ (f t) ^ 2) volume (0 : ℝ) 1 ∧
    IntervalIntegrable (fun t ↦ (f t) ^ 3 + |f t|) volume (0 : ℝ) 1 ∧
    frontierBMOOriginalMeanIntegral f = -10 ∧
    frontierBMOOriginalSecondMomentIntegral f = 100 + (1 / 12 : ℝ) ∧
    ∀ a b : ℝ, 0 ≤ a → a < b → b ≤ 1 →
      IntervalIntegrable
          (fun t ↦ (f t - frontierBMOIntervalMean f a b) ^ 2) volume a b ∧
        frontierBMOIntervalVariance f a b ≤ (1 / 12 : ℝ)

def frontierBMOOriginalFunctionObjectiveSet : Set ℝ :=
  {y : ℝ | ∃ f : ℝ → ℝ,
    frontierBMOOriginalFunctionAdmissible f ∧
      y = frontierBMOOriginalObjectiveIntegral f}

def frontierBMOOriginalFunctionSupremum : ℝ :=
  sSup frontierBMOOriginalFunctionObjectiveSet

def frontierBMOOriginalFunctionBenchmarkValue : ℝ :=
  frontierBMOOriginalFunctionSupremum + (1985 / 2 : ℝ)

def frontierBMOOriginalActualUpperBound : Prop :=
  ∀ y ∈ frontierBMOOriginalFunctionObjectiveSet, y ≤ frontierBMOOriginalSupremumValue

def frontierStoppedLogCupActualLowerBound : Prop :=
  frontierBMOOriginalSupremumValue ∈ frontierBMOOriginalFunctionObjectiveSet

theorem frontierBMOOriginalFunctionBenchmarkValue_eq_publicAnswer_iff :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer ↔
      frontierBMOOriginalFunctionSupremum = frontierBMOOriginalSupremumValue := by
  constructor
  · intro h
    rw [frontierBMOOriginalFunctionBenchmarkValue] at h
    rw [frontierBMOOriginalSupremumValue]
    linarith
  · intro h
    rw [frontierBMOOriginalFunctionBenchmarkValue, h, frontierBMOOriginalSupremumValue]
    ring

theorem frontier_bmo_public_sample_original_unconditional_supremum_iff :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer ↔
      frontierBMOOriginalFunctionSupremum = frontierBMOOriginalSupremumValue :=
  frontierBMOOriginalFunctionBenchmarkValue_eq_publicAnswer_iff

theorem frontierBMOOriginalFunctionSupremum_eq_value_of_actual_bounds
    (frontier_unboundedNonsmoothBellmanUpper :
      frontierBMOOriginalActualUpperBound)
    (frontier_stoppedLogCupOptimizerLower :
      frontierStoppedLogCupActualLowerBound) :
    frontierBMOOriginalFunctionSupremum = frontierBMOOriginalSupremumValue := by
  have hnonempty : frontierBMOOriginalFunctionObjectiveSet.Nonempty :=
    ⟨frontierBMOOriginalSupremumValue, frontier_stoppedLogCupOptimizerLower⟩
  have hbdd : BddAbove frontierBMOOriginalFunctionObjectiveSet :=
    ⟨frontierBMOOriginalSupremumValue, frontier_unboundedNonsmoothBellmanUpper⟩
  have hsup_le :
      frontierBMOOriginalFunctionSupremum ≤ frontierBMOOriginalSupremumValue :=
    csSup_le hnonempty frontier_unboundedNonsmoothBellmanUpper
  have hle_sup :
      frontierBMOOriginalSupremumValue ≤ frontierBMOOriginalFunctionSupremum :=
    le_csSup hbdd frontier_stoppedLogCupOptimizerLower
  exact le_antisymm hsup_le hle_sup

theorem bmo_public_answer_contact_form :
    frontierBMOPublicAnswer =
      2 * (Real.sqrt 3 / 6) ^ 3 +
        (Real.sqrt 3 / 6) *
          Real.exp (-((10 + Real.sqrt 3 / 36) / (Real.sqrt 3 / 6))) := by
  have hs_nonneg : 0 ≤ (3 : ℝ) := by norm_num
  have hs : (Real.sqrt 3) ^ 2 = (3 : ℝ) := Real.sq_sqrt hs_nonneg
  have hs0 : Real.sqrt 3 ≠ 0 := Real.sqrt_ne_zero'.2 (by norm_num)
  have hcubic : 2 * (Real.sqrt 3 / 6) ^ 3 = 1 / (12 * Real.sqrt 3) := by
    calc
      2 * (Real.sqrt 3 / 6) ^ 3 = Real.sqrt 3 / 36 :=
        bmo_contact_cubic_identity (Real.sqrt 3) hs
      _ = 1 / (12 * Real.sqrt 3) := by
        apply mul_right_cancel₀ hs0
        calc
          (Real.sqrt 3 / 36) * Real.sqrt 3 = (Real.sqrt 3 ^ 2) / 36 := by ring
          _ = 3 / 36 := by rw [hs]
          _ = (1 / (12 * Real.sqrt 3)) * Real.sqrt 3 := by
            field_simp [hs0]
            norm_num
  rw [frontierBMOPublicAnswer, hcubic,
    bmo_contact_exponent_identity (Real.sqrt 3) hs hs0]

/-!
The following definitions are the current proof-obligation scaffold for the
piecewise Bellman candidate produced by the blocker-driven BMO loop. They do
not assert the missing global majorant theorem; they name the payoff, strip,
candidate pieces, and the precise right-tail obstruction for later proof.
-/

def frontierEpsilon : ℝ :=
  Real.sqrt 3 / 6

def frontierA : ℝ :=
  10

def frontierCStar : ℝ :=
  frontierA + 2 * frontierEpsilon ^ 3

def frontierPhi (t : ℝ) : ℝ :=
  t ^ 3 + 2 * max (t - frontierA) 0

def frontierBMOCenteredObjectiveIntegral (g : ℝ → ℝ) : ℝ :=
  ∫ t in (0 : ℝ)..1, frontierPhi (g t)

def frontierBMOCenteredFunctionAdmissible (g : ℝ → ℝ) : Prop :=
  IntervalIntegrable g volume (0 : ℝ) 1 ∧
    IntervalIntegrable (fun t ↦ (g t) ^ 2) volume (0 : ℝ) 1 ∧
    IntervalIntegrable (fun t ↦ frontierPhi (g t)) volume (0 : ℝ) 1 ∧
    frontierBMOOriginalMeanIntegral g = 0 ∧
    frontierBMOOriginalSecondMomentIntegral g = (1 / 12 : ℝ) ∧
    ∀ a b : ℝ, 0 ≤ a → a < b → b ≤ 1 →
      IntervalIntegrable
          (fun t ↦ (g t - frontierBMOIntervalMean g a b) ^ 2) volume a b ∧
        frontierBMOIntervalVariance g a b ≤ (1 / 12 : ℝ)

def frontierBMOCenteredFunctionObjectiveSet : Set ℝ :=
  {y : ℝ | ∃ g : ℝ → ℝ,
    frontierBMOCenteredFunctionAdmissible g ∧
      y = frontierBMOCenteredObjectiveIntegral g}

def frontierBMOCenteredFunctionSupremum : ℝ :=
  sSup frontierBMOCenteredFunctionObjectiveSet

theorem frontier_centered_objective_pointwise (g : ℝ) :
    (g - 10) ^ 3 + |g - 10| =
      frontierPhi g - 30 * g ^ 2 + 299 * g - 990 := by
  rw [frontierPhi, frontierA]
  by_cases h : 0 ≤ g - 10
  · rw [abs_of_nonneg h, max_eq_left h]
    ring
  · have hle : g - 10 ≤ 0 := le_of_not_ge h
    rw [abs_of_nonpos hle, max_eq_right hle]
    ring

theorem frontier_centering_constant_from_moments
    (objective centeredObjective mean secondMoment : ℝ)
    (hobjective :
      objective = centeredObjective - 30 * secondMoment + 299 * mean - 990)
    (hmean : mean = 0)
    (hsecondMoment : secondMoment = (1 / 12 : ℝ)) :
    objective = centeredObjective - (1985 / 2 : ℝ) := by
  rw [hobjective, hmean, hsecondMoment]
  ring

theorem frontier_centered_objective_integral_shift
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    (hg2 : IntervalIntegrable (fun t ↦ (g t) ^ 2) volume (0 : ℝ) 1)
    (hphi : IntervalIntegrable (fun t ↦ frontierPhi (g t)) volume (0 : ℝ) 1) :
    frontierBMOOriginalObjectiveIntegral (fun t ↦ g t - 10) =
      frontierBMOCenteredObjectiveIntegral g -
        30 * frontierBMOOriginalSecondMomentIntegral g +
        299 * frontierBMOOriginalMeanIntegral g - 990 := by
  have h30 :
      IntervalIntegrable (fun t ↦ 30 * (g t) ^ 2) volume (0 : ℝ) 1 :=
    hg2.const_mul 30
  have h299 :
      IntervalIntegrable (fun t ↦ 299 * g t) volume (0 : ℝ) 1 :=
    hg.const_mul 299
  have hmain :
      IntervalIntegrable
        (fun t ↦ (frontierPhi (g t) - 30 * (g t) ^ 2) + 299 * g t)
        volume (0 : ℝ) 1 :=
    (hphi.sub h30).add h299
  have hconst :
      IntervalIntegrable (fun _ : ℝ ↦ (990 : ℝ)) volume (0 : ℝ) 1 :=
    intervalIntegrable_const
  rw [frontierBMOOriginalObjectiveIntegral, frontierBMOCenteredObjectiveIntegral,
    frontierBMOOriginalSecondMomentIntegral, frontierBMOOriginalMeanIntegral]
  calc
    ∫ t in (0 : ℝ)..1, (g t - 10) ^ 3 + |g t - 10| =
        ∫ t in (0 : ℝ)..1,
          ((frontierPhi (g t) - 30 * (g t) ^ 2) + 299 * g t) - 990 := by
      apply intervalIntegral.integral_congr
      intro t _ht
      simpa using frontier_centered_objective_pointwise (g t)
    _ = (∫ t in (0 : ℝ)..1, frontierPhi (g t)) -
          30 * (∫ t in (0 : ℝ)..1, (g t) ^ 2) +
          299 * (∫ t in (0 : ℝ)..1, g t) - 990 := by
      rw [intervalIntegral.integral_sub hmain hconst]
      rw [intervalIntegral.integral_add (hphi.sub h30) h299]
      rw [intervalIntegral.integral_sub hphi h30]
      rw [intervalIntegral.integral_const_mul, intervalIntegral.integral_const_mul]
      rw [intervalIntegral.integral_const]
      norm_num

theorem frontier_centered_objective_integral_shift_of_moments
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    (hg2 : IntervalIntegrable (fun t ↦ (g t) ^ 2) volume (0 : ℝ) 1)
    (hphi : IntervalIntegrable (fun t ↦ frontierPhi (g t)) volume (0 : ℝ) 1)
    (hmean : frontierBMOOriginalMeanIntegral g = 0)
    (hsecondMoment : frontierBMOOriginalSecondMomentIntegral g = (1 / 12 : ℝ)) :
    frontierBMOOriginalObjectiveIntegral (fun t ↦ g t - 10) =
      frontierBMOCenteredObjectiveIntegral g - (1985 / 2 : ℝ) := by
  exact frontier_centering_constant_from_moments
    (frontierBMOOriginalObjectiveIntegral (fun t ↦ g t - 10))
    (frontierBMOCenteredObjectiveIntegral g)
    (frontierBMOOriginalMeanIntegral g)
    (frontierBMOOriginalSecondMomentIntegral g)
    (frontier_centered_objective_integral_shift g hg hg2 hphi)
    hmean hsecondMoment

theorem frontier_centered_objective_shift_mem_original_objectiveSet
    (g : ℝ → ℝ)
    (hshifted : frontierBMOOriginalFunctionAdmissible (fun t ↦ g t - 10))
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    (hg2 : IntervalIntegrable (fun t ↦ (g t) ^ 2) volume (0 : ℝ) 1)
    (hphi : IntervalIntegrable (fun t ↦ frontierPhi (g t)) volume (0 : ℝ) 1)
    (hmean : frontierBMOOriginalMeanIntegral g = 0)
    (hsecondMoment : frontierBMOOriginalSecondMomentIntegral g = (1 / 12 : ℝ)) :
    frontierBMOCenteredObjectiveIntegral g - (1985 / 2 : ℝ) ∈
      frontierBMOOriginalFunctionObjectiveSet := by
  refine ⟨fun t ↦ g t - 10, hshifted, ?_⟩
  exact (frontier_centered_objective_integral_shift_of_moments
    g hg hg2 hphi hmean hsecondMoment).symm

theorem frontier_centered_shift_intervalIntegrable
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1) :
    IntervalIntegrable (fun t ↦ g t - 10) volume (0 : ℝ) 1 := by
  exact hg.sub intervalIntegrable_const

theorem frontier_centered_shift_square_intervalIntegrable
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    (hg2 : IntervalIntegrable (fun t ↦ (g t) ^ 2) volume (0 : ℝ) 1) :
    IntervalIntegrable (fun t ↦ (g t - 10) ^ 2) volume (0 : ℝ) 1 := by
  have h20 : IntervalIntegrable (fun t ↦ 20 * g t) volume (0 : ℝ) 1 :=
    hg.const_mul 20
  have hpoly :
      IntervalIntegrable (fun t ↦ (g t) ^ 2 - 20 * g t + 100) volume (0 : ℝ) 1 :=
    (hg2.sub h20).add intervalIntegrable_const
  refine hpoly.congr ?_
  intro t _ht
  ring

theorem frontier_centered_shift_objective_intervalIntegrable
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    (hg2 : IntervalIntegrable (fun t ↦ (g t) ^ 2) volume (0 : ℝ) 1)
    (hphi : IntervalIntegrable (fun t ↦ frontierPhi (g t)) volume (0 : ℝ) 1) :
    IntervalIntegrable (fun t ↦ (g t - 10) ^ 3 + |g t - 10|)
      volume (0 : ℝ) 1 := by
  have h30 :
      IntervalIntegrable (fun t ↦ 30 * (g t) ^ 2) volume (0 : ℝ) 1 :=
    hg2.const_mul 30
  have h299 :
      IntervalIntegrable (fun t ↦ 299 * g t) volume (0 : ℝ) 1 :=
    hg.const_mul 299
  have hmain :
      IntervalIntegrable
        (fun t ↦ ((frontierPhi (g t) - 30 * (g t) ^ 2) + 299 * g t) - 990)
        volume (0 : ℝ) 1 :=
    ((hphi.sub h30).add h299).sub intervalIntegrable_const
  refine hmain.congr ?_
  intro t _ht
  simpa using (frontier_centered_objective_pointwise (g t)).symm

theorem frontier_centered_mean_integral_shift
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1) :
    frontierBMOOriginalMeanIntegral (fun t ↦ g t - 10) =
      frontierBMOOriginalMeanIntegral g - 10 := by
  have hconst :
      IntervalIntegrable (fun _ : ℝ ↦ (10 : ℝ)) volume (0 : ℝ) 1 :=
    intervalIntegrable_const
  rw [frontierBMOOriginalMeanIntegral]
  rw [intervalIntegral.integral_sub hg hconst]
  rw [intervalIntegral.integral_const]
  rw [frontierBMOOriginalMeanIntegral]
  norm_num

theorem frontier_centered_mean_integral_shift_of_centered_mean
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    (hmean : frontierBMOOriginalMeanIntegral g = 0) :
    frontierBMOOriginalMeanIntegral (fun t ↦ g t - 10) = -10 := by
  rw [frontier_centered_mean_integral_shift g hg, hmean]
  norm_num

theorem frontier_centered_second_moment_integral_shift
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    (hg2 : IntervalIntegrable (fun t ↦ (g t) ^ 2) volume (0 : ℝ) 1) :
    frontierBMOOriginalSecondMomentIntegral (fun t ↦ g t - 10) =
      frontierBMOOriginalSecondMomentIntegral g -
        20 * frontierBMOOriginalMeanIntegral g + 100 := by
  have h20 :
      IntervalIntegrable (fun t ↦ 20 * g t) volume (0 : ℝ) 1 :=
    hg.const_mul 20
  have hsum :
      IntervalIntegrable (fun t ↦ (g t) ^ 2 - 20 * g t) volume (0 : ℝ) 1 :=
    hg2.sub h20
  have hconst :
      IntervalIntegrable (fun _ : ℝ ↦ (100 : ℝ)) volume (0 : ℝ) 1 :=
    intervalIntegrable_const
  rw [frontierBMOOriginalSecondMomentIntegral, frontierBMOOriginalMeanIntegral]
  calc
    ∫ t in (0 : ℝ)..1, (g t - 10) ^ 2 =
        ∫ t in (0 : ℝ)..1, ((g t) ^ 2 - 20 * g t) + 100 := by
      apply intervalIntegral.integral_congr
      intro t _ht
      ring
    _ = (∫ t in (0 : ℝ)..1, (g t) ^ 2) -
          20 * (∫ t in (0 : ℝ)..1, g t) + 100 := by
      rw [intervalIntegral.integral_add hsum hconst]
      rw [intervalIntegral.integral_sub hg2 h20]
      rw [intervalIntegral.integral_const_mul]
      rw [intervalIntegral.integral_const]
      norm_num

theorem frontier_centered_second_moment_integral_shift_of_centered_moments
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    (hg2 : IntervalIntegrable (fun t ↦ (g t) ^ 2) volume (0 : ℝ) 1)
    (hmean : frontierBMOOriginalMeanIntegral g = 0)
    (hsecondMoment : frontierBMOOriginalSecondMomentIntegral g = (1 / 12 : ℝ)) :
    frontierBMOOriginalSecondMomentIntegral (fun t ↦ g t - 10) =
      100 + (1 / 12 : ℝ) := by
  rw [frontier_centered_second_moment_integral_shift g hg hg2, hmean, hsecondMoment]
  ring

theorem frontier_intervalIntegrable_on_subinterval_of_unit
    (g : ℝ → ℝ)
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    {a b : ℝ} (ha : 0 ≤ a) (hab : a < b) (hb : b ≤ 1) :
    IntervalIntegrable g volume a b := by
  exact hg.mono_set (by
    apply Set.uIcc_subset_uIcc
    · constructor
      · simpa using ha
      · have : a ≤ (1 : ℝ) := by linarith
        simpa using this
    · constructor
      · have : (0 : ℝ) ≤ b := by linarith
        simpa using this
      · simpa using hb)

theorem frontier_intervalMean_shift_sub
    (g : ℝ → ℝ) {a b : ℝ}
    (hg : IntervalIntegrable g volume a b) (hab : a < b) :
    frontierBMOIntervalMean (fun t ↦ g t - 10) a b =
      frontierBMOIntervalMean g a b - 10 := by
  have hconst :
      IntervalIntegrable (fun _ : ℝ ↦ (10 : ℝ)) volume a b :=
    intervalIntegrable_const
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalMean]
  rw [intervalIntegral.integral_sub hg hconst]
  rw [intervalIntegral.integral_const]
  rw [frontierBMOIntervalMean]
  simp only [smul_eq_mul]
  field_simp [hne]

theorem frontier_intervalVariance_shift_sub
    (g : ℝ → ℝ) {a b : ℝ}
    (hg : IntervalIntegrable g volume a b)
    (hvar :
      IntervalIntegrable
        (fun t ↦ (g t - frontierBMOIntervalMean g a b) ^ 2) volume a b)
    (hab : a < b) :
    IntervalIntegrable
        (fun t ↦
          ((g t - 10) - frontierBMOIntervalMean (fun t ↦ g t - 10) a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance (fun t ↦ g t - 10) a b =
        frontierBMOIntervalVariance g a b := by
  have hmean := frontier_intervalMean_shift_sub g hg hab
  have hvar_shift :
      IntervalIntegrable
        (fun t ↦
          ((g t - 10) - frontierBMOIntervalMean (fun t ↦ g t - 10) a b) ^ 2)
        volume a b := by
    refine hvar.congr ?_
    intro t _ht
    rw [hmean]
    ring
  refine ⟨hvar_shift, ?_⟩
  rw [frontierBMOIntervalVariance]
  apply congrArg (fun z : ℝ ↦ z / (b - a))
  apply intervalIntegral.integral_congr
  intro t _ht
  rw [hmean]
  ring

theorem frontier_centered_admissible_shift_variance
    (g : ℝ → ℝ)
    (hcentered : frontierBMOCenteredFunctionAdmissible g)
    {a b : ℝ} (ha : 0 ≤ a) (hab : a < b) (hb : b ≤ 1) :
    IntervalIntegrable
        (fun t ↦
          ((g t - 10) - frontierBMOIntervalMean (fun t ↦ g t - 10) a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance (fun t ↦ g t - 10) a b ≤ (1 / 12 : ℝ) := by
  rcases hcentered with ⟨hg, _hg2, _hphi, _hmean, _hsecondMoment, hvariance⟩
  have hgab : IntervalIntegrable g volume a b :=
    frontier_intervalIntegrable_on_subinterval_of_unit g hg ha hab hb
  rcases hvariance a b ha hab hb with ⟨hvar_int, hvar_le⟩
  rcases frontier_intervalVariance_shift_sub g hgab hvar_int hab with
    ⟨hshift_int, hshift_eq⟩
  exact ⟨hshift_int, by rw [hshift_eq]; exact hvar_le⟩

theorem frontier_centered_admissible_shift_original
    (g : ℝ → ℝ)
    (hcentered : frontierBMOCenteredFunctionAdmissible g) :
    frontierBMOOriginalFunctionAdmissible (fun t ↦ g t - 10) := by
  rcases hcentered with ⟨hg, hg2, hphi, hmean, hsecondMoment, hvariance⟩
  refine ⟨
    frontier_centered_shift_intervalIntegrable g hg,
    frontier_centered_shift_square_intervalIntegrable g hg hg2,
    frontier_centered_shift_objective_intervalIntegrable g hg hg2 hphi,
    frontier_centered_mean_integral_shift_of_centered_mean g hg hmean,
    frontier_centered_second_moment_integral_shift_of_centered_moments
      g hg hg2 hmean hsecondMoment,
    ?_⟩
  intro a b ha hab hb
  exact frontier_centered_admissible_shift_variance
    g ⟨hg, hg2, hphi, hmean, hsecondMoment, hvariance⟩ ha hab hb

theorem frontier_centered_objective_shift_mem_original_objectiveSet_of_admissible
    (g : ℝ → ℝ)
    (hcentered : frontierBMOCenteredFunctionAdmissible g) :
    frontierBMOCenteredObjectiveIntegral g - (1985 / 2 : ℝ) ∈
      frontierBMOOriginalFunctionObjectiveSet := by
  rcases hcentered with ⟨hg, hg2, hphi, hmean, hsecondMoment, hvariance⟩
  exact frontier_centered_objective_shift_mem_original_objectiveSet
    g
    (frontier_centered_admissible_shift_original
      g ⟨hg, hg2, hphi, hmean, hsecondMoment, hvariance⟩)
    hg hg2 hphi hmean hsecondMoment

theorem frontier_original_objective_pointwise_uncenter (x : ℝ) :
    frontierPhi (x + 10) =
      x ^ 3 + |x| + 30 * x ^ 2 + 301 * x + 1000 := by
  rw [frontierPhi, frontierA]
  by_cases h : 0 ≤ x
  · rw [abs_of_nonneg h, max_eq_left]
    · ring
    · ring_nf
      exact h
  · have hx : x ≤ 0 := le_of_not_ge h
    rw [abs_of_nonpos hx, max_eq_right]
    · ring
    · ring_nf
      exact hx

theorem frontier_original_objective_integral_uncenter
    (f : ℝ → ℝ)
    (hf : IntervalIntegrable f volume (0 : ℝ) 1)
    (hf2 : IntervalIntegrable (fun t ↦ (f t) ^ 2) volume (0 : ℝ) 1)
    (hobj : IntervalIntegrable (fun t ↦ (f t) ^ 3 + |f t|) volume (0 : ℝ) 1) :
    frontierBMOCenteredObjectiveIntegral (fun t ↦ f t + 10) =
      frontierBMOOriginalObjectiveIntegral f +
        30 * frontierBMOOriginalSecondMomentIntegral f +
        301 * frontierBMOOriginalMeanIntegral f + 1000 := by
  have h30 :
      IntervalIntegrable (fun t ↦ 30 * (f t) ^ 2) volume (0 : ℝ) 1 :=
    hf2.const_mul 30
  have h301 :
      IntervalIntegrable (fun t ↦ 301 * f t) volume (0 : ℝ) 1 :=
    hf.const_mul 301
  have hleft :
      IntervalIntegrable
        (fun t ↦ (f t) ^ 3 + |f t| + 30 * (f t) ^ 2) volume (0 : ℝ) 1 :=
    hobj.add h30
  have hmain :
      IntervalIntegrable
        (fun t ↦ ((f t) ^ 3 + |f t| + 30 * (f t) ^ 2) + 301 * f t)
        volume (0 : ℝ) 1 :=
    hleft.add h301
  have hconst :
      IntervalIntegrable (fun _ : ℝ ↦ (1000 : ℝ)) volume (0 : ℝ) 1 :=
    intervalIntegrable_const
  rw [frontierBMOCenteredObjectiveIntegral, frontierBMOOriginalObjectiveIntegral,
    frontierBMOOriginalSecondMomentIntegral, frontierBMOOriginalMeanIntegral]
  calc
    ∫ t in (0 : ℝ)..1, frontierPhi (f t + 10) =
        ∫ t in (0 : ℝ)..1,
          (((f t) ^ 3 + |f t| + 30 * (f t) ^ 2) + 301 * f t) + 1000 := by
      apply intervalIntegral.integral_congr
      intro t _ht
      simpa [add_assoc] using frontier_original_objective_pointwise_uncenter (f t)
    _ = (∫ t in (0 : ℝ)..1, (f t) ^ 3 + |f t|) +
          30 * (∫ t in (0 : ℝ)..1, (f t) ^ 2) +
          301 * (∫ t in (0 : ℝ)..1, f t) + 1000 := by
      rw [intervalIntegral.integral_add hmain hconst]
      rw [intervalIntegral.integral_add hleft h301]
      rw [intervalIntegral.integral_add hobj h30]
      rw [intervalIntegral.integral_const_mul, intervalIntegral.integral_const_mul]
      rw [intervalIntegral.integral_const]
      norm_num

theorem frontier_original_objective_integral_uncenter_of_moments
    (f : ℝ → ℝ)
    (hf : IntervalIntegrable f volume (0 : ℝ) 1)
    (hf2 : IntervalIntegrable (fun t ↦ (f t) ^ 2) volume (0 : ℝ) 1)
    (hobj : IntervalIntegrable (fun t ↦ (f t) ^ 3 + |f t|) volume (0 : ℝ) 1)
    (hmean : frontierBMOOriginalMeanIntegral f = -10)
    (hsecondMoment :
      frontierBMOOriginalSecondMomentIntegral f = 100 + (1 / 12 : ℝ)) :
    frontierBMOCenteredObjectiveIntegral (fun t ↦ f t + 10) =
      frontierBMOOriginalObjectiveIntegral f + (1985 / 2 : ℝ) := by
  rw [frontier_original_objective_integral_uncenter f hf hf2 hobj, hmean, hsecondMoment]
  ring

theorem frontier_original_mean_integral_uncenter
    (f : ℝ → ℝ)
    (hf : IntervalIntegrable f volume (0 : ℝ) 1) :
    frontierBMOOriginalMeanIntegral (fun t ↦ f t + 10) =
      frontierBMOOriginalMeanIntegral f + 10 := by
  have hconst :
      IntervalIntegrable (fun _ : ℝ ↦ (10 : ℝ)) volume (0 : ℝ) 1 :=
    intervalIntegrable_const
  rw [frontierBMOOriginalMeanIntegral]
  rw [intervalIntegral.integral_add hf hconst]
  rw [intervalIntegral.integral_const]
  rw [frontierBMOOriginalMeanIntegral]
  norm_num

theorem frontier_original_mean_integral_uncenter_of_original_mean
    (f : ℝ → ℝ)
    (hf : IntervalIntegrable f volume (0 : ℝ) 1)
    (hmean : frontierBMOOriginalMeanIntegral f = -10) :
    frontierBMOOriginalMeanIntegral (fun t ↦ f t + 10) = 0 := by
  rw [frontier_original_mean_integral_uncenter f hf, hmean]
  norm_num

theorem frontier_original_second_moment_integral_uncenter
    (f : ℝ → ℝ)
    (hf : IntervalIntegrable f volume (0 : ℝ) 1)
    (hf2 : IntervalIntegrable (fun t ↦ (f t) ^ 2) volume (0 : ℝ) 1) :
    frontierBMOOriginalSecondMomentIntegral (fun t ↦ f t + 10) =
      frontierBMOOriginalSecondMomentIntegral f +
        20 * frontierBMOOriginalMeanIntegral f + 100 := by
  have h20 :
      IntervalIntegrable (fun t ↦ 20 * f t) volume (0 : ℝ) 1 :=
    hf.const_mul 20
  have hsum :
      IntervalIntegrable (fun t ↦ (f t) ^ 2 + 20 * f t) volume (0 : ℝ) 1 :=
    hf2.add h20
  have hconst :
      IntervalIntegrable (fun _ : ℝ ↦ (100 : ℝ)) volume (0 : ℝ) 1 :=
    intervalIntegrable_const
  rw [frontierBMOOriginalSecondMomentIntegral, frontierBMOOriginalMeanIntegral]
  calc
    ∫ t in (0 : ℝ)..1, (f t + 10) ^ 2 =
        ∫ t in (0 : ℝ)..1, ((f t) ^ 2 + 20 * f t) + 100 := by
      apply intervalIntegral.integral_congr
      intro t _ht
      ring
    _ = (∫ t in (0 : ℝ)..1, (f t) ^ 2) +
          20 * (∫ t in (0 : ℝ)..1, f t) + 100 := by
      rw [intervalIntegral.integral_add hsum hconst]
      rw [intervalIntegral.integral_add hf2 h20]
      rw [intervalIntegral.integral_const_mul]
      rw [intervalIntegral.integral_const]
      norm_num

theorem frontier_original_second_moment_integral_uncenter_of_original_moments
    (f : ℝ → ℝ)
    (hf : IntervalIntegrable f volume (0 : ℝ) 1)
    (hf2 : IntervalIntegrable (fun t ↦ (f t) ^ 2) volume (0 : ℝ) 1)
    (hmean : frontierBMOOriginalMeanIntegral f = -10)
    (hsecondMoment :
      frontierBMOOriginalSecondMomentIntegral f = 100 + (1 / 12 : ℝ)) :
    frontierBMOOriginalSecondMomentIntegral (fun t ↦ f t + 10) =
      (1 / 12 : ℝ) := by
  rw [frontier_original_second_moment_integral_uncenter f hf hf2, hmean, hsecondMoment]
  ring

theorem frontier_original_uncenter_intervalIntegrable
    (f : ℝ → ℝ)
    (hf : IntervalIntegrable f volume (0 : ℝ) 1) :
    IntervalIntegrable (fun t ↦ f t + 10) volume (0 : ℝ) 1 := by
  exact hf.add intervalIntegrable_const

theorem frontier_original_uncenter_square_intervalIntegrable
    (f : ℝ → ℝ)
    (hf : IntervalIntegrable f volume (0 : ℝ) 1)
    (hf2 : IntervalIntegrable (fun t ↦ (f t) ^ 2) volume (0 : ℝ) 1) :
    IntervalIntegrable (fun t ↦ (f t + 10) ^ 2) volume (0 : ℝ) 1 := by
  have h20 : IntervalIntegrable (fun t ↦ 20 * f t) volume (0 : ℝ) 1 :=
    hf.const_mul 20
  have hpoly :
      IntervalIntegrable (fun t ↦ (f t) ^ 2 + 20 * f t + 100) volume (0 : ℝ) 1 :=
    (hf2.add h20).add intervalIntegrable_const
  refine hpoly.congr ?_
  intro t _ht
  ring

theorem frontier_original_uncenter_phi_intervalIntegrable
    (f : ℝ → ℝ)
    (hf : IntervalIntegrable f volume (0 : ℝ) 1)
    (hf2 : IntervalIntegrable (fun t ↦ (f t) ^ 2) volume (0 : ℝ) 1)
    (hobj : IntervalIntegrable (fun t ↦ (f t) ^ 3 + |f t|)
      volume (0 : ℝ) 1) :
    IntervalIntegrable (fun t ↦ frontierPhi (f t + 10)) volume (0 : ℝ) 1 := by
  have h30 :
      IntervalIntegrable (fun t ↦ 30 * (f t) ^ 2) volume (0 : ℝ) 1 :=
    hf2.const_mul 30
  have h301 :
      IntervalIntegrable (fun t ↦ 301 * f t) volume (0 : ℝ) 1 :=
    hf.const_mul 301
  have hleft :
      IntervalIntegrable
        (fun t ↦ (f t) ^ 3 + |f t| + 30 * (f t) ^ 2) volume (0 : ℝ) 1 :=
    hobj.add h30
  have hmain :
      IntervalIntegrable
        (fun t ↦ ((f t) ^ 3 + |f t| + 30 * (f t) ^ 2) + 301 * f t)
        volume (0 : ℝ) 1 :=
    hleft.add h301
  have hpoly :
      IntervalIntegrable
        (fun t ↦ (((f t) ^ 3 + |f t| + 30 * (f t) ^ 2) + 301 * f t) + 1000)
        volume (0 : ℝ) 1 :=
    hmain.add intervalIntegrable_const
  refine hpoly.congr ?_
  intro t _ht
  simpa [add_assoc] using (frontier_original_objective_pointwise_uncenter (f t)).symm

theorem frontier_intervalMean_shift_add
    (f : ℝ → ℝ) {a b : ℝ}
    (hf : IntervalIntegrable f volume a b) (hab : a < b) :
    frontierBMOIntervalMean (fun t ↦ f t + 10) a b =
      frontierBMOIntervalMean f a b + 10 := by
  have hconst :
      IntervalIntegrable (fun _ : ℝ ↦ (10 : ℝ)) volume a b :=
    intervalIntegrable_const
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalMean]
  rw [intervalIntegral.integral_add hf hconst]
  rw [intervalIntegral.integral_const]
  rw [frontierBMOIntervalMean]
  simp only [smul_eq_mul]
  field_simp [hne]

theorem frontier_intervalVariance_shift_add
    (f : ℝ → ℝ) {a b : ℝ}
    (hf : IntervalIntegrable f volume a b)
    (hvar :
      IntervalIntegrable
        (fun t ↦ (f t - frontierBMOIntervalMean f a b) ^ 2) volume a b)
    (hab : a < b) :
    IntervalIntegrable
        (fun t ↦
          ((f t + 10) - frontierBMOIntervalMean (fun t ↦ f t + 10) a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance (fun t ↦ f t + 10) a b =
        frontierBMOIntervalVariance f a b := by
  have hmean := frontier_intervalMean_shift_add f hf hab
  have hvar_shift :
      IntervalIntegrable
        (fun t ↦
          ((f t + 10) - frontierBMOIntervalMean (fun t ↦ f t + 10) a b) ^ 2)
        volume a b := by
    refine hvar.congr ?_
    intro t _ht
    rw [hmean]
    ring
  refine ⟨hvar_shift, ?_⟩
  rw [frontierBMOIntervalVariance]
  apply congrArg (fun z : ℝ ↦ z / (b - a))
  apply intervalIntegral.integral_congr
  intro t _ht
  rw [hmean]
  ring

theorem frontier_original_admissible_uncenter_variance
    (f : ℝ → ℝ)
    (horiginal : frontierBMOOriginalFunctionAdmissible f)
    {a b : ℝ} (ha : 0 ≤ a) (hab : a < b) (hb : b ≤ 1) :
    IntervalIntegrable
        (fun t ↦
          ((f t + 10) - frontierBMOIntervalMean (fun t ↦ f t + 10) a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance (fun t ↦ f t + 10) a b ≤ (1 / 12 : ℝ) := by
  rcases horiginal with ⟨hf, _hf2, _hobj, _hmean, _hsecondMoment, hvariance⟩
  have hfab : IntervalIntegrable f volume a b :=
    frontier_intervalIntegrable_on_subinterval_of_unit f hf ha hab hb
  rcases hvariance a b ha hab hb with ⟨hvar_int, hvar_le⟩
  rcases frontier_intervalVariance_shift_add f hfab hvar_int hab with
    ⟨hshift_int, hshift_eq⟩
  exact ⟨hshift_int, by rw [hshift_eq]; exact hvar_le⟩

theorem frontier_original_admissible_uncenter_centered
    (f : ℝ → ℝ)
    (horiginal : frontierBMOOriginalFunctionAdmissible f) :
    frontierBMOCenteredFunctionAdmissible (fun t ↦ f t + 10) := by
  rcases horiginal with ⟨hf, hf2, hobj, hmean, hsecondMoment, hvariance⟩
  refine ⟨
    frontier_original_uncenter_intervalIntegrable f hf,
    frontier_original_uncenter_square_intervalIntegrable f hf hf2,
    frontier_original_uncenter_phi_intervalIntegrable f hf hf2 hobj,
    frontier_original_mean_integral_uncenter_of_original_mean f hf hmean,
    frontier_original_second_moment_integral_uncenter_of_original_moments
      f hf hf2 hmean hsecondMoment,
    ?_⟩
  intro a b ha hab hb
  exact frontier_original_admissible_uncenter_variance
    f ⟨hf, hf2, hobj, hmean, hsecondMoment, hvariance⟩ ha hab hb

theorem frontier_original_objective_shift_mem_centered_objectiveSet
    (f : ℝ → ℝ)
    (horiginal : frontierBMOOriginalFunctionAdmissible f) :
    frontierBMOOriginalObjectiveIntegral f + (1985 / 2 : ℝ) ∈
      frontierBMOCenteredFunctionObjectiveSet := by
  rcases horiginal with ⟨hf, hf2, hobj, hmean, hsecondMoment, hvariance⟩
  refine ⟨fun t ↦ f t + 10,
    frontier_original_admissible_uncenter_centered
      f ⟨hf, hf2, hobj, hmean, hsecondMoment, hvariance⟩, ?_⟩
  exact (frontier_original_objective_integral_uncenter_of_moments
    f hf hf2 hobj hmean hsecondMoment).symm

theorem frontier_original_centered_objectiveSet_shift :
    frontierBMOOriginalFunctionObjectiveSet =
      (fun y : ℝ ↦ y - (1985 / 2 : ℝ)) '' frontierBMOCenteredFunctionObjectiveSet := by
  ext y
  constructor
  · intro hy
    rcases hy with ⟨f, horiginal, rfl⟩
    refine ⟨frontierBMOOriginalObjectiveIntegral f + (1985 / 2 : ℝ),
      frontier_original_objective_shift_mem_centered_objectiveSet f horiginal, ?_⟩
    ring
  · intro hy
    rcases hy with ⟨z, hz, rfl⟩
    rcases hz with ⟨g, hcentered, rfl⟩
    exact frontier_centered_objective_shift_mem_original_objectiveSet_of_admissible
      g hcentered

theorem frontier_sSup_image_sub_const
    (S : Set ℝ) (c : ℝ) (hne : S.Nonempty) (hbdd : BddAbove S) :
    sSup ((fun y : ℝ ↦ y - c) '' S) = sSup S - c := by
  have hne_image : ((fun y : ℝ ↦ y - c) '' S).Nonempty := by
    rcases hne with ⟨y, hy⟩
    exact ⟨y - c, y, hy, rfl⟩
  have hbddS : BddAbove S := hbdd
  obtain ⟨M, hM⟩ := hbdd
  have hbdd_image : BddAbove ((fun y : ℝ ↦ y - c) '' S) := by
    refine ⟨M - c, ?_⟩
    intro y hy
    rcases hy with ⟨z, hz, rfl⟩
    exact sub_le_sub_right (hM hz) c
  apply le_antisymm
  · refine csSup_le hne_image ?_
    intro y hy
    rcases hy with ⟨z, hz, rfl⟩
    exact sub_le_sub_right (le_csSup hbddS hz) c
  · have hupper : ∀ z ∈ S, z ≤ sSup ((fun y : ℝ ↦ y - c) '' S) + c := by
      intro z hz
      have hz_image : z - c ∈ ((fun y : ℝ ↦ y - c) '' S) := ⟨z, hz, rfl⟩
      have hz_le : z - c ≤ sSup ((fun y : ℝ ↦ y - c) '' S) :=
        le_csSup hbdd_image hz_image
      linarith
    have hsup_le : sSup S ≤ sSup ((fun y : ℝ ↦ y - c) '' S) + c :=
      csSup_le hne hupper
    linarith

theorem frontier_original_benchmark_eq_centered_supremum_of_set_shift
    (hset :
      frontierBMOOriginalFunctionObjectiveSet =
        (fun y : ℝ ↦ y - (1985 / 2 : ℝ)) '' frontierBMOCenteredFunctionObjectiveSet)
    (hne : frontierBMOCenteredFunctionObjectiveSet.Nonempty)
    (hbdd : BddAbove frontierBMOCenteredFunctionObjectiveSet) :
    frontierBMOOriginalFunctionBenchmarkValue =
      frontierBMOCenteredFunctionSupremum := by
  rw [frontierBMOOriginalFunctionBenchmarkValue,
    frontierBMOOriginalFunctionSupremum, frontierBMOCenteredFunctionSupremum,
    hset]
  rw [frontier_sSup_image_sub_const frontierBMOCenteredFunctionObjectiveSet
    (1985 / 2 : ℝ) hne hbdd]
  ring

theorem frontier_original_benchmark_eq_centered_supremum
    (hne : frontierBMOCenteredFunctionObjectiveSet.Nonempty)
    (hbdd : BddAbove frontierBMOCenteredFunctionObjectiveSet) :
    frontierBMOOriginalFunctionBenchmarkValue =
      frontierBMOCenteredFunctionSupremum := by
  exact frontier_original_benchmark_eq_centered_supremum_of_set_shift
    frontier_original_centered_objectiveSet_shift hne hbdd

def frontierBMOCenteredActualUpperBound : Prop :=
  ∀ y ∈ frontierBMOCenteredFunctionObjectiveSet, y ≤ frontierBMOPublicAnswer

theorem frontierBMOOriginalActualUpperBound_of_centered_cover
    (hcover : ∀ y ∈ frontierBMOOriginalFunctionObjectiveSet,
      y + (1985 / 2 : ℝ) ∈ frontierBMOCenteredFunctionObjectiveSet)
    (hupper : frontierBMOCenteredActualUpperBound) :
    frontierBMOOriginalActualUpperBound := by
  intro y hy
  have hy_upper : y + (1985 / 2 : ℝ) ≤ frontierBMOPublicAnswer :=
    hupper (y + (1985 / 2 : ℝ)) (hcover y hy)
  rw [frontierBMOOriginalSupremumValue]
  linarith

theorem frontierBMOOriginalActualUpperBound_of_centered_set_shift
    (hset :
      frontierBMOOriginalFunctionObjectiveSet =
        (fun y : ℝ ↦ y - (1985 / 2 : ℝ)) '' frontierBMOCenteredFunctionObjectiveSet)
    (hupper : frontierBMOCenteredActualUpperBound) :
    frontierBMOOriginalActualUpperBound := by
  apply frontierBMOOriginalActualUpperBound_of_centered_cover
  · intro y hy
    rw [hset] at hy
    rcases hy with ⟨z, hz, rfl⟩
    convert hz using 1
    ring
  · exact hupper

theorem frontierBMOOriginalActualUpperBound_of_centered_upper
    (hupper : frontierBMOCenteredActualUpperBound) :
    frontierBMOOriginalActualUpperBound := by
  exact frontierBMOOriginalActualUpperBound_of_centered_set_shift
    frontier_original_centered_objectiveSet_shift hupper

theorem frontierBMOCenteredActualUpperBound_of_original_actual_upper
    (hupper : frontierBMOOriginalActualUpperBound) :
    frontierBMOCenteredActualUpperBound := by
  intro y hy
  have hy_original :
      y - (1985 / 2 : ℝ) ∈ frontierBMOOriginalFunctionObjectiveSet := by
    rw [frontier_original_centered_objectiveSet_shift]
    exact ⟨y, hy, rfl⟩
  have hy_bound := hupper (y - (1985 / 2 : ℝ)) hy_original
  rw [frontierBMOOriginalSupremumValue] at hy_bound
  linarith

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction_to_originalActualUpperBound :
    frontierBMOOriginalActualUpperBound → frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_original_actual_upper

def frontierOmega (eps x1 x2 : ℝ) : Prop :=
  x1 ^ 2 ≤ x2 ∧ x2 ≤ x1 ^ 2 + eps ^ 2

def frontierRadius (eps x1 x2 : ℝ) : ℝ :=
  Real.sqrt (eps ^ 2 + x1 ^ 2 - x2)

def frontierCPlus (eps x1 x2 : ℝ) : ℝ :=
  x1 + frontierRadius eps x1 x2

def frontierDMinus (eps x1 x2 : ℝ) : ℝ :=
  x1 - frontierRadius eps x1 x2

def frontierKL : ℝ :=
  frontierEpsilon * Real.exp (-(frontierCStar / frontierEpsilon))

def frontierKR : ℝ :=
  frontierEpsilon * Real.exp (frontierCStar / frontierEpsilon)

def frontierLeftPiece (x1 x2 : ℝ) : ℝ :=
  let eps := frontierEpsilon
  let r := frontierRadius eps x1 x2
  let C := frontierCPlus eps x1 x2
  (r / eps) * (C - eps) ^ 3 +
    (1 - r / eps) * (C ^ 3 + 3 * C * eps ^ 2 + 2 * eps ^ 3 + frontierKL * Real.exp (C / eps))

def frontierCupAlpha : ℝ :=
  frontierCStar - frontierEpsilon

def frontierCupBeta : ℝ :=
  frontierCStar + frontierEpsilon

def frontierCupDomain (x1 x2 : ℝ) : Prop :=
  frontierCupAlpha ≤ x1 ∧ x1 ≤ frontierCupBeta ∧
    x1 ^ 2 ≤ x2 ∧ x2 ≤ 2 * frontierCStar * x1 - frontierCStar ^ 2 + frontierEpsilon ^ 2

def frontierCupPiece (x1 _x2 : ℝ) : ℝ :=
  ((frontierCupBeta - x1) / (2 * frontierEpsilon)) * frontierPhi frontierCupAlpha +
    ((x1 - frontierCupAlpha) / (2 * frontierEpsilon)) * frontierPhi frontierCupBeta

def frontierRightReflectedPiece (x1 x2 : ℝ) : ℝ :=
  let eps := frontierEpsilon
  let r := frontierRadius eps x1 x2
  let D := frontierDMinus eps x1 x2
  (r / eps) * ((D + eps) ^ 3 + 2 * (D + eps - frontierA)) +
    (1 - r / eps) *
      (D ^ 3 + 3 * D * eps ^ 2 - 2 * eps ^ 3 + 2 * D - 2 * frontierA +
        frontierKR * Real.exp (-(D / eps)))

def frontierRightReflectedConcavityCondition (D : ℝ) : Prop :=
  6 * frontierEpsilon ^ 3 ≤ frontierKR * Real.exp (-(D / frontierEpsilon))

def frontierRightReflectedCutoff : ℝ :=
  frontierCStar + frontierEpsilon * Real.log 2

def frontierRightTailStart : ℝ :=
  frontierCStar + 2 * frontierEpsilon

def frontierRightTailTrace (C : ℝ) : ℝ :=
  C ^ 3 + 3 * C * frontierEpsilon ^ 2 + 2 * frontierEpsilon ^ 3 +
    2 * C - 2 * frontierA

def frontierRightTailTraceDeriv (C : ℝ) : ℝ :=
  3 * C ^ 2 + 3 * frontierEpsilon ^ 2 + 2

def frontierLeftTrace (C : ℝ) : ℝ :=
  C ^ 3 + 3 * C * frontierEpsilon ^ 2 + 2 * frontierEpsilon ^ 3 +
    frontierKL * Real.exp (C / frontierEpsilon)

def frontierLeftTraceDeriv (C : ℝ) : ℝ :=
  3 * C ^ 2 + 3 * frontierEpsilon ^ 2 +
    frontierKL / frontierEpsilon * Real.exp (C / frontierEpsilon)

def frontierLeftTraceSecond (C : ℝ) : ℝ :=
  6 * C + frontierKL / frontierEpsilon ^ 2 * Real.exp (C / frontierEpsilon)

def frontierLeftTraceThird (C : ℝ) : ℝ :=
  6 + frontierKL / frontierEpsilon ^ 3 * Real.exp (C / frontierEpsilon)

def frontierMiddleTrace (C : ℝ) : ℝ :=
  frontierLeftTrace frontierCStar +
    frontierLeftTraceDeriv frontierCStar * (C - frontierCStar) +
      (3 * frontierCStar + 6 * frontierEpsilon) * (C - frontierCStar) ^ 2

def frontierMiddleTraceDeriv (C : ℝ) : ℝ :=
  frontierLeftTraceDeriv frontierCStar +
    2 * (3 * frontierCStar + 6 * frontierEpsilon) * (C - frontierCStar)

def frontierMiddlePiece (x1 x2 : ℝ) : ℝ :=
  let r := frontierRadius frontierEpsilon x1 x2
  let C := frontierCPlus frontierEpsilon x1 x2
  frontierMiddleTrace C - r * frontierMiddleTraceDeriv C

def frontierMiddleTraceSecond (_C : ℝ) : ℝ :=
  2 * (3 * frontierCStar + 6 * frontierEpsilon)

def frontierMiddleTraceThird (_C : ℝ) : ℝ :=
  0

def frontierRightTailTraceSecond (C : ℝ) : ℝ :=
  6 * C

def frontierRightTailTraceThird (_C : ℝ) : ℝ :=
  6

def frontierRightTailPiece (x1 x2 : ℝ) : ℝ :=
  let r := frontierRadius frontierEpsilon x1 x2
  let C := frontierCPlus frontierEpsilon x1 x2
  frontierRightTailTrace C - r * frontierRightTailTraceDeriv C

def frontierMajorant (x1 x2 : ℝ) : ℝ :=
  if frontierCPlus frontierEpsilon x1 x2 ≤ frontierCStar then
    frontierLeftPiece x1 x2
  else if frontierCPlus frontierEpsilon x1 x2 ≤ frontierCStar + 2 * frontierEpsilon then
    frontierMiddlePiece x1 x2
  else
    frontierRightTailPiece x1 x2

def frontierMajorantLocallyConcaveOnStrip : Prop :=
  ∀ x1 x2 : ℝ, frontierOmega frontierEpsilon x1 x2 →
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2

def frontierMajorantLocalConcavityAt (x1 x2 : ℝ) : Prop :=
  ∃ δ : ℝ, 0 < δ ∧
    ∀ y1 y2 z1 z2 θ : ℝ,
      |y1 - x1| < δ → |y2 - x2| < δ →
      |z1 - x1| < δ → |z2 - x2| < δ →
      frontierOmega frontierEpsilon y1 y2 →
      frontierOmega frontierEpsilon z1 z2 →
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) →
      0 ≤ θ → θ ≤ 1 →
        frontierMajorant
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) ≥
          θ * frontierMajorant y1 y2 +
            (1 - θ) * frontierMajorant z1 z2

def frontierMiddleBranchDomain (x1 x2 : ℝ) : Prop :=
  frontierCStar < frontierCPlus frontierEpsilon x1 x2 ∧
    frontierCPlus frontierEpsilon x1 x2 ≤ frontierCStar + 2 * frontierEpsilon

def frontierLeftBranchDomain (x1 x2 : ℝ) : Prop :=
  frontierCPlus frontierEpsilon x1 x2 < frontierCStar

def frontierRightBranchDomain (x1 x2 : ℝ) : Prop :=
  frontierCStar + 2 * frontierEpsilon <
    frontierCPlus frontierEpsilon x1 x2

theorem frontierEpsilon_pos : 0 < frontierEpsilon := by
  rw [frontierEpsilon]
  positivity

theorem frontierEpsilon_ne_zero : frontierEpsilon ≠ 0 :=
  ne_of_gt frontierEpsilon_pos

theorem frontierEpsilon_sq : frontierEpsilon ^ 2 = (1 / 12 : ℝ) := by
  rw [frontierEpsilon]
  have hs_nonneg : 0 ≤ (3 : ℝ) := by norm_num
  have hs : (Real.sqrt 3) ^ 2 = (3 : ℝ) := Real.sq_sqrt hs_nonneg
  rw [div_pow, hs]
  norm_num

theorem frontierEpsilon_lt_one : frontierEpsilon < 1 := by
  nlinarith [frontierEpsilon_pos, frontierEpsilon_sq]

theorem frontierOmega_center_moments :
    frontierOmega frontierEpsilon 0 (1 / 12 : ℝ) := by
  rw [frontierOmega, frontierEpsilon_sq]
  constructor <;> norm_num

theorem frontierBMOCenteredAdmissible_moments_mem_omega
    (g : ℝ → ℝ) (hg : frontierBMOCenteredFunctionAdmissible g) :
    frontierOmega frontierEpsilon
      (frontierBMOOriginalMeanIntegral g)
      (frontierBMOOriginalSecondMomentIntegral g) := by
  rcases hg with ⟨_hg, _hg2, _hphi, hmean, hsecondMoment, _hvariance⟩
  rw [hmean, hsecondMoment]
  exact frontierOmega_center_moments

theorem frontierLeftPiece_trace_form (x1 x2 : ℝ) :
    frontierLeftPiece x1 x2 =
      frontierLeftTrace (frontierCPlus frontierEpsilon x1 x2) -
        frontierRadius frontierEpsilon x1 x2 *
          frontierLeftTraceDeriv (frontierCPlus frontierEpsilon x1 x2) := by
  rw [frontierLeftPiece, frontierLeftTrace, frontierLeftTraceDeriv]
  field_simp [frontierEpsilon_ne_zero]
  ring

theorem frontierMiddlePiece_trace_form (x1 x2 : ℝ) :
    frontierMiddlePiece x1 x2 =
      frontierMiddleTrace (frontierCPlus frontierEpsilon x1 x2) -
        frontierRadius frontierEpsilon x1 x2 *
          frontierMiddleTraceDeriv (frontierCPlus frontierEpsilon x1 x2) := by
  rfl

theorem frontierRightTailPiece_trace_form (x1 x2 : ℝ) :
    frontierRightTailPiece x1 x2 =
      frontierRightTailTrace (frontierCPlus frontierEpsilon x1 x2) -
        frontierRadius frontierEpsilon x1 x2 *
          frontierRightTailTraceDeriv (frontierCPlus frontierEpsilon x1 x2) := by
  rfl

theorem frontierLeftTrace_hasDerivAt (C : ℝ) :
    HasDerivAt frontierLeftTrace (frontierLeftTraceDeriv C) C := by
  unfold frontierLeftTrace frontierLeftTraceDeriv
  have hdiv :
      HasDerivAt (fun x : ℝ => x / frontierEpsilon) (1 / frontierEpsilon) C := by
    simpa [div_eq_mul_inv] using
      (hasDerivAt_id' C).mul_const frontierEpsilon⁻¹
  have hexp :
      HasDerivAt (fun x : ℝ => Real.exp (x / frontierEpsilon))
        (Real.exp (C / frontierEpsilon) * (1 / frontierEpsilon)) C := by
    simpa only [one_div] using
      (Real.hasDerivAt_exp (C / frontierEpsilon)).comp C hdiv
  have hkl :
      HasDerivAt
        (fun x : ℝ => frontierKL * Real.exp (x / frontierEpsilon))
        (frontierKL * (Real.exp (C / frontierEpsilon) *
          (1 / frontierEpsilon))) C := by
    exact hexp.const_mul frontierKL
  convert
      (((hasDerivAt_id' C).pow 3).add
        ((hasDerivAt_id' C).const_mul (3 * frontierEpsilon ^ 2))).add
          (hasDerivAt_const C (2 * frontierEpsilon ^ 3)) |>.add hkl using 1
  · funext x
    simp
    ring_nf
  · ring

theorem frontierLeftTraceDeriv_hasDerivAt (C : ℝ) :
    HasDerivAt frontierLeftTraceDeriv (frontierLeftTraceSecond C) C := by
  unfold frontierLeftTraceDeriv frontierLeftTraceSecond
  have hdiv :
      HasDerivAt (fun x : ℝ => x / frontierEpsilon) (1 / frontierEpsilon) C := by
    simpa [div_eq_mul_inv] using
      (hasDerivAt_id' C).mul_const frontierEpsilon⁻¹
  have hexp :
      HasDerivAt (fun x : ℝ => Real.exp (x / frontierEpsilon))
        (Real.exp (C / frontierEpsilon) * (1 / frontierEpsilon)) C := by
    simpa only [one_div] using
      (Real.hasDerivAt_exp (C / frontierEpsilon)).comp C hdiv
  have hkl :
      HasDerivAt
        (fun x : ℝ =>
          frontierKL / frontierEpsilon * Real.exp (x / frontierEpsilon))
        ((frontierKL / frontierEpsilon) *
          (Real.exp (C / frontierEpsilon) * (1 / frontierEpsilon))) C := by
    exact hexp.const_mul (frontierKL / frontierEpsilon)
  convert
      (((hasDerivAt_id' C).pow 2).const_mul 3).add
        (hasDerivAt_const C (3 * frontierEpsilon ^ 2)) |>.add hkl using 1
  field_simp [frontierEpsilon_ne_zero]
  ring

theorem frontierLeftTraceSecond_hasDerivAt (C : ℝ) :
    HasDerivAt frontierLeftTraceSecond (frontierLeftTraceThird C) C := by
  unfold frontierLeftTraceSecond frontierLeftTraceThird
  have hdiv :
      HasDerivAt (fun x : ℝ => x / frontierEpsilon) (1 / frontierEpsilon) C := by
    simpa [div_eq_mul_inv] using
      (hasDerivAt_id' C).mul_const frontierEpsilon⁻¹
  have hexp :
      HasDerivAt (fun x : ℝ => Real.exp (x / frontierEpsilon))
        (Real.exp (C / frontierEpsilon) * (1 / frontierEpsilon)) C := by
    simpa only [one_div] using
      (Real.hasDerivAt_exp (C / frontierEpsilon)).comp C hdiv
  have hkl :
      HasDerivAt
        (fun x : ℝ =>
          frontierKL / frontierEpsilon ^ 2 * Real.exp (x / frontierEpsilon))
        ((frontierKL / frontierEpsilon ^ 2) *
          (Real.exp (C / frontierEpsilon) * (1 / frontierEpsilon))) C := by
    exact hexp.const_mul (frontierKL / frontierEpsilon ^ 2)
  convert ((hasDerivAt_id' C).const_mul 6).add hkl using 1
  field_simp [frontierEpsilon_ne_zero]

theorem frontierRightTailTrace_hasDerivAt (C : ℝ) :
    HasDerivAt frontierRightTailTrace (frontierRightTailTraceDeriv C) C := by
  unfold frontierRightTailTrace frontierRightTailTraceDeriv
  convert
      (((((hasDerivAt_id' C).pow 3).add
        ((hasDerivAt_id' C).const_mul (3 * frontierEpsilon ^ 2))).add
          (hasDerivAt_const C (2 * frontierEpsilon ^ 3))).add
            ((hasDerivAt_id' C).const_mul 2)).sub
              (hasDerivAt_const C (2 * frontierA)) using 1
  · funext x
    simp
    ring
  · ring

theorem frontierRightTailTraceDeriv_hasDerivAt (C : ℝ) :
    HasDerivAt frontierRightTailTraceDeriv (frontierRightTailTraceSecond C) C := by
  unfold frontierRightTailTraceDeriv frontierRightTailTraceSecond
  convert
      (((hasDerivAt_id' C).pow 2).const_mul 3).add
        (hasDerivAt_const C (3 * frontierEpsilon ^ 2)) |>.add
          (hasDerivAt_const C 2) using 1
  ring_nf

theorem frontierRightTailTraceSecond_hasDerivAt (C : ℝ) :
    HasDerivAt frontierRightTailTraceSecond (frontierRightTailTraceThird C) C := by
  unfold frontierRightTailTraceSecond frontierRightTailTraceThird
  convert (hasDerivAt_id' C).const_mul 6 using 1
  ring_nf

theorem frontierMiddleTrace_hasDerivAt (C : ℝ) :
    HasDerivAt frontierMiddleTrace (frontierMiddleTraceDeriv C) C := by
  unfold frontierMiddleTrace frontierMiddleTraceDeriv
  have hlin : HasDerivAt (fun x : ℝ => x - frontierCStar) 1 C := by
    exact (hasDerivAt_id' C).sub_const frontierCStar
  have hterm1 :
      HasDerivAt
        (fun x : ℝ => frontierLeftTraceDeriv frontierCStar *
          (x - frontierCStar))
        (frontierLeftTraceDeriv frontierCStar) C := by
    convert hlin.const_mul (frontierLeftTraceDeriv frontierCStar) using 1
    ring
  have hterm2 :
      HasDerivAt
        (fun x : ℝ => (3 * frontierCStar + 6 * frontierEpsilon) *
          (x - frontierCStar) ^ 2)
        ((3 * frontierCStar + 6 * frontierEpsilon) *
          (2 * (C - frontierCStar))) C := by
    convert (hlin.pow 2).const_mul (3 * frontierCStar + 6 * frontierEpsilon)
      using 1
    ring
  convert
      ((hasDerivAt_const C (frontierLeftTrace frontierCStar)).add hterm1).add
        hterm2 using 1
  ring

theorem frontierMiddleTraceDeriv_hasDerivAt (C : ℝ) :
    HasDerivAt frontierMiddleTraceDeriv (frontierMiddleTraceSecond C) C := by
  unfold frontierMiddleTraceDeriv frontierMiddleTraceSecond
  have hlin : HasDerivAt (fun x : ℝ => x - frontierCStar) 1 C := by
    exact (hasDerivAt_id' C).sub_const frontierCStar
  have hterm :
      HasDerivAt
        (fun x : ℝ => 2 * (3 * frontierCStar + 6 * frontierEpsilon) *
          (x - frontierCStar))
        (2 * (3 * frontierCStar + 6 * frontierEpsilon)) C := by
    convert hlin.const_mul (2 * (3 * frontierCStar + 6 * frontierEpsilon))
      using 1
    ring
  convert
      (hasDerivAt_const C (frontierLeftTraceDeriv frontierCStar)).add hterm
      using 1
  ring

theorem frontierMiddleTraceSecond_hasDerivAt (C : ℝ) :
    HasDerivAt frontierMiddleTraceSecond (frontierMiddleTraceThird C) C := by
  unfold frontierMiddleTraceSecond frontierMiddleTraceThird
  simpa using hasDerivAt_const C (2 * (3 * frontierCStar + 6 * frontierEpsilon))

theorem frontierRadius_nonneg (eps x1 x2 : ℝ) :
    0 ≤ frontierRadius eps x1 x2 := by
  rw [frontierRadius]
  exact Real.sqrt_nonneg _

theorem frontierRadius_arg_hasDerivAt_along
    (eps x1 x2 u v t : ℝ) :
    HasDerivAt
      (fun s : ℝ => eps ^ 2 + (x1 + s * u) ^ 2 - (x2 + s * v))
      (2 * (x1 + t * u) * u - v) t := by
  have hlin1 : HasDerivAt (fun s : ℝ => x1 + s * u) u t := by
    simpa only [Pi.add_apply, zero_add, one_mul] using
      (hasDerivAt_const t x1).add ((hasDerivAt_id' t).mul_const u)
  have hlin2 : HasDerivAt (fun s : ℝ => x2 + s * v) v t := by
    simpa only [Pi.add_apply, zero_add, one_mul] using
      (hasDerivAt_const t x2).add ((hasDerivAt_id' t).mul_const v)
  have hmain :=
    ((hasDerivAt_const t (eps ^ 2)).add (hlin1.pow 2)).sub hlin2
  convert hmain using 1
  ring

theorem frontierRadius_hasDerivAt_along_of_pos
    {eps x1 x2 u v t : ℝ}
    (hr : 0 < frontierRadius eps (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ => frontierRadius eps (x1 + s * u) (x2 + s * v))
      ((2 * (x1 + t * u) * u - v) /
        (2 * frontierRadius eps (x1 + t * u) (x2 + t * v))) t := by
  have harg_ne :
      eps ^ 2 + (x1 + t * u) ^ 2 - (x2 + t * v) ≠ 0 := by
    intro hzero
    have hr0 : frontierRadius eps (x1 + t * u) (x2 + t * v) = 0 := by
      rw [frontierRadius, hzero, Real.sqrt_zero]
    linarith
  have harg := frontierRadius_arg_hasDerivAt_along eps x1 x2 u v t
  have harg_ne_at :
      eps ^ 2 + (x1 + t * u) ^ 2 - (x2 + t * v) ≠ 0 := by
    simpa using harg_ne
  simpa [frontierRadius] using harg.sqrt harg_ne_at

theorem frontierCPlus_hasDerivAt_along_of_radius_pos
    {eps x1 x2 u v t : ℝ}
    (hr : 0 < frontierRadius eps (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ => frontierCPlus eps (x1 + s * u) (x2 + s * v))
      (u + (2 * (x1 + t * u) * u - v) /
        (2 * frontierRadius eps (x1 + t * u) (x2 + t * v))) t := by
  have hx1 : HasDerivAt (fun s : ℝ => x1 + s * u) u t := by
    simpa only [Pi.add_apply, zero_add, one_mul] using
      (hasDerivAt_const t x1).add ((hasDerivAt_id' t).mul_const u)
  have hradius :=
    frontierRadius_hasDerivAt_along_of_pos (eps := eps) (x1 := x1) (x2 := x2)
      (u := u) (v := v) (t := t) hr
  simpa [frontierCPlus] using hx1.add hradius

theorem frontierTraceBranch_hasDerivAt_along_of_radius_pos
    {trace traceDeriv traceSecond : ℝ → ℝ}
    {eps x1 x2 u v t : ℝ}
    (hr : 0 < frontierRadius eps (x1 + t * u) (x2 + t * v))
    (htrace :
      HasDerivAt trace
        (traceDeriv (frontierCPlus eps (x1 + t * u) (x2 + t * v)))
        (frontierCPlus eps (x1 + t * u) (x2 + t * v)))
    (htraceDeriv :
      HasDerivAt traceDeriv
        (traceSecond (frontierCPlus eps (x1 + t * u) (x2 + t * v)))
        (frontierCPlus eps (x1 + t * u) (x2 + t * v))) :
    HasDerivAt
      (fun s : ℝ =>
        trace (frontierCPlus eps (x1 + s * u) (x2 + s * v)) -
          frontierRadius eps (x1 + s * u) (x2 + s * v) *
            traceDeriv (frontierCPlus eps (x1 + s * u) (x2 + s * v)))
      (u * traceDeriv (frontierCPlus eps (x1 + t * u) (x2 + t * v)) -
        frontierRadius eps (x1 + t * u) (x2 + t * v) *
          traceSecond (frontierCPlus eps (x1 + t * u) (x2 + t * v)) *
            (u + (2 * (x1 + t * u) * u - v) /
              (2 * frontierRadius eps (x1 + t * u) (x2 + t * v)))) t := by
  let r : ℝ := frontierRadius eps (x1 + t * u) (x2 + t * v)
  let C : ℝ := frontierCPlus eps (x1 + t * u) (x2 + t * v)
  let rdot : ℝ := (2 * (x1 + t * u) * u - v) / (2 * r)
  let Cdot : ℝ := u + rdot
  have hradius :
      HasDerivAt
        (fun s : ℝ => frontierRadius eps (x1 + s * u) (x2 + s * v))
        rdot t := by
    simpa [r, rdot] using
      frontierRadius_hasDerivAt_along_of_pos
        (eps := eps) (x1 := x1) (x2 := x2) (u := u) (v := v) (t := t) hr
  have hC :
      HasDerivAt
        (fun s : ℝ => frontierCPlus eps (x1 + s * u) (x2 + s * v))
        Cdot t := by
    simpa [r, rdot, Cdot] using
      frontierCPlus_hasDerivAt_along_of_radius_pos
        (eps := eps) (x1 := x1) (x2 := x2) (u := u) (v := v) (t := t) hr
  have htrace_comp :
      HasDerivAt
        (fun s : ℝ =>
          trace (frontierCPlus eps (x1 + s * u) (x2 + s * v)))
        (traceDeriv C * Cdot) t := by
    simpa [C] using htrace.comp t hC
  have htraceDeriv_comp :
      HasDerivAt
        (fun s : ℝ =>
          traceDeriv (frontierCPlus eps (x1 + s * u) (x2 + s * v)))
        (traceSecond C * Cdot) t := by
    simpa [C] using htraceDeriv.comp t hC
  convert htrace_comp.sub (hradius.mul htraceDeriv_comp) using 1;
    simp [r, C, rdot, Cdot]
  ring

theorem frontierLeftPiece_hasDerivAt_along_of_radius_pos
    {x1 x2 u v t : ℝ}
    (hr :
      0 < frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ => frontierLeftPiece (x1 + s * u) (x2 + s * v))
      (u * frontierLeftTraceDeriv
          (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) -
        frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v) *
          frontierLeftTraceSecond
            (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) *
            (u + (2 * (x1 + t * u) * u - v) /
              (2 * frontierRadius frontierEpsilon
                (x1 + t * u) (x2 + t * v)))) t := by
  convert
    frontierTraceBranch_hasDerivAt_along_of_radius_pos
      (trace := frontierLeftTrace) (traceDeriv := frontierLeftTraceDeriv)
      (traceSecond := frontierLeftTraceSecond)
      (eps := frontierEpsilon) (x1 := x1) (x2 := x2)
      (u := u) (v := v) (t := t) hr
      (frontierLeftTrace_hasDerivAt
        (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)))
      (frontierLeftTraceDeriv_hasDerivAt
        (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v))) using 1
  ext s
  rw [frontierLeftPiece_trace_form]

theorem frontierRightTailPiece_hasDerivAt_along_of_radius_pos
    {x1 x2 u v t : ℝ}
    (hr :
      0 < frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ => frontierRightTailPiece (x1 + s * u) (x2 + s * v))
      (u * frontierRightTailTraceDeriv
          (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) -
        frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v) *
          frontierRightTailTraceSecond
            (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) *
            (u + (2 * (x1 + t * u) * u - v) /
              (2 * frontierRadius frontierEpsilon
                (x1 + t * u) (x2 + t * v)))) t := by
  convert
    frontierTraceBranch_hasDerivAt_along_of_radius_pos
      (trace := frontierRightTailTrace)
      (traceDeriv := frontierRightTailTraceDeriv)
      (traceSecond := frontierRightTailTraceSecond)
      (eps := frontierEpsilon) (x1 := x1) (x2 := x2)
      (u := u) (v := v) (t := t) hr
      (frontierRightTailTrace_hasDerivAt
        (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)))
      (frontierRightTailTraceDeriv_hasDerivAt
        (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v))) using 1

theorem frontierMiddlePiece_hasDerivAt_along_of_radius_pos
    {x1 x2 u v t : ℝ}
    (hr :
      0 < frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ => frontierMiddlePiece (x1 + s * u) (x2 + s * v))
      (u * frontierMiddleTraceDeriv
          (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) -
        frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v) *
          frontierMiddleTraceSecond
            (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) *
            (u + (2 * (x1 + t * u) * u - v) /
              (2 * frontierRadius frontierEpsilon
                (x1 + t * u) (x2 + t * v)))) t := by
  convert
    frontierTraceBranch_hasDerivAt_along_of_radius_pos
      (trace := frontierMiddleTrace)
      (traceDeriv := frontierMiddleTraceDeriv)
      (traceSecond := frontierMiddleTraceSecond)
      (eps := frontierEpsilon) (x1 := x1) (x2 := x2)
      (u := u) (v := v) (t := t) hr
      (frontierMiddleTrace_hasDerivAt
        (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)))
      (frontierMiddleTraceDeriv_hasDerivAt
        (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v))) using 1

theorem frontierLeftPiece_hasDerivAt_along_rankOne_of_radius_pos
    {x1 x2 u v t : ℝ}
    (hr :
      0 < frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ => frontierLeftPiece (x1 + s * u) (x2 + s * v))
      (u * frontierLeftTraceDeriv
          (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) -
        (((2 * frontierCPlus frontierEpsilon
            (x1 + t * u) (x2 + t * v)) * u - v) / 2) *
          frontierLeftTraceSecond
            (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v))) t := by
  have hder :=
    frontierLeftPiece_hasDerivAt_along_of_radius_pos
      (x1 := x1) (x2 := x2) (u := u) (v := v) (t := t) hr
  have hr_ne :
      frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v) ≠ 0 :=
    ne_of_gt hr
  have hmul :
      frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v) *
          (u + (2 * (x1 + t * u) * u - v) /
            (2 * frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v))) =
        (((2 * frontierCPlus frontierEpsilon
          (x1 + t * u) (x2 + t * v)) * u - v) / 2) := by
    rw [frontierCPlus]
    field_simp [hr_ne]
    ring
  convert hder using 1
  rw [← hmul]
  ring

theorem frontierRightTailPiece_hasDerivAt_along_rankOne_of_radius_pos
    {x1 x2 u v t : ℝ}
    (hr :
      0 < frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ => frontierRightTailPiece (x1 + s * u) (x2 + s * v))
      (u * frontierRightTailTraceDeriv
          (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) -
        (((2 * frontierCPlus frontierEpsilon
            (x1 + t * u) (x2 + t * v)) * u - v) / 2) *
          frontierRightTailTraceSecond
            (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v))) t := by
  have hder :=
    frontierRightTailPiece_hasDerivAt_along_of_radius_pos
      (x1 := x1) (x2 := x2) (u := u) (v := v) (t := t) hr
  have hr_ne :
      frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v) ≠ 0 :=
    ne_of_gt hr
  have hmul :
      frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v) *
          (u + (2 * (x1 + t * u) * u - v) /
            (2 * frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v))) =
        (((2 * frontierCPlus frontierEpsilon
          (x1 + t * u) (x2 + t * v)) * u - v) / 2) := by
    rw [frontierCPlus]
    field_simp [hr_ne]
    ring
  convert hder using 1
  rw [← hmul]
  ring

theorem frontierMiddlePiece_hasDerivAt_along_rankOne_of_radius_pos
    {x1 x2 u v t : ℝ}
    (hr :
      0 < frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ => frontierMiddlePiece (x1 + s * u) (x2 + s * v))
      (u * frontierMiddleTraceDeriv
          (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) -
        (((2 * frontierCPlus frontierEpsilon
            (x1 + t * u) (x2 + t * v)) * u - v) / 2) *
          frontierMiddleTraceSecond
            (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v))) t := by
  have hder :=
    frontierMiddlePiece_hasDerivAt_along_of_radius_pos
      (x1 := x1) (x2 := x2) (u := u) (v := v) (t := t) hr
  have hr_ne :
      frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v) ≠ 0 :=
    ne_of_gt hr
  have hmul :
      frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v) *
          (u + (2 * (x1 + t * u) * u - v) /
            (2 * frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v))) =
        (((2 * frontierCPlus frontierEpsilon
          (x1 + t * u) (x2 + t * v)) * u - v) / 2) := by
    rw [frontierCPlus]
    field_simp [hr_ne]
    ring
  convert hder using 1
  rw [← hmul]
  ring

theorem frontierCPlus_hasDerivAt_along_rankOne_of_radius_pos
    {eps x1 x2 u v t : ℝ}
    (hr : 0 < frontierRadius eps (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ => frontierCPlus eps (x1 + s * u) (x2 + s * v))
      (((2 * frontierCPlus eps (x1 + t * u) (x2 + t * v)) * u - v) /
        (2 * frontierRadius eps (x1 + t * u) (x2 + t * v))) t := by
  have hC :=
    frontierCPlus_hasDerivAt_along_of_radius_pos
      (eps := eps) (x1 := x1) (x2 := x2) (u := u) (v := v) (t := t) hr
  convert hC using 1
  field_simp [ne_of_gt hr]
  rw [frontierCPlus]
  ring

theorem frontierTraceBranch_rankOne_slope_hasDerivAt_along_of_radius_pos
    {traceDeriv traceSecond traceThird : ℝ → ℝ}
    {eps x1 x2 u v t : ℝ}
    (hr : 0 < frontierRadius eps (x1 + t * u) (x2 + t * v))
    (htraceDeriv :
      HasDerivAt traceDeriv
        (traceSecond (frontierCPlus eps (x1 + t * u) (x2 + t * v)))
        (frontierCPlus eps (x1 + t * u) (x2 + t * v)))
    (htraceSecond :
      HasDerivAt traceSecond
        (traceThird (frontierCPlus eps (x1 + t * u) (x2 + t * v)))
        (frontierCPlus eps (x1 + t * u) (x2 + t * v))) :
    HasDerivAt
      (fun s : ℝ =>
        u * traceDeriv (frontierCPlus eps (x1 + s * u) (x2 + s * v)) -
          (((2 * frontierCPlus eps (x1 + s * u) (x2 + s * v)) * u - v) / 2) *
            traceSecond (frontierCPlus eps (x1 + s * u) (x2 + s * v)))
      ((-(frontierCPlus eps (x1 + t * u) (x2 + t * v) ^ 2 *
              traceThird (frontierCPlus eps (x1 + t * u) (x2 + t * v)) /
                frontierRadius eps (x1 + t * u) (x2 + t * v))) * u ^ 2 +
        2 * (frontierCPlus eps (x1 + t * u) (x2 + t * v) *
              traceThird (frontierCPlus eps (x1 + t * u) (x2 + t * v)) /
                (2 * frontierRadius eps (x1 + t * u) (x2 + t * v))) * u * v +
          (-(traceThird (frontierCPlus eps (x1 + t * u) (x2 + t * v)) /
              (4 * frontierRadius eps (x1 + t * u) (x2 + t * v)))) * v ^ 2) t := by
  let C : ℝ := frontierCPlus eps (x1 + t * u) (x2 + t * v)
  let r : ℝ := frontierRadius eps (x1 + t * u) (x2 + t * v)
  let Cdot : ℝ := ((2 * C) * u - v) / (2 * r)
  let A : ℝ := ((2 * C) * u - v) / 2
  have hr_ne : r ≠ 0 := ne_of_gt (by simpa [r] using hr)
  have hC :
      HasDerivAt
        (fun s : ℝ => frontierCPlus eps (x1 + s * u) (x2 + s * v))
        Cdot t := by
    simpa [C, r, Cdot] using
      frontierCPlus_hasDerivAt_along_rankOne_of_radius_pos
        (eps := eps) (x1 := x1) (x2 := x2) (u := u) (v := v) (t := t) hr
  have htraceDeriv_comp :
      HasDerivAt
        (fun s : ℝ => traceDeriv (frontierCPlus eps (x1 + s * u) (x2 + s * v)))
        (traceSecond C * Cdot) t := by
    simpa [C] using htraceDeriv.comp t hC
  have htraceSecond_comp :
      HasDerivAt
        (fun s : ℝ => traceSecond (frontierCPlus eps (x1 + s * u) (x2 + s * v)))
        (traceThird C * Cdot) t := by
    simpa [C] using htraceSecond.comp t hC
  have hA :
      HasDerivAt
        (fun s : ℝ =>
          (((2 * frontierCPlus eps (x1 + s * u) (x2 + s * v)) * u - v) / 2))
        (u * Cdot) t := by
    convert (((hC.const_mul (2 * u)).sub (hasDerivAt_const t v)).const_mul
      ((1 / 2 : ℝ))) using 1
    · ext s
      simp [Pi.sub_apply]
      ring
    · ring
  have hslope :=
    (htraceDeriv_comp.const_mul u).sub (hA.mul htraceSecond_comp)
  convert hslope using 1
  dsimp [C, r, Cdot, A] at *
  field_simp [hr_ne]
  ring

theorem frontierLeftPiece_rankOne_slope_hasDerivAt_along_of_radius_pos
    {x1 x2 u v t : ℝ}
    (hr :
      0 < frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ =>
        u * frontierLeftTraceDeriv
          (frontierCPlus frontierEpsilon (x1 + s * u) (x2 + s * v)) -
          (((2 * frontierCPlus frontierEpsilon
              (x1 + s * u) (x2 + s * v)) * u - v) / 2) *
            frontierLeftTraceSecond
              (frontierCPlus frontierEpsilon (x1 + s * u) (x2 + s * v)))
      ((-(frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v) ^ 2 *
              frontierLeftTraceThird
                (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) /
                frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v))) * u ^ 2 +
        2 * (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v) *
              frontierLeftTraceThird
                (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) /
                (2 * frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v))) *
            u * v +
          (-(frontierLeftTraceThird
                (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) /
              (4 * frontierRadius frontierEpsilon
                (x1 + t * u) (x2 + t * v)))) * v ^ 2) t := by
  exact frontierTraceBranch_rankOne_slope_hasDerivAt_along_of_radius_pos
    (traceDeriv := frontierLeftTraceDeriv)
    (traceSecond := frontierLeftTraceSecond)
    (traceThird := frontierLeftTraceThird)
    (eps := frontierEpsilon) (x1 := x1) (x2 := x2)
    (u := u) (v := v) (t := t) hr
    (frontierLeftTraceDeriv_hasDerivAt
      (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)))
    (frontierLeftTraceSecond_hasDerivAt
      (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)))

theorem frontierRightTailPiece_rankOne_slope_hasDerivAt_along_of_radius_pos
    {x1 x2 u v t : ℝ}
    (hr :
      0 < frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ =>
        u * frontierRightTailTraceDeriv
          (frontierCPlus frontierEpsilon (x1 + s * u) (x2 + s * v)) -
          (((2 * frontierCPlus frontierEpsilon
              (x1 + s * u) (x2 + s * v)) * u - v) / 2) *
            frontierRightTailTraceSecond
              (frontierCPlus frontierEpsilon (x1 + s * u) (x2 + s * v)))
      ((-(frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v) ^ 2 *
              frontierRightTailTraceThird
                (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) /
                frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v))) * u ^ 2 +
        2 * (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v) *
              frontierRightTailTraceThird
                (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) /
                (2 * frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v))) *
            u * v +
          (-(frontierRightTailTraceThird
                (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) /
              (4 * frontierRadius frontierEpsilon
                (x1 + t * u) (x2 + t * v)))) * v ^ 2) t := by
  exact frontierTraceBranch_rankOne_slope_hasDerivAt_along_of_radius_pos
    (traceDeriv := frontierRightTailTraceDeriv)
    (traceSecond := frontierRightTailTraceSecond)
    (traceThird := frontierRightTailTraceThird)
    (eps := frontierEpsilon) (x1 := x1) (x2 := x2)
    (u := u) (v := v) (t := t) hr
    (frontierRightTailTraceDeriv_hasDerivAt
      (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)))
    (frontierRightTailTraceSecond_hasDerivAt
      (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)))

theorem frontierMiddlePiece_rankOne_slope_hasDerivAt_along_of_radius_pos
    {x1 x2 u v t : ℝ}
    (hr :
      0 < frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v)) :
    HasDerivAt
      (fun s : ℝ =>
        u * frontierMiddleTraceDeriv
          (frontierCPlus frontierEpsilon (x1 + s * u) (x2 + s * v)) -
          (((2 * frontierCPlus frontierEpsilon
              (x1 + s * u) (x2 + s * v)) * u - v) / 2) *
            frontierMiddleTraceSecond
              (frontierCPlus frontierEpsilon (x1 + s * u) (x2 + s * v)))
      ((-(frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v) ^ 2 *
              frontierMiddleTraceThird
                (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) /
                frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v))) * u ^ 2 +
        2 * (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v) *
              frontierMiddleTraceThird
                (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) /
                (2 * frontierRadius frontierEpsilon (x1 + t * u) (x2 + t * v))) *
            u * v +
          (-(frontierMiddleTraceThird
                (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)) /
              (4 * frontierRadius frontierEpsilon
                (x1 + t * u) (x2 + t * v)))) * v ^ 2) t := by
  exact frontierTraceBranch_rankOne_slope_hasDerivAt_along_of_radius_pos
    (traceDeriv := frontierMiddleTraceDeriv)
    (traceSecond := frontierMiddleTraceSecond)
    (traceThird := frontierMiddleTraceThird)
    (eps := frontierEpsilon) (x1 := x1) (x2 := x2)
    (u := u) (v := v) (t := t) hr
    (frontierMiddleTraceDeriv_hasDerivAt
      (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)))
    (frontierMiddleTraceSecond_hasDerivAt
      (frontierCPlus frontierEpsilon (x1 + t * u) (x2 + t * v)))

theorem frontierRadius_sq_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    frontierRadius frontierEpsilon x1 x2 ^ 2 =
      frontierEpsilon ^ 2 + x1 ^ 2 - x2 := by
  have harg_nonneg :
      0 ≤ frontierEpsilon ^ 2 + x1 ^ 2 - x2 := by
    nlinarith [hΩ.2]
  rw [frontierRadius]
  exact Real.sq_sqrt harg_nonneg

theorem frontierRadius_le_epsilon_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    frontierRadius frontierEpsilon x1 x2 ≤ frontierEpsilon := by
  have harg_le :
      frontierEpsilon ^ 2 + x1 ^ 2 - x2 ≤ frontierEpsilon ^ 2 := by
    linarith [hΩ.1]
  have hsqrt_le :
      Real.sqrt (frontierEpsilon ^ 2 + x1 ^ 2 - x2) ≤
        Real.sqrt (frontierEpsilon ^ 2) :=
    Real.sqrt_le_sqrt harg_le
  rw [Real.sqrt_sq_eq_abs, abs_of_pos frontierEpsilon_pos] at hsqrt_le
  simpa [frontierRadius] using hsqrt_le

theorem frontierCPlus_sub_x1_nonneg_of_omega
    {x1 x2 : ℝ} (_hΩ : frontierOmega frontierEpsilon x1 x2) :
    0 ≤ frontierCPlus frontierEpsilon x1 x2 - x1 := by
  have hr : 0 ≤ frontierRadius frontierEpsilon x1 x2 :=
    frontierRadius_nonneg frontierEpsilon x1 x2
  rw [frontierCPlus]
  linarith

theorem frontierCPlus_sub_x1_le_epsilon_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    frontierCPlus frontierEpsilon x1 x2 - x1 ≤ frontierEpsilon := by
  have hr : frontierRadius frontierEpsilon x1 x2 ≤ frontierEpsilon :=
    frontierRadius_le_epsilon_of_omega hΩ
  rw [frontierCPlus]
  linarith

theorem frontierCPlus_lower_x1_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    x1 ≤ frontierCPlus frontierEpsilon x1 x2 := by
  have h := frontierCPlus_sub_x1_nonneg_of_omega hΩ
  linarith

theorem frontierCPlus_upper_x1_add_epsilon_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    frontierCPlus frontierEpsilon x1 x2 ≤ x1 + frontierEpsilon := by
  have h := frontierCPlus_sub_x1_le_epsilon_of_omega hΩ
  linarith

theorem frontierRadius_upper_boundary (x1 : ℝ) :
    frontierRadius frontierEpsilon x1 (x1 ^ 2 + frontierEpsilon ^ 2) = 0 := by
  rw [frontierRadius]
  have harg : frontierEpsilon ^ 2 + x1 ^ 2 -
      (x1 ^ 2 + frontierEpsilon ^ 2) = 0 := by
    ring
  rw [harg, Real.sqrt_zero]

theorem frontierCPlus_upper_boundary (x1 : ℝ) :
    frontierCPlus frontierEpsilon x1 (x1 ^ 2 + frontierEpsilon ^ 2) = x1 := by
  rw [frontierCPlus, frontierRadius_upper_boundary]
  ring

theorem frontierRadius_eq_zero_iff_upper_boundary_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    frontierRadius frontierEpsilon x1 x2 = 0 ↔
      x2 = x1 ^ 2 + frontierEpsilon ^ 2 := by
  constructor
  · intro hr
    have hsq := frontierRadius_sq_of_omega hΩ
    rw [hr] at hsq
    linarith
  · intro hx
    rw [hx, frontierRadius_upper_boundary]

theorem frontierRadius_pos_iff_upper_strict_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    0 < frontierRadius frontierEpsilon x1 x2 ↔
      x2 < x1 ^ 2 + frontierEpsilon ^ 2 := by
  constructor
  · intro hr
    have hne : x2 ≠ x1 ^ 2 + frontierEpsilon ^ 2 := by
      intro hx
      have hr0 :
          frontierRadius frontierEpsilon x1 x2 = 0 :=
        (frontierRadius_eq_zero_iff_upper_boundary_of_omega hΩ).2 hx
      linarith
    exact lt_of_le_of_ne hΩ.2 hne
  · intro hupper
    rw [frontierRadius]
    exact Real.sqrt_pos_of_pos (by linarith)

theorem frontierCPlus_eq_x1_of_radius_eq_zero
    {eps x1 x2 : ℝ} (hr : frontierRadius eps x1 x2 = 0) :
    frontierCPlus eps x1 x2 = x1 := by
  rw [frontierCPlus, hr]
  ring

theorem frontierLeftPiece_upper_boundary (x1 : ℝ) :
    frontierLeftPiece x1 (x1 ^ 2 + frontierEpsilon ^ 2) =
      frontierLeftTrace x1 := by
  rw [frontierLeftPiece, frontierLeftTrace, frontierCPlus_upper_boundary,
    frontierRadius_upper_boundary]
  field_simp [frontierEpsilon_ne_zero]
  ring

theorem frontierMiddlePiece_upper_boundary (x1 : ℝ) :
    frontierMiddlePiece x1 (x1 ^ 2 + frontierEpsilon ^ 2) =
      frontierMiddleTrace x1 := by
  rw [frontierMiddlePiece, frontierCPlus_upper_boundary,
    frontierRadius_upper_boundary]
  ring

theorem frontierRightTailPiece_upper_boundary (x1 : ℝ) :
    frontierRightTailPiece x1 (x1 ^ 2 + frontierEpsilon ^ 2) =
      frontierRightTailTrace x1 := by
  rw [frontierRightTailPiece, frontierCPlus_upper_boundary,
    frontierRadius_upper_boundary]
  ring

theorem frontierRightTailPiece_upperBoundary_asymmetric_gap_identity
    (x a : ℝ) (ha : 0 ≤ a) :
    frontierRightTailPiece x (x ^ 2 + frontierEpsilon ^ 2) -
        ((1 / 2 : ℝ) *
            frontierRightTailPiece (x + a)
              ((x + a) ^ 2 + frontierEpsilon ^ 2) +
          (1 / 2 : ℝ) *
            frontierRightTailPiece (x - a)
              ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2)) =
      a ^ 3 * (2 * Real.sqrt 2 - 3) := by
  have hsqrt_two_sq : (Real.sqrt 2) ^ 2 = (2 : ℝ) :=
    Real.sq_sqrt (by norm_num)
  have hz_radius :
      frontierRadius frontierEpsilon (x - a)
          ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) =
        Real.sqrt 2 * a := by
    rw [frontierRadius]
    have harg :
        frontierEpsilon ^ 2 + (x - a) ^ 2 -
            ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) =
          2 * (a * a) := by ring
    rw [harg, Real.sqrt_mul (by norm_num : (0 : ℝ) ≤ 2) (a * a),
      Real.sqrt_mul_self ha]
  have hz_C :
      frontierCPlus frontierEpsilon (x - a)
          ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) =
        x + (Real.sqrt 2 - 1) * a := by
    rw [frontierCPlus, hz_radius]
    ring
  rw [frontierRightTailPiece_upper_boundary,
    frontierRightTailPiece_upper_boundary]
  rw [frontierRightTailPiece_trace_form, hz_radius, hz_C]
  unfold frontierRightTailTrace frontierRightTailTraceDeriv
  ring_nf
  have hsqrt_two_cube : (Real.sqrt 2) ^ 3 = Real.sqrt 2 * (2 : ℝ) := by
    rw [show (Real.sqrt 2) ^ 3 = Real.sqrt 2 * (Real.sqrt 2) ^ 2 by ring,
      hsqrt_two_sq]
  rw [hsqrt_two_sq]
  rw [hsqrt_two_cube]
  ring_nf

theorem two_mul_sqrt_two_sub_three_neg : 2 * Real.sqrt 2 - (3 : ℝ) < 0 := by
  have hsqrt_two_sq : (Real.sqrt 2) ^ 2 = (2 : ℝ) :=
    Real.sq_sqrt (by norm_num)
  have hsqrt_two_nonneg : 0 ≤ Real.sqrt 2 := Real.sqrt_nonneg 2
  nlinarith

theorem frontierRightTailPiece_upperBoundary_asymmetric_gap_strict
    (x a : ℝ) (ha : 0 < a) :
    frontierRightTailPiece x (x ^ 2 + frontierEpsilon ^ 2) <
        (1 / 2 : ℝ) *
            frontierRightTailPiece (x + a)
              ((x + a) ^ 2 + frontierEpsilon ^ 2) +
          (1 / 2 : ℝ) *
            frontierRightTailPiece (x - a)
              ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) := by
  have hid :=
    frontierRightTailPiece_upperBoundary_asymmetric_gap_identity x a
      (le_of_lt ha)
  have hcoef : a ^ 3 * (2 * Real.sqrt 2 - (3 : ℝ)) < 0 :=
    mul_neg_of_pos_of_neg (pow_pos ha 3) two_mul_sqrt_two_sub_three_neg
  linarith

theorem frontierRadius_upperBoundary_asymmetric_lower
    (x a : ℝ) (ha : 0 ≤ a) :
    frontierRadius frontierEpsilon (x - a)
        ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) =
      Real.sqrt 2 * a := by
  rw [frontierRadius]
  have harg :
      frontierEpsilon ^ 2 + (x - a) ^ 2 -
          ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) =
        2 * (a * a) := by ring
  rw [harg, Real.sqrt_mul (by norm_num : (0 : ℝ) ≤ 2) (a * a),
    Real.sqrt_mul_self ha]

theorem frontierCPlus_upperBoundary_asymmetric_lower
    (x a : ℝ) (ha : 0 ≤ a) :
    frontierCPlus frontierEpsilon (x - a)
        ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) =
      x + (Real.sqrt 2 - 1) * a := by
  rw [frontierCPlus, frontierRadius_upperBoundary_asymmetric_lower x a ha]
  ring

theorem sqrt_two_sub_one_pos : 0 < Real.sqrt 2 - (1 : ℝ) := by
  have hsqrt_two_sq : (Real.sqrt 2) ^ 2 = (2 : ℝ) :=
    Real.sq_sqrt (by norm_num)
  have hsqrt_two_nonneg : 0 ≤ Real.sqrt 2 := Real.sqrt_nonneg 2
  nlinarith

theorem frontier_exists_small_asymmetric_parameter
    (x δ : ℝ) (hδ : 0 < δ) :
    ∃ a : ℝ, 0 < a ∧ a < δ ∧
      |(x + a) ^ 2 + frontierEpsilon ^ 2 -
          (x ^ 2 + frontierEpsilon ^ 2)| < δ ∧
      |((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) -
          (x ^ 2 + frontierEpsilon ^ 2)| < δ ∧
      2 * a ^ 2 ≤ frontierEpsilon ^ 2 := by
  let B : ℝ :=
    min (min δ 1)
      (min (frontierEpsilon / 2) (δ / (4 * (|x| + 1))))
  have hxden_pos : 0 < 4 * (|x| + 1) := by
    have hxabs : 0 ≤ |x| := abs_nonneg x
    nlinarith
  have hB_pos : 0 < B := by
    dsimp [B]
    repeat' apply lt_min
    · exact hδ
    · norm_num
    · linarith [frontierEpsilon_pos]
    · exact div_pos hδ hxden_pos
  refine ⟨B / 2, by linarith, ?_, ?_, ?_, ?_⟩
  · have hB_le_delta : B ≤ δ := by
      dsimp [B]
      exact le_trans (min_le_left _ _) (min_le_left _ _)
    linarith
  · have ha_nonneg : 0 ≤ B / 2 := by linarith
    have hB_le_one : B ≤ 1 := by
      dsimp [B]
      exact le_trans (min_le_left _ _) (min_le_right _ _)
    have hB_le_frac : B ≤ δ / (4 * (|x| + 1)) := by
      dsimp [B]
      exact le_trans (min_le_right _ _) (min_le_right _ _)
    have hxabs : |x| ≤ |x| + 1 := by linarith [abs_nonneg x]
    have hmul_small :
        2 * |x| * (B / 2) < δ / 2 := by
      have hmain : (|x| + 1) * B ≤ δ / 4 := by
        have hmul := mul_le_mul_of_nonneg_left hB_le_frac
          (by linarith [abs_nonneg x] : 0 ≤ |x| + 1)
        field_simp [ne_of_gt hxden_pos] at hmul ⊢
        linarith
      nlinarith [abs_nonneg x]
    have hsquare_small : (B / 2) ^ 2 < δ / 2 := by
      have ha_le_one : B / 2 ≤ 1 := by
        linarith [hB_le_one]
      have hmain : (|x| + 1) * B ≤ δ / 4 := by
        have hmul := mul_le_mul_of_nonneg_left hB_le_frac
          (by linarith [abs_nonneg x] : 0 ≤ |x| + 1)
        field_simp [ne_of_gt hxden_pos] at hmul ⊢
        linarith
      have hB_le_delta_quarter : B ≤ δ / 4 := by
        have hB_le_main : B ≤ (|x| + 1) * B := by
          nlinarith [abs_nonneg x, le_of_lt hB_pos]
        linarith
      nlinarith
    calc
      |(x + B / 2) ^ 2 + frontierEpsilon ^ 2 -
          (x ^ 2 + frontierEpsilon ^ 2)|
          = |2 * x * (B / 2) + (B / 2) ^ 2| := by
            congr 1
            ring
      _ ≤ |2 * x * (B / 2)| + |(B / 2) ^ 2| := abs_add_le _ _
      _ = 2 * |x| * (B / 2) + (B / 2) ^ 2 := by
        have hterm : |2 * x * (B / 2)| = 2 * |x| * (B / 2) := by
          rw [abs_mul, abs_mul, abs_of_nonneg (by norm_num : (0 : ℝ) ≤ 2),
            abs_of_nonneg ha_nonneg]
        have hsquare_abs : |(B / 2) ^ 2| = (B / 2) ^ 2 :=
          abs_of_nonneg (sq_nonneg _)
        rw [hterm, hsquare_abs]
      _ < δ := by linarith
  · have ha_nonneg : 0 ≤ B / 2 := by linarith
    have hB_le_frac : B ≤ δ / (4 * (|x| + 1)) := by
      dsimp [B]
      exact le_trans (min_le_right _ _) (min_le_right _ _)
    have hmul_small :
        2 * |x| * (B / 2) < δ / 2 := by
      have hmain : (|x| + 1) * B ≤ δ / 4 := by
        have hmul := mul_le_mul_of_nonneg_left hB_le_frac
          (by linarith [abs_nonneg x] : 0 ≤ |x| + 1)
        field_simp [ne_of_gt hxden_pos] at hmul ⊢
        linarith
      nlinarith [abs_nonneg x]
    have hsquare_small : (B / 2) ^ 2 < δ / 2 := by
      have hB_le_one : B ≤ 1 := by
        dsimp [B]
        exact le_trans (min_le_left _ _) (min_le_right _ _)
      have ha_le_one : B / 2 ≤ 1 := by
        linarith [hB_le_one]
      have hmain : (|x| + 1) * B ≤ δ / 4 := by
        have hmul := mul_le_mul_of_nonneg_left hB_le_frac
          (by linarith [abs_nonneg x] : 0 ≤ |x| + 1)
        field_simp [ne_of_gt hxden_pos] at hmul ⊢
        linarith
      have hB_le_delta_quarter : B ≤ δ / 4 := by
        have hB_le_main : B ≤ (|x| + 1) * B := by
          nlinarith [abs_nonneg x, le_of_lt hB_pos]
        linarith
      nlinarith
    calc
      |((x - B / 2) ^ 2 + frontierEpsilon ^ 2 - 2 * (B / 2) ^ 2) -
          (x ^ 2 + frontierEpsilon ^ 2)|
          = |-(2 * x * (B / 2) + (B / 2) ^ 2)| := by
            congr 1
            ring
      _ = |2 * x * (B / 2) + (B / 2) ^ 2| := abs_neg _
      _ ≤ |2 * x * (B / 2)| + |(B / 2) ^ 2| := abs_add_le _ _
      _ = 2 * |x| * (B / 2) + (B / 2) ^ 2 := by
        have hterm : |2 * x * (B / 2)| = 2 * |x| * (B / 2) := by
          rw [abs_mul, abs_mul, abs_of_nonneg (by norm_num : (0 : ℝ) ≤ 2),
            abs_of_nonneg ha_nonneg]
        have hsquare_abs : |(B / 2) ^ 2| = (B / 2) ^ 2 :=
          abs_of_nonneg (sq_nonneg _)
        rw [hterm, hsquare_abs]
      _ < δ := by linarith
  · have hB_le_eps : B ≤ frontierEpsilon / 2 := by
      dsimp [B]
      exact le_trans (min_le_right _ _) (min_le_left _ _)
    have ha_nonneg : 0 ≤ B / 2 := by linarith
    nlinarith [frontierEpsilon_pos]

theorem frontierMajorant_upper_boundary_left_eq
    (x1 : ℝ) (hleft : x1 ≤ frontierCStar) :
    frontierMajorant x1 (x1 ^ 2 + frontierEpsilon ^ 2) =
      frontierLeftTrace x1 := by
  rw [frontierMajorant, frontierCPlus_upper_boundary, if_pos hleft,
    frontierLeftPiece_upper_boundary]

theorem frontierMajorant_upper_boundary_middle_eq
    (x1 : ℝ) (hleft : frontierCStar < x1)
    (hright : x1 ≤ frontierCStar + 2 * frontierEpsilon) :
    frontierMajorant x1 (x1 ^ 2 + frontierEpsilon ^ 2) =
      frontierMiddleTrace x1 := by
  rw [frontierMajorant, frontierCPlus_upper_boundary,
    if_neg (not_le.mpr hleft), if_pos hright,
    frontierMiddlePiece_upper_boundary]

theorem frontierMajorant_upper_boundary_right_eq
    (x1 : ℝ) (hright : frontierCStar + 2 * frontierEpsilon < x1) :
    frontierMajorant x1 (x1 ^ 2 + frontierEpsilon ^ 2) =
      frontierRightTailTrace x1 := by
  have hnotLeft : ¬ x1 ≤ frontierCStar := by
    linarith [frontierEpsilon_pos]
  have hnotMiddle : ¬ x1 ≤ frontierCStar + 2 * frontierEpsilon :=
    not_le.mpr hright
  rw [frontierMajorant, frontierCPlus_upper_boundary, if_neg hnotLeft,
    if_neg hnotMiddle, frontierRightTailPiece_upper_boundary]

theorem frontierMajorant_leftBranch_radius_zero_upper_boundary
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2)
    (hleft : frontierCPlus frontierEpsilon x1 x2 < frontierCStar)
    (hr : frontierRadius frontierEpsilon x1 x2 = 0) :
    x2 = x1 ^ 2 + frontierEpsilon ^ 2 ∧
      x1 < frontierCStar ∧
        frontierMajorant x1 x2 = frontierLeftTrace x1 := by
  have hx2 :
      x2 = x1 ^ 2 + frontierEpsilon ^ 2 :=
    (frontierRadius_eq_zero_iff_upper_boundary_of_omega hΩ).1 hr
  have hC :
      frontierCPlus frontierEpsilon x1 x2 = x1 :=
    frontierCPlus_eq_x1_of_radius_eq_zero hr
  have hx1 : x1 < frontierCStar := by
    rwa [hC] at hleft
  refine ⟨hx2, hx1, ?_⟩
  rw [hx2]
  exact frontierMajorant_upper_boundary_left_eq x1 (le_of_lt hx1)

theorem frontierMajorant_rightBranch_radius_zero_upper_boundary
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2)
    (hright :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1 x2)
    (hr : frontierRadius frontierEpsilon x1 x2 = 0) :
    x2 = x1 ^ 2 + frontierEpsilon ^ 2 ∧
      frontierCStar + 2 * frontierEpsilon < x1 ∧
        frontierMajorant x1 x2 = frontierRightTailTrace x1 := by
  have hx2 :
      x2 = x1 ^ 2 + frontierEpsilon ^ 2 :=
    (frontierRadius_eq_zero_iff_upper_boundary_of_omega hΩ).1 hr
  have hC :
      frontierCPlus frontierEpsilon x1 x2 = x1 :=
    frontierCPlus_eq_x1_of_radius_eq_zero hr
  have hx1 : frontierCStar + 2 * frontierEpsilon < x1 := by
    rwa [hC] at hright
  refine ⟨hx2, hx1, ?_⟩
  rw [hx2]
  exact frontierMajorant_upper_boundary_right_eq x1 hx1

theorem frontierOmega_upper_boundary (x1 : ℝ) :
    frontierOmega frontierEpsilon x1 (x1 ^ 2 + frontierEpsilon ^ 2) := by
  rw [frontierOmega]
  constructor
  · nlinarith [sq_nonneg frontierEpsilon]
  · rfl

theorem frontier_upperGap_mix_identity
    (y1 y2 z1 z2 θ : ℝ) :
    frontierEpsilon ^ 2 +
          (θ * y1 + (1 - θ) * z1) ^ 2 -
        (θ * y2 + (1 - θ) * z2) =
      θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
          θ * (1 - θ) * (y1 - z1) ^ 2 := by
  ring

theorem frontier_upperGap_mix_nonneg_of_omega
    {y1 y2 z1 z2 θ : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2)) :
    0 ≤
      θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
          θ * (1 - θ) * (y1 - z1) ^ 2 := by
  rw [← frontier_upperGap_mix_identity]
  linarith [hmixΩ.2]

theorem frontier_upperGap_mix_eq_zero_of_radius_eq_zero
    {y1 y2 z1 z2 θ : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hrmix :
      frontierRadius frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) = 0) :
    θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
          θ * (1 - θ) * (y1 - z1) ^ 2 = 0 := by
  have hupper :
      θ * y2 + (1 - θ) * z2 =
        (θ * y1 + (1 - θ) * z1) ^ 2 + frontierEpsilon ^ 2 :=
    (frontierRadius_eq_zero_iff_upper_boundary_of_omega hmixΩ).1 hrmix
  rw [← frontier_upperGap_mix_identity]
  linarith

theorem frontier_upperGap_mix_eq_radius_sq_of_omega
    {y1 y2 z1 z2 θ : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2)) :
    θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
          θ * (1 - θ) * (y1 - z1) ^ 2 =
      frontierRadius frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ^ 2 := by
  rw [← frontier_upperGap_mix_identity]
  exact (frontierRadius_sq_of_omega hmixΩ).symm

theorem frontier_upperGap_mix_eq_zero_iff_radius_eq_zero_of_omega
    {y1 y2 z1 z2 θ : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2)) :
    θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
          (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
            θ * (1 - θ) * (y1 - z1) ^ 2 = 0 ↔
      frontierRadius frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) = 0 := by
  rw [frontier_upperGap_mix_eq_radius_sq_of_omega hmixΩ]
  exact sq_eq_zero_iff

theorem frontier_upperGap_mix_pos_iff_radius_pos_of_omega
    {y1 y2 z1 z2 θ : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2)) :
    0 <
        θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
          (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
            θ * (1 - θ) * (y1 - z1) ^ 2 ↔
      0 < frontierRadius frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) := by
  rw [frontier_upperGap_mix_eq_radius_sq_of_omega hmixΩ]
  constructor
  · intro hsq
    have hr_ne :
        frontierRadius frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) ≠ 0 := by
      exact sq_pos_iff.mp hsq
    exact lt_of_le_of_ne
      (frontierRadius_nonneg frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
      (Ne.symm hr_ne)
  · intro hr
    exact sq_pos_of_pos hr

theorem frontier_upperGap_mix_balance_of_radius_eq_zero
    {y1 y2 z1 z2 θ : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hrmix :
      frontierRadius frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) = 0) :
    θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) =
      θ * (1 - θ) * (y1 - z1) ^ 2 := by
  have hzero :=
    frontier_upperGap_mix_eq_zero_of_radius_eq_zero hmixΩ hrmix
  linarith

theorem frontier_upperGap_nonneg_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    0 ≤ frontierEpsilon ^ 2 + x1 ^ 2 - x2 := by
  linarith [hΩ.2]

theorem frontier_upperGap_le_epsilon_sq_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    frontierEpsilon ^ 2 + x1 ^ 2 - x2 ≤ frontierEpsilon ^ 2 := by
  linarith [hΩ.1]

theorem frontier_upperGap_mix_balance_of_upper_boundary
    {y1 y2 z1 z2 θ : ℝ}
    (hmixUpper :
      θ * y2 + (1 - θ) * z2 =
        (θ * y1 + (1 - θ) * z1) ^ 2 + frontierEpsilon ^ 2) :
    θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) =
      θ * (1 - θ) * (y1 - z1) ^ 2 := by
  have hzero :
      θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
          (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
            θ * (1 - θ) * (y1 - z1) ^ 2 = 0 := by
    rw [← frontier_upperGap_mix_identity]
    linarith
  linarith

theorem frontier_upperGap_mix_rankOne_le_of_upper_boundary
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixUpper :
      θ * y2 + (1 - θ) * z2 =
        (θ * y1 + (1 - θ) * z1) ^ 2 + frontierEpsilon ^ 2)
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    θ * (1 - θ) * (y1 - z1) ^ 2 ≤ frontierEpsilon ^ 2 := by
  have hbalance :=
    frontier_upperGap_mix_balance_of_upper_boundary
      (y1 := y1) (y2 := y2) (z1 := z1) (z2 := z2) (θ := θ)
      hmixUpper
  have hy_le :
      frontierEpsilon ^ 2 + y1 ^ 2 - y2 ≤ frontierEpsilon ^ 2 :=
    frontier_upperGap_le_epsilon_sq_of_omega hyΩ
  have hz_le :
      frontierEpsilon ^ 2 + z1 ^ 2 - z2 ≤ frontierEpsilon ^ 2 :=
    frontier_upperGap_le_epsilon_sq_of_omega hzΩ
  have hθ_nonneg : 0 ≤ 1 - θ := by linarith
  calc
    θ * (1 - θ) * (y1 - z1) ^ 2 =
        θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
          (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) := by
          rw [hbalance]
    _ ≤ θ * frontierEpsilon ^ 2 + (1 - θ) * frontierEpsilon ^ 2 := by
          exact add_le_add
            (mul_le_mul_of_nonneg_left hy_le hθ0)
            (mul_le_mul_of_nonneg_left hz_le hθ_nonneg)
    _ = frontierEpsilon ^ 2 := by ring

theorem frontier_upperGap_mix_rankOne_le_of_mixed_radius_zero
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hrmix :
      frontierRadius frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) = 0)
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    θ * (1 - θ) * (y1 - z1) ^ 2 ≤ frontierEpsilon ^ 2 := by
  have hmixUpper :
      θ * y2 + (1 - θ) * z2 =
        (θ * y1 + (1 - θ) * z1) ^ 2 + frontierEpsilon ^ 2 :=
    (frontierRadius_eq_zero_iff_upper_boundary_of_omega hmixΩ).1 hrmix
  exact frontier_upperGap_mix_rankOne_le_of_upper_boundary
    hyΩ hzΩ hmixUpper hθ0 hθ1

theorem frontier_upperGap_endpoints_upper_boundary_of_mixed_radius_zero_same_x
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hrmix :
      frontierRadius frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) = 0)
    (hyz : y1 = z1) (hθ0 : 0 < θ) (hθ1 : θ < 1) :
    y2 = y1 ^ 2 + frontierEpsilon ^ 2 ∧
      z2 = z1 ^ 2 + frontierEpsilon ^ 2 := by
  have hbalance :=
    frontier_upperGap_mix_balance_of_radius_eq_zero hmixΩ hrmix
  have hygap_nonneg :
      0 ≤ frontierEpsilon ^ 2 + y1 ^ 2 - y2 :=
    frontier_upperGap_nonneg_of_omega hyΩ
  have hzgap_nonneg :
      0 ≤ frontierEpsilon ^ 2 + z1 ^ 2 - z2 :=
    frontier_upperGap_nonneg_of_omega hzΩ
  have hθ_nonneg : 0 ≤ θ := le_of_lt hθ0
  have hone_minus_pos : 0 < 1 - θ := by linarith
  have hone_minus_nonneg : 0 ≤ 1 - θ := le_of_lt hone_minus_pos
  have hweighted :
      θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
          (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) = 0 := by
    simpa [hyz] using hbalance
  have hygap_zero : frontierEpsilon ^ 2 + y1 ^ 2 - y2 = 0 := by
    have hyterm_nonneg :
        0 ≤ θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) :=
      mul_nonneg hθ_nonneg hygap_nonneg
    have hzterm_nonneg :
        0 ≤ (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) :=
      mul_nonneg hone_minus_nonneg hzgap_nonneg
    have hyterm_zero :
        θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) = 0 := by
      nlinarith
    exact mul_eq_zero.mp hyterm_zero |>.resolve_left (ne_of_gt hθ0)
  have hzgap_zero : frontierEpsilon ^ 2 + z1 ^ 2 - z2 = 0 := by
    have hyterm_nonneg :
        0 ≤ θ * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) :=
      mul_nonneg hθ_nonneg hygap_nonneg
    have hzterm_nonneg :
        0 ≤ (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) :=
      mul_nonneg hone_minus_nonneg hzgap_nonneg
    have hzterm_zero :
        (1 - θ) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) = 0 := by
      nlinarith
    exact mul_eq_zero.mp hzterm_zero |>.resolve_left (ne_of_gt hone_minus_pos)
  constructor <;> linarith

theorem frontier_upperGap_segment_identity
    (y1 y2 z1 z2 t : ℝ) :
    frontierEpsilon ^ 2 + (z1 + t * (y1 - z1)) ^ 2 -
        (z2 + t * (y2 - z2)) =
      t * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - t) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
          t * (1 - t) * (y1 - z1) ^ 2 := by
  ring

theorem frontier_upperGap_segment_eq_radius_sq_of_omega
    {y1 y2 z1 z2 t : ℝ}
    (hsegΩ :
      frontierOmega frontierEpsilon
        (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2))) :
    t * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - t) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
          t * (1 - t) * (y1 - z1) ^ 2 =
      frontierRadius frontierEpsilon
        (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)) ^ 2 := by
  rw [← frontier_upperGap_segment_identity]
  exact (frontierRadius_sq_of_omega hsegΩ).symm

theorem frontier_upperGap_segment_eq_zero_of_radius_eq_zero
    {y1 y2 z1 z2 t : ℝ}
    (hsegΩ :
      frontierOmega frontierEpsilon
        (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)))
    (hrseg :
      frontierRadius frontierEpsilon
        (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)) = 0) :
    t * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - t) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
          t * (1 - t) * (y1 - z1) ^ 2 = 0 := by
  rw [frontier_upperGap_segment_eq_radius_sq_of_omega hsegΩ, hrseg]
  ring

theorem frontier_upperGap_segment_balance_of_radius_eq_zero
    {y1 y2 z1 z2 t : ℝ}
    (hsegΩ :
      frontierOmega frontierEpsilon
        (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)))
    (hrseg :
      frontierRadius frontierEpsilon
        (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)) = 0) :
    t * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
        (1 - t) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) =
      t * (1 - t) * (y1 - z1) ^ 2 := by
  have hzero :=
    frontier_upperGap_segment_eq_zero_of_radius_eq_zero hsegΩ hrseg
  linarith

theorem frontier_lowerGap_segment_identity
    (y1 y2 z1 z2 t : ℝ) :
    (z2 + t * (y2 - z2)) - (z1 + t * (y1 - z1)) ^ 2 =
      t * (y2 - y1 ^ 2) + (1 - t) * (z2 - z1 ^ 2) +
        t * (1 - t) * (y1 - z1) ^ 2 := by
  ring

theorem frontier_lowerGap_segment_nonneg_of_omega
    {y1 y2 z1 z2 t : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (ht0 : 0 ≤ t) (ht1 : t ≤ 1) :
    0 ≤ (z2 + t * (y2 - z2)) -
        (z1 + t * (y1 - z1)) ^ 2 := by
  rw [frontier_lowerGap_segment_identity]
  have hy : 0 ≤ y2 - y1 ^ 2 := by linarith [hyΩ.1]
  have hz : 0 ≤ z2 - z1 ^ 2 := by linarith [hzΩ.1]
  have ht1_nonneg : 0 ≤ 1 - t := by linarith
  have hsq : 0 ≤ (y1 - z1) ^ 2 := sq_nonneg _
  nlinarith [mul_nonneg ht0 hy, mul_nonneg ht1_nonneg hz,
    mul_nonneg (mul_nonneg ht0 ht1_nonneg) hsq]

theorem frontier_segment_lower_bound_of_omega
    {y1 y2 z1 z2 t : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (ht0 : 0 ≤ t) (ht1 : t ≤ 1) :
    (z1 + t * (y1 - z1)) ^ 2 ≤ z2 + t * (y2 - z2) := by
  have hgap :=
    frontier_lowerGap_segment_nonneg_of_omega
      (y1 := y1) (y2 := y2) (z1 := z1) (z2 := z2) (t := t)
      hyΩ hzΩ ht0 ht1
  linarith

theorem frontier_segment_omega_iff_upperGap_nonneg_of_endpoint_omega
    {y1 y2 z1 z2 t : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (ht0 : 0 ≤ t) (ht1 : t ≤ 1) :
    frontierOmega frontierEpsilon
        (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)) ↔
      0 ≤
        t * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
          (1 - t) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
            t * (1 - t) * (y1 - z1) ^ 2 := by
  constructor
  · intro hsegΩ
    have hgap :
        0 ≤ frontierEpsilon ^ 2 + (z1 + t * (y1 - z1)) ^ 2 -
            (z2 + t * (y2 - z2)) := by
      linarith [hsegΩ.2]
    simpa [frontier_upperGap_segment_identity] using hgap
  · intro hgap
    have hgap' :
        0 ≤ frontierEpsilon ^ 2 + (z1 + t * (y1 - z1)) ^ 2 -
            (z2 + t * (y2 - z2)) := by
      simpa [frontier_upperGap_segment_identity] using hgap
    refine ⟨?_, ?_⟩
    · exact frontier_segment_lower_bound_of_omega hyΩ hzΩ ht0 ht1
    · linarith

theorem frontier_segment_radius_pos_iff_upperGap_pos
    (y1 y2 z1 z2 t : ℝ) :
    0 < frontierRadius frontierEpsilon
        (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)) ↔
      0 <
        t * (frontierEpsilon ^ 2 + y1 ^ 2 - y2) +
          (1 - t) * (frontierEpsilon ^ 2 + z1 ^ 2 - z2) -
            t * (1 - t) * (y1 - z1) ^ 2 := by
  rw [frontierRadius, Real.sqrt_pos, frontier_upperGap_segment_identity]

theorem frontier_segment_radius_pos_or_eq_of_same_x
    {y1 y2 z1 z2 : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hyz : y1 = z1) :
    (∀ t ∈ Set.Ioo (0 : ℝ) 1,
      0 < frontierRadius frontierEpsilon
        (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2))) ∨
      (y1 = z1 ∧ y2 = z2) := by
  by_cases hy2z2 : y2 = z2
  · exact Or.inr ⟨hyz, hy2z2⟩
  · refine Or.inl ?_
    intro t ht
    have ht0 : 0 < t := ht.1
    have ht1 : t < 1 := ht.2
    have ht0_nonneg : 0 ≤ t := le_of_lt ht0
    have ht1_nonneg : 0 ≤ 1 - t := by linarith
    have hsegΩ :
        frontierOmega frontierEpsilon
          (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)) := by
      rw [hyz]
      have hlower :
          z1 ^ 2 ≤ z2 + t * (y2 - z2) := by
        have hy_lower : z1 ^ 2 ≤ y2 := by
          rw [← hyz]
          exact hyΩ.1
        have hz_lower : z1 ^ 2 ≤ z2 := hzΩ.1
        have hconv :
            z2 + t * (y2 - z2) =
              t * y2 + (1 - t) * z2 := by ring
        rw [hconv]
        nlinarith [mul_le_mul_of_nonneg_left hy_lower ht0_nonneg,
          mul_le_mul_of_nonneg_left hz_lower ht1_nonneg]
      have hupper :
          z2 + t * (y2 - z2) ≤ z1 ^ 2 + frontierEpsilon ^ 2 := by
        have hy_upper : y2 ≤ z1 ^ 2 + frontierEpsilon ^ 2 := by
          rw [← hyz]
          exact hyΩ.2
        have hz_upper : z2 ≤ z1 ^ 2 + frontierEpsilon ^ 2 := hzΩ.2
        have hconv :
            z2 + t * (y2 - z2) =
              t * y2 + (1 - t) * z2 := by ring
        rw [hconv]
        nlinarith [mul_le_mul_of_nonneg_left hy_upper ht0_nonneg,
          mul_le_mul_of_nonneg_left hz_upper ht1_nonneg]
      simpa using And.intro hlower hupper
    have hupper_strict :
        z2 + t * (y2 - z2) < z1 ^ 2 + frontierEpsilon ^ 2 := by
      by_cases hy_top : y2 = z1 ^ 2 + frontierEpsilon ^ 2
      · have hz_strict : z2 < z1 ^ 2 + frontierEpsilon ^ 2 := by
          exact lt_of_le_of_ne hzΩ.2 (by
            intro hz_top
            exact hy2z2 (by rw [hy_top, hz_top]))
        have hconv :
            z2 + t * (y2 - z2) =
              t * y2 + (1 - t) * z2 := by ring
        rw [hconv, hy_top]
        nlinarith
      · have hy_strict : y2 < z1 ^ 2 + frontierEpsilon ^ 2 := by
          have hy_upper : y2 ≤ z1 ^ 2 + frontierEpsilon ^ 2 := by
            rw [← hyz]
            exact hyΩ.2
          exact lt_of_le_of_ne hy_upper hy_top
        have hconv :
            z2 + t * (y2 - z2) =
              t * y2 + (1 - t) * z2 := by ring
        rw [hconv]
        nlinarith [hzΩ.2]
    have hseg_upper_strict :
        z2 + t * (y2 - z2) <
          (z1 + t * (y1 - z1)) ^ 2 + frontierEpsilon ^ 2 := by
      rw [hyz]
      simpa using hupper_strict
    exact (frontierRadius_pos_iff_upper_strict_of_omega hsegΩ).2
      hseg_upper_strict

theorem frontier_upperBoundary_mix_omega_eq_of_theta_mem
    {y z θ : ℝ} (hθ0 : 0 < θ) (hθ1 : θ < 1)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y + (1 - θ) * z)
        (θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2))) :
    y = z := by
  have hupper := hmixΩ.2
  have hdiff :
      θ * (1 - θ) * (y - z) ^ 2 ≤ 0 := by
    nlinarith
  have hcoef_pos : 0 < θ * (1 - θ) := by
    nlinarith
  have hsq_nonpos : (y - z) ^ 2 ≤ 0 := by
    nlinarith
  have hsq_zero : (y - z) ^ 2 = 0 :=
    le_antisymm hsq_nonpos (sq_nonneg _)
  nlinarith

theorem frontierMajorant_upperBoundary_leftBranch_jensen
    {y z θ : ℝ} (_hy : y ≤ frontierCStar) (hz : z ≤ frontierCStar)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y + (1 - θ) * z)
        (θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierMajorant
        (θ * y + (1 - θ) * z)
        (θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)) ≥
      θ * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) +
        (1 - θ) * frontierMajorant z (z ^ 2 + frontierEpsilon ^ 2) := by
  by_cases hθ_left : θ = 0
  · subst θ
    simp
  · by_cases hθ_right : θ = 1
    · subst θ
      simp
    · have hθ0' : 0 < θ := lt_of_le_of_ne hθ0 (Ne.symm hθ_left)
      have hθ1' : θ < 1 := lt_of_le_of_ne hθ1 hθ_right
      have hyz : y = z :=
        frontier_upperBoundary_mix_omega_eq_of_theta_mem hθ0' hθ1' hmixΩ
      subst z
      rw [show θ * y + (1 - θ) * y = y by ring,
        show θ * (y ^ 2 + frontierEpsilon ^ 2) +
            (1 - θ) * (y ^ 2 + frontierEpsilon ^ 2) =
              y ^ 2 + frontierEpsilon ^ 2 by ring,
        show θ * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) +
            (1 - θ) * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) =
              frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) by ring]

theorem frontierMajorant_upperBoundary_rightBranch_jensen
    {y z θ : ℝ}
    (_hy : frontierCStar + 2 * frontierEpsilon < y)
    (hz : frontierCStar + 2 * frontierEpsilon < z)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y + (1 - θ) * z)
        (θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierMajorant
        (θ * y + (1 - θ) * z)
        (θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)) ≥
      θ * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) +
        (1 - θ) * frontierMajorant z (z ^ 2 + frontierEpsilon ^ 2) := by
  by_cases hθ_left : θ = 0
  · subst θ
    simp
  · by_cases hθ_right : θ = 1
    · subst θ
      simp
    · have hθ0' : 0 < θ := lt_of_le_of_ne hθ0 (Ne.symm hθ_left)
      have hθ1' : θ < 1 := lt_of_le_of_ne hθ1 hθ_right
      have hyz : y = z :=
        frontier_upperBoundary_mix_omega_eq_of_theta_mem hθ0' hθ1' hmixΩ
      subst z
      rw [show θ * y + (1 - θ) * y = y by ring,
        show θ * (y ^ 2 + frontierEpsilon ^ 2) +
            (1 - θ) * (y ^ 2 + frontierEpsilon ^ 2) =
              y ^ 2 + frontierEpsilon ^ 2 by ring,
        show θ * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) +
            (1 - θ) * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) =
              frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) by ring]

theorem frontierMajorant_upperBoundary_jensen
    {y z θ : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y + (1 - θ) * z)
        (θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierMajorant
        (θ * y + (1 - θ) * z)
        (θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)) ≥
      θ * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) +
        (1 - θ) * frontierMajorant z (z ^ 2 + frontierEpsilon ^ 2) := by
  by_cases hθ_left : θ = 0
  · subst θ
    simp
  · by_cases hθ_right : θ = 1
    · subst θ
      simp
    · have hθ0' : 0 < θ := lt_of_le_of_ne hθ0 (Ne.symm hθ_left)
      have hθ1' : θ < 1 := lt_of_le_of_ne hθ1 hθ_right
      have hyz : y = z :=
        frontier_upperBoundary_mix_omega_eq_of_theta_mem hθ0' hθ1' hmixΩ
      subst z
      rw [show θ * y + (1 - θ) * y = y by ring,
        show θ * (y ^ 2 + frontierEpsilon ^ 2) +
            (1 - θ) * (y ^ 2 + frontierEpsilon ^ 2) =
              y ^ 2 + frontierEpsilon ^ 2 by ring,
        show θ * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) +
            (1 - θ) * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) =
              frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) by ring]

theorem frontierMajorant_upperBoundary_jensen_of_endpoint_eq
    {y1 y2 z1 z2 θ : ℝ}
    (hy2 : y2 = y1 ^ 2 + frontierEpsilon ^ 2)
    (hz2 : z2 = z1 ^ 2 + frontierEpsilon ^ 2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierMajorant
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ≥
      θ * frontierMajorant y1 y2 +
        (1 - θ) * frontierMajorant z1 z2 := by
  subst y2
  subst z2
  exact frontierMajorant_upperBoundary_jensen hmixΩ hθ0 hθ1

theorem frontierMajorant_upperBoundary_endpoint_localConcavity
    (x1 : ℝ) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ →
        |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
        |z1 - x1| < δ →
        |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
        y2 = y1 ^ 2 + frontierEpsilon ^ 2 →
        z2 = z1 ^ 2 + frontierEpsilon ^ 2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  refine ⟨1, by norm_num, ?_⟩
  intro y1 y2 z1 z2 θ _hy1 _hy2 _hz1 _hz2 hy2 hz2 hmixΩ hθ0 hθ1
  exact frontierMajorant_upperBoundary_jensen_of_endpoint_eq
    hy2 hz2 hmixΩ hθ0 hθ1

theorem frontierBoundaryMajorantResidualBudget_upperBoundaryEndpointBellmanSplit
    {y z θ : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y + (1 - θ) * z)
        (θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    θ * (frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) -
        frontierPhi y) +
        (1 - θ) *
          (frontierMajorant z (z ^ 2 + frontierEpsilon ^ 2) -
            frontierPhi z) ≤
      frontierMajorant
          (θ * y + (1 - θ) * z)
          (θ * (y ^ 2 + frontierEpsilon ^ 2) +
            (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)) -
        (θ * frontierPhi y + (1 - θ) * frontierPhi z) := by
  have hbellman :
      frontierMajorant
          (θ * y + (1 - θ) * z)
          (θ * (y ^ 2 + frontierEpsilon ^ 2) +
            (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)) ≥
        θ * frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * frontierMajorant z (z ^ 2 + frontierEpsilon ^ 2) :=
    frontierMajorant_upperBoundary_jensen hmixΩ hθ0 hθ1
  nlinarith

theorem frontierBoundaryMajorantResidualBudget_upperBoundaryEndpointTwoPointCenter
    {y z θ : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y + (1 - θ) * z)
        (θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2)))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1)
    (hmix_mean : θ * y + (1 - θ) * z = 0)
    (hmix_second :
      θ * (y ^ 2 + frontierEpsilon ^ 2) +
          (1 - θ) * (z ^ 2 + frontierEpsilon ^ 2) =
        (1 / 12 : ℝ)) :
    θ * (frontierMajorant y (y ^ 2 + frontierEpsilon ^ 2) -
        frontierPhi y) +
        (1 - θ) *
          (frontierMajorant z (z ^ 2 + frontierEpsilon ^ 2) -
            frontierPhi z) ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        (θ * frontierPhi y + (1 - θ) * frontierPhi z) := by
  have hsplit :=
    frontierBoundaryMajorantResidualBudget_upperBoundaryEndpointBellmanSplit
      hmixΩ hθ0 hθ1
  simpa [hmix_mean, hmix_second] using hsplit

theorem frontier_two_epsilon_cubed :
    2 * frontierEpsilon ^ 3 = frontierEpsilon / 6 := by
  calc
    2 * frontierEpsilon ^ 3 = 2 * frontierEpsilon * frontierEpsilon ^ 2 := by ring
    _ = 2 * frontierEpsilon * (1 / 12 : ℝ) := by rw [frontierEpsilon_sq]
    _ = frontierEpsilon / 6 := by ring

theorem frontierEpsilon_cube :
    frontierEpsilon ^ 3 = frontierEpsilon / 12 := by
  calc
    frontierEpsilon ^ 3 = frontierEpsilon * frontierEpsilon ^ 2 := by ring
    _ = frontierEpsilon * (1 / 12 : ℝ) := by rw [frontierEpsilon_sq]
    _ = frontierEpsilon / 12 := by ring

theorem frontierEpsilon_fourth :
    frontierEpsilon ^ 4 = (1 / 144 : ℝ) := by
  calc
    frontierEpsilon ^ 4 = frontierEpsilon ^ 2 * frontierEpsilon ^ 2 := by ring
    _ = (1 / 12 : ℝ) * (1 / 12 : ℝ) := by rw [frontierEpsilon_sq]
    _ = (1 / 144 : ℝ) := by norm_num

theorem frontierEpsilon_fifth :
    frontierEpsilon ^ 5 = frontierEpsilon / 144 := by
  calc
    frontierEpsilon ^ 5 = frontierEpsilon * frontierEpsilon ^ 4 := by ring
    _ = frontierEpsilon * (1 / 144 : ℝ) := by rw [frontierEpsilon_fourth]
    _ = frontierEpsilon / 144 := by ring

theorem frontierEpsilon_sixth :
    frontierEpsilon ^ 6 = (1 / 1728 : ℝ) := by
  calc
    frontierEpsilon ^ 6 = frontierEpsilon ^ 2 * frontierEpsilon ^ 4 := by ring
    _ = (1 / 12 : ℝ) * (1 / 144 : ℝ) := by
      rw [frontierEpsilon_sq, frontierEpsilon_fourth]
    _ = (1 / 1728 : ℝ) := by norm_num

theorem frontierEpsilon_seventh :
    frontierEpsilon ^ 7 = frontierEpsilon / 1728 := by
  calc
    frontierEpsilon ^ 7 = frontierEpsilon * frontierEpsilon ^ 6 := by ring
    _ = frontierEpsilon * (1 / 1728 : ℝ) := by rw [frontierEpsilon_sixth]
    _ = frontierEpsilon / 1728 := by ring

theorem frontierEpsilon_ninth :
    frontierEpsilon ^ 9 = frontierEpsilon / 20736 := by
  calc
    frontierEpsilon ^ 9 = frontierEpsilon * frontierEpsilon ^ 8 := by ring
    _ = frontierEpsilon * (frontierEpsilon ^ 4 * frontierEpsilon ^ 4) := by ring
    _ = frontierEpsilon * ((1 / 144 : ℝ) * (1 / 144 : ℝ)) := by
      rw [frontierEpsilon_fourth]
    _ = frontierEpsilon / 20736 := by ring

theorem frontierCStar_eq :
    frontierCStar = 10 + Real.sqrt 3 / 36 := by
  have hs_nonneg : 0 ≤ (3 : ℝ) := by norm_num
  have hs : (Real.sqrt 3) ^ 2 = (3 : ℝ) := Real.sq_sqrt hs_nonneg
  rw [frontierCStar, frontierA, frontierEpsilon]
  calc
    (10 : ℝ) + 2 * (Real.sqrt 3 / 6) ^ 3 =
        10 + Real.sqrt 3 / 36 := by
      rw [bmo_contact_cubic_identity (Real.sqrt 3) hs]

theorem frontierCStar_sub_epsilon_lt_A :
    frontierCStar - frontierEpsilon < frontierA := by
  rw [frontierCStar]
  nlinarith [frontierEpsilon_pos, frontierEpsilon_sq]

theorem frontierCStar_div_epsilon :
    frontierCStar / frontierEpsilon = 20 * Real.sqrt 3 + (1 / 6 : ℝ) := by
  have hs_nonneg : 0 ≤ (3 : ℝ) := by norm_num
  have hs : (Real.sqrt 3) ^ 2 = (3 : ℝ) := Real.sq_sqrt hs_nonneg
  have hs0 : Real.sqrt 3 ≠ 0 := Real.sqrt_ne_zero'.2 (by norm_num)
  rw [frontierCStar_eq, frontierEpsilon]
  exact bmo_contact_exponent_identity (Real.sqrt 3) hs hs0

theorem frontierKL_eq_public_weight :
    frontierKL =
      (Real.sqrt 3 / 6) * Real.exp (-(20 * Real.sqrt 3 + (1 / 6 : ℝ))) := by
  rw [frontierKL, frontierCStar_div_epsilon, frontierEpsilon]

theorem frontierKL_pos : 0 < frontierKL := by
  rw [frontierKL]
  exact mul_pos frontierEpsilon_pos (Real.exp_pos _)

theorem frontierKL_mul_exp_CStar_div :
    frontierKL * Real.exp (frontierCStar / frontierEpsilon) =
      frontierEpsilon := by
  rw [frontierKL]
  calc
    frontierEpsilon * Real.exp (-(frontierCStar / frontierEpsilon)) *
        Real.exp (frontierCStar / frontierEpsilon) =
        frontierEpsilon *
          (Real.exp (-(frontierCStar / frontierEpsilon)) *
            Real.exp (frontierCStar / frontierEpsilon)) := by
      ring
    _ = frontierEpsilon *
          Real.exp (-(frontierCStar / frontierEpsilon) +
            frontierCStar / frontierEpsilon) := by
      rw [Real.exp_add]
    _ = frontierEpsilon := by
      rw [show -(frontierCStar / frontierEpsilon) +
          frontierCStar / frontierEpsilon = 0 by ring]
      rw [Real.exp_zero]
      ring

theorem frontierKL_div_epsilon_mul_exp_CStar_div :
    frontierKL / frontierEpsilon * Real.exp (frontierCStar / frontierEpsilon) =
      1 := by
  calc
    frontierKL / frontierEpsilon * Real.exp (frontierCStar / frontierEpsilon) =
        (frontierKL * Real.exp (frontierCStar / frontierEpsilon)) /
          frontierEpsilon := by
      ring
    _ = frontierEpsilon / frontierEpsilon := by
      rw [frontierKL_mul_exp_CStar_div]
    _ = 1 := by
      exact div_self frontierEpsilon_ne_zero

theorem frontierKL_div_epsilon_sq_mul_exp_CStar_div :
    frontierKL / frontierEpsilon ^ 2 *
        Real.exp (frontierCStar / frontierEpsilon) =
      12 * frontierEpsilon := by
  calc
    frontierKL / frontierEpsilon ^ 2 *
        Real.exp (frontierCStar / frontierEpsilon) =
        (frontierKL * Real.exp (frontierCStar / frontierEpsilon)) /
          frontierEpsilon ^ 2 := by
      ring
    _ = frontierEpsilon / frontierEpsilon ^ 2 := by
      rw [frontierKL_mul_exp_CStar_div]
    _ = 12 * frontierEpsilon := by
      field_simp [frontierEpsilon_ne_zero]
      rw [frontierEpsilon_sq]
      ring

theorem frontierLeftTraceThird_nonneg (C : ℝ) :
    0 ≤ frontierLeftTraceThird C := by
  rw [frontierLeftTraceThird]
  have hcoef : 0 ≤ frontierKL / frontierEpsilon ^ 3 := by
    exact div_nonneg (le_of_lt frontierKL_pos)
      (pow_nonneg (le_of_lt frontierEpsilon_pos) 3)
  have hexp : 0 ≤ Real.exp (C / frontierEpsilon) := le_of_lt (Real.exp_pos _)
  nlinarith [mul_nonneg hcoef hexp]

theorem frontierMiddleTraceThird_eq_zero (C : ℝ) :
    frontierMiddleTraceThird C = 0 := by
  rfl

theorem frontierMiddleTraceThird_nonneg (C : ℝ) :
    0 ≤ frontierMiddleTraceThird C := by
  rw [frontierMiddleTraceThird_eq_zero]

theorem frontierMiddlePiece_affine_formula_of_omega
    {x1 x2 : ℝ} (hΩ : frontierOmega frontierEpsilon x1 x2) :
    frontierMiddlePiece x1 x2 =
      frontierLeftTrace frontierCStar +
        frontierLeftTraceDeriv frontierCStar * (x1 - frontierCStar) +
          (3 * frontierCStar + 6 * frontierEpsilon) *
            (x2 - 2 * frontierCStar * x1 + frontierCStar ^ 2 -
              frontierEpsilon ^ 2) := by
  rcases hΩ with ⟨_hlower, hupper⟩
  have harg_nonneg :
      0 ≤ frontierEpsilon ^ 2 + x1 ^ 2 - x2 := by
    linarith
  rw [frontierMiddlePiece, frontierMiddleTrace, frontierMiddleTraceDeriv,
    frontierCPlus, frontierRadius]
  set r : ℝ := Real.sqrt (frontierEpsilon ^ 2 + x1 ^ 2 - x2)
  have hr2 : r ^ 2 = frontierEpsilon ^ 2 + x1 ^ 2 - x2 := by
    dsimp [r]
    exact Real.sq_sqrt harg_nonneg
  calc
    frontierLeftTrace frontierCStar +
            frontierLeftTraceDeriv frontierCStar * (x1 + r - frontierCStar) +
          (3 * frontierCStar + 6 * frontierEpsilon) *
              (x1 + r - frontierCStar) ^ 2 -
        r *
          (frontierLeftTraceDeriv frontierCStar +
            2 * (3 * frontierCStar + 6 * frontierEpsilon) *
              (x1 + r - frontierCStar)) =
        frontierLeftTrace frontierCStar +
          frontierLeftTraceDeriv frontierCStar * (x1 - frontierCStar) +
            (3 * frontierCStar + 6 * frontierEpsilon) *
              ((x1 - frontierCStar) ^ 2 - r ^ 2) := by
      ring
    _ =
      frontierLeftTrace frontierCStar +
        frontierLeftTraceDeriv frontierCStar * (x1 - frontierCStar) +
          (3 * frontierCStar + 6 * frontierEpsilon) *
            (x2 - 2 * frontierCStar * x1 + frontierCStar ^ 2 -
              frontierEpsilon ^ 2) := by
      rw [hr2]
      ring

theorem frontierMiddlePiece_affine_combo_of_omega
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2)) :
    frontierMiddlePiece
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) =
      θ * frontierMiddlePiece y1 y2 +
        (1 - θ) * frontierMiddlePiece z1 z2 := by
  rw [frontierMiddlePiece_affine_formula_of_omega hmixΩ,
    frontierMiddlePiece_affine_formula_of_omega hyΩ,
    frontierMiddlePiece_affine_formula_of_omega hzΩ]
  ring

theorem frontierMajorant_eq_middlePiece_of_CPlus
    {x1 x2 : ℝ}
    (hleft : frontierCStar < frontierCPlus frontierEpsilon x1 x2)
    (hright :
      frontierCPlus frontierEpsilon x1 x2 ≤
        frontierCStar + 2 * frontierEpsilon) :
    frontierMajorant x1 x2 = frontierMiddlePiece x1 x2 := by
  rw [frontierMajorant]
  exact if_neg (not_le.mpr hleft) ▸ if_pos hright

theorem frontierMajorant_eq_leftPiece_of_CPlus
    {x1 x2 : ℝ}
    (hleft : frontierCPlus frontierEpsilon x1 x2 ≤ frontierCStar) :
    frontierMajorant x1 x2 = frontierLeftPiece x1 x2 := by
  rw [frontierMajorant]
  exact if_pos hleft

theorem frontierMajorant_eq_leftPiece_of_leftBranchDomain
    {x1 x2 : ℝ} (hD : frontierLeftBranchDomain x1 x2) :
    frontierMajorant x1 x2 = frontierLeftPiece x1 x2 := by
  exact frontierMajorant_eq_leftPiece_of_CPlus (le_of_lt hD)

theorem frontierMajorant_eq_rightTailPiece_of_CPlus
    {x1 x2 : ℝ}
    (hright :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1 x2) :
    frontierMajorant x1 x2 = frontierRightTailPiece x1 x2 := by
  rw [frontierMajorant]
  have hnotLeft :
      ¬ frontierCPlus frontierEpsilon x1 x2 ≤ frontierCStar := by
    linarith [frontierEpsilon_pos]
  have hnotMiddle :
      ¬ frontierCPlus frontierEpsilon x1 x2 ≤
        frontierCStar + 2 * frontierEpsilon :=
    not_le.mpr hright
  rw [if_neg hnotLeft, if_neg hnotMiddle]

theorem frontierMajorant_eq_rightTailPiece_of_rightBranchDomain
    {x1 x2 : ℝ} (hD : frontierRightBranchDomain x1 x2) :
    frontierMajorant x1 x2 = frontierRightTailPiece x1 x2 := by
  exact frontierMajorant_eq_rightTailPiece_of_CPlus hD

theorem frontierMajorant_upperBoundary_rightTail_not_localConcavity
    {x : ℝ} (hx_right : frontierCStar + 2 * frontierEpsilon < x) :
    ¬ frontierMajorantLocalConcavityAt x
      (x ^ 2 + frontierEpsilon ^ 2) := by
  intro hlocal
  rcases hlocal with ⟨δ, hδ_pos, hJensen⟩
  rcases frontier_exists_small_asymmetric_parameter x δ hδ_pos with
    ⟨a, ha_pos, ha_delta, hy2_close, hz2_close, ha_eps⟩
  have ha_nonneg : 0 ≤ a := le_of_lt ha_pos
  have hy1_close : |x + a - x| < δ := by
    rw [show x + a - x = a by ring, abs_of_pos ha_pos]
    exact ha_delta
  have hz1_close : |x - a - x| < δ := by
    rw [show x - a - x = -a by ring, abs_neg, abs_of_pos ha_pos]
    exact ha_delta
  have hyΩ :
      frontierOmega frontierEpsilon (x + a)
        ((x + a) ^ 2 + frontierEpsilon ^ 2) :=
    frontierOmega_upper_boundary (x + a)
  have hzΩ :
      frontierOmega frontierEpsilon (x - a)
        ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) := by
    rw [frontierOmega]
    constructor
    · nlinarith
    · nlinarith
  have hmixΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * (x + a) + (1 - (1 / 2 : ℝ)) * (x - a))
        ((1 / 2 : ℝ) * ((x + a) ^ 2 + frontierEpsilon ^ 2) +
          (1 - (1 / 2 : ℝ)) *
            ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2)) := by
    convert frontierOmega_upper_boundary x using 1 <;> ring
  have hJ :=
    hJensen (x + a) ((x + a) ^ 2 + frontierEpsilon ^ 2)
      (x - a) ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2)
      (1 / 2 : ℝ)
      hy1_close hy2_close hz1_close hz2_close hyΩ hzΩ hmixΩ
      (by norm_num) (by norm_num)
  have hJ' :
      frontierMajorant x (x ^ 2 + frontierEpsilon ^ 2) ≥
        (1 / 2 : ℝ) *
            frontierMajorant (x + a)
              ((x + a) ^ 2 + frontierEpsilon ^ 2) +
          (1 / 2 : ℝ) *
            frontierMajorant (x - a)
              ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) := by
    convert hJ using 1 <;> ring_nf
  have hx_majorant :
      frontierMajorant x (x ^ 2 + frontierEpsilon ^ 2) =
        frontierRightTailPiece x (x ^ 2 + frontierEpsilon ^ 2) := by
    exact frontierMajorant_eq_rightTailPiece_of_CPlus (by
      rw [frontierCPlus_upper_boundary]
      exact hx_right)
  have hy_majorant :
      frontierMajorant (x + a)
          ((x + a) ^ 2 + frontierEpsilon ^ 2) =
        frontierRightTailPiece (x + a)
          ((x + a) ^ 2 + frontierEpsilon ^ 2) := by
    exact frontierMajorant_eq_rightTailPiece_of_CPlus (by
      rw [frontierCPlus_upper_boundary]
      linarith)
  have hz_majorant :
      frontierMajorant (x - a)
          ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) =
        frontierRightTailPiece (x - a)
          ((x - a) ^ 2 + frontierEpsilon ^ 2 - 2 * a ^ 2) := by
    exact frontierMajorant_eq_rightTailPiece_of_CPlus (by
      rw [frontierCPlus_upperBoundary_asymmetric_lower x a ha_nonneg]
      nlinarith [hx_right, mul_pos sqrt_two_sub_one_pos ha_pos])
  rw [hx_majorant, hy_majorant, hz_majorant] at hJ'
  have hstrict :=
    frontierRightTailPiece_upperBoundary_asymmetric_gap_strict x a ha_pos
  linarith

theorem frontierMajorant_upperBoundary_rightTailPoint_not_localConcavity :
    ¬ frontierMajorantLocalConcavityAt
      (frontierCStar + 3 * frontierEpsilon)
      ((frontierCStar + 3 * frontierEpsilon) ^ 2 + frontierEpsilon ^ 2) := by
  exact frontierMajorant_upperBoundary_rightTail_not_localConcavity (by
    linarith [frontierEpsilon_pos])

theorem frontiermajorant_upperboundary_localconcavity_false :
    ¬ (∀ x1 : ℝ,
      frontierMajorantLocalConcavityAt x1
        (x1 ^ 2 + frontierEpsilon ^ 2)) := by
  intro hlocal
  exact frontierMajorant_upperBoundary_rightTailPoint_not_localConcavity
    (hlocal (frontierCStar + 3 * frontierEpsilon))

theorem frontierMajorant_upperBoundary_localConcavity_false :
    ¬ (∀ x1 : ℝ,
      frontierMajorantLocalConcavityAt x1
        (x1 ^ 2 + frontierEpsilon ^ 2)) :=
  frontiermajorant_upperboundary_localconcavity_false

theorem frontierMajorant_upperBoundary_localConcavity_obstruction :
    ¬ (∀ x1 : ℝ,
      frontierMajorantLocalConcavityAt x1
        (x1 ^ 2 + frontierEpsilon ^ 2)) :=
  frontierMajorant_upperBoundary_localConcavity_false

theorem frontierMajorant_upperBoundary_localConcavity_target_contradiction
    (hlocal :
      ∀ x1 : ℝ,
        frontierMajorantLocalConcavityAt x1
          (x1 ^ 2 + frontierEpsilon ^ 2)) :
    False :=
  frontierMajorant_upperBoundary_localConcavity_obstruction hlocal

theorem frontierMajorantLocallyConcaveOnStrip_obstruction :
    ¬ frontierMajorantLocallyConcaveOnStrip := by
  intro hstrip
  exact frontierMajorant_upperBoundary_rightTailPoint_not_localConcavity
    (hstrip (frontierCStar + 3 * frontierEpsilon)
      ((frontierCStar + 3 * frontierEpsilon) ^ 2 + frontierEpsilon ^ 2)
      (frontierOmega_upper_boundary (frontierCStar + 3 * frontierEpsilon)))

theorem frontierMajorant_middleBranch_jensen_eq
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hy_left : frontierCStar < frontierCPlus frontierEpsilon y1 y2)
    (hy_right :
      frontierCPlus frontierEpsilon y1 y2 ≤
        frontierCStar + 2 * frontierEpsilon)
    (hz_left : frontierCStar < frontierCPlus frontierEpsilon z1 z2)
    (hz_right :
      frontierCPlus frontierEpsilon z1 z2 ≤
        frontierCStar + 2 * frontierEpsilon)
    (hmix_left :
      frontierCStar <
        frontierCPlus frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2))
    (hmix_right :
      frontierCPlus frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) ≤
        frontierCStar + 2 * frontierEpsilon) :
    frontierMajorant
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) =
      θ * frontierMajorant y1 y2 +
        (1 - θ) * frontierMajorant z1 z2 := by
  rw [frontierMajorant_eq_middlePiece_of_CPlus hmix_left hmix_right,
    frontierMajorant_eq_middlePiece_of_CPlus hy_left hy_right,
    frontierMajorant_eq_middlePiece_of_CPlus hz_left hz_right,
    frontierMiddlePiece_affine_combo_of_omega hyΩ hzΩ hmixΩ]

theorem frontierMajorant_middleBranch_jensen_concave
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hy_left : frontierCStar < frontierCPlus frontierEpsilon y1 y2)
    (hy_right :
      frontierCPlus frontierEpsilon y1 y2 ≤
        frontierCStar + 2 * frontierEpsilon)
    (hz_left : frontierCStar < frontierCPlus frontierEpsilon z1 z2)
    (hz_right :
      frontierCPlus frontierEpsilon z1 z2 ≤
        frontierCStar + 2 * frontierEpsilon)
    (hmix_left :
      frontierCStar <
        frontierCPlus frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2))
    (hmix_right :
      frontierCPlus frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) ≤
        frontierCStar + 2 * frontierEpsilon) :
    frontierMajorant
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ≥
      θ * frontierMajorant y1 y2 +
        (1 - θ) * frontierMajorant z1 z2 := by
  rw [frontierMajorant_middleBranch_jensen_eq hyΩ hzΩ hmixΩ
    hy_left hy_right hz_left hz_right hmix_left hmix_right]

theorem frontierMajorant_middleBranchDomain_jensen_concave
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hyD : frontierMiddleBranchDomain y1 y2)
    (hzD : frontierMiddleBranchDomain z1 z2)
    (hmixD :
      frontierMiddleBranchDomain
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2)) :
    frontierMajorant
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ≥
      θ * frontierMajorant y1 y2 +
        (1 - θ) * frontierMajorant z1 z2 := by
  exact frontierMajorant_middleBranch_jensen_concave hyΩ hzΩ hmixΩ
    hyD.1 hyD.2 hzD.1 hzD.2 hmixD.1 hmixD.2

theorem frontierBoundaryMajorantResidualBudget_middleBranchBellmanSplit
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hyD : frontierMiddleBranchDomain y1 y2)
    (hzD : frontierMiddleBranchDomain z1 z2)
    (hmixD :
      frontierMiddleBranchDomain
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2)) :
    θ * (frontierMajorant y1 y2 - frontierPhi y1) +
        (1 - θ) * (frontierMajorant z1 z2 - frontierPhi z1) ≤
      frontierMajorant
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) -
        (θ * frontierPhi y1 + (1 - θ) * frontierPhi z1) := by
  have hbellman :
      frontierMajorant
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) ≥
        θ * frontierMajorant y1 y2 +
          (1 - θ) * frontierMajorant z1 z2 :=
    frontierMajorant_middleBranchDomain_jensen_concave
      hyΩ hzΩ hmixΩ hyD hzD hmixD
  nlinarith

theorem frontierBoundaryMajorantResidualBudget_concatFeasibleBellmanSplit
    {leftMean leftSecond rightMean rightSecond θ : ℝ}
    {leftResidual rightResidual leftObjective rightObjective : ℝ}
    (hleft :
      leftResidual ≤
        frontierMajorant leftMean leftSecond - leftObjective)
    (hright :
      rightResidual ≤
        frontierMajorant rightMean rightSecond - rightObjective)
    (hleftΩ : frontierOmega frontierEpsilon leftMean leftSecond)
    (hrightΩ : frontierOmega frontierEpsilon rightMean rightSecond)
    (hconcatΩ :
      frontierOmega frontierEpsilon
        (θ * leftMean + (1 - θ) * rightMean)
        (θ * leftSecond + (1 - θ) * rightSecond))
    (hleftD : frontierMiddleBranchDomain leftMean leftSecond)
    (hrightD : frontierMiddleBranchDomain rightMean rightSecond)
    (hconcatD :
      frontierMiddleBranchDomain
        (θ * leftMean + (1 - θ) * rightMean)
        (θ * leftSecond + (1 - θ) * rightSecond))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    θ * leftResidual + (1 - θ) * rightResidual ≤
      frontierMajorant
          (θ * leftMean + (1 - θ) * rightMean)
          (θ * leftSecond + (1 - θ) * rightSecond) -
        (θ * leftObjective + (1 - θ) * rightObjective) := by
  have hleft_scaled :
      θ * leftResidual ≤
        θ * (frontierMajorant leftMean leftSecond - leftObjective) :=
    mul_le_mul_of_nonneg_left hleft hθ0
  have hright_scaled :
      (1 - θ) * rightResidual ≤
        (1 - θ) *
          (frontierMajorant rightMean rightSecond - rightObjective) :=
    mul_le_mul_of_nonneg_left hright (sub_nonneg.mpr hθ1)
  have hsplit :
      θ * (frontierMajorant leftMean leftSecond - leftObjective) +
          (1 - θ) *
            (frontierMajorant rightMean rightSecond - rightObjective) ≤
        frontierMajorant
            (θ * leftMean + (1 - θ) * rightMean)
            (θ * leftSecond + (1 - θ) * rightSecond) -
          (θ * leftObjective + (1 - θ) * rightObjective) := by
    have hbellman :
        frontierMajorant
            (θ * leftMean + (1 - θ) * rightMean)
            (θ * leftSecond + (1 - θ) * rightSecond) ≥
          θ * frontierMajorant leftMean leftSecond +
            (1 - θ) * frontierMajorant rightMean rightSecond :=
      frontierMajorant_middleBranchDomain_jensen_concave
        hleftΩ hrightΩ hconcatΩ hleftD hrightD hconcatD
    nlinarith
  nlinarith

theorem frontierBoundaryMajorantResidualBudget_concatFeasibleBellmanSplit_center
    {leftMean leftSecond rightMean rightSecond θ : ℝ}
    {leftResidual rightResidual leftObjective rightObjective : ℝ}
    (hleft :
      leftResidual ≤
        frontierMajorant leftMean leftSecond - leftObjective)
    (hright :
      rightResidual ≤
        frontierMajorant rightMean rightSecond - rightObjective)
    (hleftΩ : frontierOmega frontierEpsilon leftMean leftSecond)
    (hrightΩ : frontierOmega frontierEpsilon rightMean rightSecond)
    (hconcatΩ :
      frontierOmega frontierEpsilon
        (θ * leftMean + (1 - θ) * rightMean)
        (θ * leftSecond + (1 - θ) * rightSecond))
    (hleftD : frontierMiddleBranchDomain leftMean leftSecond)
    (hrightD : frontierMiddleBranchDomain rightMean rightSecond)
    (hconcatD :
      frontierMiddleBranchDomain
        (θ * leftMean + (1 - θ) * rightMean)
        (θ * leftSecond + (1 - θ) * rightSecond))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1)
    (hcenter_mean : θ * leftMean + (1 - θ) * rightMean = 0)
    (hcenter_second :
      θ * leftSecond + (1 - θ) * rightSecond = (1 / 12 : ℝ)) :
    θ * leftResidual + (1 - θ) * rightResidual ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        (θ * leftObjective + (1 - θ) * rightObjective) := by
  have hconcat :=
    frontierBoundaryMajorantResidualBudget_concatFeasibleBellmanSplit
      hleft hright hleftΩ hrightΩ hconcatΩ hleftD hrightD hconcatD
      hθ0 hθ1
  rw [hcenter_mean, hcenter_second] at hconcat
  exact hconcat

theorem frontierBoundaryMajorantResidualBudget_adjacentIntervalFeasibleBellmanSplit
    {leftLength rightLength totalLength : ℝ}
    {leftMean leftSecond rightMean rightSecond : ℝ}
    {leftResidual rightResidual leftObjective rightObjective : ℝ}
    (hleft :
      leftResidual ≤
        frontierMajorant leftMean leftSecond - leftObjective)
    (hright :
      rightResidual ≤
        frontierMajorant rightMean rightSecond - rightObjective)
    (hleftΩ : frontierOmega frontierEpsilon leftMean leftSecond)
    (hrightΩ : frontierOmega frontierEpsilon rightMean rightSecond)
    (hconcatΩ :
      frontierOmega frontierEpsilon
        ((leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond))
    (hleftD : frontierMiddleBranchDomain leftMean leftSecond)
    (hrightD : frontierMiddleBranchDomain rightMean rightSecond)
    (hconcatD :
      frontierMiddleBranchDomain
        ((leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond))
    (hleftLength_nonneg : 0 ≤ leftLength)
    (hrightLength_nonneg : 0 ≤ rightLength)
    (htotal : totalLength = leftLength + rightLength)
    (htotal_pos : 0 < totalLength) :
    (leftLength / totalLength) * leftResidual +
        (rightLength / totalLength) * rightResidual ≤
      frontierMajorant
          ((leftLength / totalLength) * leftMean +
            (rightLength / totalLength) * rightMean)
          ((leftLength / totalLength) * leftSecond +
            (rightLength / totalLength) * rightSecond) -
        ((leftLength / totalLength) * leftObjective +
          (rightLength / totalLength) * rightObjective) := by
  have hrightWeight :
      1 - leftLength / totalLength = rightLength / totalLength := by
    field_simp [ne_of_gt htotal_pos]
    linarith
  have hθ0 : 0 ≤ leftLength / totalLength :=
    div_nonneg hleftLength_nonneg (le_of_lt htotal_pos)
  have hleft_le_total : leftLength ≤ totalLength := by
    linarith
  have hθ1 : leftLength / totalLength ≤ 1 :=
    (div_le_one htotal_pos).mpr hleft_le_total
  have hconcatΩ' :
      frontierOmega frontierEpsilon
        ((leftLength / totalLength) * leftMean +
          (1 - leftLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (1 - leftLength / totalLength) * rightSecond) := by
    simpa [hrightWeight] using hconcatΩ
  have hconcatD' :
      frontierMiddleBranchDomain
        ((leftLength / totalLength) * leftMean +
          (1 - leftLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (1 - leftLength / totalLength) * rightSecond) := by
    simpa [hrightWeight] using hconcatD
  have hsplit :=
    frontierBoundaryMajorantResidualBudget_concatFeasibleBellmanSplit
      (θ := leftLength / totalLength)
      hleft hright hleftΩ hrightΩ hconcatΩ' hleftD hrightD hconcatD'
      hθ0 hθ1
  simpa [hrightWeight] using hsplit

theorem frontierBoundaryMajorantResidualBudget_adjacentIntervalFeasibleBellmanSplit_center
    {leftLength rightLength totalLength : ℝ}
    {leftMean leftSecond rightMean rightSecond : ℝ}
    {leftResidual rightResidual leftObjective rightObjective : ℝ}
    (hleft :
      leftResidual ≤
        frontierMajorant leftMean leftSecond - leftObjective)
    (hright :
      rightResidual ≤
        frontierMajorant rightMean rightSecond - rightObjective)
    (hleftΩ : frontierOmega frontierEpsilon leftMean leftSecond)
    (hrightΩ : frontierOmega frontierEpsilon rightMean rightSecond)
    (hconcatΩ :
      frontierOmega frontierEpsilon
        ((leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond))
    (hleftD : frontierMiddleBranchDomain leftMean leftSecond)
    (hrightD : frontierMiddleBranchDomain rightMean rightSecond)
    (hconcatD :
      frontierMiddleBranchDomain
        ((leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond))
    (hleftLength_nonneg : 0 ≤ leftLength)
    (hrightLength_nonneg : 0 ≤ rightLength)
    (htotal : totalLength = leftLength + rightLength)
    (htotal_pos : 0 < totalLength)
    (hcenter_mean :
      (leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean =
        0)
    (hcenter_second :
      (leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond =
        (1 / 12 : ℝ)) :
    (leftLength / totalLength) * leftResidual +
        (rightLength / totalLength) * rightResidual ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        ((leftLength / totalLength) * leftObjective +
          (rightLength / totalLength) * rightObjective) := by
  have hsplit :=
    frontierBoundaryMajorantResidualBudget_adjacentIntervalFeasibleBellmanSplit
      hleft hright hleftΩ hrightΩ hconcatΩ hleftD hrightD hconcatD
      hleftLength_nonneg hrightLength_nonneg htotal htotal_pos
  rw [hcenter_mean, hcenter_second] at hsplit
  exact hsplit

theorem frontierMajorant_adjacentSubintervalBellmanSplit
    {leftLength rightLength totalLength : ℝ}
    {leftMean leftSecond rightMean rightSecond : ℝ}
    (hleftΩ : frontierOmega frontierEpsilon leftMean leftSecond)
    (hrightΩ : frontierOmega frontierEpsilon rightMean rightSecond)
    (hconcatΩ :
      frontierOmega frontierEpsilon
        ((leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond))
    (hleftD : frontierMiddleBranchDomain leftMean leftSecond)
    (hrightD : frontierMiddleBranchDomain rightMean rightSecond)
    (hconcatD :
      frontierMiddleBranchDomain
        ((leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond))
    (hleftLength_nonneg : 0 ≤ leftLength)
    (hrightLength_nonneg : 0 ≤ rightLength)
    (htotal : totalLength = leftLength + rightLength)
    (htotal_pos : 0 < totalLength) :
    (leftLength / totalLength) * frontierMajorant leftMean leftSecond +
        (rightLength / totalLength) * frontierMajorant rightMean rightSecond ≤
      frontierMajorant
        ((leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond) := by
  have hleft :
      frontierMajorant leftMean leftSecond ≤
        frontierMajorant leftMean leftSecond - (0 : ℝ) := by
    simp
  have hright :
      frontierMajorant rightMean rightSecond ≤
        frontierMajorant rightMean rightSecond - (0 : ℝ) := by
    simp
  have hsplit :=
    frontierBoundaryMajorantResidualBudget_adjacentIntervalFeasibleBellmanSplit
      (leftResidual := frontierMajorant leftMean leftSecond)
      (rightResidual := frontierMajorant rightMean rightSecond)
      (leftObjective := 0)
      (rightObjective := 0)
      hleft hright hleftΩ hrightΩ hconcatΩ hleftD hrightD hconcatD
      hleftLength_nonneg hrightLength_nonneg htotal htotal_pos
  simpa using hsplit

theorem frontierMajorant_adjacentSubintervalBellmanSplit_of_centeredAdmissible
    (g : ℝ → ℝ) (hg : frontierBMOCenteredFunctionAdmissible g)
    {leftLength rightLength totalLength : ℝ}
    {leftMean leftSecond rightMean rightSecond : ℝ}
    (hleftΩ : frontierOmega frontierEpsilon leftMean leftSecond)
    (hrightΩ : frontierOmega frontierEpsilon rightMean rightSecond)
    (hleftD : frontierMiddleBranchDomain leftMean leftSecond)
    (hrightD : frontierMiddleBranchDomain rightMean rightSecond)
    (hconcatD :
      frontierMiddleBranchDomain
        ((leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond))
    (hleftLength_nonneg : 0 ≤ leftLength)
    (hrightLength_nonneg : 0 ≤ rightLength)
    (htotal : totalLength = leftLength + rightLength)
    (htotal_pos : 0 < totalLength)
    (hconcatMean :
      (leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean =
        frontierBMOOriginalMeanIntegral g)
    (hconcatSecond :
      (leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond =
        frontierBMOOriginalSecondMomentIntegral g) :
    (leftLength / totalLength) * frontierMajorant leftMean leftSecond +
        (rightLength / totalLength) *
          frontierMajorant rightMean rightSecond ≤
      frontierMajorant 0 (1 / 12 : ℝ) := by
  have hconcatΩ :
      frontierOmega frontierEpsilon
        ((leftLength / totalLength) * leftMean +
          (rightLength / totalLength) * rightMean)
        ((leftLength / totalLength) * leftSecond +
          (rightLength / totalLength) * rightSecond) := by
    simpa [hconcatMean, hconcatSecond] using
      frontierBMOCenteredAdmissible_moments_mem_omega g hg
  have hsplit :=
    frontierMajorant_adjacentSubintervalBellmanSplit
      hleftΩ hrightΩ hconcatΩ hleftD hrightD hconcatD
      hleftLength_nonneg hrightLength_nonneg htotal htotal_pos
  rcases hg with
    ⟨_hg, _hg2, _hphi, hmean, hsecondMoment, _hvariance⟩
  simpa [hconcatMean, hconcatSecond, hmean, hsecondMoment] using hsplit

theorem frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicCombine
    {leftMean leftSecond rightMean rightSecond : ℝ}
    {leftResidual rightResidual leftObjective rightObjective : ℝ}
    (hleft :
      leftResidual ≤
        frontierMajorant leftMean leftSecond - leftObjective)
    (hright :
      rightResidual ≤
        frontierMajorant rightMean rightSecond - rightObjective)
    (hleftΩ : frontierOmega frontierEpsilon leftMean leftSecond)
    (hrightΩ : frontierOmega frontierEpsilon rightMean rightSecond)
    (hmixΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * leftMean +
          (1 - (1 / 2 : ℝ)) * rightMean)
        ((1 / 2 : ℝ) * leftSecond +
          (1 - (1 / 2 : ℝ)) * rightSecond))
    (hleftD : frontierMiddleBranchDomain leftMean leftSecond)
    (hrightD : frontierMiddleBranchDomain rightMean rightSecond)
    (hmixD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * leftMean +
          (1 - (1 / 2 : ℝ)) * rightMean)
        ((1 / 2 : ℝ) * leftSecond +
          (1 - (1 / 2 : ℝ)) * rightSecond)) :
    (1 / 2 : ℝ) * leftResidual +
        (1 - (1 / 2 : ℝ)) * rightResidual ≤
      frontierMajorant
          ((1 / 2 : ℝ) * leftMean +
            (1 - (1 / 2 : ℝ)) * rightMean)
          ((1 / 2 : ℝ) * leftSecond +
            (1 - (1 / 2 : ℝ)) * rightSecond) -
        ((1 / 2 : ℝ) * leftObjective +
          (1 - (1 / 2 : ℝ)) * rightObjective) := by
  have hbellman :
      frontierMajorant
          ((1 / 2 : ℝ) * leftMean +
            (1 - (1 / 2 : ℝ)) * rightMean)
          ((1 / 2 : ℝ) * leftSecond +
            (1 - (1 / 2 : ℝ)) * rightSecond) ≥
        (1 / 2 : ℝ) * frontierMajorant leftMean leftSecond +
          (1 - (1 / 2 : ℝ)) *
            frontierMajorant rightMean rightSecond :=
    frontierMajorant_middleBranchDomain_jensen_concave
      hleftΩ hrightΩ hmixΩ hleftD hrightD hmixD
  nlinarith

theorem frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicCombine_center
    {leftMean leftSecond rightMean rightSecond : ℝ}
    {leftResidual rightResidual leftObjective rightObjective : ℝ}
    (hleft :
      leftResidual ≤
        frontierMajorant leftMean leftSecond - leftObjective)
    (hright :
      rightResidual ≤
        frontierMajorant rightMean rightSecond - rightObjective)
    (hleftΩ : frontierOmega frontierEpsilon leftMean leftSecond)
    (hrightΩ : frontierOmega frontierEpsilon rightMean rightSecond)
    (hmixΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * leftMean +
          (1 - (1 / 2 : ℝ)) * rightMean)
        ((1 / 2 : ℝ) * leftSecond +
          (1 - (1 / 2 : ℝ)) * rightSecond))
    (hleftD : frontierMiddleBranchDomain leftMean leftSecond)
    (hrightD : frontierMiddleBranchDomain rightMean rightSecond)
    (hmixD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * leftMean +
          (1 - (1 / 2 : ℝ)) * rightMean)
        ((1 / 2 : ℝ) * leftSecond +
          (1 - (1 / 2 : ℝ)) * rightSecond))
    (hcenter_mean :
      (1 / 2 : ℝ) * leftMean +
          (1 - (1 / 2 : ℝ)) * rightMean =
        0)
    (hcenter_second :
      (1 / 2 : ℝ) * leftSecond +
          (1 - (1 / 2 : ℝ)) * rightSecond =
        (1 / 12 : ℝ)) :
    (1 / 2 : ℝ) * leftResidual +
        (1 - (1 / 2 : ℝ)) * rightResidual ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        ((1 / 2 : ℝ) * leftObjective +
          (1 - (1 / 2 : ℝ)) * rightObjective) := by
  have hcombine :=
    frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicCombine
      hleft hright hleftΩ hrightΩ hmixΩ hleftD hrightD hmixD
  rw [hcenter_mean, hcenter_second] at hcombine
  exact hcombine

theorem frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicFourCombine
    {aMean aSecond bMean bSecond cMean cSecond dMean dSecond : ℝ}
    {aResidual bResidual cResidual dResidual : ℝ}
    {aObjective bObjective cObjective dObjective : ℝ}
    (ha :
      aResidual ≤
        frontierMajorant aMean aSecond - aObjective)
    (hb :
      bResidual ≤
        frontierMajorant bMean bSecond - bObjective)
    (hc :
      cResidual ≤
        frontierMajorant cMean cSecond - cObjective)
    (hd :
      dResidual ≤
        frontierMajorant dMean dSecond - dObjective)
    (haΩ : frontierOmega frontierEpsilon aMean aSecond)
    (hbΩ : frontierOmega frontierEpsilon bMean bSecond)
    (hcΩ : frontierOmega frontierEpsilon cMean cSecond)
    (hdΩ : frontierOmega frontierEpsilon dMean dSecond)
    (habΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean)
        ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond))
    (hcdΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean)
        ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond))
    (hfinalΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond)))
    (haD : frontierMiddleBranchDomain aMean aSecond)
    (hbD : frontierMiddleBranchDomain bMean bSecond)
    (hcD : frontierMiddleBranchDomain cMean cSecond)
    (hdD : frontierMiddleBranchDomain dMean dSecond)
    (habD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean)
        ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond))
    (hcdD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean)
        ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond))
    (hfinalD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond))) :
    (1 / 4 : ℝ) * aResidual +
        (1 / 4 : ℝ) * bResidual +
        (1 / 4 : ℝ) * cResidual +
        (1 / 4 : ℝ) * dResidual ≤
      frontierMajorant
          ((1 / 2 : ℝ) *
              ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean) +
            (1 - (1 / 2 : ℝ)) *
              ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean))
          ((1 / 2 : ℝ) *
              ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond) +
            (1 - (1 / 2 : ℝ)) *
              ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond)) -
        ((1 / 4 : ℝ) * aObjective +
          (1 / 4 : ℝ) * bObjective +
          (1 / 4 : ℝ) * cObjective +
          (1 / 4 : ℝ) * dObjective) := by
  have hab :
      (1 / 2 : ℝ) * aResidual +
          (1 - (1 / 2 : ℝ)) * bResidual ≤
        frontierMajorant
            ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean)
            ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond) -
          ((1 / 2 : ℝ) * aObjective +
            (1 - (1 / 2 : ℝ)) * bObjective) :=
    frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicCombine
      ha hb haΩ hbΩ habΩ haD hbD habD
  have hcd :
      (1 / 2 : ℝ) * cResidual +
          (1 - (1 / 2 : ℝ)) * dResidual ≤
        frontierMajorant
            ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean)
            ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond) -
          ((1 / 2 : ℝ) * cObjective +
            (1 - (1 / 2 : ℝ)) * dObjective) :=
    frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicCombine
      hc hd hcΩ hdΩ hcdΩ hcD hdD hcdD
  have hfinal :=
    frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicCombine
      hab hcd habΩ hcdΩ hfinalΩ habD hcdD hfinalD
  convert hfinal using 1 <;> ring

theorem frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicFourCombine_center
    {aMean aSecond bMean bSecond cMean cSecond dMean dSecond : ℝ}
    {aResidual bResidual cResidual dResidual : ℝ}
    {aObjective bObjective cObjective dObjective : ℝ}
    (ha :
      aResidual ≤
        frontierMajorant aMean aSecond - aObjective)
    (hb :
      bResidual ≤
        frontierMajorant bMean bSecond - bObjective)
    (hc :
      cResidual ≤
        frontierMajorant cMean cSecond - cObjective)
    (hd :
      dResidual ≤
        frontierMajorant dMean dSecond - dObjective)
    (haΩ : frontierOmega frontierEpsilon aMean aSecond)
    (hbΩ : frontierOmega frontierEpsilon bMean bSecond)
    (hcΩ : frontierOmega frontierEpsilon cMean cSecond)
    (hdΩ : frontierOmega frontierEpsilon dMean dSecond)
    (habΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean)
        ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond))
    (hcdΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean)
        ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond))
    (hfinalΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond)))
    (haD : frontierMiddleBranchDomain aMean aSecond)
    (hbD : frontierMiddleBranchDomain bMean bSecond)
    (hcD : frontierMiddleBranchDomain cMean cSecond)
    (hdD : frontierMiddleBranchDomain dMean dSecond)
    (habD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean)
        ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond))
    (hcdD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean)
        ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond))
    (hfinalD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond)))
    (hcenter_mean :
      (1 / 2 : ℝ) *
          ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean) +
        (1 - (1 / 2 : ℝ)) *
          ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean) =
        0)
    (hcenter_second :
      (1 / 2 : ℝ) *
          ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond) +
        (1 - (1 / 2 : ℝ)) *
          ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond) =
        (1 / 12 : ℝ)) :
    (1 / 4 : ℝ) * aResidual +
        (1 / 4 : ℝ) * bResidual +
        (1 / 4 : ℝ) * cResidual +
        (1 / 4 : ℝ) * dResidual ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        ((1 / 4 : ℝ) * aObjective +
          (1 / 4 : ℝ) * bObjective +
          (1 / 4 : ℝ) * cObjective +
          (1 / 4 : ℝ) * dObjective) := by
  have hab :
      (1 / 2 : ℝ) * aResidual +
          (1 - (1 / 2 : ℝ)) * bResidual ≤
        frontierMajorant
            ((1 / 2 : ℝ) * aMean + (1 - (1 / 2 : ℝ)) * bMean)
            ((1 / 2 : ℝ) * aSecond + (1 - (1 / 2 : ℝ)) * bSecond) -
          ((1 / 2 : ℝ) * aObjective +
            (1 - (1 / 2 : ℝ)) * bObjective) :=
    frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicCombine
      ha hb haΩ hbΩ habΩ haD hbD habD
  have hcd :
      (1 / 2 : ℝ) * cResidual +
          (1 - (1 / 2 : ℝ)) * dResidual ≤
        frontierMajorant
            ((1 / 2 : ℝ) * cMean + (1 - (1 / 2 : ℝ)) * dMean)
            ((1 / 2 : ℝ) * cSecond + (1 - (1 / 2 : ℝ)) * dSecond) -
          ((1 / 2 : ℝ) * cObjective +
            (1 - (1 / 2 : ℝ)) * dObjective) :=
    frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicCombine
      hc hd hcΩ hdΩ hcdΩ hcD hdD hcdD
  have hfinal :=
    frontierBoundaryMajorantResidualBudget_finiteBellmanInduction_dyadicCombine_center
      hab hcd habΩ hcdΩ hfinalΩ habD hcdD hfinalD
      hcenter_mean hcenter_second
  convert hfinal using 1 <;> ring

theorem frontierBoundaryMajorantResidualBudget_middleBranchTwoPointCenter
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hyD : frontierMiddleBranchDomain y1 y2)
    (hzD : frontierMiddleBranchDomain z1 z2)
    (hmixD :
      frontierMiddleBranchDomain
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2))
    (hmix_mean : θ * y1 + (1 - θ) * z1 = 0)
    (hmix_second : θ * y2 + (1 - θ) * z2 = (1 / 12 : ℝ)) :
    θ * (frontierMajorant y1 y2 - frontierPhi y1) +
        (1 - θ) * (frontierMajorant z1 z2 - frontierPhi z1) ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        (θ * frontierPhi y1 + (1 - θ) * frontierPhi z1) := by
  have hsplit :=
    frontierBoundaryMajorantResidualBudget_middleBranchBellmanSplit
      hyΩ hzΩ hmixΩ hyD hzD hmixD
  simpa [hmix_mean, hmix_second] using hsplit

theorem frontierBMOCenteredBoundaryMajorantResidualBudget_dyadicStep
    {y1 y2 z1 z2 : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hmixΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * y1 + (1 - (1 / 2 : ℝ)) * z1)
        ((1 / 2 : ℝ) * y2 + (1 - (1 / 2 : ℝ)) * z2))
    (hyD : frontierMiddleBranchDomain y1 y2)
    (hzD : frontierMiddleBranchDomain z1 z2)
    (hmixD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * y1 + (1 - (1 / 2 : ℝ)) * z1)
        ((1 / 2 : ℝ) * y2 + (1 - (1 / 2 : ℝ)) * z2))
    (hmix_mean :
      (1 / 2 : ℝ) * y1 + (1 - (1 / 2 : ℝ)) * z1 = 0)
    (hmix_second :
      (1 / 2 : ℝ) * y2 + (1 - (1 / 2 : ℝ)) * z2 =
        (1 / 12 : ℝ)) :
    (1 / 2 : ℝ) * (frontierMajorant y1 y2 - frontierPhi y1) +
        (1 - (1 / 2 : ℝ)) *
          (frontierMajorant z1 z2 - frontierPhi z1) ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        ((1 / 2 : ℝ) * frontierPhi y1 +
          (1 - (1 / 2 : ℝ)) * frontierPhi z1) := by
  exact
    frontierBoundaryMajorantResidualBudget_middleBranchTwoPointCenter
      hyΩ hzΩ hmixΩ hyD hzD hmixD hmix_mean hmix_second

theorem frontierBMOCenteredBoundaryMajorantResidualBudget_lowerBoundaryDyadicStep
    {y z : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * y + (1 - (1 / 2 : ℝ)) * z)
        ((1 / 2 : ℝ) * y ^ 2 + (1 - (1 / 2 : ℝ)) * z ^ 2))
    (hyD : frontierMiddleBranchDomain y (y ^ 2))
    (hzD : frontierMiddleBranchDomain z (z ^ 2))
    (hmixD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * y + (1 - (1 / 2 : ℝ)) * z)
        ((1 / 2 : ℝ) * y ^ 2 + (1 - (1 / 2 : ℝ)) * z ^ 2))
    (hmix_mean :
      (1 / 2 : ℝ) * y + (1 - (1 / 2 : ℝ)) * z = 0)
    (hmix_second :
      (1 / 2 : ℝ) * y ^ 2 + (1 - (1 / 2 : ℝ)) * z ^ 2 =
        (1 / 12 : ℝ)) :
    (1 / 2 : ℝ) * (frontierMajorant y (y ^ 2) - frontierPhi y) +
        (1 - (1 / 2 : ℝ)) *
          (frontierMajorant z (z ^ 2) - frontierPhi z) ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        ((1 / 2 : ℝ) * frontierPhi y +
          (1 - (1 / 2 : ℝ)) * frontierPhi z) := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudget_dyadicStep
      (by
        rw [frontierOmega]
        constructor
        · rfl
        · nlinarith [sq_nonneg frontierEpsilon])
      (by
        rw [frontierOmega]
        constructor
        · rfl
        · nlinarith [sq_nonneg frontierEpsilon])
      hmixΩ hyD hzD hmixD hmix_mean hmix_second

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBound_lowerBoundaryDyadicStep
    {y z : ℝ}
    (hmixΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * y + (1 - (1 / 2 : ℝ)) * z)
        ((1 / 2 : ℝ) * y ^ 2 + (1 - (1 / 2 : ℝ)) * z ^ 2))
    (hyD : frontierMiddleBranchDomain y (y ^ 2))
    (hzD : frontierMiddleBranchDomain z (z ^ 2))
    (hmixD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * y + (1 - (1 / 2 : ℝ)) * z)
        ((1 / 2 : ℝ) * y ^ 2 + (1 - (1 / 2 : ℝ)) * z ^ 2))
    (hmix_mean :
      (1 / 2 : ℝ) * y + (1 - (1 / 2 : ℝ)) * z = 0)
    (hmix_second :
      (1 / 2 : ℝ) * y ^ 2 + (1 - (1 / 2 : ℝ)) * z ^ 2 =
        (1 / 12 : ℝ)) :
    (1 / 2 : ℝ) * frontierMajorant y (y ^ 2) +
        (1 - (1 / 2 : ℝ)) * frontierMajorant z (z ^ 2) ≤
      frontierMajorant 0 (1 / 12 : ℝ) := by
  have hbudget :=
    frontierBMOCenteredBoundaryMajorantResidualBudget_lowerBoundaryDyadicStep
      hmixΩ hyD hzD hmixD hmix_mean hmix_second
  nlinarith

theorem frontierBoundaryMajorantResidualBudget_middleBranchDyadicFourPointBellmanSplit
    {a1 a2 b1 b2 c1 c2 d1 d2 : ℝ}
    (haΩ : frontierOmega frontierEpsilon a1 a2)
    (hbΩ : frontierOmega frontierEpsilon b1 b2)
    (hcΩ : frontierOmega frontierEpsilon c1 c2)
    (hdΩ : frontierOmega frontierEpsilon d1 d2)
    (habΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1)
        ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2))
    (hcdΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1)
        ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2))
    (hfinalΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2)))
    (haD : frontierMiddleBranchDomain a1 a2)
    (hbD : frontierMiddleBranchDomain b1 b2)
    (hcD : frontierMiddleBranchDomain c1 c2)
    (hdD : frontierMiddleBranchDomain d1 d2)
    (habD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1)
        ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2))
    (hcdD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1)
        ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2))
    (hfinalD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2))) :
    (1 / 4 : ℝ) * (frontierMajorant a1 a2 - frontierPhi a1) +
        (1 / 4 : ℝ) * (frontierMajorant b1 b2 - frontierPhi b1) +
        (1 / 4 : ℝ) * (frontierMajorant c1 c2 - frontierPhi c1) +
        (1 / 4 : ℝ) * (frontierMajorant d1 d2 - frontierPhi d1) ≤
      frontierMajorant
          ((1 / 2 : ℝ) *
              ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1) +
            (1 - (1 / 2 : ℝ)) *
              ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1))
          ((1 / 2 : ℝ) *
              ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) +
            (1 - (1 / 2 : ℝ)) *
              ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2)) -
        ((1 / 4 : ℝ) * frontierPhi a1 +
          (1 / 4 : ℝ) * frontierPhi b1 +
          (1 / 4 : ℝ) * frontierPhi c1 +
          (1 / 4 : ℝ) * frontierPhi d1) := by
  have hab :
      frontierMajorant
          ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1)
          ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) ≥
        (1 / 2 : ℝ) * frontierMajorant a1 a2 +
          (1 - (1 / 2 : ℝ)) * frontierMajorant b1 b2 :=
    frontierMajorant_middleBranchDomain_jensen_concave
      haΩ hbΩ habΩ haD hbD habD
  have hcd :
      frontierMajorant
          ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1)
          ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2) ≥
        (1 / 2 : ℝ) * frontierMajorant c1 c2 +
          (1 - (1 / 2 : ℝ)) * frontierMajorant d1 d2 :=
    frontierMajorant_middleBranchDomain_jensen_concave
      hcΩ hdΩ hcdΩ hcD hdD hcdD
  have hfinal :
      frontierMajorant
          ((1 / 2 : ℝ) *
              ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1) +
            (1 - (1 / 2 : ℝ)) *
              ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1))
          ((1 / 2 : ℝ) *
              ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) +
            (1 - (1 / 2 : ℝ)) *
              ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2)) ≥
        (1 / 2 : ℝ) *
            frontierMajorant
              ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1)
              ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) +
          (1 - (1 / 2 : ℝ)) *
            frontierMajorant
              ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1)
              ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2) :=
    frontierMajorant_middleBranchDomain_jensen_concave
      habΩ hcdΩ hfinalΩ habD hcdD hfinalD
  nlinarith

theorem frontierBoundaryMajorantResidualBudget_middleBranchDyadicFourPointCenter
    {a1 a2 b1 b2 c1 c2 d1 d2 : ℝ}
    (haΩ : frontierOmega frontierEpsilon a1 a2)
    (hbΩ : frontierOmega frontierEpsilon b1 b2)
    (hcΩ : frontierOmega frontierEpsilon c1 c2)
    (hdΩ : frontierOmega frontierEpsilon d1 d2)
    (habΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1)
        ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2))
    (hcdΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1)
        ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2))
    (hfinalΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2)))
    (haD : frontierMiddleBranchDomain a1 a2)
    (hbD : frontierMiddleBranchDomain b1 b2)
    (hcD : frontierMiddleBranchDomain c1 c2)
    (hdD : frontierMiddleBranchDomain d1 d2)
    (habD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1)
        ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2))
    (hcdD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1)
        ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2))
    (hfinalD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2)))
    (hcenter_mean :
      (1 / 2 : ℝ) *
          ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1) +
        (1 - (1 / 2 : ℝ)) *
          ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1) =
        0)
    (hcenter_second :
      (1 / 2 : ℝ) *
          ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) +
        (1 - (1 / 2 : ℝ)) *
          ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2) =
        (1 / 12 : ℝ)) :
    (1 / 4 : ℝ) * (frontierMajorant a1 a2 - frontierPhi a1) +
        (1 / 4 : ℝ) * (frontierMajorant b1 b2 - frontierPhi b1) +
        (1 / 4 : ℝ) * (frontierMajorant c1 c2 - frontierPhi c1) +
        (1 / 4 : ℝ) * (frontierMajorant d1 d2 - frontierPhi d1) ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        ((1 / 4 : ℝ) * frontierPhi a1 +
          (1 / 4 : ℝ) * frontierPhi b1 +
          (1 / 4 : ℝ) * frontierPhi c1 +
          (1 / 4 : ℝ) * frontierPhi d1) := by
  have hab :
      frontierMajorant
          ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1)
          ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) ≥
        (1 / 2 : ℝ) * frontierMajorant a1 a2 +
          (1 - (1 / 2 : ℝ)) * frontierMajorant b1 b2 :=
    frontierMajorant_middleBranchDomain_jensen_concave
      haΩ hbΩ habΩ haD hbD habD
  have hcd :
      frontierMajorant
          ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1)
          ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2) ≥
        (1 / 2 : ℝ) * frontierMajorant c1 c2 +
          (1 - (1 / 2 : ℝ)) * frontierMajorant d1 d2 :=
    frontierMajorant_middleBranchDomain_jensen_concave
      hcΩ hdΩ hcdΩ hcD hdD hcdD
  have hfinal :
      frontierMajorant 0 (1 / 12 : ℝ) ≥
        (1 / 2 : ℝ) *
            frontierMajorant
              ((1 / 2 : ℝ) * a1 + (1 - (1 / 2 : ℝ)) * b1)
              ((1 / 2 : ℝ) * a2 + (1 - (1 / 2 : ℝ)) * b2) +
          (1 - (1 / 2 : ℝ)) *
            frontierMajorant
              ((1 / 2 : ℝ) * c1 + (1 - (1 / 2 : ℝ)) * d1)
              ((1 / 2 : ℝ) * c2 + (1 - (1 / 2 : ℝ)) * d2) := by
    have h :=
      frontierMajorant_middleBranchDomain_jensen_concave
        habΩ hcdΩ hfinalΩ habD hcdD hfinalD
    rw [hcenter_mean, hcenter_second] at h
    exact h
  nlinarith

theorem frontierBMOCenteredBoundaryMajorantResidualBudget_lowerBoundaryDyadicFourPointCenter
    {a b c d : ℝ}
    (habΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b)
        ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2))
    (hcdΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d)
        ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2))
    (hfinalΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2)))
    (haD : frontierMiddleBranchDomain a (a ^ 2))
    (hbD : frontierMiddleBranchDomain b (b ^ 2))
    (hcD : frontierMiddleBranchDomain c (c ^ 2))
    (hdD : frontierMiddleBranchDomain d (d ^ 2))
    (habD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b)
        ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2))
    (hcdD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d)
        ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2))
    (hfinalD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2)))
    (hcenter_mean :
      (1 / 2 : ℝ) *
          ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b) +
        (1 - (1 / 2 : ℝ)) *
          ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d) =
        0)
    (hcenter_second :
      (1 / 2 : ℝ) *
          ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2) +
        (1 - (1 / 2 : ℝ)) *
          ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2) =
        (1 / 12 : ℝ)) :
    (1 / 4 : ℝ) * (frontierMajorant a (a ^ 2) - frontierPhi a) +
        (1 / 4 : ℝ) * (frontierMajorant b (b ^ 2) - frontierPhi b) +
        (1 / 4 : ℝ) * (frontierMajorant c (c ^ 2) - frontierPhi c) +
        (1 / 4 : ℝ) * (frontierMajorant d (d ^ 2) - frontierPhi d) ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        ((1 / 4 : ℝ) * frontierPhi a +
          (1 / 4 : ℝ) * frontierPhi b +
          (1 / 4 : ℝ) * frontierPhi c +
          (1 / 4 : ℝ) * frontierPhi d) := by
  exact
    frontierBoundaryMajorantResidualBudget_middleBranchDyadicFourPointCenter
      (by
        rw [frontierOmega]
        constructor
        · rfl
        · nlinarith [sq_nonneg frontierEpsilon])
      (by
        rw [frontierOmega]
        constructor
        · rfl
        · nlinarith [sq_nonneg frontierEpsilon])
      (by
        rw [frontierOmega]
        constructor
        · rfl
        · nlinarith [sq_nonneg frontierEpsilon])
      (by
        rw [frontierOmega]
        constructor
        · rfl
        · nlinarith [sq_nonneg frontierEpsilon])
      habΩ hcdΩ hfinalΩ
      haD hbD hcD hdD habD hcdD hfinalD hcenter_mean hcenter_second

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBound_lowerBoundaryDyadicFourPointCenter
    {a b c d : ℝ}
    (habΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b)
        ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2))
    (hcdΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d)
        ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2))
    (hfinalΩ :
      frontierOmega frontierEpsilon
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2)))
    (haD : frontierMiddleBranchDomain a (a ^ 2))
    (hbD : frontierMiddleBranchDomain b (b ^ 2))
    (hcD : frontierMiddleBranchDomain c (c ^ 2))
    (hdD : frontierMiddleBranchDomain d (d ^ 2))
    (habD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b)
        ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2))
    (hcdD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d)
        ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2))
    (hfinalD :
      frontierMiddleBranchDomain
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d))
        ((1 / 2 : ℝ) *
            ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2) +
          (1 - (1 / 2 : ℝ)) *
            ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2)))
    (hcenter_mean :
      (1 / 2 : ℝ) *
          ((1 / 2 : ℝ) * a + (1 - (1 / 2 : ℝ)) * b) +
        (1 - (1 / 2 : ℝ)) *
          ((1 / 2 : ℝ) * c + (1 - (1 / 2 : ℝ)) * d) =
        0)
    (hcenter_second :
      (1 / 2 : ℝ) *
          ((1 / 2 : ℝ) * a ^ 2 + (1 - (1 / 2 : ℝ)) * b ^ 2) +
        (1 - (1 / 2 : ℝ)) *
          ((1 / 2 : ℝ) * c ^ 2 + (1 - (1 / 2 : ℝ)) * d ^ 2) =
        (1 / 12 : ℝ)) :
    (1 / 4 : ℝ) * frontierMajorant a (a ^ 2) +
        (1 / 4 : ℝ) * frontierMajorant b (b ^ 2) +
        (1 / 4 : ℝ) * frontierMajorant c (c ^ 2) +
        (1 / 4 : ℝ) * frontierMajorant d (d ^ 2) ≤
      frontierMajorant 0 (1 / 12 : ℝ) := by
  have hbudget :=
    frontierBMOCenteredBoundaryMajorantResidualBudget_lowerBoundaryDyadicFourPointCenter
      habΩ hcdΩ hfinalΩ haD hbD hcD hdD habD hcdD hfinalD
      hcenter_mean hcenter_second
  nlinarith

theorem frontierMajorant_middleBranch_localConcavity_witness
    {x1 x2 δ : ℝ} (hδ : 0 < δ)
    (hbranch :
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMiddleBranchDomain y1 y2 ∧
            frontierMiddleBranchDomain z1 z2 ∧
            frontierMiddleBranchDomain
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2)) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  refine ⟨δ, hδ, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  rcases hbranch y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1 with
    ⟨⟨hy_left, hy_right⟩, ⟨⟨hz_left, hz_right⟩, ⟨hmix_left, hmix_right⟩⟩⟩
  exact frontierMajorant_middleBranch_jensen_concave hyΩ hzΩ hmixΩ
    hy_left hy_right hz_left hz_right hmix_left hmix_right

theorem frontierCPlus_continuous (eps : ℝ) :
    Continuous (fun p : ℝ × ℝ => frontierCPlus eps p.1 p.2) := by
  unfold frontierCPlus frontierRadius
  continuity

theorem frontierRadius_continuous (eps : ℝ) :
    Continuous (fun p : ℝ × ℝ => frontierRadius eps p.1 p.2) := by
  unfold frontierRadius
  continuity

theorem frontier_pair_dist_lt_of_abs
    {x1 x2 y1 y2 δ : ℝ}
    (hy1 : |y1 - x1| < δ) (hy2 : |y2 - x2| < δ) :
    dist (y1, y2) (x1, x2) < δ := by
  rw [show dist (y1, y2) (x1, x2) =
      max (dist y1 x1) (dist y2 x2) by rfl]
  rw [Real.dist_eq, Real.dist_eq]
  exact max_lt hy1 hy2

theorem frontier_convex_coord_abs_lt
    {x y z θ δ : ℝ}
    (hy : |y - x| < δ) (hz : |z - x| < δ)
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    |(θ * y + (1 - θ) * z) - x| < δ := by
  have hrewrite :
      θ * y + (1 - θ) * z - x =
        θ * (y - x) + (1 - θ) * (z - x) := by
    ring
  rw [hrewrite]
  have htri :
      |θ * (y - x) + (1 - θ) * (z - x)| ≤
        |θ * (y - x)| + |(1 - θ) * (z - x)| :=
    abs_add_le _ _
  have hθ_nonneg : 0 ≤ 1 - θ := by
    linarith
  have habs :
      |θ * (y - x)| + |(1 - θ) * (z - x)| =
        θ * |y - x| + (1 - θ) * |z - x| := by
    rw [abs_mul, abs_mul, abs_of_nonneg hθ0, abs_of_nonneg hθ_nonneg]
  rw [habs] at htri
  by_cases hθzero : θ = 0
  · subst θ
    simpa using hz
  · have hθpos : 0 < θ := lt_of_le_of_ne hθ0 (Ne.symm hθzero)
    by_cases hθone : θ = 1
    · subst θ
      simpa using hy
    · have hθlt : θ < 1 := lt_of_le_of_ne hθ1 hθone
      have honepos : 0 < 1 - θ := by
        linarith
      have hyw : θ * |y - x| < θ * δ :=
        mul_lt_mul_of_pos_left hy hθpos
      have hzw : (1 - θ) * |z - x| < (1 - θ) * δ :=
        mul_lt_mul_of_pos_left hz honepos
      have hsum : θ * |y - x| + (1 - θ) * |z - x| < δ := by
        calc
          θ * |y - x| + (1 - θ) * |z - x| <
              θ * δ + (1 - θ) * δ := add_lt_add hyw hzw
          _ = δ := by ring
      exact lt_of_le_of_lt htri hsum

theorem frontierMajorant_leftGlue_piece_neighborhood
    {x1 x2 : ℝ}
    (hC : frontierCPlus frontierEpsilon x1 x2 = frontierCStar) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
          frontierCPlus frontierEpsilon y1 y2 <
              frontierCStar + 2 * frontierEpsilon ∧
            frontierMajorant y1 y2 =
              if frontierCPlus frontierEpsilon y1 y2 ≤ frontierCStar then
                frontierLeftPiece y1 y2
              else
                frontierMiddlePiece y1 y2 := by
  let F : ℝ × ℝ → ℝ := fun p ↦ frontierCPlus frontierEpsilon p.1 p.2
  let η : ℝ := frontierEpsilon
  have hη_pos : 0 < η := by
    dsimp [η]
    exact frontierEpsilon_pos
  have hcont : ContinuousAt F (x1, x2) := by
    exact (frontierCPlus_continuous frontierEpsilon).continuousAt
  rw [Metric.continuousAt_iff] at hcont
  rcases hcont η hη_pos with ⟨δ, hδ_pos, hδ⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 hy1 hy2
  have hdist := hδ (frontier_pair_dist_lt_of_abs hy1 hy2)
  have hCabs :
      |F (y1, y2) - frontierCStar| < frontierEpsilon := by
    simpa [Real.dist_eq, F, η, hC] using hdist
  have hbounds := abs_lt.mp hCabs
  have hbelowRight :
      frontierCPlus frontierEpsilon y1 y2 <
        frontierCStar + 2 * frontierEpsilon := by
    dsimp [F] at hbounds
    linarith [frontierEpsilon_pos]
  refine ⟨hbelowRight, ?_⟩
  by_cases hleft : frontierCPlus frontierEpsilon y1 y2 ≤ frontierCStar
  · rw [frontierMajorant_eq_leftPiece_of_CPlus hleft, if_pos hleft]
  · have hleft_strict :
        frontierCStar < frontierCPlus frontierEpsilon y1 y2 :=
      not_le.mp hleft
    rw [frontierMajorant_eq_middlePiece_of_CPlus hleft_strict
        (le_of_lt hbelowRight), if_neg hleft]

theorem frontierMajorant_rightGlue_piece_neighborhood
    {x1 x2 : ℝ}
    (hC :
      frontierCPlus frontierEpsilon x1 x2 =
        frontierCStar + 2 * frontierEpsilon) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
          frontierCStar < frontierCPlus frontierEpsilon y1 y2 ∧
            frontierMajorant y1 y2 =
              if frontierCPlus frontierEpsilon y1 y2 ≤
                  frontierCStar + 2 * frontierEpsilon then
                frontierMiddlePiece y1 y2
              else
                frontierRightTailPiece y1 y2 := by
  let F : ℝ × ℝ → ℝ := fun p ↦ frontierCPlus frontierEpsilon p.1 p.2
  let U : ℝ := frontierCStar + 2 * frontierEpsilon
  let η : ℝ := frontierEpsilon
  have hη_pos : 0 < η := by
    dsimp [η]
    exact frontierEpsilon_pos
  have hcont : ContinuousAt F (x1, x2) := by
    exact (frontierCPlus_continuous frontierEpsilon).continuousAt
  rw [Metric.continuousAt_iff] at hcont
  rcases hcont η hη_pos with ⟨δ, hδ_pos, hδ⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 hy1 hy2
  have hdist := hδ (frontier_pair_dist_lt_of_abs hy1 hy2)
  have hCabs :
      |F (y1, y2) - U| < frontierEpsilon := by
    simpa [Real.dist_eq, F, U, η, hC] using hdist
  have hbounds := abs_lt.mp hCabs
  have haboveLeft :
      frontierCStar < frontierCPlus frontierEpsilon y1 y2 := by
    dsimp [F, U] at hbounds
    linarith [frontierEpsilon_pos]
  refine ⟨haboveLeft, ?_⟩
  by_cases hmiddle :
      frontierCPlus frontierEpsilon y1 y2 ≤
        frontierCStar + 2 * frontierEpsilon
  · rw [frontierMajorant_eq_middlePiece_of_CPlus haboveLeft hmiddle,
      if_pos hmiddle]
  · have hright :
        frontierCStar + 2 * frontierEpsilon <
          frontierCPlus frontierEpsilon y1 y2 :=
      not_le.mp hmiddle
    rw [frontierMajorant_eq_rightTailPiece_of_CPlus hright, if_neg hmiddle]

theorem frontierMajorant_leftBranchInterior_piece_neighborhood
    {x1 x2 : ℝ}
    (hleft : frontierCPlus frontierEpsilon x1 x2 < frontierCStar) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        0 ≤ θ → θ ≤ 1 →
          frontierLeftBranchDomain y1 y2 ∧
            frontierMajorant y1 y2 = frontierLeftPiece y1 y2 ∧
          frontierLeftBranchDomain z1 z2 ∧
            frontierMajorant z1 z2 = frontierLeftPiece z1 z2 ∧
          frontierLeftBranchDomain
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) ∧
            frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) =
                frontierLeftPiece
                  (θ * y1 + (1 - θ) * z1)
                  (θ * y2 + (1 - θ) * z2) := by
  let F : ℝ × ℝ → ℝ := fun p ↦ frontierCPlus frontierEpsilon p.1 p.2
  let Cx : ℝ := F (x1, x2)
  let η : ℝ := (frontierCStar - Cx) / 2
  have hη_pos : 0 < η := by
    dsimp [η, Cx, F]
    linarith
  have hcont : ContinuousAt F (x1, x2) := by
    exact (frontierCPlus_continuous frontierEpsilon).continuousAt
  rw [Metric.continuousAt_iff] at hcont
  rcases hcont η hη_pos with ⟨δ, hδ_pos, hδ⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hθ0 hθ1
  have stable :
      ∀ p : ℝ × ℝ, dist p (x1, x2) < δ →
        frontierLeftBranchDomain p.1 p.2 := by
    intro p hp
    have hpCdist := hδ hp
    have hpCabs : |F p - Cx| < η := by
      simpa [Real.dist_eq, Cx] using hpCdist
    have hp_bounds := abs_lt.mp hpCabs
    dsimp [frontierLeftBranchDomain, F, Cx, η] at *
    linarith
  have hyD : frontierLeftBranchDomain y1 y2 :=
    stable (y1, y2) (frontier_pair_dist_lt_of_abs hy1 hy2)
  have hzD : frontierLeftBranchDomain z1 z2 :=
    stable (z1, z2) (frontier_pair_dist_lt_of_abs hz1 hz2)
  have hmix1 :
      |(θ * y1 + (1 - θ) * z1) - x1| < δ :=
    frontier_convex_coord_abs_lt hy1 hz1 hθ0 hθ1
  have hmix2 :
      |(θ * y2 + (1 - θ) * z2) - x2| < δ :=
    frontier_convex_coord_abs_lt hy2 hz2 hθ0 hθ1
  have hmixD :
      frontierLeftBranchDomain
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) :=
    stable
      ((θ * y1 + (1 - θ) * z1),
        (θ * y2 + (1 - θ) * z2))
      (frontier_pair_dist_lt_of_abs hmix1 hmix2)
  exact ⟨hyD, frontierMajorant_eq_leftPiece_of_leftBranchDomain hyD,
    hzD, frontierMajorant_eq_leftPiece_of_leftBranchDomain hzD,
    hmixD, frontierMajorant_eq_leftPiece_of_leftBranchDomain hmixD⟩

theorem frontierMajorant_rightBranchInterior_piece_neighborhood
    {x1 x2 : ℝ}
    (hright :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1 x2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        0 ≤ θ → θ ≤ 1 →
          frontierRightBranchDomain y1 y2 ∧
            frontierMajorant y1 y2 = frontierRightTailPiece y1 y2 ∧
          frontierRightBranchDomain z1 z2 ∧
            frontierMajorant z1 z2 = frontierRightTailPiece z1 z2 ∧
          frontierRightBranchDomain
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) ∧
            frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) =
                frontierRightTailPiece
                  (θ * y1 + (1 - θ) * z1)
                  (θ * y2 + (1 - θ) * z2) := by
  let F : ℝ × ℝ → ℝ := fun p ↦ frontierCPlus frontierEpsilon p.1 p.2
  let Cx : ℝ := F (x1, x2)
  let U : ℝ := frontierCStar + 2 * frontierEpsilon
  let η : ℝ := (Cx - U) / 2
  have hη_pos : 0 < η := by
    dsimp [η, U, Cx, F]
    linarith
  have hcont : ContinuousAt F (x1, x2) := by
    exact (frontierCPlus_continuous frontierEpsilon).continuousAt
  rw [Metric.continuousAt_iff] at hcont
  rcases hcont η hη_pos with ⟨δ, hδ_pos, hδ⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hθ0 hθ1
  have stable :
      ∀ p : ℝ × ℝ, dist p (x1, x2) < δ →
        frontierRightBranchDomain p.1 p.2 := by
    intro p hp
    have hpCdist := hδ hp
    have hpCabs : |F p - Cx| < η := by
      simpa [Real.dist_eq, Cx] using hpCdist
    have hp_bounds := abs_lt.mp hpCabs
    dsimp [frontierRightBranchDomain, F, Cx, U, η] at *
    linarith
  have hyD : frontierRightBranchDomain y1 y2 :=
    stable (y1, y2) (frontier_pair_dist_lt_of_abs hy1 hy2)
  have hzD : frontierRightBranchDomain z1 z2 :=
    stable (z1, z2) (frontier_pair_dist_lt_of_abs hz1 hz2)
  have hmix1 :
      |(θ * y1 + (1 - θ) * z1) - x1| < δ :=
    frontier_convex_coord_abs_lt hy1 hz1 hθ0 hθ1
  have hmix2 :
      |(θ * y2 + (1 - θ) * z2) - x2| < δ :=
    frontier_convex_coord_abs_lt hy2 hz2 hθ0 hθ1
  have hmixD :
      frontierRightBranchDomain
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) :=
    stable
      ((θ * y1 + (1 - θ) * z1),
        (θ * y2 + (1 - θ) * z2))
      (frontier_pair_dist_lt_of_abs hmix1 hmix2)
  exact ⟨hyD, frontierMajorant_eq_rightTailPiece_of_rightBranchDomain hyD,
    hzD, frontierMajorant_eq_rightTailPiece_of_rightBranchDomain hzD,
    hmixD, frontierMajorant_eq_rightTailPiece_of_rightBranchDomain hmixD⟩

theorem frontierMajorant_middleBranchInterior_localConcavity
    {x1 x2 : ℝ} (_hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hleft : frontierCStar < frontierCPlus frontierEpsilon x1 x2)
    (hright :
      frontierCPlus frontierEpsilon x1 x2 <
        frontierCStar + 2 * frontierEpsilon) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  let F : ℝ × ℝ → ℝ := fun p ↦ frontierCPlus frontierEpsilon p.1 p.2
  let Cx : ℝ := F (x1, x2)
  let U : ℝ := frontierCStar + 2 * frontierEpsilon
  let η : ℝ := min (Cx - frontierCStar) (U - Cx) / 2
  have hη_pos : 0 < η := by
    have hgap_left : 0 < Cx - frontierCStar := by
      dsimp [Cx, F]
      linarith
    have hgap_right : 0 < U - Cx := by
      dsimp [U, Cx, F]
      linarith
    dsimp [η]
    exact half_pos (lt_min hgap_left hgap_right)
  have hη_left : η ≤ Cx - frontierCStar := by
    dsimp [η]
    have hmin : min (Cx - frontierCStar) (U - Cx) ≤
        Cx - frontierCStar :=
      min_le_left _ _
    linarith
  have hη_right : η ≤ U - Cx := by
    dsimp [η]
    have hmin : min (Cx - frontierCStar) (U - Cx) ≤ U - Cx :=
      min_le_right _ _
    linarith
  have hcont : ContinuousAt F (x1, x2) := by
    exact (frontierCPlus_continuous frontierEpsilon).continuousAt
  rw [Metric.continuousAt_iff] at hcont
  rcases hcont η hη_pos with ⟨δ, hδ_pos, hδ⟩
  refine frontierMajorant_middleBranch_localConcavity_witness hδ_pos ?_
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  have stable :
      ∀ p : ℝ × ℝ, dist p (x1, x2) < δ →
        frontierMiddleBranchDomain p.1 p.2 := by
    intro p hp
    have hpCdist := hδ hp
    have hpCabs : |F p - Cx| < η := by
      simpa [Real.dist_eq, Cx] using hpCdist
    have hp_bounds := abs_lt.mp hpCabs
    constructor
    · dsimp [frontierMiddleBranchDomain, F, Cx] at *
      linarith
    · dsimp [frontierMiddleBranchDomain, F, Cx, U] at *
      linarith
  have hyD : frontierMiddleBranchDomain y1 y2 :=
    stable (y1, y2) (frontier_pair_dist_lt_of_abs hy1 hy2)
  have hzD : frontierMiddleBranchDomain z1 z2 :=
    stable (z1, z2) (frontier_pair_dist_lt_of_abs hz1 hz2)
  have hmix1 :
      |(θ * y1 + (1 - θ) * z1) - x1| < δ :=
    frontier_convex_coord_abs_lt hy1 hz1 hθ0 hθ1
  have hmix2 :
      |(θ * y2 + (1 - θ) * z2) - x2| < δ :=
    frontier_convex_coord_abs_lt hy2 hz2 hθ0 hθ1
  have hmixD :
      frontierMiddleBranchDomain
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) :=
    stable
      ((θ * y1 + (1 - θ) * z1),
        (θ * y2 + (1 - θ) * z2))
      (frontier_pair_dist_lt_of_abs hmix1 hmix2)
  exact ⟨hyD, hzD, hmixD⟩

theorem frontierRightTailTraceThird_nonneg (C : ℝ) :
    0 ≤ frontierRightTailTraceThird C := by
  rw [frontierRightTailTraceThird]
  norm_num

theorem frontierLeft_middle_trace_value_glue :
    frontierMiddleTrace frontierCStar = frontierLeftTrace frontierCStar := by
  rw [frontierMiddleTrace]
  ring

theorem frontierLeft_middle_trace_deriv_glue :
    frontierMiddleTraceDeriv frontierCStar =
      frontierLeftTraceDeriv frontierCStar := by
  rw [frontierMiddleTraceDeriv]
  ring

theorem frontierLeft_middle_trace_second_glue :
    frontierMiddleTraceSecond frontierCStar =
      frontierLeftTraceSecond frontierCStar := by
  rw [frontierMiddleTraceSecond, frontierLeftTraceSecond,
    frontierKL_div_epsilon_sq_mul_exp_CStar_div]
  ring

theorem frontierMiddle_right_trace_value_glue :
    frontierMiddleTrace (frontierCStar + 2 * frontierEpsilon) =
      frontierRightTailTrace (frontierCStar + 2 * frontierEpsilon) := by
  rw [frontierMiddleTrace, frontierRightTailTrace,
    frontierLeftTrace, frontierLeftTraceDeriv,
    frontierKL_mul_exp_CStar_div,
    frontierKL_div_epsilon_mul_exp_CStar_div]
  rw [frontierCStar, frontierA]
  ring_nf
  rw [frontierEpsilon_ninth, frontierEpsilon_seventh, frontierEpsilon_sixth,
    frontierEpsilon_fifth, frontierEpsilon_fourth, frontierEpsilon_cube,
    frontierEpsilon_sq]
  ring

theorem frontierMiddle_right_trace_deriv_glue :
    frontierMiddleTraceDeriv (frontierCStar + 2 * frontierEpsilon) =
      frontierRightTailTraceDeriv (frontierCStar + 2 * frontierEpsilon) := by
  rw [frontierMiddleTraceDeriv, frontierRightTailTraceDeriv,
    frontierLeftTraceDeriv,
    frontierKL_div_epsilon_mul_exp_CStar_div]
  nlinarith [frontierEpsilon_sq]

theorem frontierMiddle_right_trace_second_glue :
    frontierMiddleTraceSecond (frontierCStar + 2 * frontierEpsilon) =
      frontierRightTailTraceSecond (frontierCStar + 2 * frontierEpsilon) := by
  rw [frontierMiddleTraceSecond, frontierRightTailTraceSecond]
  ring

theorem frontierLeft_middle_traceBranchValue_glue (r : ℝ) :
    frontierMiddleTrace frontierCStar -
        r * frontierMiddleTraceDeriv frontierCStar =
      frontierLeftTrace frontierCStar -
        r * frontierLeftTraceDeriv frontierCStar := by
  rw [frontierLeft_middle_trace_value_glue,
    frontierLeft_middle_trace_deriv_glue]

theorem frontierLeft_middle_rankOneSlope_glue (u v : ℝ) :
    u * frontierMiddleTraceDeriv frontierCStar -
        (((2 * frontierCStar) * u - v) / 2) *
          frontierMiddleTraceSecond frontierCStar =
      u * frontierLeftTraceDeriv frontierCStar -
        (((2 * frontierCStar) * u - v) / 2) *
          frontierLeftTraceSecond frontierCStar := by
  rw [frontierLeft_middle_trace_deriv_glue,
    frontierLeft_middle_trace_second_glue]

theorem frontierMiddle_right_traceBranchValue_glue (r : ℝ) :
    frontierMiddleTrace (frontierCStar + 2 * frontierEpsilon) -
        r * frontierMiddleTraceDeriv (frontierCStar + 2 * frontierEpsilon) =
      frontierRightTailTrace (frontierCStar + 2 * frontierEpsilon) -
        r * frontierRightTailTraceDeriv
          (frontierCStar + 2 * frontierEpsilon) := by
  rw [frontierMiddle_right_trace_value_glue,
    frontierMiddle_right_trace_deriv_glue]

theorem frontierMiddle_right_rankOneSlope_glue (u v : ℝ) :
    u * frontierMiddleTraceDeriv (frontierCStar + 2 * frontierEpsilon) -
        (((2 * (frontierCStar + 2 * frontierEpsilon)) * u - v) / 2) *
          frontierMiddleTraceSecond (frontierCStar + 2 * frontierEpsilon) =
      u * frontierRightTailTraceDeriv (frontierCStar + 2 * frontierEpsilon) -
        (((2 * (frontierCStar + 2 * frontierEpsilon)) * u - v) / 2) *
          frontierRightTailTraceSecond
            (frontierCStar + 2 * frontierEpsilon) := by
  rw [frontierMiddle_right_trace_deriv_glue,
    frontierMiddle_right_trace_second_glue]

theorem frontierLeft_middle_rankOneSlope_glue_of_CPlus_eq_leftBoundary
    {x1 x2 u v : ℝ}
    (hC : frontierCPlus frontierEpsilon x1 x2 = frontierCStar) :
    u * frontierMiddleTraceDeriv (frontierCPlus frontierEpsilon x1 x2) -
        (((2 * frontierCPlus frontierEpsilon x1 x2) * u - v) / 2) *
          frontierMiddleTraceSecond (frontierCPlus frontierEpsilon x1 x2) =
      u * frontierLeftTraceDeriv (frontierCPlus frontierEpsilon x1 x2) -
        (((2 * frontierCPlus frontierEpsilon x1 x2) * u - v) / 2) *
          frontierLeftTraceSecond (frontierCPlus frontierEpsilon x1 x2) := by
  rw [hC]
  exact frontierLeft_middle_rankOneSlope_glue u v

theorem frontierMiddle_right_rankOneSlope_glue_of_CPlus_eq_rightBoundary
    {x1 x2 u v : ℝ}
    (hC :
      frontierCPlus frontierEpsilon x1 x2 =
        frontierCStar + 2 * frontierEpsilon) :
    u * frontierMiddleTraceDeriv (frontierCPlus frontierEpsilon x1 x2) -
        (((2 * frontierCPlus frontierEpsilon x1 x2) * u - v) / 2) *
          frontierMiddleTraceSecond (frontierCPlus frontierEpsilon x1 x2) =
      u * frontierRightTailTraceDeriv (frontierCPlus frontierEpsilon x1 x2) -
        (((2 * frontierCPlus frontierEpsilon x1 x2) * u - v) / 2) *
          frontierRightTailTraceSecond (frontierCPlus frontierEpsilon x1 x2) := by
  rw [hC]
  exact frontierMiddle_right_rankOneSlope_glue u v

theorem frontierLeftPiece_eq_middlePiece_of_CPlus_eq_leftBoundary
    {x1 x2 : ℝ}
    (hC : frontierCPlus frontierEpsilon x1 x2 = frontierCStar) :
    frontierLeftPiece x1 x2 = frontierMiddlePiece x1 x2 := by
  rw [frontierLeftPiece_trace_form, frontierMiddlePiece_trace_form, hC,
    frontierLeft_middle_trace_value_glue,
    frontierLeft_middle_trace_deriv_glue]

theorem frontierMajorant_eq_middlePiece_of_CPlus_eq_leftBoundary
    {x1 x2 : ℝ}
    (hC : frontierCPlus frontierEpsilon x1 x2 = frontierCStar) :
    frontierMajorant x1 x2 = frontierMiddlePiece x1 x2 := by
  rw [frontierMajorant_eq_leftPiece_of_CPlus (by rw [hC]),
    frontierLeftPiece_eq_middlePiece_of_CPlus_eq_leftBoundary hC]

theorem frontierMiddlePiece_eq_rightTailPiece_of_CPlus_eq_rightBoundary
    {x1 x2 : ℝ}
    (hC :
      frontierCPlus frontierEpsilon x1 x2 =
        frontierCStar + 2 * frontierEpsilon) :
    frontierMiddlePiece x1 x2 = frontierRightTailPiece x1 x2 := by
  rw [frontierMiddlePiece_trace_form, frontierRightTailPiece_trace_form, hC,
    frontierMiddle_right_trace_value_glue,
    frontierMiddle_right_trace_deriv_glue]

theorem frontierMajorant_eq_rightTailPiece_of_CPlus_eq_rightBoundary
    {x1 x2 : ℝ}
    (hC :
      frontierCPlus frontierEpsilon x1 x2 =
        frontierCStar + 2 * frontierEpsilon) :
    frontierMajorant x1 x2 = frontierRightTailPiece x1 x2 := by
  rw [frontierMajorant_eq_middlePiece_of_CPlus
      (by rw [hC]; linarith [frontierEpsilon_pos]) (by rw [hC]),
    frontierMiddlePiece_eq_rightTailPiece_of_CPlus_eq_rightBoundary hC]

theorem frontier_trace_rankOne_quadratic_identity
    (third r C u v : ℝ) :
    (-(C ^ 2 * third / r)) * u ^ 2 +
        2 * (C * third / (2 * r)) * u * v +
          (-(third / (4 * r))) * v ^ 2 =
      -(third / (4 * r)) * ((2 * C) * u - v) ^ 2 := by
  ring

theorem frontier_trace_rankOne_quadratic_nonpos
    {third r C u v : ℝ} (hthird : 0 ≤ third) (hr : 0 < r) :
    -(third / (4 * r)) * ((2 * C) * u - v) ^ 2 ≤ 0 := by
  have hden : 0 < 4 * r := by nlinarith
  have hcoef : 0 ≤ third / (4 * r) :=
    div_nonneg hthird (le_of_lt hden)
  have hsq : 0 ≤ ((2 * C) * u - v) ^ 2 := sq_nonneg _
  nlinarith [mul_nonneg hcoef hsq]

theorem frontier_trace_rankOne_hessianQuadratic_nonpos
    {third r C u v : ℝ} (hthird : 0 ≤ third) (hr : 0 < r) :
    (-(C ^ 2 * third / r)) * u ^ 2 +
        2 * (C * third / (2 * r)) * u * v +
          (-(third / (4 * r))) * v ^ 2 ≤ 0 := by
  rw [frontier_trace_rankOne_quadratic_identity]
  exact frontier_trace_rankOne_quadratic_nonpos hthird hr

theorem frontierLeftTrace_rankOne_hessianQuadratic_nonpos
    {r C u v : ℝ} (hr : 0 < r) :
    (-(C ^ 2 * frontierLeftTraceThird C / r)) * u ^ 2 +
        2 * (C * frontierLeftTraceThird C / (2 * r)) * u * v +
          (-(frontierLeftTraceThird C / (4 * r))) * v ^ 2 ≤ 0 := by
  exact frontier_trace_rankOne_hessianQuadratic_nonpos
    (frontierLeftTraceThird_nonneg C) hr

theorem frontierMiddleTrace_rankOne_hessianQuadratic_zero
    (r C u v : ℝ) :
    (-(C ^ 2 * frontierMiddleTraceThird C / r)) * u ^ 2 +
        2 * (C * frontierMiddleTraceThird C / (2 * r)) * u * v +
          (-(frontierMiddleTraceThird C / (4 * r))) * v ^ 2 = 0 := by
  rw [frontierMiddleTraceThird_eq_zero]
  ring

theorem frontierMiddleTrace_rankOne_hessianQuadratic_nonpos
    {r C u v : ℝ} :
    (-(C ^ 2 * frontierMiddleTraceThird C / r)) * u ^ 2 +
        2 * (C * frontierMiddleTraceThird C / (2 * r)) * u * v +
          (-(frontierMiddleTraceThird C / (4 * r))) * v ^ 2 ≤ 0 := by
  rw [frontierMiddleTrace_rankOne_hessianQuadratic_zero]

theorem frontierRightTailTrace_rankOne_hessianQuadratic_nonpos
    {r C u v : ℝ} (hr : 0 < r) :
    (-(C ^ 2 * frontierRightTailTraceThird C / r)) * u ^ 2 +
        2 * (C * frontierRightTailTraceThird C / (2 * r)) * u * v +
          (-(frontierRightTailTraceThird C / (4 * r))) * v ^ 2 ≤ 0 := by
  exact frontier_trace_rankOne_hessianQuadratic_nonpos
    (frontierRightTailTraceThird_nonneg C) hr

theorem frontier_segment_jensen_of_hasDerivWithinAt2_nonpos
    {f f' f'' : ℝ → ℝ}
    (hf : ContinuousOn f (Set.Icc (0 : ℝ) 1))
    (hf' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f (f' t) (Set.Ioo (0 : ℝ) 1) t)
    (hf'' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f' (f'' t) (Set.Ioo (0 : ℝ) 1) t)
    (hf''_nonpos : ∀ t ∈ Set.Ioo (0 : ℝ) 1, f'' t ≤ 0)
    {θ : ℝ} (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    f θ ≥ θ * f 1 + (1 - θ) * f 0 := by
  have hconc : ConcaveOn ℝ (Set.Icc (0 : ℝ) 1) f := by
    refine concaveOn_of_hasDerivWithinAt2_nonpos
      (D := Set.Icc (0 : ℝ) 1) (f := f) (f' := f') (f'' := f'')
      (convex_Icc (0 : ℝ) 1) hf ?_ ?_ ?_
    · intro t ht
      simpa [interior_Icc] using
        (hf' t (by simpa [interior_Icc] using ht))
    · intro t ht
      simpa [interior_Icc] using
        (hf'' t (by simpa [interior_Icc] using ht))
    · intro t ht
      rw [interior_Icc] at ht
      exact hf''_nonpos t ht
  have hθ_nonneg : 0 ≤ 1 - θ := by linarith
  have hmain :=
    hconc.2 (x := (1 : ℝ)) (y := (0 : ℝ))
      (by norm_num : (1 : ℝ) ∈ Set.Icc (0 : ℝ) 1)
      (by norm_num : (0 : ℝ) ∈ Set.Icc (0 : ℝ) 1)
      hθ0 hθ_nonneg (by ring : θ + (1 - θ) = (1 : ℝ))
  simpa [sub_eq_add_neg, mul_comm, mul_left_comm, mul_assoc] using hmain

theorem frontier_branchSegment_jensen_of_rankOne_secondDerivative
    {f f' : ℝ → ℝ} {third r C u v θ : ℝ}
    (hf : ContinuousOn f (Set.Icc (0 : ℝ) 1))
    (hf' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f (f' t) (Set.Ioo (0 : ℝ) 1) t)
    (hf'' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f'
          ((-(C ^ 2 * third / r)) * u ^ 2 +
            2 * (C * third / (2 * r)) * u * v +
              (-(third / (4 * r))) * v ^ 2)
          (Set.Ioo (0 : ℝ) 1) t)
    (hthird : 0 ≤ third) (hr : 0 < r)
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    f θ ≥ θ * f 1 + (1 - θ) * f 0 := by
  refine frontier_segment_jensen_of_hasDerivWithinAt2_nonpos
    hf hf' hf'' ?_ hθ0 hθ1
  intro t _ht
  exact frontier_trace_rankOne_hessianQuadratic_nonpos hthird hr

theorem frontierLeftTrace_branchSegment_jensen_of_rankOne_secondDerivative
    {f f' : ℝ → ℝ} {r C u v θ : ℝ}
    (hf : ContinuousOn f (Set.Icc (0 : ℝ) 1))
    (hf' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f (f' t) (Set.Ioo (0 : ℝ) 1) t)
    (hf'' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f'
          ((-(C ^ 2 * frontierLeftTraceThird C / r)) * u ^ 2 +
            2 * (C * frontierLeftTraceThird C / (2 * r)) * u * v +
              (-(frontierLeftTraceThird C / (4 * r))) * v ^ 2)
          (Set.Ioo (0 : ℝ) 1) t)
    (hr : 0 < r)
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    f θ ≥ θ * f 1 + (1 - θ) * f 0 := by
  exact frontier_branchSegment_jensen_of_rankOne_secondDerivative
    hf hf' hf'' (frontierLeftTraceThird_nonneg C) hr hθ0 hθ1

theorem frontierRightTailTrace_branchSegment_jensen_of_rankOne_secondDerivative
    {f f' : ℝ → ℝ} {r C u v θ : ℝ}
    (hf : ContinuousOn f (Set.Icc (0 : ℝ) 1))
    (hf' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f (f' t) (Set.Ioo (0 : ℝ) 1) t)
    (hf'' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f'
          ((-(C ^ 2 * frontierRightTailTraceThird C / r)) * u ^ 2 +
            2 * (C * frontierRightTailTraceThird C / (2 * r)) * u * v +
              (-(frontierRightTailTraceThird C / (4 * r))) * v ^ 2)
          (Set.Ioo (0 : ℝ) 1) t)
    (hr : 0 < r)
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    f θ ≥ θ * f 1 + (1 - θ) * f 0 := by
  exact frontier_branchSegment_jensen_of_rankOne_secondDerivative
    hf hf' hf'' (frontierRightTailTraceThird_nonneg C) hr hθ0 hθ1

theorem frontierLeftPiece_jensen_of_rankOne_radius_pos
    {y1 y2 z1 z2 θ : ℝ}
    (hr :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        0 < frontierRadius frontierEpsilon
          (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierLeftPiece
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ≥
      θ * frontierLeftPiece y1 y2 +
        (1 - θ) * frontierLeftPiece z1 z2 := by
  let u : ℝ := y1 - z1
  let v : ℝ := y2 - z2
  let C : ℝ → ℝ := fun t ↦
    frontierCPlus frontierEpsilon (z1 + t * u) (z2 + t * v)
  let r : ℝ → ℝ := fun t ↦
    frontierRadius frontierEpsilon (z1 + t * u) (z2 + t * v)
  let f : ℝ → ℝ := fun t ↦ frontierLeftPiece (z1 + t * u) (z2 + t * v)
  let f' : ℝ → ℝ := fun t ↦
    u * frontierLeftTraceDeriv (C t) -
      (((2 * C t) * u - v) / 2) * frontierLeftTraceSecond (C t)
  let f'' : ℝ → ℝ := fun t ↦
    (-(C t ^ 2 * frontierLeftTraceThird (C t) / r t)) * u ^ 2 +
      2 * (C t * frontierLeftTraceThird (C t) / (2 * r t)) * u * v +
        (-(frontierLeftTraceThird (C t) / (4 * r t))) * v ^ 2
  have hf : ContinuousOn f (Set.Icc (0 : ℝ) 1) := by
    have hf_eq :
        f = fun t ↦ frontierLeftTrace (C t) - r t * frontierLeftTraceDeriv (C t) := by
      funext t
      dsimp [f, C, r]
      rw [frontierLeftPiece_trace_form]
    have hC : Continuous C := by
      dsimp [C]
      have hpair :
          Continuous (fun t : ℝ => (z1 + t * u, z2 + t * v)) := by
        continuity
      simpa [Function.comp_def] using
        (frontierCPlus_continuous frontierEpsilon).comp hpair
    have hrcont : Continuous r := by
      dsimp [r, frontierRadius]
      continuity
    have htrace : Continuous (fun t ↦ frontierLeftTrace (C t)) := by
      unfold frontierLeftTrace
      continuity
    have htraceDeriv : Continuous (fun t ↦ frontierLeftTraceDeriv (C t)) := by
      unfold frontierLeftTraceDeriv
      continuity
    rw [hf_eq]
    exact (htrace.sub (hrcont.mul htraceDeriv)).continuousOn
  have hf' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f (f' t) (Set.Ioo (0 : ℝ) 1) t := by
    intro t ht
    have hder :=
      frontierLeftPiece_hasDerivAt_along_rankOne_of_radius_pos
        (x1 := z1) (x2 := z2) (u := u) (v := v) (t := t)
        (by simpa [u, v, r] using hr t ht)
    exact hder.hasDerivWithinAt
  have hf'' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f' (f'' t) (Set.Ioo (0 : ℝ) 1) t := by
    intro t ht
    have hder :=
      frontierLeftPiece_rankOne_slope_hasDerivAt_along_of_radius_pos
        (x1 := z1) (x2 := z2) (u := u) (v := v) (t := t)
        (by simpa [u, v, r] using hr t ht)
    exact hder.hasDerivWithinAt
  have hf''_nonpos :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1, f'' t ≤ 0 := by
    intro t ht
    exact frontierLeftTrace_rankOne_hessianQuadratic_nonpos
      (r := r t) (C := C t) (u := u) (v := v)
      (by simpa [u, v, r] using hr t ht)
  have hj :=
    frontier_segment_jensen_of_hasDerivWithinAt2_nonpos
      hf hf' hf'' hf''_nonpos hθ0 hθ1
  convert hj using 1 <;> dsimp [f, u, v] <;> ring_nf

theorem frontierRightTailPiece_jensen_of_rankOne_radius_pos
    {y1 y2 z1 z2 θ : ℝ}
    (hr :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        0 < frontierRadius frontierEpsilon
          (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierRightTailPiece
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ≥
      θ * frontierRightTailPiece y1 y2 +
        (1 - θ) * frontierRightTailPiece z1 z2 := by
  let u : ℝ := y1 - z1
  let v : ℝ := y2 - z2
  let C : ℝ → ℝ := fun t ↦
    frontierCPlus frontierEpsilon (z1 + t * u) (z2 + t * v)
  let r : ℝ → ℝ := fun t ↦
    frontierRadius frontierEpsilon (z1 + t * u) (z2 + t * v)
  let f : ℝ → ℝ := fun t ↦ frontierRightTailPiece (z1 + t * u) (z2 + t * v)
  let f' : ℝ → ℝ := fun t ↦
    u * frontierRightTailTraceDeriv (C t) -
      (((2 * C t) * u - v) / 2) * frontierRightTailTraceSecond (C t)
  let f'' : ℝ → ℝ := fun t ↦
    (-(C t ^ 2 * frontierRightTailTraceThird (C t) / r t)) * u ^ 2 +
      2 * (C t * frontierRightTailTraceThird (C t) / (2 * r t)) * u * v +
        (-(frontierRightTailTraceThird (C t) / (4 * r t))) * v ^ 2
  have hf : ContinuousOn f (Set.Icc (0 : ℝ) 1) := by
    have hf_eq :
        f = fun t ↦
          frontierRightTailTrace (C t) - r t * frontierRightTailTraceDeriv (C t) := by
      funext t
      dsimp [f, C, r]
      rw [frontierRightTailPiece_trace_form]
    have hC : Continuous C := by
      dsimp [C]
      have hpair :
          Continuous (fun t : ℝ => (z1 + t * u, z2 + t * v)) := by
        continuity
      simpa [Function.comp_def] using
        (frontierCPlus_continuous frontierEpsilon).comp hpair
    have hrcont : Continuous r := by
      dsimp [r, frontierRadius]
      continuity
    have htrace : Continuous (fun t ↦ frontierRightTailTrace (C t)) := by
      unfold frontierRightTailTrace
      continuity
    have htraceDeriv : Continuous (fun t ↦ frontierRightTailTraceDeriv (C t)) := by
      unfold frontierRightTailTraceDeriv
      continuity
    rw [hf_eq]
    exact (htrace.sub (hrcont.mul htraceDeriv)).continuousOn
  have hf' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f (f' t) (Set.Ioo (0 : ℝ) 1) t := by
    intro t ht
    have hder :=
      frontierRightTailPiece_hasDerivAt_along_rankOne_of_radius_pos
        (x1 := z1) (x2 := z2) (u := u) (v := v) (t := t)
        (by simpa [u, v, r] using hr t ht)
    exact hder.hasDerivWithinAt
  have hf'' :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        HasDerivWithinAt f' (f'' t) (Set.Ioo (0 : ℝ) 1) t := by
    intro t ht
    have hder :=
      frontierRightTailPiece_rankOne_slope_hasDerivAt_along_of_radius_pos
        (x1 := z1) (x2 := z2) (u := u) (v := v) (t := t)
        (by simpa [u, v, r] using hr t ht)
    exact hder.hasDerivWithinAt
  have hf''_nonpos :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1, f'' t ≤ 0 := by
    intro t ht
    exact frontierRightTailTrace_rankOne_hessianQuadratic_nonpos
      (r := r t) (C := C t) (u := u) (v := v)
      (by simpa [u, v, r] using hr t ht)
  have hj :=
    frontier_segment_jensen_of_hasDerivWithinAt2_nonpos
      hf hf' hf'' hf''_nonpos hθ0 hθ1
  convert hj using 1 <;> dsimp [f, u, v] <;> ring_nf

theorem frontierLeftPiece_jensen_of_rankOne_radius_pos_or_eq
    {y1 y2 z1 z2 θ : ℝ}
    (hcase :
      (∀ t ∈ Set.Ioo (0 : ℝ) 1,
        0 < frontierRadius frontierEpsilon
          (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2))) ∨
        (y1 = z1 ∧ y2 = z2))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierLeftPiece
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ≥
      θ * frontierLeftPiece y1 y2 +
        (1 - θ) * frontierLeftPiece z1 z2 := by
  rcases hcase with hr | ⟨hy1, hy2⟩
  · exact frontierLeftPiece_jensen_of_rankOne_radius_pos hr hθ0 hθ1
  · subst y1
    subst y2
    rw [show θ * z1 + (1 - θ) * z1 = z1 by ring,
      show θ * z2 + (1 - θ) * z2 = z2 by ring,
      show θ * frontierLeftPiece z1 z2 +
          (1 - θ) * frontierLeftPiece z1 z2 =
            frontierLeftPiece z1 z2 by ring]

theorem frontierRightTailPiece_jensen_of_rankOne_radius_pos_or_eq
    {y1 y2 z1 z2 θ : ℝ}
    (hcase :
      (∀ t ∈ Set.Ioo (0 : ℝ) 1,
        0 < frontierRadius frontierEpsilon
          (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2))) ∨
        (y1 = z1 ∧ y2 = z2))
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierRightTailPiece
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ≥
      θ * frontierRightTailPiece y1 y2 +
        (1 - θ) * frontierRightTailPiece z1 z2 := by
  rcases hcase with hr | ⟨hy1, hy2⟩
  · exact frontierRightTailPiece_jensen_of_rankOne_radius_pos hr hθ0 hθ1
  · subst y1
    subst y2
    rw [show θ * z1 + (1 - θ) * z1 = z1 by ring,
      show θ * z2 + (1 - θ) * z2 = z2 by ring,
      show θ * frontierRightTailPiece z1 z2 +
          (1 - θ) * frontierRightTailPiece z1 z2 =
            frontierRightTailPiece z1 z2 by ring]

theorem frontierLeftPiece_jensen_of_same_x
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hyz : y1 = z1)
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierLeftPiece
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ≥
      θ * frontierLeftPiece y1 y2 +
        (1 - θ) * frontierLeftPiece z1 z2 := by
  exact frontierLeftPiece_jensen_of_rankOne_radius_pos_or_eq
    (frontier_segment_radius_pos_or_eq_of_same_x hyΩ hzΩ hyz) hθ0 hθ1

theorem frontierRightTailPiece_jensen_of_same_x
    {y1 y2 z1 z2 θ : ℝ}
    (hyΩ : frontierOmega frontierEpsilon y1 y2)
    (hzΩ : frontierOmega frontierEpsilon z1 z2)
    (hyz : y1 = z1)
    (hθ0 : 0 ≤ θ) (hθ1 : θ ≤ 1) :
    frontierRightTailPiece
        (θ * y1 + (1 - θ) * z1)
        (θ * y2 + (1 - θ) * z2) ≥
      θ * frontierRightTailPiece y1 y2 +
        (1 - θ) * frontierRightTailPiece z1 z2 := by
  exact frontierRightTailPiece_jensen_of_rankOne_radius_pos_or_eq
    (frontier_segment_radius_pos_or_eq_of_same_x hyΩ hzΩ hyz) hθ0 hθ1

theorem frontierMajorant_upperBoundary_leftBranch_sameX_localJensen
    {x1 : ℝ} (hleft : x1 < frontierCStar) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ →
        |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
        |z1 - x1| < δ →
        |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 → y1 = z1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  have hC :
      frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) < frontierCStar := by
    rwa [frontierCPlus_upper_boundary]
  rcases frontierMajorant_leftBranchInterior_piece_neighborhood hC with
    ⟨δ, hδ_pos, hbranch⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ _hmixΩ hθ0 hθ1 hyz
  rcases hbranch y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hθ0 hθ1 with
    ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
  have hj :=
    frontierLeftPiece_jensen_of_same_x hyΩ hzΩ hyz hθ0 hθ1
  rw [hmixEq, hyEq, hzEq]
  exact hj

theorem frontierMajorant_upperBoundary_rightBranch_sameX_localJensen
    {x1 : ℝ} (hright : frontierCStar + 2 * frontierEpsilon < x1) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ →
        |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
        |z1 - x1| < δ →
        |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 → y1 = z1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  have hC :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) := by
    rwa [frontierCPlus_upper_boundary]
  rcases frontierMajorant_rightBranchInterior_piece_neighborhood hC with
    ⟨δ, hδ_pos, hbranch⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ _hmixΩ hθ0 hθ1 hyz
  rcases hbranch y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hθ0 hθ1 with
    ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
  have hj :=
    frontierRightTailPiece_jensen_of_same_x hyΩ hzΩ hyz hθ0 hθ1
  rw [hmixEq, hyEq, hzEq]
  exact hj

theorem frontierMajorant_leftBranchInterior_localConcavity_of_radius_pos
    {x1 x2 : ℝ} (_hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hleft : frontierCPlus frontierEpsilon x1 x2 < frontierCStar)
    (hrx : 0 < frontierRadius frontierEpsilon x1 x2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  rcases frontierMajorant_leftBranchInterior_piece_neighborhood hleft with
    ⟨δB, hδB_pos, hbranch⟩
  let R : ℝ × ℝ → ℝ := fun p ↦ frontierRadius frontierEpsilon p.1 p.2
  let rx : ℝ := R (x1, x2)
  let η : ℝ := rx / 2
  have hη_pos : 0 < η := by
    dsimp [η, rx, R]
    linarith
  have hcont : ContinuousAt R (x1, x2) := by
    exact (frontierRadius_continuous frontierEpsilon).continuousAt
  rw [Metric.continuousAt_iff] at hcont
  rcases hcont η hη_pos with ⟨δR, hδR_pos, hδR⟩
  let δ : ℝ := min δB δR
  have hδ_pos : 0 < δ := lt_min hδB_pos hδR_pos
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 _hyΩ _hzΩ _hmixΩ hθ0 hθ1
  have hy1B : |y1 - x1| < δB := lt_of_lt_of_le hy1 (min_le_left δB δR)
  have hy2B : |y2 - x2| < δB := lt_of_lt_of_le hy2 (min_le_left δB δR)
  have hz1B : |z1 - x1| < δB := lt_of_lt_of_le hz1 (min_le_left δB δR)
  have hz2B : |z2 - x2| < δB := lt_of_lt_of_le hz2 (min_le_left δB δR)
  rcases hbranch y1 y2 z1 z2 θ hy1B hy2B hz1B hz2B hθ0 hθ1 with
    ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
  have hy1R : |y1 - x1| < δR := lt_of_lt_of_le hy1 (min_le_right δB δR)
  have hy2R : |y2 - x2| < δR := lt_of_lt_of_le hy2 (min_le_right δB δR)
  have hz1R : |z1 - x1| < δR := lt_of_lt_of_le hz1 (min_le_right δB δR)
  have hz2R : |z2 - x2| < δR := lt_of_lt_of_le hz2 (min_le_right δB δR)
  have radius_stable :
      ∀ p : ℝ × ℝ, dist p (x1, x2) < δR → 0 < R p := by
    intro p hp
    have hpdist := hδR hp
    have hpabs : |R p - rx| < η := by
      simpa [Real.dist_eq, rx] using hpdist
    have hp_bounds := abs_lt.mp hpabs
    dsimp [η, rx, R] at hp_bounds
    linarith
  have hrseg :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        0 < frontierRadius frontierEpsilon
          (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)) := by
    intro t ht
    have ht0 : 0 ≤ t := le_of_lt ht.1
    have ht1 : t ≤ 1 := le_of_lt ht.2
    have hcoord1 :
        |(z1 + t * (y1 - z1)) - x1| < δR := by
      convert frontier_convex_coord_abs_lt hy1R hz1R ht0 ht1 using 1
      ring_nf
    have hcoord2 :
        |(z2 + t * (y2 - z2)) - x2| < δR := by
      convert frontier_convex_coord_abs_lt hy2R hz2R ht0 ht1 using 1
      ring_nf
    exact radius_stable
      ((z1 + t * (y1 - z1)), (z2 + t * (y2 - z2)))
      (frontier_pair_dist_lt_of_abs hcoord1 hcoord2)
  have hj :=
    frontierLeftPiece_jensen_of_rankOne_radius_pos
      (y1 := y1) (y2 := y2) (z1 := z1) (z2 := z2) (θ := θ)
      hrseg hθ0 hθ1
  rw [hmixEq, hyEq, hzEq]
  exact hj

theorem frontierMajorant_rightBranchInterior_localConcavity_of_radius_pos
    {x1 x2 : ℝ} (_hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hright :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1 x2)
    (hrx : 0 < frontierRadius frontierEpsilon x1 x2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  rcases frontierMajorant_rightBranchInterior_piece_neighborhood hright with
    ⟨δB, hδB_pos, hbranch⟩
  let R : ℝ × ℝ → ℝ := fun p ↦ frontierRadius frontierEpsilon p.1 p.2
  let rx : ℝ := R (x1, x2)
  let η : ℝ := rx / 2
  have hη_pos : 0 < η := by
    dsimp [η, rx, R]
    linarith
  have hcont : ContinuousAt R (x1, x2) := by
    exact (frontierRadius_continuous frontierEpsilon).continuousAt
  rw [Metric.continuousAt_iff] at hcont
  rcases hcont η hη_pos with ⟨δR, hδR_pos, hδR⟩
  let δ : ℝ := min δB δR
  have hδ_pos : 0 < δ := lt_min hδB_pos hδR_pos
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 _hyΩ _hzΩ _hmixΩ hθ0 hθ1
  have hy1B : |y1 - x1| < δB := lt_of_lt_of_le hy1 (min_le_left δB δR)
  have hy2B : |y2 - x2| < δB := lt_of_lt_of_le hy2 (min_le_left δB δR)
  have hz1B : |z1 - x1| < δB := lt_of_lt_of_le hz1 (min_le_left δB δR)
  have hz2B : |z2 - x2| < δB := lt_of_lt_of_le hz2 (min_le_left δB δR)
  rcases hbranch y1 y2 z1 z2 θ hy1B hy2B hz1B hz2B hθ0 hθ1 with
    ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
  have hy1R : |y1 - x1| < δR := lt_of_lt_of_le hy1 (min_le_right δB δR)
  have hy2R : |y2 - x2| < δR := lt_of_lt_of_le hy2 (min_le_right δB δR)
  have hz1R : |z1 - x1| < δR := lt_of_lt_of_le hz1 (min_le_right δB δR)
  have hz2R : |z2 - x2| < δR := lt_of_lt_of_le hz2 (min_le_right δB δR)
  have radius_stable :
      ∀ p : ℝ × ℝ, dist p (x1, x2) < δR → 0 < R p := by
    intro p hp
    have hpdist := hδR hp
    have hpabs : |R p - rx| < η := by
      simpa [Real.dist_eq, rx] using hpdist
    have hp_bounds := abs_lt.mp hpabs
    dsimp [η, rx, R] at hp_bounds
    linarith
  have hrseg :
      ∀ t ∈ Set.Ioo (0 : ℝ) 1,
        0 < frontierRadius frontierEpsilon
          (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2)) := by
    intro t ht
    have ht0 : 0 ≤ t := le_of_lt ht.1
    have ht1 : t ≤ 1 := le_of_lt ht.2
    have hcoord1 :
        |(z1 + t * (y1 - z1)) - x1| < δR := by
      convert frontier_convex_coord_abs_lt hy1R hz1R ht0 ht1 using 1
      ring_nf
    have hcoord2 :
        |(z2 + t * (y2 - z2)) - x2| < δR := by
      convert frontier_convex_coord_abs_lt hy2R hz2R ht0 ht1 using 1
      ring_nf
    exact radius_stable
      ((z1 + t * (y1 - z1)), (z2 + t * (y2 - z2)))
      (frontier_pair_dist_lt_of_abs hcoord1 hcoord2)
  have hj :=
    frontierRightTailPiece_jensen_of_rankOne_radius_pos
      (y1 := y1) (y2 := y2) (z1 := z1) (z2 := z2) (θ := θ)
      hrseg hθ0 hθ1
  rw [hmixEq, hyEq, hzEq]
  exact hj

theorem frontierMajorant_leftBranchInterior_localConcavity_of_upper_strict
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hleft : frontierCPlus frontierEpsilon x1 x2 < frontierCStar)
    (hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  exact frontierMajorant_leftBranchInterior_localConcavity_of_radius_pos
    hxΩ hleft ((frontierRadius_pos_iff_upper_strict_of_omega hxΩ).2 hupper)

theorem frontierMajorant_rightBranchInterior_localConcavity_of_upper_strict
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hright :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1 x2)
    (hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  exact frontierMajorant_rightBranchInterior_localConcavity_of_radius_pos
    hxΩ hright ((frontierRadius_pos_iff_upper_strict_of_omega hxΩ).2 hupper)

theorem frontierMajorant_leftBranchInterior_localConcavity
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hleft : frontierCPlus frontierEpsilon x1 x2 < frontierCStar)
    (hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  exact frontierMajorant_leftBranchInterior_localConcavity_of_upper_strict
    hxΩ hleft hupper

theorem frontierMajorant_rightBranchInterior_localConcavity
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hright :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1 x2)
    (hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  exact frontierMajorant_rightBranchInterior_localConcavity_of_upper_strict
    hxΩ hright hupper

theorem frontierBoundaryMajorantResidualBudget_leftBranchInteriorLocalBellmanSplit
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hleft : frontierCPlus frontierEpsilon x1 x2 < frontierCStar)
    (hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          θ * (frontierMajorant y1 y2 - frontierPhi y1) +
              (1 - θ) * (frontierMajorant z1 z2 - frontierPhi z1) ≤
            frontierMajorant
                (θ * y1 + (1 - θ) * z1)
                (θ * y2 + (1 - θ) * z2) -
              (θ * frontierPhi y1 + (1 - θ) * frontierPhi z1) := by
  rcases frontierMajorant_leftBranchInterior_localConcavity hxΩ hleft hupper with
    ⟨δ, hδ_pos, hconcave⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  have hbellman :
      frontierMajorant
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) ≥
        θ * frontierMajorant y1 y2 +
          (1 - θ) * frontierMajorant z1 z2 :=
    hconcave y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  nlinarith

theorem frontierBoundaryMajorantResidualBudget_rightBranchInteriorLocalBellmanSplit
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hright :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1 x2)
    (hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          θ * (frontierMajorant y1 y2 - frontierPhi y1) +
              (1 - θ) * (frontierMajorant z1 z2 - frontierPhi z1) ≤
            frontierMajorant
                (θ * y1 + (1 - θ) * z1)
                (θ * y2 + (1 - θ) * z2) -
              (θ * frontierPhi y1 + (1 - θ) * frontierPhi z1) := by
  rcases frontierMajorant_rightBranchInterior_localConcavity hxΩ hright hupper with
    ⟨δ, hδ_pos, hconcave⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  have hbellman :
      frontierMajorant
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) ≥
        θ * frontierMajorant y1 y2 +
          (1 - θ) * frontierMajorant z1 z2 :=
    hconcave y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  nlinarith

theorem frontierMajorant_strictUpper_nonBoundary_localConcavity
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2)
    (hleftBoundary :
      frontierCPlus frontierEpsilon x1 x2 ≠ frontierCStar)
    (hrightBoundary :
      frontierCPlus frontierEpsilon x1 x2 ≠
        frontierCStar + 2 * frontierEpsilon) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2 := by
  by_cases hleft : frontierCPlus frontierEpsilon x1 x2 ≤ frontierCStar
  · have hleft_strict :
      frontierCPlus frontierEpsilon x1 x2 < frontierCStar :=
      lt_of_le_of_ne hleft hleftBoundary
    exact frontierMajorant_leftBranchInterior_localConcavity
      hxΩ hleft_strict hupper
  · have hleft_strict :
      frontierCStar < frontierCPlus frontierEpsilon x1 x2 :=
      not_le.mp hleft
    by_cases hmiddle :
        frontierCPlus frontierEpsilon x1 x2 ≤
          frontierCStar + 2 * frontierEpsilon
    · have hright_strict :
        frontierCPlus frontierEpsilon x1 x2 <
          frontierCStar + 2 * frontierEpsilon :=
        lt_of_le_of_ne hmiddle hrightBoundary
      exact frontierMajorant_middleBranchInterior_localConcavity
        hxΩ hleft_strict hright_strict
    · have hright_strict :
        frontierCStar + 2 * frontierEpsilon <
          frontierCPlus frontierEpsilon x1 x2 :=
        not_le.mp hmiddle
      exact frontierMajorant_rightBranchInterior_localConcavity
        hxΩ hright_strict hupper

theorem frontierBoundaryMajorantResidualBudget_strictUpperNonBoundaryLocalBellmanSplit
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2)
    (hleftBoundary :
      frontierCPlus frontierEpsilon x1 x2 ≠ frontierCStar)
    (hrightBoundary :
      frontierCPlus frontierEpsilon x1 x2 ≠
        frontierCStar + 2 * frontierEpsilon) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          θ * (frontierMajorant y1 y2 - frontierPhi y1) +
              (1 - θ) * (frontierMajorant z1 z2 - frontierPhi z1) ≤
            frontierMajorant
                (θ * y1 + (1 - θ) * z1)
                (θ * y2 + (1 - θ) * z2) -
              (θ * frontierPhi y1 + (1 - θ) * frontierPhi z1) := by
  rcases frontierMajorant_strictUpper_nonBoundary_localConcavity
      hxΩ hupper hleftBoundary hrightBoundary with
    ⟨δ, hδ_pos, hconcave⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  have hbellman :
      frontierMajorant
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) ≥
        θ * frontierMajorant y1 y2 +
          (1 - θ) * frontierMajorant z1 z2 :=
    hconcave y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  nlinarith

theorem frontierBoundaryMajorantResidualBudget_localBellmanSplit_of_majorantLocalConcavity
    {x1 x2 : ℝ}
    (hlocal : frontierMajorantLocalConcavityAt x1 x2) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          θ * (frontierMajorant y1 y2 - frontierPhi y1) +
              (1 - θ) * (frontierMajorant z1 z2 - frontierPhi z1) ≤
            frontierMajorant
                (θ * y1 + (1 - θ) * z1)
                (θ * y2 + (1 - θ) * z2) -
              (θ * frontierPhi y1 + (1 - θ) * frontierPhi z1) := by
  rcases hlocal with ⟨δ, hδ_pos, hconcave⟩
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  have hbellman :
      frontierMajorant
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) ≥
        θ * frontierMajorant y1 y2 +
          (1 - θ) * frontierMajorant z1 z2 :=
    hconcave y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  nlinarith

theorem frontierMajorant_leftBranchInterior_localConcavity_or_upperBoundary
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hleft : frontierCPlus frontierEpsilon x1 x2 < frontierCStar) :
    (∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2) ∨
      x2 = x1 ^ 2 + frontierEpsilon ^ 2 ∧
        x1 < frontierCStar ∧
          frontierMajorant x1 x2 = frontierLeftTrace x1 := by
  by_cases hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2
  · left
    exact frontierMajorant_leftBranchInterior_localConcavity hxΩ hleft hupper
  · right
    have hx2 : x2 = x1 ^ 2 + frontierEpsilon ^ 2 := by
      linarith [hxΩ.2]
    have hr : frontierRadius frontierEpsilon x1 x2 = 0 := by
      rw [hx2, frontierRadius_upper_boundary]
    exact frontierMajorant_leftBranch_radius_zero_upper_boundary hxΩ hleft hr

theorem frontierMajorant_rightBranchInterior_localConcavity_or_upperBoundary
    {x1 x2 : ℝ} (hxΩ : frontierOmega frontierEpsilon x1 x2)
    (hright :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1 x2) :
    (∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ → |y2 - x2| < δ →
        |z1 - x1| < δ → |z2 - x2| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          frontierMajorant
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) ≥
            θ * frontierMajorant y1 y2 +
              (1 - θ) * frontierMajorant z1 z2) ∨
      x2 = x1 ^ 2 + frontierEpsilon ^ 2 ∧
        frontierCStar + 2 * frontierEpsilon < x1 ∧
          frontierMajorant x1 x2 = frontierRightTailTrace x1 := by
  by_cases hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2
  · left
    exact frontierMajorant_rightBranchInterior_localConcavity hxΩ hright hupper
  · right
    have hx2 : x2 = x1 ^ 2 + frontierEpsilon ^ 2 := by
      linarith [hxΩ.2]
    have hr : frontierRadius frontierEpsilon x1 x2 = 0 := by
      rw [hx2, frontierRadius_upper_boundary]
    exact frontierMajorant_rightBranch_radius_zero_upper_boundary hxΩ hright hr

theorem frontierMajorant_upperBoundary_middleBranch_localConcavity
    {x1 : ℝ} (hleft : frontierCStar < x1)
    (hright : x1 < frontierCStar + 2 * frontierEpsilon) :
    frontierMajorantLocalConcavityAt x1
      (x1 ^ 2 + frontierEpsilon ^ 2) := by
  have hxΩ :
      frontierOmega frontierEpsilon x1
        (x1 ^ 2 + frontierEpsilon ^ 2) :=
    frontierOmega_upper_boundary x1
  have hC_left :
      frontierCStar <
        frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) := by
    rwa [frontierCPlus_upper_boundary]
  have hC_right :
      frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) <
        frontierCStar + 2 * frontierEpsilon := by
    rwa [frontierCPlus_upper_boundary]
  exact frontierMajorant_middleBranchInterior_localConcavity
    hxΩ hC_left hC_right

theorem frontierBoundaryMajorantResidualBudget_upperBoundaryMiddleLocalBellmanSplit
    {x1 : ℝ} (hleft : frontierCStar < x1)
    (hright : x1 < frontierCStar + 2 * frontierEpsilon) :
    ∃ δ : ℝ, 0 < δ ∧
      ∀ y1 y2 z1 z2 θ : ℝ,
        |y1 - x1| < δ →
        |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
        |z1 - x1| < δ →
        |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
        frontierOmega frontierEpsilon y1 y2 →
        frontierOmega frontierEpsilon z1 z2 →
        frontierOmega frontierEpsilon
          (θ * y1 + (1 - θ) * z1)
          (θ * y2 + (1 - θ) * z2) →
        0 ≤ θ → θ ≤ 1 →
          θ * (frontierMajorant y1 y2 - frontierPhi y1) +
              (1 - θ) * (frontierMajorant z1 z2 - frontierPhi z1) ≤
            frontierMajorant
                (θ * y1 + (1 - θ) * z1)
                (θ * y2 + (1 - θ) * z2) -
              (θ * frontierPhi y1 + (1 - θ) * frontierPhi z1) := by
  exact
    frontierBoundaryMajorantResidualBudget_localBellmanSplit_of_majorantLocalConcavity
      (frontierMajorant_upperBoundary_middleBranch_localConcavity hleft hright)

theorem frontierMajorant_upperBoundary_leftBranch_localConcavity_of_segment_radius_pos_or_eq
    {x1 : ℝ} (hleft : x1 < frontierCStar)
    (hsegment :
      ∃ δ : ℝ, 0 < δ ∧
        ∀ y1 y2 z1 z2 θ : ℝ,
          |y1 - x1| < δ →
          |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          |z1 - x1| < δ →
          |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          frontierOmega frontierEpsilon y1 y2 →
          frontierOmega frontierEpsilon z1 z2 →
          frontierOmega frontierEpsilon
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) →
          0 ≤ θ → θ ≤ 1 →
            (∀ t ∈ Set.Ioo (0 : ℝ) 1,
              0 < frontierRadius frontierEpsilon
                (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2))) ∨
              (y1 = z1 ∧ y2 = z2)) :
    frontierMajorantLocalConcavityAt x1
      (x1 ^ 2 + frontierEpsilon ^ 2) := by
  have hC :
      frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) < frontierCStar := by
    rwa [frontierCPlus_upper_boundary]
  rcases frontierMajorant_leftBranchInterior_piece_neighborhood hC with
    ⟨δB, hδB_pos, hbranch⟩
  rcases hsegment with ⟨δR, hδR_pos, hsegment⟩
  let δ : ℝ := min δB δR
  have hδ_pos : 0 < δ := lt_min hδB_pos hδR_pos
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  have hy1B : |y1 - x1| < δB := lt_of_lt_of_le hy1 (min_le_left δB δR)
  have hy2B : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
    lt_of_lt_of_le hy2 (min_le_left δB δR)
  have hz1B : |z1 - x1| < δB := lt_of_lt_of_le hz1 (min_le_left δB δR)
  have hz2B : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
    lt_of_lt_of_le hz2 (min_le_left δB δR)
  rcases hbranch y1 y2 z1 z2 θ hy1B hy2B hz1B hz2B hθ0 hθ1 with
    ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
  have hy1R : |y1 - x1| < δR := lt_of_lt_of_le hy1 (min_le_right δB δR)
  have hy2R : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δR :=
    lt_of_lt_of_le hy2 (min_le_right δB δR)
  have hz1R : |z1 - x1| < δR := lt_of_lt_of_le hz1 (min_le_right δB δR)
  have hz2R : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δR :=
    lt_of_lt_of_le hz2 (min_le_right δB δR)
  have hcase :=
    hsegment y1 y2 z1 z2 θ hy1R hy2R hz1R hz2R
      hyΩ hzΩ hmixΩ hθ0 hθ1
  have hj :=
    frontierLeftPiece_jensen_of_rankOne_radius_pos_or_eq hcase hθ0 hθ1
  rw [hmixEq, hyEq, hzEq]
  exact hj

theorem frontierMajorant_upperBoundary_rightBranch_localConcavity_of_segment_radius_pos_or_eq
    {x1 : ℝ} (hright : frontierCStar + 2 * frontierEpsilon < x1)
    (hsegment :
      ∃ δ : ℝ, 0 < δ ∧
        ∀ y1 y2 z1 z2 θ : ℝ,
          |y1 - x1| < δ →
          |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          |z1 - x1| < δ →
          |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          frontierOmega frontierEpsilon y1 y2 →
          frontierOmega frontierEpsilon z1 z2 →
          frontierOmega frontierEpsilon
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) →
          0 ≤ θ → θ ≤ 1 →
            (∀ t ∈ Set.Ioo (0 : ℝ) 1,
              0 < frontierRadius frontierEpsilon
                (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2))) ∨
              (y1 = z1 ∧ y2 = z2)) :
    frontierMajorantLocalConcavityAt x1
      (x1 ^ 2 + frontierEpsilon ^ 2) := by
  have hC :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) := by
    rwa [frontierCPlus_upper_boundary]
  rcases frontierMajorant_rightBranchInterior_piece_neighborhood hC with
    ⟨δB, hδB_pos, hbranch⟩
  rcases hsegment with ⟨δR, hδR_pos, hsegment⟩
  let δ : ℝ := min δB δR
  have hδ_pos : 0 < δ := lt_min hδB_pos hδR_pos
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  have hy1B : |y1 - x1| < δB := lt_of_lt_of_le hy1 (min_le_left δB δR)
  have hy2B : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
    lt_of_lt_of_le hy2 (min_le_left δB δR)
  have hz1B : |z1 - x1| < δB := lt_of_lt_of_le hz1 (min_le_left δB δR)
  have hz2B : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
    lt_of_lt_of_le hz2 (min_le_left δB δR)
  rcases hbranch y1 y2 z1 z2 θ hy1B hy2B hz1B hz2B hθ0 hθ1 with
    ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
  have hy1R : |y1 - x1| < δR := lt_of_lt_of_le hy1 (min_le_right δB δR)
  have hy2R : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δR :=
    lt_of_lt_of_le hy2 (min_le_right δB δR)
  have hz1R : |z1 - x1| < δR := lt_of_lt_of_le hz1 (min_le_right δB δR)
  have hz2R : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δR :=
    lt_of_lt_of_le hz2 (min_le_right δB δR)
  have hcase :=
    hsegment y1 y2 z1 z2 θ hy1R hy2R hz1R hz2R
      hyΩ hzΩ hmixΩ hθ0 hθ1
  have hj :=
    frontierRightTailPiece_jensen_of_rankOne_radius_pos_or_eq hcase hθ0 hθ1
  rw [hmixEq, hyEq, hzEq]
  exact hj

theorem frontierMajorant_upperBoundary_leftBranch_localConcavity_of_strict_segment_radius_pos_or_eq
    {x1 : ℝ} (hleft : x1 < frontierCStar)
    (hsegment :
      ∃ δ : ℝ, 0 < δ ∧
        ∀ y1 y2 z1 z2 θ : ℝ,
          |y1 - x1| < δ →
          |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          |z1 - x1| < δ →
          |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          frontierOmega frontierEpsilon y1 y2 →
          frontierOmega frontierEpsilon z1 z2 →
          frontierOmega frontierEpsilon
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) →
          0 < θ → θ < 1 →
            (∀ t ∈ Set.Ioo (0 : ℝ) 1,
              0 < frontierRadius frontierEpsilon
                (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2))) ∨
              (y1 = z1 ∧ y2 = z2)) :
    frontierMajorantLocalConcavityAt x1
      (x1 ^ 2 + frontierEpsilon ^ 2) := by
  have hC :
      frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) < frontierCStar := by
    rwa [frontierCPlus_upper_boundary]
  rcases frontierMajorant_leftBranchInterior_piece_neighborhood hC with
    ⟨δB, hδB_pos, hbranch⟩
  rcases hsegment with ⟨δR, hδR_pos, hsegment⟩
  let δ : ℝ := min δB δR
  have hδ_pos : 0 < δ := lt_min hδB_pos hδR_pos
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  by_cases hθ_left : θ = 0
  · subst θ
    simp
  · by_cases hθ_right : θ = 1
    · subst θ
      simp
    · have hθ0' : 0 < θ := lt_of_le_of_ne hθ0 (Ne.symm hθ_left)
      have hθ1' : θ < 1 := lt_of_le_of_ne hθ1 hθ_right
      have hy1B : |y1 - x1| < δB := lt_of_lt_of_le hy1 (min_le_left δB δR)
      have hy2B : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
        lt_of_lt_of_le hy2 (min_le_left δB δR)
      have hz1B : |z1 - x1| < δB := lt_of_lt_of_le hz1 (min_le_left δB δR)
      have hz2B : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
        lt_of_lt_of_le hz2 (min_le_left δB δR)
      rcases hbranch y1 y2 z1 z2 θ hy1B hy2B hz1B hz2B hθ0 hθ1 with
        ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
      have hy1R : |y1 - x1| < δR := lt_of_lt_of_le hy1 (min_le_right δB δR)
      have hy2R : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δR :=
        lt_of_lt_of_le hy2 (min_le_right δB δR)
      have hz1R : |z1 - x1| < δR := lt_of_lt_of_le hz1 (min_le_right δB δR)
      have hz2R : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δR :=
        lt_of_lt_of_le hz2 (min_le_right δB δR)
      have hcase :=
        hsegment y1 y2 z1 z2 θ hy1R hy2R hz1R hz2R
          hyΩ hzΩ hmixΩ hθ0' hθ1'
      have hj :=
        frontierLeftPiece_jensen_of_rankOne_radius_pos_or_eq hcase hθ0 hθ1
      rw [hmixEq, hyEq, hzEq]
      exact hj

theorem frontierMajorant_upperBoundary_rightBranch_localConcavity_of_strict_segment_radius_pos_or_eq
    {x1 : ℝ} (hright : frontierCStar + 2 * frontierEpsilon < x1)
    (hsegment :
      ∃ δ : ℝ, 0 < δ ∧
        ∀ y1 y2 z1 z2 θ : ℝ,
          |y1 - x1| < δ →
          |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          |z1 - x1| < δ →
          |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          frontierOmega frontierEpsilon y1 y2 →
          frontierOmega frontierEpsilon z1 z2 →
          frontierOmega frontierEpsilon
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) →
          0 < θ → θ < 1 →
            (∀ t ∈ Set.Ioo (0 : ℝ) 1,
              0 < frontierRadius frontierEpsilon
                (z1 + t * (y1 - z1)) (z2 + t * (y2 - z2))) ∨
              (y1 = z1 ∧ y2 = z2)) :
    frontierMajorantLocalConcavityAt x1
      (x1 ^ 2 + frontierEpsilon ^ 2) := by
  have hC :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) := by
    rwa [frontierCPlus_upper_boundary]
  rcases frontierMajorant_rightBranchInterior_piece_neighborhood hC with
    ⟨δB, hδB_pos, hbranch⟩
  rcases hsegment with ⟨δR, hδR_pos, hsegment⟩
  let δ : ℝ := min δB δR
  have hδ_pos : 0 < δ := lt_min hδB_pos hδR_pos
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  by_cases hθ_left : θ = 0
  · subst θ
    simp
  · by_cases hθ_right : θ = 1
    · subst θ
      simp
    · have hθ0' : 0 < θ := lt_of_le_of_ne hθ0 (Ne.symm hθ_left)
      have hθ1' : θ < 1 := lt_of_le_of_ne hθ1 hθ_right
      have hy1B : |y1 - x1| < δB := lt_of_lt_of_le hy1 (min_le_left δB δR)
      have hy2B : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
        lt_of_lt_of_le hy2 (min_le_left δB δR)
      have hz1B : |z1 - x1| < δB := lt_of_lt_of_le hz1 (min_le_left δB δR)
      have hz2B : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
        lt_of_lt_of_le hz2 (min_le_left δB δR)
      rcases hbranch y1 y2 z1 z2 θ hy1B hy2B hz1B hz2B hθ0 hθ1 with
        ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
      have hy1R : |y1 - x1| < δR := lt_of_lt_of_le hy1 (min_le_right δB δR)
      have hy2R : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δR :=
        lt_of_lt_of_le hy2 (min_le_right δB δR)
      have hz1R : |z1 - x1| < δR := lt_of_lt_of_le hz1 (min_le_right δB δR)
      have hz2R : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δR :=
        lt_of_lt_of_le hz2 (min_le_right δB δR)
      have hcase :=
        hsegment y1 y2 z1 z2 θ hy1R hy2R hz1R hz2R
          hyΩ hzΩ hmixΩ hθ0' hθ1'
      have hj :=
        frontierRightTailPiece_jensen_of_rankOne_radius_pos_or_eq hcase hθ0 hθ1
      rw [hmixEq, hyEq, hzEq]
      exact hj

theorem frontierMajorant_upperBoundary_leftBranch_localConcavity_of_leftPiece_jensen
    {x1 : ℝ} (hleft : x1 < frontierCStar)
    (hpiece :
      ∃ δ : ℝ, 0 < δ ∧
        ∀ y1 y2 z1 z2 θ : ℝ,
          |y1 - x1| < δ →
          |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          |z1 - x1| < δ →
          |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          frontierOmega frontierEpsilon y1 y2 →
          frontierOmega frontierEpsilon z1 z2 →
          frontierOmega frontierEpsilon
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) →
          0 ≤ θ → θ ≤ 1 →
            frontierLeftPiece
                (θ * y1 + (1 - θ) * z1)
                (θ * y2 + (1 - θ) * z2) ≥
              θ * frontierLeftPiece y1 y2 +
                (1 - θ) * frontierLeftPiece z1 z2) :
    frontierMajorantLocalConcavityAt x1
      (x1 ^ 2 + frontierEpsilon ^ 2) := by
  have hC :
      frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) < frontierCStar := by
    rwa [frontierCPlus_upper_boundary]
  rcases frontierMajorant_leftBranchInterior_piece_neighborhood hC with
    ⟨δB, hδB_pos, hbranch⟩
  rcases hpiece with ⟨δP, hδP_pos, hpiece⟩
  let δ : ℝ := min δB δP
  have hδ_pos : 0 < δ := lt_min hδB_pos hδP_pos
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  have hy1B : |y1 - x1| < δB := lt_of_lt_of_le hy1 (min_le_left δB δP)
  have hy2B : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
    lt_of_lt_of_le hy2 (min_le_left δB δP)
  have hz1B : |z1 - x1| < δB := lt_of_lt_of_le hz1 (min_le_left δB δP)
  have hz2B : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
    lt_of_lt_of_le hz2 (min_le_left δB δP)
  rcases hbranch y1 y2 z1 z2 θ hy1B hy2B hz1B hz2B hθ0 hθ1 with
    ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
  have hy1P : |y1 - x1| < δP := lt_of_lt_of_le hy1 (min_le_right δB δP)
  have hy2P : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δP :=
    lt_of_lt_of_le hy2 (min_le_right δB δP)
  have hz1P : |z1 - x1| < δP := lt_of_lt_of_le hz1 (min_le_right δB δP)
  have hz2P : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δP :=
    lt_of_lt_of_le hz2 (min_le_right δB δP)
  have hj :=
    hpiece y1 y2 z1 z2 θ hy1P hy2P hz1P hz2P
      hyΩ hzΩ hmixΩ hθ0 hθ1
  rw [hmixEq, hyEq, hzEq]
  exact hj

theorem frontierMajorant_upperBoundary_rightBranch_localConcavity_of_rightPiece_jensen
    {x1 : ℝ} (hright : frontierCStar + 2 * frontierEpsilon < x1)
    (hpiece :
      ∃ δ : ℝ, 0 < δ ∧
        ∀ y1 y2 z1 z2 θ : ℝ,
          |y1 - x1| < δ →
          |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          |z1 - x1| < δ →
          |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          frontierOmega frontierEpsilon y1 y2 →
          frontierOmega frontierEpsilon z1 z2 →
          frontierOmega frontierEpsilon
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) →
          0 ≤ θ → θ ≤ 1 →
            frontierRightTailPiece
                (θ * y1 + (1 - θ) * z1)
                (θ * y2 + (1 - θ) * z2) ≥
              θ * frontierRightTailPiece y1 y2 +
                (1 - θ) * frontierRightTailPiece z1 z2) :
    frontierMajorantLocalConcavityAt x1
      (x1 ^ 2 + frontierEpsilon ^ 2) := by
  have hC :
      frontierCStar + 2 * frontierEpsilon <
        frontierCPlus frontierEpsilon x1
          (x1 ^ 2 + frontierEpsilon ^ 2) := by
    rwa [frontierCPlus_upper_boundary]
  rcases frontierMajorant_rightBranchInterior_piece_neighborhood hC with
    ⟨δB, hδB_pos, hbranch⟩
  rcases hpiece with ⟨δP, hδP_pos, hpiece⟩
  let δ : ℝ := min δB δP
  have hδ_pos : 0 < δ := lt_min hδB_pos hδP_pos
  refine ⟨δ, hδ_pos, ?_⟩
  intro y1 y2 z1 z2 θ hy1 hy2 hz1 hz2 hyΩ hzΩ hmixΩ hθ0 hθ1
  have hy1B : |y1 - x1| < δB := lt_of_lt_of_le hy1 (min_le_left δB δP)
  have hy2B : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
    lt_of_lt_of_le hy2 (min_le_left δB δP)
  have hz1B : |z1 - x1| < δB := lt_of_lt_of_le hz1 (min_le_left δB δP)
  have hz2B : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δB :=
    lt_of_lt_of_le hz2 (min_le_left δB δP)
  rcases hbranch y1 y2 z1 z2 θ hy1B hy2B hz1B hz2B hθ0 hθ1 with
    ⟨_hyD, hyEq, _hzD, hzEq, _hmixD, hmixEq⟩
  have hy1P : |y1 - x1| < δP := lt_of_lt_of_le hy1 (min_le_right δB δP)
  have hy2P : |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δP :=
    lt_of_lt_of_le hy2 (min_le_right δB δP)
  have hz1P : |z1 - x1| < δP := lt_of_lt_of_le hz1 (min_le_right δB δP)
  have hz2P : |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δP :=
    lt_of_lt_of_le hz2 (min_le_right δB δP)
  have hj :=
    hpiece y1 y2 z1 z2 θ hy1P hy2P hz1P hz2P
      hyΩ hzΩ hmixΩ hθ0 hθ1
  rw [hmixEq, hyEq, hzEq]
  exact hj

theorem frontierMajorant_upperBoundary_localConcavity_of_cases
    (hleft :
      ∀ x1 : ℝ, x1 < frontierCStar →
        frontierMajorantLocalConcavityAt x1
          (x1 ^ 2 + frontierEpsilon ^ 2))
    (hleftGlue :
      frontierMajorantLocalConcavityAt frontierCStar
        (frontierCStar ^ 2 + frontierEpsilon ^ 2))
    (hrightGlue :
      frontierMajorantLocalConcavityAt
        (frontierCStar + 2 * frontierEpsilon)
        ((frontierCStar + 2 * frontierEpsilon) ^ 2 +
          frontierEpsilon ^ 2))
    (hright :
      ∀ x1 : ℝ, frontierCStar + 2 * frontierEpsilon < x1 →
        frontierMajorantLocalConcavityAt x1
          (x1 ^ 2 + frontierEpsilon ^ 2)) :
    ∀ x1 : ℝ,
      frontierMajorantLocalConcavityAt x1
        (x1 ^ 2 + frontierEpsilon ^ 2) := by
  intro x1
  by_cases hxleft : x1 < frontierCStar
  · exact hleft x1 hxleft
  · by_cases hxleft_eq : x1 = frontierCStar
    · subst x1
      exact hleftGlue
    · have hxmiddle_left : frontierCStar < x1 := by
        exact lt_of_le_of_ne (le_of_not_gt hxleft) (Ne.symm hxleft_eq)
      by_cases hxmiddle_right : x1 < frontierCStar + 2 * frontierEpsilon
      · exact frontierMajorant_upperBoundary_middleBranch_localConcavity
          hxmiddle_left hxmiddle_right
      · by_cases hxright_eq : x1 = frontierCStar + 2 * frontierEpsilon
        · subst x1
          exact hrightGlue
        · have hxright : frontierCStar + 2 * frontierEpsilon < x1 := by
            exact lt_of_le_of_ne (le_of_not_gt hxmiddle_right)
              (Ne.symm hxright_eq)
          exact hright x1 hxright

theorem frontierMajorant_upperBoundary_localConcavity_of_pieceJensen_and_glue
    (hleftPiece :
      ∀ x1 : ℝ, x1 < frontierCStar →
        ∃ δ : ℝ, 0 < δ ∧
          ∀ y1 y2 z1 z2 θ : ℝ,
            |y1 - x1| < δ →
            |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
            |z1 - x1| < δ →
            |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
            frontierOmega frontierEpsilon y1 y2 →
            frontierOmega frontierEpsilon z1 z2 →
            frontierOmega frontierEpsilon
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) →
            0 ≤ θ → θ ≤ 1 →
              frontierLeftPiece
                  (θ * y1 + (1 - θ) * z1)
                  (θ * y2 + (1 - θ) * z2) ≥
                θ * frontierLeftPiece y1 y2 +
                  (1 - θ) * frontierLeftPiece z1 z2)
    (hleftGlue :
      frontierMajorantLocalConcavityAt frontierCStar
        (frontierCStar ^ 2 + frontierEpsilon ^ 2))
    (hrightGlue :
      frontierMajorantLocalConcavityAt
        (frontierCStar + 2 * frontierEpsilon)
        ((frontierCStar + 2 * frontierEpsilon) ^ 2 +
          frontierEpsilon ^ 2))
    (hrightPiece :
      ∀ x1 : ℝ, frontierCStar + 2 * frontierEpsilon < x1 →
        ∃ δ : ℝ, 0 < δ ∧
          ∀ y1 y2 z1 z2 θ : ℝ,
            |y1 - x1| < δ →
            |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
            |z1 - x1| < δ →
            |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
            frontierOmega frontierEpsilon y1 y2 →
            frontierOmega frontierEpsilon z1 z2 →
            frontierOmega frontierEpsilon
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) →
            0 ≤ θ → θ ≤ 1 →
              frontierRightTailPiece
                  (θ * y1 + (1 - θ) * z1)
                  (θ * y2 + (1 - θ) * z2) ≥
                θ * frontierRightTailPiece y1 y2 +
                  (1 - θ) * frontierRightTailPiece z1 z2) :
    ∀ x1 : ℝ,
      frontierMajorantLocalConcavityAt x1
        (x1 ^ 2 + frontierEpsilon ^ 2) := by
  refine frontierMajorant_upperBoundary_localConcavity_of_cases ?_ hleftGlue
    hrightGlue ?_
  · intro x1 hleft
    exact frontierMajorant_upperBoundary_leftBranch_localConcavity_of_leftPiece_jensen
      hleft (hleftPiece x1 hleft)
  · intro x1 hright
    exact frontierMajorant_upperBoundary_rightBranch_localConcavity_of_rightPiece_jensen
      hright (hrightPiece x1 hright)

theorem frontierBoundaryMajorantResidualBudget_upperBoundaryLocalBellmanSplit_of_pieceJensen_and_glue
    (hleftPiece :
      ∀ x1 : ℝ, x1 < frontierCStar →
        ∃ δ : ℝ, 0 < δ ∧
          ∀ y1 y2 z1 z2 θ : ℝ,
            |y1 - x1| < δ →
            |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
            |z1 - x1| < δ →
            |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
            frontierOmega frontierEpsilon y1 y2 →
            frontierOmega frontierEpsilon z1 z2 →
            frontierOmega frontierEpsilon
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) →
            0 ≤ θ → θ ≤ 1 →
              frontierLeftPiece
                  (θ * y1 + (1 - θ) * z1)
                  (θ * y2 + (1 - θ) * z2) ≥
                θ * frontierLeftPiece y1 y2 +
                  (1 - θ) * frontierLeftPiece z1 z2)
    (hleftGlue :
      frontierMajorantLocalConcavityAt frontierCStar
        (frontierCStar ^ 2 + frontierEpsilon ^ 2))
    (hrightGlue :
      frontierMajorantLocalConcavityAt
        (frontierCStar + 2 * frontierEpsilon)
        ((frontierCStar + 2 * frontierEpsilon) ^ 2 +
          frontierEpsilon ^ 2))
    (hrightPiece :
      ∀ x1 : ℝ, frontierCStar + 2 * frontierEpsilon < x1 →
        ∃ δ : ℝ, 0 < δ ∧
          ∀ y1 y2 z1 z2 θ : ℝ,
            |y1 - x1| < δ →
            |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
            |z1 - x1| < δ →
            |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
            frontierOmega frontierEpsilon y1 y2 →
            frontierOmega frontierEpsilon z1 z2 →
            frontierOmega frontierEpsilon
              (θ * y1 + (1 - θ) * z1)
              (θ * y2 + (1 - θ) * z2) →
            0 ≤ θ → θ ≤ 1 →
              frontierRightTailPiece
                  (θ * y1 + (1 - θ) * z1)
                  (θ * y2 + (1 - θ) * z2) ≥
                θ * frontierRightTailPiece y1 y2 +
                  (1 - θ) * frontierRightTailPiece z1 z2) :
    ∀ x1 : ℝ,
      ∃ δ : ℝ, 0 < δ ∧
        ∀ y1 y2 z1 z2 θ : ℝ,
          |y1 - x1| < δ →
          |y2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          |z1 - x1| < δ →
          |z2 - (x1 ^ 2 + frontierEpsilon ^ 2)| < δ →
          frontierOmega frontierEpsilon y1 y2 →
          frontierOmega frontierEpsilon z1 z2 →
          frontierOmega frontierEpsilon
            (θ * y1 + (1 - θ) * z1)
            (θ * y2 + (1 - θ) * z2) →
          0 ≤ θ → θ ≤ 1 →
            θ * (frontierMajorant y1 y2 - frontierPhi y1) +
                (1 - θ) * (frontierMajorant z1 z2 - frontierPhi z1) ≤
              frontierMajorant
                  (θ * y1 + (1 - θ) * z1)
                  (θ * y2 + (1 - θ) * z2) -
                (θ * frontierPhi y1 + (1 - θ) * frontierPhi z1) := by
  intro x1
  exact
    frontierBoundaryMajorantResidualBudget_localBellmanSplit_of_majorantLocalConcavity
      (frontierMajorant_upperBoundary_localConcavity_of_pieceJensen_and_glue
        hleftPiece hleftGlue hrightGlue hrightPiece x1)

theorem frontierMajorant_locallyConcave_reduction_to_boundary_cases
    (hupperBoundary :
      ∀ x1 : ℝ,
        frontierMajorantLocalConcavityAt x1
          (x1 ^ 2 + frontierEpsilon ^ 2))
    (hleftGlue :
      ∀ {x1 x2 : ℝ}, frontierOmega frontierEpsilon x1 x2 →
        x2 < x1 ^ 2 + frontierEpsilon ^ 2 →
        frontierCPlus frontierEpsilon x1 x2 = frontierCStar →
          frontierMajorantLocalConcavityAt x1 x2)
    (hrightGlue :
      ∀ {x1 x2 : ℝ}, frontierOmega frontierEpsilon x1 x2 →
        x2 < x1 ^ 2 + frontierEpsilon ^ 2 →
        frontierCPlus frontierEpsilon x1 x2 =
          frontierCStar + 2 * frontierEpsilon →
          frontierMajorantLocalConcavityAt x1 x2) :
    frontierMajorantLocallyConcaveOnStrip := by
  intro x1 x2 hxΩ
  by_cases hupper : x2 < x1 ^ 2 + frontierEpsilon ^ 2
  · by_cases hleftBoundary :
      frontierCPlus frontierEpsilon x1 x2 = frontierCStar
    · exact hleftGlue hxΩ hupper hleftBoundary
    · by_cases hrightBoundary :
        frontierCPlus frontierEpsilon x1 x2 =
          frontierCStar + 2 * frontierEpsilon
      · exact hrightGlue hxΩ hupper hrightBoundary
      · exact frontierMajorant_strictUpper_nonBoundary_localConcavity
          hxΩ hupper hleftBoundary hrightBoundary
  · have hx2 : x2 = x1 ^ 2 + frontierEpsilon ^ 2 := by
      linarith [hxΩ.2]
    rw [hx2]
    exact hupperBoundary x1

def frontierMajorantTraceConcavityCertificate : Prop :=
  (∀ C : ℝ, 0 ≤ frontierLeftTraceThird C) ∧
    (∀ C : ℝ, frontierMiddleTraceThird C = 0) ∧
    (∀ C : ℝ, 0 ≤ frontierRightTailTraceThird C) ∧
    frontierMiddleTrace frontierCStar = frontierLeftTrace frontierCStar ∧
    frontierMiddleTraceDeriv frontierCStar =
      frontierLeftTraceDeriv frontierCStar ∧
    frontierMiddleTraceSecond frontierCStar =
      frontierLeftTraceSecond frontierCStar ∧
    frontierMiddleTrace (frontierCStar + 2 * frontierEpsilon) =
      frontierRightTailTrace (frontierCStar + 2 * frontierEpsilon) ∧
    frontierMiddleTraceDeriv (frontierCStar + 2 * frontierEpsilon) =
      frontierRightTailTraceDeriv (frontierCStar + 2 * frontierEpsilon) ∧
    frontierMiddleTraceSecond (frontierCStar + 2 * frontierEpsilon) =
      frontierRightTailTraceSecond (frontierCStar + 2 * frontierEpsilon) ∧
    ∀ third r C u v : ℝ, 0 ≤ third → 0 < r →
      -(third / (4 * r)) * ((2 * C) * u - v) ^ 2 ≤ 0

theorem frontierMajorant_traceConcavityCertificate :
    frontierMajorantTraceConcavityCertificate := by
  refine ⟨frontierLeftTraceThird_nonneg, frontierMiddleTraceThird_eq_zero,
    frontierRightTailTraceThird_nonneg,
    frontierLeft_middle_trace_value_glue,
    frontierLeft_middle_trace_deriv_glue,
    frontierLeft_middle_trace_second_glue,
    frontierMiddle_right_trace_value_glue,
    frontierMiddle_right_trace_deriv_glue,
    frontierMiddle_right_trace_second_glue, ?_⟩
  intro third r C u v hthird hr
  exact frontier_trace_rankOne_quadratic_nonpos hthird hr

theorem frontierCupAlpha_lt_beta :
    frontierCupAlpha < frontierCupBeta := by
  rw [frontierCupAlpha, frontierCupBeta]
  linarith [frontierEpsilon_pos]

theorem frontierCupBeta_sub_alpha :
    frontierCupBeta - frontierCupAlpha = 2 * frontierEpsilon := by
  rw [frontierCupAlpha, frontierCupBeta]
  ring

theorem frontierCupAlpha_le_A :
    frontierCupAlpha ≤ frontierA := by
  exact le_of_lt frontierCStar_sub_epsilon_lt_A

theorem frontierA_le_CupBeta :
    frontierA ≤ frontierCupBeta := by
  rw [frontierCupBeta, frontierCStar]
  nlinarith [frontierEpsilon_pos, frontier_two_epsilon_cubed]

theorem frontierRightReflectedConcavityCondition_def (D : ℝ) :
    frontierRightReflectedConcavityCondition D ↔
      6 * frontierEpsilon ^ 3 ≤ frontierKR * Real.exp (-(D / frontierEpsilon)) := by
  rfl

theorem frontierRightTailStart_beyond_reflected_cutoff :
    frontierRightReflectedCutoff < frontierRightTailStart := by
  rw [frontierRightReflectedCutoff, frontierRightTailStart]
  have hlog : Real.log 2 < (2 : ℝ) := by
    have hlog_one : Real.log 2 < (2 : ℝ) - 1 :=
      Real.log_lt_sub_one_of_pos (by norm_num) (by norm_num)
    linarith
  nlinarith [frontierEpsilon_pos]

theorem frontierRadius_lower_boundary (t : ℝ) :
    frontierRadius frontierEpsilon t (t ^ 2) = frontierEpsilon := by
  rw [frontierRadius]
  have harg : frontierEpsilon ^ 2 + t ^ 2 - t ^ 2 = frontierEpsilon ^ 2 := by
    ring
  rw [harg, Real.sqrt_sq_eq_abs, abs_of_pos frontierEpsilon_pos]

theorem frontierCPlus_lower_boundary (t : ℝ) :
    frontierCPlus frontierEpsilon t (t ^ 2) = t + frontierEpsilon := by
  rw [frontierCPlus, frontierRadius_lower_boundary]

theorem frontierLeftPiece_lower_boundary (t : ℝ) :
    frontierLeftPiece t (t ^ 2) = t ^ 3 := by
  rw [frontierLeftPiece, frontierCPlus_lower_boundary, frontierRadius_lower_boundary]
  field_simp [frontierEpsilon_ne_zero]
  ring

theorem frontierMajorant_left_boundary_eq
    (t : ℝ) (ht : t + frontierEpsilon ≤ frontierCStar) :
    frontierMajorant t (t ^ 2) = t ^ 3 := by
  rw [frontierMajorant, frontierCPlus_lower_boundary]
  rw [if_pos ht, frontierLeftPiece_lower_boundary]

theorem frontierMajorant_left_boundary_eq_phi
    (t : ℝ) (ht : t + frontierEpsilon ≤ frontierCStar) :
    frontierMajorant t (t ^ 2) = frontierPhi t := by
  rw [frontierMajorant_left_boundary_eq t ht]
  have htA : t ≤ frontierA := by
    linarith [ht, frontierCStar_sub_epsilon_lt_A]
  rw [frontierPhi]
  have hnonpos : t - frontierA ≤ 0 := by linarith
  rw [max_eq_right hnonpos]
  ring

theorem frontierRightTailTrace_boundary_sub (t : ℝ) :
    frontierRightTailTrace (t + frontierEpsilon) -
        frontierEpsilon * frontierRightTailTraceDeriv (t + frontierEpsilon) =
      t ^ 3 + 2 * (t - frontierA) := by
  rw [frontierRightTailTrace, frontierRightTailTraceDeriv]
  ring

theorem frontierPhi_right_of_ge (t : ℝ) (ht : frontierA ≤ t) :
    frontierPhi t = t ^ 3 + 2 * (t - frontierA) := by
  rw [frontierPhi]
  have hnonneg : 0 ≤ t - frontierA := by linarith
  rw [max_eq_left hnonneg]

theorem frontierPhi_left_of_le (t : ℝ) (ht : t ≤ frontierA) :
    frontierPhi t = t ^ 3 := by
  rw [frontierPhi]
  have hnonpos : t - frontierA ≤ 0 := by linarith
  rw [max_eq_right hnonpos]
  ring

theorem frontierPhi_abs_le_cubic_linear (t : ℝ) :
    |frontierPhi t| ≤ |t| ^ 3 + 2 * |t| := by
  by_cases htA : frontierA ≤ t
  · rw [frontierPhi_right_of_ge t htA]
    have ht_nonneg : 0 ≤ t := by
      rw [frontierA] at htA
      linarith
    have htail_nonneg : 0 ≤ 2 * (t - frontierA) := by
      exact mul_nonneg (by norm_num) (sub_nonneg.mpr htA)
    have hphi_nonneg : 0 ≤ t ^ 3 + 2 * (t - frontierA) := by
      exact add_nonneg (pow_nonneg ht_nonneg 3) htail_nonneg
    rw [abs_of_nonneg hphi_nonneg, abs_of_nonneg ht_nonneg]
    rw [frontierA]
    linarith
  · have htA' : t ≤ frontierA := le_of_not_ge htA
    rw [frontierPhi_left_of_le t htA']
    rw [abs_pow]
    have hnonneg : 0 ≤ 2 * |t| := by positivity
    linarith

theorem frontierPhi_le_cubic_linear (t : ℝ) :
    frontierPhi t ≤ |t| ^ 3 + 2 * |t| := by
  exact le_trans (le_abs_self (frontierPhi t)) (frontierPhi_abs_le_cubic_linear t)

theorem frontierMajorant_left_boundary_dominates
    (t : ℝ) (ht : t + frontierEpsilon ≤ frontierCStar) :
    frontierPhi t ≤ frontierMajorant t (t ^ 2) := by
  rw [frontierMajorant_left_boundary_eq t ht]
  have htA : t ≤ frontierA := by
    linarith [ht, frontierCStar_sub_epsilon_lt_A]
  rw [frontierPhi_left_of_le t htA]

theorem frontierCupPiece_lower_boundary_left_residual
    (t : ℝ) (htA : t ≤ frontierA) :
    frontierCupPiece t (t ^ 2) - frontierPhi t =
      (t - frontierCupAlpha) *
        (72 * frontierA * frontierEpsilon -
          36 * frontierA * (t - frontierCupAlpha) +
          30 * frontierEpsilon * (t - frontierCupAlpha) -
          12 * (t - frontierCupAlpha) ^ 2 + 13) / 12 := by
  rw [frontierPhi_left_of_le t htA]
  rw [frontierCupPiece]
  rw [frontierPhi_left_of_le frontierCupAlpha frontierCupAlpha_le_A,
    frontierPhi_right_of_ge frontierCupBeta frontierA_le_CupBeta]
  rw [frontierCupAlpha, frontierCupBeta, frontierCStar, frontierA]
  rw [frontier_two_epsilon_cubed]
  field_simp [frontierEpsilon_ne_zero]
  ring_nf
  rw [frontierEpsilon_cube, frontierEpsilon_fourth, frontierEpsilon_sq]
  ring

theorem frontierCupPiece_lower_boundary_right_residual
    (t : ℝ) (htA : frontierA ≤ t) :
    frontierCupPiece t (t ^ 2) - frontierPhi t =
      (frontierCupBeta - t) *
        (72 * frontierA * frontierEpsilon -
          36 * frontierA * (frontierCupBeta - t) -
          42 * frontierEpsilon * (frontierCupBeta - t) +
          12 * (frontierCupBeta - t) ^ 2 + 13) / 12 := by
  rw [frontierPhi_right_of_ge t htA]
  rw [frontierCupPiece]
  rw [frontierPhi_left_of_le frontierCupAlpha frontierCupAlpha_le_A,
    frontierPhi_right_of_ge frontierCupBeta frontierA_le_CupBeta]
  rw [frontierCupAlpha, frontierCupBeta, frontierCStar, frontierA]
  rw [frontier_two_epsilon_cubed]
  field_simp [frontierEpsilon_ne_zero]
  ring_nf
  rw [frontierEpsilon_cube, frontierEpsilon_fourth, frontierEpsilon_sq]
  ring

theorem frontierCupPiece_lower_boundary_dominates
    (t : ℝ) (hα : frontierCupAlpha ≤ t) (hβ : t ≤ frontierCupBeta) :
    frontierPhi t ≤ frontierCupPiece t (t ^ 2) := by
  by_cases htA : t ≤ frontierA
  · have hu_nonneg : 0 ≤ t - frontierCupAlpha := by linarith
    have hu_le_eps : t - frontierCupAlpha ≤ frontierEpsilon := by
      rw [frontierCupAlpha, frontierCStar]
      have htwo_nonneg : 0 ≤ 2 * frontierEpsilon ^ 3 := by
        rw [frontier_two_epsilon_cubed]
        linarith [frontierEpsilon_pos]
      nlinarith [htA, htwo_nonneg]
    have hneg_le_u : -frontierEpsilon ≤ t - frontierCupAlpha := by
      linarith [hu_nonneg, frontierEpsilon_pos]
    have hu_sq_le : (t - frontierCupAlpha) ^ 2 ≤ frontierEpsilon ^ 2 :=
      sq_le_sq' hneg_le_u hu_le_eps
    have heu_nonneg : 0 ≤ frontierEpsilon * (t - frontierCupAlpha) := by
      exact mul_nonneg (le_of_lt frontierEpsilon_pos) hu_nonneg
    have hbracket :
        0 ≤ 72 * frontierA * frontierEpsilon -
          36 * frontierA * (t - frontierCupAlpha) +
          30 * frontierEpsilon * (t - frontierCupAlpha) -
          12 * (t - frontierCupAlpha) ^ 2 + 13 := by
      rw [frontierA]
      nlinarith [frontierEpsilon_pos, frontierEpsilon_sq, hu_le_eps,
        hu_sq_le, heu_nonneg]
    have hres_nonneg :
        0 ≤ frontierCupPiece t (t ^ 2) - frontierPhi t := by
      rw [frontierCupPiece_lower_boundary_left_residual t htA]
      positivity
    linarith
  · have htA' : frontierA ≤ t := le_of_not_ge htA
    have hw_nonneg : 0 ≤ frontierCupBeta - t := by linarith
    have hw_le : frontierCupBeta - t ≤ 7 * frontierEpsilon / 6 := by
      rw [frontierCupBeta, frontierCStar]
      nlinarith [htA', frontier_two_epsilon_cubed]
    have hew_le :
        frontierEpsilon * (frontierCupBeta - t) ≤
          frontierEpsilon * (7 * frontierEpsilon / 6) :=
      mul_le_mul_of_nonneg_left hw_le (le_of_lt frontierEpsilon_pos)
    have hbracket :
        0 ≤ 72 * frontierA * frontierEpsilon -
          36 * frontierA * (frontierCupBeta - t) -
          42 * frontierEpsilon * (frontierCupBeta - t) +
          12 * (frontierCupBeta - t) ^ 2 + 13 := by
      rw [frontierA]
      nlinarith [frontierEpsilon_pos, frontierEpsilon_sq, hw_nonneg, hw_le, hew_le]
    have hres_nonneg :
        0 ≤ frontierCupPiece t (t ^ 2) - frontierPhi t := by
      rw [frontierCupPiece_lower_boundary_right_residual t htA']
      positivity
    linarith

theorem frontierMiddlePiece_lower_boundary_left_residual
    (t : ℝ) (htA : t ≤ frontierA) :
    frontierMiddlePiece t (t ^ 2) - frontierPhi t =
      (t + frontierEpsilon - frontierCStar) ^ 2 *
        (9 * frontierEpsilon - (t + frontierEpsilon - frontierCStar)) := by
  rw [frontierPhi_left_of_le t htA]
  rw [frontierMiddlePiece, frontierCPlus_lower_boundary,
    frontierRadius_lower_boundary, frontierMiddleTrace, frontierMiddleTraceDeriv,
    frontierLeftTrace, frontierLeftTraceDeriv,
    frontierKL_mul_exp_CStar_div,
    frontierKL_div_epsilon_mul_exp_CStar_div]
  rw [frontierCStar, frontierA]
  ring_nf
  rw [frontierEpsilon_ninth, frontierEpsilon_seventh, frontierEpsilon_sixth,
    frontierEpsilon_fifth, frontierEpsilon_fourth, frontierEpsilon_cube,
    frontierEpsilon_sq]
  ring

theorem frontierMiddlePiece_lower_boundary_right_residual
    (t : ℝ) (htA : frontierA ≤ t) :
    frontierMiddlePiece t (t ^ 2) - frontierPhi t =
      (2 * frontierEpsilon - (t + frontierEpsilon - frontierCStar)) *
        ((t + frontierEpsilon - frontierCStar) ^ 2 -
          7 * frontierEpsilon * (t + frontierEpsilon - frontierCStar) +
          (5 / 6 : ℝ)) := by
  rw [frontierPhi_right_of_ge t htA]
  rw [frontierMiddlePiece, frontierCPlus_lower_boundary,
    frontierRadius_lower_boundary, frontierMiddleTrace, frontierMiddleTraceDeriv,
    frontierLeftTrace, frontierLeftTraceDeriv,
    frontierKL_mul_exp_CStar_div,
    frontierKL_div_epsilon_mul_exp_CStar_div]
  rw [frontierCStar, frontierA]
  ring_nf
  rw [frontierEpsilon_ninth, frontierEpsilon_seventh, frontierEpsilon_sixth,
    frontierEpsilon_fifth, frontierEpsilon_fourth, frontierEpsilon_cube,
    frontierEpsilon_sq]
  ring

theorem frontierMiddlePiece_lower_boundary_left_residual_nonneg
    (t : ℝ) (hleft : frontierCStar < t + frontierEpsilon)
    (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon)
    (htA : t ≤ frontierA) :
    0 ≤ frontierMiddlePiece t (t ^ 2) - frontierPhi t := by
  set u : ℝ := t + frontierEpsilon - frontierCStar
  have hu_nonneg : 0 ≤ u := by
    dsimp [u]
    linarith
  have hu_le : u ≤ 2 * frontierEpsilon := by
    dsimp [u]
    linarith
  have hfactor : 0 ≤ 9 * frontierEpsilon - u := by
    linarith [hu_le, frontierEpsilon_pos]
  rw [frontierMiddlePiece_lower_boundary_left_residual t htA]
  rw [← show u = t + frontierEpsilon - frontierCStar by rfl]
  exact mul_nonneg (sq_nonneg u) hfactor

theorem frontierMiddlePiece_lower_boundary_right_residual_nonneg
    (t : ℝ) (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon)
    (htA : frontierA ≤ t) :
    0 ≤ frontierMiddlePiece t (t ^ 2) - frontierPhi t := by
  set u : ℝ := t + frontierEpsilon - frontierCStar
  have hu_le : u ≤ 2 * frontierEpsilon := by
    dsimp [u]
    linarith
  have htwo_nonneg : 0 ≤ 2 * frontierEpsilon - u := by
    linarith
  have hq_nonneg :
      0 ≤ u ^ 2 - 7 * frontierEpsilon * u + (5 / 6 : ℝ) := by
    have hq_ge :
        (2 * frontierEpsilon) ^ 2 -
            7 * frontierEpsilon * (2 * frontierEpsilon) + (5 / 6 : ℝ) ≤
          u ^ 2 - 7 * frontierEpsilon * u + (5 / 6 : ℝ) := by
      have hslope_nonpos : u + 2 * frontierEpsilon - 7 * frontierEpsilon ≤ 0 := by
        linarith [hu_le, frontierEpsilon_pos]
      have hdiff_nonneg : 0 ≤ 2 * frontierEpsilon - u := by
        linarith
      nlinarith [mul_nonpos_of_nonneg_of_nonpos hdiff_nonneg hslope_nonpos]
    have hq_at_right :
        (2 * frontierEpsilon) ^ 2 -
            7 * frontierEpsilon * (2 * frontierEpsilon) + (5 / 6 : ℝ) = 0 := by
      ring_nf
      rw [frontierEpsilon_sq]
      norm_num
    linarith
  rw [frontierMiddlePiece_lower_boundary_right_residual t htA]
  rw [← show u = t + frontierEpsilon - frontierCStar by rfl]
  exact mul_nonneg htwo_nonneg hq_nonneg

theorem frontierMiddlePiece_lower_boundary_dominates
    (t : ℝ) (hleft : frontierCStar < t + frontierEpsilon)
    (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon) :
    frontierPhi t ≤ frontierMiddlePiece t (t ^ 2) := by
  by_cases htA : t ≤ frontierA
  · have hres_nonneg :
        0 ≤ frontierMiddlePiece t (t ^ 2) - frontierPhi t :=
      frontierMiddlePiece_lower_boundary_left_residual_nonneg t hleft hright htA
    linarith
  · have htA' : frontierA ≤ t := le_of_not_ge htA
    have hres_nonneg :
        0 ≤ frontierMiddlePiece t (t ^ 2) - frontierPhi t :=
      frontierMiddlePiece_lower_boundary_right_residual_nonneg t hright htA'
    linarith

theorem frontierMiddlePiece_lower_boundary_residual_certificate
    (t : ℝ) (hleft : frontierCStar < t + frontierEpsilon)
    (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon) :
    (t ≤ frontierA →
        frontierMiddlePiece t (t ^ 2) - frontierPhi t =
          (t + frontierEpsilon - frontierCStar) ^ 2 *
            (9 * frontierEpsilon - (t + frontierEpsilon - frontierCStar))) ∧
      (frontierA ≤ t →
        frontierMiddlePiece t (t ^ 2) - frontierPhi t =
          (2 * frontierEpsilon - (t + frontierEpsilon - frontierCStar)) *
            ((t + frontierEpsilon - frontierCStar) ^ 2 -
              7 * frontierEpsilon * (t + frontierEpsilon - frontierCStar) +
              (5 / 6 : ℝ))) ∧
      0 ≤ frontierMiddlePiece t (t ^ 2) - frontierPhi t := by
  refine ⟨frontierMiddlePiece_lower_boundary_left_residual t,
    frontierMiddlePiece_lower_boundary_right_residual t, ?_⟩
  have hdom := frontierMiddlePiece_lower_boundary_dominates t hleft hright
  linarith

theorem frontierMajorant_middle_boundary_eq
    (t : ℝ) (hleft : frontierCStar < t + frontierEpsilon)
    (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon) :
    frontierMajorant t (t ^ 2) = frontierMiddlePiece t (t ^ 2) := by
  rw [frontierMajorant, frontierCPlus_lower_boundary]
  have hnotLeft : ¬ t + frontierEpsilon ≤ frontierCStar := not_le.mpr hleft
  rw [if_neg hnotLeft, if_pos hright]

theorem frontierMajorant_middle_boundary_dominates
    (t : ℝ) (hleft : frontierCStar < t + frontierEpsilon)
    (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon) :
    frontierPhi t ≤ frontierMajorant t (t ^ 2) := by
  rw [frontierMajorant_middle_boundary_eq t hleft hright]
  exact frontierMiddlePiece_lower_boundary_dominates t hleft hright

theorem frontierMajorant_middle_boundary_residual_certificate
    (t : ℝ) (hleft : frontierCStar < t + frontierEpsilon)
    (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon) :
    (t ≤ frontierA →
        frontierMajorant t (t ^ 2) - frontierPhi t =
          (t + frontierEpsilon - frontierCStar) ^ 2 *
            (9 * frontierEpsilon - (t + frontierEpsilon - frontierCStar))) ∧
      (frontierA ≤ t →
        frontierMajorant t (t ^ 2) - frontierPhi t =
          (2 * frontierEpsilon - (t + frontierEpsilon - frontierCStar)) *
            ((t + frontierEpsilon - frontierCStar) ^ 2 -
              7 * frontierEpsilon * (t + frontierEpsilon - frontierCStar) +
              (5 / 6 : ℝ))) ∧
      0 ≤ frontierMajorant t (t ^ 2) - frontierPhi t := by
  rw [frontierMajorant_middle_boundary_eq t hleft hright]
  exact frontierMiddlePiece_lower_boundary_residual_certificate t hleft hright

theorem frontierMajorant_middle_boundary_residual_certificate_u
    (t u : ℝ) (hu : u = t + frontierEpsilon - frontierCStar)
    (hleft : frontierCStar < t + frontierEpsilon)
    (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon) :
    (t ≤ frontierA →
        frontierMajorant t (t ^ 2) - frontierPhi t =
          u ^ 2 * (9 * frontierEpsilon - u)) ∧
      (frontierA ≤ t →
        frontierMajorant t (t ^ 2) - frontierPhi t =
          (2 * frontierEpsilon - u) *
            (u ^ 2 - 7 * frontierEpsilon * u + (5 / 6 : ℝ))) ∧
      0 ≤ frontierMajorant t (t ^ 2) - frontierPhi t := by
  rcases frontierMajorant_middle_boundary_residual_certificate t hleft hright with
    ⟨hleft_res, hright_res, hnonneg⟩
  refine ⟨?_, ?_, hnonneg⟩
  · intro htA
    rw [hleft_res htA, hu]
  · intro htA
    rw [hright_res htA, hu]

theorem frontierRightTailPiece_boundary (t : ℝ) (ht : frontierA ≤ t) :
    frontierRightTailPiece t (t ^ 2) = frontierPhi t := by
  rw [frontierRightTailPiece, frontierCPlus_lower_boundary,
    frontierRadius_lower_boundary, frontierRightTailTrace_boundary_sub,
    frontierPhi_right_of_ge t ht]

theorem frontierPhi_continuous : Continuous frontierPhi := by
  unfold frontierPhi
  fun_prop

theorem frontierLeftPiece_lower_boundary_continuous :
    Continuous (fun t : ℝ ↦ frontierLeftPiece t (t ^ 2)) := by
  unfold frontierLeftPiece frontierCPlus frontierRadius
  fun_prop

theorem frontierMiddlePiece_lower_boundary_continuous :
    Continuous (fun t : ℝ ↦ frontierMiddlePiece t (t ^ 2)) := by
  unfold frontierMiddlePiece frontierCPlus frontierRadius frontierMiddleTrace
    frontierMiddleTraceDeriv frontierLeftTrace frontierLeftTraceDeriv
  fun_prop

theorem frontierRightTailPiece_lower_boundary_continuous :
    Continuous (fun t : ℝ ↦ frontierRightTailPiece t (t ^ 2)) := by
  unfold frontierRightTailPiece frontierCPlus frontierRadius
    frontierRightTailTrace frontierRightTailTraceDeriv
  fun_prop

theorem frontierLeftPiece_eq_middlePiece_lower_boundary_glue
    (t : ℝ) (ht : t + frontierEpsilon = frontierCStar) :
    frontierLeftPiece t (t ^ 2) = frontierMiddlePiece t (t ^ 2) := by
  have htA : t ≤ frontierA := by
    linarith [frontierCStar_sub_epsilon_lt_A, ht]
  have hleft : frontierLeftPiece t (t ^ 2) = frontierPhi t := by
    rw [frontierLeftPiece_lower_boundary, frontierPhi_left_of_le t htA]
  have hmiddle_gap :
      frontierMiddlePiece t (t ^ 2) - frontierPhi t = 0 := by
    rw [frontierMiddlePiece_lower_boundary_left_residual t htA]
    have hu : t + frontierEpsilon - frontierCStar = 0 := by
      linarith
    rw [hu]
    ring
  linarith

theorem frontierMiddlePiece_eq_rightTailPiece_lower_boundary_glue
    (t : ℝ) (ht : t + frontierEpsilon = frontierCStar + 2 * frontierEpsilon) :
    frontierMiddlePiece t (t ^ 2) = frontierRightTailPiece t (t ^ 2) := by
  have htA : frontierA ≤ t := by
    have hAβ := frontierA_le_CupBeta
    rw [frontierCupBeta] at hAβ
    linarith [hAβ, ht]
  have hright : frontierRightTailPiece t (t ^ 2) = frontierPhi t :=
    frontierRightTailPiece_boundary t htA
  have hmiddle_gap :
      frontierMiddlePiece t (t ^ 2) - frontierPhi t = 0 := by
    rw [frontierMiddlePiece_lower_boundary_right_residual t htA]
    have hu : t + frontierEpsilon - frontierCStar = 2 * frontierEpsilon := by
      linarith
    rw [hu]
    ring_nf
  linarith

theorem frontierMajorant_lower_boundary_continuous :
    Continuous (fun t : ℝ ↦ frontierMajorant t (t ^ 2)) := by
  unfold frontierMajorant
  have hCfun :
      Continuous (fun t : ℝ ↦ frontierCPlus frontierEpsilon t (t ^ 2)) := by
    have hpair : Continuous (fun t : ℝ ↦ (t, t ^ 2)) := by
      continuity
    simpa [Function.comp_def] using
      (frontierCPlus_continuous frontierEpsilon).comp hpair
  apply Continuous.if
  · intro t ht
    have hCeq : frontierCPlus frontierEpsilon t (t ^ 2) = frontierCStar :=
      frontier_le_subset_eq hCfun continuous_const ht
    have hteq : t + frontierEpsilon = frontierCStar := by
      rwa [frontierCPlus_lower_boundary] at hCeq
    rw [if_pos]
    · exact frontierLeftPiece_eq_middlePiece_lower_boundary_glue t hteq
    · rw [frontierCPlus_lower_boundary]
      linarith [frontierEpsilon_pos]
  · exact frontierLeftPiece_lower_boundary_continuous
  · apply Continuous.if
    · intro t ht
      have hCeq :
          frontierCPlus frontierEpsilon t (t ^ 2) =
            frontierCStar + 2 * frontierEpsilon :=
        frontier_le_subset_eq hCfun continuous_const ht
      have hteq :
          t + frontierEpsilon = frontierCStar + 2 * frontierEpsilon := by
        rwa [frontierCPlus_lower_boundary] at hCeq
      exact frontierMiddlePiece_eq_rightTailPiece_lower_boundary_glue t hteq
    · exact frontierMiddlePiece_lower_boundary_continuous
    · exact frontierRightTailPiece_lower_boundary_continuous

theorem frontierMajorant_boundary_gap_continuous :
    Continuous
      (fun t : ℝ ↦ frontierMajorant t (t ^ 2) - frontierPhi t) :=
  frontierMajorant_lower_boundary_continuous.sub frontierPhi_continuous

theorem frontierMajorant_right_boundary_eq
    (t : ℝ) (htC : frontierCStar + 2 * frontierEpsilon < t + frontierEpsilon)
    (htA : frontierA ≤ t) :
    frontierMajorant t (t ^ 2) = frontierPhi t := by
  rw [frontierMajorant, frontierCPlus_lower_boundary]
  have hnotLeft : ¬ t + frontierEpsilon ≤ frontierCStar := by
    linarith [frontierEpsilon_pos]
  have hnotMiddle :
      ¬ t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon := by
    exact not_le.mpr htC
  rw [if_neg hnotLeft, if_neg hnotMiddle, frontierRightTailPiece_boundary t htA]

theorem frontierMajorant_right_boundary_eq_phi
    (t : ℝ) (htC : frontierCStar + 2 * frontierEpsilon < t + frontierEpsilon) :
    frontierMajorant t (t ^ 2) = frontierPhi t := by
  have htA : frontierA ≤ t := by
    have hAβ := frontierA_le_CupBeta
    rw [frontierCupBeta] at hAβ
    linarith [hAβ, htC]
  exact frontierMajorant_right_boundary_eq t htC htA

theorem frontierMajorant_right_boundary_dominates
    (t : ℝ) (htC : frontierCStar + 2 * frontierEpsilon < t + frontierEpsilon)
    (htA : frontierA ≤ t) :
    frontierPhi t ≤ frontierMajorant t (t ^ 2) := by
  rw [frontierMajorant_right_boundary_eq t htC htA]

theorem frontierMajorant_boundary_eq_phi_or_middle
    (t : ℝ) :
    frontierMajorant t (t ^ 2) = frontierPhi t ∨
      (frontierCStar < t + frontierEpsilon ∧
        t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon ∧
        frontierMajorant t (t ^ 2) = frontierMiddlePiece t (t ^ 2)) := by
  by_cases hleft : t + frontierEpsilon ≤ frontierCStar
  · exact Or.inl (frontierMajorant_left_boundary_eq_phi t hleft)
  · have hleft' : frontierCStar < t + frontierEpsilon := not_le.mp hleft
    by_cases hmiddle : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon
    · exact Or.inr
        ⟨hleft', hmiddle, frontierMajorant_middle_boundary_eq t hleft' hmiddle⟩
    · exact Or.inl
        (frontierMajorant_right_boundary_eq_phi t (not_le.mp hmiddle))

theorem frontierMajorant_boundary_eq_phi_of_not_middle
    (t : ℝ)
    (hnotMiddle :
      ¬ (frontierCStar < t + frontierEpsilon ∧
        t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon)) :
    frontierMajorant t (t ^ 2) = frontierPhi t := by
  rcases frontierMajorant_boundary_eq_phi_or_middle t with hphi | hmiddle
  · exact hphi
  · exact False.elim (hnotMiddle ⟨hmiddle.1, hmiddle.2.1⟩)

theorem frontierMajorant_boundary_middle_t_bounds
    (t : ℝ)
    (hleft : frontierCStar < t + frontierEpsilon)
    (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon) :
    frontierCStar - frontierEpsilon < t ∧
      t ≤ frontierCStar + frontierEpsilon := by
  constructor <;> linarith

theorem frontierMajorant_boundary_middle_t_bounds_A
    (t : ℝ)
    (hleft : frontierCStar < t + frontierEpsilon)
    (hright : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon) :
    frontierA - 1 < t ∧ t ≤ frontierA + 1 := by
  rcases frontierMajorant_boundary_middle_t_bounds t hleft hright with
    ⟨ht_lower, ht_upper⟩
  constructor
  · unfold frontierCStar frontierA at ht_lower
    unfold frontierA
    nlinarith [frontierEpsilon_pos, frontierEpsilon_sq, frontierEpsilon_lt_one]
  · unfold frontierCStar frontierA at ht_upper
    unfold frontierA
    nlinarith [frontierEpsilon_pos, frontierEpsilon_sq, frontierEpsilon_lt_one]

theorem frontierMajorant_boundary_eq_phi_of_left_or_right
    (t : ℝ)
    (h :
      t + frontierEpsilon ≤ frontierCStar ∨
        frontierCStar + 2 * frontierEpsilon < t + frontierEpsilon) :
    frontierMajorant t (t ^ 2) = frontierPhi t := by
  rcases h with hleft | hright
  · exact frontierMajorant_left_boundary_eq_phi t hleft
  · exact frontierMajorant_right_boundary_eq_phi t hright

theorem frontierMajorant_boundaryDominates (t : ℝ) :
    frontierPhi t ≤ frontierMajorant t (t ^ 2) := by
  by_cases hleft : t + frontierEpsilon ≤ frontierCStar
  · exact frontierMajorant_left_boundary_dominates t hleft
  · have hleft' : frontierCStar < t + frontierEpsilon := not_le.mp hleft
    by_cases hmiddle : t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon
    · exact frontierMajorant_middle_boundary_dominates t hleft' hmiddle
    · have hright : frontierCStar + 2 * frontierEpsilon < t + frontierEpsilon :=
        not_le.mp hmiddle
      have htA : frontierA ≤ t := by
        have hAβ := frontierA_le_CupBeta
        rw [frontierCupBeta] at hAβ
        linarith [hAβ, hright]
      exact frontierMajorant_right_boundary_dominates t hright htA

theorem frontierOmega_lower_boundary (t : ℝ) :
    frontierOmega frontierEpsilon t (t ^ 2) := by
  rw [frontierOmega]
  constructor
  · rfl
  · nlinarith [sq_nonneg frontierEpsilon]

theorem frontierMajorant_boundary_gap_nonneg (t : ℝ) :
    0 ≤ frontierMajorant t (t ^ 2) - frontierPhi t := by
  have hdom := frontierMajorant_boundaryDominates t
  linarith

theorem frontierMajorant_boundary_gap_eq_zero_or_middle_nonneg
    (t : ℝ) :
    frontierMajorant t (t ^ 2) - frontierPhi t = 0 ∨
      (frontierCStar < t + frontierEpsilon ∧
        t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon ∧
        0 ≤ frontierMajorant t (t ^ 2) - frontierPhi t) := by
  rcases frontierMajorant_boundary_eq_phi_or_middle t with hphi | hmiddle
  · left
    rw [hphi]
    ring
  · right
    exact ⟨hmiddle.1, hmiddle.2.1, frontierMajorant_boundary_gap_nonneg t⟩

theorem frontierMajorant_boundary_gap_eq_zero_of_not_middle
    (t : ℝ)
    (hnotMiddle :
      ¬ (frontierCStar < t + frontierEpsilon ∧
        t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon)) :
    frontierMajorant t (t ^ 2) - frontierPhi t = 0 := by
  rw [frontierMajorant_boundary_eq_phi_of_not_middle t hnotMiddle]
  ring

theorem frontierMajorant_boundary_gap_nonzero_middle
    (t : ℝ)
    (hgap : frontierMajorant t (t ^ 2) - frontierPhi t ≠ 0) :
    frontierCStar < t + frontierEpsilon ∧
      t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon := by
  by_contra hnot
  exact hgap (frontierMajorant_boundary_gap_eq_zero_of_not_middle t hnot)

theorem frontierMajorant_boundary_gap_nonzero_t_bounds
    (t : ℝ)
    (hgap : frontierMajorant t (t ^ 2) - frontierPhi t ≠ 0) :
    frontierCStar - frontierEpsilon < t ∧
      t ≤ frontierCStar + frontierEpsilon := by
  rcases frontierMajorant_boundary_gap_nonzero_middle t hgap with
    ⟨hleft, hright⟩
  exact frontierMajorant_boundary_middle_t_bounds t hleft hright

theorem frontierMajorant_boundary_gap_nonzero_t_bounds_A
    (t : ℝ)
    (hgap : frontierMajorant t (t ^ 2) - frontierPhi t ≠ 0) :
    frontierA - 1 < t ∧ t ≤ frontierA + 1 := by
  rcases frontierMajorant_boundary_gap_nonzero_middle t hgap with
    ⟨hleft, hright⟩
  exact frontierMajorant_boundary_middle_t_bounds_A t hleft hright

theorem frontierMajorant_boundary_gap_eq_zero_of_le_A_sub_one
    (t : ℝ) (ht : t ≤ frontierA - 1) :
    frontierMajorant t (t ^ 2) - frontierPhi t = 0 := by
  apply frontierMajorant_boundary_gap_eq_zero_of_not_middle
  intro hmiddle
  rcases hmiddle with ⟨hleft, hright⟩
  rcases frontierMajorant_boundary_middle_t_bounds_A t hleft hright with
    ⟨ht_lower, _ht_upper⟩
  linarith

theorem frontierMajorant_boundary_gap_eq_zero_of_le_CStar_sub_epsilon
    (t : ℝ) (ht : t ≤ frontierCStar - frontierEpsilon) :
    frontierMajorant t (t ^ 2) - frontierPhi t = 0 := by
  apply frontierMajorant_boundary_gap_eq_zero_of_not_middle
  intro hmiddle
  rcases hmiddle with ⟨hleft, hright⟩
  rcases frontierMajorant_boundary_middle_t_bounds t hleft hright with
    ⟨ht_lower, _ht_upper⟩
  linarith

theorem frontierMajorant_boundary_gap_eq_zero_of_A_add_one_lt
    (t : ℝ) (ht : frontierA + 1 < t) :
    frontierMajorant t (t ^ 2) - frontierPhi t = 0 := by
  apply frontierMajorant_boundary_gap_eq_zero_of_not_middle
  intro hmiddle
  rcases hmiddle with ⟨hleft, hright⟩
  rcases frontierMajorant_boundary_middle_t_bounds_A t hleft hright with
    ⟨_ht_lower, ht_upper⟩
  linarith

theorem frontierMajorant_boundary_gap_eq_zero_of_CStar_add_epsilon_lt
    (t : ℝ) (ht : frontierCStar + frontierEpsilon < t) :
    frontierMajorant t (t ^ 2) - frontierPhi t = 0 := by
  apply frontierMajorant_boundary_gap_eq_zero_of_not_middle
  intro hmiddle
  rcases hmiddle with ⟨hleft, hright⟩
  rcases frontierMajorant_boundary_middle_t_bounds t hleft hright with
    ⟨_ht_lower, ht_upper⟩
  linarith

theorem frontierMajorant_boundary_gap_le_const (t : ℝ) :
    frontierMajorant t (t ^ 2) - frontierPhi t ≤ 100 := by
  rcases frontierMajorant_boundary_eq_phi_or_middle t with hphi | hmiddle
  · rw [hphi]
    norm_num
  · rcases hmiddle with ⟨hleft, hright, hmajorant⟩
    set u : ℝ := t + frontierEpsilon - frontierCStar
    have hu_eq : u = t + frontierEpsilon - frontierCStar := rfl
    have hu_nonneg : 0 ≤ u := by
      dsimp [u]
      linarith
    have hu_le : u ≤ 2 * frontierEpsilon := by
      dsimp [u]
      linarith
    have hcert :=
      frontierMajorant_middle_boundary_residual_certificate_u
        t u hu_eq hleft hright
    by_cases htA : t ≤ frontierA
    · rw [hcert.1 htA]
      have hfactor_nonneg : 0 ≤ 9 * frontierEpsilon - u := by
        linarith [hu_le, frontierEpsilon_pos]
      nlinarith [frontierEpsilon_pos, frontierEpsilon_lt_one,
        hu_nonneg, hu_le, hfactor_nonneg]
    · have htA' : frontierA ≤ t := le_of_not_ge htA
      rw [hcert.2.1 htA']
      have hfactor_nonneg : 0 ≤ 2 * frontierEpsilon - u := by
        linarith
      have hq_nonneg :
          0 ≤ u ^ 2 - 7 * frontierEpsilon * u + (5 / 6 : ℝ) := by
        have hq_ge :
            (2 * frontierEpsilon) ^ 2 -
                7 * frontierEpsilon * (2 * frontierEpsilon) + (5 / 6 : ℝ) ≤
              u ^ 2 - 7 * frontierEpsilon * u + (5 / 6 : ℝ) := by
          have hslope_nonpos :
              u + 2 * frontierEpsilon - 7 * frontierEpsilon ≤ 0 := by
            linarith [hu_le, frontierEpsilon_pos]
          have hdiff_nonneg : 0 ≤ 2 * frontierEpsilon - u := by
            linarith
          nlinarith [mul_nonpos_of_nonneg_of_nonpos hdiff_nonneg
            hslope_nonpos]
        have hq_at_right :
            (2 * frontierEpsilon) ^ 2 -
                7 * frontierEpsilon * (2 * frontierEpsilon) +
                  (5 / 6 : ℝ) = 0 := by
          ring_nf
          rw [frontierEpsilon_sq]
          norm_num
        linarith
      nlinarith [frontierEpsilon_pos, frontierEpsilon_lt_one,
        hu_nonneg, hu_le, hfactor_nonneg, hq_nonneg]

theorem frontierMajorant_boundary_gap_abs_le_const (t : ℝ) :
    |frontierMajorant t (t ^ 2) - frontierPhi t| ≤ 100 := by
  have hnonneg : 0 ≤ frontierMajorant t (t ^ 2) - frontierPhi t :=
    frontierMajorant_boundary_gap_nonneg t
  have hle : frontierMajorant t (t ^ 2) - frontierPhi t ≤ 100 :=
    frontierMajorant_boundary_gap_le_const t
  exact abs_le.mpr ⟨by linarith, hle⟩

theorem frontier_bmo_public_sample_original_unconditional_boundary_support :
    (∀ t : ℝ, frontierOmega frontierEpsilon t (t ^ 2)) ∧
      ∀ t : ℝ, 0 ≤ frontierMajorant t (t ^ 2) - frontierPhi t := by
  exact ⟨frontierOmega_lower_boundary, frontierMajorant_boundary_gap_nonneg⟩

theorem frontier_bmo_public_sample_original_unconditional_boundaryDominates
    (t : ℝ) :
    frontierPhi t ≤ frontierMajorant t (t ^ 2) := by
  exact frontierMajorant_boundaryDominates t

theorem frontierBMOCenteredObjectiveIntegral_le_boundaryMajorantIntegral
    (g : ℝ → ℝ)
    (hphi : IntervalIntegrable (fun t : ℝ ↦ frontierPhi (g t)) volume
      (0 : ℝ) 1)
    (hmajorant : IntervalIntegrable
      (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
        (0 : ℝ) 1) :
    frontierBMOCenteredObjectiveIntegral g ≤
      ∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2) := by
  rw [frontierBMOCenteredObjectiveIntegral]
  exact intervalIntegral.integral_mono (by norm_num) hphi hmajorant
    (fun t ↦ frontierMajorant_boundaryDominates (g t))

def frontierCenteredLinearWitness (t : ℝ) : ℝ :=
  t - (1 / 2 : ℝ)

theorem frontierCenteredLinearWitness_intervalIntegral (a b : ℝ) :
    (∫ t in a..b, frontierCenteredLinearWitness t) =
      (b ^ 2 / 2 - b / 2) - (a ^ 2 / 2 - a / 2) := by
  rw [intervalIntegral.integral_eq_sub_of_hasDerivAt
    (f := fun t : ℝ ↦ t ^ 2 / 2 - t / 2) (f' := frontierCenteredLinearWitness)]
  · intro x _hx
    unfold frontierCenteredLinearWitness
    convert (((hasDerivAt_id x).pow 2).div_const 2).sub
      ((hasDerivAt_id x).div_const 2) using 1
    simp [id]
  · unfold frontierCenteredLinearWitness
    have hcont : Continuous (fun t : ℝ ↦ t - (1 / 2 : ℝ)) := by
      exact continuous_id.sub continuous_const
    exact hcont.intervalIntegrable a b

theorem frontierCenteredLinearWitness_intervalMean
    (a b : ℝ) (hab : a < b) :
    frontierBMOIntervalMean frontierCenteredLinearWitness a b =
      (a + b) / 2 - (1 / 2 : ℝ) := by
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalMean, frontierCenteredLinearWitness_intervalIntegral]
  field_simp [hne]
  ring

theorem frontierCenteredLinearCenteredSquareIntegral (a b : ℝ) :
    (∫ t in a..b, (t - (a + b) / 2) ^ 2) = (b - a) ^ 3 / 12 := by
  rw [intervalIntegral.integral_eq_sub_of_hasDerivAt
    (f := fun t : ℝ ↦ (t - (a + b) / 2) ^ 3 / 3)
    (f' := fun t ↦ (t - (a + b) / 2) ^ 2)]
  · ring_nf
  · intro x _hx
    convert (((hasDerivAt_id x).sub_const ((a + b) / 2)).pow 3).div_const 3
      using 1
    simp [id]
  · have hcont : Continuous (fun t : ℝ ↦ (t - (a + b) / 2) ^ 2) := by
      exact (continuous_id.sub continuous_const).pow 2
    exact hcont.intervalIntegrable a b

theorem frontierCenteredLinearWitness_intervalVariance
    (a b : ℝ) (hab : a < b) :
    frontierBMOIntervalVariance frontierCenteredLinearWitness a b =
      (b - a) ^ 2 / 12 := by
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalVariance,
    frontierCenteredLinearWitness_intervalMean a b hab]
  have hcongr :
      (∫ t in a..b,
          (frontierCenteredLinearWitness t - ((a + b) / 2 - 1 / 2)) ^ 2) =
        ∫ t in a..b, (t - (a + b) / 2) ^ 2 := by
    apply intervalIntegral.integral_congr
    intro t _ht
    unfold frontierCenteredLinearWitness
    ring
  rw [hcongr, frontierCenteredLinearCenteredSquareIntegral]
  field_simp [hne]

theorem frontierCenteredLinearWitness_intervalVarianceIntegrable (a b : ℝ) :
    IntervalIntegrable
      (fun t ↦
        (frontierCenteredLinearWitness t -
          frontierBMOIntervalMean frontierCenteredLinearWitness a b) ^ 2)
      volume a b := by
  have hcont :
      Continuous
        (fun t : ℝ ↦
          (frontierCenteredLinearWitness t -
            frontierBMOIntervalMean frontierCenteredLinearWitness a b) ^ 2) := by
    unfold frontierCenteredLinearWitness
    exact ((continuous_id.sub continuous_const).sub continuous_const).pow 2
  exact hcont.intervalIntegrable a b

theorem frontierCenteredLinearWitness_phiIntervalIntegrable :
    IntervalIntegrable (fun t : ℝ ↦ frontierPhi (frontierCenteredLinearWitness t))
      volume (0 : ℝ) 1 := by
  have hpoly :
      IntervalIntegrable (fun t : ℝ ↦ (t - (1 / 2 : ℝ)) ^ 3) volume
        (0 : ℝ) 1 := by
    have hcont : Continuous (fun t : ℝ ↦ (t - (1 / 2 : ℝ)) ^ 3) := by
      exact (continuous_id.sub continuous_const).pow 3
    exact hcont.intervalIntegrable 0 1
  refine hpoly.congr ?_
  intro t ht
  have htA : t - (1 / 2 : ℝ) ≤ frontierA := by
    rw [frontierA]
    rw [Set.uIoc_of_le (by norm_num : (0 : ℝ) ≤ 1)] at ht
    linarith [ht.2]
  change (t - (1 / 2 : ℝ)) ^ 3 =
    frontierPhi (frontierCenteredLinearWitness t)
  rw [frontierCenteredLinearWitness, frontierPhi_left_of_le _ htA]

theorem frontierCenteredLinearWitness_meanIntegral :
    frontierBMOOriginalMeanIntegral frontierCenteredLinearWitness = 0 := by
  rw [frontierBMOOriginalMeanIntegral,
    frontierCenteredLinearWitness_intervalIntegral]
  norm_num

theorem frontierCenteredLinearWitness_secondMomentIntegral :
    frontierBMOOriginalSecondMomentIntegral frontierCenteredLinearWitness =
      (1 / 12 : ℝ) := by
  rw [frontierBMOOriginalSecondMomentIntegral]
  unfold frontierCenteredLinearWitness
  rw [intervalIntegral.integral_eq_sub_of_hasDerivAt
    (f := fun t : ℝ ↦ (t - (1 / 2 : ℝ)) ^ 3 / 3)
    (f' := fun t ↦ (t - (1 / 2 : ℝ)) ^ 2)]
  · norm_num
  · intro x _hx
    convert (((hasDerivAt_id x).sub_const (1 / 2 : ℝ)).pow 3).div_const 3
      using 1
    simp [id]
  · have hcont : Continuous (fun t : ℝ ↦ (t - (1 / 2 : ℝ)) ^ 2) := by
      exact (continuous_id.sub continuous_const).pow 2
    exact hcont.intervalIntegrable 0 1

theorem frontierCenteredLinearWitness_objectiveIntegral :
    frontierBMOCenteredObjectiveIntegral frontierCenteredLinearWitness = 0 := by
  rw [frontierBMOCenteredObjectiveIntegral]
  calc
    ∫ t in (0 : ℝ)..1, frontierPhi (frontierCenteredLinearWitness t) =
        ∫ t in (0 : ℝ)..1, (t - (1 / 2 : ℝ)) ^ 3 := by
      apply intervalIntegral.integral_congr
      intro t ht
      have htA : t - (1 / 2 : ℝ) ≤ frontierA := by
        rw [frontierA]
        rw [Set.uIcc_of_le (by norm_num : (0 : ℝ) ≤ 1)] at ht
        linarith [ht.2]
      change frontierPhi (frontierCenteredLinearWitness t) =
        (t - (1 / 2 : ℝ)) ^ 3
      rw [frontierCenteredLinearWitness, frontierPhi_left_of_le _ htA]
    _ = 0 := by
      rw [intervalIntegral.integral_eq_sub_of_hasDerivAt
        (f := fun t : ℝ ↦ (t - (1 / 2 : ℝ)) ^ 4 / 4)
        (f' := fun t ↦ (t - (1 / 2 : ℝ)) ^ 3)]
      · norm_num
      · intro x _hx
        convert (((hasDerivAt_id x).sub_const (1 / 2 : ℝ)).pow 4).div_const 4
          using 1
        simp [id]
      · have hcont : Continuous (fun t : ℝ ↦ (t - (1 / 2 : ℝ)) ^ 3) := by
          exact (continuous_id.sub continuous_const).pow 3
        exact hcont.intervalIntegrable 0 1

theorem frontierCenteredLinearWitness_boundaryMajorant_eq_phi_on_unit
    {t : ℝ} (_ht0 : 0 ≤ t) (ht1 : t ≤ 1) :
    frontierMajorant (frontierCenteredLinearWitness t)
        ((frontierCenteredLinearWitness t) ^ 2) =
      frontierPhi (frontierCenteredLinearWitness t) := by
  apply frontierMajorant_left_boundary_eq_phi
  unfold frontierCenteredLinearWitness frontierCStar frontierA
  have heps_le_one : frontierEpsilon ≤ 1 := le_of_lt frontierEpsilon_lt_one
  have hcube_nonneg : 0 ≤ 2 * frontierEpsilon ^ 3 := by
    exact mul_nonneg (by norm_num) (pow_nonneg (le_of_lt frontierEpsilon_pos) 3)
  linarith

theorem frontierCenteredLinearWitness_boundaryMajorantIntegral :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierCenteredLinearWitness t)
        ((frontierCenteredLinearWitness t) ^ 2)) = 0 := by
  calc
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierCenteredLinearWitness t)
        ((frontierCenteredLinearWitness t) ^ 2)) =
        ∫ t in (0 : ℝ)..1,
          frontierPhi (frontierCenteredLinearWitness t) := by
      apply intervalIntegral.integral_congr
      intro t ht
      rw [Set.uIcc_of_le (by norm_num : (0 : ℝ) ≤ 1)] at ht
      exact frontierCenteredLinearWitness_boundaryMajorant_eq_phi_on_unit
        ht.1 ht.2
    _ = 0 := by
      simpa [frontierBMOCenteredObjectiveIntegral] using
        frontierCenteredLinearWitness_objectiveIntegral

theorem frontierMajorant_center_nonneg :
    0 ≤ frontierMajorant 0 (1 / 12 : ℝ) := by
  rw [← frontierEpsilon_sq]
  have hradius :
      frontierRadius frontierEpsilon 0 (frontierEpsilon ^ 2) = 0 := by
    rw [frontierRadius]
    have harg : frontierEpsilon ^ 2 + (0 : ℝ) ^ 2 - frontierEpsilon ^ 2 = 0 := by
      ring
    rw [harg, Real.sqrt_zero]
  have hcplus :
      frontierCPlus frontierEpsilon 0 (frontierEpsilon ^ 2) = 0 := by
    rw [frontierCPlus, hradius]
    norm_num
  have hcenter :
      frontierMajorant 0 (frontierEpsilon ^ 2) =
        2 * frontierEpsilon ^ 3 + frontierKL := by
    rw [frontierMajorant, hcplus]
    have hleft : (0 : ℝ) ≤ frontierCStar := by
      rw [frontierCStar, frontierA]
      have hcube : 0 ≤ 2 * frontierEpsilon ^ 3 :=
        mul_nonneg (by norm_num) (pow_nonneg (le_of_lt frontierEpsilon_pos) 3)
      linarith
    rw [if_pos hleft, frontierLeftPiece, hcplus, hradius]
    field_simp [frontierEpsilon_ne_zero]
    rw [zero_div, Real.exp_zero]
    ring
  rw [hcenter, frontierKL]
  have heps_nonneg : 0 ≤ frontierEpsilon := le_of_lt frontierEpsilon_pos
  have hcube_nonneg : 0 ≤ 2 * frontierEpsilon ^ 3 :=
    mul_nonneg (by norm_num) (pow_nonneg heps_nonneg 3)
  have hkl_nonneg :
      0 ≤ frontierEpsilon * Real.exp (-(frontierCStar / frontierEpsilon)) :=
    mul_nonneg heps_nonneg (le_of_lt (Real.exp_pos _))
  nlinarith

theorem frontierCenteredLinearWitness_boundaryMajorantIntegral_le_center :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierCenteredLinearWitness t)
        ((frontierCenteredLinearWitness t) ^ 2)) ≤
      frontierMajorant 0 (1 / 12 : ℝ) := by
  rw [frontierCenteredLinearWitness_boundaryMajorantIntegral]
  exact frontierMajorant_center_nonneg

theorem frontierCenteredLinearWitness_admissible :
    frontierBMOCenteredFunctionAdmissible frontierCenteredLinearWitness := by
  refine ⟨?_, ?_, frontierCenteredLinearWitness_phiIntervalIntegrable,
    frontierCenteredLinearWitness_meanIntegral,
    frontierCenteredLinearWitness_secondMomentIntegral, ?_⟩
  · unfold frontierCenteredLinearWitness
    have hcont : Continuous (fun t : ℝ ↦ t - (1 / 2 : ℝ)) := by
      exact continuous_id.sub continuous_const
    exact hcont.intervalIntegrable 0 1
  · unfold frontierCenteredLinearWitness
    have hcont : Continuous (fun t : ℝ ↦ (t - (1 / 2 : ℝ)) ^ 2) := by
      exact (continuous_id.sub continuous_const).pow 2
    exact hcont.intervalIntegrable 0 1
  · intro a b ha hab hb
    refine ⟨frontierCenteredLinearWitness_intervalVarianceIntegrable a b, ?_⟩
    rw [frontierCenteredLinearWitness_intervalVariance a b hab]
    have hba_nonneg : 0 ≤ b - a := by linarith
    have hba_le : b - a ≤ 1 := by linarith
    nlinarith

theorem frontierCenteredLinearWitness_mem_objectiveSet :
    0 ∈ frontierBMOCenteredFunctionObjectiveSet := by
  refine ⟨frontierCenteredLinearWitness,
    frontierCenteredLinearWitness_admissible, ?_⟩
  exact frontierCenteredLinearWitness_objectiveIntegral.symm

theorem frontierBMOCenteredFunctionObjectiveSet_nonempty :
    frontierBMOCenteredFunctionObjectiveSet.Nonempty := by
  exact ⟨0, frontierCenteredLinearWitness_mem_objectiveSet⟩

theorem frontierBMOCenteredFunctionObjectiveSet_bddAbove_of_actualUpper
    (hupper : frontierBMOCenteredActualUpperBound) :
    BddAbove frontierBMOCenteredFunctionObjectiveSet := by
  exact ⟨frontierBMOPublicAnswer, hupper⟩

theorem frontierCenteredLinearWitness_originalObjective_mem :
    -(1985 / 2 : ℝ) ∈ frontierBMOOriginalFunctionObjectiveSet := by
  have hmem :=
    frontier_centered_objective_shift_mem_original_objectiveSet_of_admissible
      frontierCenteredLinearWitness frontierCenteredLinearWitness_admissible
  rw [frontierCenteredLinearWitness_objectiveIntegral] at hmem
  norm_num at hmem ⊢
  exact hmem

theorem frontierBMOOriginalFunctionObjectiveSet_nonempty :
    frontierBMOOriginalFunctionObjectiveSet.Nonempty := by
  exact ⟨-(1985 / 2 : ℝ), frontierCenteredLinearWitness_originalObjective_mem⟩

theorem frontierRightTailPiece_exists :
    ∃ B : ℝ → ℝ → ℝ,
      B = frontierRightTailPiece ∧
        frontierRightReflectedCutoff < frontierRightTailStart ∧
        (∀ t : ℝ, frontierA ≤ t → B t (t ^ 2) = frontierPhi t) ∧
        ∀ x1 x2 : ℝ,
          B x1 x2 =
            frontierRightTailTrace (frontierCPlus frontierEpsilon x1 x2) -
              frontierRadius frontierEpsilon x1 x2 *
                frontierRightTailTraceDeriv (frontierCPlus frontierEpsilon x1 x2) := by
  refine ⟨frontierRightTailPiece, rfl, frontierRightTailStart_beyond_reflected_cutoff, ?_, ?_⟩
  · intro t ht
    exact frontierRightTailPiece_boundary t ht
  · intro x1 x2
    rfl

def frontierStoppedLogCupObjective : ℝ :=
  2 * frontierEpsilon ^ 3 + frontierKL

def frontierStoppedLogCupRatio : ℝ :=
  Real.exp (-(frontierCStar / frontierEpsilon))

def frontierStoppedLogCupOptimizer (t : ℝ) : ℝ :=
  if t < frontierStoppedLogCupRatio / 2 then
    frontierCStar + frontierEpsilon
  else if t < frontierStoppedLogCupRatio then
    frontierCStar - frontierEpsilon
  else
    frontierEpsilon * (Real.log (1 / t) - 1)

theorem frontierStoppedLogCupRatio_pos :
    0 < frontierStoppedLogCupRatio := by
  rw [frontierStoppedLogCupRatio]
  positivity

theorem frontierStoppedLogCupRatio_ne_zero :
    frontierStoppedLogCupRatio ≠ 0 :=
  ne_of_gt frontierStoppedLogCupRatio_pos

theorem frontierKL_eq_epsilon_mul_stoppedLogCupRatio :
    frontierKL = frontierEpsilon * frontierStoppedLogCupRatio := by
  rw [frontierKL, frontierStoppedLogCupRatio]

theorem frontierStoppedLogCupRatio_lt_one :
    frontierStoppedLogCupRatio < 1 := by
  rw [frontierStoppedLogCupRatio]
  have hCStar_pos : 0 < frontierCStar := by
    rw [frontierCStar, frontierA]
    have hcube_pos : 0 < 2 * frontierEpsilon ^ 3 := by
      exact mul_pos (by norm_num) (pow_pos frontierEpsilon_pos 3)
    linarith
  have hquot_pos : 0 < frontierCStar / frontierEpsilon :=
    div_pos hCStar_pos frontierEpsilon_pos
  have hneg : -(frontierCStar / frontierEpsilon) < 0 := by
    linarith
  simpa using (Real.exp_lt_exp.mpr hneg)

theorem frontierStoppedLogCupRatio_half_pos :
    0 < frontierStoppedLogCupRatio / 2 := by
  exact div_pos frontierStoppedLogCupRatio_pos (by norm_num)

theorem frontierStoppedLogCupRatio_half_lt_ratio :
    frontierStoppedLogCupRatio / 2 < frontierStoppedLogCupRatio := by
  linarith [frontierStoppedLogCupRatio_pos]

theorem frontierStoppedLogCupOptimizer_left
    {t : ℝ} (ht : t < frontierStoppedLogCupRatio / 2) :
    frontierStoppedLogCupOptimizer t = frontierCStar + frontierEpsilon := by
  rw [frontierStoppedLogCupOptimizer, if_pos ht]

theorem frontierStoppedLogCupOptimizer_middle
    {t : ℝ}
    (hleft : frontierStoppedLogCupRatio / 2 ≤ t)
    (hright : t < frontierStoppedLogCupRatio) :
    frontierStoppedLogCupOptimizer t = frontierCStar - frontierEpsilon := by
  rw [frontierStoppedLogCupOptimizer, if_neg (not_lt.mpr hleft), if_pos hright]

theorem frontierStoppedLogCupOptimizer_tail
    {t : ℝ} (ht : frontierStoppedLogCupRatio ≤ t) :
    frontierStoppedLogCupOptimizer t =
      frontierEpsilon * (Real.log (1 / t) - 1) := by
  have hleft : ¬ t < frontierStoppedLogCupRatio / 2 := by
    exact not_lt.mpr (le_trans (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio) ht)
  have hright : ¬ t < frontierStoppedLogCupRatio := not_lt.mpr ht
  rw [frontierStoppedLogCupOptimizer, if_neg hleft, if_neg hright]

theorem frontierStoppedLogCupOptimizer_zero_value :
    frontierStoppedLogCupOptimizer 0 = frontierCStar + frontierEpsilon := by
  exact frontierStoppedLogCupOptimizer_left
    (by linarith [frontierStoppedLogCupRatio_half_pos])

theorem frontierStoppedLogCupOptimizer_one_value :
    frontierStoppedLogCupOptimizer 1 = -frontierEpsilon := by
  have htail : frontierStoppedLogCupRatio ≤ (1 : ℝ) := by
    exact le_of_lt frontierStoppedLogCupRatio_lt_one
  rw [frontierStoppedLogCupOptimizer_tail htail]
  norm_num

theorem frontierStoppedLogCup_log_one_div_ratio :
    Real.log (1 / frontierStoppedLogCupRatio) =
      frontierCStar / frontierEpsilon := by
  rw [one_div, Real.log_inv, frontierStoppedLogCupRatio, Real.log_exp]
  ring

theorem frontier_hasDerivAt_mul_log_one_div {x : ℝ} (hx : x ≠ 0) :
    HasDerivAt (fun t : ℝ ↦ t * Real.log (1 / t))
      (Real.log (1 / x) - 1) x := by
  have hdiv :
      HasDerivAt (fun t : ℝ ↦ (1 : ℝ) / t) (-(1 / x ^ 2)) x := by
    simpa [one_div, div_eq_mul_inv] using (hasDerivAt_inv hx)
  have hlog :
      HasDerivAt (fun t : ℝ ↦ Real.log (1 / t)) (-(1 / x)) x := by
    convert (Real.hasDerivAt_log (one_div_ne_zero hx)).comp x hdiv using 1
    field_simp [hx]
  convert (hasDerivAt_id x).mul hlog using 1
  simp only [id_eq, one_mul]
  field_simp [hx]
  ring_nf

theorem frontier_hasDerivAt_log_one_div {x : ℝ} (hx : x ≠ 0) :
    HasDerivAt (fun t : ℝ ↦ Real.log (1 / t)) (-(1 / x)) x := by
  have hdiv :
      HasDerivAt (fun t : ℝ ↦ (1 : ℝ) / t) (-(1 / x ^ 2)) x := by
    simpa [one_div, div_eq_mul_inv] using (hasDerivAt_inv hx)
  convert (Real.hasDerivAt_log (one_div_ne_zero hx)).comp x hdiv using 1
  field_simp [hx]

theorem frontierStoppedLogCup_logMinusOne_tail_integral :
    (∫ t in frontierStoppedLogCupRatio..1, (Real.log (1 / t) - 1)) =
      -frontierStoppedLogCupRatio *
        Real.log (1 / frontierStoppedLogCupRatio) := by
  rw [intervalIntegral.integral_eq_sub_of_hasDerivAt
    (f := fun t : ℝ ↦ t * Real.log (1 / t))
    (f' := fun t ↦ Real.log (1 / t) - 1)]
  · norm_num
  · intro x hx
    rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at hx
    exact frontier_hasDerivAt_mul_log_one_div
      (ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos hx.1))
  · have hcont :
        ContinuousOn (fun t : ℝ ↦ Real.log (1 / t) - 1)
          [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
      have hinv :
          ContinuousOn (fun t : ℝ ↦ 1 / t)
            [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
        exact continuousOn_const.div continuousOn_id (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
          exact ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1))
      exact (hinv.log (by
        intro t ht
        rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
        exact one_div_ne_zero
          (ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1)))).sub
            continuousOn_const
    exact hcont.intervalIntegrable

theorem frontierStoppedLogCupOptimizer_left_ge_A
    {t : ℝ} (ht : t < frontierStoppedLogCupRatio / 2) :
    frontierA ≤ frontierStoppedLogCupOptimizer t := by
  rw [frontierStoppedLogCupOptimizer_left ht, frontierCStar]
  have hnonneg : 0 ≤ 2 * frontierEpsilon ^ 3 := by
    exact le_of_lt (mul_pos (by norm_num) (pow_pos frontierEpsilon_pos 3))
  linarith [frontierEpsilon_pos]

theorem frontierStoppedLogCupOptimizer_middle_le_A
    {t : ℝ}
    (hleft : frontierStoppedLogCupRatio / 2 ≤ t)
    (hright : t < frontierStoppedLogCupRatio) :
    frontierStoppedLogCupOptimizer t ≤ frontierA := by
  rw [frontierStoppedLogCupOptimizer_middle hleft hright]
  exact le_of_lt frontierCStar_sub_epsilon_lt_A

theorem frontierStoppedLogCupOptimizer_tail_le_cupAlpha
    {t : ℝ} (hleft : frontierStoppedLogCupRatio ≤ t) (_hright : t ≤ 1) :
    frontierStoppedLogCupOptimizer t ≤ frontierCupAlpha := by
  rw [frontierStoppedLogCupOptimizer_tail hleft, frontierCupAlpha]
  have htpos : 0 < t := lt_of_lt_of_le frontierStoppedLogCupRatio_pos hleft
  have hinv_le : 1 / t ≤ 1 / frontierStoppedLogCupRatio :=
    one_div_le_one_div_of_le frontierStoppedLogCupRatio_pos hleft
  have hlog_le :
      Real.log (1 / t) ≤ Real.log (1 / frontierStoppedLogCupRatio) :=
    Real.log_le_log (div_pos zero_lt_one htpos) hinv_le
  rw [frontierStoppedLogCup_log_one_div_ratio] at hlog_le
  have hsub :
      Real.log (1 / t) - 1 ≤ frontierCStar / frontierEpsilon - 1 := by
    linarith
  have hmul :
      frontierEpsilon * (Real.log (1 / t) - 1) ≤
        frontierEpsilon * (frontierCStar / frontierEpsilon - 1) :=
    mul_le_mul_of_nonneg_left hsub (le_of_lt frontierEpsilon_pos)
  calc
    frontierEpsilon * (Real.log (1 / t) - 1) ≤
        frontierEpsilon * (frontierCStar / frontierEpsilon - 1) := hmul
    _ = frontierCStar - frontierEpsilon := by
      field_simp [frontierEpsilon_ne_zero]

theorem frontierStoppedLogCupOptimizer_tail_le_A
    {t : ℝ} (hleft : frontierStoppedLogCupRatio ≤ t) (hright : t ≤ 1) :
    frontierStoppedLogCupOptimizer t ≤ frontierA := by
  exact le_trans (frontierStoppedLogCupOptimizer_tail_le_cupAlpha hleft hright)
    (le_of_lt frontierCStar_sub_epsilon_lt_A)

theorem frontierPhi_stoppedLogCupOptimizer_left
    {t : ℝ} (ht : t < frontierStoppedLogCupRatio / 2) :
    frontierPhi (frontierStoppedLogCupOptimizer t) =
      frontierStoppedLogCupOptimizer t ^ 3 +
        2 * (frontierStoppedLogCupOptimizer t - frontierA) := by
  exact frontierPhi_right_of_ge _ (frontierStoppedLogCupOptimizer_left_ge_A ht)

theorem frontierPhi_stoppedLogCupOptimizer_middle
    {t : ℝ}
    (hleft : frontierStoppedLogCupRatio / 2 ≤ t)
    (hright : t < frontierStoppedLogCupRatio) :
    frontierPhi (frontierStoppedLogCupOptimizer t) =
      frontierStoppedLogCupOptimizer t ^ 3 := by
  exact frontierPhi_left_of_le _
    (frontierStoppedLogCupOptimizer_middle_le_A hleft hright)

theorem frontierPhi_stoppedLogCupOptimizer_tail
    {t : ℝ} (hleft : frontierStoppedLogCupRatio ≤ t) (hright : t ≤ 1) :
    frontierPhi (frontierStoppedLogCupOptimizer t) =
      frontierStoppedLogCupOptimizer t ^ 3 := by
  exact frontierPhi_left_of_le _
    (frontierStoppedLogCupOptimizer_tail_le_A hleft hright)

theorem frontierStoppedLogCupOptimizer_ratio_half_value :
    frontierStoppedLogCupOptimizer (frontierStoppedLogCupRatio / 2) =
      frontierCStar - frontierEpsilon := by
  exact frontierStoppedLogCupOptimizer_middle le_rfl
    frontierStoppedLogCupRatio_half_lt_ratio

theorem frontierStoppedLogCupOptimizer_ratio_value :
    frontierStoppedLogCupOptimizer frontierStoppedLogCupRatio =
      frontierCStar - frontierEpsilon := by
  rw [frontierStoppedLogCupOptimizer_tail le_rfl,
    frontierStoppedLogCup_log_one_div_ratio]
  field_simp [frontierEpsilon_ne_zero]

theorem frontierStoppedLogCupOptimizer_left_square
    {t : ℝ} (ht : t < frontierStoppedLogCupRatio / 2) :
    frontierStoppedLogCupOptimizer t ^ 2 =
      (frontierCStar + frontierEpsilon) ^ 2 := by
  rw [frontierStoppedLogCupOptimizer_left ht]

theorem frontierStoppedLogCupOptimizer_middle_square
    {t : ℝ}
    (hleft : frontierStoppedLogCupRatio / 2 ≤ t)
    (hright : t < frontierStoppedLogCupRatio) :
    frontierStoppedLogCupOptimizer t ^ 2 =
      (frontierCStar - frontierEpsilon) ^ 2 := by
  rw [frontierStoppedLogCupOptimizer_middle hleft hright]

theorem frontierStoppedLogCupOptimizer_tail_square
    {t : ℝ} (hleft : frontierStoppedLogCupRatio ≤ t) :
    frontierStoppedLogCupOptimizer t ^ 2 =
      frontierEpsilon ^ 2 * (Real.log (1 / t) - 1) ^ 2 := by
  rw [frontierStoppedLogCupOptimizer_tail hleft]
  ring

theorem frontierPhi_stoppedLogCupOptimizer_left_value
    {t : ℝ} (ht : t < frontierStoppedLogCupRatio / 2) :
    frontierPhi (frontierStoppedLogCupOptimizer t) =
      (frontierCStar + frontierEpsilon) ^ 3 +
        2 * ((frontierCStar + frontierEpsilon) - frontierA) := by
  rw [frontierPhi_stoppedLogCupOptimizer_left ht,
    frontierStoppedLogCupOptimizer_left ht]

theorem frontierPhi_stoppedLogCupOptimizer_middle_value
    {t : ℝ}
    (hleft : frontierStoppedLogCupRatio / 2 ≤ t)
    (hright : t < frontierStoppedLogCupRatio) :
    frontierPhi (frontierStoppedLogCupOptimizer t) =
      (frontierCStar - frontierEpsilon) ^ 3 := by
  rw [frontierPhi_stoppedLogCupOptimizer_middle hleft hright,
    frontierStoppedLogCupOptimizer_middle hleft hright]

theorem frontierPhi_stoppedLogCupOptimizer_tail_value
    {t : ℝ} (hleft : frontierStoppedLogCupRatio ≤ t) (hright : t ≤ 1) :
    frontierPhi (frontierStoppedLogCupOptimizer t) =
      frontierEpsilon ^ 3 * (Real.log (1 / t) - 1) ^ 3 := by
  rw [frontierPhi_stoppedLogCupOptimizer_tail hleft hright,
    frontierStoppedLogCupOptimizer_tail hleft]
  ring

theorem frontierStoppedLogCupOptimizer_left_intervalIntegrable :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume
      (0 : ℝ) (frontierStoppedLogCupRatio / 2) := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le
    (le_of_lt frontierStoppedLogCupRatio_half_pos)]
  have hconst :
      IntegrableOn (fun _ : ℝ ↦ frontierCStar + frontierEpsilon)
        (Set.Ioo (0 : ℝ) (frontierStoppedLogCupRatio / 2)) volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le
      (le_of_lt frontierStoppedLogCupRatio_half_pos)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  exact (frontierStoppedLogCupOptimizer_left ht.2).symm

theorem frontierStoppedLogCupOptimizer_left_square_intervalIntegrable :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume (0 : ℝ) (frontierStoppedLogCupRatio / 2) := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le
    (le_of_lt frontierStoppedLogCupRatio_half_pos)]
  have hconst :
      IntegrableOn (fun _ : ℝ ↦ (frontierCStar + frontierEpsilon) ^ 2)
        (Set.Ioo (0 : ℝ) (frontierStoppedLogCupRatio / 2)) volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le
      (le_of_lt frontierStoppedLogCupRatio_half_pos)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  exact (frontierStoppedLogCupOptimizer_left_square ht.2).symm

theorem frontierPhi_stoppedLogCupOptimizer_left_intervalIntegrable :
    IntervalIntegrable
      (fun t : ℝ ↦ frontierPhi (frontierStoppedLogCupOptimizer t)) volume
        (0 : ℝ) (frontierStoppedLogCupRatio / 2) := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le
    (le_of_lt frontierStoppedLogCupRatio_half_pos)]
  have hconst :
      IntegrableOn
        (fun _ : ℝ ↦
          (frontierCStar + frontierEpsilon) ^ 3 +
            2 * ((frontierCStar + frontierEpsilon) - frontierA))
        (Set.Ioo (0 : ℝ) (frontierStoppedLogCupRatio / 2)) volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le
      (le_of_lt frontierStoppedLogCupRatio_half_pos)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  exact (frontierPhi_stoppedLogCupOptimizer_left_value ht.2).symm

theorem frontierStoppedLogCupOptimizer_middle_intervalIntegrable :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume
      (frontierStoppedLogCupRatio / 2) frontierStoppedLogCupRatio := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le
    (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)]
  have hconst :
      IntegrableOn (fun _ : ℝ ↦ frontierCStar - frontierEpsilon)
        (Set.Ioo (frontierStoppedLogCupRatio / 2) frontierStoppedLogCupRatio)
          volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le
      (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  exact (frontierStoppedLogCupOptimizer_middle (le_of_lt ht.1) ht.2).symm

theorem frontierStoppedLogCupOptimizer_middle_square_intervalIntegrable :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume (frontierStoppedLogCupRatio / 2) frontierStoppedLogCupRatio := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le
    (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)]
  have hconst :
      IntegrableOn (fun _ : ℝ ↦ (frontierCStar - frontierEpsilon) ^ 2)
        (Set.Ioo (frontierStoppedLogCupRatio / 2) frontierStoppedLogCupRatio)
          volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le
      (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  exact (frontierStoppedLogCupOptimizer_middle_square
    (le_of_lt ht.1) ht.2).symm

theorem frontierPhi_stoppedLogCupOptimizer_middle_intervalIntegrable :
    IntervalIntegrable
      (fun t : ℝ ↦ frontierPhi (frontierStoppedLogCupOptimizer t)) volume
        (frontierStoppedLogCupRatio / 2) frontierStoppedLogCupRatio := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le
    (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)]
  have hconst :
      IntegrableOn (fun _ : ℝ ↦ (frontierCStar - frontierEpsilon) ^ 3)
        (Set.Ioo (frontierStoppedLogCupRatio / 2) frontierStoppedLogCupRatio)
          volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le
      (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  exact (frontierPhi_stoppedLogCupOptimizer_middle_value
    (le_of_lt ht.1) ht.2).symm

theorem frontierStoppedLogCup_tailFormula_continuousOn :
    ContinuousOn
      (fun t : ℝ ↦ frontierEpsilon * (Real.log (1 / t) - 1))
      [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
  have hinv :
      ContinuousOn (fun t : ℝ ↦ 1 / t)
        [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
    exact continuousOn_const.div continuousOn_id (by
      intro t ht
      rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
      exact ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1))
  have hlog :
      ContinuousOn (fun t : ℝ ↦ Real.log (1 / t))
        [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
    exact hinv.log (by
      intro t ht
      rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
      exact one_div_ne_zero
        (ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1)))
  exact continuousOn_const.mul (hlog.sub continuousOn_const)

theorem frontierStoppedLogCupOptimizer_tail_continuousOn :
    ContinuousOn frontierStoppedLogCupOptimizer
      [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
  refine frontierStoppedLogCup_tailFormula_continuousOn.congr ?_
  intro t ht
  rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
  exact frontierStoppedLogCupOptimizer_tail ht.1

theorem frontierStoppedLogCupOptimizer_tail_intervalIntegrable :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume
      frontierStoppedLogCupRatio 1 := by
  exact frontierStoppedLogCupOptimizer_tail_continuousOn.intervalIntegrable

theorem frontierStoppedLogCupOptimizer_tail_square_intervalIntegrable :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume frontierStoppedLogCupRatio 1 := by
  exact (frontierStoppedLogCupOptimizer_tail_continuousOn.pow 2).intervalIntegrable

theorem frontierPhi_stoppedLogCupOptimizer_tail_continuousOn :
    ContinuousOn (fun t : ℝ ↦ frontierPhi (frontierStoppedLogCupOptimizer t))
      [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
  have hformula :
      ContinuousOn
        (fun t : ℝ ↦
          frontierEpsilon ^ 3 * (Real.log (1 / t) - 1) ^ 3)
        [[frontierStoppedLogCupRatio, (1 : ℝ)]] :=
    by
      have hinv :
          ContinuousOn (fun t : ℝ ↦ 1 / t)
            [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
        exact continuousOn_const.div continuousOn_id (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
          exact ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1))
      have hlog :
          ContinuousOn (fun t : ℝ ↦ Real.log (1 / t))
            [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
        exact hinv.log (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
          exact one_div_ne_zero
            (ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1)))
      exact continuousOn_const.mul ((hlog.sub continuousOn_const).pow 3)
  refine hformula.congr ?_
  intro t ht
  rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
  exact frontierPhi_stoppedLogCupOptimizer_tail_value ht.1 ht.2

theorem frontierPhi_stoppedLogCupOptimizer_tail_intervalIntegrable :
    IntervalIntegrable (fun t : ℝ ↦ frontierPhi (frontierStoppedLogCupOptimizer t))
      volume frontierStoppedLogCupRatio 1 := by
  exact frontierPhi_stoppedLogCupOptimizer_tail_continuousOn.intervalIntegrable

theorem frontierStoppedLogCupOptimizer_intervalIntegrable :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume (0 : ℝ) 1 := by
  exact
    (frontierStoppedLogCupOptimizer_left_intervalIntegrable.trans
      frontierStoppedLogCupOptimizer_middle_intervalIntegrable).trans
        frontierStoppedLogCupOptimizer_tail_intervalIntegrable

theorem frontierStoppedLogCupOptimizer_square_intervalIntegrable :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume (0 : ℝ) 1 := by
  exact
    (frontierStoppedLogCupOptimizer_left_square_intervalIntegrable.trans
      frontierStoppedLogCupOptimizer_middle_square_intervalIntegrable).trans
        frontierStoppedLogCupOptimizer_tail_square_intervalIntegrable

theorem frontierPhi_stoppedLogCupOptimizer_intervalIntegrable :
    IntervalIntegrable
      (fun t : ℝ ↦ frontierPhi (frontierStoppedLogCupOptimizer t))
        volume (0 : ℝ) 1 := by
  exact
    (frontierPhi_stoppedLogCupOptimizer_left_intervalIntegrable.trans
      frontierPhi_stoppedLogCupOptimizer_middle_intervalIntegrable).trans
        frontierPhi_stoppedLogCupOptimizer_tail_intervalIntegrable

theorem frontierStoppedLogCupOptimizer_centered_integrability_obligations :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume (0 : ℝ) 1 ∧
      IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
        volume (0 : ℝ) 1 ∧
      IntervalIntegrable
        (fun t : ℝ ↦ frontierPhi (frontierStoppedLogCupOptimizer t))
          volume (0 : ℝ) 1 := by
  exact ⟨frontierStoppedLogCupOptimizer_intervalIntegrable,
    frontierStoppedLogCupOptimizer_square_intervalIntegrable,
    frontierPhi_stoppedLogCupOptimizer_intervalIntegrable⟩

theorem frontierStoppedLogCupOptimizer_left_integral :
    (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
        frontierStoppedLogCupOptimizer t) =
      (frontierStoppedLogCupRatio / 2) * (frontierCStar + frontierEpsilon) := by
  calc
    (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
        frontierStoppedLogCupOptimizer t) =
        ∫ _t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
          (frontierCStar + frontierEpsilon) := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne (frontierStoppedLogCupRatio / 2)]
        with t hne ht
      rw [Set.uIoc_of_le (le_of_lt frontierStoppedLogCupRatio_half_pos)] at ht
      have hlt : t < frontierStoppedLogCupRatio / 2 := lt_of_le_of_ne ht.2 hne
      exact frontierStoppedLogCupOptimizer_left hlt
    _ = (frontierStoppedLogCupRatio / 2) *
        (frontierCStar + frontierEpsilon) := by
      rw [intervalIntegral.integral_const]
      simp

theorem frontierStoppedLogCupOptimizer_middle_integral :
    (∫ t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
        frontierStoppedLogCupOptimizer t) =
      (frontierStoppedLogCupRatio / 2) * (frontierCStar - frontierEpsilon) := by
  calc
    (∫ t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
        frontierStoppedLogCupOptimizer t) =
        ∫ _t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
          (frontierCStar - frontierEpsilon) := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne frontierStoppedLogCupRatio] with t hne ht
      rw [Set.uIoc_of_le (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)] at ht
      have hlt : t < frontierStoppedLogCupRatio := lt_of_le_of_ne ht.2 hne
      exact frontierStoppedLogCupOptimizer_middle (le_of_lt ht.1) hlt
    _ = (frontierStoppedLogCupRatio / 2) *
        (frontierCStar - frontierEpsilon) := by
      rw [intervalIntegral.integral_const]
      change (frontierStoppedLogCupRatio - frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) =
        (frontierStoppedLogCupRatio / 2) * (frontierCStar - frontierEpsilon)
      ring

theorem frontierStoppedLogCupOptimizer_tail_integral :
    (∫ t in frontierStoppedLogCupRatio..1, frontierStoppedLogCupOptimizer t) =
      -frontierCStar * frontierStoppedLogCupRatio := by
  calc
    (∫ t in frontierStoppedLogCupRatio..1, frontierStoppedLogCupOptimizer t) =
        ∫ t in frontierStoppedLogCupRatio..1,
          frontierEpsilon * (Real.log (1 / t) - 1) := by
      apply intervalIntegral.integral_congr
      intro t ht
      rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
      exact frontierStoppedLogCupOptimizer_tail ht.1
    _ = frontierEpsilon *
        (∫ t in frontierStoppedLogCupRatio..1, (Real.log (1 / t) - 1)) := by
      rw [intervalIntegral.integral_const_mul]
    _ = frontierEpsilon *
        (-frontierStoppedLogCupRatio *
          Real.log (1 / frontierStoppedLogCupRatio)) := by
      rw [frontierStoppedLogCup_logMinusOne_tail_integral]
    _ = -frontierCStar * frontierStoppedLogCupRatio := by
      rw [frontierStoppedLogCup_log_one_div_ratio]
      field_simp [frontierEpsilon_ne_zero]

theorem frontierStoppedLogCupOptimizer_meanIntegral :
    frontierBMOOriginalMeanIntegral frontierStoppedLogCupOptimizer = 0 := by
  rw [frontierBMOOriginalMeanIntegral]
  calc
    (∫ t in (0 : ℝ)..1, frontierStoppedLogCupOptimizer t) =
        (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
          frontierStoppedLogCupOptimizer t) +
        (∫ t in frontierStoppedLogCupRatio / 2..1,
          frontierStoppedLogCupOptimizer t) := by
      rw [intervalIntegral.integral_add_adjacent_intervals
        frontierStoppedLogCupOptimizer_left_intervalIntegrable
        (frontierStoppedLogCupOptimizer_middle_intervalIntegrable.trans
          frontierStoppedLogCupOptimizer_tail_intervalIntegrable)]
    _ = (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
          frontierStoppedLogCupOptimizer t) +
        ((∫ t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
          frontierStoppedLogCupOptimizer t) +
        (∫ t in frontierStoppedLogCupRatio..1,
          frontierStoppedLogCupOptimizer t)) := by
      rw [intervalIntegral.integral_add_adjacent_intervals
        frontierStoppedLogCupOptimizer_middle_intervalIntegrable
        frontierStoppedLogCupOptimizer_tail_intervalIntegrable]
    _ = 0 := by
      rw [frontierStoppedLogCupOptimizer_left_integral,
        frontierStoppedLogCupOptimizer_middle_integral,
        frontierStoppedLogCupOptimizer_tail_integral]
      ring

theorem frontier_hasDerivAt_log_one_div_sq_antiderivative {x : ℝ} (hx : x ≠ 0) :
    HasDerivAt
      (fun t : ℝ ↦ t * ((Real.log (1 / t)) ^ 2 + 1))
      ((Real.log (1 / x) - 1) ^ 2) x := by
  have hlog := frontier_hasDerivAt_log_one_div hx
  have hsq :
      HasDerivAt
        (fun t : ℝ ↦ (Real.log (1 / t)) ^ 2 + 1)
        (2 * Real.log (1 / x) * (-(1 / x))) x := by
    simpa [pow_one, mul_assoc] using ((hlog.pow 2).add_const 1)
  convert (hasDerivAt_id x).mul hsq using 1
  simp only [id_eq]
  field_simp [hx]
  ring

theorem frontierStoppedLogCup_logMinusOne_sq_tail_integral :
    (∫ t in frontierStoppedLogCupRatio..1,
        (Real.log (1 / t) - 1) ^ 2) =
      1 - frontierStoppedLogCupRatio *
        ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 2 + 1) := by
  rw [intervalIntegral.integral_eq_sub_of_hasDerivAt
    (f := fun t : ℝ ↦ t * ((Real.log (1 / t)) ^ 2 + 1))
    (f' := fun t ↦ (Real.log (1 / t) - 1) ^ 2)]
  · norm_num
  · intro x hx
    rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at hx
    exact frontier_hasDerivAt_log_one_div_sq_antiderivative
      (ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos hx.1))
  · have hcont :
        ContinuousOn (fun t : ℝ ↦ (Real.log (1 / t) - 1) ^ 2)
          [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
      have hinv :
          ContinuousOn (fun t : ℝ ↦ 1 / t)
            [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
        exact continuousOn_const.div continuousOn_id (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
          exact ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1))
      have hlog :
          ContinuousOn (fun t : ℝ ↦ Real.log (1 / t))
            [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
        exact hinv.log (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
          exact one_div_ne_zero
            (ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1)))
      exact ((hlog.sub continuousOn_const).pow 2)
    exact hcont.intervalIntegrable

theorem frontierStoppedLogCupOptimizer_left_square_integral :
    (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
        frontierStoppedLogCupOptimizer t ^ 2) =
      (frontierStoppedLogCupRatio / 2) *
        (frontierCStar + frontierEpsilon) ^ 2 := by
  calc
    (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
        frontierStoppedLogCupOptimizer t ^ 2) =
        ∫ _t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
          (frontierCStar + frontierEpsilon) ^ 2 := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne (frontierStoppedLogCupRatio / 2)]
        with t hne ht
      rw [Set.uIoc_of_le (le_of_lt frontierStoppedLogCupRatio_half_pos)] at ht
      have hlt : t < frontierStoppedLogCupRatio / 2 := lt_of_le_of_ne ht.2 hne
      exact frontierStoppedLogCupOptimizer_left_square hlt
    _ = (frontierStoppedLogCupRatio / 2) *
        (frontierCStar + frontierEpsilon) ^ 2 := by
      rw [intervalIntegral.integral_const]
      simp

theorem frontierStoppedLogCupOptimizer_middle_square_integral :
    (∫ t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
        frontierStoppedLogCupOptimizer t ^ 2) =
      (frontierStoppedLogCupRatio / 2) *
        (frontierCStar - frontierEpsilon) ^ 2 := by
  calc
    (∫ t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
        frontierStoppedLogCupOptimizer t ^ 2) =
        ∫ _t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
          (frontierCStar - frontierEpsilon) ^ 2 := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne frontierStoppedLogCupRatio] with t hne ht
      rw [Set.uIoc_of_le (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)] at ht
      have hlt : t < frontierStoppedLogCupRatio := lt_of_le_of_ne ht.2 hne
      exact frontierStoppedLogCupOptimizer_middle_square (le_of_lt ht.1) hlt
    _ = (frontierStoppedLogCupRatio / 2) *
        (frontierCStar - frontierEpsilon) ^ 2 := by
      rw [intervalIntegral.integral_const]
      change (frontierStoppedLogCupRatio - frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) ^ 2 =
        (frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) ^ 2
      ring

theorem frontierStoppedLogCupOptimizer_tail_square_integral :
    (∫ t in frontierStoppedLogCupRatio..1,
        frontierStoppedLogCupOptimizer t ^ 2) =
      frontierEpsilon ^ 2 *
        (1 - frontierStoppedLogCupRatio *
          ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 2 + 1)) := by
  calc
    (∫ t in frontierStoppedLogCupRatio..1,
        frontierStoppedLogCupOptimizer t ^ 2) =
        ∫ t in frontierStoppedLogCupRatio..1,
          frontierEpsilon ^ 2 * (Real.log (1 / t) - 1) ^ 2 := by
      apply intervalIntegral.integral_congr
      intro t ht
      rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
      exact frontierStoppedLogCupOptimizer_tail_square ht.1
    _ = frontierEpsilon ^ 2 *
        (∫ t in frontierStoppedLogCupRatio..1,
          (Real.log (1 / t) - 1) ^ 2) := by
      rw [intervalIntegral.integral_const_mul]
    _ = frontierEpsilon ^ 2 *
        (1 - frontierStoppedLogCupRatio *
          ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 2 + 1)) := by
      rw [frontierStoppedLogCup_logMinusOne_sq_tail_integral]

theorem frontierStoppedLogCupOptimizer_secondMomentIntegral :
    frontierBMOOriginalSecondMomentIntegral frontierStoppedLogCupOptimizer =
      (1 / 12 : ℝ) := by
  rw [frontierBMOOriginalSecondMomentIntegral]
  calc
    (∫ t in (0 : ℝ)..1, frontierStoppedLogCupOptimizer t ^ 2) =
        (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
          frontierStoppedLogCupOptimizer t ^ 2) +
        (∫ t in frontierStoppedLogCupRatio / 2..1,
          frontierStoppedLogCupOptimizer t ^ 2) := by
      rw [intervalIntegral.integral_add_adjacent_intervals
        frontierStoppedLogCupOptimizer_left_square_intervalIntegrable
        (frontierStoppedLogCupOptimizer_middle_square_intervalIntegrable.trans
          frontierStoppedLogCupOptimizer_tail_square_intervalIntegrable)]
    _ = (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
          frontierStoppedLogCupOptimizer t ^ 2) +
        ((∫ t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
          frontierStoppedLogCupOptimizer t ^ 2) +
        (∫ t in frontierStoppedLogCupRatio..1,
          frontierStoppedLogCupOptimizer t ^ 2)) := by
      rw [intervalIntegral.integral_add_adjacent_intervals
        frontierStoppedLogCupOptimizer_middle_square_intervalIntegrable
        frontierStoppedLogCupOptimizer_tail_square_intervalIntegrable]
    _ = (1 / 12 : ℝ) := by
      rw [frontierStoppedLogCupOptimizer_left_square_integral,
        frontierStoppedLogCupOptimizer_middle_square_integral,
        frontierStoppedLogCupOptimizer_tail_square_integral,
        frontierStoppedLogCup_log_one_div_ratio, ← frontierEpsilon_sq]
      field_simp [frontierEpsilon_ne_zero]
      ring

theorem frontierStoppedLogCupOptimizer_centered_core_obligations :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume (0 : ℝ) 1 ∧
      IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
        volume (0 : ℝ) 1 ∧
      IntervalIntegrable
        (fun t : ℝ ↦ frontierPhi (frontierStoppedLogCupOptimizer t))
          volume (0 : ℝ) 1 ∧
      frontierBMOOriginalMeanIntegral frontierStoppedLogCupOptimizer = 0 ∧
      frontierBMOOriginalSecondMomentIntegral frontierStoppedLogCupOptimizer =
        (1 / 12 : ℝ) := by
  exact ⟨frontierStoppedLogCupOptimizer_intervalIntegrable,
    frontierStoppedLogCupOptimizer_square_intervalIntegrable,
    frontierPhi_stoppedLogCupOptimizer_intervalIntegrable,
    frontierStoppedLogCupOptimizer_meanIntegral,
    frontierStoppedLogCupOptimizer_secondMomentIntegral⟩

theorem frontierBMOIntervalVariance_eq_secondMoment_sub_mean_sq
    {g : ℝ → ℝ} {a b : ℝ} (hab : a < b)
    (hg : IntervalIntegrable g volume a b)
    (hg2 : IntervalIntegrable (fun t : ℝ ↦ g t ^ 2) volume a b) :
    frontierBMOIntervalVariance g a b =
      (∫ t in a..b, g t ^ 2) / (b - a) -
        (frontierBMOIntervalMean g a b) ^ 2 := by
  have hne : b - a ≠ 0 := by linarith
  let m := frontierBMOIntervalMean g a b
  have hlin : IntervalIntegrable (fun t : ℝ ↦ (2 * m) * g t) volume a b :=
    hg.const_mul (2 * m)
  have hsum :
      IntervalIntegrable (fun t : ℝ ↦ g t ^ 2 - (2 * m) * g t) volume a b :=
    hg2.sub hlin
  have hcentered :
      (∫ t in a..b, (g t - m) ^ 2) =
        (∫ t in a..b, g t ^ 2) -
          (2 * m) * (∫ t in a..b, g t) +
          (b - a) * m ^ 2 := by
    calc
      (∫ t in a..b, (g t - m) ^ 2) =
          ∫ t in a..b, (g t ^ 2 - (2 * m) * g t) + m ^ 2 := by
        apply intervalIntegral.integral_congr
        intro t _ht
        ring
      _ = (∫ t in a..b, g t ^ 2) -
          (2 * m) * (∫ t in a..b, g t) +
          (b - a) * m ^ 2 := by
        rw [intervalIntegral.integral_add hsum intervalIntegrable_const]
        rw [intervalIntegral.integral_sub hg2 hlin]
        rw [intervalIntegral.integral_const_mul]
        rw [intervalIntegral.integral_const]
        rw [smul_eq_mul]
  rw [frontierBMOIntervalVariance]
  change (∫ t in a..b, (g t - m) ^ 2) / (b - a) =
    (∫ t in a..b, g t ^ 2) / (b - a) - m ^ 2
  rw [hcentered]
  subst m
  rw [frontierBMOIntervalMean]
  field_simp [hne]
  ring

theorem frontierBMOCenteredAdmissible_unit_intervalMean_eq_zero
    (g : ℝ → ℝ) (hg : frontierBMOCenteredFunctionAdmissible g) :
    frontierBMOIntervalMean g (0 : ℝ) 1 = 0 := by
  rcases hg with ⟨_hg, _hg2, _hphi, hmean, _hsecondMoment, _hvariance⟩
  rw [frontierBMOIntervalMean]
  rw [← frontierBMOOriginalMeanIntegral, hmean]
  norm_num

theorem frontierBMOCenteredAdmissible_unit_secondMoment_eq
    (g : ℝ → ℝ) (hg : frontierBMOCenteredFunctionAdmissible g) :
    (∫ t in (0 : ℝ)..1, (g t) ^ 2) = (1 / 12 : ℝ) := by
  rcases hg with ⟨_hg, _hg2, _hphi, _hmean, hsecondMoment, _hvariance⟩
  simpa [frontierBMOOriginalSecondMomentIntegral] using hsecondMoment

theorem frontierBMOCenteredAdmissible_unit_intervalVariance_eq
    (g : ℝ → ℝ) (hg : frontierBMOCenteredFunctionAdmissible g) :
    frontierBMOIntervalVariance g (0 : ℝ) 1 = (1 / 12 : ℝ) := by
  rcases hg with ⟨hg_int, hg2_int, hphi, hmean, hsecondMoment, hvariance⟩
  have hg_adm : frontierBMOCenteredFunctionAdmissible g :=
    ⟨hg_int, hg2_int, hphi, hmean, hsecondMoment, hvariance⟩
  rw [frontierBMOIntervalVariance_eq_secondMoment_sub_mean_sq
    (by norm_num : (0 : ℝ) < 1) hg_int hg2_int]
  rw [frontierBMOCenteredAdmissible_unit_intervalMean_eq_zero g hg_adm]
  rw [frontierBMOCenteredAdmissible_unit_secondMoment_eq g hg_adm]
  norm_num

theorem frontierStoppedLogCupOptimizer_left_plateau_intervalIntegral
    {a b : ℝ} (hab : a < b) (hb : b ≤ frontierStoppedLogCupRatio / 2) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
      (b - a) * (frontierCStar + frontierEpsilon) := by
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
        ∫ _t in a..b, frontierCStar + frontierEpsilon := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne (frontierStoppedLogCupRatio / 2)] with t hne ht
      rw [Set.uIoc_of_le (le_of_lt hab)] at ht
      have hlt : t < frontierStoppedLogCupRatio / 2 := by
        exact lt_of_le_of_ne (le_trans ht.2 hb) hne
      exact frontierStoppedLogCupOptimizer_left hlt
    _ = (b - a) * (frontierCStar + frontierEpsilon) := by
      rw [intervalIntegral.integral_const]
      simp

theorem frontierStoppedLogCupOptimizer_left_plateau_intervalIntegrable
    {a b : ℝ} (hab : a < b) (hb : b ≤ frontierStoppedLogCupRatio / 2) :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume a b := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
  have hconst :
      IntegrableOn (fun _ : ℝ ↦ frontierCStar + frontierEpsilon)
        (Set.Ioo a b) volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  symm
  exact frontierStoppedLogCupOptimizer_left (lt_of_lt_of_le ht.2 hb)

theorem frontierStoppedLogCupOptimizer_left_plateau_intervalMean
    {a b : ℝ} (hab : a < b) (hb : b ≤ frontierStoppedLogCupRatio / 2) :
    frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b =
      frontierCStar + frontierEpsilon := by
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalMean,
    frontierStoppedLogCupOptimizer_left_plateau_intervalIntegral hab hb]
  field_simp [hne]

theorem frontierStoppedLogCupOptimizer_left_plateau_centeredSquare_intervalIntegrable
    {a b : ℝ} (hab : a < b) (hb : b ≤ frontierStoppedLogCupRatio / 2) :
    IntervalIntegrable
      (fun t ↦
        (frontierStoppedLogCupOptimizer t -
          frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
      volume a b := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
  have hzero :
      IntegrableOn (fun _ : ℝ ↦ (0 : ℝ)) (Set.Ioo a b) volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
    exact intervalIntegrable_const
  refine hzero.congr_fun ?_ measurableSet_Ioo
  intro t ht
  rw [frontierStoppedLogCupOptimizer_left_plateau_intervalMean hab hb]
  have hlt : t < frontierStoppedLogCupRatio / 2 := lt_of_lt_of_le ht.2 hb
  change (0 : ℝ) =
    (frontierStoppedLogCupOptimizer t - (frontierCStar + frontierEpsilon)) ^ 2
  rw [frontierStoppedLogCupOptimizer_left hlt]
  ring

theorem frontierStoppedLogCupOptimizer_left_plateau_intervalVariance
    {a b : ℝ} (hab : a < b) (hb : b ≤ frontierStoppedLogCupRatio / 2) :
    frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b = 0 := by
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalVariance,
    frontierStoppedLogCupOptimizer_left_plateau_intervalMean hab hb]
  have hintegral :
      (∫ t in a..b,
          (frontierStoppedLogCupOptimizer t -
            (frontierCStar + frontierEpsilon)) ^ 2) = 0 := by
    calc
      (∫ t in a..b,
          (frontierStoppedLogCupOptimizer t -
            (frontierCStar + frontierEpsilon)) ^ 2) =
          ∫ _t in a..b, (0 : ℝ) := by
        apply intervalIntegral.integral_congr_ae
        filter_upwards [volume.ae_ne (frontierStoppedLogCupRatio / 2)] with t hne' ht
        rw [Set.uIoc_of_le (le_of_lt hab)] at ht
        have hlt : t < frontierStoppedLogCupRatio / 2 := by
          exact lt_of_le_of_ne (le_trans ht.2 hb) hne'
        rw [frontierStoppedLogCupOptimizer_left hlt]
        ring
      _ = 0 := by simp
  rw [hintegral]
  field_simp [hne]
  ring

theorem frontierStoppedLogCupOptimizer_left_plateau_intervalVariance_obligation
    {a b : ℝ} (hab : a < b) (hb : b ≤ frontierStoppedLogCupRatio / 2) :
    IntervalIntegrable
        (fun t ↦
          (frontierStoppedLogCupOptimizer t -
            frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b ≤
        (1 / 12 : ℝ) := by
  refine ⟨frontierStoppedLogCupOptimizer_left_plateau_centeredSquare_intervalIntegrable
      hab hb, ?_⟩
  rw [frontierStoppedLogCupOptimizer_left_plateau_intervalVariance hab hb]
  norm_num

theorem frontierStoppedLogCupOptimizer_left_plateau_square_intervalIntegral
    {a b : ℝ} (hab : a < b) (hb : b ≤ frontierStoppedLogCupRatio / 2) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
      (b - a) * (frontierCStar + frontierEpsilon) ^ 2 := by
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
        ∫ _t in a..b, (frontierCStar + frontierEpsilon) ^ 2 := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne (frontierStoppedLogCupRatio / 2)] with t hne ht
      rw [Set.uIoc_of_le (le_of_lt hab)] at ht
      have hlt : t < frontierStoppedLogCupRatio / 2 := by
        exact lt_of_le_of_ne (le_trans ht.2 hb) hne
      exact frontierStoppedLogCupOptimizer_left_square hlt
    _ = (b - a) * (frontierCStar + frontierEpsilon) ^ 2 := by
      rw [intervalIntegral.integral_const]
      simp

theorem frontierStoppedLogCupOptimizer_left_plateau_square_intervalIntegrable
    {a b : ℝ} (hab : a < b) (hb : b ≤ frontierStoppedLogCupRatio / 2) :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume a b := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
  have hconst :
      IntegrableOn (fun _ : ℝ ↦ (frontierCStar + frontierEpsilon) ^ 2)
        (Set.Ioo a b) volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  symm
  exact frontierStoppedLogCupOptimizer_left_square (lt_of_lt_of_le ht.2 hb)

theorem frontierStoppedLogCupOptimizer_middle_plateau_intervalIntegral
    {a b : ℝ} (hab : a < b)
    (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
      (b - a) * (frontierCStar - frontierEpsilon) := by
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
        ∫ _t in a..b, frontierCStar - frontierEpsilon := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne frontierStoppedLogCupRatio] with t hne ht
      rw [Set.uIoc_of_le (le_of_lt hab)] at ht
      have hleft : frontierStoppedLogCupRatio / 2 ≤ t := le_trans ha (le_of_lt ht.1)
      have hright : t < frontierStoppedLogCupRatio := lt_of_le_of_ne
        (le_trans ht.2 hb) hne
      exact frontierStoppedLogCupOptimizer_middle hleft hright
    _ = (b - a) * (frontierCStar - frontierEpsilon) := by
      rw [intervalIntegral.integral_const]
      simp

theorem frontierStoppedLogCupOptimizer_middle_plateau_intervalIntegrable
    {a b : ℝ} (hab : a < b)
    (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume a b := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
  have hconst :
      IntegrableOn (fun _ : ℝ ↦ frontierCStar - frontierEpsilon)
        (Set.Ioo a b) volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  symm
  exact frontierStoppedLogCupOptimizer_middle
    (le_trans ha (le_of_lt ht.1)) (lt_of_lt_of_le ht.2 hb)

theorem frontierStoppedLogCupOptimizer_middle_plateau_intervalMean
    {a b : ℝ} (hab : a < b)
    (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b =
      frontierCStar - frontierEpsilon := by
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalMean,
    frontierStoppedLogCupOptimizer_middle_plateau_intervalIntegral hab ha hb]
  field_simp [hne]

theorem frontierStoppedLogCupOptimizer_middle_plateau_centeredSquare_intervalIntegrable
    {a b : ℝ} (hab : a < b)
    (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    IntervalIntegrable
      (fun t ↦
        (frontierStoppedLogCupOptimizer t -
          frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
      volume a b := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
  have hzero :
      IntegrableOn (fun _ : ℝ ↦ (0 : ℝ)) (Set.Ioo a b) volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
    exact intervalIntegrable_const
  refine hzero.congr_fun ?_ measurableSet_Ioo
  intro t ht
  rw [frontierStoppedLogCupOptimizer_middle_plateau_intervalMean hab ha hb]
  have hleft : frontierStoppedLogCupRatio / 2 ≤ t := le_trans ha (le_of_lt ht.1)
  have hright : t < frontierStoppedLogCupRatio := lt_of_lt_of_le ht.2 hb
  change (0 : ℝ) =
    (frontierStoppedLogCupOptimizer t - (frontierCStar - frontierEpsilon)) ^ 2
  rw [frontierStoppedLogCupOptimizer_middle hleft hright]
  ring

theorem frontierStoppedLogCupOptimizer_middle_plateau_intervalVariance
    {a b : ℝ} (hab : a < b)
    (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b = 0 := by
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalVariance,
    frontierStoppedLogCupOptimizer_middle_plateau_intervalMean hab ha hb]
  have hintegral :
      (∫ t in a..b,
          (frontierStoppedLogCupOptimizer t -
            (frontierCStar - frontierEpsilon)) ^ 2) = 0 := by
    calc
      (∫ t in a..b,
          (frontierStoppedLogCupOptimizer t -
            (frontierCStar - frontierEpsilon)) ^ 2) =
          ∫ _t in a..b, (0 : ℝ) := by
        apply intervalIntegral.integral_congr_ae
        filter_upwards [volume.ae_ne frontierStoppedLogCupRatio] with t hne' ht
        rw [Set.uIoc_of_le (le_of_lt hab)] at ht
        have hleft : frontierStoppedLogCupRatio / 2 ≤ t :=
          le_trans ha (le_of_lt ht.1)
        have hright : t < frontierStoppedLogCupRatio := lt_of_le_of_ne
          (le_trans ht.2 hb) hne'
        rw [frontierStoppedLogCupOptimizer_middle hleft hright]
        ring
      _ = 0 := by simp
  rw [hintegral]
  field_simp [hne]
  ring

theorem frontierStoppedLogCupOptimizer_middle_plateau_intervalVariance_obligation
    {a b : ℝ} (hab : a < b)
    (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    IntervalIntegrable
        (fun t ↦
          (frontierStoppedLogCupOptimizer t -
            frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b ≤
        (1 / 12 : ℝ) := by
  refine ⟨frontierStoppedLogCupOptimizer_middle_plateau_centeredSquare_intervalIntegrable
      hab ha hb, ?_⟩
  rw [frontierStoppedLogCupOptimizer_middle_plateau_intervalVariance hab ha hb]
  norm_num

theorem frontierStoppedLogCupOptimizer_middle_plateau_square_intervalIntegral
    {a b : ℝ} (hab : a < b)
    (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
      (b - a) * (frontierCStar - frontierEpsilon) ^ 2 := by
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
        ∫ _t in a..b, (frontierCStar - frontierEpsilon) ^ 2 := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne frontierStoppedLogCupRatio] with t hne ht
      rw [Set.uIoc_of_le (le_of_lt hab)] at ht
      have hleft : frontierStoppedLogCupRatio / 2 ≤ t :=
        le_trans ha (le_of_lt ht.1)
      have hright : t < frontierStoppedLogCupRatio := lt_of_le_of_ne
        (le_trans ht.2 hb) hne
      exact frontierStoppedLogCupOptimizer_middle_square hleft hright
    _ = (b - a) * (frontierCStar - frontierEpsilon) ^ 2 := by
      rw [intervalIntegral.integral_const]
      simp

theorem frontierStoppedLogCupOptimizer_middle_plateau_square_intervalIntegrable
    {a b : ℝ} (hab : a < b)
    (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume a b := by
  rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
  have hconst :
      IntegrableOn (fun _ : ℝ ↦ (frontierCStar - frontierEpsilon) ^ 2)
        (Set.Ioo a b) volume := by
    rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hab)]
    exact intervalIntegrable_const
  refine hconst.congr_fun ?_ measurableSet_Ioo
  intro t ht
  symm
  exact frontierStoppedLogCupOptimizer_middle_square
    (le_trans ha (le_of_lt ht.1)) (lt_of_lt_of_le ht.2 hb)

theorem frontierStoppedLogCupOptimizer_left_middle_intervalIntegral
    {a b : ℝ} (ha : a < frontierStoppedLogCupRatio / 2)
    (hmiddle : frontierStoppedLogCupRatio / 2 < b)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
      (frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) +
        (b - frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) := by
  have hleft :
      IntervalIntegrable frontierStoppedLogCupOptimizer volume
        a (frontierStoppedLogCupRatio / 2) :=
    frontierStoppedLogCupOptimizer_left_plateau_intervalIntegrable ha le_rfl
  have hright :
      IntervalIntegrable frontierStoppedLogCupOptimizer volume
        (frontierStoppedLogCupRatio / 2) b :=
    frontierStoppedLogCupOptimizer_middle_plateau_intervalIntegrable
      hmiddle le_rfl hb
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
        (∫ t in a..frontierStoppedLogCupRatio / 2,
          frontierStoppedLogCupOptimizer t) +
        (∫ t in frontierStoppedLogCupRatio / 2..b,
          frontierStoppedLogCupOptimizer t) := by
      rw [intervalIntegral.integral_add_adjacent_intervals hleft hright]
    _ = (frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) +
        (b - frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) := by
      rw [frontierStoppedLogCupOptimizer_left_plateau_intervalIntegral ha le_rfl,
        frontierStoppedLogCupOptimizer_middle_plateau_intervalIntegral
          hmiddle le_rfl hb]

theorem frontierStoppedLogCupOptimizer_left_middle_square_intervalIntegral
    {a b : ℝ} (ha : a < frontierStoppedLogCupRatio / 2)
    (hmiddle : frontierStoppedLogCupRatio / 2 < b)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
      (frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) ^ 2 +
        (b - frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) ^ 2 := by
  have hleft :
      IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
        volume a (frontierStoppedLogCupRatio / 2) :=
    frontierStoppedLogCupOptimizer_left_plateau_square_intervalIntegrable ha le_rfl
  have hright :
      IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
        volume (frontierStoppedLogCupRatio / 2) b :=
    frontierStoppedLogCupOptimizer_middle_plateau_square_intervalIntegrable
      hmiddle le_rfl hb
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
        (∫ t in a..frontierStoppedLogCupRatio / 2,
          frontierStoppedLogCupOptimizer t ^ 2) +
        (∫ t in frontierStoppedLogCupRatio / 2..b,
          frontierStoppedLogCupOptimizer t ^ 2) := by
      rw [intervalIntegral.integral_add_adjacent_intervals hleft hright]
    _ = (frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) ^ 2 +
        (b - frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) ^ 2 := by
      rw [frontierStoppedLogCupOptimizer_left_plateau_square_intervalIntegral
          ha le_rfl,
        frontierStoppedLogCupOptimizer_middle_plateau_square_intervalIntegral
          hmiddle le_rfl hb]

theorem frontierStoppedLogCupOptimizer_left_middle_intervalMean
    {a b : ℝ} (ha : a < frontierStoppedLogCupRatio / 2)
    (hmiddle : frontierStoppedLogCupRatio / 2 < b)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b =
      ((frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) +
        (b - frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon)) / (b - a) := by
  have hab : a < b := lt_trans ha hmiddle
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalMean,
    frontierStoppedLogCupOptimizer_left_middle_intervalIntegral ha hmiddle hb]

theorem frontierStoppedLogCupOptimizer_left_middle_intervalIntegrable
    {a b : ℝ} (ha : a < frontierStoppedLogCupRatio / 2)
    (hmiddle : frontierStoppedLogCupRatio / 2 < b)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume a b :=
  (frontierStoppedLogCupOptimizer_left_plateau_intervalIntegrable ha le_rfl).trans
    (frontierStoppedLogCupOptimizer_middle_plateau_intervalIntegrable
      hmiddle le_rfl hb)

theorem frontierStoppedLogCupOptimizer_left_middle_square_intervalIntegrable
    {a b : ℝ} (ha : a < frontierStoppedLogCupRatio / 2)
    (hmiddle : frontierStoppedLogCupRatio / 2 < b)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume a b :=
  (frontierStoppedLogCupOptimizer_left_plateau_square_intervalIntegrable
      ha le_rfl).trans
    (frontierStoppedLogCupOptimizer_middle_plateau_square_intervalIntegrable
      hmiddle le_rfl hb)

theorem frontierStoppedLogCupOptimizer_left_middle_centeredSquare_intervalIntegrable
    {a b : ℝ} (ha : a < frontierStoppedLogCupRatio / 2)
    (hmiddle : frontierStoppedLogCupRatio / 2 < b)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    IntervalIntegrable
      (fun t ↦
        (frontierStoppedLogCupOptimizer t -
          frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
      volume a b := by
  let m := frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b
  have hleft :
      IntervalIntegrable (fun t ↦ (frontierStoppedLogCupOptimizer t - m) ^ 2)
        volume a (frontierStoppedLogCupRatio / 2) := by
    rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt ha)]
    have hconst :
        IntegrableOn
          (fun _ : ℝ ↦ ((frontierCStar + frontierEpsilon) - m) ^ 2)
          (Set.Ioo a (frontierStoppedLogCupRatio / 2)) volume := by
      rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt ha)]
      exact intervalIntegrable_const
    refine hconst.congr_fun ?_ measurableSet_Ioo
    intro t ht
    change ((frontierCStar + frontierEpsilon) - m) ^ 2 =
      (frontierStoppedLogCupOptimizer t - m) ^ 2
    rw [frontierStoppedLogCupOptimizer_left ht.2]
  have hright :
      IntervalIntegrable (fun t ↦ (frontierStoppedLogCupOptimizer t - m) ^ 2)
        volume (frontierStoppedLogCupRatio / 2) b := by
    rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hmiddle)]
    have hconst :
        IntegrableOn
          (fun _ : ℝ ↦ ((frontierCStar - frontierEpsilon) - m) ^ 2)
          (Set.Ioo (frontierStoppedLogCupRatio / 2) b) volume := by
      rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hmiddle)]
      exact intervalIntegrable_const
    refine hconst.congr_fun ?_ measurableSet_Ioo
    intro t ht
    change ((frontierCStar - frontierEpsilon) - m) ^ 2 =
      (frontierStoppedLogCupOptimizer t - m) ^ 2
    rw [frontierStoppedLogCupOptimizer_middle (le_of_lt ht.1)
      (lt_of_lt_of_le ht.2 hb)]
  exact hleft.trans hright

theorem frontierStoppedLogCupOptimizer_left_middle_intervalVariance
    {a b : ℝ} (ha : a < frontierStoppedLogCupRatio / 2)
    (hmiddle : frontierStoppedLogCupRatio / 2 < b)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b =
      frontierEpsilon ^ 2 *
        (4 * (frontierStoppedLogCupRatio / 2 - a) *
          (b - frontierStoppedLogCupRatio / 2) / (b - a) ^ 2) := by
  have hab : a < b := lt_trans ha hmiddle
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalVariance_eq_secondMoment_sub_mean_sq hab
      (frontierStoppedLogCupOptimizer_left_middle_intervalIntegrable ha hmiddle hb)
      (frontierStoppedLogCupOptimizer_left_middle_square_intervalIntegrable
        ha hmiddle hb),
    frontierStoppedLogCupOptimizer_left_middle_square_intervalIntegral
      ha hmiddle hb,
    frontierStoppedLogCupOptimizer_left_middle_intervalMean ha hmiddle hb]
  field_simp [hne]
  ring

theorem frontierStoppedLogCupOptimizer_left_middle_intervalVariance_obligation
    {a b : ℝ} (ha : a < frontierStoppedLogCupRatio / 2)
    (hmiddle : frontierStoppedLogCupRatio / 2 < b)
    (hb : b ≤ frontierStoppedLogCupRatio) :
    IntervalIntegrable
        (fun t ↦
          (frontierStoppedLogCupOptimizer t -
            frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b ≤
        (1 / 12 : ℝ) := by
  refine ⟨frontierStoppedLogCupOptimizer_left_middle_centeredSquare_intervalIntegrable
      ha hmiddle hb, ?_⟩
  rw [frontierStoppedLogCupOptimizer_left_middle_intervalVariance ha hmiddle hb,
    frontierEpsilon_sq]
  have hden_pos : 0 < (b - a) ^ 2 := by
    exact sq_pos_of_ne_zero (by linarith [lt_trans ha hmiddle])
  have hfour :
      4 * (frontierStoppedLogCupRatio / 2 - a) *
          (b - frontierStoppedLogCupRatio / 2) ≤
        (b - a) ^ 2 := by
    nlinarith [sq_nonneg
      ((frontierStoppedLogCupRatio / 2 - a) -
        (b - frontierStoppedLogCupRatio / 2))]
  have hratio :
      4 * (frontierStoppedLogCupRatio / 2 - a) *
          (b - frontierStoppedLogCupRatio / 2) / (b - a) ^ 2 ≤
        (1 : ℝ) := by
    calc
      4 * (frontierStoppedLogCupRatio / 2 - a) *
          (b - frontierStoppedLogCupRatio / 2) / (b - a) ^ 2 ≤
          (b - a) ^ 2 / (b - a) ^ 2 := by
        exact div_le_div_of_nonneg_right hfour (le_of_lt hden_pos)
      _ = (1 : ℝ) := by
        have hba_ne : b - a ≠ 0 := by linarith [lt_trans ha hmiddle]
        field_simp [hba_ne]
  calc
    (1 / 12 : ℝ) *
        (4 * (frontierStoppedLogCupRatio / 2 - a) *
          (b - frontierStoppedLogCupRatio / 2) / (b - a) ^ 2) ≤
        (1 / 12 : ℝ) * 1 := by
      exact mul_le_mul_of_nonneg_left hratio (by norm_num)
    _ = (1 / 12 : ℝ) := by ring

theorem frontierStoppedLogCup_logMinusOne_interval_integral
    {a b : ℝ} (ha : 0 < a) (hab : a < b) :
    (∫ t in a..b, (Real.log (1 / t) - 1)) =
      b * Real.log (1 / b) - a * Real.log (1 / a) := by
  have hderiv :
      ∀ x ∈ [[a, b]],
        HasDerivAt (fun t : ℝ ↦ t * Real.log (1 / t))
          (Real.log (1 / x) - 1) x := by
    intro x hx
    rw [Set.uIcc_of_le (le_of_lt hab)] at hx
    exact frontier_hasDerivAt_mul_log_one_div
      (ne_of_gt (lt_of_lt_of_le ha hx.1))
  have hint :
      IntervalIntegrable (fun t : ℝ ↦ Real.log (1 / t) - 1) volume a b := by
    have hcont :
        ContinuousOn (fun t : ℝ ↦ Real.log (1 / t) - 1) [[a, b]] := by
      have hinv : ContinuousOn (fun t : ℝ ↦ 1 / t) [[a, b]] := by
        exact continuousOn_const.div continuousOn_id (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt hab)] at ht
          exact ne_of_gt (lt_of_lt_of_le ha ht.1))
      exact (hinv.log (by
        intro t ht
        rw [Set.uIcc_of_le (le_of_lt hab)] at ht
        exact one_div_ne_zero (ne_of_gt (lt_of_lt_of_le ha ht.1)))).sub
          continuousOn_const
    exact hcont.intervalIntegrable
  calc
    (∫ t in a..b, (Real.log (1 / t) - 1)) =
        b * Real.log (1 / b) - a * Real.log (1 / a) := by
      simpa using intervalIntegral.integral_eq_sub_of_hasDerivAt hderiv hint

theorem frontierStoppedLogCup_logMinusOne_sq_interval_integral
    {a b : ℝ} (ha : 0 < a) (hab : a < b) :
    (∫ t in a..b, (Real.log (1 / t) - 1) ^ 2) =
      b * ((Real.log (1 / b)) ^ 2 + 1) -
        a * ((Real.log (1 / a)) ^ 2 + 1) := by
  have hderiv :
      ∀ x ∈ [[a, b]],
        HasDerivAt
          (fun t : ℝ ↦ t * ((Real.log (1 / t)) ^ 2 + 1))
          ((Real.log (1 / x) - 1) ^ 2) x := by
    intro x hx
    rw [Set.uIcc_of_le (le_of_lt hab)] at hx
    exact frontier_hasDerivAt_log_one_div_sq_antiderivative
      (ne_of_gt (lt_of_lt_of_le ha hx.1))
  have hint :
      IntervalIntegrable (fun t : ℝ ↦ (Real.log (1 / t) - 1) ^ 2)
        volume a b := by
    have hcont :
        ContinuousOn (fun t : ℝ ↦ (Real.log (1 / t) - 1) ^ 2) [[a, b]] := by
      have hinv : ContinuousOn (fun t : ℝ ↦ 1 / t) [[a, b]] := by
        exact continuousOn_const.div continuousOn_id (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt hab)] at ht
          exact ne_of_gt (lt_of_lt_of_le ha ht.1))
      have hlog : ContinuousOn (fun t : ℝ ↦ Real.log (1 / t)) [[a, b]] := by
        exact hinv.log (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt hab)] at ht
          exact one_div_ne_zero (ne_of_gt (lt_of_lt_of_le ha ht.1)))
      exact (hlog.sub continuousOn_const).pow 2
    exact hcont.intervalIntegrable
  simpa using intervalIntegral.integral_eq_sub_of_hasDerivAt hderiv hint

theorem frontierStoppedLogCupOptimizer_tail_restricted_continuousOn
    {a b : ℝ} (hab : a < b) (ha : frontierStoppedLogCupRatio ≤ a)
    (hb : b ≤ 1) :
    ContinuousOn frontierStoppedLogCupOptimizer [[a, b]] := by
  refine frontierStoppedLogCupOptimizer_tail_continuousOn.mono ?_
  intro t ht
  rw [Set.uIcc_of_le (le_of_lt hab)] at ht
  rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)]
  exact ⟨le_trans ha ht.1, le_trans ht.2 hb⟩

theorem frontierStoppedLogCupOptimizer_tail_restricted_intervalIntegrable
    {a b : ℝ} (hab : a < b) (ha : frontierStoppedLogCupRatio ≤ a)
    (hb : b ≤ 1) :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume a b := by
  exact (frontierStoppedLogCupOptimizer_tail_restricted_continuousOn
    hab ha hb).intervalIntegrable

theorem frontierStoppedLogCupOptimizer_tail_restricted_square_intervalIntegrable
    {a b : ℝ} (hab : a < b) (ha : frontierStoppedLogCupRatio ≤ a)
    (hb : b ≤ 1) :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume a b := by
  exact ((frontierStoppedLogCupOptimizer_tail_restricted_continuousOn
    hab ha hb).pow 2).intervalIntegrable

theorem frontierStoppedLogCupOptimizer_tail_intervalIntegral
    {a b : ℝ} (hab : a < b) (ha : frontierStoppedLogCupRatio ≤ a) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
      frontierEpsilon *
        (b * Real.log (1 / b) - a * Real.log (1 / a)) := by
  have hapos : 0 < a := lt_of_lt_of_le frontierStoppedLogCupRatio_pos ha
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
        ∫ t in a..b, frontierEpsilon * (Real.log (1 / t) - 1) := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards with t ht
      rw [Set.uIoc_of_le (le_of_lt hab)] at ht
      exact frontierStoppedLogCupOptimizer_tail (le_trans ha (le_of_lt ht.1))
    _ = frontierEpsilon *
        (∫ t in a..b, (Real.log (1 / t) - 1)) := by
      rw [intervalIntegral.integral_const_mul]
    _ = frontierEpsilon *
        (b * Real.log (1 / b) - a * Real.log (1 / a)) := by
      rw [frontierStoppedLogCup_logMinusOne_interval_integral hapos hab]

theorem frontierStoppedLogCupOptimizer_tail_square_intervalIntegral
    {a b : ℝ} (hab : a < b) (ha : frontierStoppedLogCupRatio ≤ a) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
      frontierEpsilon ^ 2 *
        (b * ((Real.log (1 / b)) ^ 2 + 1) -
          a * ((Real.log (1 / a)) ^ 2 + 1)) := by
  have hapos : 0 < a := lt_of_lt_of_le frontierStoppedLogCupRatio_pos ha
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
        ∫ t in a..b, frontierEpsilon ^ 2 * (Real.log (1 / t) - 1) ^ 2 := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards with t ht
      rw [Set.uIoc_of_le (le_of_lt hab)] at ht
      exact frontierStoppedLogCupOptimizer_tail_square
        (le_trans ha (le_of_lt ht.1))
    _ = frontierEpsilon ^ 2 *
        (∫ t in a..b, (Real.log (1 / t) - 1) ^ 2) := by
      rw [intervalIntegral.integral_const_mul]
    _ = frontierEpsilon ^ 2 *
        (b * ((Real.log (1 / b)) ^ 2 + 1) -
          a * ((Real.log (1 / a)) ^ 2 + 1)) := by
      rw [frontierStoppedLogCup_logMinusOne_sq_interval_integral hapos hab]

theorem frontierStoppedLogCupOptimizer_tail_intervalMean
    {a b : ℝ} (hab : a < b) (ha : frontierStoppedLogCupRatio ≤ a) :
    frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b =
      frontierEpsilon *
        (b * Real.log (1 / b) - a * Real.log (1 / a)) / (b - a) := by
  have hne : b - a ≠ 0 := by linarith
  rw [frontierBMOIntervalMean,
    frontierStoppedLogCupOptimizer_tail_intervalIntegral hab ha]

theorem frontierStoppedLogCupOptimizer_tail_centeredSquare_intervalIntegrable
    {a b : ℝ} (hab : a < b) (ha : frontierStoppedLogCupRatio ≤ a)
    (hb : b ≤ 1) :
    IntervalIntegrable
      (fun t ↦
        (frontierStoppedLogCupOptimizer t -
          frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
      volume a b := by
  exact (((frontierStoppedLogCupOptimizer_tail_restricted_continuousOn
    hab ha hb).sub continuousOn_const).pow 2).intervalIntegrable

theorem frontierStoppedLogCupOptimizer_tail_intervalVariance
    {a b : ℝ} (hab : a < b) (ha : frontierStoppedLogCupRatio ≤ a)
    (hb : b ≤ 1) :
    frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b =
      frontierEpsilon ^ 2 *
        (1 -
          a * b * (Real.log (1 / a) - Real.log (1 / b)) ^ 2 /
            (b - a) ^ 2) := by
  have hne : b - a ≠ 0 := by linarith
  have hg :
      IntervalIntegrable frontierStoppedLogCupOptimizer volume a b :=
    frontierStoppedLogCupOptimizer_tail_restricted_intervalIntegrable hab ha hb
  have hg2 :
      IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
        volume a b :=
    frontierStoppedLogCupOptimizer_tail_restricted_square_intervalIntegrable
      hab ha hb
  let m := frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b
  have hlin :
      IntervalIntegrable (fun t : ℝ ↦ (2 * m) * frontierStoppedLogCupOptimizer t)
        volume a b := hg.const_mul (2 * m)
  have hsum :
      IntervalIntegrable
        (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2 -
          (2 * m) * frontierStoppedLogCupOptimizer t)
        volume a b := hg2.sub hlin
  have hcentered :
      (∫ t in a..b, (frontierStoppedLogCupOptimizer t - m) ^ 2) =
        (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) -
          (2 * m) * (∫ t in a..b, frontierStoppedLogCupOptimizer t) +
          (b - a) * m ^ 2 := by
    calc
      (∫ t in a..b, (frontierStoppedLogCupOptimizer t - m) ^ 2) =
          ∫ t in a..b,
            (frontierStoppedLogCupOptimizer t ^ 2 -
              (2 * m) * frontierStoppedLogCupOptimizer t) + m ^ 2 := by
        apply intervalIntegral.integral_congr
        intro t _ht
        ring
      _ = (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) -
          (2 * m) * (∫ t in a..b, frontierStoppedLogCupOptimizer t) +
          (b - a) * m ^ 2 := by
        rw [intervalIntegral.integral_add hsum intervalIntegrable_const]
        rw [intervalIntegral.integral_sub hg2 hlin]
        rw [intervalIntegral.integral_const_mul]
        rw [intervalIntegral.integral_const]
        rw [smul_eq_mul]
  rw [frontierBMOIntervalVariance]
  change (∫ t in a..b, (frontierStoppedLogCupOptimizer t - m) ^ 2) /
      (b - a) =
    frontierEpsilon ^ 2 *
      (1 -
        a * b * (Real.log (1 / a) - Real.log (1 / b)) ^ 2 / (b - a) ^ 2)
  rw [hcentered, frontierStoppedLogCupOptimizer_tail_square_intervalIntegral hab ha,
    frontierStoppedLogCupOptimizer_tail_intervalIntegral hab ha]
  rw [show m =
      frontierEpsilon *
        (b * Real.log (1 / b) - a * Real.log (1 / a)) / (b - a) by
    exact frontierStoppedLogCupOptimizer_tail_intervalMean hab ha]
  field_simp [hne]
  ring

theorem frontierStoppedLogCupOptimizer_tail_intervalVariance_obligation
    {a b : ℝ} (hab : a < b) (ha : frontierStoppedLogCupRatio ≤ a)
    (hb : b ≤ 1) :
    IntervalIntegrable
        (fun t ↦
          (frontierStoppedLogCupOptimizer t -
            frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b ≤
        (1 / 12 : ℝ) := by
  refine ⟨frontierStoppedLogCupOptimizer_tail_centeredSquare_intervalIntegrable
      hab ha hb, ?_⟩
  rw [frontierStoppedLogCupOptimizer_tail_intervalVariance hab ha hb,
    frontierEpsilon_sq]
  have hapos : 0 < a := lt_of_lt_of_le frontierStoppedLogCupRatio_pos ha
  have hbpos : 0 < b := lt_trans hapos hab
  have hden_nonneg : 0 ≤ (b - a) ^ 2 := sq_nonneg (b - a)
  have hden_pos : 0 < (b - a) ^ 2 := sq_pos_of_ne_zero (by linarith)
  have hsub_nonneg :
      0 ≤
        a * b * (Real.log (1 / a) - Real.log (1 / b)) ^ 2 /
          (b - a) ^ 2 := by
    exact div_nonneg
      (mul_nonneg (mul_nonneg (le_of_lt hapos) (le_of_lt hbpos))
        (sq_nonneg _)) hden_nonneg
  have hfactor :
      1 -
        a * b * (Real.log (1 / a) - Real.log (1 / b)) ^ 2 /
          (b - a) ^ 2 ≤ (1 : ℝ) := by
    linarith
  calc
    (1 / 12 : ℝ) *
        (1 -
          a * b * (Real.log (1 / a) - Real.log (1 / b)) ^ 2 /
            (b - a) ^ 2) ≤
        (1 / 12 : ℝ) * 1 := by
      exact mul_le_mul_of_nonneg_left hfactor (by norm_num)
    _ = (1 / 12 : ℝ) := by ring

theorem frontierStoppedLogCupOptimizer_middle_tail_intervalIntegrable
    {a b : ℝ} (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hmiddle : a < frontierStoppedLogCupRatio)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume a b :=
  (frontierStoppedLogCupOptimizer_middle_plateau_intervalIntegrable
      hmiddle ha le_rfl).trans
    (frontierStoppedLogCupOptimizer_tail_restricted_intervalIntegrable
      htail le_rfl hb)

theorem frontierStoppedLogCupOptimizer_middle_tail_square_intervalIntegrable
    {a b : ℝ} (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hmiddle : a < frontierStoppedLogCupRatio)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume a b :=
  (frontierStoppedLogCupOptimizer_middle_plateau_square_intervalIntegrable
      hmiddle ha le_rfl).trans
    (frontierStoppedLogCupOptimizer_tail_restricted_square_intervalIntegrable
      htail le_rfl hb)

theorem frontierStoppedLogCupOptimizer_middle_tail_centeredSquare_intervalIntegrable
    {a b : ℝ} (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hmiddle : a < frontierStoppedLogCupRatio)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    IntervalIntegrable
      (fun t ↦
        (frontierStoppedLogCupOptimizer t -
          frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
      volume a b := by
  let m := frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b
  have hleft :
      IntervalIntegrable (fun t ↦ (frontierStoppedLogCupOptimizer t - m) ^ 2)
        volume a frontierStoppedLogCupRatio := by
    rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hmiddle)]
    have hconst :
        IntegrableOn
          (fun _ : ℝ ↦ ((frontierCStar - frontierEpsilon) - m) ^ 2)
          (Set.Ioo a frontierStoppedLogCupRatio) volume := by
      rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hmiddle)]
      exact intervalIntegrable_const
    refine hconst.congr_fun ?_ measurableSet_Ioo
    intro t ht
    change ((frontierCStar - frontierEpsilon) - m) ^ 2 =
      (frontierStoppedLogCupOptimizer t - m) ^ 2
    exact congrArg (fun x ↦ (x - m) ^ 2)
      (frontierStoppedLogCupOptimizer_middle
        (le_trans ha (le_of_lt ht.1)) ht.2).symm
  have hright :
      IntervalIntegrable (fun t ↦ (frontierStoppedLogCupOptimizer t - m) ^ 2)
        volume frontierStoppedLogCupRatio b := by
    exact (((frontierStoppedLogCupOptimizer_tail_restricted_continuousOn
      htail le_rfl hb).sub continuousOn_const).pow 2).intervalIntegrable
  exact hleft.trans hright

theorem frontierStoppedLogCupOptimizer_middle_tail_intervalIntegral
    {a b : ℝ} (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hmiddle : a < frontierStoppedLogCupRatio)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
      (frontierStoppedLogCupRatio - a) *
          (frontierCStar - frontierEpsilon) +
        frontierEpsilon *
          (b * Real.log (1 / b) -
            frontierStoppedLogCupRatio *
              Real.log (1 / frontierStoppedLogCupRatio)) := by
  have hleft :
      IntervalIntegrable frontierStoppedLogCupOptimizer volume
        a frontierStoppedLogCupRatio :=
    frontierStoppedLogCupOptimizer_middle_plateau_intervalIntegrable
      hmiddle ha le_rfl
  have hright :
      IntervalIntegrable frontierStoppedLogCupOptimizer volume
        frontierStoppedLogCupRatio b :=
    frontierStoppedLogCupOptimizer_tail_restricted_intervalIntegrable
      htail le_rfl hb
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
        (∫ t in a..frontierStoppedLogCupRatio,
          frontierStoppedLogCupOptimizer t) +
        (∫ t in frontierStoppedLogCupRatio..b,
          frontierStoppedLogCupOptimizer t) := by
      rw [intervalIntegral.integral_add_adjacent_intervals hleft hright]
    _ = (frontierStoppedLogCupRatio - a) *
          (frontierCStar - frontierEpsilon) +
        frontierEpsilon *
          (b * Real.log (1 / b) -
            frontierStoppedLogCupRatio *
              Real.log (1 / frontierStoppedLogCupRatio)) := by
      rw [frontierStoppedLogCupOptimizer_middle_plateau_intervalIntegral
          hmiddle ha le_rfl,
        frontierStoppedLogCupOptimizer_tail_intervalIntegral htail le_rfl]

theorem frontierStoppedLogCupOptimizer_middle_tail_square_intervalIntegral
    {a b : ℝ} (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hmiddle : a < frontierStoppedLogCupRatio)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
      (frontierStoppedLogCupRatio - a) *
          (frontierCStar - frontierEpsilon) ^ 2 +
        frontierEpsilon ^ 2 *
          (b * ((Real.log (1 / b)) ^ 2 + 1) -
            frontierStoppedLogCupRatio *
              ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 2 + 1)) := by
  have hleft :
      IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
        volume a frontierStoppedLogCupRatio :=
    frontierStoppedLogCupOptimizer_middle_plateau_square_intervalIntegrable
      hmiddle ha le_rfl
  have hright :
      IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
        volume frontierStoppedLogCupRatio b :=
    frontierStoppedLogCupOptimizer_tail_restricted_square_intervalIntegrable
      htail le_rfl hb
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
        (∫ t in a..frontierStoppedLogCupRatio,
          frontierStoppedLogCupOptimizer t ^ 2) +
        (∫ t in frontierStoppedLogCupRatio..b,
          frontierStoppedLogCupOptimizer t ^ 2) := by
      rw [intervalIntegral.integral_add_adjacent_intervals hleft hright]
    _ = (frontierStoppedLogCupRatio - a) *
          (frontierCStar - frontierEpsilon) ^ 2 +
        frontierEpsilon ^ 2 *
          (b * ((Real.log (1 / b)) ^ 2 + 1) -
            frontierStoppedLogCupRatio *
              ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 2 + 1)) := by
      rw [frontierStoppedLogCupOptimizer_middle_plateau_square_intervalIntegral
          hmiddle ha le_rfl,
        frontierStoppedLogCupOptimizer_tail_square_intervalIntegral htail le_rfl]

theorem frontierStoppedLogCupOptimizer_middle_tail_intervalMean
    {a b : ℝ} (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hmiddle : a < frontierStoppedLogCupRatio)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b =
      ((frontierStoppedLogCupRatio - a) *
          (frontierCStar - frontierEpsilon) +
        frontierEpsilon *
          (b * Real.log (1 / b) -
            frontierStoppedLogCupRatio *
              Real.log (1 / frontierStoppedLogCupRatio))) / (b - a) := by
  rw [frontierBMOIntervalMean,
    frontierStoppedLogCupOptimizer_middle_tail_intervalIntegral ha hmiddle htail hb]

theorem frontierStoppedLogCup_middle_tail_variance_factor_le_one
    {u v : ℝ} (hu0 : 0 ≤ u) (hu1 : u ≤ 1) (hv1 : 1 ≤ v) (huv : u < v) :
    (v * ((Real.log v) ^ 2 - 2 * Real.log v + 2) - 2) / (v - u) -
        ((v - 1 - v * Real.log v) / (v - u)) ^ 2 ≤ (1 : ℝ) := by
  have hden_ne : v - u ≠ 0 := by linarith
  have hden_sq_pos : 0 < (v - u) ^ 2 := sq_pos_of_ne_zero hden_ne
  have hv0 : 0 ≤ v := le_trans (by norm_num) hv1
  have hlog : 0 ≤ Real.log v := Real.log_nonneg hv1
  have hone_sub : 0 ≤ 1 - u := by linarith
  have hbracket : 0 ≤ u * Real.log v + 2 * (1 - u) := by
    exact add_nonneg (mul_nonneg hu0 hlog)
      (mul_nonneg (by norm_num) hone_sub)
  have hres :
      0 ≤
        (1 - u) ^ 2 +
          v * Real.log v * (u * Real.log v + 2 * (1 - u)) :=
    add_nonneg (sq_nonneg (1 - u))
      (mul_nonneg (mul_nonneg hv0 hlog) hbracket)
  have hidentity :
      1 -
        ((v * ((Real.log v) ^ 2 - 2 * Real.log v + 2) - 2) / (v - u) -
          ((v - 1 - v * Real.log v) / (v - u)) ^ 2) =
        ((1 - u) ^ 2 +
          v * Real.log v * (u * Real.log v + 2 * (1 - u))) /
          (v - u) ^ 2 := by
    field_simp [hden_ne]
    ring
  have hnonneg :
      0 ≤
        1 -
          ((v * ((Real.log v) ^ 2 - 2 * Real.log v + 2) - 2) / (v - u) -
            ((v - 1 - v * Real.log v) / (v - u)) ^ 2) := by
    rw [hidentity]
    exact div_nonneg hres (le_of_lt hden_sq_pos)
  linarith

theorem frontierStoppedLogCupOptimizer_middle_tail_intervalVariance
    {a b : ℝ} (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hmiddle : a < frontierStoppedLogCupRatio)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b =
      frontierEpsilon ^ 2 *
        ((b / frontierStoppedLogCupRatio *
            ((Real.log (b / frontierStoppedLogCupRatio)) ^ 2 -
              2 * Real.log (b / frontierStoppedLogCupRatio) + 2) - 2) /
            (b / frontierStoppedLogCupRatio -
              a / frontierStoppedLogCupRatio) -
          ((b / frontierStoppedLogCupRatio - 1 -
              b / frontierStoppedLogCupRatio *
                Real.log (b / frontierStoppedLogCupRatio)) /
            (b / frontierStoppedLogCupRatio -
              a / frontierStoppedLogCupRatio)) ^ 2) := by
  have hab : a < b := lt_trans hmiddle htail
  have hne : b - a ≠ 0 := by linarith
  have hrpos : 0 < frontierStoppedLogCupRatio := frontierStoppedLogCupRatio_pos
  have hrne : frontierStoppedLogCupRatio ≠ 0 := ne_of_gt hrpos
  have hbpos : 0 < b := lt_of_lt_of_le hrpos (le_of_lt htail)
  have hbne : b ≠ 0 := ne_of_gt hbpos
  have hbr_ne : b / frontierStoppedLogCupRatio ≠ 0 := div_ne_zero hbne hrne
  have hlogb :
      Real.log (1 / b) =
        Real.log (1 / frontierStoppedLogCupRatio) -
          Real.log (b / frontierStoppedLogCupRatio) := by
    calc
      Real.log (1 / b) =
          Real.log ((1 / frontierStoppedLogCupRatio) /
            (b / frontierStoppedLogCupRatio)) := by
        congr 1
        field_simp [hbne, hrne]
      _ = Real.log (1 / frontierStoppedLogCupRatio) -
          Real.log (b / frontierStoppedLogCupRatio) := by
        rw [Real.log_div (one_div_ne_zero hrne) hbr_ne]
  have hC :
      frontierCStar =
        frontierEpsilon * Real.log (1 / frontierStoppedLogCupRatio) := by
    rw [frontierStoppedLogCup_log_one_div_ratio]
    field_simp [frontierEpsilon_ne_zero]
  rw [frontierBMOIntervalVariance_eq_secondMoment_sub_mean_sq hab
      (frontierStoppedLogCupOptimizer_middle_tail_intervalIntegrable
        ha hmiddle htail hb)
      (frontierStoppedLogCupOptimizer_middle_tail_square_intervalIntegrable
        ha hmiddle htail hb),
    frontierStoppedLogCupOptimizer_middle_tail_square_intervalIntegral
      ha hmiddle htail hb,
    frontierStoppedLogCupOptimizer_middle_tail_intervalMean
      ha hmiddle htail hb]
  rw [hC, hlogb]
  field_simp [hne, hrne]
  ring

theorem frontierStoppedLogCupOptimizer_middle_tail_intervalVariance_obligation
    {a b : ℝ} (ha : frontierStoppedLogCupRatio / 2 ≤ a)
    (hmiddle : a < frontierStoppedLogCupRatio)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    IntervalIntegrable
        (fun t ↦
          (frontierStoppedLogCupOptimizer t -
            frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b ≤
        (1 / 12 : ℝ) := by
  refine ⟨frontierStoppedLogCupOptimizer_middle_tail_centeredSquare_intervalIntegrable
      ha hmiddle htail hb, ?_⟩
  rw [frontierStoppedLogCupOptimizer_middle_tail_intervalVariance
      ha hmiddle htail hb, frontierEpsilon_sq]
  have hrpos : 0 < frontierStoppedLogCupRatio := frontierStoppedLogCupRatio_pos
  have hu0 : 0 ≤ a / frontierStoppedLogCupRatio := by
    have hhalf_nonneg : 0 ≤ frontierStoppedLogCupRatio / 2 := by
      exact le_of_lt frontierStoppedLogCupRatio_half_pos
    exact div_nonneg (le_trans hhalf_nonneg ha) (le_of_lt hrpos)
  have hu1 : a / frontierStoppedLogCupRatio ≤ 1 := by
    exact (div_le_one hrpos).mpr (le_of_lt hmiddle)
  have hv1 : 1 ≤ b / frontierStoppedLogCupRatio := by
    exact (one_le_div hrpos).mpr (le_of_lt htail)
  have huv : a / frontierStoppedLogCupRatio < b / frontierStoppedLogCupRatio := by
    exact div_lt_div_of_pos_right (lt_trans hmiddle htail) hrpos
  have hfactor :=
    frontierStoppedLogCup_middle_tail_variance_factor_le_one
      hu0 hu1 hv1 huv
  calc
    (1 / 12 : ℝ) *
        ((b / frontierStoppedLogCupRatio *
            ((Real.log (b / frontierStoppedLogCupRatio)) ^ 2 -
              2 * Real.log (b / frontierStoppedLogCupRatio) + 2) - 2) /
            (b / frontierStoppedLogCupRatio -
              a / frontierStoppedLogCupRatio) -
          ((b / frontierStoppedLogCupRatio - 1 -
              b / frontierStoppedLogCupRatio *
                Real.log (b / frontierStoppedLogCupRatio)) /
            (b / frontierStoppedLogCupRatio -
              a / frontierStoppedLogCupRatio)) ^ 2) ≤
        (1 / 12 : ℝ) * 1 := by
      exact mul_le_mul_of_nonneg_left hfactor
        (show 0 ≤ (1 / 12 : ℝ) by norm_num)
    _ = (1 / 12 : ℝ) := by ring

theorem frontierStoppedLogCupOptimizer_all_three_centeredSquare_intervalIntegrable
    {a b : ℝ} (hleft : a < frontierStoppedLogCupRatio / 2)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    IntervalIntegrable
      (fun t ↦
        (frontierStoppedLogCupOptimizer t -
          frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
      volume a b := by
  let m := frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b
  have hleft_int :
      IntervalIntegrable (fun t ↦ (frontierStoppedLogCupOptimizer t - m) ^ 2)
        volume a (frontierStoppedLogCupRatio / 2) := by
    rw [intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hleft)]
    have hconst :
        IntegrableOn
          (fun _ : ℝ ↦ ((frontierCStar + frontierEpsilon) - m) ^ 2)
          (Set.Ioo a (frontierStoppedLogCupRatio / 2)) volume := by
      rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le (le_of_lt hleft)]
      exact intervalIntegrable_const
    refine hconst.congr_fun ?_ measurableSet_Ioo
    intro t ht
    change ((frontierCStar + frontierEpsilon) - m) ^ 2 =
      (frontierStoppedLogCupOptimizer t - m) ^ 2
    exact congrArg (fun x ↦ (x - m) ^ 2)
      (frontierStoppedLogCupOptimizer_left ht.2).symm
  have hright_int :
      IntervalIntegrable (fun t ↦ (frontierStoppedLogCupOptimizer t - m) ^ 2)
        volume (frontierStoppedLogCupRatio / 2) b := by
    have hmiddle_int :
        IntervalIntegrable (fun t ↦ (frontierStoppedLogCupOptimizer t - m) ^ 2)
          volume (frontierStoppedLogCupRatio / 2) frontierStoppedLogCupRatio := by
      rw [intervalIntegrable_iff_integrableOn_Ioo_of_le
        (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)]
      have hconst :
          IntegrableOn
            (fun _ : ℝ ↦ ((frontierCStar - frontierEpsilon) - m) ^ 2)
            (Set.Ioo (frontierStoppedLogCupRatio / 2)
              frontierStoppedLogCupRatio) volume := by
        rw [← intervalIntegrable_iff_integrableOn_Ioo_of_le
          (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)]
        exact intervalIntegrable_const
      refine hconst.congr_fun ?_ measurableSet_Ioo
      intro t ht
      change ((frontierCStar - frontierEpsilon) - m) ^ 2 =
        (frontierStoppedLogCupOptimizer t - m) ^ 2
      exact congrArg (fun x ↦ (x - m) ^ 2)
        (frontierStoppedLogCupOptimizer_middle (le_of_lt ht.1) ht.2).symm
    have htail_int :
        IntervalIntegrable (fun t ↦ (frontierStoppedLogCupOptimizer t - m) ^ 2)
          volume frontierStoppedLogCupRatio b := by
      exact (((frontierStoppedLogCupOptimizer_tail_restricted_continuousOn
        htail le_rfl hb).sub continuousOn_const).pow 2).intervalIntegrable
    exact hmiddle_int.trans htail_int
  exact hleft_int.trans hright_int

theorem frontierStoppedLogCupOptimizer_all_three_intervalIntegrable
    {a b : ℝ} (hleft : a < frontierStoppedLogCupRatio / 2)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    IntervalIntegrable frontierStoppedLogCupOptimizer volume a b :=
  (frontierStoppedLogCupOptimizer_left_middle_intervalIntegrable
      hleft frontierStoppedLogCupRatio_half_lt_ratio le_rfl).trans
    (frontierStoppedLogCupOptimizer_tail_restricted_intervalIntegrable
      htail le_rfl hb)

theorem frontierStoppedLogCupOptimizer_all_three_square_intervalIntegrable
    {a b : ℝ} (hleft : a < frontierStoppedLogCupRatio / 2)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
      volume a b :=
  (frontierStoppedLogCupOptimizer_left_middle_square_intervalIntegrable
      hleft frontierStoppedLogCupRatio_half_lt_ratio le_rfl).trans
    (frontierStoppedLogCupOptimizer_tail_restricted_square_intervalIntegrable
      htail le_rfl hb)

theorem frontierStoppedLogCupOptimizer_all_three_intervalIntegral
    {a b : ℝ} (hleft : a < frontierStoppedLogCupRatio / 2)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
      (frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) +
        (frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) +
        frontierEpsilon *
          (b * Real.log (1 / b) -
            frontierStoppedLogCupRatio *
              Real.log (1 / frontierStoppedLogCupRatio)) := by
  have hleftMiddle :
      IntervalIntegrable frontierStoppedLogCupOptimizer volume
        a frontierStoppedLogCupRatio :=
    frontierStoppedLogCupOptimizer_left_middle_intervalIntegrable
      hleft frontierStoppedLogCupRatio_half_lt_ratio le_rfl
  have htailInt :
      IntervalIntegrable frontierStoppedLogCupOptimizer volume
        frontierStoppedLogCupRatio b :=
    frontierStoppedLogCupOptimizer_tail_restricted_intervalIntegrable
      htail le_rfl hb
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t) =
        (∫ t in a..frontierStoppedLogCupRatio,
          frontierStoppedLogCupOptimizer t) +
        (∫ t in frontierStoppedLogCupRatio..b,
          frontierStoppedLogCupOptimizer t) := by
      rw [intervalIntegral.integral_add_adjacent_intervals hleftMiddle htailInt]
    _ = (frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) +
        (frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) +
        frontierEpsilon *
          (b * Real.log (1 / b) -
            frontierStoppedLogCupRatio *
              Real.log (1 / frontierStoppedLogCupRatio)) := by
      rw [frontierStoppedLogCupOptimizer_left_middle_intervalIntegral
          hleft frontierStoppedLogCupRatio_half_lt_ratio le_rfl,
        frontierStoppedLogCupOptimizer_tail_intervalIntegral htail le_rfl]
      ring

theorem frontierStoppedLogCupOptimizer_all_three_square_intervalIntegral
    {a b : ℝ} (hleft : a < frontierStoppedLogCupRatio / 2)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
      (frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) ^ 2 +
        (frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) ^ 2 +
        frontierEpsilon ^ 2 *
          (b * ((Real.log (1 / b)) ^ 2 + 1) -
            frontierStoppedLogCupRatio *
              ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 2 + 1)) := by
  have hleftMiddle :
      IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
        volume a frontierStoppedLogCupRatio :=
    frontierStoppedLogCupOptimizer_left_middle_square_intervalIntegrable
      hleft frontierStoppedLogCupRatio_half_lt_ratio le_rfl
  have htailInt :
      IntervalIntegrable (fun t : ℝ ↦ frontierStoppedLogCupOptimizer t ^ 2)
        volume frontierStoppedLogCupRatio b :=
    frontierStoppedLogCupOptimizer_tail_restricted_square_intervalIntegrable
      htail le_rfl hb
  calc
    (∫ t in a..b, frontierStoppedLogCupOptimizer t ^ 2) =
        (∫ t in a..frontierStoppedLogCupRatio,
          frontierStoppedLogCupOptimizer t ^ 2) +
        (∫ t in frontierStoppedLogCupRatio..b,
          frontierStoppedLogCupOptimizer t ^ 2) := by
      rw [intervalIntegral.integral_add_adjacent_intervals hleftMiddle htailInt]
    _ = (frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) ^ 2 +
        (frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) ^ 2 +
        frontierEpsilon ^ 2 *
          (b * ((Real.log (1 / b)) ^ 2 + 1) -
            frontierStoppedLogCupRatio *
              ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 2 + 1)) := by
      rw [frontierStoppedLogCupOptimizer_left_middle_square_intervalIntegral
          hleft frontierStoppedLogCupRatio_half_lt_ratio le_rfl,
        frontierStoppedLogCupOptimizer_tail_square_intervalIntegral htail le_rfl]
      ring

theorem frontierStoppedLogCupOptimizer_all_three_intervalMean
    {a b : ℝ} (hleft : a < frontierStoppedLogCupRatio / 2)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b =
      ((frontierStoppedLogCupRatio / 2 - a) *
          (frontierCStar + frontierEpsilon) +
        (frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) +
        frontierEpsilon *
          (b * Real.log (1 / b) -
            frontierStoppedLogCupRatio *
              Real.log (1 / frontierStoppedLogCupRatio))) / (b - a) := by
  rw [frontierBMOIntervalMean,
    frontierStoppedLogCupOptimizer_all_three_intervalIntegral hleft htail hb]

theorem frontierStoppedLogCup_all_three_variance_factor_le_one
    {u v : ℝ} (hu0 : 0 ≤ u) (hv1 : 1 ≤ v) (huv : u < v) :
    (v * ((Real.log v) ^ 2 - 2 * Real.log v + 2) - 4 * u) / (v - u) -
        ((v - 2 * u - v * Real.log v) / (v - u)) ^ 2 ≤ (1 : ℝ) := by
  have hden_ne : v - u ≠ 0 := by linarith
  have hden_sq_pos : 0 < (v - u) ^ 2 := sq_pos_of_ne_zero hden_ne
  have hv0 : 0 ≤ v := le_trans (by norm_num) hv1
  have hlog : 0 ≤ Real.log v := Real.log_nonneg hv1
  have hbracket : 0 ≤ u + v * (Real.log v) ^ 2 + 2 * v * Real.log v := by
    exact add_nonneg
      (add_nonneg hu0 (mul_nonneg hv0 (sq_nonneg (Real.log v))))
      (mul_nonneg (mul_nonneg (by norm_num) hv0) hlog)
  have hres :
      0 ≤ u * (u + v * (Real.log v) ^ 2 + 2 * v * Real.log v) :=
    mul_nonneg hu0 hbracket
  have hidentity :
      1 -
        ((v * ((Real.log v) ^ 2 - 2 * Real.log v + 2) - 4 * u) / (v - u) -
          ((v - 2 * u - v * Real.log v) / (v - u)) ^ 2) =
        u * (u + v * (Real.log v) ^ 2 + 2 * v * Real.log v) /
          (v - u) ^ 2 := by
    field_simp [hden_ne]
    ring
  have hnonneg :
      0 ≤
        1 -
          ((v * ((Real.log v) ^ 2 - 2 * Real.log v + 2) - 4 * u) / (v - u) -
            ((v - 2 * u - v * Real.log v) / (v - u)) ^ 2) := by
    rw [hidentity]
    exact div_nonneg hres (le_of_lt hden_sq_pos)
  linarith

theorem frontierStoppedLogCupOptimizer_all_three_intervalVariance
    {a b : ℝ} (hleft : a < frontierStoppedLogCupRatio / 2)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b =
      frontierEpsilon ^ 2 *
        ((b / frontierStoppedLogCupRatio *
            ((Real.log (b / frontierStoppedLogCupRatio)) ^ 2 -
              2 * Real.log (b / frontierStoppedLogCupRatio) + 2) -
              4 * (a / frontierStoppedLogCupRatio)) /
            (b / frontierStoppedLogCupRatio -
              a / frontierStoppedLogCupRatio) -
          ((b / frontierStoppedLogCupRatio -
              2 * (a / frontierStoppedLogCupRatio) -
              b / frontierStoppedLogCupRatio *
                Real.log (b / frontierStoppedLogCupRatio)) /
            (b / frontierStoppedLogCupRatio -
              a / frontierStoppedLogCupRatio)) ^ 2) := by
  have hab : a < b := lt_trans hleft (lt_trans
    frontierStoppedLogCupRatio_half_lt_ratio htail)
  have hne : b - a ≠ 0 := by linarith
  have hrpos : 0 < frontierStoppedLogCupRatio := frontierStoppedLogCupRatio_pos
  have hrne : frontierStoppedLogCupRatio ≠ 0 := ne_of_gt hrpos
  have hbpos : 0 < b := lt_of_lt_of_le hrpos (le_of_lt htail)
  have hbne : b ≠ 0 := ne_of_gt hbpos
  have hbr_ne : b / frontierStoppedLogCupRatio ≠ 0 := div_ne_zero hbne hrne
  have hlogb :
      Real.log (1 / b) =
        Real.log (1 / frontierStoppedLogCupRatio) -
          Real.log (b / frontierStoppedLogCupRatio) := by
    calc
      Real.log (1 / b) =
          Real.log ((1 / frontierStoppedLogCupRatio) /
            (b / frontierStoppedLogCupRatio)) := by
        congr 1
        field_simp [hbne, hrne]
      _ = Real.log (1 / frontierStoppedLogCupRatio) -
          Real.log (b / frontierStoppedLogCupRatio) := by
        rw [Real.log_div (one_div_ne_zero hrne) hbr_ne]
  have hC :
      frontierCStar =
        frontierEpsilon * Real.log (1 / frontierStoppedLogCupRatio) := by
    rw [frontierStoppedLogCup_log_one_div_ratio]
    field_simp [frontierEpsilon_ne_zero]
  rw [frontierBMOIntervalVariance_eq_secondMoment_sub_mean_sq hab
      (frontierStoppedLogCupOptimizer_all_three_intervalIntegrable
        hleft htail hb)
      (frontierStoppedLogCupOptimizer_all_three_square_intervalIntegrable
        hleft htail hb),
    frontierStoppedLogCupOptimizer_all_three_square_intervalIntegral
      hleft htail hb,
    frontierStoppedLogCupOptimizer_all_three_intervalMean hleft htail hb]
  rw [hC, hlogb]
  field_simp [hne, hrne]
  ring

theorem frontierStoppedLogCupOptimizer_all_three_intervalVariance_obligation
    {a b : ℝ} (ha : 0 ≤ a) (hleft : a < frontierStoppedLogCupRatio / 2)
    (htail : frontierStoppedLogCupRatio < b) (hb : b ≤ 1) :
    IntervalIntegrable
        (fun t ↦
          (frontierStoppedLogCupOptimizer t -
            frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b ≤
        (1 / 12 : ℝ) := by
  refine ⟨frontierStoppedLogCupOptimizer_all_three_centeredSquare_intervalIntegrable
      hleft htail hb, ?_⟩
  rw [frontierStoppedLogCupOptimizer_all_three_intervalVariance
      hleft htail hb, frontierEpsilon_sq]
  have hrpos : 0 < frontierStoppedLogCupRatio := frontierStoppedLogCupRatio_pos
  have hu0 : 0 ≤ a / frontierStoppedLogCupRatio :=
    div_nonneg ha (le_of_lt hrpos)
  have hv1 : 1 ≤ b / frontierStoppedLogCupRatio := by
    exact (one_le_div hrpos).mpr (le_of_lt htail)
  have huv : a / frontierStoppedLogCupRatio < b / frontierStoppedLogCupRatio := by
    exact div_lt_div_of_pos_right
      (lt_trans hleft (lt_trans frontierStoppedLogCupRatio_half_lt_ratio htail))
      hrpos
  have hfactor :=
    frontierStoppedLogCup_all_three_variance_factor_le_one hu0 hv1 huv
  calc
    (1 / 12 : ℝ) *
        ((b / frontierStoppedLogCupRatio *
            ((Real.log (b / frontierStoppedLogCupRatio)) ^ 2 -
              2 * Real.log (b / frontierStoppedLogCupRatio) + 2) -
              4 * (a / frontierStoppedLogCupRatio)) /
            (b / frontierStoppedLogCupRatio -
              a / frontierStoppedLogCupRatio) -
          ((b / frontierStoppedLogCupRatio -
              2 * (a / frontierStoppedLogCupRatio) -
              b / frontierStoppedLogCupRatio *
                Real.log (b / frontierStoppedLogCupRatio)) /
            (b / frontierStoppedLogCupRatio -
              a / frontierStoppedLogCupRatio)) ^ 2) ≤
        (1 / 12 : ℝ) * 1 := by
      exact mul_le_mul_of_nonneg_left hfactor
        (show 0 ≤ (1 / 12 : ℝ) by norm_num)
    _ = (1 / 12 : ℝ) := by ring

theorem frontierStoppedLogCupOptimizer_intervalVariance_obligation
    (a b : ℝ) (ha0 : 0 ≤ a) (hab : a < b) (hb1 : b ≤ 1) :
    IntervalIntegrable
        (fun t ↦
          (frontierStoppedLogCupOptimizer t -
            frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
        volume a b ∧
      frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b ≤
        (1 / 12 : ℝ) := by
  by_cases hbLeft : b ≤ frontierStoppedLogCupRatio / 2
  · exact frontierStoppedLogCupOptimizer_left_plateau_intervalVariance_obligation
      hab hbLeft
  · have hbPastLeft : frontierStoppedLogCupRatio / 2 < b := lt_of_not_ge hbLeft
    by_cases hbMiddle : b ≤ frontierStoppedLogCupRatio
    · by_cases haLeft : a < frontierStoppedLogCupRatio / 2
      · exact frontierStoppedLogCupOptimizer_left_middle_intervalVariance_obligation
          haLeft hbPastLeft hbMiddle
      · exact frontierStoppedLogCupOptimizer_middle_plateau_intervalVariance_obligation
          hab (not_lt.mp haLeft) hbMiddle
    · have hbTail : frontierStoppedLogCupRatio < b := lt_of_not_ge hbMiddle
      by_cases haLeft : a < frontierStoppedLogCupRatio / 2
      · exact frontierStoppedLogCupOptimizer_all_three_intervalVariance_obligation
          ha0 haLeft hbTail hb1
      · have haHalf : frontierStoppedLogCupRatio / 2 ≤ a := not_lt.mp haLeft
        by_cases haMiddle : a < frontierStoppedLogCupRatio
        · exact frontierStoppedLogCupOptimizer_middle_tail_intervalVariance_obligation
            haHalf haMiddle hbTail hb1
        · exact frontierStoppedLogCupOptimizer_tail_intervalVariance_obligation
            hab (not_lt.mp haMiddle) hb1

theorem frontierStoppedLogCup_middle_tail_variance_residual_nonneg
    {u v : ℝ} (hu0 : 0 ≤ u) (hu1 : u ≤ 1) (hv1 : 1 ≤ v) :
    0 ≤
      (1 - u) ^ 2 +
        v * Real.log v * (u * Real.log v + 2 * (1 - u)) := by
  have hv0 : 0 ≤ v := le_trans (by norm_num) hv1
  have hlog : 0 ≤ Real.log v := Real.log_nonneg hv1
  have hone_sub : 0 ≤ 1 - u := by linarith
  have hbracket : 0 ≤ u * Real.log v + 2 * (1 - u) := by
    exact add_nonneg (mul_nonneg hu0 hlog)
      (mul_nonneg (by norm_num) hone_sub)
  exact add_nonneg (sq_nonneg (1 - u))
    (mul_nonneg (mul_nonneg hv0 hlog) hbracket)

theorem frontierStoppedLogCup_all_three_variance_residual_nonneg
    {u v : ℝ} (hu0 : 0 ≤ u) (hv1 : 1 ≤ v) :
    0 ≤ u * (u + v * (Real.log v) ^ 2 + 2 * v * Real.log v) := by
  have hv0 : 0 ≤ v := le_trans (by norm_num) hv1
  have hlog : 0 ≤ Real.log v := Real.log_nonneg hv1
  have hbracket : 0 ≤ u + v * (Real.log v) ^ 2 + 2 * v * Real.log v := by
    exact add_nonneg
      (add_nonneg hu0 (mul_nonneg hv0 (sq_nonneg (Real.log v))))
      (mul_nonneg (mul_nonneg (by norm_num) hv0) hlog)
  exact mul_nonneg hu0 hbracket

theorem frontier_hasDerivAt_log_one_div_cube_antiderivative {x : ℝ} (hx : x ≠ 0) :
    HasDerivAt
      (fun t : ℝ ↦
        t * ((Real.log (1 / t)) ^ 3 + 3 * Real.log (1 / t) + 2))
      ((Real.log (1 / x) - 1) ^ 3) x := by
  have hlog := frontier_hasDerivAt_log_one_div hx
  have hpoly :
      HasDerivAt
        (fun t : ℝ ↦ (Real.log (1 / t)) ^ 3 + 3 * Real.log (1 / t) + 2)
        (3 * (Real.log (1 / x)) ^ 2 * (-(1 / x)) +
          3 * (-(1 / x)) + 0) x := by
    simpa [pow_one, mul_assoc, add_assoc, add_left_comm, add_comm] using
      (((hlog.pow 3).add (hlog.const_mul 3)).add_const 2)
  convert (hasDerivAt_id x).mul hpoly using 1
  simp only [id_eq]
  field_simp [hx]
  ring

theorem frontierStoppedLogCup_logMinusOne_cube_tail_integral :
    (∫ t in frontierStoppedLogCupRatio..1,
        (Real.log (1 / t) - 1) ^ 3) =
      2 - frontierStoppedLogCupRatio *
        ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 3 +
          3 * Real.log (1 / frontierStoppedLogCupRatio) + 2) := by
  rw [intervalIntegral.integral_eq_sub_of_hasDerivAt
    (f := fun t : ℝ ↦
      t * ((Real.log (1 / t)) ^ 3 + 3 * Real.log (1 / t) + 2))
    (f' := fun t ↦ (Real.log (1 / t) - 1) ^ 3)]
  · norm_num
  · intro x hx
    rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at hx
    exact frontier_hasDerivAt_log_one_div_cube_antiderivative
      (ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos hx.1))
  · have hcont :
        ContinuousOn (fun t : ℝ ↦ (Real.log (1 / t) - 1) ^ 3)
          [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
      have hinv :
          ContinuousOn (fun t : ℝ ↦ 1 / t)
            [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
        exact continuousOn_const.div continuousOn_id (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
          exact ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1))
      have hlog :
          ContinuousOn (fun t : ℝ ↦ Real.log (1 / t))
            [[frontierStoppedLogCupRatio, (1 : ℝ)]] := by
        exact hinv.log (by
          intro t ht
          rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
          exact one_div_ne_zero
            (ne_of_gt (lt_of_lt_of_le frontierStoppedLogCupRatio_pos ht.1)))
      exact ((hlog.sub continuousOn_const).pow 3)
    exact hcont.intervalIntegrable

theorem frontierStoppedLogCupOptimizer_left_phi_integral :
    (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
        frontierPhi (frontierStoppedLogCupOptimizer t)) =
      (frontierStoppedLogCupRatio / 2) *
        ((frontierCStar + frontierEpsilon) ^ 3 +
          2 * ((frontierCStar + frontierEpsilon) - frontierA)) := by
  calc
    (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
        frontierPhi (frontierStoppedLogCupOptimizer t)) =
        ∫ _t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
          ((frontierCStar + frontierEpsilon) ^ 3 +
            2 * ((frontierCStar + frontierEpsilon) - frontierA)) := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne (frontierStoppedLogCupRatio / 2)]
        with t hne ht
      rw [Set.uIoc_of_le (le_of_lt frontierStoppedLogCupRatio_half_pos)] at ht
      have hlt : t < frontierStoppedLogCupRatio / 2 := lt_of_le_of_ne ht.2 hne
      exact frontierPhi_stoppedLogCupOptimizer_left_value hlt
    _ = (frontierStoppedLogCupRatio / 2) *
        ((frontierCStar + frontierEpsilon) ^ 3 +
          2 * ((frontierCStar + frontierEpsilon) - frontierA)) := by
      rw [intervalIntegral.integral_const]
      simp

theorem frontierStoppedLogCupOptimizer_middle_phi_integral :
    (∫ t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
        frontierPhi (frontierStoppedLogCupOptimizer t)) =
      (frontierStoppedLogCupRatio / 2) *
        (frontierCStar - frontierEpsilon) ^ 3 := by
  calc
    (∫ t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
        frontierPhi (frontierStoppedLogCupOptimizer t)) =
        ∫ _t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
          (frontierCStar - frontierEpsilon) ^ 3 := by
      apply intervalIntegral.integral_congr_ae
      filter_upwards [volume.ae_ne frontierStoppedLogCupRatio] with t hne ht
      rw [Set.uIoc_of_le (le_of_lt frontierStoppedLogCupRatio_half_lt_ratio)] at ht
      have hlt : t < frontierStoppedLogCupRatio := lt_of_le_of_ne ht.2 hne
      exact frontierPhi_stoppedLogCupOptimizer_middle_value (le_of_lt ht.1) hlt
    _ = (frontierStoppedLogCupRatio / 2) *
        (frontierCStar - frontierEpsilon) ^ 3 := by
      rw [intervalIntegral.integral_const]
      change (frontierStoppedLogCupRatio - frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) ^ 3 =
        (frontierStoppedLogCupRatio / 2) *
          (frontierCStar - frontierEpsilon) ^ 3
      ring

theorem frontierStoppedLogCupOptimizer_tail_phi_integral :
    (∫ t in frontierStoppedLogCupRatio..1,
        frontierPhi (frontierStoppedLogCupOptimizer t)) =
      frontierEpsilon ^ 3 *
        (2 - frontierStoppedLogCupRatio *
          ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 3 +
            3 * Real.log (1 / frontierStoppedLogCupRatio) + 2)) := by
  calc
    (∫ t in frontierStoppedLogCupRatio..1,
        frontierPhi (frontierStoppedLogCupOptimizer t)) =
        ∫ t in frontierStoppedLogCupRatio..1,
          frontierEpsilon ^ 3 * (Real.log (1 / t) - 1) ^ 3 := by
      apply intervalIntegral.integral_congr
      intro t ht
      rw [Set.uIcc_of_le (le_of_lt frontierStoppedLogCupRatio_lt_one)] at ht
      exact frontierPhi_stoppedLogCupOptimizer_tail_value ht.1 ht.2
    _ = frontierEpsilon ^ 3 *
        (∫ t in frontierStoppedLogCupRatio..1,
          (Real.log (1 / t) - 1) ^ 3) := by
      rw [intervalIntegral.integral_const_mul]
    _ = frontierEpsilon ^ 3 *
        (2 - frontierStoppedLogCupRatio *
          ((Real.log (1 / frontierStoppedLogCupRatio)) ^ 3 +
            3 * Real.log (1 / frontierStoppedLogCupRatio) + 2)) := by
      rw [frontierStoppedLogCup_logMinusOne_cube_tail_integral]

theorem frontierStoppedLogCupOptimizer_objectiveIntegral :
    frontierBMOCenteredObjectiveIntegral frontierStoppedLogCupOptimizer =
      frontierStoppedLogCupObjective := by
  rw [frontierBMOCenteredObjectiveIntegral]
  calc
    (∫ t in (0 : ℝ)..1, frontierPhi (frontierStoppedLogCupOptimizer t)) =
        (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
          frontierPhi (frontierStoppedLogCupOptimizer t)) +
        (∫ t in frontierStoppedLogCupRatio / 2..1,
          frontierPhi (frontierStoppedLogCupOptimizer t)) := by
      rw [intervalIntegral.integral_add_adjacent_intervals
        frontierPhi_stoppedLogCupOptimizer_left_intervalIntegrable
        (frontierPhi_stoppedLogCupOptimizer_middle_intervalIntegrable.trans
          frontierPhi_stoppedLogCupOptimizer_tail_intervalIntegrable)]
    _ = (∫ t in (0 : ℝ)..frontierStoppedLogCupRatio / 2,
          frontierPhi (frontierStoppedLogCupOptimizer t)) +
        ((∫ t in frontierStoppedLogCupRatio / 2..frontierStoppedLogCupRatio,
          frontierPhi (frontierStoppedLogCupOptimizer t)) +
        (∫ t in frontierStoppedLogCupRatio..1,
          frontierPhi (frontierStoppedLogCupOptimizer t))) := by
      rw [intervalIntegral.integral_add_adjacent_intervals
        frontierPhi_stoppedLogCupOptimizer_middle_intervalIntegrable
        frontierPhi_stoppedLogCupOptimizer_tail_intervalIntegrable]
    _ = frontierStoppedLogCupObjective := by
      rw [frontierStoppedLogCupOptimizer_left_phi_integral,
        frontierStoppedLogCupOptimizer_middle_phi_integral,
        frontierStoppedLogCupOptimizer_tail_phi_integral,
        frontierStoppedLogCup_log_one_div_ratio,
        frontierStoppedLogCupObjective, frontierKL_eq_epsilon_mul_stoppedLogCupRatio]
      field_simp [frontierEpsilon_ne_zero]
      rw [frontierCStar, frontierA, frontierEpsilon_cube, frontierEpsilon_sq]
      ring_nf
      rw [frontierEpsilon_sq, frontierEpsilon_cube]
      ring

theorem frontierStoppedLogCupOptimizer_centered_admissible_of_intervalVariance
    (hvariance :
      ∀ a b : ℝ, 0 ≤ a → a < b → b ≤ 1 →
        IntervalIntegrable
            (fun t ↦
              (frontierStoppedLogCupOptimizer t -
                frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
            volume a b ∧
          frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b ≤
            (1 / 12 : ℝ)) :
    frontierBMOCenteredFunctionAdmissible frontierStoppedLogCupOptimizer := by
  rcases frontierStoppedLogCupOptimizer_centered_core_obligations with
    ⟨hg, hg2, hphi, hmean, hsecondMoment⟩
  exact ⟨hg, hg2, hphi, hmean, hsecondMoment, hvariance⟩

theorem frontierStoppedLogCupObjective_mem_centered_objectiveSet_of_intervalVariance
    (hvariance :
      ∀ a b : ℝ, 0 ≤ a → a < b → b ≤ 1 →
        IntervalIntegrable
            (fun t ↦
              (frontierStoppedLogCupOptimizer t -
                frontierBMOIntervalMean frontierStoppedLogCupOptimizer a b) ^ 2)
            volume a b ∧
          frontierBMOIntervalVariance frontierStoppedLogCupOptimizer a b ≤
            (1 / 12 : ℝ)) :
    frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet := by
  refine ⟨frontierStoppedLogCupOptimizer,
    frontierStoppedLogCupOptimizer_centered_admissible_of_intervalVariance hvariance, ?_⟩
  exact frontierStoppedLogCupOptimizer_objectiveIntegral.symm

theorem frontierStoppedLogCupObjective_mem_centered_objectiveSet :
    frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet := by
  exact frontierStoppedLogCupObjective_mem_centered_objectiveSet_of_intervalVariance
    frontierStoppedLogCupOptimizer_intervalVariance_obligation

theorem frontierStoppedLogCupObjective_mem_centered_objectiveSet_unconditional :
    frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet := by
  exact frontierStoppedLogCupObjective_mem_centered_objectiveSet

theorem frontierStoppedLogCupObjective_eq_contact_ratio_form :
    frontierStoppedLogCupObjective =
      2 * frontierEpsilon ^ 3 +
        frontierEpsilon * frontierStoppedLogCupRatio := by
  rw [frontierStoppedLogCupObjective, frontierKL_eq_epsilon_mul_stoppedLogCupRatio]

theorem frontierStoppedLogCupObjective_mem_centered_objectiveSet_of_explicit_optimizer
    (hcentered :
      frontierBMOCenteredFunctionAdmissible frontierStoppedLogCupOptimizer)
    (hvalue :
    frontierBMOCenteredObjectiveIntegral frontierStoppedLogCupOptimizer =
        frontierStoppedLogCupObjective) :
    frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet := by
  refine ⟨frontierStoppedLogCupOptimizer, hcentered, ?_⟩
  exact hvalue.symm

theorem frontierRadius_center :
    frontierRadius frontierEpsilon 0 (frontierEpsilon ^ 2) = 0 := by
  rw [frontierRadius]
  have harg : frontierEpsilon ^ 2 + (0 : ℝ) ^ 2 - frontierEpsilon ^ 2 = 0 := by
    ring
  rw [harg, Real.sqrt_zero]

theorem frontierCPlus_center :
    frontierCPlus frontierEpsilon 0 (frontierEpsilon ^ 2) = 0 := by
  rw [frontierCPlus, frontierRadius_center]
  norm_num

theorem frontierMajorant_center_eq_stoppedLogCupObjective :
    frontierMajorant 0 (frontierEpsilon ^ 2) = frontierStoppedLogCupObjective := by
  rw [frontierMajorant, frontierCPlus_center]
  have hleft : (0 : ℝ) ≤ frontierCStar := by
    rw [frontierCStar, frontierA]
    have hcube : 0 ≤ 2 * frontierEpsilon ^ 3 :=
      mul_nonneg (by norm_num) (pow_nonneg (le_of_lt frontierEpsilon_pos) 3)
    linarith
  rw [if_pos hleft, frontierLeftPiece, frontierCPlus_center,
    frontierRadius_center, frontierStoppedLogCupObjective]
  field_simp [frontierEpsilon_ne_zero]
  rw [zero_div, Real.exp_zero]
  ring

theorem frontierStoppedLogCupObjective_eq_publicAnswer :
    frontierStoppedLogCupObjective = frontierBMOPublicAnswer := by
  have hs_nonneg : 0 ≤ (3 : ℝ) := by norm_num
  have hs : (Real.sqrt 3) ^ 2 = (3 : ℝ) := Real.sq_sqrt hs_nonneg
  have hs0 : Real.sqrt 3 ≠ 0 := Real.sqrt_ne_zero'.2 (by norm_num)
  rw [frontierStoppedLogCupObjective, frontierKL_eq_public_weight, frontierEpsilon]
  rw [← bmo_contact_exponent_identity (Real.sqrt 3) hs hs0]
  exact bmo_public_answer_contact_form.symm

theorem frontierStoppedLogCupObjective_sub_centering_eq_originalSupremumValue :
    frontierStoppedLogCupObjective - (1985 / 2 : ℝ) =
      frontierBMOOriginalSupremumValue := by
  rw [frontierStoppedLogCupObjective_eq_publicAnswer, frontierBMOOriginalSupremumValue]

theorem frontierMajorant_center_eq_publicAnswer :
    frontierMajorant 0 (1 / 12 : ℝ) = frontierBMOPublicAnswer := by
  rw [← frontierEpsilon_sq, frontierMajorant_center_eq_stoppedLogCupObjective,
    frontierStoppedLogCupObjective_eq_publicAnswer]

theorem frontierMajorant_cupAlpha_boundary_eq_phi :
    frontierMajorant frontierCupAlpha (frontierCupAlpha ^ 2) =
      frontierPhi frontierCupAlpha := by
  exact frontierMajorant_left_boundary_eq_phi frontierCupAlpha (by
    rw [frontierCupAlpha]
    ring_nf
    exact le_rfl)

theorem frontierMajorant_cupBeta_boundary_eq_phi :
    frontierMajorant frontierCupBeta (frontierCupBeta ^ 2) =
      frontierPhi frontierCupBeta := by
  have hleft : frontierCStar < frontierCupBeta + frontierEpsilon := by
    rw [frontierCupBeta]
    linarith [frontierEpsilon_pos]
  have hright :
      frontierCupBeta + frontierEpsilon ≤
        frontierCStar + 2 * frontierEpsilon := by
    rw [frontierCupBeta]
    linarith
  have hglue :
      frontierMiddlePiece frontierCupBeta (frontierCupBeta ^ 2) =
        frontierRightTailPiece frontierCupBeta (frontierCupBeta ^ 2) := by
    apply frontierMiddlePiece_eq_rightTailPiece_lower_boundary_glue
    rw [frontierCupBeta]
    ring
  rw [frontierMajorant_middle_boundary_eq frontierCupBeta hleft hright,
    hglue, frontierRightTailPiece_boundary frontierCupBeta frontierA_le_CupBeta]

theorem frontierMajorant_stoppedLogCupOptimizer_boundary_eq_phi_on_unit
    {t : ℝ} (_ht0 : 0 ≤ t) (ht1 : t ≤ 1) :
    frontierMajorant (frontierStoppedLogCupOptimizer t)
        ((frontierStoppedLogCupOptimizer t) ^ 2) =
      frontierPhi (frontierStoppedLogCupOptimizer t) := by
  by_cases hleft : t < frontierStoppedLogCupRatio / 2
  · rw [frontierStoppedLogCupOptimizer_left hleft]
    rw [← frontierCupBeta]
    exact frontierMajorant_cupBeta_boundary_eq_phi
  · by_cases hmiddle : t < frontierStoppedLogCupRatio
    · have hhalf : frontierStoppedLogCupRatio / 2 ≤ t := not_lt.mp hleft
      rw [frontierStoppedLogCupOptimizer_middle hhalf hmiddle]
      rw [← frontierCupAlpha]
      exact frontierMajorant_cupAlpha_boundary_eq_phi
    · have htail : frontierStoppedLogCupRatio ≤ t := not_lt.mp hmiddle
      have hx_le :
          frontierStoppedLogCupOptimizer t ≤ frontierCupAlpha :=
        frontierStoppedLogCupOptimizer_tail_le_cupAlpha htail ht1
      apply frontierMajorant_left_boundary_eq_phi
      rw [frontierCupAlpha] at hx_le
      linarith

def frontierStoppedLogCupEnvelope (t : ℝ) : ℝ :=
  frontierPhi (frontierStoppedLogCupOptimizer t)

def frontierStoppedLogCupBoundaryMajorantTrace (t : ℝ) : ℝ :=
  frontierMajorant (frontierStoppedLogCupOptimizer t)
    ((frontierStoppedLogCupOptimizer t) ^ 2)

theorem frontierStoppedLogCupEnvelope_boundaryMajorantTrace_upper
    {t : ℝ} (ht0 : 0 ≤ t) (ht1 : t ≤ 1) :
    frontierStoppedLogCupEnvelope t ≤
      frontierStoppedLogCupBoundaryMajorantTrace t := by
  exact le_of_eq
    (frontierMajorant_stoppedLogCupOptimizer_boundary_eq_phi_on_unit
      ht0 ht1).symm

theorem frontierStoppedLogCupOptimizer_boundaryMajorantIntegral :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierStoppedLogCupOptimizer t)
        ((frontierStoppedLogCupOptimizer t) ^ 2)) =
      frontierStoppedLogCupObjective := by
  calc
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierStoppedLogCupOptimizer t)
        ((frontierStoppedLogCupOptimizer t) ^ 2)) =
        ∫ t in (0 : ℝ)..1,
          frontierPhi (frontierStoppedLogCupOptimizer t) := by
      apply intervalIntegral.integral_congr
      intro t ht
      rw [Set.uIcc_of_le (by norm_num : (0 : ℝ) ≤ 1)] at ht
      exact frontierMajorant_stoppedLogCupOptimizer_boundary_eq_phi_on_unit
        ht.1 ht.2
    _ = frontierStoppedLogCupObjective := by
      rw [← frontierStoppedLogCupOptimizer_objectiveIntegral,
        frontierBMOCenteredObjectiveIntegral]

theorem frontierStoppedLogCupOptimizer_boundaryMajorantIntegral_eq_center :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierStoppedLogCupOptimizer t)
        ((frontierStoppedLogCupOptimizer t) ^ 2)) =
      frontierMajorant 0 (1 / 12 : ℝ) := by
  rw [frontierStoppedLogCupOptimizer_boundaryMajorantIntegral,
    ← frontierEpsilon_sq, frontierMajorant_center_eq_stoppedLogCupObjective]

theorem frontierStoppedLogCupOptimizer_boundaryMajorantIntegral_le_center :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierStoppedLogCupOptimizer t)
        ((frontierStoppedLogCupOptimizer t) ^ 2)) ≤
      frontierMajorant 0 (1 / 12 : ℝ) := by
  exact le_of_eq frontierStoppedLogCupOptimizer_boundaryMajorantIntegral_eq_center

theorem frontierStoppedLogCupBoundaryMajorantIntegral_upper :
    (∫ t in (0 : ℝ)..1, frontierStoppedLogCupBoundaryMajorantTrace t) ≤
      frontierMajorant 0 (1 / 12 : ℝ) := by
  simpa [frontierStoppedLogCupBoundaryMajorantTrace] using
    frontierStoppedLogCupOptimizer_boundaryMajorantIntegral_le_center

theorem frontierStoppedLogCupOptimizer_boundaryMajorantGapIntegral :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierStoppedLogCupOptimizer t)
          ((frontierStoppedLogCupOptimizer t) ^ 2) -
        frontierPhi (frontierStoppedLogCupOptimizer t)) = 0 := by
  calc
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierStoppedLogCupOptimizer t)
          ((frontierStoppedLogCupOptimizer t) ^ 2) -
        frontierPhi (frontierStoppedLogCupOptimizer t)) =
        ∫ _t in (0 : ℝ)..1, (0 : ℝ) := by
      apply intervalIntegral.integral_congr
      intro t ht
      rw [Set.uIcc_of_le (by norm_num : (0 : ℝ) ≤ 1)] at ht
      have hboundary :=
        frontierMajorant_stoppedLogCupOptimizer_boundary_eq_phi_on_unit
          ht.1 ht.2
      simpa using sub_eq_zero.mpr hboundary
    _ = 0 := by simp

theorem frontierStoppedLogCupOptimizer_boundaryMajorantResidualBudget_eq :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierStoppedLogCupOptimizer t)
          ((frontierStoppedLogCupOptimizer t) ^ 2) -
        frontierPhi (frontierStoppedLogCupOptimizer t)) =
      frontierMajorant 0 (1 / 12 : ℝ) -
        frontierBMOCenteredObjectiveIntegral frontierStoppedLogCupOptimizer := by
  rw [frontierStoppedLogCupOptimizer_boundaryMajorantGapIntegral,
    frontierStoppedLogCupOptimizer_objectiveIntegral]
  rw [← frontierEpsilon_sq, frontierMajorant_center_eq_stoppedLogCupObjective]
  ring

theorem frontierStoppedLogCupOptimizer_boundaryMajorant_contact :
    frontierBMOCenteredFunctionAdmissible frontierStoppedLogCupOptimizer ∧
      (∫ t in (0 : ℝ)..1,
        frontierMajorant (frontierStoppedLogCupOptimizer t)
          ((frontierStoppedLogCupOptimizer t) ^ 2)) =
        frontierMajorant 0 (1 / 12 : ℝ) := by
  exact ⟨
    frontierStoppedLogCupOptimizer_centered_admissible_of_intervalVariance
      frontierStoppedLogCupOptimizer_intervalVariance_obligation,
    frontierStoppedLogCupOptimizer_boundaryMajorantIntegral_eq_center⟩

theorem frontierBMOPublicAnswer_mem_centered_objectiveSet_of_stoppedLogCup
    (hmem : frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet) :
    frontierBMOPublicAnswer ∈ frontierBMOCenteredFunctionObjectiveSet := by
  rwa [← frontierStoppedLogCupObjective_eq_publicAnswer]

theorem frontierBMOCenteredFunctionSupremum_eq_publicAnswer_of_actual_bounds
    (hupper : frontierBMOCenteredActualUpperBound)
    (hlower : frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet) :
    frontierBMOCenteredFunctionSupremum = frontierBMOPublicAnswer := by
  have hbdd : BddAbove frontierBMOCenteredFunctionObjectiveSet :=
    frontierBMOCenteredFunctionObjectiveSet_bddAbove_of_actualUpper hupper
  have hpublic_mem :
      frontierBMOPublicAnswer ∈ frontierBMOCenteredFunctionObjectiveSet :=
    frontierBMOPublicAnswer_mem_centered_objectiveSet_of_stoppedLogCup hlower
  have hle : frontierBMOCenteredFunctionSupremum ≤ frontierBMOPublicAnswer := by
    exact csSup_le frontierBMOCenteredFunctionObjectiveSet_nonempty hupper
  have hge : frontierBMOPublicAnswer ≤ frontierBMOCenteredFunctionSupremum := by
    exact le_csSup hbdd hpublic_mem
  exact le_antisymm hle hge

theorem frontier_bmo_public_sample_original_unconditional_sSup_bridge
    (hupper : frontierBMOCenteredActualUpperBound)
    (_hlower : frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOCenteredFunctionSupremum := by
  exact frontier_original_benchmark_eq_centered_supremum
    frontierBMOCenteredFunctionObjectiveSet_nonempty
    (frontierBMOCenteredFunctionObjectiveSet_bddAbove_of_actualUpper hupper)

theorem frontier_bmo_public_sample_original_unconditional_from_centered_sSup
    (hupper : frontierBMOCenteredActualUpperBound)
    (hlower : frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  rw [frontier_bmo_public_sample_original_unconditional_sSup_bridge hupper hlower]
  exact frontierBMOCenteredFunctionSupremum_eq_publicAnswer_of_actual_bounds hupper hlower

theorem frontierBMOCenteredActualUpperBound_iff_direct_integral_bound :
    frontierBMOCenteredActualUpperBound ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤ frontierBMOPublicAnswer := by
  constructor
  · intro hupper g hg
    exact hupper (frontierBMOCenteredObjectiveIntegral g) ⟨g, hg, rfl⟩
  · intro hbound y hy
    rcases hy with ⟨g, hg, rfl⟩
    exact hbound g hg

theorem frontierBMOCenteredActualUpperBound_of_direct_integral_bound
    (hbound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤ frontierBMOPublicAnswer) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_iff_direct_integral_bound.mpr hbound

theorem frontierBMOCenteredActualUpperBound_of_majorant_integral_bound
    (hmajorization :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤ frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredActualUpperBound := by
  intro y hy
  rcases hy with ⟨g, hg, rfl⟩
  exact le_trans (hmajorization g hg) (le_of_eq frontierMajorant_center_eq_publicAnswer)

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegral_bound
    (hmajorantIntegrable :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        IntervalIntegrable
          (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
            (0 : ℝ) 1)
    (hmajorantBound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredActualUpperBound := by
  apply frontierBMOCenteredActualUpperBound_of_majorant_integral_bound
  intro g hg
  rcases hg with ⟨hg_int, hg2_int, hphi, hmean, hsecondMoment, hvariance⟩
  have hg_adm :
      frontierBMOCenteredFunctionAdmissible g :=
    ⟨hg_int, hg2_int, hphi, hmean, hsecondMoment, hvariance⟩
  exact le_trans
    (frontierBMOCenteredObjectiveIntegral_le_boundaryMajorantIntegral
      g hphi (hmajorantIntegrable g hg_adm))
    (hmajorantBound g hg_adm)

theorem frontierBMOOriginalActualUpperBound_of_centered_majorant_integral_bound
    (hmajorization :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤ frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOOriginalActualUpperBound := by
  exact frontierBMOOriginalActualUpperBound_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_majorant_integral_bound hmajorization)

def frontierBMOCenteredBellmanMajorizationObligation : Prop :=
  ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    frontierBMOCenteredObjectiveIntegral g ≤ frontierMajorant 0 (1 / 12 : ℝ)

theorem frontierBMOCenteredBellmanMajorizationObligation_iff_objectiveIntegral_bound :
    frontierBMOCenteredBellmanMajorizationObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ) := by
  rfl

def frontierUnboundedNonsmoothBellmanUpperObligation : Prop :=
  ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    frontierBMOCenteredObjectiveIntegral g ≤
      frontierMajorant 0 (frontierEpsilon ^ 2)

theorem frontierUnboundedNonsmoothBellmanUpperObligation_iff_centeredBellmanMajorization :
    frontierUnboundedNonsmoothBellmanUpperObligation ↔
      frontierBMOCenteredBellmanMajorizationObligation := by
  constructor
  · intro hupper g hg
    rw [← frontierEpsilon_sq]
    exact hupper g hg
  · intro hmajorization g hg
    rw [frontierEpsilon_sq]
    exact hmajorization g hg

theorem frontierBMOCenteredBellmanMajorizationObligation_of_unboundedNonsmoothBellmanUpper
    (hupper : frontierUnboundedNonsmoothBellmanUpperObligation) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  exact
    frontierUnboundedNonsmoothBellmanUpperObligation_iff_centeredBellmanMajorization.mp
      hupper

def frontierBMOCenteredBoundaryMajorantIntegralObligation : Prop :=
  (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    IntervalIntegrable
      (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
        (0 : ℝ) 1) ∧
  (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
      frontierMajorant 0 (1 / 12 : ℝ))

def frontierBMOCenteredBoundaryMajorantJensenObligation : Prop :=
  (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    IntervalIntegrable
      (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
        (0 : ℝ) 1) ∧
  (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
      frontierMajorant
        (frontierBMOOriginalMeanIntegral g)
        (frontierBMOOriginalSecondMomentIntegral g))

def frontierBMOCenteredBoundaryMajorantJensenInequalityObligation : Prop :=
  ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
      frontierMajorant
        (frontierBMOOriginalMeanIntegral g)
        (frontierBMOOriginalSecondMomentIntegral g)

def frontierBMOCenteredBoundaryMajorantIntegrabilityObligation : Prop :=
  ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    IntervalIntegrable
      (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
        (0 : ℝ) 1

def frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation : Prop :=
  ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    IntervalIntegrable
      (fun t : ℝ ↦
        frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) volume
        (0 : ℝ) 1

def frontierBMOCenteredBoundaryMajorantGapCompensationObligation : Prop :=
  ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    frontierBMOCenteredObjectiveIntegral g +
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
      frontierMajorant
        (frontierBMOOriginalMeanIntegral g)
        (frontierBMOOriginalSecondMomentIntegral g)

def frontierBMOCenteredBoundaryMajorantCenterBoundObligation : Prop :=
  ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    frontierBMOCenteredObjectiveIntegral g +
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
      frontierMajorant 0 (1 / 12 : ℝ)

def frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation : Prop :=
  ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
      frontierMajorant 0 (1 / 12 : ℝ)

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_integral_bound :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) := by
  rfl

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_integral_bound
    (hbound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_integral_bound.mpr
      hbound

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_of_integral_bound
    (hbound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_integral_bound
      hbound

theorem frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation_unconditional :
    frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation := by
  intro g hg
  rcases hg with ⟨hg, _hg2, _hphi, _hmean, _hsecondMoment, _hvariance⟩
  refine IntervalIntegrable.mono_fun'
    (intervalIntegrable_const (c := (100 : ℝ))) ?_ ?_
  · simpa [Set.uIoc_of_le (by norm_num : (0 : ℝ) ≤ 1)] using
      frontierMajorant_boundary_gap_continuous.comp_aestronglyMeasurable
        hg.aestronglyMeasurable
  · filter_upwards with t
    rw [Real.norm_eq_abs]
    exact frontierMajorant_boundary_gap_abs_le_const (g t)

theorem frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_of_gap
    (hgap : frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation) :
    frontierBMOCenteredBoundaryMajorantIntegrabilityObligation := by
  intro g hg
  have hg_adm : frontierBMOCenteredFunctionAdmissible g := hg
  rcases hg with
    ⟨_hg, _hg2, hphi, _hmean, _hsecondMoment, _hvariance⟩
  have hsum :
      IntervalIntegrable
        (fun t : ℝ ↦
          frontierPhi (g t) +
            (frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)))
          volume (0 : ℝ) 1 :=
    hphi.add (hgap g hg_adm)
  convert hsum using 1
  ext t
  ring

theorem frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_unconditional :
    frontierBMOCenteredBoundaryMajorantIntegrabilityObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_of_gap
    frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation_unconditional

theorem frontierUnboundedNonsmoothBellmanUpperObligation_of_boundaryMajorantIntegralCenterBoundObligation
    (hbound : frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) :
    frontierUnboundedNonsmoothBellmanUpperObligation := by
  intro g hg
  rw [frontierEpsilon_sq]
  exact le_trans
    (frontierBMOCenteredObjectiveIntegral_le_boundaryMajorantIntegral
      g hg.2.2.1
      (frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_unconditional
        g hg))
    (hbound g hg)

theorem frontierUnboundedNonsmoothBellmanUpperObligation_unconditional_reduction_to_boundaryMajorantIntegralCenterBoundObligation :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation →
      frontierUnboundedNonsmoothBellmanUpperObligation := by
  exact
    frontierUnboundedNonsmoothBellmanUpperObligation_of_boundaryMajorantIntegralCenterBoundObligation

theorem frontierBMOCenteredBoundaryMajorantIntegral_eq_objective_add_gap
    (g : ℝ → ℝ) (hg : frontierBMOCenteredFunctionAdmissible g) :
    (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) =
      frontierBMOCenteredObjectiveIntegral g +
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) := by
  rcases hg with
    ⟨_hg, _hg2, hphi, _hmean, _hsecondMoment, _hvariance⟩
  rw [frontierBMOCenteredObjectiveIntegral]
  calc
    (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) =
        ∫ t in (0 : ℝ)..1,
          frontierPhi (g t) +
            (frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) := by
      apply intervalIntegral.integral_congr
      intro t _ht
      ring
    _ = (∫ t in (0 : ℝ)..1, frontierPhi (g t)) +
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) := by
      exact intervalIntegral.integral_add hphi
        (frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation_unconditional
          g ⟨_hg, _hg2, hphi, _hmean, _hsecondMoment, _hvariance⟩)

theorem frontierBMOCenteredBoundaryMajorantGapIntegral_le_const
    (g : ℝ → ℝ) (hg : frontierBMOCenteredFunctionAdmissible g) :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ 100 := by
  have hgap :
      IntervalIntegrable
        (fun t : ℝ ↦
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t))
        volume (0 : ℝ) 1 :=
    frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation_unconditional
      g hg
  have hconst :
      IntervalIntegrable (fun _ : ℝ ↦ (100 : ℝ)) volume (0 : ℝ) 1 :=
    intervalIntegrable_const
  have hmono :
      (∫ t in (0 : ℝ)..1,
        frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
        ∫ _t in (0 : ℝ)..1, (100 : ℝ) :=
    intervalIntegral.integral_mono (by norm_num) hgap hconst
      (fun t ↦ frontierMajorant_boundary_gap_le_const (g t))
  rw [intervalIntegral.integral_const] at hmono
  norm_num at hmono
  exact hmono

theorem frontierBMOCenteredBoundaryMajorantIntegral_le_objective_add_const
    (g : ℝ → ℝ) (hg : frontierBMOCenteredFunctionAdmissible g) :
    (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
      frontierBMOCenteredObjectiveIntegral g + 100 := by
  rw [frontierBMOCenteredBoundaryMajorantIntegral_eq_objective_add_gap g hg]
  linarith [frontierBMOCenteredBoundaryMajorantGapIntegral_le_const g hg]

theorem frontierBMOCenteredBoundaryMajorantGapIntegral_nonneg
    (g : ℝ → ℝ) (_hg : frontierBMOCenteredFunctionAdmissible g) :
    0 ≤
      (∫ t in (0 : ℝ)..1,
        frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) := by
  exact intervalIntegral.integral_nonneg (by norm_num)
    (fun t _ht ↦ frontierMajorant_boundary_gap_nonneg (g t))

theorem frontierBMOCenteredBoundaryMajorantGapIntegral_eq_zero_of_not_middle
    (g : ℝ → ℝ)
    (hnotMiddle :
      ∀ t : ℝ,
        ¬ (frontierCStar < g t + frontierEpsilon ∧
          g t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon)) :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) = 0 := by
  calc
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) =
        ∫ _t in (0 : ℝ)..1, (0 : ℝ) := by
          apply intervalIntegral.integral_congr
          intro t _ht
          exact frontierMajorant_boundary_gap_eq_zero_of_not_middle
            (g t) (hnotMiddle t)
    _ = 0 := by simp

theorem frontierBMOCenteredBoundaryMajorantGapIntegral_eq_zero_of_ae_not_middle
    (g : ℝ → ℝ)
    (hnotMiddle :
      ∀ᵐ t ∂volume,
        ¬ (frontierCStar < g t + frontierEpsilon ∧
          g t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon)) :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) = 0 := by
  calc
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) =
        ∫ _t in (0 : ℝ)..1, (0 : ℝ) := by
          apply intervalIntegral.integral_congr_ae
          filter_upwards [hnotMiddle] with t ht_not_middle _ht
          exact frontierMajorant_boundary_gap_eq_zero_of_not_middle
            (g t) ht_not_middle
    _ = 0 := by simp

theorem frontierBMOCenteredBoundaryMajorantGapCompensationObligation_of_gapless_objective_bound
    (hobjective :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant
            (frontierBMOOriginalMeanIntegral g)
            (frontierBMOOriginalSecondMomentIntegral g))
    (hgapless :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        ∀ t : ℝ,
          ¬ (frontierCStar < g t + frontierEpsilon ∧
            g t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon)) :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation := by
  intro g hg
  rw [frontierBMOCenteredBoundaryMajorantGapIntegral_eq_zero_of_not_middle
    g (hgapless g hg)]
  simpa using hobjective g hg

theorem frontierBMOCenteredBoundaryMajorantGapCompensationObligation_of_ae_gapless_objective_bound
    (hobjective :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant
            (frontierBMOOriginalMeanIntegral g)
            (frontierBMOOriginalSecondMomentIntegral g))
    (hgapless :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        ∀ᵐ t ∂volume,
          ¬ (frontierCStar < g t + frontierEpsilon ∧
            g t + frontierEpsilon ≤ frontierCStar + 2 * frontierEpsilon)) :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation := by
  intro g hg
  rw [frontierBMOCenteredBoundaryMajorantGapIntegral_eq_zero_of_ae_not_middle
    g (hgapless g hg)]
  simpa using hobjective g hg

theorem frontierBMOCenteredBoundaryMajorantCenterBoundObligation_of_gap_split
    (η : ℝ)
    (hobjective :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ) - η)
    (hgap :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ η) :
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation := by
  intro g hg
  linarith [hobjective g hg, hgap g hg]

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gap_split
    (η : ℝ)
    (hobjective :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ) - η)
    (hgap :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ η) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  intro g hg
  rw [frontierBMOCenteredBoundaryMajorantIntegral_eq_objective_add_gap g hg]
  linarith [hobjective g hg, hgap g hg]

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_gap_split :
    (∃ η : ℝ,
      (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ) - η) ∧
      (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ η)) →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  rintro ⟨η, hobjective, hgap⟩
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gap_split
      η hobjective hgap

theorem frontierCenteredLinearWitness_boundaryMajorantGapIntegral :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierCenteredLinearWitness t)
          ((frontierCenteredLinearWitness t) ^ 2) -
        frontierPhi (frontierCenteredLinearWitness t)) = 0 := by
  calc
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierCenteredLinearWitness t)
          ((frontierCenteredLinearWitness t) ^ 2) -
        frontierPhi (frontierCenteredLinearWitness t)) =
        ∫ _t in (0 : ℝ)..1, (0 : ℝ) := by
      apply intervalIntegral.integral_congr
      intro t ht
      rw [Set.uIcc_of_le (by norm_num : (0 : ℝ) ≤ 1)] at ht
      have hboundary :=
        frontierCenteredLinearWitness_boundaryMajorant_eq_phi_on_unit
          ht.1 ht.2
      simpa using sub_eq_zero.mpr hboundary
    _ = 0 := by simp

theorem frontierBMOCenteredBoundaryMajorantGapSplit_eta_bounds
    {η : ℝ}
    (hobjective :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ) - η)
    (hgap :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ η) :
    0 ≤ η ∧ η ≤ frontierMajorant 0 (1 / 12 : ℝ) := by
  constructor
  · have hlin_gap :=
      hgap frontierCenteredLinearWitness frontierCenteredLinearWitness_admissible
    rw [frontierCenteredLinearWitness_boundaryMajorantGapIntegral] at hlin_gap
    exact hlin_gap
  · have hlin_objective :=
      hobjective frontierCenteredLinearWitness frontierCenteredLinearWitness_admissible
    rw [frontierCenteredLinearWitness_objectiveIntegral] at hlin_objective
    linarith

theorem frontierBMOCenteredBoundaryMajorantGapSplit_eta_eq_zero
    {η : ℝ}
    (hobjective :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ) - η)
    (hgap :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ η) :
    η = 0 := by
  have hη_nonneg :
      0 ≤ η :=
    (frontierBMOCenteredBoundaryMajorantGapSplit_eta_bounds
      hobjective hgap).1
  have hopt :=
    hobjective frontierStoppedLogCupOptimizer
      (frontierStoppedLogCupOptimizer_centered_admissible_of_intervalVariance
        frontierStoppedLogCupOptimizer_intervalVariance_obligation)
  have hcenter :
      frontierMajorant 0 (1 / 12 : ℝ) = frontierStoppedLogCupObjective := by
    rw [← frontierEpsilon_sq, frontierMajorant_center_eq_stoppedLogCupObjective]
  rw [frontierStoppedLogCupOptimizer_objectiveIntegral, ← hcenter] at hopt
  exact le_antisymm (by linarith) hη_nonneg

theorem frontierBMOCenteredBoundaryMajorantGapSplit_no_positive_eta :
    ¬ ∃ η : ℝ,
      0 < η ∧
      (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ) - η) ∧
      (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ η) := by
  rintro ⟨η, hη_pos, hobjective, hgap⟩
  have hη_zero :
      η = 0 :=
    frontierBMOCenteredBoundaryMajorantGapSplit_eta_eq_zero
      hobjective hgap
  linarith

theorem frontierBMOCenteredBoundaryMajorantGapSplit_iff_zero_gapSplit :
    (∃ η : ℝ,
      (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ) - η) ∧
      (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ η)) ↔
      (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ)) ∧
      (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ 0) := by
  constructor
  · rintro ⟨η, hobjective, hgap⟩
    have hη_zero :
        η = 0 :=
      frontierBMOCenteredBoundaryMajorantGapSplit_eta_eq_zero
        hobjective hgap
    constructor
    · intro g hg
      have h := hobjective g hg
      rw [hη_zero] at h
      simpa using h
    · intro g hg
      have h := hgap g hg
      rwa [hη_zero] at h
  · rintro ⟨hobjective, hgap⟩
    refine ⟨0, ?_, ?_⟩
    · intro g hg
      simpa using hobjective g hg
    · intro g hg
      simpa using hgap g hg

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_zero_gapSplit
    (hobjective :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ))
    (hgap :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ 0) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gap_split
      0
      (by
        intro g hg
        simpa using hobjective g hg)
      hgap

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_zero_gapSplit :
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      frontierBMOCenteredObjectiveIntegral g ≤
        frontierMajorant 0 (1 / 12 : ℝ)) →
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      (∫ t in (0 : ℝ)..1,
        frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ 0) →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_zero_gapSplit

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_gapCompensation
    (hgapBound : frontierBMOCenteredBoundaryMajorantGapCompensationObligation) :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  intro g hg
  rw [frontierBMOCenteredBoundaryMajorantIntegral_eq_objective_add_gap g hg]
  exact hgapBound g hg

theorem frontierBMOCenteredBoundaryMajorantGapCompensationObligation_of_jensenInequality
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation := by
  intro g hg
  rw [← frontierBMOCenteredBoundaryMajorantIntegral_eq_objective_add_gap g hg]
  exact hjensen g hg

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_iff_gapCompensation :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation ↔
      frontierBMOCenteredBoundaryMajorantGapCompensationObligation := by
  constructor
  · exact frontierBMOCenteredBoundaryMajorantGapCompensationObligation_of_jensenInequality
  · exact frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_gapCompensation

theorem frontierBMOCenteredBoundaryMajorantGapCompensationObligation_iff_center_bound :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g +
            (∫ t in (0 : ℝ)..1,
              frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) := by
  constructor
  · intro hgap g hg
    have hmoments :
        frontierMajorant
            (frontierBMOOriginalMeanIntegral g)
            (frontierBMOOriginalSecondMomentIntegral g) =
          frontierMajorant 0 (1 / 12 : ℝ) := by
      rcases hg with
        ⟨_hg, _hg2, _hphi, hmean, hsecondMoment, _hvariance⟩
      rw [hmean, hsecondMoment]
    exact le_trans (hgap g hg) (le_of_eq hmoments)
  · intro hgap g hg
    have hmoments :
        frontierMajorant
            (frontierBMOOriginalMeanIntegral g)
            (frontierBMOOriginalSecondMomentIntegral g) =
          frontierMajorant 0 (1 / 12 : ℝ) := by
      rcases hg with
        ⟨_hg, _hg2, _hphi, hmean, hsecondMoment, _hvariance⟩
      rw [hmean, hsecondMoment]
    rw [hmoments]
    exact hgap g hg

theorem frontierBMOCenteredBoundaryMajorantGapCompensationObligation_iff_centerBoundObligation :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation ↔
      frontierBMOCenteredBoundaryMajorantCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantGapCompensationObligation_iff_center_bound

theorem frontierBMOCenteredBoundaryMajorantCenterBoundObligation_iff_gapCompensation :
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantGapCompensationObligation := by
  exact frontierBMOCenteredBoundaryMajorantGapCompensationObligation_iff_centerBoundObligation.symm

theorem frontierBMOCenteredBoundaryMajorantCenterBoundObligation_iff_boundaryMajorantIntegral_bound :
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) := by
  constructor
  · intro hcenter g hg
    rw [frontierBMOCenteredBoundaryMajorantIntegral_eq_objective_add_gap g hg]
    exact hcenter g hg
  · intro hbound g hg
    rw [← frontierBMOCenteredBoundaryMajorantIntegral_eq_objective_add_gap g hg]
    exact hbound g hg

theorem frontierBMOCenteredBoundaryMajorantCenterBoundObligation_iff_integralCenterBoundObligation :
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantCenterBoundObligation_iff_boundaryMajorantIntegral_bound

theorem frontierBMOCenteredBoundaryMajorantIntegral_bound_of_centerBoundObligation
    (hcenter : frontierBMOCenteredBoundaryMajorantCenterBoundObligation) :
    ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
        frontierMajorant 0 (1 / 12 : ℝ) := by
  exact
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation_iff_boundaryMajorantIntegral_bound.mp
      hcenter

theorem frontierBMOCenteredBoundaryMajorantCenterBoundObligation_of_boundaryMajorantIntegral_bound
    (hbound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation_iff_boundaryMajorantIntegral_bound.mpr
      hbound

theorem frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation_of_majorant
    (hmajorant : frontierBMOCenteredBoundaryMajorantIntegrabilityObligation) :
    frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation := by
  intro g hg
  have hg_adm : frontierBMOCenteredFunctionAdmissible g := hg
  rcases hg with
    ⟨_hg, _hg2, hphi, _hmean, _hsecondMoment, _hvariance⟩
  exact (hmajorant g hg_adm).sub hphi

theorem frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_iff_gap :
    frontierBMOCenteredBoundaryMajorantIntegrabilityObligation ↔
      frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation := by
  constructor
  · exact frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation_of_majorant
  · exact frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_of_gap

theorem frontierBMOCenteredBoundaryMajorantJensenObligation_of_gap_and_jensen
    (hgap : frontierBMOCenteredBoundaryMajorantGapIntegrabilityObligation)
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredBoundaryMajorantJensenObligation := by
  exact ⟨frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_of_gap hgap,
    hjensen⟩

theorem frontierBMOCenteredAdmissible_moments_majorant_eq_publicAnswer
    (g : ℝ → ℝ) (hg : frontierBMOCenteredFunctionAdmissible g) :
    frontierMajorant
        (frontierBMOOriginalMeanIntegral g)
        (frontierBMOOriginalSecondMomentIntegral g) =
      frontierBMOPublicAnswer := by
  rw [← frontierMajorant_center_eq_publicAnswer]
  rcases hg with ⟨_hg, _hg2, _hphi, hmean, hsecondMoment, _hvariance⟩
  rw [hmean, hsecondMoment]

theorem frontierBMOCenteredBoundaryMajorantJensenObligation_of_components
    (hmajorantIntegrable :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        IntervalIntegrable
          (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
            (0 : ℝ) 1)
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredBoundaryMajorantJensenObligation := by
  exact ⟨hmajorantIntegrable, hjensen⟩

theorem frontierBMOCenteredBoundaryMajorantJensenObligation_iff_components :
    frontierBMOCenteredBoundaryMajorantJensenObligation ↔
      frontierBMOCenteredBoundaryMajorantIntegrabilityObligation ∧
        frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  constructor
  · intro h
    exact h
  · intro h
    exact h

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_iff_center_bound :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) := by
  constructor
  · intro hjensen g hg
    have hg_adm : frontierBMOCenteredFunctionAdmissible g := hg
    rcases hg with
      ⟨_hg, _hg2, _hphi, hmean, hsecondMoment, _hvariance⟩
    have hmoments :
        frontierMajorant
            (frontierBMOOriginalMeanIntegral g)
            (frontierBMOOriginalSecondMomentIntegral g) =
          frontierMajorant 0 (1 / 12 : ℝ) := by
      rw [hmean, hsecondMoment]
    exact le_trans (hjensen g hg_adm) (le_of_eq hmoments)
  · intro hbound g hg
    have hg_adm : frontierBMOCenteredFunctionAdmissible g := hg
    rcases hg with
      ⟨_hg, _hg2, _hphi, hmean, hsecondMoment, _hvariance⟩
    have hmoments :
        frontierMajorant
            (frontierBMOOriginalMeanIntegral g)
            (frontierBMOOriginalSecondMomentIntegral g) =
          frontierMajorant 0 (1 / 12 : ℝ) := by
      rw [hmean, hsecondMoment]
    rw [hmoments]
    exact hbound g hg_adm

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_center_bound
    (hbound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_iff_center_bound.mpr
      hbound

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_jensenInequalityObligation :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_iff_center_bound.symm

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_jensenInequality
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_jensenInequalityObligation.mpr
      hjensen

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_integralCenterBound
    (hbound : frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_jensenInequalityObligation.mp
      hbound

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_boundaryMajorantJensenInequality :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_jensenInequality

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_jensenInequality_unconditional_target
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_jensenInequality
      hjensen

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_blocker :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_jensenInequalityObligation

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_unconditional_reduction_to_integralCenterBound :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation →
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_integralCenterBound

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gapCompensation
    (hgap : frontierBMOCenteredBoundaryMajorantGapCompensationObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_jensenInequality
    (frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_gapCompensation
      hgap)

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_gapCompensation :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gapCompensation

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_gapCompensation :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantGapCompensationObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_jensenInequalityObligation.trans
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_iff_gapCompensation

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_gap_center_bound :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g +
            (∫ t in (0 : ℝ)..1,
              frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_gapCompensation.trans
      frontierBMOCenteredBoundaryMajorantGapCompensationObligation_iff_center_bound

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_blocker_gap_center_bound :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g +
            (∫ t in (0 : ℝ)..1,
              frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_gap_center_bound

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_gap_budget :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) -
            frontierBMOCenteredObjectiveIntegral g := by
  constructor
  · intro hbound g hg
    have hcenter := hbound g hg
    rw [frontierBMOCenteredBoundaryMajorantIntegral_eq_objective_add_gap g hg]
      at hcenter
    linarith
  · intro hbudget g hg
    rw [frontierBMOCenteredBoundaryMajorantIntegral_eq_objective_add_gap g hg]
    linarith [hbudget g hg]

def frontierBMOCenteredBoundaryMajorantResidualBudgetObligation : Prop :=
  ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        frontierBMOCenteredObjectiveIntegral g

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_gap_budget :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) -
            frontierBMOCenteredObjectiveIntegral g := by
  rfl

theorem frontierBMOCenteredBoundaryMajorantResidualBudget_stoppedLogCupOptimizer :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierStoppedLogCupOptimizer t)
          ((frontierStoppedLogCupOptimizer t) ^ 2) -
        frontierPhi (frontierStoppedLogCupOptimizer t)) ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        frontierBMOCenteredObjectiveIntegral frontierStoppedLogCupOptimizer := by
  exact le_of_eq frontierStoppedLogCupOptimizer_boundaryMajorantResidualBudget_eq

theorem frontierBMOCenteredBoundaryMajorantResidualBudget_centeredLinearWitness :
    (∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierCenteredLinearWitness t)
          ((frontierCenteredLinearWitness t) ^ 2) -
        frontierPhi (frontierCenteredLinearWitness t)) ≤
      frontierMajorant 0 (1 / 12 : ℝ) -
        frontierBMOCenteredObjectiveIntegral frontierCenteredLinearWitness := by
  rw [frontierCenteredLinearWitness_boundaryMajorantGapIntegral,
    frontierCenteredLinearWitness_objectiveIntegral]
  simpa using frontierMajorant_center_nonneg

theorem frontierBMOCenteredBoundaryMajorantResidualBudget_contact_witnesses :
    ((∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierStoppedLogCupOptimizer t)
          ((frontierStoppedLogCupOptimizer t) ^ 2) -
        frontierPhi (frontierStoppedLogCupOptimizer t)) =
      frontierMajorant 0 (1 / 12 : ℝ) -
        frontierBMOCenteredObjectiveIntegral frontierStoppedLogCupOptimizer) ∧
    ((∫ t in (0 : ℝ)..1,
      frontierMajorant (frontierCenteredLinearWitness t)
          ((frontierCenteredLinearWitness t) ^ 2) -
        frontierPhi (frontierCenteredLinearWitness t)) =
      0) := by
  exact ⟨frontierStoppedLogCupOptimizer_boundaryMajorantResidualBudget_eq,
    frontierCenteredLinearWitness_boundaryMajorantGapIntegral⟩

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_integralCenterBound :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation ↔
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_gap_budget.symm

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_centerBound :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation ↔
      frontierBMOCenteredBoundaryMajorantCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_integralCenterBound.trans
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation_iff_integralCenterBoundObligation.symm

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget
    (hbudget : frontierBMOCenteredBoundaryMajorantResidualBudgetObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_integralCenterBound.mp
      hbudget

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_of_integralCenterBound
    (hbound : frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_integralCenterBound.mpr
      hbound

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_unconditional_of_integralCenterBound
    (hbound : frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_of_integralCenterBound
      hbound

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_jensenInequality :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation ↔
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_integralCenterBound.trans
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_jensenInequalityObligation

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_of_jensenInequality
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_jensenInequality.mpr
      hjensen

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_residualBudget
    (hbudget : frontierBMOCenteredBoundaryMajorantResidualBudgetObligation) :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_jensenInequality.mp
      hbudget

theorem frontierBMOCenteredBoundaryMajorantCenterBoundObligation_of_residualBudget
    (hbudget : frontierBMOCenteredBoundaryMajorantResidualBudgetObligation) :
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_centerBound.mp
      hbudget

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_of_centerBound
    (hcenter : frontierBMOCenteredBoundaryMajorantCenterBoundObligation) :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_centerBound.mpr
      hcenter

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_residualBudget :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_of_residualBudget
    (hbudget : frontierBMOCenteredBoundaryMajorantResidualBudgetObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget
      hbudget

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_blocker_residualBudget :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_integralCenterBound.symm

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_target_reduction_to_residualBudget :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_target_blocker :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_blocker_residualBudget

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_unconditional_reduction_to_target :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_unconditional_blocker_target :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation ↔
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_integralCenterBound

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_exact_blocker :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_blocker_residualBudget

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_unconditional_blocker_gap_budget :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) -
            frontierBMOCenteredObjectiveIntegral g := by
  exact frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_gap_budget

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_unconditional_reduction_to_gap_budget :
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      (∫ t in (0 : ℝ)..1,
        frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
        frontierMajorant 0 (1 / 12 : ℝ) -
          frontierBMOCenteredObjectiveIntegral g) →
      frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_gap_budget.mpr

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_of_zero_gapSplit
    (hobjective :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ))
    (hgap :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ 0) :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  intro g hg
  linarith [hobjective g hg, hgap g hg]

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_unconditional_reduction_to_zero_gapSplit :
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      frontierBMOCenteredObjectiveIntegral g ≤
        frontierMajorant 0 (1 / 12 : ℝ)) →
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      (∫ t in (0 : ℝ)..1,
        frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ 0) →
      frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_of_zero_gapSplit

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_blocker_gap_budget :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) -
            frontierBMOCenteredObjectiveIntegral g := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_gap_budget

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gap_budget
    (hbudget :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) -
            frontierBMOCenteredObjectiveIntegral g) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_gap_budget.mpr
      hbudget

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_gap_budget :
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      (∫ t in (0 : ℝ)..1,
        frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
        frontierMajorant 0 (1 / 12 : ℝ) -
          frontierBMOCenteredObjectiveIntegral g) →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gap_budget

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_unconditional_blocker_gap_center_bound :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation ↔
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g +
            (∫ t in (0 : ℝ)..1,
              frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ) := by
  exact
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_iff_gapCompensation.trans
      frontierBMOCenteredBoundaryMajorantGapCompensationObligation_iff_center_bound

theorem frontierBMOCenteredBoundaryMajorantGapCompensationObligation_iff_integralCenterBoundObligation :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation ↔
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_gapCompensation.symm

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_centerBound
    (hcenter : frontierBMOCenteredBoundaryMajorantCenterBoundObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation_iff_integralCenterBoundObligation.mp
      hcenter

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_boundary_quadratic_support
    (slope curvature : ℝ)
    (hsupport :
      ∀ x : ℝ,
        frontierMajorant x (x ^ 2) ≤
          frontierMajorant 0 (1 / 12 : ℝ) +
            slope * x + curvature * (x ^ 2 - (1 / 12 : ℝ))) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  intro g hg
  rcases hg with ⟨hg_int, hg2_int, hphi, hmean, hsecondMoment, hvariance⟩
  have hg_adm :
      frontierBMOCenteredFunctionAdmissible g :=
    ⟨hg_int, hg2_int, hphi, hmean, hsecondMoment, hvariance⟩
  let center : ℝ := frontierMajorant 0 (1 / 12 : ℝ)
  let q : ℝ → ℝ := fun t ↦
    center + slope * g t + curvature * ((g t) ^ 2 - (1 / 12 : ℝ))
  have hmajorantInt :
      IntervalIntegrable
        (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
          (0 : ℝ) 1 :=
    frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_unconditional
      g hg_adm
  have hqInt : IntervalIntegrable q volume (0 : ℝ) 1 := by
    have hlin : IntervalIntegrable (fun t : ℝ ↦ slope * g t) volume
        (0 : ℝ) 1 := hg_int.const_mul slope
    have hsqShift :
        IntervalIntegrable (fun t : ℝ ↦ (g t) ^ 2 - (1 / 12 : ℝ)) volume
          (0 : ℝ) 1 :=
      hg2_int.sub intervalIntegrable_const
    have hcurv :
        IntervalIntegrable
          (fun t : ℝ ↦ curvature * ((g t) ^ 2 - (1 / 12 : ℝ))) volume
            (0 : ℝ) 1 :=
      hsqShift.const_mul curvature
    exact ((intervalIntegrable_const (c := center)).add hlin).add hcurv
  have hmono :
      (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
        ∫ t in (0 : ℝ)..1, q t :=
    intervalIntegral.integral_mono (by norm_num) hmajorantInt hqInt
      (fun t ↦ hsupport (g t))
  have hq_eval :
      (∫ t in (0 : ℝ)..1, q t) = center := by
    have hlin : IntervalIntegrable (fun t : ℝ ↦ slope * g t) volume
        (0 : ℝ) 1 := hg_int.const_mul slope
    have hsqShift :
        IntervalIntegrable (fun t : ℝ ↦ (g t) ^ 2 - (1 / 12 : ℝ)) volume
          (0 : ℝ) 1 :=
      hg2_int.sub intervalIntegrable_const
    have hcurv :
        IntervalIntegrable
          (fun t : ℝ ↦ curvature * ((g t) ^ 2 - (1 / 12 : ℝ))) volume
            (0 : ℝ) 1 :=
      hsqShift.const_mul curvature
    rw [show q = fun t : ℝ ↦
        (center + slope * g t) +
          curvature * ((g t) ^ 2 - (1 / 12 : ℝ)) by rfl]
    rw [intervalIntegral.integral_add
      ((intervalIntegrable_const (c := center)).add hlin) hcurv]
    rw [intervalIntegral.integral_add (intervalIntegrable_const (c := center)) hlin]
    rw [intervalIntegral.integral_const, intervalIntegral.integral_const_mul,
      intervalIntegral.integral_const_mul]
    have hshift :
        (∫ t in (0 : ℝ)..1, (g t) ^ 2 - (1 / 12 : ℝ)) = 0 := by
      rw [intervalIntegral.integral_sub hg2_int intervalIntegrable_const,
        intervalIntegral.integral_const]
      rw [← frontierBMOOriginalSecondMomentIntegral, hsecondMoment]
      norm_num
    rw [hshift]
    rw [← frontierBMOOriginalMeanIntegral, hmean]
    simp
  exact le_trans hmono (le_of_eq hq_eval)

def frontierBoundaryMajorantQuadraticCenterSupportObligation : Prop :=
  ∃ slope curvature : ℝ,
    ∀ x : ℝ,
      frontierMajorant x (x ^ 2) ≤
        frontierMajorant 0 (1 / 12 : ℝ) +
          slope * x + curvature * (x ^ 2 - (1 / 12 : ℝ))

theorem frontierBoundaryMajorantQuadraticCenterSupportObligation_right_tail_bound
    (hsupport : frontierBoundaryMajorantQuadraticCenterSupportObligation) :
    ∃ slope curvature : ℝ,
      ∀ x : ℝ,
        frontierA ≤ x →
          frontierCStar + 2 * frontierEpsilon < x + frontierEpsilon →
            x ^ 3 + 2 * (x - frontierA) ≤
              frontierMajorant 0 (1 / 12 : ℝ) +
                slope * x + curvature * (x ^ 2 - (1 / 12 : ℝ)) := by
  rcases hsupport with ⟨slope, curvature, hsupport⟩
  refine ⟨slope, curvature, ?_⟩
  intro x hxA hxC
  have hright :
      frontierMajorant x (x ^ 2) = frontierPhi x :=
    frontierMajorant_right_boundary_eq x hxC hxA
  have hphi : frontierPhi x = x ^ 3 + 2 * (x - frontierA) :=
    frontierPhi_right_of_ge x hxA
  simpa [hright, hphi] using hsupport x

set_option maxHeartbeats 800000 in
theorem frontierBoundaryMajorantQuadraticCenterSupportObligation_false :
    ¬ frontierBoundaryMajorantQuadraticCenterSupportObligation := by
  rintro ⟨slope, curvature, hsupport⟩
  let center : ℝ := frontierMajorant 0 (1 / 12 : ℝ)
  let M : ℝ :=
    |slope| + |curvature| + |center| + |frontierA| +
      |frontierCStar| + |frontierEpsilon| + 1
  have hM_nonneg : 0 ≤ M := by
    dsimp [M]
    linarith [abs_nonneg slope, abs_nonneg curvature, abs_nonneg center,
      abs_nonneg frontierA, abs_nonneg frontierCStar, abs_nonneg frontierEpsilon]
  obtain ⟨n, hn⟩ :=
    exists_nat_gt
      (max (max (12 * M + 12) (frontierA + 1))
        (frontierCStar + frontierEpsilon + 1))
  let x : ℝ := n
  have hx_gt_big : 12 * M + 12 < x := by
    dsimp [x]
    exact lt_of_le_of_lt (le_trans (le_max_left _ _) (le_max_left _ _)) hn
  have hx_gt_A1 : frontierA + 1 < x := by
    dsimp [x]
    exact lt_of_le_of_lt (le_trans (le_max_right _ _) (le_max_left _ _)) hn
  have hx_gt_C1 : frontierCStar + frontierEpsilon + 1 < x := by
    dsimp [x]
    exact lt_of_le_of_lt (le_max_right _ _) hn
  have hx_pos : 0 < x := by
    have : (0 : ℝ) < frontierA + 1 := by norm_num [frontierA]
    linarith
  have hx_ge_one : 1 ≤ x := by linarith [hx_pos]
  have hx_ge_A : frontierA ≤ x := by linarith
  have hx_right : frontierCStar + 2 * frontierEpsilon < x + frontierEpsilon := by
    linarith
  have hsupport_x := hsupport x
  have hright_eq : frontierMajorant x (x ^ 2) = frontierPhi x :=
    frontierMajorant_right_boundary_eq x hx_right hx_ge_A
  have hphi_eq : frontierPhi x = x ^ 3 + 2 * (x - frontierA) :=
    frontierPhi_right_of_ge x hx_ge_A
  have hineq :
      x ^ 3 + 2 * (x - frontierA) ≤
        center + slope * x + curvature * (x ^ 2 - (1 / 12 : ℝ)) := by
    simpa [center, hright_eq, hphi_eq] using hsupport_x
  have hM_bound : M ≤ x / 12 := by linarith
  have hslope_le_M : slope ≤ M := by
    have hs : slope ≤ |slope| := le_abs_self slope
    dsimp [M]
    linarith [abs_nonneg curvature, abs_nonneg center, abs_nonneg frontierA,
      abs_nonneg frontierCStar, abs_nonneg frontierEpsilon]
  have hcurv_le_M : curvature ≤ M := by
    have hc : curvature ≤ |curvature| := le_abs_self curvature
    dsimp [M]
    linarith [abs_nonneg slope, abs_nonneg center, abs_nonneg frontierA,
      abs_nonneg frontierCStar, abs_nonneg frontierEpsilon]
  have hcenter_le_M : center ≤ M := by
    have hc : center ≤ |center| := le_abs_self center
    dsimp [M]
    linarith [abs_nonneg slope, abs_nonneg curvature, abs_nonneg frontierA,
      abs_nonneg frontierCStar, abs_nonneg frontierEpsilon]
  have hA_abs_le_M : |frontierA| ≤ M := by
    dsimp [M]
    linarith [abs_nonneg slope, abs_nonneg curvature, abs_nonneg center,
      abs_nonneg frontierCStar, abs_nonneg frontierEpsilon]
  have hA_le_M : frontierA ≤ M := le_trans (le_abs_self frontierA) hA_abs_le_M
  have hx2_nonneg : 0 ≤ x ^ 2 - (1 / 12 : ℝ) := by nlinarith [hx_ge_one]
  have hslope_term : slope * x ≤ M * x := by
    exact mul_le_mul_of_nonneg_right hslope_le_M (le_of_lt hx_pos)
  have hcurv_term :
      curvature * (x ^ 2 - (1 / 12 : ℝ)) ≤
        M * (x ^ 2 - (1 / 12 : ℝ)) := by
    exact mul_le_mul_of_nonneg_right hcurv_le_M hx2_nonneg
  have hquad_part : M * (x ^ 2 - (1 / 12 : ℝ)) ≤ M * x ^ 2 := by
    have hsub_le : x ^ 2 - (1 / 12 : ℝ) ≤ x ^ 2 := by norm_num
    exact mul_le_mul_of_nonneg_left hsub_le hM_nonneg
  have hright_upper :
      center + slope * x + curvature * (x ^ 2 - (1 / 12 : ℝ)) ≤
        x ^ 3 / 4 := by
    nlinarith [hcenter_le_M, hslope_term, hcurv_term, hquad_part, hM_bound,
      hM_nonneg, hx_ge_one]
  have hleft_lower : x ^ 3 / 2 ≤ x ^ 3 + 2 * (x - frontierA) := by
    nlinarith [hA_le_M, hM_bound, hM_nonneg, hx_ge_one]
  nlinarith

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_quadraticCenterSupport
    (hsupport : frontierBoundaryMajorantQuadraticCenterSupportObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  rcases hsupport with ⟨slope, curvature, hsupport⟩
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_boundary_quadratic_support
      slope curvature hsupport

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_quadraticCenterSupport :
    frontierBoundaryMajorantQuadraticCenterSupportObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_quadraticCenterSupport

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_next_route :
    (frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) ∧
      ¬ frontierBoundaryMajorantQuadraticCenterSupportObligation := by
  exact
    ⟨frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget,
      frontierBoundaryMajorantQuadraticCenterSupportObligation_false⟩

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_route :
    (frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantResidualBudgetObligation) ∧
      ¬ frontierBoundaryMajorantQuadraticCenterSupportObligation := by
  exact
    ⟨frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_exact_blocker,
      frontierBoundaryMajorantQuadraticCenterSupportObligation_false⟩

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_open_continuation_target :
    (frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) ∧
      (frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation →
        frontierBMOCenteredBoundaryMajorantResidualBudgetObligation) := by
  exact
    ⟨frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget,
      frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_of_integralCenterBound⟩

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_centerBound :
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_centerBound

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_unconditional_reduction_to_gapCompensation :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation →
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_gapCompensation

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_unconditional_exact_blocker :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation ↔
      frontierBMOCenteredBoundaryMajorantResidualBudgetObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_jensenInequality.symm

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_unconditional_reduction_to_residualBudget :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_residualBudget

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_unconditional_open_continuation_target :
    (frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) ∧
      (frontierBMOCenteredBoundaryMajorantJensenInequalityObligation →
        frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) := by
  exact
    ⟨frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_residualBudget,
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_jensenInequality⟩

theorem frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_unconditional_open_continuation_target :
    (frontierBMOCenteredBoundaryMajorantResidualBudgetObligation ↔
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) ∧
      (frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
        frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) := by
  exact
    ⟨frontierBMOCenteredBoundaryMajorantResidualBudgetObligation_iff_jensenInequality,
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget⟩

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gap_center_bound
    (hgap :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g +
            (∫ t in (0 : ℝ)..1,
              frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gapCompensation
    (frontierBMOCenteredBoundaryMajorantGapCompensationObligation_iff_center_bound.mpr
      hgap)

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_gap_center_bound :
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      frontierBMOCenteredObjectiveIntegral g +
          (∫ t in (0 : ℝ)..1,
            frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
        frontierMajorant 0 (1 / 12 : ℝ)) →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gap_center_bound

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_gap_center_bound
    (hgap :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g +
            (∫ t in (0 : ℝ)..1,
              frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_integralCenterBound
    (frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_gap_center_bound
      hgap)

theorem frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_unconditional_reduction_to_gap_center_bound :
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      frontierBMOCenteredObjectiveIntegral g +
          (∫ t in (0 : ℝ)..1,
            frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
        frontierMajorant 0 (1 / 12 : ℝ)) →
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  exact frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_gap_center_bound

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_integralObligation :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantIntegralObligation := by
  constructor
  · intro hbound
    exact ⟨frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_unconditional,
      hbound⟩
  · intro hboundary
    exact hboundary.2

theorem frontierBMOCenteredBoundaryMajorantIntegralObligation_of_integralCenterBound
    (hbound : frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_integralObligation.mp
      hbound

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_integralObligation
    (hboundary : frontierBMOCenteredBoundaryMajorantIntegralObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_integralObligation.mpr
      hboundary

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_integralObligation :
    frontierBMOCenteredBoundaryMajorantIntegralObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_integralObligation

theorem frontierBMOCenteredBoundaryMajorant_center_bound_of_jensenInequalityObligation
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
        frontierMajorant 0 (1 / 12 : ℝ) := by
  exact
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_iff_center_bound.mp
      hjensen

theorem frontierBMOCenteredBoundaryMajorantIntegralObligation_iff_jensen_components :
    frontierBMOCenteredBoundaryMajorantIntegralObligation ↔
      frontierBMOCenteredBoundaryMajorantIntegrabilityObligation ∧
        frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  constructor
  · intro hboundary
    rcases hboundary with ⟨hintegrable, hbound⟩
    exact ⟨hintegrable,
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_iff_center_bound.mpr
        hbound⟩
  · intro h
    rcases h with ⟨hintegrable, hjensen⟩
    exact ⟨hintegrable,
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_iff_center_bound.mp
        hjensen⟩

theorem frontierBMOCenteredBoundaryMajorantIntegralObligation_iff_jensenInequality :
    frontierBMOCenteredBoundaryMajorantIntegralObligation ↔
      frontierBMOCenteredBoundaryMajorantJensenInequalityObligation := by
  constructor
  · intro hboundary
    exact
      (frontierBMOCenteredBoundaryMajorantIntegralObligation_iff_jensen_components.mp
        hboundary).2
  · intro hjensen
    exact
      frontierBMOCenteredBoundaryMajorantIntegralObligation_iff_jensen_components.mpr
        ⟨frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_unconditional,
          hjensen⟩

theorem frontierBMOCenteredBoundaryMajorantJensenObligation_iff_integralObligation :
    frontierBMOCenteredBoundaryMajorantJensenObligation ↔
      frontierBMOCenteredBoundaryMajorantIntegralObligation := by
  constructor
  · intro hjensen
    rcases hjensen with ⟨hintegrable, hjensen_bound⟩
    refine ⟨hintegrable, ?_⟩
    intro g hg
    have hmoments :
        frontierMajorant
            (frontierBMOOriginalMeanIntegral g)
            (frontierBMOOriginalSecondMomentIntegral g) =
          frontierMajorant 0 (1 / 12 : ℝ) := by
      exact (frontierBMOCenteredAdmissible_moments_majorant_eq_publicAnswer g hg).trans
        frontierMajorant_center_eq_publicAnswer.symm
    exact le_trans (hjensen_bound g hg)
      (le_of_eq hmoments)
  · intro hboundary
    rcases hboundary with ⟨hintegrable, hbound⟩
    refine ⟨hintegrable, ?_⟩
    intro g hg
    have hmoments :
        frontierMajorant 0 (1 / 12 : ℝ) =
          frontierMajorant
            (frontierBMOOriginalMeanIntegral g)
            (frontierBMOOriginalSecondMomentIntegral g) := by
      exact frontierMajorant_center_eq_publicAnswer.trans
        (frontierBMOCenteredAdmissible_moments_majorant_eq_publicAnswer g hg).symm
    exact le_trans (hbound g hg) (le_of_eq hmoments)

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_jensenObligation :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation ↔
      frontierBMOCenteredBoundaryMajorantJensenObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_integralObligation.trans
      frontierBMOCenteredBoundaryMajorantJensenObligation_iff_integralObligation.symm

theorem frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_unconditional_reduction_to_boundaryMajorantJensen :
    frontierBMOCenteredBoundaryMajorantJensenObligation →
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation := by
  exact
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_iff_jensenObligation.mpr

theorem frontierBMOCenteredBoundaryMajorantIntegralObligation_of_jensen
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenObligation) :
    frontierBMOCenteredBoundaryMajorantIntegralObligation := by
  rcases hjensen with ⟨hmajorantIntegrable, hmajorantJensen⟩
  refine ⟨hmajorantIntegrable, ?_⟩
  intro g hg
  have hcenter :=
    frontierBMOCenteredAdmissible_moments_majorant_eq_publicAnswer g hg
  rw [frontierMajorant_center_eq_publicAnswer]
  exact le_trans (hmajorantJensen g hg) (le_of_eq hcenter)

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegral
    (hboundary : frontierBMOCenteredBoundaryMajorantIntegralObligation) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  intro g hg
  rcases hboundary with ⟨hmajorantIntegrable, hmajorantBound⟩
  exact le_trans
    (frontierBMOCenteredObjectiveIntegral_le_boundaryMajorantIntegral
      g hg.2.2.1 (hmajorantIntegrable g hg))
    (hmajorantBound g hg)

theorem frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization
    (hmajorization : frontierBMOCenteredBellmanMajorizationObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_majorant_integral_bound hmajorization

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantJensen
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenObligation) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  exact frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegral
    (frontierBMOCenteredBoundaryMajorantIntegralObligation_of_jensen hjensen)

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensen
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization
    (frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantJensen
      hjensen)

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensen_components
    (hmajorantIntegrable :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        IntervalIntegrable
          (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
            (0 : ℝ) 1)
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensen
    (frontierBMOCenteredBoundaryMajorantJensenObligation_of_components
      hmajorantIntegrable hjensen)

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenObligations
    (hintegrable : frontierBMOCenteredBoundaryMajorantIntegrabilityObligation)
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensen_components
    hintegrable hjensen

theorem frontierBMOOriginalActualUpperBound_of_centeredBellmanMajorization
    (hmajorization : frontierBMOCenteredBellmanMajorizationObligation) :
    frontierBMOOriginalActualUpperBound := by
  exact frontierBMOOriginalActualUpperBound_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization hmajorization)

theorem frontierBMOCenteredActualUpperBound_of_unboundedNonsmoothBellmanUpper
    (hupper : frontierUnboundedNonsmoothBellmanUpperObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization
    (frontierBMOCenteredBellmanMajorizationObligation_of_unboundedNonsmoothBellmanUpper
      hupper)

theorem frontierBMOOriginalActualUpperBound_of_unboundedNonsmoothBellmanUpper
    (hupper : frontierUnboundedNonsmoothBellmanUpperObligation) :
    frontierBMOOriginalActualUpperBound := by
  exact frontierBMOOriginalActualUpperBound_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_unboundedNonsmoothBellmanUpper
      hupper)

theorem frontierBMOCenteredBellmanMajorizationObligation_of_actualUpper
    (hupper : frontierBMOCenteredActualUpperBound) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  intro g hg
  rw [frontierMajorant_center_eq_publicAnswer]
  exact hupper (frontierBMOCenteredObjectiveIntegral g) ⟨g, hg, rfl⟩

theorem frontierBMOCenteredActualUpperBound_iff_centeredBellmanMajorization :
    frontierBMOCenteredActualUpperBound ↔
      frontierBMOCenteredBellmanMajorizationObligation := by
  constructor
  · exact frontierBMOCenteredBellmanMajorizationObligation_of_actualUpper
  · exact frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization

theorem frontierBMOCenteredBellmanMajorizationObligation_iff_actualUpper :
    frontierBMOCenteredBellmanMajorizationObligation ↔
      frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_iff_centeredBellmanMajorization.symm

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction :
    frontierBMOCenteredBellmanMajorizationObligation →
      frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization

theorem frontierBMOCenteredActualUpperBound_unconditional_blocker :
    frontierBMOCenteredActualUpperBound ↔
      frontierBMOCenteredBellmanMajorizationObligation := by
  exact frontierBMOCenteredActualUpperBound_iff_centeredBellmanMajorization

theorem frontierBMOCenteredActualUpperBound_iff_unboundedNonsmoothBellmanUpper :
    frontierBMOCenteredActualUpperBound ↔
      frontierUnboundedNonsmoothBellmanUpperObligation := by
  constructor
  · intro hupper
    exact
      frontierUnboundedNonsmoothBellmanUpperObligation_iff_centeredBellmanMajorization.mpr
        (frontierBMOCenteredBellmanMajorizationObligation_of_actualUpper hupper)
  · intro hupper
    exact frontierBMOCenteredActualUpperBound_of_unboundedNonsmoothBellmanUpper
      hupper

theorem frontierBMOCenteredActualUpperBound_unconditional_blocker_unboundedNonsmoothBellmanUpper :
    frontierBMOCenteredActualUpperBound ↔
      frontierUnboundedNonsmoothBellmanUpperObligation := by
  exact frontierBMOCenteredActualUpperBound_iff_unboundedNonsmoothBellmanUpper

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction_to_boundaryMajorantJensenObligations
    (hintegrable : frontierBMOCenteredBoundaryMajorantIntegrabilityObligation)
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenObligations
    hintegrable hjensen

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenInequality
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenObligations
    frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_unconditional
    hjensen

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantGapCompensation
    (hgapBound : frontierBMOCenteredBoundaryMajorantGapCompensationObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenInequality
    (frontierBMOCenteredBoundaryMajorantJensenInequalityObligation_of_gapCompensation
      hgapBound)

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantCenterBound
    (hcenterBound : frontierBMOCenteredBoundaryMajorantCenterBoundObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantGapCompensation
    (frontierBMOCenteredBoundaryMajorantCenterBoundObligation_iff_gapCompensation.mp
      hcenterBound)

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantCenterBound
    (hcenterBound : frontierBMOCenteredBoundaryMajorantCenterBoundObligation) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  intro g hg
  have hgap_nonneg :=
    frontierBMOCenteredBoundaryMajorantGapIntegral_nonneg g hg
  have hcenter := hcenterBound g hg
  linarith

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantGapSplit
    (η : ℝ)
    (hobjective :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤
          frontierMajorant 0 (1 / 12 : ℝ) - η)
    (hgap :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1,
          frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤ η) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantCenterBound
    (frontierBMOCenteredBoundaryMajorantCenterBoundObligation_of_gap_split
      η hobjective hgap)

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantGapCompensation :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation →
      frontierBMOCenteredBellmanMajorizationObligation := by
  intro hgapBound
  exact frontierBMOCenteredBellmanMajorizationObligation_of_actualUpper
    (frontierBMOCenteredActualUpperBound_of_boundaryMajorantGapCompensation
      hgapBound)

theorem frontierBMOCenteredActualUpperBound_blocker_boundaryMajorantGapCompensation :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation →
      frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantGapCompensation

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantJensenInequality_direct
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  intro g hg
  have hmajorantIntegrable :
      IntervalIntegrable
        (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
          (0 : ℝ) 1 :=
    frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_unconditional g hg
  exact le_trans
    (frontierBMOCenteredObjectiveIntegral_le_boundaryMajorantIntegral
      g hg.2.2.1 hmajorantIntegrable)
    (frontierBMOCenteredBoundaryMajorant_center_bound_of_jensenInequalityObligation
      hjensen g hg)

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantJensenInequality
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  exact
    frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantJensenInequality_direct
      hjensen

theorem frontierBMOCenteredBellmanMajorizationObligation_unconditional_reduction_to_boundaryMajorantJensenInequality :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation →
      frontierBMOCenteredBellmanMajorizationObligation := by
  exact frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantJensenInequality

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenInequality_unconditional
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenInequality
    hjensen

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction_to_boundaryMajorantJensenInequality :
    frontierBMOCenteredBoundaryMajorantJensenInequalityObligation →
      frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenInequality

theorem frontierBMOCenteredActualUpperBound_unconditional_of_boundaryMajorantJensenCenterBound
    (hjensen :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant
            (frontierBMOOriginalMeanIntegral g)
            (frontierBMOOriginalSecondMomentIntegral g)) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenInequality
    hjensen

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction_to_boundaryMajorantGapCompensation :
    frontierBMOCenteredBoundaryMajorantGapCompensationObligation →
      frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantGapCompensation

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction_to_gap_center_bound :
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      frontierBMOCenteredObjectiveIntegral g +
          (∫ t in (0 : ℝ)..1,
            frontierMajorant (g t) ((g t) ^ 2) - frontierPhi (g t)) ≤
        frontierMajorant 0 (1 / 12 : ℝ)) →
      frontierBMOCenteredActualUpperBound := by
  intro hgap
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantGapCompensation
    (frontierBMOCenteredBoundaryMajorantGapCompensationObligation_iff_center_bound.mpr
      hgap)

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction_to_boundaryMajorantCenterBound :
    frontierBMOCenteredBoundaryMajorantCenterBoundObligation →
      frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantCenterBound

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegralCenterBound
    (hbound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantCenterBound
    (frontierBMOCenteredBoundaryMajorantCenterBoundObligation_of_boundaryMajorantIntegral_bound
      hbound)

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction_to_boundaryMajorantIntegralCenterBound :
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
        frontierMajorant 0 (1 / 12 : ℝ)) →
      frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegralCenterBound

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegralObligation
    (hboundary : frontierBMOCenteredBoundaryMajorantIntegralObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization
    (frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegral
      hboundary)

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction_to_boundaryMajorantIntegralObligation :
    frontierBMOCenteredBoundaryMajorantIntegralObligation →
      frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegralObligation

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegralComponents
    (hmajorantIntegrable :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        IntervalIntegrable
          (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
            (0 : ℝ) 1)
    (hmajorantBound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  exact frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegral
    ⟨hmajorantIntegrable, hmajorantBound⟩

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegralCenterBound
    (hmajorantBound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  exact frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegralComponents
    frontierBMOCenteredBoundaryMajorantIntegrabilityObligation_unconditional
    hmajorantBound

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegralCenterBoundObligation
    (hmajorantBound :
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  exact
    frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegralCenterBound
      hmajorantBound

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegralCenterBoundObligation
    (hmajorantBound :
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization
    (frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegralCenterBoundObligation
      hmajorantBound)

theorem frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantResidualBudget
    (hbudget : frontierBMOCenteredBoundaryMajorantResidualBudgetObligation) :
    frontierBMOCenteredBellmanMajorizationObligation := by
  exact
    frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantIntegralCenterBoundObligation
      (frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget
        hbudget)

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantResidualBudget
    (hbudget : frontierBMOCenteredBoundaryMajorantResidualBudgetObligation) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization
    (frontierBMOCenteredBellmanMajorizationObligation_of_boundaryMajorantResidualBudget
      hbudget)

theorem frontierUnboundedNonsmoothBellmanUpperObligation_of_boundaryMajorantResidualBudget
    (hbudget : frontierBMOCenteredBoundaryMajorantResidualBudgetObligation) :
    frontierUnboundedNonsmoothBellmanUpperObligation := by
  exact
    frontierUnboundedNonsmoothBellmanUpperObligation_of_boundaryMajorantIntegralCenterBoundObligation
      (frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget
        hbudget)

theorem frontierBMOCenteredActualUpperBound_unconditional_reduction_to_boundaryMajorantResidualBudget :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
      frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantResidualBudget

theorem frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegralComponents
    (hmajorantIntegrable :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        IntervalIntegrable
          (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
            (0 : ℝ) 1)
    (hmajorantBound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOCenteredActualUpperBound := by
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegralObligation
    ⟨hmajorantIntegrable, hmajorantBound⟩

theorem frontierStoppedLogCupObjective_mem_centered_objectiveSet_of_optimizer
    (g : ℝ → ℝ)
    (hcentered : frontierBMOCenteredFunctionAdmissible g)
    (hvalue : frontierBMOCenteredObjectiveIntegral g = frontierStoppedLogCupObjective) :
    frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet := by
  refine ⟨g, hcentered, ?_⟩
  exact hvalue.symm

theorem frontierStoppedLogCupActualLowerBound_of_centered_optimizer
    (g : ℝ → ℝ)
    (hshifted : frontierBMOOriginalFunctionAdmissible (fun t ↦ g t - 10))
    (hg : IntervalIntegrable g volume (0 : ℝ) 1)
    (hg2 : IntervalIntegrable (fun t ↦ (g t) ^ 2) volume (0 : ℝ) 1)
    (hphi : IntervalIntegrable (fun t ↦ frontierPhi (g t)) volume (0 : ℝ) 1)
    (hmean : frontierBMOOriginalMeanIntegral g = 0)
    (hsecondMoment : frontierBMOOriginalSecondMomentIntegral g = (1 / 12 : ℝ))
    (hvalue : frontierBMOCenteredObjectiveIntegral g = frontierStoppedLogCupObjective) :
    frontierStoppedLogCupActualLowerBound := by
  have hmem :
      frontierBMOCenteredObjectiveIntegral g - (1985 / 2 : ℝ) ∈
        frontierBMOOriginalFunctionObjectiveSet :=
    frontier_centered_objective_shift_mem_original_objectiveSet
      g hshifted hg hg2 hphi hmean hsecondMoment
  rw [frontierStoppedLogCupActualLowerBound]
  convert hmem using 1
  rw [hvalue, frontierStoppedLogCupObjective_sub_centering_eq_originalSupremumValue]

theorem frontierStoppedLogCupActualLowerBound_of_centered_admissible_optimizer
    (g : ℝ → ℝ)
    (hcentered : frontierBMOCenteredFunctionAdmissible g)
    (hshifted : frontierBMOOriginalFunctionAdmissible (fun t ↦ g t - 10))
    (hvalue : frontierBMOCenteredObjectiveIntegral g = frontierStoppedLogCupObjective) :
    frontierStoppedLogCupActualLowerBound := by
  rcases hcentered with
    ⟨hg, hg2, hphi, hmean, hsecondMoment, _hvariance⟩
  exact frontierStoppedLogCupActualLowerBound_of_centered_optimizer
    g hshifted hg hg2 hphi hmean hsecondMoment hvalue

theorem frontierStoppedLogCupActualLowerBound_of_centered_optimizer_value
    (g : ℝ → ℝ)
    (hcentered : frontierBMOCenteredFunctionAdmissible g)
    (hvalue : frontierBMOCenteredObjectiveIntegral g = frontierStoppedLogCupObjective) :
    frontierStoppedLogCupActualLowerBound := by
  have hmem :
      frontierBMOCenteredObjectiveIntegral g - (1985 / 2 : ℝ) ∈
        frontierBMOOriginalFunctionObjectiveSet :=
    frontier_centered_objective_shift_mem_original_objectiveSet_of_admissible g hcentered
  rw [frontierStoppedLogCupActualLowerBound]
  convert hmem using 1
  rw [hvalue, frontierStoppedLogCupObjective_sub_centering_eq_originalSupremumValue]

theorem frontierStoppedLogCupActualLowerBound_of_centered_objectiveSet_mem
    (hmem : frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet) :
    frontierStoppedLogCupActualLowerBound := by
  rcases hmem with ⟨g, hcentered, hvalue⟩
  exact frontierStoppedLogCupActualLowerBound_of_centered_optimizer_value
    g hcentered hvalue.symm

theorem frontier_bmo_public_sample_original_unconditional_from_centered_obligations
    (hupper : frontierBMOCenteredActualUpperBound)
    (hlower : frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact frontierBMOOriginalFunctionBenchmarkValue_eq_publicAnswer_iff.mpr
    (frontierBMOOriginalFunctionSupremum_eq_value_of_actual_bounds
      (frontierBMOOriginalActualUpperBound_of_centered_upper hupper)
      (frontierStoppedLogCupActualLowerBound_of_centered_objectiveSet_mem hlower))

theorem frontier_bmo_public_sample_original_unconditional_reduction_to_actual_obligations :
    frontierBMOCenteredActualUpperBound →
      frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet →
        frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  intro hupper hlower
  exact frontier_bmo_public_sample_original_unconditional_from_centered_obligations
    hupper hlower

theorem frontier_bmo_public_sample_original_unconditional_of_centered_upper
    (hupper : frontierBMOCenteredActualUpperBound) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact frontier_bmo_public_sample_original_unconditional_from_centered_obligations
    hupper frontierStoppedLogCupObjective_mem_centered_objectiveSet

theorem frontier_bmo_public_sample_original_unconditional_of_centered_majorant_integral_bound
    (hmajorization :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        frontierBMOCenteredObjectiveIntegral g ≤ frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact frontier_bmo_public_sample_original_unconditional_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_majorant_integral_bound hmajorization)

theorem frontier_bmo_public_sample_original_unconditional_of_centeredBellmanMajorization
    (hmajorization : frontierBMOCenteredBellmanMajorizationObligation) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact frontier_bmo_public_sample_original_unconditional_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_centeredBellmanMajorization hmajorization)

theorem frontier_bmo_public_sample_original_unconditional_of_unboundedNonsmoothBellmanUpper
    (hupper : frontierUnboundedNonsmoothBellmanUpperObligation) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact frontier_bmo_public_sample_original_unconditional_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_unboundedNonsmoothBellmanUpper
      hupper)

theorem frontierBMOOriginalActualUpperBound_of_boundaryMajorantJensenInequality
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOOriginalActualUpperBound := by
  exact frontierBMOOriginalActualUpperBound_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenInequality
      hjensen)

theorem frontier_bmo_public_sample_original_unconditional_of_boundaryMajorantJensenInequality
    (hjensen : frontierBMOCenteredBoundaryMajorantJensenInequalityObligation) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact frontier_bmo_public_sample_original_unconditional_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_boundaryMajorantJensenInequality
      hjensen)

theorem frontierBMOCenteredActualUpperBound_reduction_to_boundaryMajorantIntegral_bound :
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      IntervalIntegrable
        (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
          (0 : ℝ) 1) →
    (∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
      (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
        frontierMajorant 0 (1 / 12 : ℝ)) →
    frontierBMOCenteredActualUpperBound := by
  intro hmajorantIntegrable hmajorantBound
  exact frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegral_bound
    hmajorantIntegrable hmajorantBound

theorem frontier_bmo_public_sample_original_unconditional_of_boundaryMajorantIntegral_bound
    (hmajorantIntegrable :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        IntervalIntegrable
          (fun t : ℝ ↦ frontierMajorant (g t) ((g t) ^ 2)) volume
            (0 : ℝ) 1)
    (hmajorantBound :
      ∀ g : ℝ → ℝ, frontierBMOCenteredFunctionAdmissible g →
        (∫ t in (0 : ℝ)..1, frontierMajorant (g t) ((g t) ^ 2)) ≤
          frontierMajorant 0 (1 / 12 : ℝ)) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact frontier_bmo_public_sample_original_unconditional_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegral_bound
      hmajorantIntegrable hmajorantBound)

theorem frontier_bmo_public_sample_original_unconditional_of_boundaryMajorantIntegralCenterBoundObligation
    (hmajorantBound :
      frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact frontier_bmo_public_sample_original_unconditional_of_centered_upper
    (frontierBMOCenteredActualUpperBound_of_boundaryMajorantIntegralCenterBoundObligation
      hmajorantBound)

theorem frontier_bmo_public_sample_original_unconditional_reduction_to_boundaryMajorantIntegralCenterBoundObligation :
    frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation →
      frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact
    frontier_bmo_public_sample_original_unconditional_of_boundaryMajorantIntegralCenterBoundObligation

theorem frontier_bmo_public_sample_original_unconditional_reduction_to_boundaryMajorantResidualBudget :
    frontierBMOCenteredBoundaryMajorantResidualBudgetObligation →
      frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  intro hbudget
  exact
    frontier_bmo_public_sample_original_unconditional_of_boundaryMajorantIntegralCenterBoundObligation
      (frontierBMOCenteredBoundaryMajorantIntegralCenterBoundObligation_of_residualBudget
        hbudget)

theorem frontier_bmo_public_sample_original_unconditional_missing_lower_obligation :
    frontierStoppedLogCupObjective = frontierBMOPublicAnswer ∧
      (frontierStoppedLogCupObjective ∈ frontierBMOCenteredFunctionObjectiveSet →
        frontierBMOPublicAnswer ∈ frontierBMOCenteredFunctionObjectiveSet) := by
  refine ⟨frontierStoppedLogCupObjective_eq_publicAnswer, ?_⟩
  intro hmem
  exact frontierBMOPublicAnswer_mem_centered_objectiveSet_of_stoppedLogCup hmem

theorem frontier_bmo_public_sample_original
    (frontier_unboundedNonsmoothBellmanUpper :
      frontierBMOOriginalActualUpperBound)
    (frontier_stoppedLogCupOptimizerLower :
      frontierStoppedLogCupActualLowerBound) :
    frontierBMOOriginalFunctionBenchmarkValue = frontierBMOPublicAnswer := by
  exact frontierBMOOriginalFunctionBenchmarkValue_eq_publicAnswer_iff.mpr
    (frontierBMOOriginalFunctionSupremum_eq_value_of_actual_bounds
      frontier_unboundedNonsmoothBellmanUpper frontier_stoppedLogCupOptimizerLower)

end

end AraLibrary.Analysis
