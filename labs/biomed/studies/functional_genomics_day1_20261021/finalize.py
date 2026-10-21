"""Hash-bound local result package; no submission, publishing or factory mutation."""
import json,shutil,sys,importlib.util
from common import *
sys.path.insert(0,str(CODE.parents[1]))
from tools.dataset_intake import validate_manifest
from protocols.public_data_pilot import validate

assert (PROJECT/'confirmation.completed.json').exists()
r=json.loads((PROJECT/'results.json').read_text())
v=json.loads((PROJECT/'frozen-selection.json').read_text())
assert r['confirmation_openings']==1 and r['paper_candidate'] is False
assert v['analysis_code_sha256']==sha(CODE/'run.py')
manifests=[];inputs=[];official={}
for accession in ['ENCSR022GQD','ENCSR382BVV','ENCSR244FWB','ENCSR405QCT','ENCSR203UFY','ENCSR336MKI']:
    meta=json.loads((ART/f'metadata/{accession}.json').read_text())
    for item in meta['files']:
        official[item['accession'].lower()]=dict(file_created_at=item.get('date_created'),
             experiment_released_at=meta.get('date_released'),file_status=item.get('status'),
             official_md5=item.get('md5sum'),experiment=accession)
for p in sorted((ART/'intakes').glob('*/manifest.json')):
    m=json.loads(p.read_text());errors=validate_manifest(m,verify_payload=True)
    assert not errors,(p,errors)
    dest=PROJECT/'intake-manifests'/f'{m["dataset_id"]}.json'
    dest.parent.mkdir(exist_ok=True);shutil.copyfile(p,dest)
    manifests.append(dict(path=str(dest.relative_to(PROJECT)),sha256=sha(dest)))
    inputs.append(dict(dataset=m['dataset_id'],release_or_accession=m['release_or_accession'],
        bytes=m['bytes'],sha256=m['sha256'],source_url=m['source_url'],terms_url=m['terms_url'],
        retrieved_at_utc=m['retrieved_at_utc'],official_metadata=official[m['dataset_id']],
        role='schema_only_excluded_from_analysis' if m['dataset_id']=='encff511xtz' else 'frozen_research_input'))
assert len(inputs)==13, 'All planned opaque inputs and excluded schema file must be inventoried'
atomic(PROJECT/'data-lock.json',dict(schema_version='openlabs.functional_genomics_data_lock.v1',
       upstream_study='DOI:10.1038/s41586-024-08430-9',files=inputs,
       payload_bytes=sum(x['bytes'] for x in inputs),independent_studies=1,
       distinct_cell_contexts=3,held_out_contexts=1,
       terms='Released ENCODE processed assays; exact official policy snapshot and per-file canonical intake manifests retained.',
       provenance_clarification='Early intake manifest release tags used released-<file date_created> to pin a released-status snapshot. That timestamp is the FILE CREATION date, not a claimed public release date. Original immutable manifests retained. Actual official experiment date_released and file date_created are separately recorded above.'))
codefiles={str(p.relative_to(CODE)):sha(p) for p in sorted(CODE.glob('*.py'))}
atomic(PROJECT/'code-lock.json',dict(files=codefiles,source_tree='labs/biomed/studies/functional_genomics_day1_20261021',
     note='Content hashes identify uncommitted campaign-local code; no shared tools were changed. Only a unique, locked source registry addition was authorized.'))
artifacts=[];total=0
for p in sorted(ART.rglob('*')):
    if not p.is_file() or '.download-' in p.name:continue
    total+=p.stat().st_size
    assert total<=3*1024**3
    artifacts.append(dict(path=str(p.relative_to(ART)),bytes=p.stat().st_size,sha256=sha(p)))
atomic(PROJECT/'artifact-index.json',dict(staging_root=str(ART),total_bytes=total,files=artifacts))

b=r['selected_baseline'];m=r['selected_orientation_policy'];metric=r['metrics'];ci=r['uncertainty']
ci1=ci['block_95ci'];ci2=ci['block_and_target_culture_95ci']
support=r['primary_pilot_support']
interpretation=('达到预登记的条件迁移试点阈值；这只支持所测报告系统中的条件预测增量。'
                if support else '未达到预登记的条件迁移试点阈值；不能解释为等价，也不能排除更小或其他条件下的增益。')
rows=[]
for item in json.loads((PROJECT/'complete-trial-ledger.json').read_text()):
    name=item['configuration']
    rows.append(f"| {name} | {item['validation']['mse']:.6f} | {item['confirmation_descriptive']['mse']:.6f} |")
report=f'''# 功能基因组学一天研究结果包

结论：当前论文推进 **no-go**，`paper_candidate=false`。{interpretation} 尚不足以支持2025中科院升级版大类二区论文的成果判断；没有选刊、投稿、付费或公开发布。

筛查3个实质不同方向，停止蛋白活性/丰度解耦（2026近邻直接覆盖、独立蛋白面板不足）与酵母表达—适合度环境迁移（原研究已直接回答核心问题、仅一个启动子）；完成最强可接入方向的小规模研究。审计见 `candidate-screen.json`、`literature-audit.json`、`SEARCH_LOG.md`，未改写旧CRISPR负结果，也未打开其剩余4个细胞。检索使用官方原文、Europe PMC和公开API；专业文献MCP不可用，不能声称穷尽。

问题：控制来源总体活性、测量精度和共同正义链偏好后，HepG2的启动子个体正义减反义方向差能否经K562训练，迁移至未用WTC11及未用位点？数据为Agarwal等2025原始双方向大库 ENCSR022GQD/ENCSR382BVV/ENCSR244FWB 的当前released处理文件；官方实验release日期前两者为2021-09-01，后者为2023-12-21，三次培养重复/细胞。单方向joint库只作格式核查，全部排除。精确accession、release、官方MD5、SHA-256、原研究与使用条款在 `data-lock.json` 和13份 intake manifest 中。下载链接没有被当作独立实验。

身份冻结：3,578个共同200nt常染色体启动子位点；chr1–16训练2454、chr17–18验证368、chr19–22确认756。固定每方向每重复至少10条码及有限数值后，实际训练 **{v['n_train']}**、验证 **{v['n_validation']}**、确认 **{int(metric['n_confirmation'])}**。没有跨集合染色体/1Mb区块/位点重叠。独立单位是基因组DNA位点，不能把这些数量当作独立细胞、供体或研究数。三细胞来自同一研究，WTC11仅一个新背景。

8个预登记策略，种子20261021；仅K562验证集选择，之后未重拟合。另有两个固定残差诊断回归，不参与选择，其中目标回归与activity_ridge相同；全部配置低于12上限。模型选择为无个体方向特征基线 **{b}**，方向策略 **{m}**。确认集仅评估一次，有开始/完成锁。

| 固定策略 | K562验证MSE | WTC11确认MSE（描述性） |
|---|---:|---:|
{chr(10).join(rows)}

唯一主比较：MSE由 **{metric['baseline_mse']:.6f}** 至 **{metric['orientation_mse']:.6f}**，改善 **{metric['primary_mse_improvement']:.6f} log2²**，相对下降 **{100*metric['primary_relative_mse_reduction']:.2f}%**。2000次1Mb配对区块bootstrap的95%区间 **[{ci1[0]:.6f}, {ci1[1]:.6f}]**；同时整体重采样三次目标培养的敏感性区间 **[{ci2[0]:.6f}, {ci2[1]:.6f}]**，{ci['n_blocks']}个确认区块。区间条件于固定来源测量、训练策略、四条染色体、单个WTC11背景和该研究；不是跨细胞/实验室总体区间。主阈值预定为相对下降≥10%且区块区间下限>0。

完整试验账本：`complete-trial-ledger.json`；逐位点预测、区块重采样、模型和来源特征在 artifact staging。培养重复相关性、各染色体误差、来源活性分层及预定来源可靠子集都在 `results.json`，仅作诊断，未据其挑选显著亚群。活动校正残差相关为 **{r['secondary']['train_fit_activity_residual_pearson']:.3f}**，不是机制证据。

最近工作差异与局限：Roberts2021（10.1101/gr.270751.120）已发现跨细胞链偏差，并明确指出启动子类报告中总体活性与不对称程度相关；Agarwal2025（10.1038/s41586-024-08430-9）已有方向和跨细胞启动子相关性。Bose2025预印本（10.1101/2025.10.13.659964）还直接考察了启动子、载体位置与链方向。本轮仅量化控制活动与平均偏好后的个体对比迁移，没有新算法或新机制结论；官方公开全文审计见 `nearest-fulltext-audit.json`。2026 QUASARR-seq（10.1038/s41467-026-68780-y）的内源/双功能结论不能由此推出。共同载体、片段选择和处理流程可共同保留测量偏差，精确序列身份来自坐标及原研究设计而非重新测序，固定QC也限制推广。不同位点仍可能同源；染色体隔离不保证序列同源家族隔离。位点区间不能替代独立实验室、载体和多个新细胞背景的验证。{('即使本试点达到数值阈值，也仅值得在更独立的数据中复核。' if support else '当前不建议以同一确认集继续调参；若继续，需要新的问题依据和独立数据。')}

数据锁 SHA-256：`{sha(PROJECT/'data-lock.json')}`  
代码锁 SHA-256：`{sha(PROJECT/'code-lock.json')}`  
依赖uv锁 SHA-256：`{sha(PROJECT/'environment.uv.lock')}`  
冻结方案 SHA-256：`{sha(PROJECT/'plan.json')}`。实际Python及全部已安装版本在 `environment.json`；数据和每个代码文件的完整哈希均在对应锁/索引中。

原始执行顺序（每条均在2线程CPU guard下；详见代码README）：`probe.py` → `audit_sources.py` → `intake.py` / `prepare_metadata.py` → `screening.py` → `freeze.py` → `download_replicates.py` 与不透明确认下载 → `software_check.py` → `run.py select` → `run.py confirm` → `finalize.py`。

可复现数值回放（原始确认目录拒绝再次打开；回放不构成新验证）：

```bash
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 FG_PROJECT_ROOT={PROJECT}/replay FG_ARTIFACT_ROOT={ART}/replay labs/biomed/.venv/bin/python labs/biomed/studies/functional_genomics_day1_20261021/reproduce.py
```

资源：2 CPU、MemoryHigh1536/Max2048MiB、TasksMax96，HTTP≤2，无GPU或新依赖；payload共 {sum(x['bytes'] for x in inputs)/1024**2:.2f} MiB（含排除的格式核查文件），staging共 {total/1024**2:.2f} MiB。运行未触碰其他研究、全局factory/timer或SQLite。计算完成不等于论文或投稿就绪；后续只能经独立科学审查决定是否值得继续。
'''
(WORKER/'FINAL_REPORT.md').write_text(report)
(PROJECT/'FINAL_REPORT.md').write_text(report)

def rec(name):return dict(path=name,sha256=sha(PROJECT/name))
state=json.loads((PROJECT/'research_state.json').read_text())
state.update(status='completed',paper_candidate=False,next_experiment='Current paper development no-go. Preserve consumed confirmation. Any continuation needs independent scientific review and a genuinely new, independently sourced validation panel; no same-holdout tuning.',
 datasets=manifests,split_audit=rec('split-audit.json'),results=rec('results.json'),
 evidence=[rec(n) for n in ['results.json','candidate-screen.json','literature-audit.json','nearest-fulltext-audit.json','identity-audit.json','split-audit.json','frozen-selection.json','complete-trial-ledger.json','software-check.json','data-lock.json','code-lock.json','artifact-index.json','FINAL_REPORT.md']],
 claims=[dict(status='provisional',text=f"Frozen single-confirmation MSE improvement {metric['primary_mse_improvement']:.6f}; relative reduction {100*metric['primary_relative_mse_reduction']:.2f}%. Conditional assay-transfer observation only.")],
 completed_at_utc=now(),scientific_disposition='no_go_for_current_paper',live_worker=False)
atomic(PROJECT/'research_state.json',state)
errors=validate(PROJECT/'project.json',PROJECT/'research_state.json',mode='commit')
atomic(PROJECT/'protocol-validation.json',dict(valid=not errors,errors=errors,
     scope='Provenance/bookkeeping only; does not assess novelty, mechanistic validity, independence adequacy or publication readiness.'))
assert not errors,errors
bundle=dict(schema_version='openlabs.result_bundle.v1',task_id='functional-genomics-day1-20261021',campaign_id='biomed-day1-20261021',
 lab_id='biomed',domain='biology',status='needs_replan',paper_candidate=False,
 summary=f"Completed frozen eight-policy promoter contrast-transfer pilot, {int(metric['n_confirmation'])} WTC11 test loci. Primary MSE improvement {metric['primary_mse_improvement']:.6f}, conditional block95CI {ci1}. No-go for current paper development; generic phenomenon already known and no independent laboratory validation.",
 artifacts=[dict(artifact_id=n,uri=(PROJECT/n).as_uri(),sha256=sha(PROJECT/n),kind='evidence') for n in ['FINAL_REPORT.md','results.json','plan.json','data-lock.json','code-lock.json','artifact-index.json','protocol-validation.json','complete-trial-ledger.json']],
 claims=[dict(claim_id='conditional-assay-transfer',text=state['claims'][0]['text'],status='supported',
               evidence=['results.json','complete-trial-ledger.json'],limitations=r['limitations'])],
 next_actions=['Preserve all consumed confirmation labels and negative/null evidence; do not adapt models on this holdout.',
               'Only an independent scientific audit plus new external laboratory/context data can justify a next study or paper promotion.'])
atomic(PROJECT/'result-bundle.json',bundle)
(PROJECT/'CHECKPOINT.md').write_text(f'# 最后检查点\n\n{now()}\n\n8策略比较与一次WTC11确认完成。主改善={metric["primary_mse_improvement"]:.6f}，区块95%CI={ci1}。paper_candidate=false，论文推进no-go。全部payload重哈希及划分重算通过；通用pilot协议通过仅表明记录一致。没有再次打开确认集。最终报告和完整账本已保存。所有下载进程必须在交付前确认为退出，无后台训练。\n')
status('final_evidence_packaged','Completed conditional promoter contrast-transfer pilot; paper no-go',
       'finalize.py completed',[PROJECT/'FINAL_REPORT.md',PROJECT/'result-bundle.json',PROJECT/'protocol-validation.json'],state='completed')
print(json.dumps(dict(protocol_valid=not errors,paper_candidate=False,scientific_disposition='no_go_for_current_paper',
     report=str(WORKER/'FINAL_REPORT.md'),bundle=str(PROJECT/'result-bundle.json')),indent=2))
