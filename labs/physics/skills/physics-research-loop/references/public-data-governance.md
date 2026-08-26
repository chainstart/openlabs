# Public physics data governance

Only acquire data whose public access and intended use are documented. Before analysis:

1. record the canonical HTTPS source, dataset/record/version identifier and provider;
2. record the applicable license or terms URL and the requested citation;
3. download with `tools/dataset_intake.py`, which writes under the artifacts experiment tree and
   emits an `openlabs.physics_dataset.v1` manifest;
4. preserve the raw bytes as immutable, record size and SHA-256, and derive cleaned data separately;
5. record calibration, quality masks, selection/cut flow, units, frames and transformations;
6. honor rate limits and do not scrape around an official API or bulk-download policy.

Never store access tokens, cookies, private URLs, embargoed data or personal data in the code or
state repositories. A public landing page does not imply every linked artifact has the same license.
If terms, citation, redistribution, calibration version or raw-data lineage are unclear, stop at
metadata discovery and record the blocker.
