from pathlib import Path
import json,hashlib,datetime,shutil
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024');C=Path(__file__).parent;V=A/'revision-v2';R=Path('/home/biostar/work/projects/openlabs/openlabs-data/maintenance/biomed-new-five-4h-20261024/reviews/drug');now=datetime.datetime.now(datetime.timezone.utc).isoformat()
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
r=json.loads((V/'RESULTS_V2.json').read_text());shutil.copy2(V/'RESULTS_V2.json',P/'RESULTS_V2.json');shutil.copy2(V/'VERIFICATION_V2.json',P/'VERIFICATION_V2.json')
report='''# 药物组合冻结预测试验：独立审查后修订版v2

本版替代旧报告、旧研究状态和结果摘要中受影响的解释，旧文件和全部预测不作改写。路线继续降优先级，未达到二区论文贡献要求；不晋升论文候选。独立审查已完成第一轮并要求五项修订；本版尚待新的空白复核。没有新拟合、调参、重置留出集或新独立确认。

## C1：组合标签留出、辅助控制可用的条件预测

5个同一上游研究的屏共84,055原始矩阵行。训练23,200单位/457细胞/57药物对，验证2,804/131/25，测试1,643/63/27；细胞及药物对的三划分两两交集为零。GDSC010组合标签未进入训练，但不是完全screen-naive：构建other-screen增长中位数时，221/457训练细胞、11,322/23,200训练行有GDSC010未处理辅助控制进入候选池。这里是控制可用性计数，不等于每一数值都改变中位数。不可再称“GDSC010整体未参与拟合”或“完全未见屏迁移”。它也不是独立实验室或新药物节点检验。

M3相对M1改善−0.592052%，交叉bootstrap95% [−5.115652,3.631576]%；树模型增增长变量改善0.154499% [−1.848463,1.750222]%。两个固定增长实现未达到5%改善门槛；这不否定增殖生物机制，也不证明所有增长表征都无用。

## C2：外部实验室及主终点的准确含义

Sanger源3,915,245孔行中选31细胞、11家族、13,769技术平均剂量点；Oslo原始文件1,299,594长格式行，经物理孔去重得到3,801组合剂量点、234合格矩阵、223肿瘤矩阵，保守合并同供体衍生系后18供体组、11家族和190供体×家族单位。22实际细胞名与原文25初始/23质控不同，未补造样本。6供体组跨研究重叠；12名称非重叠组也不保证完全生物独立。

主终点明确是：先在剂量矩阵内平均标签与预测，再平均同供体衍生细胞的矩阵均值，**随后平方**；每家族内等权供体、最后等权家族。它检验剂量面平均交互效应，不能代表局部剂量面准确度，正负局部误差可能抵消。主方案原本已指定平均，本版没有事后替换终点。

主结果保持不变：B4活性KNN对B2家族均值改善−19.644645% [−44.704778,−0.504222]%；对B3条件回归−3.203483% [−19.663317,13.336003]%；零交互B0 MSE为0.0054058026，七配置最低。B4未获得指定优势，不能据此证明活性坐标普遍无效或与B3等效。

审查后追加的逐剂量平方诊断仍是同曝光数据的描述性核算：先逐点平方，再矩阵/供体/家族分层平均，B0/B2/B3/B4 MSE依次为0.02272515、0.02349784、0.02635165、0.02811793。这不是新主终点、确认检验或新的模型选择依据。

## crossnull口径修正及遗漏配对差

原诊断错误地先在细胞上平方再合并供体；该估计对象包含供体内衍生细胞差异，与主分析不一致。v2按主分析修正：每fold先合并同供体的矩阵标签和预测，再平方，最后平均fold、供体及家族。3,785剂量点、444肿瘤矩阵fold、18供体和11家族保持不变；由于拆孔支持排除16点，本诊断剩189供体×家族单位，不是主分析190。

修正后coupled B2/B4 MSE为0.0064994972/0.0076448525，disjoint为0.0064994972/0.0077941969；B4对B2改善−17.622215%及−19.919998%。两者不是旧报告−17.378589%与−19.762691%的静默替换；旧结果保留为“细胞先平方”的历史估计对象。

使用同一组供体/家族交叉重采样1000次（seed20261024），配对计算disjoint-minus-coupled增益差：对B2为−2.297783个百分点，95% [−15.551004,8.323551]；对B3为−0.117669个百分点，95% [−9.748887,13.553034]。区间均含零，不能说分离单药孔显著改变预测优势，也不能声称噪声耦合解释已被验证或推翻。分孔仍共享培养及控制归一化；技术孔不是独立生物重复。代数损失恒等式是已知算术关系，不是新机制。

## 结论边界、来源及可复现性

准确结论是“两个冻结预测实现未达到指定改善阈值”。无法区分表征不足、固定KNN容量、化合物替换、浓度域、归一化及生物异质性等原因。仅3个相同活性母体化学对，其源浓度范围覆盖约36.9%、12.2%、18.5%；11家族在源中各只有一种化学组合，不能分离家族和化合物效应。共享7目标药物节点、同供体系和源模型不确定性未被当前bootstrap完全覆盖；区间只适用于当前有限库和固定流程。单一永生化正常黑素细胞不能支持安全性。

17原始payload哈希、6官方MD5、孔级重构与C1完整重放已由第一轮独立审查核对；v2另用不导入分析模块的stdlib CSV/显式循环核算修正MSE、gain及配对CI，误差小于1e−10。该验证不是科学批准。源Sanger为CC BY4.0，Oslo出版社材料CC BY-NC-ND4.0，仅本地非商业分析，不再分发原始或改编数据表，不推定伦理豁免。

没有证明新生物机制、方法优势或SOTA优越性；保留阴性pilot，停止已曝光数据上的救模型。未来重启须先有区别于既有文献的新命题及未曝光、同化合物、重叠浓度、独立培养重复的新数据。代码、精确路径、旧证据和修订证据统一由REVIEW_INPUT_INDEX_V2.json绑定；RESULTS_V2.json为新增数值，RESPONSE_TO_REVIEW_V2.md逐项回应。现有五篇稿件、数据库、投稿及Git均未修改。
'''
(P/'REPORT_zh_V2.md').write_text(report)
response='''# 独立审查逐项回应（v2）

接受五项问题。旧冻结168文件、旧索引、addendum和审查记录均原样保留；不训练、不调参、不重新开放留出。

| 编号 | 修正与证据 | 影响 |
|---|---|---|
| M1 | revision_v2.py按每fold先平均同供体预测/标签，再平方；RESULTS_V2.json和crossnull-aligned-units.csv给189单位；VERIFICATION_V2.json独立循环重算 | B4对B2 coupled/disjoint改为−17.622215%/−19.919998%；阴性方向保持。旧−17.378589%/−19.762691%仅为不同历史口径 |
| M2 | 同一bootstrap抽样逐次计算两个gain的配对差；保存全部1000次分布 | 对B2差−2.297783pp CI[−15.551004,8.323551]；对B3−0.117669pp CI[−9.748887,13.553034]。均含0，不能支持耦合影响的确证结论 |
| M3 | 新报告明确矩阵平均、供体平均后平方；另存dosewise-loss-units.csv和七模型逐点平方诊断 | 主终点及其原结果不变；逐点诊断是审查后描述性计算，不是新确认 |
| M4 | 新报告/状态/结果摘要均只称两个冻结预测实现未达门槛，列出未识别替代原因 | 不再用“机制被否定/失败”作科学结论；技术诊断不作因果归因 |
| M5 | 从原控制CSV独立重算GDSC010辅助控制候选池：221训练细胞/11,322训练行 | C1是组合标签留出、辅助控制可用的条件预测；保留细胞/药物对零重叠，不宣称screen-naive。不在已曝光集重拟合 |

## 全量受影响声明核对

旧REPORT_zh.md标题、“机制诊断”、末段“两机制未支持”由REPORT_zh_V2.md替代。旧research_state.json.scientific_disposition由research_state_V2.json替代。旧result_bundle.json.summary及C1“newscreen”宽泛文字由result_bundle_V2.json替代。旧REVIEW_INPUT_INDEX.json.scope、read_first与旧next_action仅作历史，新的索引scope、read_first及状态为本次复核入口。旧CROSSNULL_DIAGNOSTIC_RESULTS.json.stage及其全部metrics/CI保留历史口径，不作为当前供体平均后平方估计；由RESULTS_V2.json明确替代。旧PLAN_FROZEN/EXTERNAL_PLAN_FROZEN/CROSSNULL_PLAN是历史承诺，不重写；原始C1/C2确认数值仍有效，必须结合新增终点/辅助控制限定解释。环境、来源manifest、原始数据和预测均不变。

v2尚未获得独立科学通过；第一轮审查报告保留为修订依据，不修改其结论或记录。新的空白复核应核查对齐顺序、配对差与所有保留边界。
'''
(P/'RESPONSE_TO_REVIEW_V2.md').write_text(response)
state=json.loads((P/'research_state.json').read_text());state.update(revision=2,updated_at=now,scientific_disposition='deprioritize: two frozen predictive implementations did not meet specified improvement thresholds; no mechanism falsification',independent_scientific_review_completed=True,independent_review_revision_status='five requested corrections completed; fresh v2 review pending',current_report='REPORT_zh_V2.md',current_results='RESULTS_V2.json',supersedes_interpretation_only=['research_state.json','REPORT_zh.md','result_bundle.json']);state['next_action']['objective']='Fresh blank review of v2 corrections and frozen original evidence; no scientific approval inferred.';dump(P/'research_state_V2.json',state)
dump(P/'result_bundle_V2.json',{'revision':2,'status':'needs_replan','paper_candidate':False,'summary':'Two frozen predictive implementations missed specified improvement thresholds. Conditional C1 auxiliary controls disclosed; C2 mean-effect endpoint and crossnull aggregation corrected; paired gain differences uncertain. No mechanism falsification.','scientific_approval':False,'fresh_v2_review_pending':True,'results':'RESULTS_V2.json','response':'RESPONSE_TO_REVIEW_V2.md','report':'REPORT_zh_V2.md'})
old=json.loads((P/'REVIEW_INPUT_INDEX.json').read_text());files={x['path']:x for x in old['files']}
for x in files.values():
 p=Path(x['path']);assert sha(p)==x['sha256'],p
snapshot=V/'code';snapshot.mkdir(exist_ok=True)
for name in ['revision_v2.py','verify_revision_v2.py','seal_revision_v2.py','run-guarded']:shutil.copy2(C/name,snapshot/name)
extras=[P/'REVIEW_INPUT_INDEX.json',P/'REVIEW_INPUT_ADDENDUM.json']+[P/n for n in ['REPORT_zh_V2.md','RESPONSE_TO_REVIEW_V2.md','research_state_V2.json','result_bundle_V2.json','RESULTS_V2.json','VERIFICATION_V2.json']]+list(V.glob('*.json'))+list(V.glob('*.csv'))+list(snapshot.iterdir())+[R/n for n in ['REVIEW.md','COMMANDS.md','review_manifest.json']]
for p in extras:files[str(p)]={'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
idx={'schema_version':'openlabs.manual_research_review_input.v2','frozen_at':now,'project_id':'biomed-new5-drug-20261024','paper_candidate':False,'creator_scientific_approval':False,'scope':'Post-review correction of estimand, omitted paired contrast, endpoint definition, inference boundaries and auxiliary-control disclosure. No new model fits or confirmations. Old frozen evidence retained byte-identically.','read_first':[str(P/n) for n in ['REPORT_zh_V2.md','RESPONSE_TO_REVIEW_V2.md','RESULTS_V2.json','research_state_V2.json']],'prior_index_sha256':sha(P/'REVIEW_INPUT_INDEX.json'),'files':list(files.values()),'replay_commands':[[str(snapshot/'run-guarded'),'/home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python',str(snapshot/'revision_v2.py'),'--output-root','<NEW_EMPTY_PRIVATE_DIRECTORY>'],[str(snapshot/'run-guarded'),'/home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python',str(snapshot/'verify_revision_v2.py'),'--output','<NEW_PRIVATE_VERIFICATION_JSON>']],'prior_evidence_index':str(P/'REVIEW_INPUT_INDEX.json'),'prior_addendum':str(P/'REVIEW_INPUT_ADDENDUM.json')};dump(P/'REVIEW_INPUT_INDEX_V2.json',idx);print(json.dumps({'files':len(files),'index_sha256':sha(P/'REVIEW_INPUT_INDEX_V2.json'),'old_index_sha256':sha(P/'REVIEW_INPUT_INDEX.json')},indent=2))
