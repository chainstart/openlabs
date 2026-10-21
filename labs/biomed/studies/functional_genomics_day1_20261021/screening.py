"""Record the actual three-candidate audit; no synthetic candidate padding."""
import json,platform,importlib.metadata,shutil
from common import *

candidates=[
 dict(id='C1',topic='Protein abundance-independent functional loss',
      question='Can substitution chemistry predict abundance-normal activity loss across proteins beyond abundance alone?',
      recent_primary=[dict(doi='10.1038/s41467-026-74517-8',date='2026-06-22',role='direct nearest work')],
      data_access=dict(metadata='metadata/allostery-tree.json',official_repository='https://github.com/lehner-lab/allostery_pathogenicity',
                       examples=['data/vampseq/vampseq_ddg/GCK_mavedb/urn_mavedb_00000096-a-1_scores_activity.csv','data/vampseq/vampseq_ddg/GCK_mavedb/urn_mavedb_00000096-b-1_scores_abundance.csv'],
                       verification='GitHub official author tree API 200, exact paths and sizes saved; experimental payload not opened',
                       terms='Author repository LICENSE exists; upstream MaveDB scores require per-score-set terms, not inferred from code licence'),
      independent_unit='protein for transfer, residue position within protein; two proteins insufficient broad transfer evidence',
      falsification='No held-out-protein improvement over abundance-only relation, or no independent multi-protein panel',
      decision='stop',stop_reason='Direct 2026 paired activity/abundance analysis substantially covers the biological question; no verified additional independent protein panel today. No new model run.'),
 dict(id='C2',topic='Cross-cell portability of signed reporter orientation effects',
      question='Does signed forward-minus-reverse activity transfer from HepG2 to K562 and untouched WTC11 at unseen genomic loci beyond orientation-invariant and activity-only baselines?',
      recent_primary=[dict(doi='10.1038/s41586-024-08430-9',date='2025-01-15',role='source study, within-cell orientation analysis'),
                      dict(doi='10.1038/s41467-026-68780-y',date='2026-01-30',role='dual promoter-enhancer potential, K562'),
                      dict(doi='10.1186/s13059-025-03828-8',date='2025-11-03',role='assay comparison and orientation-aware calls'),
                      dict(doi='10.1038/s41467-025-56380-1',date='2025-01-25',role='endogenous superenhancer orientation, distinct scale')],
      data_access=dict(metadata=['metadata/ENCSR405QCT.json','metadata/ENCSR203UFY.json','metadata/ENCSR336MKI.json','metadata/ENCSR022GQD.json','metadata/ENCSR382BVV.json','metadata/ENCSR244FWB.json'],
                       verification='ENCODE official experiment APIs 200; released processed replicate TSV files 6–23 MB; public S3 object URLs explicitly supplied by official API',
                       accessions=['ENCSR022GQD','ENCSR382BVV','ENCSR244FWB'],
                       terms='https://www.encodeproject.org/help/citing-encode/; released ENCODE data unrestricted analysis with attribution; official snapshot retained'),
      independent_unit='DNA genomic locus, three paired culture contexts, three cultures each; same upstream study/library, not three independent studies or donors',
      falsification='Insufficient jointly measured paired orientations; no out-of-locus transfer; dependence-aware interval not excluding negligible gain; assay confounding prevents biological inference',
      decision='selected_for_bounded_pilot',stop_reason=None,
      novelty_boundary='Cross-cell signed orientation transfer is a narrow empirical extension, not established novelty. Mean orientation asymmetry, promoter/enhancer distinctions and endogenous orientation effects are already known. No new algorithm or mechanism claim.'),
 dict(id='C3',topic='Environment-specific regulatory dosage–fitness mapping in yeast',
      question='Can promoter-expression plasticity predict fitness-effect reversals under a held-out carbon source?',
      recent_primary=[dict(doi='10.1038/s41559-024-02582-7',date='2024-11-13',role='source and direct biological overlap'),
                      dict(doi='10.1093/molbev/msag203',date='2026-08-01',role='recent related cis/trans TDH3 evolution')],
      data_access=dict(url='https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41559-024-02582-7/MediaObjects/41559_2024_2582_MOESM3_ESM.xlsx',
                       verification='Official article HTML links exact Supplementary Data workbook; HEAD result separately retained if available',
                       raw_accessions=['FR-FCM-Z8EK','FR-FCM-Z8EQ'],terms='Source article open access CC BY 4.0; workbook linked supplementary material; no payload downloaded'),
      independent_unit='promoter allele/position within TDH3, environments not independent experiments across genes',
      falsification='No held-out-carbon prediction gain over environment-specific expression–fitness functions',
      decision='stop',stop_reason='The source paper already directly shows expression–fitness decoupling and environmental reversals. One promoter and four carbon sources do not support a broad new confirmation claim.')
]
atomic(PROJECT/'candidate-screen.json',dict(checked_at_utc=now(),candidate_count=3,max_candidates=6,candidates=candidates,
    search_limitations='No professional literature MCP tools mounted. Used official primary articles, ENCODE and author GitHub APIs, Europe PMC public API (12 records/query), and web discovery. Not an exhaustive systematic review.',
    selected='C2',target_policy='This campaign only: 2025 CAS upgraded major-category Zone 2 aspiration per latest user; no journal selected; no global change.'))
shutil.copyfile(CODE.parents[1]/'uv.lock',PROJECT/'environment.uv.lock')
atomic(PROJECT/'environment.json',dict(python=platform.python_version(),executable=__import__('sys').executable,
   distributions=sorted([(d.metadata['Name'],d.version) for d in importlib.metadata.distributions()]),
   repository_lock_sha256=sha(PROJECT/'environment.uv.lock'),threads=2,cgroup=Path('/proc/self/cgroup').read_text()))
(PROJECT/'README.md').write_text('''# 功能基因组学一天试点\n\n研究线仅执行公开数据计算研究。最新用户本轮目标为2025中科院升级版大类二区，不选具体期刊、不投稿或发布。\n\n已读取根AGENTS、biomed研究Skill、README、source registry、evidence contract及数据仓库AGENTS。旧bio-shift项目没有README.md/CHECKPOINT.md/SEARCH_LOG.md；已读代码README及continuation-decision.json。新campaign目录启动时不存在，当前文件是新建记录。原项目和测试结果保持只读。\n\n候选审计：candidate-screen.json。代码：labs/biomed/studies/functional_genomics_day1_20261021/。\n大文件：/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-functional-genomics-20261021/。\n截止时间：2026-10-22T00:10:00Z。paper_candidate始终默认false。\n''')
(PROJECT/'SEARCH_LOG.md').write_text('''# 检索记录（2026-10-21 UTC）\n\n执行nature-academic-search多来源流程，专业MCP未挂载，回退官方全文、Europe PMC API和网络发现。\n查询包括：2025/2026 deep mutational scanning independent assays abundance/activity；CRISPR enhancer replication；yeast expression fitness environment；lentiMPRA orientation cross-cell。\nEurope PMC精确查询与原始结果保存在metadata/europepmc-search-{0,1,2}.json及access记录。各次最多12条，检索有限。\n\n最近工作和停止理由见candidate-screen.json。三个方向实质不同，没有为凑满六个而增加弱候选。C1和C3因直接生物学覆盖、独立确认面板不足停止；C2仅选作有明确失败条件的试点。\n\n原始论文、条款、六个ENCODE实验元数据及GitHub树快照保存在artifact metadata目录并有SHA-256。旧CRISPR数据未打开。\n''')
(PROJECT/'CHECKPOINT.md').write_text('# 检查点\n\n资源隔离已核实：2CPU，MemoryHigh1536MiB/Max2048MiB，TasksMax96。\n三候选筛查完成，选择C2。当前仅取一个HepG2文件作格式核查，未执行结果比较。冻结方案待确认表格结构，预览行将剔除。\n')
status('candidate_screen_complete','C2: signed orientation portability across cells',
       'screening.py completed',[PROJECT/'candidate-screen.json',PROJECT/'environment.json'])
print('screened 3, selected C2 for schema feasibility')
