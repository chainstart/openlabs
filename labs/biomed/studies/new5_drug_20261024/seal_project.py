from pathlib import Path
import json,hashlib,datetime,shutil,xml.etree.ElementTree as E
R=Path('/home/biostar/work/projects/openlabs/openlabs');P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024');C=Path(__file__).parent
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
def sha(f):return hashlib.sha256(Path(f).read_bytes()).hexdigest()
def write(name,obj):(P/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def ref(name):return {'path':name,'sha256':sha(P/name)}
now=datetime.datetime.now(datetime.timezone.utc).isoformat();a=json.loads((P/'RESULTS.json').read_text());b=json.loads((P/'EXTERNAL_RESULTS.json').read_text());c=json.loads((P/'CROSSNULL_DIAGNOSTIC_RESULTS.json').read_text());v=json.loads((P/'DETERMINISTIC_DELIVERY_VERIFICATION.json').read_text())
assert v['passed'] and a['trials_run']==7 and b['fixed_configurations']==7
registry=json.loads((R/'labs/biomed/registries/data_sources.json').read_text());source=json.loads((P/'source-registry-local.json').read_text());source['checked_at']='2026-10-24';sources=[source]+[x for x in registry['sources'] if x['source_id'] in ['publisher_supplementary_tables','pubchem']];write('source_registry_local.json',{'schema_version':'openlabs.biomed_sources.v1','checked_at':now,'scope':'Project-local source extension only; global registry unchanged.','sources':sources})
allman=[r['dataset'] for r in json.loads((P/'intake-index.json').read_text())]+[json.loads((P/'sanger-raw-intake.json').read_text())]+json.loads((P/'melanoma-intake-index.json').read_text())+[json.loads(Path(r['manifest']).read_text()) for r in json.loads((P/'EXTERNAL_CHEMICAL_QUALIFICATION.json').read_text())['compound_matches']]
(P/'datasets').mkdir(exist_ok=True);dsrefs=[]
for m in allman:
 name='datasets/'+m['dataset_id']+'.json';write(name,m);dsrefs.append(ref(name))
plan=json.loads((P/'PLAN_FROZEN.json').read_text());plan['original_frozen_plan']=ref('PLAN_FROZEN.json');plan['confirmatory_holdout']=json.dumps(plan['confirmatory_holdout'],ensure_ascii=False,sort_keys=True);plan['adapter_note']='Serialization-only adapter for native validator string field; original preregistration remains unchanged and hash-bound.';write('native-pilot-plan.json',plan)
write('project.json',{'schema_version':'openlabs.project.v1','project_id':P.name,'domain':'biology','lab_id':'biomed','protocol':{'id':'biomed-public-data-pilot','primary_skill':'biomed-research-loop'},'title':'药物组合的增长状态与单药活性条件能否跨实验迁移','status':'active','paper_candidate':False,'workstreams':[{'workstream_id':'growth_transport','state_path':'state.json'}],'manual_registration':{'registered_at':now,'research_authorized_by':'User2026-10-24 requested5newbioinformaticsprojects with4hourbudget andZone2contributionobjective.','timing':'Formal metadata written after executed pilots; frozen plans and sample boundaries precede model fitting. No claim of prior factory admission or task lease.','target_level':'2025CAS major-categoryZone2 scientific contribution target; no journal selected.'}})
write('state.json',{'schema_version':'openlabs.biomed_pilot_state.v1','project_id':P.name,'workstream_id':'growth_transport','status':'completed','paper_candidate':False,'research_question':plan['research_question'],'independent_unit':'cell_line','next_experiment':'Do not retune exposed heldouts. Complete fresh independent scientific review of frozen review input; route deprioritized unless a new independently testable mechanism/data source is justified.','plan':ref('native-pilot-plan.json'),'environment':ref('environment.json'),'datasets':dsrefs,'evidence':[ref(x) for x in ['RESULTS.json','EXTERNAL_RESULTS.json','CROSSNULL_DIAGNOSTIC_RESULTS.json','DETERMINISTIC_DELIVERY_VERIFICATION.json']],'claims':[{'status':'provisional','text':'The frozen growth-state/pathway model did not improve heldout pair-cell-new-screen prediction by the preregistered5% criterion; this doesnot refute all possible growth-aware mechanisms.'}],'split_audit':ref('split-audit-retained.json'),'results':ref('RESULTS.json')})
write('research_state.json',{'project_id':P.name,'updated_at':now,'status':'needs_replan','scientific_disposition':'deprioritize after two unsupported frozen calibration mechanisms','paper_candidate':False,'q2_target_reached':False,'independent_scientific_review_completed':False,'experiments':[{'id':'C1_growth_state','status':'completed','fixed_configurations':7,'result':ref('RESULTS.json')},{'id':'C2_activity_coordinate_external','status':'completed','fixed_configurations':7,'result':ref('EXTERNAL_RESULTS.json')},{'id':'D1_crossnull','status':'completed','new_model_fits':0,'not_new_confirmation':True,'result':ref('CROSSNULL_DIAGNOSTIC_RESULTS.json')}],'actual_default_data_used':False,'existing_five_ready_manuscripts_modified':False,'next_action':{'objective':'Fresh blank independent scientific audit of the declared frozen code, data provenance, unit identities, null construction and negative-result scope; do not treat deterministic gate as scientific approval.','agent_role':'reviewer','session_mode':'fresh','handoff_kind':'role_handoff','resources':{'cpu_threads':2,'memory_mib':4096,'scratch_mib':2048}}})
write('SOFTWARE_AND_METADATA_CORRECTIONS.json',{'preserve_original_scientific_plans_and_negative_results':True,'items':[{'issue':'pip absent in uv-managed environment; follow-up one-line export quoting error','resolution':'importlib.metadata exact installed-version export and uv.lockSHA; no science or frozen sample change.'},{'issue':'Missing openpyxl dependency inshared environment','resolution':'Stdlib XML/ZIP reader; no shared environment installation/change.'},{'issue':'Original static publisherCDN TLS EOF and large archive range timeout','resolution':'Official media.springernature.com same linked supplemental files downloaded; failed directories/probes retained; no access-control bypass.'},{'issue':'Initial generic source citation mistakenly named Garcia-Alonso','resolution':'Correct citation is Bashi AC,Coker EA,Bulusu KC etal2024, Large-scale Pan-cancer Cell Line Screening Identifies Actionable and Effective Drug Combinations, DOI10.1158/2159-8290.CD-23-0388. Original immutable intake manifests retained; this explicit correction supersedes author label only, not file identity/hashes.'},{'issue':'First computational replay path replacement nested artifactprefix in newrecordsroot and failed before reading plan','resolution':'Placeholder substitution; failedcase retained; v2 completed fullscientificworkflow.'},{'issue':'Strict byte-identity assertion on v2 predictionCSV failed','resolution':'All reported scientific metric fields reproduced exactly; only two parallel ExtraTrees prediction columns differ by<=1.04e-16. Original predictions retained. Numerical replay passes tolerance1e-12; do not claim byteidentity.'},{'issue':'Publisher rawCSV22cell names differs initial25/quality23 inarticle and23inAUCsupplement','resolution':'Analyze exactly frozen rawCSV rows, source metadata and hashes; no imputed missing cells, no assertion of exact original authorcohort replication.'},{'issue':'Nativepilot validator expects confirmatory_holdout string, original freeze used structuredobject','resolution':'Separate serialization-only native-pilot-plan adapter; originalplan immutable. Sourceextension project-local, not globalregistry.'}]})
papers=[('10.1038/nmeth.3853','Hafner etal2016','Growth-rate confounding and GR corrections already established; do not claim first recognition.'),('10.1038/s42003-023-04783-5','Harmonizing across datasets2023','Dose-response harmonization for crossstudy combination prediction already exists; C2is a narrow independent conditional-measurement test, not first harmonizer.'),('10.1016/j.isci.2025.112622','Moving beyond synergy scores2025','Dose-specific inhibition and unseen-cell prediction already studied; large synergybenchmark isnot novelty by itself.'),('10.1093/bib/bbae717','DD-PRiSM2025','Decomposes monotherapy and interaction and predicts dose-specific response; our simple conditional baselines do not establish superiority to this fullmethod.'),('10.1093/bib/bbaf676','SynVerse2025','One-hot/feature-shuffling/cold-start shortcomings and network confounding already covered; ordinary cold-split audit isnotnewcontribution.'),('10.1093/bib/bbab251','bayesynergy2021','Monotherapy-null uncertainty, replicates, missingdosegrids and posterior interaction estimates established.'),('10.64898/2026.02.05.704019','SIR2026 preprint','Shape constrained interaction testing and unstable scoring/noise addressed. Treat aspreprint, not peerreviewedacceptance.'),('10.1158/2159-8290.CD-23-0388','Bashi,Coker,Bulusu etal2024','Original109combination/755cell resource includes biomarker analyses and validations. Reusing it doesnot create newdataor prove mechanism.'),('10.1038/s43856-026-01583-w','Ayuda-Duran etal2026','Original melanoma screen already validates CHK1+nucleoside and schedule-dependent CDK4/6 antagonism. We do not present those published mechanisms as discoveries.')]
lines=['# 文献与旧题去重审计','',f'核查日期：{now}。使用PubMed esearch/efetch、EuropePMC原文与原始出版资料；原始响应保留在artifact目录。搜索不到不作为首创证据。','', '| 原始来源 | 与本题的边界 |','|---|---|']+[f'| [{label}](https://doi.org/{doi}) | {note} |' for doi,label,note in papers]
lines+=['','旧工作已核查：20261021 drug-support是单药测量支持/跨屏重复可靠性，perturbation-context是靶RNA效力校准。另drug_response_day1曾做通用组合/剂量迁移的文献与访问审计（零模型、未取得payload），该通用方向不重新计为新题。本次新题为未执行过的增长状态×通路迁移；C2是其失败后的测量状态解释测试，非另计一个新课题。','','当前没有建立足够区别于上述文献的二区论文贡献。阴性结果保留，但不把常识性“泛化困难”、一个失败的KNN或技术代数恒等式包装为新机制。','', '原始数据库响应：pubmed-search-0..5.json、pubmed-records-1/3/4/5.xml、pubmed-nearest-search.json、pubmed-nearest-records.xml；空结果与API失败均保留。SIR身份：sir2026-europepmc.json明确pubType=preprint。原始研究XML：original-paper.xml、melanoma2026.xml。']
(P/'LITERATURE_AUDIT.md').write_text('\n'.join(lines)+'\n')
report=f'''# 药物组合状态迁移：两次冻结机制检验与外部原始数据复核

更新时间：{now}。**本路线降优先级；未达到二区论文贡献目标，paper_candidate=false。** 这是已执行的探索研究，不是待投稿论文。独立科学审查尚未开展；下述“核验通过”仅指算术、来源哈希和复现检查。

## 新问题与执行边界

问题是：基线增殖状态或单药活性坐标，能否为药物组合的超Bliss作用提供可跨新药物对、细胞系、实验室迁移的信息？单药IC50剂量支持、靶RNA效力校准及一般冷启动问题均不是本题声称的新发现。先冻结方案、样本和基线，再各执行一次确认；没有在曝光确认集上调参或挑选成功子群。

## C1：增长状态×通路

5个Sanger官方Figshare矩阵文件共84,055行、755细胞系、109药物对、37化合物；技术重复合并，细胞系和药物对跨三划分均零重叠。训练23,200单位/457细胞/57对；验证2,804/131/25；GDSC010新屏确认1,643/63/27。原始预选确认为1,904/71/27，质量排除全记账，没有填充缺失结果。7个固定配置含均值、单药/组织/药物身份岭回归、全局增长、通路增长、药物增长及配对有/无增长ExtraTrees。跨屏对照增长来自同细胞其他屏的未处理对照，非目标组合反应。

M3通路增长模型相对无增长M1的MSE改善**−0.592%**，两向药物对/细胞bootstrap95% **[−5.116,3.632]%**；相对全局增长M2 **−1.024%**。树模型加入增长仅 **+0.154% [−1.848,1.750]%**。预设5%材料改善未获支持。组织内细胞增长置换是特征依赖诊断，不是因果随机实验。

## C2：单药活性坐标，真正独立实验室

取得Oslo2026出版社原始data.csv：1,299,594个长格式行，22个实际细胞名；同一组合孔每给药物重复一行，已核对CPS/viability一致后去重，未当作独立重复。原论文25初始/23质控及另一个AUC表23的数量不相同，明确按本次原始文件分析；不补造缺失样本。

源原始每孔档案流式读入3,915,245行，冻结选中31个黑色素瘤细胞、11组合家族、13,769技术平均剂量点。原生Bliss公式最大误差4.16e−16。5个共享活性母体结构经PubChem/源名称与目标SMILES核对，MK2206盐形式明确；只有3个完全相同药物对。其余为意向靶家族替代，不能当成完整靶谱等价。

目标3,801剂量点全部保留；234个合格矩阵，223个肿瘤矩阵；合并明确同来源个体后18供体组、11家族、190供体×家族单位。7个固定配置比较零交互、全局/家族均值、家族+通用活性回归、活性KNN、拟合null KNN、浓度KNN。87.48%点有至少3源细胞的邻域支持；7,586次单药浓度精确匹配、16次范围内内插，无外推。

活性KNN比家族均值MSE改善**−19.645% [−44.705,−0.504]%**；比强简单活性回归**−3.203% [−19.663,13.336]%**；比零交互**−36.746%**。不能宣称活性坐标完成机制迁移。原生拟合null与实测单药null的每孔差异RMS约0.097；该量描述参考构造差别，不证明哪一个是真实生物学。

## 分离单药技术孔的交叉null诊断

在主外部流程执行后、查看最终指标前记录补充诊断；明确是同一曝光目标的机制诊断，**不是新独立确认**。882个单药剂量组有3孔，31组2孔，9组仅1孔；仅后者不能拆分，诊断排除16组合剂量点。固定源模型、零新拟合，预测输入和Bliss参考使用不相交单药孔，两向交换后评分。

相对家族均值的改善：共用单药孔参考 **−17.379%**；分离参考 **−19.763% [−38.616,−4.661]%**。仍无改进。两次配对误差差值恒等式数值误差1.17e−17；这只是已知代数关系的核验，不是新理论或因果证明。培养及部分控制仍共享，技术孔不等于独立培养/患者。

## 实际验证与局限

17个payload逐一SHA复核，6个Sanger文件另与Figshare官方MD5一致。C1 21个指标用独立stdlib CSV算术重算；完整计算重放所有报告指标精确一致，只有两个并行树预测列有1.04e−16舍入差，**不是字节完全一致**。C2 7个主MSE由点表重新聚合；3,801个条件预测由保存系数与独立NumPy邻域程序重构，最大差1.33e−15。技术/下载/初始引用纠错均保留。

以上不取代独立科学审查。11家族共享7药物节点，bootstrap不能制造独立机制；细胞部分跨研究重叠，同供体衍生系已保守合并但别名审计不保证完全独立。多数靶家族只有一种源化学组合；不能分离靶作用与化合物特异效应。三种共享化合物对中，目标点落在源两药名义浓度范围内仅约36.9%、12.2%、18.5%；活性相同不保证暴露或靶占据相同，也不能据此证明off-target。仅一株永生化“正常”黑素细胞不能证明安全或治疗窗。

公开数据的实际条款已保存：Sanger Figshare为CC BY4.0；Oslo出版社材料为CC BY-NC-ND4.0，Zenodo记录未标独立license。仅本地非商业分析，不再分发原始/改编补充表；不从公开访问推定伦理豁免。没有新增真实作者核验声明，没有使用默认数值代替研究数据。

## 决策与交付

两个直观校准机制均未跨留出边界得到支持，现阶段**停止在已曝光数据上优化**。近期文献已覆盖GR、剂量协调、单药/交互分解、标签噪声和冷启动基准；本次没有证明新的生物机制，也没有完整SOTA胜出或充分独立培养证据。建议降优先级，让空白独立reviewer核查冻结材料；若未来继续，先寻找具有同一化合物、重叠物理浓度与独立单药/组合培养重复的新公开屏，并提出区别于已测两假设的机制，再冻结新确认。

数据状态：`{P}`；代码：`{C}`；大文件：`{A}`。协议：PLAN_FROZEN.json、EXTERNAL_PLAN_FROZEN.json；结果：RESULTS.json、EXTERNAL_RESULTS.json；诊断：CROSSNULL_DIAGNOSTIC_RESULTS.json；复核：DETERMINISTIC_DELIVERY_VERIFICATION.json；完整机器状态：research_state.json；查新：LITERATURE_AUDIT.md；审查输入：REVIEW_INPUT_INDEX.json（所有代码、manifest、协议、结果和精确原始路径均有SHA）。现有5篇可投稿论文未修改，未选刊、投稿、发布或付费。
'''
(P/'REPORT_zh.md').write_text(report)
print(P/'REPORT_zh.md')
