"""Finalize the dated literature audit without opening research labels."""
from common import *

records=[
 dict(doi='10.1101/gr.270751.120',year=2021,
      title='Genome-wide strand asymmetry in massively parallel reporter activity favors genic strands',
      primary_url='https://genome.cshlp.org/content/31/5/866',pmcid='PMC8092006',
      checked_via='Publisher indexed abstract and methods/PDF; direct full web fetch inaccessible; PMC returned browser verification and was not bypassed',
      known='Cross-cell reproducible reporter strand asymmetry and sequence-driven predictions already reported.',
      implication='No novelty claim for general orientation conservation. Our conditional per-promoter transfer contrast is at most a narrow extension.'),
 dict(doi='10.1038/s41586-024-08430-9',year=2025,
      title='Massively parallel characterization of transcriptional regulatory elements',
      primary_url='https://www.nature.com/articles/s41586-024-08430-9',snapshot='metadata/agarwal2025.html',
      anchors=['Promoter properties and orientation effect','Extended Data Fig.3d','Joint library tested in HepG2, K562, and WTC11 cells'],
      known='Source study already measures paired orientations and cross-cell promoter correlations. Joint library is forward/sense only and selected partly on previous activities.',
      implication='Joint library excluded. Exact promoter overlap in original large libraries used; infer no new endogenous mechanism.'),
 dict(doi='10.1038/s41467-026-68780-y',year=2026,
      title='Dual promoter–enhancer activities reflect a unified regulatory logic',
      primary_url='https://www.nature.com/articles/s41467-026-68780-y',
      checked_via='Official Nature article, abstract/results/assay methods',
      known='Dual promoter/enhancer readouts and reciprocal activity in K562; not a matched cross-cell promoter contrast predictor.',
      implication='Does not support interpreting lentiMPRA directionality as endogenous promoter/enhancer duality.'),
 dict(doi='10.1186/s13059-025-03828-8',year=2025,
      title='Comprehensive evaluation of diverse massively parallel reporter assays to functionally characterize human enhancers genome-wide',
      primary_url='https://pmc.ncbi.nlm.nih.gov/articles/PMC12581240/',
      checked_via='Primary full-text indexed result; official publisher direct open failed once (500)',
      known='Uniform enhancer calls use orientation-aware filtering and assay-design comparisons.',
      implication='No novelty claim for orientation-aware reporting or general MPRA assay inconsistency.'),
 dict(doi='10.1038/s41467-025-56380-1',year=2025,
      title='The alpha-globin super-enhancer acts in an orientation-dependent manner',
      primary_url='https://www.nature.com/articles/s41467-025-56380-1',
      checked_via='Official Nature primary PDF indexed abstract',
      known='An endogenous super-enhancer inversion changes target regulation.',
      implication='Distinct perturbation/scale; a reporter contrast does not prove such a mechanism.'),
 dict(doi='10.1038/s41467-026-74517-8',year=2026,
      title='Allostery is a widespread cause of loss-of-function variant pathogenicity',
      primary_url='https://www.nature.com/articles/s41467-026-74517-8',snapshot='metadata/liao2026.html',
      known='Paired experimental activity and abundance residual framework in PTEN/GCK and broader model analyses.',
      implication='C1 stopped for direct overlap and lack of adequate new independent protein panel.'),
 dict(doi='10.1038/s41559-024-02582-7',year=2024,
      title='Plasticity and environment-specific relationships between gene expression and fitness in Saccharomyces cerevisiae',
      primary_url='https://www.nature.com/articles/s41559-024-02582-7',snapshot='metadata/siddiq2024.html',
      known='Directly maps TDH3 regulatory expression and fitness across four carbon sources.',
      implication='C3 stopped: proposed environmental reversal biology already directly studied; single promoter.'),
]
for r in records:
    r['checked_at_utc']=now()
    if 'snapshot' in r:r['snapshot_sha256']=sha(ART/r['snapshot'])
atomic(PROJECT/'literature-audit.json',dict(checked_at_utc=now(),records=records,
 search_scope='Limited targeted audit using primary sources and Europe PMC API, not exhaustive review. Professional literature MCP unavailable.',
 final_novelty_assessment='Generic cross-cell strand asymmetry is established. This pilot quantifies incremental individual-contrast portability after controlling activity and mean sense preference. Insufficient alone for a new paper or a Zone2 quality assertion.',
 selected_question_refinement='Before label comparisons, after identity-only design audit: shared exact 200nt promoter pairs, not arbitrary enhancer libraries. General enhancer portability is not tested. Original candidate record retained unchanged.'))
with (PROJECT/'SEARCH_LOG.md').open('a') as f:
    f.write('\n更新：发现Roberts等2021 (10.1101/gr.270751.120)直接覆盖一般跨细胞链偏差；Agarwal2025已有跨细胞启动子相关性。冻结前收窄为控制总体活性和正义链共同偏好后的个体对比迁移。此收窄在任何K562/WTC11数值比较前完成，属于待检验增量，不声称新颖性已成立。详见literature-audit.json。PMC浏览器验证未绕过。\n')
print('seven closest primary records, no novelty promotion')
