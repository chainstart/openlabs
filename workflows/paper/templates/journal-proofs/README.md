# Journal proofs

Select the article type in [journals.json](journals.json). Each wrapper compiles the same short ruler article. Inspect the single and spanning floats, captions, equation and cross-references. Run pdflatex twice with the official class and its dependencies on TEXINPUTS. The log prints SINGLE and DOUBLE in TeX points inside the floats. Multiply by 25.4/72.27 for millimetres. Measured dimensions drive the [figure profiles](../../figure-templates/style/profiles.json). Verify current submission options for the selected article type. Empty limits await primary evidence.

| Atlas layout | Official distribution retrieved 2026-11-22 | Class options used for the proof | Single / spanning (mm) | Official comparison |
|---|---|---|---:|---|
| Elsevier | [Elsevier class on CTAN](https://ctan.org/pkg/elsarticle) | final,5p | 88.57 / 183.46 | doc/elstest-5p.pdf |
| Springer | [Springer Nature author resources](https://www.springernature.com/gp/authors/campaigns/latex-author-support), December 2024 template | iicol,pdflatex,sn-basic,Numbered | 76 / 160 | sn-article.pdf (publisher example uses its selected column mode) |
| IEEE | [IEEEtran on CTAN](https://ctan.org/pkg/ieeetran) | journal | 88.57 / 181.35 | bare_jrnl.tex |
| Nature preview | [Nature figure specifications](https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/) | local article, twocolumn, 5 mm gutter | 89 / 183 | Preview uses the published figure widths. |

IEEE TII limits refer to regular research papers newly submitted since 1 January 2025. See the [society notice](https://www.ieee-ies.org/pubs/transactions-on-industrial-informatics). The Ap&SS guide contains different abstract ranges in its general and specific instructions. Verify applicability before enforcing a hard limit.
