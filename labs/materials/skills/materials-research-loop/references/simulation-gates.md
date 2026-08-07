# Materials simulation gates

## Provenance gate

- Structure source, composition, occupancy realization, charge state, cell transform, and hash.
- Code, dependency, model-weight, pseudopotential, input, parameter, and random-seed versions.
- Experimental or literature comparator with sample context and measurement convention.

## Numerical gate

- Energy, force, stress, cell size, k-point, cutoff, timestep, and ensemble checks as applicable.
- Equilibration and production convergence under a rule fixed before inspecting the final outcome.
- Resource estimates and restart behavior demonstrated on a pilot.

## Scientific gate

- Independent preparations and uncertainty match the claimed population.
- Finite-size, initialization, temperature, volume, and model-domain sensitivities are addressed.
- A learned-potential result has an independent reference set outside its fitting/tuning evidence.
- Negative and unresolved points are not silently removed from fits.

## Promotion gate

- The exact claim is narrower than or equal to the verified evidence boundary.
- Reproduction regenerates the claim-bearing values and manifests from frozen inputs.
- Mechanism wording matches the design: correlation is not causation and a trajectory motif is not
  automatically an elementary mechanism.
