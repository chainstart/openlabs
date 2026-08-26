# Physics tool routing

Choose a bounded toolchain after stating the scientific question.

| Need | Preferred route | Required audit |
|---|---|---|
| Algebra, transforms, series, exact identities | SymPy; python-flint/mpmath for exact or arbitrary precision | assumptions, branch choices, independent numeric points |
| Convex/SDP bounds | CVXPY with Clarabel/SCS for prototypes | primal/dual residuals, solver/version, precision sensitivity; use a certifying solver when the claim requires rigor |
| Closed/open quantum dynamics | QuTiP and the vendored `qutip` Skill | Hilbert truncation, solver tolerances, trace/positivity, conserved quantities |
| ROOT/HEP event data | Uproot, Awkward, Vector, Hist, iminuit, pyhf | dataset record/version, event selections, weights/systematics, statistical model |
| Astronomy/cosmology | Astropy and the vendored `astropy` Skill | units, frames, time scales, WCS/IERS provenance, catalog selection |
| Gravitational-wave public metadata/data | GWOSC client/API; add GWPy only in a campaign-specific environment | detector/data-quality segments, sample rate, calibration release, PSD/window choices |
| Tabular/array storage | HDF5, xarray, pandas | schema, units, chunking, missing-data policy, hash-bound raw input |

Packages compute; Codex and the project protocol remain the controller. Do not introduce a second
autonomous orchestrator into a campaign. External collider generators, Wolfram kernels, cloud agents,
GPU clusters and licensed solvers are optional integrations that need a separate environment, license
review, explicit credentials boundary and a reproducible local receipt before use.
