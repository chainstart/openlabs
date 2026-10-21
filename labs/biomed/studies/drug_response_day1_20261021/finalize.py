"""Finalize bounded feasibility/no-go records; verify immutable prior inputs."""
import json,os
from pathlib import Path
import pandas as pd
from audit import OUT,PROJECT,CODE,OLD,STATUS,save,sha,status

def main():
    initial=json.loads((OUT/'solubility-feasibility-results.json').read_text())
    c=initial['counts']
    ext=pd.read_csv(OUT/'external-identity-audit.csv')
    clean=pd.read_csv(OUT/'ochem-clean/OChem_Clean.tab',sep='\t')
    group=clean.groupby('SMILES').Reference.agg(lambda x:'|'.join(sorted(set(map(str,x)))))
    mapped=ext.SMILES.map(group)
    rawrefs=pd.read_csv(OUT/'ochem-curated/OChemCurated.tab',sep='\t')
    article_names=rawrefs[['ARTICLEID','Reference']].drop_duplicates()
    assert not article_names.ARTICLEID.duplicated().any()
    names=article_names.set_index('ARTICLEID').Reference.to_dict()
    via_identity=ext.article_ids.fillna('').map(lambda s:'|'.join(sorted({names.get(k,k) for k in s.split('|') if k})))
    source_counts=via_identity[ext.scaffold_disjoint].value_counts().to_dict()
    adjudication=dict(stage='feasibility_adjudication_after_official_clean_table',paper_candidate=False,models_fitted=0,confirmatory_evaluations=0,external_clean_rows=len(clean),external_source_labels=int(clean.Reference.nunique()),external_scaffold_disjoint_source_counts={str(k):int(v) for k,v in source_counts.items()},external_scaffold_disjoint_without_exact_clean_smiles_reference=int((ext.scaffold_disjoint & mapped.isna()).sum()),decision='NO_GO_FOR_FROZEN_INDEPENDENT_ORIGINAL_STUDY_CLAIM',primary_reason=f"Original measurement references remain missing in {c['training_rows_missing_original_reference']} of {c['published_training_rows']} training rows; named source labels often denote compilations rather than independent experiments. Neither source completeness nor upstream measurement independence was established.",correction_to_preliminary_reason='External reference linkage is largely recoverable. The separately acquired official OChem_Clean table supplies source labels. Do not interpret the preliminary wording about multiple possible references as a claim that all external provenance is missing or irrecoverable.',scope='A feasibility failure for this frozen question and these public deposits, not evidence that curation is ineffective, that prior authors erred, or that no publishable solubility project exists.',continue_only_if=['Recover original experimental-study identifiers for the paired-label training sample and external measured values, distinguishing compilations and predicted records.','Restrict to a justified matched-molecule correction comparison with adequate independently sourced measurement groups; freeze a new plan and uncertainty method before modeling.','Verify dataset-specific reuse basis beyond a repository software licence.','Establish a material question beyond published curation/ionization/overlap work; compare closest available methods fairly.'])
    save(OUT/'solubility-final-adjudication.json',adjudication)
    inputs=json.loads((OUT/'existing-input-hashes.json').read_text())
    changed=[p for p,h in inputs.items() if sha(Path(p))!=h]
    assert not changed,changed
    index=json.loads((OUT/'solubility-intake-index.json').read_text())
    for m in index:
        p=Path(m['artifact_uri'].removeprefix('file://'))
        assert p.stat().st_size==m['bytes'] and sha(p)==m['sha256']
    verification=dict(old_files_verified_unchanged=len(inputs),new_payloads_verified=len(index),new_intake_payload_bytes=sum(m['bytes'] for m in index),all_checks_passed=True,old_test_marker_preserved=True,models_fitted_this_worker=0,original_test_evaluations_this_worker=0)
    save(OUT/'final-verification.json',verification)
    candidates=[
      dict(id='C1',question='Drug-combination interaction portability conditional on monotherapy/dose context',unit='canonical unordered drug pair, cell model and original experiment/study',outcome_units='growth/inhibition percent and explicitly named synergy reference score; never interchanged with IC50',nearest=['10.1038/s42003-023-04783-5','10.1016/j.isci.2025.112622','10.1093/nar/gkab438','10.1186/s12859-026-06665-z'],exact_routes=['https://drugcomb.fimm.fi/jing/summary_v_1_5.csv','https://api.drugcomb.org/','https://wiki.nci.nih.gov/spaces/NCIDTPdata/pages/338237347/NCI-ALMANAC'],actual_access='DrugComb TLS EOF / web502; official NCI landing200 redirects to general data directory, linked NCI ALMANAC wiki403. No payload acquired; no bypass.',stop='Direct neighbors already address dose harmonization and monotherapy-derived prediction. No verified distinct contribution with available raw matrices and independent studies in this bounded screen.',models=0),
      dict(id='C2',question='Same-assay stereoisomer potency cliffs and representation identifiability',unit='fully specified stereoisomer pair within exact assay/endpoint/document, grouped by molecule family',outcome_units='separate pIC50/pKi/pKd endpoints; no mixed endpoint average',nearest=['10.1002/cmdc.201700798','10.26434/chemrxiv-2025-w3k4n','https://arxiv.org/abs/2604.07560'],exact_routes=['https://www.ebi.ac.uk/chembl/api/data/status.json','https://www.ebi.ac.uk/chembl/api/data/activity.json','https://www.ebi.ac.uk/chembl/api/data/molecule.json','https://chemistry-europe.onlinelibrary.wiley.com/doi/10.1002/cmdc.201700798'],actual_access='Official ChEMBL status200 confirms37 release2026-05-01. No activity bulk download/model trial: same-assay chiral cliff predictive study already published2018; source prior-data release23, not independent new validation.',stop='A straightforward re-run with ChEMBL37 or chirality-aware descriptors would repeat an established question. No sufficiently distinct falsifiable contribution identified before modeling.',models=0),
      dict(id='C3',question='External portability of model-assisted solubility-label curation, keeping molecule/features fixed',unit='standardized chemical structure plus original experimental reference; scaffold groups for chemical independence',outcome_units='log10 mol/L aqueous solubility; pH/temperature/thermodynamic endpoint must be explicit',nearest=['10.1186/s13321-025-01000-9','10.1038/s41597-024-03105-6','10.1038/s41597-022-01154-3','10.1021/acs.jcim.4c02399'],exact_routes=[m['source_url'] for m in index],actual_access='Six payloads intake/hash verified; workbook and external schema parsed, conservative chemical/scaffold exclusion executed; detailed counts in solubility-feasibility-results.json.',stop=adjudication['primary_reason'],models=0,selected_for_actual_validation=True)
    ]
    save(PROJECT/'candidate-ledger.json',dict(screened_distinct_new_candidates=3,ceiling=6,original_gdsc_is_audit_not_new_candidate=True,candidates=candidates,scope='Bounded targeted search, not exhaustive field exclusion. PRISM repeatability and generic DrEval benchmarking were rejected as extensions at literature stage, not promoted into independent stories.'))
    trials=[
      ['audit.py','completed0','Read-only hash/split/arithmetic reconstruction; no models'],
      ['access_probe.py','completed0','Per-endpoint failures retained in access-probes.json'],
      ['metadata.py','completed0','NCI wiki403 retained; source metadata200'],
      ['standalone NCI wiki GET','failed1','HTTP403; no retry bypass'],
      ['intake_solubility.py attempt1','failed1','Unregistered institutional storage redirect; four earlier intake manifests retained; failed readme directory preserved'],
      ['intake_solubility.py attempt2','completed0','Unique official-storage source added under lock; readme-v2 fetched'],
      ['solubility_schema.py initial','completed0','First data row inadvertently printed; exposure disclosed; subsequent version only prints headers'],
      ['solubility_feasibility.py','completed0','Actual chemical identity/provenance feasibility audit; no inferential efficacy tests'],
      ['intake_solubility.py attempt3','completed0','Official clean OChem provenance table acquired; earlier payloads reused and hash verified'],
      ['bounded per-source/ref counts probes','completed0','No external response values summarized; no models'],
      ['finalize.py','completed0_on_success','Final input immutability and provenance adjudication']]
    save(PROJECT/'trial-ledger.json',dict(model_configurations_attempted=0,seeds=[],scientific_efficacy_tests=0,software_and_feasibility_runs=trials,failed_and_excluded_records='HTTP/source failures in access-probes.json and metadata-probes.json; chemical exclusions in external-identity-audit.csv; no failed model trial suppressed.'))
    search='''# 有限检索记录（2026-10-21 UTC）

使用 biomed-research-loop 和 nature-academic-search multi-source-search；无专用 PubMed/CrossRef/arXiv MCP，以网络检索的官方原文和公开API补位。未做系统综述，不能用未发现近邻证明新颖性。以下为实际使用的查询组：

1. `10.1186/s13321-025-00972-y`; `10.1038/s42004-026-01916-9`; `drug response cross screen extrapolated IC50 supported concentration ranking reproducibility`。
2. `PRISM primary-screen-replicate-collapsed-logfold-change figshare`; `PRISM secondary-screen-dose-response-curve-parameters download`; `Harmonization and integration of pharmacogenomics screens data availability`; `drug combination synergy prediction monotherapy baseline leakage 2025 2026`。
3. `DrugComb download summary data API study ONeil ALMANAC synergy reproducibility`; `drug combination synergy reproducibility cross study monotherapy consistency benchmark`; `stereoisomer activity cliffs ChEMBL enantiomers 2025 2026`; `aqueous solubility pH temperature metadata benchmark leakage 2025 2026`。
4. `aqueous solubility pH dataset curated benchmark experimental conditions 2025 2026`; `stereochemistry activity cliffs ChEMBL enantiomer same assay benchmark`; `drugcomb download data license summary v1.5`。
5. `aqueous solubility pH temperature data curated open dataset 2025`; `drug synergy score sign disagreement monotherapy dose range cross study benchmark`。
6. `NCI-ALMANAC ComboCompoundNames download csv`; `NCI-ALMANAC ComboDrugGrowth zip`; `Chiral Cliffs dataset 2018 github`; `AqSolDB github curated-solubility-dataset.csv`。
7. `solubility model guided curation label selection prediction bias external validation Ulrich 2025`; `Towards the improvement of thermodynamic solubility prediction Llompart`; `model-assisted curation solubility bias`; `Boosting the predictive performance with aqueous solubility dataset curation`。
8. `The specification game MAX_CONC`; `Critical evaluation DrEval Zenodo`; `Chiral Cliffs 10.1002`。

原文/API核查：2025 Ulrich原文完整Methods/Results可读，作者承认按预测选择多标签可能有偏，不能将该承认当本研究发现；作者仓库固定commit并实际获取数据。2026 DrEval出版社原文可读，其简单对照和跨研究评价已建立。2026药敏协调文献通过PMC检索正文与PubMed42286248核对，DOI10.1093/bioinformatics/btag382；出版社/PMC浏览部分受限。2026 iDRR预印本10.64898/2026.04.29.721574仅检索正文摘要可读，直接打开403，未绕过。Chiral Cliffs以PubMed29749719核查。2024 Llompart出版社重定向失败，以官方数据仓库及原文检索摘要核对，未声称完整阅读正文。

原题新增近邻：2026协调工作比较全/截断浓度范围的跨平台指标，DOI10.1093/bioinformatics/btag382；其结果不由本工作重述为创新。PRISM迭代可靠性和泛用DRP弱基线审计未独立立项，前者还会与功能基因组学线形成同构故事。
'''
    (PROJECT/'SEARCH_LOG.md').write_text(search)
    report=f'''# 药物反应／化学信息学研究线最终报告

结论：**本轮 no-go，paper_candidate=false。未获得可声称达到2025中科院升级版大类二区论文水平的成果。** 已核验旧药敏试点，筛选3个实质不同的新备选（上限6），对最强的溶解度标签修正候选完成真实数据可行性验证。后者未通过预先冻结的原始测量来源门槛，故未训练模型、未开展效果确认。不把可行性审计称为新科学效应验证，也不声称已穷尽整个领域。研究提前停止，不空转至截止时间。

本线目标限于纯计算药物反应／化学信息学，与功能基因组学worker独立。未选刊、投稿、付费、公开发布或外发消息；不改全局分区政策，不改工厂SQLite。用户本次二区要求仅作为研究目标，未产生期刊推荐。

## 旧 GDSC 替代题审计

只读旧目录，不调用旧run_pilot评估入口。三个原始payload共50,730,000字节的大小/哈希全部通过；对原计划、代码、环境锁、划分和已存在预测进行复核。75,627配对、104官方药物名称组、960细胞系；训练28,442配对，原测试2,471配对/18药物组/187细胞。双轴样本标识无交叉，265行逐药物误差和主要宏平均可复算。最终重新核对{len(inputs)}个旧文件均未改变。没有重训练、再次执行原测试、删除测试标志或声称原标签未看。

原主策略的排序不一致率28.43%，相同覆盖率的源拟合点差距对照24.16%；差4.27个百分点，原条件药物bootstrap区间1.83–7.56个百分点，方向不利于支持规则。固定HGB相对identity的整体MAE改善0.0475，原区间[-0.1014,0.1742]；未建立可靠总体收益。目的地支持域内外的方向差异是已暴露、回顾性标签分层，不能作为源信息部署门槛或机制证据。单位为ln(µM) IC50，源拟合标签本来已知，这是同药同细胞的筛选翻译，不是未知新药预测。操作性区间不是真实删失界或统计CI；不同dose范围AUC不当作共同区间AUC。

差异判断：MAX_CONC和聚合评价问题见[2025 specification game](https://doi.org/10.1186/s13321-025-00972-y)；浓度协调见[2016研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC5239501/)；超dose处理见[2026基准](https://doi.org/10.1038/s42004-026-01916-9)。新检索的[2026协调研究](https://doi.org/10.1093/bioinformatics/btag382)和[DrEval](https://doi.org/10.1038/s41467-026-72903-w)进一步限制一般性创新空间。保留旧负结果；未用新措辞包装原题。

## 三个新候选及实际停止原因

| 候选 | 直接近邻／精确数据路线 | 单位、实际验证与停止原因 |
|---|---|---|
| C1 药物组合的单药条件与相互作用迁移 | [2023跨剂量协调](https://doi.org/10.1038/s42003-023-04783-5)、[2025超越协同评分](https://doi.org/10.1016/j.isci.2025.112622)、[2026冷启动基准](https://doi.org/10.1186/s12859-026-06665-z)；DrugComb summary_v_1_5.csv、api.drugcomb.org、NCI ALMANAC官方wiki，见candidate-ledger.json | 无序药物对×细胞×原实验；生长/抑制百分数和明确命名协同评分。DrugComb TLS EOF／web502；官方NCI入口200但实为通用目录，链接wiki403。近邻已有剂量协调与单药信息迁移，未有可核实的独立新问题和原始矩阵，停止。没有绕过访问限制。 |
| C2 同测定立体异构体活性悬崖 | [2018 Chiral Cliffs](https://doi.org/10.1002/cmdc.201700798)、[2025描述符预印本](https://doi.org/10.26434/chemrxiv-2025-w3k4n)；ChEMBL官方status/activity/molecule API | 立体明确分子对×精确assay×终点×document；各pIC50/pKi/pKd分开。官方status200核对ChEMBL37，2026-05-01发布。2018已研究同assay约3,800对，单纯换37版或描述符不足创新；未批量下载标签或训练。 |
| C3 模型辅助溶解度修正的外部迁移（最强备选） | [2025原文](https://doi.org/10.1186/s13321-025-01000-9)、[2024质量研究](https://doi.org/10.1038/s41597-024-03105-6)、[2022整理工作](https://doi.org/10.1038/s41597-022-01154-3)、[2025整理建模](https://doi.org/10.1021/acs.jcim.4c02399)；固定作者仓库commit及[官方数据DOI](https://doi.org/10.57745/CZVZIA) | 分子、骨架及原始测量文献；log10(mol/L)，不是药敏。实际取得六文件、解析工作簿、完成结构/骨架/来源审计；结果如下。来源门槛未通过，未进入模型比较。 |

PRISM重复实验风险过滤与泛用DRP简单基线审计只作为原题延伸被排除，不凑成新故事。完整有限检索词、直接来源、访问错误见SEARCH_LOG.md及JSON探测记录；无专用学术MCP，不声称系统综述或穷尽新颖性。

## 最强备选的冻结方案与实测规模

问题是“同分子、同特征下，使用模型辅助修正训练标签能否改善独立原始实验的外部误差”，而非再次发现整理标签可能有偏。2025作者已承认选择更靠近预测的标签可能有偏；本研究没有发现或指控其不当行为。原题从药敏转到化学标签构建，未与另一worker共享功能基因组学故事。

先冻结feasibility-plan.json及时间/哈希feasibility-freeze.json，再执行分子规范化与来源计数。门槛包括原始/修正标签的精确分子链接、原始文献与实验重用可排除、至少100个外部分子及5个原始独立来源，骨架不重叠确认至少50个分子及5个来源；未通过前不拟合。预计后续强简单对照为中位数、理化Ridge、Morgan随机森林，只有通过门槛才另冻具体模型/划分方案；本轮配置数0/12。

| 实际计数 | 数量 |
|---|---:|
| 作者dataset_split记录 | {c['published_training_rows']} |
| 有原始/使用标签且结构可处理的行 | {c['paired_original_curated_rows']} |
| 标签改变的行（非独立实验数） | {c['changed_paired_labels']} |
| 缺原始参考文献的训练行 | {c['training_rows_missing_original_reference']} |
| 保守结构键重复涉及的训练行 | {c['training_rows_with_duplicated_conservative_structure']} |
| OChemUnseen行／独特保守结构 | {c['external_rows']}／{c['external_unique_structures']} |
| 相对整个9,800行训练池结构不重叠的外部独特结构 | {c['external_structure_disjoint_unique']} |
| 进一步骨架不重叠的外部独特结构 | {c['external_scaffold_disjoint_unique']} |
| 官方OChem_Clean行／来源标签数 | {len(clean)}／{clean.Reference.nunique()} |

采用Cleanup、FragmentParent、去电荷、规范互变异构体、移除立体信息作为**保守排重**，不据此合并活性、断言盐/异构体溶解度相同或模糊匹配名称。所有无环化合物放同一骨架组。外部排除相对整个作者训练池（含无原始标签行），不是只对选中的有利子集。来源映射与所有排除标志在external-identity-audit.csv。

来源检查才是停止原因，不能把250个骨架分离分子的规模说成“不够50”。外部来源映射大部分可恢复；后取的OChem_Clean有Reference，因此初步结果里“多个可能来源”的表述只适用于少数映射，不能扩大为全体来源丢失。最终裁定见solubility-final-adjudication.json。主要障碍是7,503个训练分子的原始测量参考文献空缺，而具名参考中又有手册/汇编库；外部17个标签含EPI Suite、TEST、OPERA等集合。它们**不自动等于17项独立实验，也不因名称而自动判成预测值**。未重建全部原实验链，不能满足被冻结的“原始研究独立”主张。只保留有参考文献的部分会改变比较总体，且仍要区分汇编和原测量；不临时缩问题以通过门槛。

这是数据来源可行性no-go，不是“整理无效”、无效/等价检验、模型性能负结果或字段缺失即数据错误的结论。未做独立效果检验，所以没有新增效应区间或显著性结果；独特分子数不是独立实验数，重复测定/种子不当独立样本。未来若解决来源，仍需按真实依赖分组的不确定性及最近方法公平预算比较。

暴露记录：初版schema工具误打印每张工作表第一条数据，随后修为只输出表头。具体暴露已记入结果；作者原测试预测被识别为已暴露信息，未用于新模型选择，也不冒充新确认。外部表在schema阶段被载入以检查列与缺失率；没有计算其LogS分布或模型误差，不能宣称标签字节从未读取。所有本轮数据视为可行性开发资料，未来效果确认需另冻清晰的未用于选择的数据边界。

## 文件、许可、复现与资源

六文件实测{verification['new_intake_payload_bytes']:,}字节，每文件低于16MiB。源元数据另为小型JSON/HTML，远低于1GiB总下载及3GiB scratch预算。作者GitHub固定commit在access/ulrich_commit.json；dataset.xlsx SHA256为416375f45fb58806a67b7124f5ab40b54faa50f329669338244c579fad6f4af1。Dataverse固定DOI版本2.0及文件ID：156689、156688、569042、569048，清单含实际返回大小（API提供tab格式与metadata体积有细微差异，以实测为准）。每文件URL、release、时间、大小、SHA256及上游研究风险在各manifest.json。所有原始payload保持不变。

Dataverse实际元数据注明etalab2.0；作者仓库有MIT软件LICENSE，不能单靠该软件许可宣称实验数据无限制再分发。原期刊及AqSolDB/OChem源条款需保留；本轮只作内部公开数据研究审计，不发布原始数据或声称获得商业授权。共享source registry仅在指定flock下重读后原子添加两个唯一scoped条目，保留他人条目；第二个来自官方Dataverse跳转的机构存储host。首次该跳转被护栏拒绝的失败保留，未关闭检查或绕过403。

使用既有labs/biomed/.venv和原锁labs/biomed/uv.lock，不安装包、不执行CUDA、不派生代理。每次解释器/下载/处理均经CPU护栏，两线程上限；/proc/self/cgroup已核对在用户指定service内。处理中观察MemoryPeak约662MiB，未提升任何上限。最终无运行中的数据处理或训练子任务。

从/home/biostar/work/openlabs运行（所有写入都在指定新目录；已有payload由intake读取复用，不覆盖）：

```bash
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/drug_response_day1_20261021/audit.py
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/drug_response_day1_20261021/metadata.py
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/drug_response_day1_20261021/intake_solubility.py
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/drug_response_day1_20261021/solubility_schema.py
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/drug_response_day1_20261021/solubility_feasibility.py
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/drug_response_day1_20261021/finalize.py
```

这组命令重建审计，不重刷旧test。新机器先放置锁定环境与官方旧输入；实时网络错误可能变化，历史访问结果在access-probes.json、metadata-probes.json。全部科学/软件尝试、错误、schema暴露及0个模型配置在trial-ledger.json，未隐匿失败试验。输入/代码/锁/计划哈希在existing-input-hashes.json、solubility-feasibility-hashes.json及reproducibility-inventory.json；最终manifest、旧文件不变检查在final-verification.json。协议的通用pilot completion不适用该未建模feasibility工作，未伪造协议通过或结果指标。

继续条件是先补原始测量溯源、明确复用许可、确认区别于已知整理工作的实质问题，再在新冻结方案和独立确认边界下比较；本报告不承诺未来工作会执行或产出正结果。本轮在截止前提前终止，最后检查点及真实进程状态见research_status.json。
'''
    report_path=STATUS.parent/'FINAL_REPORT.md';report_path.write_text(report)
    (PROJECT/'FINAL_REPORT.md').write_text(report)
    (CODE/'README.md').write_text('''# Day-1 drug response evidence audit

Read-only audit of the already evaluated GDSC pilot and bounded screening of three distinct new candidates. The strongest solubility curation candidate underwent real identity/provenance feasibility analysis and did not pass its original-study independence gate. No models trained; no new confirmatory test. paper_candidate=false.

Scripts require the repository CPU resource guard and existing labs/biomed/.venv environment. See the self-contained FINAL_REPORT.md in the declared project workspace or day1 worker artifact directory for exact commands, scope, exposure, failures and sources. Do not invoke the old study's evaluation entry point.
''')
    inventory={}
    for root in [CODE,PROJECT,OUT]:
        for p in sorted(root.rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and not p.name.startswith('.') and p.name not in ['reproducibility-inventory.json','result-bundle.json']:inventory[str(p)]=dict(bytes=p.stat().st_size,sha256=sha(p))
    for p in [Path('/home/biostar/work/openlabs/labs/biomed/uv.lock'),Path('/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-drug-support-20261021/environment.uv.lock')]:inventory[str(p)]=dict(bytes=p.stat().st_size,sha256=sha(p))
    save(OUT/'reproducibility-inventory.json',inventory)
    save(PROJECT/'result-bundle.json',dict(schema_version='openlabs.result_bundle.v1',stage='feasibility_no_go',paper_candidate=False,result_paths=[str(OUT/'existing-evidence-audit.json'),str(OUT/'solubility-final-adjudication.json'),str(report_path)],sha256={str(p):sha(p) for p in [OUT/'existing-evidence-audit.json',OUT/'solubility-final-adjudication.json',report_path,OUT/'reproducibility-inventory.json']},not_protocol_certified=True))
    status('completed_no_go','Stopped early. Resume only with recovered original-measurement provenance and a new independently frozen substantive question.',[str(report_path),str(OUT/'final-verification.json'),str(OUT/'solubility-final-adjudication.json'),str(PROJECT/'result-bundle.json')])
    state=json.loads(STATUS.read_text());state['worker']['process_state']='experiment_commands_completed; no background research jobs; status writer exits after atomic save';state['worker']['last_command_exit_code']=0;state['completed_early']=True;state['models_fitted']=0;save(STATUS,state)
    print(json.dumps(dict(verification=verification,adjudication=adjudication,report=str(report_path)),indent=2))
if __name__=='__main__':main()
