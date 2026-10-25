"""Assemble the completed frozen pilot without promoting it to a paper."""
from common import *
import pandas as pd

accs=['GSE184316','GSE199949','GSE150910']
results={a:json.loads((ART/f'{a}_analysis.json').read_text()) for a in accs}
plan=json.loads((DATA/'plan_frozen_v1.json').read_text())
dev=results['GSE184316'];con=results['GSE199949'];context=results['GSE150910'];primary=con['primary_test']
def fmt(v):return f'{v:.3f}'
def ci(v,value='mean'):
 if not v or v.get('status','estimated')!='estimated':return '不可估计：'+(v or {}).get('reason','无资料')
 return f"{fmt(v[value])} [{fmt(v['ci95'][0])}, {fmt(v['ci95'][1])}]"
def event(a,name):
 r=results[a]['by_score'][name]['regional']['IPF']
 if 'exact_pair_event' in r:return ci(r['exact_pair_event'],'proportion')
 return ci(r['mean_pair_event_frequency'])
def metric_rows():
 rows=[]
 for cfg in plan['configurations']:
  name=cfg['name'];outcomes={}
  for a,r in results.items():
   if name in r['by_score']:
    outcomes[a]={'status':'estimated','result':r['by_score'][name],'results_path':str(ART/f'{a}_analysis.json'),'key':'by_score.'+name}
   else:
    full=name.startswith('age_sex_sampling_institution_adjusted_')
    if full and a!='GSE150910':continue
    prefix='age_sex_sampling_institution_adjusted_' if full else 'age_sex_adjusted_'
    score='abundance_'+name[len(prefix):];key=prefix[:-1];out=r['by_score'][score]['disease_effect'][key]
    outcomes[a]={'status':out['status'],'result':out,'key':f'by_score.{score}.disease_effect.{key}'}
  rows.append(dict(**cfg,attempted=True,seed=20261021,outcomes=outcomes,selection='All registered configurations reported; none selected by test performance'))
 return rows
ledger=json.loads((DATA/'trial_ledger.json').read_text())
ledger['at']=now();ledger['current']['configurations_run']=12;ledger['current']['configuration_outcomes']=metric_rows()
ledger['historical']['full_ledger_snapshot']=json.loads((OD/'final_trial_ledger.json').read_text())
ledger['historical']['full_results_snapshot']=json.loads((OLD/'RESULTS.json').read_text())
ledger['historical']['snapshot_note']='Read-only historical records copied verbatim as provenance. Their historical absolute paths are not assertions that original experiments exist here. Current readable source roots are supplied in result_reference and old_evidence_references.json.'
ledger['current']['candidates'][1]['status']='completed_bounded_frozen_bulk_pilot_not_paper_candidate'
ledger['confirmation_opened']=True;ledger['confirmation_open_record']=str(DATA/'confirmation_open.json');ledger['old_confirmation_opened']=False
ledger['historical_plus_current']={'candidate_assessments':5,'configuration_attempts':20,'note':'Historical2candidates/8configs retained, current3candidate assessments/12configs; repeated cohorts and bootstrap draws are not new model choices'}
ledger['software_failures']=[str(p) for p in sorted(DATA.glob('software_failure_*.json'))]
ledger['technical_adaptations']=[str(DATA/'parser_metadata_adaptation.json'),str(DATA/'parser_preexpression_review.json'),str(DATA/'sample_id_header_repair.json')]
ledger['paper_candidate']=False
for root in [DATA,ART]:atomic(root/'final_trial_ledger.json',ledger)

limitations=[
 '最近原始研究已直接研究区域异质性、ECM/上皮程序与跨研究复现；本轮仅提供预设分数的增量定量复核，创新性不足以支持二区论文候选。',
 '确认仅9名年龄已知成人IPF供体；区间较宽，未超过阈值不代表等价或区域差异不存在。',
 '开发四组织芯与确认中央/外周取样均为有目的的解剖/病理选择，两个频率的目标总体不同；不合并估计。',
 '确认存在两批建库但缺逐样本批次对应；区域差异可能包含技术影响，不能全部归为生物学。',
 '开发IPF供体均为男性；疾病比较的性别支持不完整，不能据年龄/性别调整宣称对女性IPF可推广。精确二项区间还依赖供体独立、同一取样机制等假设。',
 '静态基因长度近似与+1伪计数可能影响分数；不是准确转录本TPM。秩分数与丰度分数的阈值不可作为临床等效尺度比较。',
 '背景队列当前GEO元数据与原文部分协变量计数不一致，且有取样适应证、中心、批次与疾病混杂；调整不能建立因果。',
 '机构和原始实验来源支持开发与确认队列分离，未做基因型级重叠核查；背景队列不宣称与所有旧肺研究独立。',
 '固定程序沿用旧开发阶段外部指定基因，源研究总体发现已知；这是分析者预先冻结的新分数检验，不是前瞻性临床研究或独立实验室验证。',
 '不能由bulk分数识别细胞比例与细胞内状态贡献；旧单细胞来源门槛仍未通过。',
 '次要终点多，区间为描述性，未据其开展多重性控制后的阳性宣称；没有结果驱动的替换基因、阈值或模型。'
]
limitations.append('部分秩分数的开发事件全为零，非参数bootstrap因而退化为[0,0]；这不是总体频率为零的证据。确认采用精确区间，0/9仍有33.6%的95%上限。')
limitations.append('共同秩基因宇宙采用三队列公开基因标识交集，共16029基因；这是预定的测定覆盖交集而非按表达选择，但不应描述为完全未接触确认测定schema的严格归纳预测评估。')
bundle=dict(schema_version='openlabs.result_bundle.v1',project_id='biomed-replan-disease-cell-state-20261021',workstream_id='disease_cell_state',created_at_utc=now(),stage='exploratory_pilot',status='needs_replan',scientific_disposition='bounded_frozen_pilot_completed; no credible_zone2_paper_candidate; attribution_source_gate_unresolved',paper_candidate=False,research_question=plan['research_question'],independent_unit='lung_donor',primary_test=primary,metrics={'confirmation_pair_event_frequency':primary['proportion'],'confirmation_lower95':primary['ci95'][0],'confirmation_upper95':primary['ci95'][1],'confirmation_independent_adult_ipf_donors':primary['n'],'development_pair_event_frequency':dev['primary_development']['mean']},baselines={cfg['name']:cfg['outcomes'] for cfg in ledger['current']['configuration_outcomes']},trials_run=12,prior_trials_retained=8,source_datasets={a:{'adult_primary_donors':r['primary_adult_donors'],'adult_primary_samples':r['primary_adult_sample_count'],'analysis_path':str(ART/f'{a}_analysis.json'),'analysis_sha256':sha(ART/f'{a}_analysis.json')} for a,r in results.items()},limitations=limitations,run=dict(command='See REPRODUCE.md and per-stage provenance records; bulk_io.py score / analyse_bulk.py, then independent raw-row numeric reconstruction',code_revision='uncommitted isolated study files, no git commit/push',code_hashes={p.name:sha(p) for p in CODE.glob('*.py')},seed=20261021,environment_sha256=sha(ART/'environment_actual.json'),plan_sha256=sha(DATA/'plan_frozen_v1.json')),evidence={p.name:{'path':str(p),'sha256':sha(p)} for p in [ART/'manifest.jsonl',DATA/'split_and_independence_audit.json',ART/'all_estimates.csv',ART/'final_trial_ledger.json',ART/'integrity_review.json',DATA/'source_design_review.json',DATA/'measurement_interpretation_review.json']},confirmation=dict(new='GSE199949 once-only frozen analysis',open_record_sha256=sha(DATA/'confirmation_open.json'),old_GSE136831_opened=False),contract_status='adapted observational evidence bundle; genericthreewaypredictivepilotvalidator not run/pass; absolute cross-root references explicitly retained',next_decision='End current3candidate/12configuration budget. Any future attribution project requires source-resolved counts and a substantively new hypothesis with new independent evidence, not another score/threshold on this exposed holdout.')
for p in [ART/'output_semantic_audit.json',ART/'rank_and_secondary_numeric_review.json',DATA/'batch_supplement_review.json',DATA/'literature_result_review.json',DATA/'sample_id_header_repair.json',DATA/'source_registry_local.json',DATA/'gene_universe_frozen.json',*[ART/f'{a}_independent_numeric_review.json' for a in accs]]:
 bundle['evidence'][p.name]={'path':str(p),'sha256':sha(p)}
sources={x['source_id']:x for x in json.loads((DATA/'source_registry_local.json').read_text())['sources']}
for a in accs:
 fmt_audit=json.loads((DATA/f'{a}_format_audit.json').read_text())
 bundle['source_datasets'][a].update(source=sources[a],matrix_rows=fmt_audit['rows'],mapped_genes=fmt_audit['mapped_genes'],scored_samples=fmt_audit['samples'],payload_sha256=fmt_audit['payload_sha256'])
bundle['scientific_goal_completed']=False
bundle['bounded_experiment_completed']=True
bundle['review_plan_path']=str(DATA/'final_review_plan.json')
bundle['measurement_scope']='Observed paired score discrepancy under selected regions; no ground-truth sampling error, causal mechanism or clinical decision claim'
bundle['resource_snapshot']=json.loads((ART/'integrity_review.json').read_text())['resource_properties']
bundle['intake_accounted_bytes']=json.loads((ART/'integrity_review.json').read_text())['accounted_transfer_bytes']
for root in [ART,DATA]:atomic(root/'RESULTS.json',bundle)

lines=[
 '# 成人肺纤维化程序分数的区域取样差异：本轮研究报告',
 '',
 f"本轮完成了三个候选的来源评估，以及冻结的 bulk 程序分析和一次独立研究确认。**未形成2025中科院升级版大类二区及以上证据强度的论文候选，`paper_candidate=false`。** 确认主终点{'达到' if primary['supported'] else '未达到'}预设支持规则：{primary['k']}/{primary['n']}名年龄已知成人IPF供体的中央/外周平衡分数绝对差至少1单位，频率{100*primary['proportion']:.1f}%，精确95%区间{100*primary['ci95'][0]:.1f}%–{100*primary['ci95'][1]:.1f}%；规则要求区间下限大于25%。",
 '',
 '科学问题是：即使疾病组间程序差异跨研究出现，同一供体的选定肺区域能否产生足够大的分数差异，从而限制单区域分数作为供体表型？这是取样方案下的描述性问题，不能解释细胞比例与细胞内状态各自的贡献。旧归因问题的来源障碍没有被本轮绕过。',
 '',
 '## 1. 评估与候选裁定',
 '',
 '| 候选 | 实际证据与裁定 |',
 '|---|---|',
 '| C1 原始单细胞计数来源修复 | 官方作者仓库及HLCA转换代码未建立core h5与GEO计数的完整可核验链。新Range206探测实际711,522字节/60秒，开发大矩阵按该速度约25小时。来源门槛不通过，未开旧确认。 |',
 '| C2 官方小型bulk矩阵与区域分数差异 | 通过元数据、年龄、供体、基因及文件来源核验，执行本报告的冻结分析。创新性为有限增量，未认定为新方法。 |',
 '| C3 原作者供体×细胞类型汇总 | 检索的作者仓库、脚本和已有补充材料没有可核验的供体级表达汇总；DE表不能替代pseudobulk。此为有边界的未找到，不证明所有地方都不存在。 |',
 '',
 '上一轮2候选、8配置及阴性结果保留于总账。上一轮主比较改善未获支持，且同细胞共同基因计数差异未解释；本机未重验上一轮完整原始实验。新一轮3候选、12预登记配置；全部配置均尝试并报告，不因结果选择有利配置。',
 '',
 '## 2. 数据、独立单位和冻结边界',
 '',
 '| 队列 | 角色 | 实际单位及主分析资格 |',
 '|---|---|---|',
 '| GSE184316 | 开发 | 100区域样本、25供体：10IPF、6对照、9HP；每供体4区域。主疾病比较16成人供体，区域IPF终点n=10。 |',
 '| GSE199949 | 独立研究确认 | 42样本、21供体：13IPF、8对照，每供体2区域。4IPF年龄缺失预先排除；主分析9成人IPF、8对照，共34样本。 |',
 '| GSE150910 | 背景/协变量敏感性 | 288供体：103IPF、103对照、82HP。1IPF及1HP年龄缺失，均不进入成人分析；主疾病比较102IPF与103对照。不是区域确认数据。 |',
 '| GSE124685 | 排除的伪独立候选 | 10个IPF供体标签与GSE184316重复，另有1对照标签重合；未下载表达矩阵，未算作新确认。 |',
 '',
 '开发源为Leuven组织/Yale表达分析，确认原文明确University of Chicago及Gift of Hope组织来源；这些原始实验信息支持分离，GEO号不同本身不作独立性证明。背景队列的LTRC等来源可能与其他旧研究有联系，仅作背景。完整供体和年龄、性别冲突审计见data目录。性别冲突保留，整名供体从年龄/性别调整模型排除；配对主终点不需要性别。',
 '',
 f"方案在2026-10-21 14:05:42 UTC、任何新表达分数计算之前冻结，SHA-256 `{sha(DATA/'plan_frozen_v1.json')}`。共同基因宇宙仅从标识交集导出，未按表达或显著性筛选。确认一次打开时间见`confirmation_open.json`；旧GSE136831始终封存。",
 '',
 '## 3. 分数、对照与不确定性',
 '',
 'ECM固定为COL1A1、COL1A2、COL3A1；肺泡程序固定为AGER、SFTPA1、SFTPA2、SFTPB、SFTPC、ABCA3、NAPSA。两个程序分别取mean(log2(A+1))，主分数为ECM减肺泡。1单位是两组**加1后几何平均值之比**的两倍差，不是每个基因均两倍变化，也不是临床阈值。',
 '',
 '开发FPKM按有效映射基因的样本内总和转为百万尺度；两个计数队列用固定ExonLength后再做同样尺度化，属于近似长度标准化丰度，非精确转录本TPM。[singscore](https://doi.org/10.1186/s12859-018-2435-4)按固定共同基因宇宙、ties=min和发表的理论秩界限实现，源R代码版本及Python代数核查均留档；没有运行官方R包，也没有发明新评分方法。',
 '',
 '无伪计数且丰度为正时，平衡分数会抵消样本总量尺度，其区域配对差还会抵消固定基因长度常数；冻结的+1分数不具备严格的这种抵消性质，尤其在低值附近。本轮仅按预定诊断报告低丰度情况，没有另换伪计数或归一化寻找阳性。共同秩基因宇宙为16029个标识交集。',
 '',
 '开发每供体6对区域先平均，再对10供体等权平均，95%区间为2000次供体bootstrap。确认每供体仅1对，使用精确双侧Clopper–Pearson区间。ICC1保留负值，反映这些选定区域下的方差比。组间效应以供体均值计算；调整模型为供体级OLS、HC3标准误及残差自由度t区间。次要结果未作多重性校正后的阳性宣称。',
 '',
 '## 4. 全部预登记分数结果',
 '',
 '以下均为IPF；频率、ICC括号为95%区间。开发列是每供体6个区域对越界比例的等权均值，不是发生过任意一次越界的供体比例；确认列每供体只有1个中央/外周对。丰度三个分数的区域事件阈值为1，单向秩分数0.10，双向秩分数0.20；量纲不同，不能凭事件数称某方法更优。',
 '',
 '| 分数 | 开发事件频率 | 确认事件频率 | 开发ICC1 | 确认ICC1 |',
 '|---|---|---|---|---|'
]
for name in results['GSE184316']['by_score']:
 d=dev['by_score'][name]['regional']['IPF'];c=con['by_score'][name]['regional']['IPF']
 ic=lambda x:f"{fmt(x['icc1'])} [{fmt(x['icc1_ci95'][0])}, {fmt(x['icc1_ci95'][1])}]"
 lines.append(f"| {name} | {event('GSE184316',name)} | {event('GSE199949',name)} | {ic(d)} | {ic(c)} |")
control=con['by_score']['abundance_balance']['regional']['Control']['exact_pair_event']
lines+=['',f"三个队列均观察到ECM疾病差异为正、肺泡程序差异为负，属于已有疾病信号的复现。开发主终点为供体等权区域对比例45.0%，确认点估计55.6%，两者取样方式不同且确认区间较宽。确认对照也有{control['k']}/{control['n']}对越界，95%区间{100*control['ci95'][0]:.1f}%–{100*control['ci95'][1]:.1f}%；本轮没有预登记IPF与对照事件频率差的检验，不能据此称IPF特异。",'', '秩分数在确认中均为0/9事件，但精确95%上限仍为33.6%；开发的[0,0]是全零事件下bootstrap退化。不同分数的范围、程序含义和容许差不同，零事件不能用来宣称秩法更可靠。']
precision=json.loads((DATA/'precision_design_review.json').read_text())
lines+=['',f"样本量限制在表达分析前已量化：若真实事件频率为50%，当前n=9按同一规则通过的概率仅{100*precision['n9_power']['0.5']:.1f}%。同一Bernoulli取样假设下的未来设计示例n=30可达约81.9%，但这不是从当前结果反推的样本量，也不改变本轮阈值或纳入资格。",'','### 疾病组间效应与调整','','表内效应均为本队列IPF减对照，单位为对应分数；不跨平台合并绝对分数。','','| 队列/分数 | 未调整 | 年龄/性别调整 | 再加取样/机构 |','|---|---|---|---|']
for a,r in results.items():
 for name in ['abundance_ECM','abundance_alveolar','abundance_balance']:
  e=r['by_score'][name]['disease_effect'];full=e.get('age_sex_sampling_institution_adjusted')
  lines.append(f"| {a}/{name} | {ci(e['unadjusted'],'difference')} | {ci(e['age_sex_adjusted'],'disease_coefficient')} | {ci(full,'disease_coefficient') if full else '不适用'} |")
lines+=['','确认队列排除3名性别冲突供体后，调整模型含14名供体且全部为男性，按预定规则移除常量性别列；因此该列结果实际是男性子样本的年龄调整，不证明跨性别稳健。背景队列加入机构后的设计矩阵虽满秩，但单例NJH供体的杠杆值为1，HC3分母为零，三个全调整配置均记为不可估计；没有事后合并机构或替换误差模型。','','| 队列/秩分数 | 未调整IPF−对照及95%供体bootstrap区间 |','|---|---|']
for a,r in results.items():
 for name in ['singscore_ECM','singscore_alveolar','singscore_bidirectional']:
  lines.append(f"| {a}/{name} | {ci(r['by_score'][name]['disease_effect']['unadjusted'],'difference')} |")
lines+=['','秩分数的全部组间效应、中央/外周有向差、平均绝对区域差、表面密度斜率、HP描述性结果和naive区域标准误对照均完整写入每队列`*_analysis.json`；主要估计另汇总于`all_estimates.csv`。naive标准误仅展示伪重复的影响，不用于主推断。','','### 低丰度诊断','','| 队列 | ECM：任一区域>20%基因低于1的IPF供体 | 肺泡：同条件供体 |','|---|---|---|']
for a,r in results.items():
 e=r['assay_floor']['ECM'];v=r['assay_floor']['alveolar'];lines.append(f"| {a} | {e['ipf_donors_with_any_region_over20pct_floor']}/{e['ipf_donors']} | {v['ipf_donors_with_any_region_over20pct_floor']}/{v['ipf_donors']} |")
lines+=['','任一程序若超过20%的成人IPF供体触发该诊断，按冻结方案标记assay-floor limited，仍保留主结果；未依低值筛掉供体。即使未触发，亦不证明伪计数和尺度变换无影响。','','![冻结结果图](regional_programme_results.png)','','## 5. 最近工作与贡献边界','','[Meltzer2011](https://doi.org/10.1186/1755-8794-4-70)已比较肺叶间表达，六对样本的第一主成分ICC为0.474，整体更按供体聚类；这不是本10基因分数的ICC，也不证明所有区域读数不可靠。[McDonough2019](https://doi.org/10.1172/jci.insight.131597)和[DeSadeleer2022](https://doi.org/10.1164/rccm.202103-0569OC)已研究区域病理进展与分子程序；[Huang2023](https://doi.org/10.1136/bmjresp-2022-001391)就是本确认来源的中央/外周研究。','','[Kim2024](https://doi.org/10.1038/s41598-024-77469-5)已涉及这些胶原与表面活性蛋白的区域变化、空间信号与配对bulk的复现限制，并采用供体相关模型及SpatialDecon/reverseDecon评估组成影响。[2026跨研究预印本](https://doi.org/10.64898/2026.06.24.734263)及[matrisome原始研究](https://doi.org/10.3390/cimb48090951)进一步覆盖跨队列复现与供体阻断。区域异质性、胶原信号、跨队列方向一致本身均不能作新贡献。此次新增内容仅是沿用预设10基因、显式供体单位和预先设置容许差的定量复核，不能因某个p值或置信区间通过而升级论文。','','相关原始文献与方法（检索原响应、版本和差异审计见data目录`literature_audit.json`）：','']
for ref in json.loads((DATA/'literature_audit.json').read_text())['references']:
 lines.append(f"- [{ref['name']}](https://doi.org/{ref['doi']})：{'预印本' if ref['status']=='preprint' else '期刊论文'}。")
lines+=['','## 6. 限制、复核和停止判断','']+[f'{i+1}. {s}' for i,s in enumerate(limitations)]
lines+=['','独立数值复核从原矩阵逐行重建丰度分数，以二项尾概率反演确认区间，并用statsmodels验证调整效应及HC3+t区间。它是同一冻结分析的实现复核，不是第二次独立确认。全部完成payload哈希、冻结样本、旧证据只读哈希、资源cgroup及字节预算均另行检查。软件初期JSON布尔类型错误与表头适配均留档；不删除失败。','','本轮到此停止：三候选评估和12配置预算已完成，旧来源问题仍阻断归因结论，当前结果的创新性、取样可推广性及精度不足以支持目标论文。状态为`needs_replan`，表示原研究目标未实现；不是把进程退出当成论文完成。未来如再开展研究，需先解决可核验的原计数/供体汇总与新颖问题，并使用新的独立证据；本确认集此后已暴露，不能换阈值再确认。','','## 7. 复现与文件索引','','代码：`labs/biomed/studies/replan_disease_cell_state_20261021/`，操作命令及非覆盖规则见该目录`REPRODUCE.md`。解释器为`/home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python`，所有运行经`bin/openlabs-resource-guard --task-type cpu --`。本轮未更改共享环境或依赖锁，未用GPU、未派生代理、未触碰第三路。','','- `RESULTS.json`：主终点、12配置、限制、代码/环境/证据哈希。','- `final_trial_ledger.json`：历史与新轮全部候选、配置、失败和确认暴露。','- `manifest.jsonl`：来源、精确URL、条款、传输字节、SHA-256及失败。','- `*_scores.csv`、`*_donor_scores.csv`、`*_regional_pairs.csv`：冻结样本级、供体级、区域对输出。','- `*_analysis.json`、`all_estimates.csv`：完整基线、区间与可估计性。','- `*_independent_numeric_review.json`：原数据独立实现复核。','- `integrity_review.json`：文件与资源检查；`environment_actual.json`：实际解释器、包与锁哈希。','- data项目保留冻结方案、共同基因、供体划分、来源与文献审计，并同步最终状态。','','通用三分预测协议不覆盖当前观测设计，已明确采用自定义供体/研究审计，不声称通用pilot gate通过。没有选刊、投稿、付费、公开发布或git提交。']
lines+=['','### 实现修复与复核补记','','开发首次推断运行因样本ID列被Pandas重置成`index`而停止。初始评分与已写出的供体表保存在`failed_output_sample_id_header/`；修复只把列名恢复为`sample_id`，所有数据行逐字节一致。主评分公式未变，确认在修复及14项软件检查通过后才打开。确认后的主评分和统计代码哈希保持不变。另保留早期软件检查的JSON布尔序列化错误；这些都是实现失败，不是新增科学配置。','','后续使用独立的pandas排序核对三个队列的singscore，并用linregress核对已注册的表面密度斜率，均与主实现一致。旧报告、冻结文件、引用的旧代码/来源记录及旧补充包哈希均未改变。','','原文方法补充通过EuropePMC官方补充文件接口取得，只读取了方法PDF。它明确STAR2.5.3和GenCodeGRCh38release24及建库流程，但仍未列逐样本批次分配；不能据此证明区域与批次已经混杂，也不能证明每对样本的批次必然抵消。见data目录`batch_supplement_review.json`。','','### 输入与资源哈希摘要','']
integrity=json.loads((ART/'integrity_review.json').read_text())
properties=dict(line.split('=',1) for line in integrity['resource_properties'].splitlines() if '=' in line)
lines += [f"接入记账总量{integrity['accounted_transfer_bytes']:,}字节（{integrity['accounted_transfer_bytes']/1024**2:.2f} MiB），逐条manifest加原始来源Range探测的711,522字节精确对齐。服务内存峰值{int(properties['MemoryPeak'])/1024**2:.1f} MiB，硬限5 GiB、软限4 GiB，CPUQuota=200%，SwapMax=512 MiB、TasksMax=96。所有本路线下载和实验子任务均结束；最终复核时长及结案时间见`scientific_closeout.json`。",'','| 矩阵 | 实际字节 | SHA-256 |','|---|---:|---|']
manifest_records=[json.loads(x) for x in (ART/'manifest.jsonl').read_text().splitlines()]
for a in accs:
 h=bundle['source_datasets'][a]['payload_sha256'];record=next(r for r in manifest_records if r.get('sha256')==h and r.get('status')=='complete')
 lines.append(f"| {a} | {record['bytes']:,} | `{h}` |")
lines += ['',f"实际环境记录SHA-256：`{sha(ART/'environment_actual.json')}`。冻结后确认评分代码`bulk_io.py`：`{sha(CODE/'bulk_io.py')}`；统计代码`analyse_bulk.py`：`{sha(CODE/'analyse_bulk.py')}`。全部代码哈希与依赖锁哈希见`RESULTS.json`和`environment_actual.json`；最终交付索引见`delivery_manifest.json`。",'',f"小型data项目目录：`{DATA}`；artifact目录：`{ART}`。"]
(ART/'FINAL_REPORT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'report':str(ART/'FINAL_REPORT.md'),'primary':primary,'paper_candidate':False}))
