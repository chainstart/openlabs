import Mathlib

noncomputable def pe (K : Type*) [Field K] :
    MvPolynomial (Fin 2) K ≃ₐ[K] Polynomial (Polynomial K) :=
  (MvPolynomial.finSuccEquiv K 1).trans
    (Polynomial.mapAlgEquiv
      ((MvPolynomial.renameEquiv K (Equiv.equivPUnit.{1, 1} (Fin 1))).trans
        (MvPolynomial.pUnitAlgEquiv.{_, 0} K)))

theorem pe_x1 (K : Type*) [Field K] :
    pe K (MvPolynomial.X 1) = Polynomial.C Polynomial.X := by
  unfold pe
  change Polynomial.map _ (MvPolynomial.finSuccEquiv K 1 (MvPolynomial.X 1)) = _
  rw [MvPolynomial.finSuccEquiv_apply]
  simp [MvPolynomial.renameEquiv_apply, MvPolynomial.pUnitAlgEquiv_apply]

theorem pe_x0 (K : Type*) [Field K] :
    pe K (MvPolynomial.X 0) = Polynomial.X := by
  unfold pe
  change Polynomial.map _ (MvPolynomial.finSuccEquiv K 1 (MvPolynomial.X 0)) = _
  rw [MvPolynomial.finSuccEquiv_apply]
  simp
