# Assay-transfer study: dated discovery audit

Checked 2026-10-21. Academic-search MCP is not mounted; discovery used web search of primary publisher articles, PubMed/PMC and author repositories. This is a bounded closest-work audit, not an exhaustive novelty claim.

* Landrum and Riniker (2024), [10.1021/acs.jcim.4c00049](https://doi.org/10.1021/acs.jcim.4c00049): same-target cross-assay IC50/Ki discrepancies and maximal metadata curation; author data are the proposed starting corpus. Repeating variability estimates is not new.
* Nelen et al. (2025), [10.1186/s13321-025-00956-y](https://doi.org/10.1186/s13321-025-00956-y): matched-pair relative activity transfer across assays. Merely claiming relative differences transfer better is not new.
* Arvidsson McShane et al. (2021), [10.1021/acs.jcim.1c00293](https://doi.org/10.1021/acs.jcim.1c00293): old-assay training/new-assay conformal calibration and assay-transition strategies; strongest overlap for basic calibration proposal. Proposed work cannot claim assay adaptation or new-assay calibration as novel.
* [Toward Assay-Aware Bioactivity Model(er)s](https://pmc.ncbi.nlm.nih.gov/articles/PMC12264928/) (2025): assay descriptors and multitask assay categories, scaffold splits.
* [ActFound](https://doi.org/10.1038/s42256-024-00876-w) (2024): pairwise meta-learning for cross-assay bioactivity. Simple transfer is not a new modeling contribution.
* [10.1016/j.compbiolchem.2026.109371](https://doi.org/10.1016/j.compbiolchem.2026.109371): ChEMBL37 six-target scaffold-shift uncertainty/conformal/risk-ranking benchmark. Ordinary scaffold CP work was rejected during selection because of this direct overlap.

Narrow candidate question: with a fixed small budget of paired measurements, does structure-only anchor selection improve same-molecule cross-assay translation on scaffolds absent from the anchors, relative to random anchors and matched-budget simple offset/affine baselines? Source-assay activity is explicitly known at inference. This is neither de novo molecular prediction nor biological discovery. Whether the evidence supports a publishable methodological result remains unestablished.

Data risk found in feasibility probes: one IC50 and matching Ki filename in the author repository decompressed identically. Endpoint filenames alone cannot be trusted. Use only one catalog, retain upstream release and verify representative actual assay measurement types against ChEMBL; never count duplicated endpoint exports as independent experiments. No author contact or external message has been sent.
