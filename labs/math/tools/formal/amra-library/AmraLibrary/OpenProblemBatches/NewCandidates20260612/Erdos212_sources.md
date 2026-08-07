# Erdos212 source notes

External sources referenced by the upstream proof route for the conditional
Bombieri-Lang consequence used in `Erdos212.lean`:

- R. Shaffaf, "On the rational distance problem", arXiv:1501.00159,
  https://arxiv.org/abs/1501.00159.
- J. Solymosi and F. de Zeeuw, "On a question of Erdős and Ulam",
  arXiv:0806.3095, https://arxiv.org/abs/0806.3095.

The Lean proof in this round does not formalize those papers. It proves the
downstream non-density theorem by composing the existing conditional
line-or-circle finite-exception wrapper with the existing non-density lemma.
