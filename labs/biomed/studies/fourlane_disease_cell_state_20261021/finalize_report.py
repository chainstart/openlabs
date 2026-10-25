"""Summarize preserved results without reopening or changing the confirmation set."""
from intake import *
import platform,subprocess
import pandas as pd,numpy as np

CODE=ROOT/'openlabs/labs/biomed/studies/fourlane_disease_cell_state_20261021'
def read(root,name):return json.loads((root/name).read_text())
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(1024**2):h.update(b)
    return h.hexdigest()
def ci(v):return f"{v[0]:.3f}～{v[1]:.3f}"

def main():
    assert not (DATA/'confirmation_open_authorization.json').exists()
    assert not (ART/'confirmation_predictions.csv').exists()
    plan=read(DATA,'plan_frozen_v1.json');metrics=read(ART,'development_metrics.json')
    bulk=read(ART,'bulk_secondary_results_zero_column_repair.json')
    refs={k:read(ART,f'redeconv/{k}/reference_record.json') for k in ['healthy','IPF','pooled']}
    gate=read(DATA,'source_gate_stop_decision.json')
    truth=pd.read_csv(ART/'development_donor_truth.csv')
    excluded=truth[~truth.primary_ECM_eligible][['donor_id','disease','primary_ECM_observed_counts']].to_dict('records')
    pred=pd.read_csv(ART/'development_predictions.csv')
    invariance=max(pred[c].abs().max() for c in pred if c.endswith('_raw_CPM_difference'))
    trial=[]
    for i,n in enumerate(plan['model_configurations'],1):
        trial.append(dict(slot=i,configuration=n,status='development_LOODO_scored' if i<=4 else 'development_reference_built_confirmation_not_opened',confirmation_scored=False))
    trial.append(dict(slot=8,configuration='bulk_explanatory_OLS',status='rank_deficient_first_run; algebraically_equivalent_zero_column_repair_scored',new_configuration_for_repair=False,confirmatory=False))
    ledger=dict(at=now(),candidates_used=2,candidate_limit=3,unused_candidate_slots=1,configurations_attempted=8,original_plan_limit=8,user_absolute_limit=12,seed=plan['seed'],trials=trial,failed_attempts=['Power-loss range cache corruption, quarantined','Slow per-chunk HDF metadata reader interrupted before expression output','MuSiC2 fulltext retrieval blocked/unavailable; metadata and author repository only','GEO web alternative HEAD and Range GET TLS failures','Bulk all-zero batch2 column caused rank deficiency; original failure preserved, same column-space repair'],unexecuted=['sealed confirmation predictions','confirmation reference bootstrap','spatial expression analysis'],paper_candidate=False)
    atomic(DATA/'final_trial_ledger.json',ledger);atomic(ART/'final_trial_ledger.json',ledger)
    candidate=read(DATA,'candidate_ledger.json')
    candidate['candidates'][1]['disposition']='needs_replan: frozen count reconciliation stop condition triggered'
    candidate.update(at=now(),remaining_unused_candidates=1,note='No claim that all three candidate slots were exhausted; source-validity stop applies to current frozen experiment.')
    atomic(DATA/'candidate_ledger_final.json',candidate)
    atomic(DATA/'exposure_final.json',dict(at=now(),development='Expression, LOODO results and original first10 MTX columns inspected',bulk='Registered exploratory analysis opened and scored; source-dependent values provisional',confirmation='Analytically sealed; no expression rows selected or scored; neighboring bytes may exist in raw HDF caches',spatial='Published summary exposure only; corrected compressed download incomplete and stopped; no expression object loaded',confirmation_open_marker_present=False))
    scratch=sum(p.stat().st_size for p in ART.rglob('*') if p.is_file() and not p.is_symlink())
    records={}
    for root in [CODE,DATA]:
        for p in sorted(root.iterdir()):
            if p.is_file() and p.suffix in ['.py','.json','.csv'] and p.name not in ['research_status.json','evidence_hashes.json']:records[str(p)]=dict(bytes=p.stat().st_size,sha256=sha(p))
    for name in ['development_raw_cells.npz','development_raw_cells.csv','atlas_genes.csv','development_predictions.csv','development_metrics.json','development_donor_truth.csv','development_expression_intake.json','original_prefix_gene_differences.json','bulk_secondary_results.json','bulk_secondary_results_zero_column_repair.json','bulk_secondary_donor_values_zero_column_repair.csv','manifest.jsonl','h5_ranges.jsonl','environment.json','development_primary_provisional.png','development_primary_provisional.svg']:
        p=ART/name;records[str(p)]=dict(bytes=p.stat().st_size,sha256=sha(p))
    for k in refs:
        for n in ['reference.npz','signature.tsv','reference_record.json']:
            p=ART/'redeconv'/k/n;records[str(p)]=dict(bytes=p.stat().st_size,sha256=sha(p))
    atomic(ART/'evidence_hashes.json',dict(at=now(),hash_algorithm='SHA256',files=records,raw_range_payload_hashes='h5_ranges.jsonl; recovery quarantines separate',upstream_payload_hashes='manifest.jsonl',scratch_regular_file_bytes=scratch))
    result=dict(schema_version='openlabs.biomed.research_result.v1',updated_at_utc=now(),lane='disease_cell_state',status='needs_replan',scientific_disposition='来源核验失败，确认集保持封存；开发结果不支持预设改善，未形成二区论文级证据',paper_candidate=False,scientific_goal_completed=False,confirmation_opened=False,question=plan['research_question'],plan_sha256=sha(DATA/'plan_frozen_v1.json'),primary_minimum_relevant_effect=.05,development=dict(donors=19,ipf=12,control=7,sampled_cells=3458,available_population_cells=80395,common_genes=19423,metrics=metrics,low_count_exclusions=excluded,source_status='provisional_original_counts_not_reconciled'),raw_CPM_max_absolute_prediction_difference=float(invariance),confirmation=dict(planned_donors=60,ipf=32,control=28,sampled_cells_planned=8708,expression_evaluated=False,reason='Frozen source-count reconciliation gate failed'),published_method_references=refs,bulk=bulk,source_gate=gate,trial_ledger=ledger,resource=dict(transfer_accounted_bytes=read(ART,'transfer_bytes.json')['bytes'],scratch_regular_file_bytes=scratch,cgroup=Path('/proc/self/cgroup').read_text(),gpu_used=False,threads_max=2),uncertainty_limitations=['Development donor bootstrap conditional on fixed fitting procedure; overlapping LOODO training sets and reference uncertainty not fully propagated','Planned100 reference bootstraps not executed because confirmation remains sealed','No equivalence or causal inference from intervals','ReDeconv reference feasibility only, no fair heldout performance comparison completed'],evidence_hashes='evidence_hashes.json',original_results_preserved=True)
    atomic(ART/'RESULTS.json',result)
    tables=[]
    for key,group in metrics.items():
        for model,v in group['models'].items():
            tables.append(f"| {key} | {model} | {v['n']} | {v['mae']*100:.2f} | {ci(np.array(v['ci95'])*100)} | {v['failed_or_nonfinite']} |")
    refrows=[]
    for k,v in refs.items():refrows.append(f"| {k} | {len(v['offered_donors'])} | {len(v['normalization_retained_donors'])} | {v['retained_cells']} | {v['signature_genes']} | {', '.join(v['compartments'])} |")
    bulkrows=[]
    for key,v in bulk['metrics'].items():
        for model,q in v.items():
            effect=q.get('mean_difference',q.get('disease_coefficient'))
            bulkrows.append(f"| {key} | {model} | {effect:.3f} | {ci(q['ci95'])} |")
    report=f'''# 成人肺纤维化细胞组成／状态归因路线：阶段裁定报告

生成时间：{now()}。原截止时间 2026-10-22 11:46:31 UTC 未延长。状态 **needs_replan**；**paper_candidate=false**；未达到本轮2025中科院升级版大类二区及以上证据目标，未进行选刊、投稿、公开发布或付费。本报告是研究审计，不是论文稿件。

当前冻结实验触发“不能核对原始计数”的停止条件，确认集保持封存。开发实验已经实际执行，但不能将其数值解释为已验证的原始 UMI 归因结果。没有把进程完成写成科学目标完成，也没有声称三个候选均已穷尽。

## 科学问题与冻结边界

候选1是一般性的 bulk 组成／状态分解。它与既有方法和原始肺研究重合，未作为创新项目推进。候选2问：健康参考是否会把成人 IPF 上皮来源的 ECM 转录本误归给间质来源，加入疾病供体参考能否改善误差，并优于开发 IPF 中位数常数预测？冻结时间为2026-10-21 12:11:05 UTC；原计划 SHA256：`{result['plan_sha256']}`，内容未改写。

主终点是每名 IPF 供体中 COL1A1、COL1A2、COL3A1 合计转录本的上皮来源份额预测绝对误差，比较健康 NNLS 减混合 NNLS 的平均误差。最小实际相关改善预设为 **0.05，即5个百分点**。次要程序为 AGER、SFTPA1、SFTPA2、SFTPB、SFTPC、ABCA3、NAPSA，不用它替换主终点。目标是捕获细胞的 RNA 来源份额，不是组织真实细胞比例，更不是因果分解。

所有 GSE135893 合格成人供体用于开发，按供体留一评估。GSE136831 全研究预留一次确认；本轮未打开。每供体、原始注释粗类群最多32细胞，SHA256固定抽样，以 N/n 权重构造 pseudobulk；原始采样程序计数少于20者不进入相应指标。共同基因在模型运行前固定为19,423个；训练标记排除两个终点程序及线粒体／核糖体基因，固定每类最多50个，不按确认结果选择。

确认集32名 IPF 的先验精度测算：若配对误差差值 SD=0.10，95%区间半宽约0.036，80%功效对应效应约0.051；SD=0.20时半宽约0.072。此为假设情景，不是观测功效，原文件 `primary_precision_clarification.json` 保留了对早期非匹配精度估计的澄清。

## 与最近工作的关系

检索保存了 Crossref、Europe PMC/PMC 原始响应与官方仓库快照。下列均为正式期刊论文，未把预印本当成已发表证据。

- [MuSiC2](https://doi.org/10.1093/bib/bbac430)已处理多条件参考与疾病可变基因；全文接口失败，核实范围是书目信息、摘要和作者仓库，不能声称已逐段核完全文。
- [ReDeconv 2025](https://doi.org/10.1038/s41467-025-56623-1)已处理转录组大小／基因长度问题，本轮使用固定上游组件作最近方法参照。
- [Unico 2025](https://doi.org/10.1186/s13059-025-03776-3)已有肺 HLCA pseudobulk 的细胞类型分辨分析；“使用肺 pseudobulk”不是创新。
- [DECODE 2026](https://doi.org/10.1038/s41592-026-03007-y)已有细胞类型／状态反卷积和目标域适应，未在本轮 CPU 预算内训练，不能宣称优于它。其肺基准使用了与 Adams 部分对照有上游重用的既有肺资料；这不证明本次开发与确认供体重叠，但排除“从未被方法使用过的数据”说法。
- [跨研究单细胞 DE meta-analysis 2025](https://doi.org/10.1038/s41467-025-62579-z)主要提供跨研究再现性的背景，不能冒充本 IPF 问题已有独立验证。
- [Habermann 2020](https://doi.org/10.1126/sciadv.aba1972)已报道 ECM 相关病理上皮群；[Adams 2020](https://doi.org/10.1126/sciadv.aba1983)已用 MuSiC 分析本轮 GSE134692 bulk。
- [Vannan 2025](https://doi.org/10.1038/s41588-025-02080-x)已有空间病理与组成关联。旧 preprint codeword 错配必须排除；仅 corrected2025 可用。既有表格部分暴露，空间路线只能作补充，不能包装成盲确认。

没有建立“首次”的证据。本轮窄问题只可能贡献特定程序的参考迁移误差或失败边界；目前证据不足。

## 实际数据与独立单位

| 来源 | 本轮实际范围 | 独立性与排除 |
|---|---|---|
| GSE135893 开发 | 19供体：12 IPF、7对照；80,395合格映射细胞中固定抽样3,458；raw矩阵55,329列，共同分析19,423基因 | 原成人合格20供体中THD0002未映射；年龄17的VUHD65与年龄未知THD0005预先排除；细胞不是独立样本 |
| GSE136831 确认 | 元数据60成人：32 IPF、28对照；239,651合格映射细胞，固定抽样计划8,708 | 表达未选取、未评分；同一Subject的library合并；不能按细胞计算n |
| GSE134692 bulk | 35 IPF、11 Normal成人；46个去重Sample.property | 原始80行仅61个Sample.property；先batch1后sample_id选重复；排除儿童、ALI与3个性别冲突对象；主体身份仍有不确定性 |
| GSE250346 空间 | 元数据拟留11 IPF、8对照，排除4个与scRNA来源重叠对象 | corrected RDS只完成部分下载，未加载表达；343基因面板，不是全转录组，也不是新实验室验证 |

主 ECM 低计数排除记录：`{json.dumps(excluded,ensure_ascii=False)}`。其他排除及条款见数据目录内 eligibility、barcode reconciliation 与 source registry 文件。官方 CELLxGENE 是原研究的传输副本，不增加独立队列数。

## 来源核验失败：本轮决定性限制

开发矩阵来自 [HLCA 官方分发](https://cellxgene.cziscience.com/collections/6f6d381a-7701-4781-935c-db10d30de293) 的 `raw/X`，固定dataset version `5f863718-02a6-46cb-83e7-52be988b915b`；未使用整合嵌入或转移标签。通过合法HTTP206范围读取取得选定行，没有下载21.86GB完整对象。

3,458细胞的图谱总计数与原 nCount_RNA **无一完全相等**；比值中位数0.977084，范围0.838388～0.995161。随后检查已经取得的原始MTX前64KiB，排除最后不完整列，前10完整细胞列中6个能与图谱精确匹配。六个细胞有1～54个同名基因计数不一致。例如同一细胞 SFTPA1 从314变309、SFTPC从1624变1618。故不能仅用“基因被过滤”解释，也不能声称已经重验原始矩阵。

已检查固定提交 `318d17d4277baddb202f903cf7b6680caf0230d8` 的作者预处理、基因转换、合并与完整对象代码；其中存在基因映射／合并步骤，但没有建立上述每基因计数变化的完整解释。六细胞审计只证明对应记录不相等，不能估计全队列误差率，也不能据此指控某个上游软件错误。

官方原始开发MTX为1,076,137,992字节，确认MTX约2GiB。FTP HEAD可访问；另一官方GEO网页入口的HEAD与Range GET均TLS失败，未关闭TLS验证或绕过访问控制。按本轮约6～16KB/s/连接的实测范围，即使两连接均持续达到上端，两文件合计传输仍约28小时，超过剩余约22小时；这只是当前实测条件下的估计，不声称数据永远不可获取。检索还发现新的合并图谱和细胞子集，但没有核实可保持本冻结样本和原始计数的等价镜像，未用另一份派生图谱掩盖差异。

因此触发原计划的来源停止条件，未创建确认集打开标记。原有阴性开发结果完整保留；空间下载停止并保留已验证块与中断片段，其补充性质不能修复主实验来源失败。状态为需要重规划，不是候选全部穷尽。

## 开发实验数值：全部为来源未通过的暂定结果

下表为供体留一预测，MAE及区间单位均为百分点；区间来自2,000次供体重采样。区间条件于当前流程，未完整传播重叠训练折和参考选择的不确定性。

| 分组与程序 | 模型 | 供体n | MAE | 95%区间 | 失败／非有限值 |
|---|---|---:|---:|---|---:|
{chr(10).join(tables)}

主比较“健康误差减混合误差”为 **−2.716个百分点，95%区间−9.265～2.359**；预设改善方向未获支持。常数减混合为7.249个百分点，区间−0.351～17.469；不能据此宣称稳定优于强简单对照。次要肺泡程序的改善不挽救主假说，区间跨零也不等于等效。raw与CPM列缩放的最大份额差为 `{invariance:.3g}`，这是无正则NNLS列缩放性质的软件检查，不是独立生物验证。

图见 `development_primary_provisional.png` / `.svg`，所有预测见 `development_predictions.csv`。没有确认集成绩。

## 最近已发表方法的实际接入

固定上游 ReDeconv 代码、默认相关性0.95的供体归一化、fold-change2／P<0.05／类群至少30细胞、每类最多50标记、MLMD预设6轮。终点程序不参与标记。共同基因与预算约束是显式适配，不能当作原论文全部设置的完全复现。

| 参考 | 提供供体 | 归一化保留供体 | 保留细胞 | 标记数 | 最终类群 |
|---|---:|---:|---:|---:|---|
{chr(10).join(refrows)}

IPF参考未保留 fibroblast／other_mesenchymal 输出类群，是实质可比性限制。以上仅是开发参考构建，不是留一验证性能。没有运行确认集MLMD，不能说 NNLS 优于ReDeconv。原reference record中“raw counts”指该分发层，不代表与GEO原始UMI的等价性已经成立。

## 真实 bulk 补充分析

按原始注释 ExonLength 做共同基因长度校正后归一化，比较 log2(程序总量+1)。原始RSEM估计计数允许小数，不是UMI；ExonLength也不是逐样本RSEM有效长度。IPF平均年龄62.71岁，对照46.36岁，残余临床混杂不能消除。

| 程序 | 分析 | IPF−对照效应／疾病系数 | 95%区间 |
|---|---|---:|---|
{chr(10).join(bulkrows)}

未调整差异是描述性结果。健康参考混合预测与组成协变量回归均依赖未通过来源核验的参考，标为暂定，不能相减后声称“多少百分比由组成解释”。OLS固定疾病、年龄、性别、batch和7个RNA混合系数；46行均batch1，首次因全零batch2列rank=11/12失败。仅删除这个全零干扰列，不改变设计列空间，保留原失败产物及修复前代码，未增加模型配置。修复后残余df35，HC3区间条件于单个参考；这不是因果分解。

## 试验预算、失败与未完成部分

候选使用2/3，未使用的第3槽没有被伪造为已穷尽。配置累计8/原计划8（用户硬上限12）：常数、3种NNLS、3种ReDeconv参考、bulk解释性OLS。LOODO、固定bootstrap和零列技术修复不是额外调参配置。完整账本为 `final_trial_ledger.json`。

断电恢复隔离了4个哈希不符及5个空缓存块，原证据未覆盖。慢HDF元数据遍历在产物前中止，改为一次索引遍历；元数据预算重分配有单独记录，总6GiB不变。MuSiC2全文接入失败、网页TLS失败、bulk秩亏和来源计数差异均保留。没有因坏结果修改确认集、终点、阈值或重新抽样。

未完成：独立确认、确认集100次参考供体重采样、空间表达与病理关联。因此没有完整公平外部方法比较，也没有独立外证支持二区论文级主张。模拟混合／软件检查只验证代码，不替代真实实验。本设计与通用train/validation/test门槛不完全一致，未伪造通用paper gate通过。

## 复现与资源

所有运行时均经 `bin/openlabs-resource-guard --task-type cpu --`，实际cgroup为本路线service且包含openlabs-workers.slice。每路CPU200%、软4GiB／硬5GiB、swap512MiB、tasks96未修改；线程最多2，HTTP最多2；未执行CUDA，未派生子代理或嵌套Codex，未写共享环境、全局注册表或旧报告。

当前传输账本 {result['resource']['transfer_accounted_bytes']:,} 字节；报告前常规文件scratch {scratch:,} 字节，分别低于6GiB／12GiB。私有R4.3.3核心仅解包约43.6MB，烟雾检查通过；未安装Seurat生态，未读取完整空间对象。

实际单细胞解释器：`{ROOT}/openlabs/labs/biomed/environments/singlecell/.venv/bin/python`。核心解释器：`{ROOT}/openlabs/labs/biomed/.venv/bin/python`。环境锁与实际恢复环境记录见 `environment.json`；全部代码、冻结计划、模型、预测及主要数据SHA256见 `evidence_hashes.json`，原始payload逐项来源／字节／SHA见 `manifest.jsonl`，范围块见 `h5_ranges.jsonl`。原始旧实验未同步，本轮没有声称重验旧实验。

主要实际执行命令（代码均位于 `{CODE}`；前缀guard不可省略）：

```bash
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/environments/singlecell/.venv/bin/python labs/biomed/studies/fourlane_disease_cell_state_20261021/extract_expression.py development
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/environments/singlecell/.venv/bin/python labs/biomed/studies/fourlane_disease_cell_state_20261021/attribution.py development
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/environments/singlecell/.venv/bin/python labs/biomed/studies/fourlane_disease_cell_state_20261021/audit_original_prefix.py
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/environments/singlecell/.venv/bin/python labs/biomed/studies/fourlane_disease_cell_state_20261021/redeconv_reference.py healthy
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/environments/singlecell/.venv/bin/python labs/biomed/studies/fourlane_disease_cell_state_20261021/redeconv_reference.py IPF
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/environments/singlecell/.venv/bin/python labs/biomed/studies/fourlane_disease_cell_state_20261021/redeconv_reference.py pooled
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/environments/singlecell/.venv/bin/python labs/biomed/studies/fourlane_disease_cell_state_20261021/bulk_analysis.py --drop-zero-nuisance
```

这些命令是历史执行记录；原产物存在时脚本拒绝覆盖。重新核验应写新审计产物，不删除保护文件或打开标记。报告生成脚本不会执行确认分析。

## 后续条件与停止判断

首先需要取得可校验的原始稀疏矩阵或可解释到基因级的官方转换依据，复核同一冻结细胞／共同基因；不能猜测整数修复，也不能仅因另一镜像数值更好就更换来源。随后应重新评估该窄问题是否有足够创新与参考可比性，在保留全部开发结果和预算账本的前提下记录数据技术修订；确认集当前尚未打开。需要新的监督窗口／可靠传输路径才能规划超出原deadline的工作，本轮未自动延长。

即使来源问题解决，现有开发结果、较少独立供体、临床混杂、未完成外部验证和有限方法比较也不支持二区论文候选。当前有价值的交付是可复核的阴性开发实验和来源失败定位，而非正结果或机制发现。
'''
    (ART/'FINAL_REPORT.md').write_text(report)
    atomic(ART/'report_hashes.json',{n:sha(ART/n) for n in ['FINAL_REPORT.md','RESULTS.json','evidence_hashes.json']})
    print(json.dumps(dict(report=str(ART/'FINAL_REPORT.md'),result=str(ART/'RESULTS.json'),scratch_bytes=scratch,transfer_bytes=result['resource']['transfer_accounted_bytes'],configurations=8),ensure_ascii=False))

if __name__=='__main__':main()
