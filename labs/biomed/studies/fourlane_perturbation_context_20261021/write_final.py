"""Assemble the reviewed Chinese report and a hash-bound, non-paper result bundle."""
import hashlib
import json
from pathlib import Path
import shutil
import pandas as pd
from intake import ART, DATA, atomic, now

CODE=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while b:=f.read(1024**2):h.update(b)
    return h.hexdigest()
def interval_text(x,percent=False):
    k=100 if percent else 1
    lo,hi=x['donor_t95']
    return f"{k*x['estimate']:.4f}{'%' if percent else ''}，名义95%供体t区间 [{k*lo:.4f}, {k*hi:.4f}]{'%' if percent else ''}"

def main():
    review=read(DATA/'scientific_review.json')
    integrity=read(DATA/'artifact_integrity_review.json')
    assert integrity['valid']
    for layer in ['bulk','screen']:
        assert read(DATA/(layer+'_prediction_reconstruction.json'))['valid']
        assert read(DATA/(layer+'_confirmation_opened.json'))['status']=='evaluated once'
    screen=read(ART/'screen_confirmation_results.json');bulk=read(ART/'bulk_confirmation_results.json')
    validation=read(ART/'bulk_validation_results.json');selection=read(DATA/'screen_selection_frozen.json')
    plan=read(DATA/'frozen_plan_v1.json');environment=read(DATA/'recovery_environment.json')
    baseline_rows=[]
    for name in plan['models']:
        cells=[name]
        for prefix in ['screen_confirmation','bulk_confirmation']:
            frame=pd.read_csv(ART/(prefix+'_all_baseline_intervals.csv')).set_index('model')
            if name in frame.index:
                r=frame.loc[name];cells.append(f"{r.donor_mse_mean:.6f} [{r.donor_t95_lower:.6f}, {r.donor_t95_upper:.6f}]")
            else:cells.append('不适用：无多刺激条件')
        baseline_rows.append('| '+' | '.join(cells)+' |')
    artifacts=[ART/'screen_confirmation_results.json',ART/'bulk_confirmation_results.json',ART/'bulk_validation_results.json',ART/'evidence_hash_index.json',DATA/'frozen_plan_v1.json',DATA/'screen_selection_frozen.json',DATA/'screen_split_audit.json',DATA/'bulk_split_audit.json',DATA/'screen_freeze_manifest.json',DATA/'bulk_freeze_manifest.json',DATA/'screen_prediction_reconstruction.json',DATA/'bulk_prediction_reconstruction.json',DATA/'screen_confirmation_reconstruction.json',DATA/'bulk_confirmation_reconstruction.json',DATA/'screen_guide_sequence_audit.json',DATA/'bulk_guide_sequence_audit.json',DATA/'artifact_integrity_review.json',DATA/'LITERATURE_AUDIT.md',DATA/'screen_execution_ledger.jsonl',DATA/'trial_ledger.json']
    result={'schema_version':'openlabs.result_bundle.v1','lab_id':'biomed','domain':'biology','campaign_id':'biomed-four-lanes-20261021','lane':'perturbation_context','created_at_utc':now(),'stage':'exploratory_pilot','status':review['status'],'scientific_disposition':review['scientific_disposition'],'paper_candidate':False,'research_question':plan['question'],'independent_unit':'donor; guides and targets are repeated interventions, not additional independent donors','screen':screen,'bulk':bulk,'bulk_validation':validation,'scientific_review':review,'candidate_budget':{'considered':3,'maximum':3,'decisions':read(DATA/'trial_ledger.json')['candidate_decisions']},'model_configuration_budget':{'unique_definitions':12,'maximum':12,'definitions':plan['models'],'fits_not_configuration_search':'bulk training3 donors and fixed refit6 donors; screen fixed fit2 donors; no test-driven tuning'},'data_independence':{'study_count':1,'study_id':'GSE314342','cross_layer_donors':read(DATA/'cross_layer_independence_audit.json'),'cross_layer_target_scope':read(DATA/'cross_layer_target_scope.json'),'screen_split':read(DATA/'screen_split_audit.json'),'bulk_split':read(DATA/'bulk_split_audit.json')},'limitations':review['limitations'],'evidence_contract':{'protocol':'biomed-public-data-pilot','full_pass_claimed':False,'reason':'screen crossed donor/guide design has only2 development and2 held donors, no independent validation donor; applicable provenance/plan/hash/ledger checks recorded without fabricating a three-way pass'},'resource_use':integrity,'run':{'code_revision':'b3c8da60486857ff726938c144869f13a68a97b8','uncommitted_lane_code_bound_by_sha256':{str(p):sha(p) for p in sorted(CODE.glob('*.py'))},'seed':20261021,'environment':environment,'additional_core_environment':read(DATA/'environment.json'),'commands_ledger':str(DATA/'screen_execution_ledger.jsonl')},'evidence':[{'path':str(p),'sha256':sha(p)} for p in artifacts]}
    numeric_summary=f"单细胞主终点：{interval_text(screen['primary_M5_vs_M2']['relative_gain'],True)}。bulk主终点：{interval_text(bulk['primary_M5_vs_M2']['relative_gain'],True)}。"
    artifacts += [DATA/'screen_development_signal_support.json', DATA/'screen_descriptive_diagnostics.json']
    # Bind the additional descriptive evidence without changing frozen inference.
    result['evidence'] += [{'path':str(p),'sha256':sha(p)} for p in artifacts[-2:]]
    for root in [ART,DATA]:atomic(root/'RESULTS.json',result)
    text=f'''# perturbation_context 最终研究报告

更新：{now()}。本轮监督截止时间仍为2026-10-22T11:46:31.613021Z，未延长。状态：**{review['status']}**；**paper_candidate=false**。

{review['summary_zh']}

## 科学问题与可检验范围

用途是判断：测到靶RNA相对丰度下降后，是否值得用它校准同一靶点的trans响应迁移。预设候选M5为测量误差收缩后的效力比例；主要对照M2为开发集学到的线性幅度校准。评分向量去除全部所扰靶基因，主终点为供体等权的trans向量MSE，实际相关效应门槛为5%相对改善。

这检验的是带干预后靶RNA信息的条件预测，不能把MSE改善解读为因果中介比例、实际蛋白抑制程度或已证明的调控机制。Rest、8h、48h三种条件均出现在开发集；没有检验从未见过的刺激状态。

## 最近工作与三个候选裁定

Zhu et al. Cell 2026（[原论文](https://doi.org/10.1016/j.cell.2026.08.002)）已讨论guide效力、off-target、供体一致性和早晚刺激调控。2026年的[CGC预印本](https://doi.org/10.64898/2026.09.30.755756)已涉及独立guide、重复和情境响应；[Virtual Cells Need Context](https://doi.org/10.64898/2026.02.04.703804)及[可靠性预印本](https://doi.org/10.64898/2026.08.11.744177)覆盖了泛化和测量支持问题。三者按预印本对待。

[TFActProfiler](https://doi.org/10.1093/nar/gkag897)已用实际靶RNA下降作预测输入；[eLife剂量实验](https://doi.org/10.7554/eLife.100555.3)及[TRADE](https://doi.org/10.1038/s41588-025-02169-3)已有非线性剂量与响应变化先例。因此不宣称首次发现效力、情境或可靠性的重要性。此次窄问题是在不按确认DE/抑制效果筛样本的条件下，检验target-only校准是否超过固定强简单对照。搜索缺失不是首创证据，详见data目录的LITERATURE_AUDIT.md及原始Crossref响应。

1. 效力校准增量：实际执行单细胞和bulk实验，结果如下。
2. 8h瞬时/48h持续模式：原Cell论文及近期预印本已直接覆盖，独立创新门槛未通过，未增加模型搜索。
3. probe与bulk不一致的归因：平台、培养、guide、供体和批次同时改变，仅9个作者选定靶点且只有1个与随机面板重叠；不能识别探针覆盖的因果贡献，未制造归因结论。

## 实际数据与独立性

官方主来源为GSE314342及作者固定提交aa5c84a973c0e1a090b0072dc5b080bf7fbbed38。44,566,657,140字节的完整pseudobulk文件未整库下载；仅使用核验206、Content-Range、原始ETag/版本及SHA-256的片段。

单细胞：283个靶点满足冻结的完整24行、每行至少25细胞及开发对照全情境至少10CPM门槛；按预设哈希选择64个，不按DE显著性或模型效果替换。评分基因{screen['n_features']}个。开发384个guide1样本、2位供体；主确认{screen['n_rows']}个guide2样本、2位不同供体、64个靶点。另384个留出guide1样本仅作残余复现诊断。两条guide序列及末端19bp均核验不同。每位供体没有独立培养重复，供体与批次部分混杂。

细胞量仅描述测量支持：开发靶向样本44,434个细胞；两条guide合计的留出靶向样本99,967个细胞。它们不等于独立样本量。冻结表达和细胞数门槛限制了可推广靶点范围，并可能排除强生长效应或低表达、强情境特异靶点。

bulk：14个文件、13位供体、98个样本（69个靶向、29个对照），训练/验证/确认供体分别3/3/7。确认{bulk['n_rows']}个靶向样本、9个作者选定靶点、{bulk['n_features']}个评分基因。DonorC2并入DonorC。每位确认供体覆盖1至9个不同靶点，不能把面板组成差异称为纯供体生物学。确认guide与开发guide的20nt序列均不同。两层供体ID无交集，但同研究、同实验室且培养/批次改变；不合并效应或声称跨实验室复现。随机面板与bulk仅共享SGF29。

## 全部预登记基线与主终点

{numeric_summary}

单细胞绝对改善：{interval_text(screen['primary_M5_vs_M2']['absolute_gain'])}。bulk绝对改善：{interval_text(bulk['primary_M5_vs_M2']['absolute_gain'])}。正值有利于M5。下表为等权供体平均MSE及未截断的名义95%供体t区间；单细胞仅2供体、自由度1，总体推断能力有限，bootstrap也不创造新供体。

供体效应图：[单细胞确认]({ART}/screen_confirmation_donor_gain.png)、[bulk确认]({ART}/bulk_confirmation_donor_gain.png)；同名PDF一并保留。

| 固定配置 | 单细胞确认MSE [t95%] | bulk确认MSE [t95%] |
| --- | ---: | ---: |
'''+ '\n'.join(baseline_rows)+f'''

M0零响应；M1未校准同靶点/同刺激均值；M2全局线性幅度；M3分刺激线性幅度；M4原始效力比；M5收缩效力比；M6线性乘收缩比；M7深度/细胞数幅度对照（bulk仅深度）；M8共享刺激响应；M9共享响应乘效力比；M10平方根效力比；M11平方效力比。M7是协变量幅度校准，不是严格的细胞数/读深下采样匹配。M3在单刺激bulk中与M2相同。所有模型结果保留，不按确认结果更换主模型。

M1/M8覆盖最近评估论文中的简单同靶点均值思路，但未运行TFActProfiler、TRADE或最近预印本的完整方法，不能宣称优于这些方法或完成全部已发表方法的公平基准。它们的输入需求和任务差异已在文献审计中记录。

bulk的3供体验证主终点为{interval_text(validation['primary_M5_vs_M2']['relative_gain'],True)}，没有据此改模型。全部供体损失、条件分层、效力分布、上限触发和bootstrap敏感性区间保存在相应CSV/JSON。区间含零不等于等价，负点估计也不能证明任何效力模型都无用。

## 残余效应及必要复核

{review['secondary_findings_zh']}

开发集另作了不拟合新模型的描述性检查：两供体、同guide的响应向量余弦中位数在Rest/8h/48h分别约0.0219/-0.0101/0.0078。它说明此筛选面板中跨供体响应支持较弱，但无法分离真正供体差异、批次、对照和采样噪声；没有据此筛掉靶点或改动确认。详见screen_development_signal_support.json。

残余诊断同时保留原始时间响应、减去共享源响应后的残余，以及两条guide各减去不同开发供体参照的残余。共享参照有估计误差，可人为抬高残余一致性；不能只展示这一版本。独立参照缓解该问题，但共同批次、拟合先验、相对计数归一化及RNA干预后选择偏差仍在。作者off-target标记仅作描述性分层，未标记不等于已证明无off-target。

确认集各打开一次。误差从保存预测独立重算；另一个不导入calibration.py的程序从冻结参数重构全部预测。两项检查只复核已暴露结果，不增加独立确认次数。数据片段、选中稀疏行、样本身份及行和完成流式核验；哈希不是生物学有效性证明。

## 失败、修正与完整试验账本

原冻结计划未改写。断电损坏的6份清单及相关产物被隔离保留；损坏账本原件保留，并以保守上界补计不确定下载字节。bulk读取在任何拟合前发现Donor5/8注释溢出和两个破损ENSG计数行；一致排除ENSG00000145362、ENSG00000155657与非ENSG记录，保留独立技术修正文件。bulk为分数计数，Poisson型误差方差只是敏感性模型。

下载优化没有改变样本：16个既有对照的HDF直读与原完整块数组完全相同；3个同来源HTTPS分块的SHA完全相同。原始慢速缓存、被中断步骤、失败探针及全部下载事件保留。累计候选3个、固定模型配置12个；bulk适用10个，单细胞12个，未增加调参网格。种子20261021仅用于固定抽样/区间过程；所有命令、失败和阶段见trial_ledger.json与screen_execution_ledger.jsonl。

## 局限与裁定

'''+ '\n'.join('- '+s for s in review['limitations'])+f'''

{review['next_step_zh']}

目前未认定达到2025中科院升级版大类二区及以上的创新性与证据目标。不做期刊推荐、投稿、付费或公开发布，未修改全局选刊政策。

## 复现与证据定位

代码：{CODE}。数据状态：{DATA}。科学产物：{ART}。

复核命令（从代码仓库根运行；读取已有数据/预测，写出审计文件，不重新拟合或打开新确认。不要删除确认标记或重新调参；复算更新审计时间后，旧RESULTS.json中相应审计文件哈希将不再匹配，须另存新证据包）：

```bash
bin/openlabs-resource-guard --task-type cpu -- env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python labs/biomed/studies/fourlane_perturbation_context_20261021/reconstruct_predictions.py bulk screen
bin/openlabs-resource-guard --task-type cpu -- env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python labs/biomed/studies/fourlane_perturbation_context_20261021/review_results.py bulk_confirmation screen_confirmation
```

实际全流程命令与代码执行哈希见screen_execution_ledger.jsonl，初始bulk命令见research_status.json及README。模型在artifact/models，原小型冻结参数快照仍保留在data以保持原哈希。RESULTS.json绑定代码、环境、计划、预测复核和原始结果；evidence_hash_index.json列出实际payload/稀疏行哈希。未将multipart ETag当作完整文件SHA。

本轮计入下载预算约{integrity['charged_download_bytes_including_conservative_bounds']/1024**2:.2f}MiB（含保守补计），核验时scratch约{integrity['scratch_bytes']/1024**3:.3f}GiB。服务始终CPU-only、2核限额、4/5GiB内存软/硬限额、HTTP并发至多2。完整解释器与锁哈希在RESULTS.json；未修改共享环境或依赖锁。

本报告只核验当前机器取得和恢复的产物，没有重新执行旧报告中未同步的原始实验。S3外部文件未发现独立明示许可，记录作者公开研究数据来源并限于内部署名分析；不把文章许可自动扩展为外部bucket再分发授权。详见terms_resolution_audit.json。
'''
    (ART/'FINAL_REPORT.md').write_text(text)
    shutil.copy2(ART/'FINAL_REPORT.md',DATA/'FINAL_REPORT.md')
    state=read(DATA/'research_status.json')
    state.update(status=review['status'],updated_at_utc=now(),stage='scientific_review_complete',scientific_disposition=review['scientific_disposition'],paper_candidate=False,completed=['frozen screen and bulk experiments completed','all registered applicable baselines reported','deterministic prediction/loss reconstruction and payload integrity checked','Chinese final report and hash-bound results delivered'],remaining=review['remaining_for_research_target'],stop_reason=review['stop_reason'],final_artifacts=[{'path':str(p),'sha256':sha(p)} for p in [ART/'FINAL_REPORT.md',ART/'RESULTS.json']])
    for root in [ART,DATA]:atomic(root/'research_status.json',state)
    print(str(ART/'FINAL_REPORT.md'))

if __name__=='__main__':main()
