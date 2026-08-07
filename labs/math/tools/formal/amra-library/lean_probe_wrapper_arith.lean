import Mathlib.Data.Nat.Basic

example (d : Nat) (hnot : ¬ d <= 3) (hlower : d + 3 <= d + 2) : False := by
  exact (Nat.not_succ_le_self (d + 2)) (by
    simpa [Nat.add_assoc] using hlower)
