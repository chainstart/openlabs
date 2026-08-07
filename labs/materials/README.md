# OpenLabs materials laboratory

This directory contains the stable simulation, analysis, provenance, queue, and validation tools
migrated from matfactory, together with the OpenLabs materials research Skill. OpenLabs owns global
task leases and retries; matfactory's internal queues remain compatibility tools for its existing
LLZTO campaign and are not a second factory scheduler.

Small frozen protocols, structures, benchmark records, and manifests remain versioned here because
they are hash-bound scientific inputs and regression fixtures. New mutable runs, trajectories,
wavefunctions, model weights, and reports must be written to the sibling `openlabs-data` or
`openlabs-artifacts`
repository and returned through `openlabs.result_bundle.v1`.

The dependency-light suite can use the project environment. Simulation tests additionally require
the optional ASE, pymatgen, CHGNet, SciPy, and PyTorch stack. The original project overview is
retained as `README.legacy.md`.

The historical LLZTO `runs/` tree is not part of this public code repository. Ten upstream tests
bind directly to that roughly 23 GiB tree (or to its historical dependency lock), so OpenLabs
marks them as optional legacy-evidence integration checks. The default suite still runs every
code, algorithm, protocol-shape, and new structure-discovery test. After hydrating the exact
legacy evidence layout, opt into the additional checks with
`OPENLABS_RUN_MATFACTORY_LEGACY_EVIDENCE=1`.
