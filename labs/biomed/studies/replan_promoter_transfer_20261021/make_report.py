from common import *
import numpy as np,pickle,subprocess,shutil
guard_check()
final='--final' in sys.argv
r=json.loads((ART/'analysis/test-results-corrected.json').read_text())
original=json.loads((ART/'analysis/test-results.json').read_text())
parts=json.loads((DATA/'partition-summary.json').read_text())
plan=json.loads((DATA/'plan.json').read_text())
freeze=json.loads((DATA/'freeze.json').read_text())
training=json.loads((DATA/'training-completed.json').read_text())
resources=json.loads((DATA/'resource-and-download-audit.json').read_text())
arithmetic=json.loads((DATA/'arithmetic-review.json').read_text())
names={'klein_wt':'Klein WT','tovar_ins':'Tovar INS','tovar_scp1':'Tovar SCP1（同研究补充）'}
point_names={'identity':'identity','affine':'affine','ridge':'ridge（α=10）','class_mean':'类别均值','author_affine':'作者来源估计线性校准','base_hgb':'HGB 基础','precision_hgb':'HGB 加重复精度'}
risk_names={'constant':'常数风险／ID 平分','source_sem':'来源 SEM²','source_sem_plus_dna':'来源 SEM² + DNA Poisson','base_hgb':'风险 HGB 基础','precision_hgb':'风险 HGB 加重复精度'}
fmt=lambda x:f'{x:.6f}'
cell=lambda v,m:f"{fmt(v[m])} [{fmt(v['CI95'][0])}, {fmt(v['CI95'][1])}]"
point_keys=list(point_names);risk_keys=list(risk_names)
post={};baselines={};metrics={}
for ctx,c in r['contexts'].items():
    z=np.load(ART/'analysis'/(ctx+'_test_bootstrap_corrected.npz'))
    selected=training['validation'][ctx]['best_validation_point_baseline']
    j=point_keys.index(selected);f=point_keys.index('precision_hgb')
    delta=z['point'][:,j]-z['point'][:,f]
    post[ctx]=dict(validation_selected_point_baseline=selected,
      precision_point_improvement=c['point'][selected]['MSE']-c['point']['precision_hgb']['MSE'],
      CI95=np.quantile(delta,[.025,.975]).tolist(),
      validation_selected_risk_baseline=training['validation'][ctx]['best_validation_risk_baseline'])
    for k,v in c['point'].items():baselines.setdefault('point:'+k,{})[ctx]=v
    for k,v in c['risk50'].items():baselines.setdefault('risk:'+k,{})[ctx]=v
    metrics[ctx+'_primary_absolute_improvement']=c['primary']['absolute_improvement']
    metrics[ctx+'_primary_relative_improvement']=c['primary']['relative_improvement']
    assert original['contexts'][ctx]['primary']==c['primary'],'primary changed after arithmetic correction'
limitations=plan['limitations']+[
 'Closest published915-feature Klein residual LASSO not reproduced; published-source calibration is not an equivalent full comparator.',
 'Klein source/target repeat variance diagnostic assumes covariance0, but designs were performed on matched days; shared batch effects are possible.',
 'Bootstrap conditions on fitted models, normalizers and observed repeat estimates; excludes training refit and study-population uncertainty.',
 'Both studies fit their own calibrations; this is replication of a fixed procedure in another original experiment, not zero-shot transfer of a Klein-trained model to Tovar.',
 'Post-confirmation arithmetic correction applies12-decimal risk-score tie equality; original outputs retained, primary results unchanged.',
 'Early HTTP handoff concurrency was not provably <=2; all later downloads used an aggregate2-slot semaphore.',
 'No broad sequence-only state-of-the-art benchmark, causal mechanism or endogenous/clinical validation.',
 'Half coverage means half the locus groups, not half the fragments/barcodes or a proven50% experimental cost saving.',
 'Tovar eligibility uses input-DNA/barcode coverage in all designs; prospective interpretation is conditional on this common measurable cohort, not unrestricted source-only library screening.'
]
result=dict(time=now(),stage='exploratory_pilot',status='needs_replan' if final else 'running_final_review',
    scientific_disposition='registered_incremental_source_precision_claim_not_supported; bounded_pilot_completed; publication_contribution_gate_not_met',
    paper_candidate=False,research_question=plan['question'],independent_unit=plan['independent_unit'],
    original_directionality_question_answered=False,upstream_experiments=2,independent_third_SCP1_experiment=False,
    metrics=metrics,baselines=baselines,contexts=r['contexts'],primary_replication_passes=False,
    validation=training['validation'],descriptive_selected_baseline_comparison=post,
    sample_summary=parts['summary'],trials_run=12,context_configuration_evaluations=36,internal_OOF_affine_fits=15,
    new_candidates_used=3,historical_candidates=3,historical_configurations=8,limitations=limitations,
    run=dict(cwd=str(ROOT),commands=['bin/openlabs-resource-guard --task-type cpu -- '+str(ROOT/'labs/biomed/.venv/bin/python')+' labs/biomed/studies/replan_promoter_transfer_20261021/'+f for f in ['aggregate_tovar.py','partition.py','freeze.py','experiment.py fit','experiment.py open-test','experiment.py summarize','experiment_tie_corrected.py summarize','review_arithmetic.py','audit_evidence.py']],
       code_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
       uncommitted_lane_code=True,code_sha256={p.name:sha(p) for p in pathlib.Path(__file__).parent.glob('*.py')},seed=20261021,
       interpreter=str(ROOT/'labs/biomed/.venv/bin/python'),environment_SHA256=sha(DATA/'environment.lock'),
       freeze_sha256=sha(DATA/'freeze.json'),original_results_sha256=sha(ART/'analysis/test-results.json'),corrected_results_sha256=sha(ART/'analysis/test-results-corrected.json')),
    evidence_contract=dict(applied=['prospective plan','exact lock','public intake hashes','sample-linked group split audit','all baselines','trial ledger','limitations'],formal_validator_passed=False,reason='Custom paired-assay risk design and lane three-directory layout; no fabricated protocol pass.'),
    next_step='Do not reopen these held-out panels as fresh confirmation. A new research phase would need author intermediate filtering, closest full comparator, and a new unexposed independent panel or new experiment; current12-configuration budget is exhausted.')
dest='RESULTS.json' if final else 'RESULTS.draft.json';write(ART/dest,result)
lines=[]
add=lines.append
add('promoter_transfer 六小时重规划：来源重复精度与跨报告位置风险\n')
add(f"{'科学结案' if final else '最终复核中的草稿'}；更新时间 {now()}。本轮截止时间固定为 2026-10-21 19:51:45 UTC，未另起六小时。\n")
add('本轮完成三个候选的门槛评估，并对优选问题进行了真实数据实验。预注册主假设未获支持：在已观测来源活性、测序支持、序列组成及注释之外，加入来源重复精度，没有在两个原始实验中带来预设的实用风险排序增益。科学状态为 **needs_replan，paper_candidate=false**。这不是二区论文成果，也不是“所有测量精度方法均无用”的结论。\n')
add('此处预登记指本路线本地带时间与哈希的冻结方案，未做公开平台注册。数据均为既有公开实验，本轮新增的是计算分析与一次预留位点确认，没有新开展湿实验。\n')
add('研究问题改为：在尚未测量某位点的目标报告设计时，能否利用来源侧三个重复的离散度，挑出校准迁移误差较小的位点组？本轮测量的是增强子／调控片段跨报告位置的相对活性；没有回答原始的启动子方向性问题。两研究分别训练自己的校准模型，属于同一固定程序在另一原始实验中的再检验，不是把 Klein 模型零样本应用于 Tovar。\n')
add('**先验审计与三个候选。** 历史 3 候选、8 配置保留在总账，旧 267 位点及 Agarwal／QUASARR／Tan500P 已暴露测试均只作开发背景。旧完成文件已做哈希审计，但旧原始实验未同步，不能称重新验证原实验。\n')
add('| 本轮候选 | 实际门槛与裁定 |\n|---|---|\n| R1：跨研究连续 responsiveness 校准 | 新 long-range 654 个 215nt 构建与 Bergman/Tan 264nt 构建未建立全长同一性；旧 500P 已暴露。未找到可用的新确认配对，不以坐标重叠替代插入同一性。 |\n| R2：来源重复精度增量风险排序 | 核验两个原始实验，冻结后完成 12 配置、三个预指定条件的真实比较。主假设未通过。 |\n| R3：局部启动子突变背景依赖 | PARM 已直接分析 4 motif ×15 位置 ×19 启动子背景及基础活性依赖；19 个背景的约 80% 功效参考为 0.64 SD，不能把构建/细胞数当独立背景。新颖性与独立确认门槛未过。 |\n')
add('**与最近工作的区别及未完成的比较。** [Klein 2020](https://doi.org/10.1038/s41592-020-0965-y) 已展示高重复一致性与跨设计差异，并用 loess 残差及 915 个特征的 LASSO 预测设计差异；因此“重复可靠仍可能不迁移”和“设计偏差可预测”不是本轮发现。本轮仅检验固定来源特征上的重复精度增量，未复现该 915 特征 LASSO；作者来源估计校准不能冒充该完整方法对照。\n')
add('[Tovar 2026](https://doi.org/10.1016/j.xhgg.2026.100606) 已分析 promoter/position 偏差、motif LASSO，并做 HNF1 扰动；本轮不重复宣称这些是新贡献。[PARM 2026](https://doi.org/10.1038/s41586-025-10093-z) 的跨背景建模及突变实验，[Tan 2026 预印本](https://doi.org/10.64898/2026.06.25.734173) 的多报告设计 responsiveness，以及 [Yang 2026 v3 预印本](https://arxiv.org/abs/2601.14969v3) 的不确定性/risk-coverage 研究，都进一步限定了可主张的空间。未检索到完全同题不能证明首创。\n')
add('本轮还刷新了 [Roberts 2021](https://doi.org/10.1101/gr.270751.120)、[Agarwal 2025](https://doi.org/10.1038/s41586-024-08430-9)、[Zhang 2025](https://doi.org/10.1186/s13059-025-03828-8)、[QUASARR 2026](https://doi.org/10.1038/s41467-026-68780-y) 及 [RegTrust-XAI 2026 预印本](https://doi.org/10.64898/2026.08.20.745945) 的原始论文或登记信息；直接相关的新 Tovar 正式论文及 Yang v3 全文另行阅读。RegTrust-XAI 的本轮核查深度为摘要/登记信息，不能据此声称已完整排除其方法重叠。检索来源和失败记录见 literature-refresh-index.json、closest-method-review.json。\n')
add('**数据与独立单位。** Klein GSE142696 的 5′/3′ WT→3′/3′ WT 使用同一 171nt 元件库，HepG2 三个独立培养/日期重复。序列从作者 hg19 区间对应的 192nt 参考设计精确截取，属于文档级设计核验，不是实物重新测序。2231 个有基因组定位的记录中 2230 个重复完整，形成 1138 个位点组。Tovar GSE279057 为四载体混合库、832/13 rat insulinoma 细胞中的三次电转；三个 RNA 重复共享一份 plasmid DNA 输入。该数据亦出现在 Bose 相关分析中，不计为另一个原始实验。SCP1 与 INS 共用同一实验/位点，只作补充。\n')
add('Tovar 注释有 79380 条设计；使用 fullseq 并逐条核对/剥离 lanch、ranch，保留 79200 条 198nt ACGT 插入，排除 180 条非该长度设计。noflankseq 在 alternate 行仍是参考序列，不能直接作为替代等位基因的实际插入。原计数含 3215489 条唯一条码；只做精确条码连接，排除歧义映射。保留每条码 DNA≥10 且每片段在四条件中均有 >2 合格条码的 16094 个片段，形成 377 个位点组。该队列**不等于论文的 11656 片段队列**：作者仓库从未提供的中间过滤表开始，本轮不能声称原处理流程精确复现。未按目标 RNA 活性或目标精度筛选。\n')
add('计数无表头，GEO 明确描述为三个 RNA 列后接 DNA；仅第四数值列作为 DNA 时，与两个来源侧作者估计呈正相关（Spearman 0.7145、0.6129）。补充表把 Alpha_original 描述为自然对数，而作者绘图代码使用 log2(value)；[MPRAnalyze 原方法](https://doi.org/10.1186/s13059-019-1787-z) 将 α 定义为转录率。因此预先同时提供报告值 Alpha_corrected 及 log2(Alpha_original) 两种固定表示给作者线性对照和两组匹配模型，未按确认效果择优。\n')
add('分组按共享 hg19 1Mb 区块、作者 index signal、完整相同或 ≥99% 全长同长度插入同一性（含反向互补）的连通分量进行，跨两研究统一划分。初始“共享任意 40mer”会由重复 DNA 把 14472 个 Tovar 片段连成大组，已在任何拟合前仅基于元数据纠正；原划分保留。最终全局 1288 个组，跨研究可能共享组，因此研究内组数不能简单相加。模型只有 GC/CpG 等低维组成，未使用 kmer、序列嵌入或预训练模型；仍不声称排除了所有远距离生物相关性。\n')
add('| 数据 | 训练：片段/组 | 验证：片段/组 | 确认：片段/组 |\n|---|---:|---:|---:|')
for ds,p in parts['summary'].items():add('| '+ds+' | '+' | '.join(f"{p[s]['n_rows']} / {p[s]['groups']}" for s in ['train','validation','test'])+' |')
add('\n确认组数的正态均值区间半宽参考约为 Klein 0.094 SD、Tovar 0.161 SD；半覆盖风险差的粗略尺度约 0.190、0.325 SD。它们仅是未知组间 SD 单位的精度参考，不是预先承诺能检出 10% 改善。\n')
add(f"**冻结与分析。** 冻结时间 {freeze['time']}；训练完成 {training['time']}；一次确认打开为 2026-10-21T15:05:18.569689Z，三个条件预测在同一执行中全部保存。冻结代码、计划、六份划分、模型及预测哈希均通过复核；组跨划分重叠为 0。\n")
add('主终点为训练仿射校准模型的目标相对活性平方误差：先对位点组内片段取均值，再等权平均位点组。风险模型仅使用来源活性、来源读数/DNA/条码支持（可得时）、GC、CpG、设计注释及来源作者估计；增量模型只多 log1p(来源 SEM²)。在训练中用五折按组 OOF 仿射误差训练风险模型，所有归一化仅由训练或 OOF 拟合折计算。保留最低风险的一半位点组，比较基础与加精度模型。最低实用效应预设为相对改善 ≥10%、绝对改善 ≥0.01 log2² 且 paired bootstrap 95% 区间下界 >0；Klein 与 Tovar INS 必须分别通过。\n')
add('HGB 固定 100 次迭代、4 叶、learning rate 0.05、min leaf 30、L2=10、无 early stopping；ridge α=10；模型种子 20261021。12 算法配置在三个固定条件共执行 36 次配置评估，另有 15 次内部 OOF 仿射拟合。验证集未用于调参或重训练；最优验证基线仅供描述性比较。10000 次配对位点组 bootstrap 每次重新选半覆盖，条件于冻结模型和归一化；不包含训练重拟合、重复测量参数或研究总体不确定性。\n')
add('半覆盖指半数位点组，不保证半数片段或实验成本。基础／加精度风险模型实际保留的片段数分别为 Klein 376／402（共853），Tovar INS 3786／3408（共6492），SCP1 3418／3470；它们的位点组数始终相同。没有据此声称节约了 50% 实验成本。\n')
add('Tovar 的共同可测队列依据四种设计的输入 DNA／条码覆盖确定，包含目标构建的输入覆盖信息。该信息不进入前瞻风险特征，也没有使用目标 RNA 质量，但应用解释须限定于目标构建 DNA 覆盖已经可得的队列，不能泛化为只持有来源数据时的全库筛选。\n')
add('| 主比较：加精度相对基础风险模型 | 基础半覆盖 MSE | 加精度半覆盖 MSE | 改善（正数更好）及 95% CI | 相对改善及 95% CI |\n|---|---:|---:|---|---|')
for ctx,c in r['contexts'].items():
    p=c['primary'];add(f"| {names[ctx]} | {fmt(c['risk50']['base_hgb']['affine_MSE'])} | {fmt(c['risk50']['precision_hgb']['affine_MSE'])} | {fmt(p['absolute_improvement'])} [{fmt(p['CI95'][0])}, {fmt(p['CI95'][1])}] | {100*p['relative_improvement']:.2f}% [{100*p['relative_CI95'][0]:.2f}%, {100*p['relative_CI95'][1]:.2f}%] |")
add('\n两主条件均未通过。固定模型的条件区间上限分别为 8.12% 和 3.34%，低于预设 10% 改善；这可限制本方案在这些位点上的大幅收益，**不等于所有精度特征或其他模型的等价性结论**。SCP1 的正向点估计也未达阈值，且与 INS 并非独立实验。\n')
add(f"主比较图及可独立导出的 [SVG]({ART}/figures/primary-risk-precision.svg)／[PDF]({ART}/figures/primary-risk-precision.pdf)：\n\n![来源精度增量的确认结果]({ART}/figures/primary-risk-precision.png)\n")
add('全部 7 个点预测配置如下，单位 log2²，方括号为组 bootstrap 95% 区间。\n\n| 点预测配置 | Klein WT | Tovar INS | Tovar SCP1 |\n|---|---|---|---|')
for k,label in point_names.items():add('| '+label+' | '+' | '.join(cell(r['contexts'][c]['point'][k],'MSE') for c in names)+' |')
add('\n全部 5 个风险配置如下，评估对象均为同一仿射预测器在各自所选半数位点组上的误差。Klein 缺少逐片段 DNA 输入计数，SEM²+DNA 与 SEM² 在此数据中相同，不是额外独立证据。\n\n| 风险配置 | Klein WT | Tovar INS | Tovar SCP1 |\n|---|---|---|---|')
for k,label in risk_names.items():add('| '+label+' | '+' | '.join(cell(r['contexts'][c]['risk50'][k],'affine_MSE') for c in names)+' |')
add('\n验证选择的最强点预测基线分别为 Klein ridge、Tovar INS 基础 HGB、Tovar SCP1 ridge。加精度点模型相对这些基线的确认改善为：\n')
for ctx,p in post.items():add(f"- {names[ctx]}：{fmt(p['precision_point_improvement'])}，95% CI [{fmt(p['CI95'][0])}, {fmt(p['CI95'][1])}]。")
add('\n**预定诊断与解释限度。** 以训练位点组 SEM² 的第 25 百分位为固定阈值，Klein 确认中 138 个低 SEM 组的仿射 MSE 为 0.044851，扣除估计重复噪声后的残差平方均值为 0.042593 [0.029414, 0.057846]；Tovar INS 的 40 组对应 1.159741 和 0.614806 [0.398654, 0.857224]。这些值说明本诊断下低重复离散并不消除校准残差，但该一般现象已有直接先例。Klein 诊断假设来源/目标噪声协方差为 0，而匹配日期的批次可能相关；Tovar 共同 DNA 误差仍会保留在“持续残差”中。Poisson DNA 扣除只是敏感性假设，不能把剩余值解释为已识别的生物方差或因果机制。\n')
add('**失败、纠错及复核。** 原始计数字段带填充空格，首次精确条码连接全失败；失败产物已保留，剥离字段空白后重新解析。来源尺度歧义、重处理队列与作者队列不一致、重复 DNA 导致的初始巨大分组，均在拟合前披露并记录。较早 Klein 文献查询使用了错误 DOI，返回 0；已由原始全文 PMC7727316 核验正确 DOI，未把查询失败当作无文献证据。\n')
add('确认后，另一算术实现发现常数风险在按组累加时产生数个 ULP 的误差，破坏了预定 ID 平分规则。统一将所有组均值风险分数舍入到 12 位小数用于排序后，仅常数风险对照发生实质变化；主比较的点估计和区间完全不变。原冻结代码、原汇总、原 bootstrap 均保留，纠正代码/输出另存，模型和预测未改写、未重新打开原始确认数据。这是**确认后的数值纠错**，不能称原始分析未经变动。\n')
add('使用独立列表/补偿求和实现核算 7 点预测、5 风险配置，最大差异 ≤2.3e-16；逐一复核前 500 个 bootstrap 抽样，最大差异 ≤3.6e-15；另用独立 RNG 做 2000 次 bootstrap 算术审计，结论一致。此“独立”指实现不同，仍由同一代理执行，并非独立人工或第二代理评审。用训练行改变可得的目标 RNA、DNA、覆盖及作者目标值，所有点预测和风险分数逐位不变；只改变真实目标标签与诊断。\n')
add('主要剩余限制包括：只有两个原始实验；每个条件只有三个重复，方差估计本身不稳定；Tovar 的单一 DNA 输入与低计数/pseudocount 影响；归一化比较库内相对活性，不能估计报告设计造成的绝对整体表达改变；源作者估计使用整份来源库处理，属于 observed-source 场景；全长设计文档不等于重新测序；位置对比同时包含载体结构、条码关联等变化，不能隔离为纯位置因果效应；未完成最近 915 特征模型对照；没有内源、临床或新湿实验验证。\n')
add(f"**资源与证据。** 全部新运行时通过本路线 CPU resource guard，服务限制保持 CPUQuota 200%、MemoryHigh 4GiB、MemoryMax 5GiB、SwapMax 512MiB、TasksMax 96；BLAS/OpenMP 实测各为 2 线程，未用 CUDA、未安装依赖、未派生代理。审计时服务 memory.peak 为 {int(resources['resources']['memory.peak'])/1024**3:.3f} GiB，memory.events 无 OOM。artifact 约 {resources['artifact_bytes']/1024**2:.1f} MiB；manifest 记录的传输/成员字节合计约 {resources['manifest_body_bytes_recorded']/1024**2:.1f} MiB，另保守计入 10MiB 中断不确定量，远低于 6GiB 下载和 12GiB scratch 限额。\n")
add('早期中断下载器与元数据进程交接时，无法证明瞬时 HTTP 总并发始终 ≤2；之后已使用跨进程文件锁的两个槽统一限制。此例外保留在 operation-errors.json，不能宣称全程严格合规。所有既有完整 payload 只读复用并核对哈希，未重复下载；旧报告与冻结文件未改写。未读取第 3 路未公开结果，未更改全局选刊政策，也未投稿、外发消息、提交或推送。\n')
add('按 evidence-contract 适用部分保存了前瞻计划、实际 lock 快照、公开数据 intake、样本表/分组审计、完整基线、账本和哈希。本题的跨设计风险终点及三个专用目录布局并非标准 confined-project 协议，**没有声称通过其形式验证器**。\n')
add('复核入口与主要证据：\n')
for label,p in [('冻结计划',DATA/'plan.json'),('冻结哈希',DATA/'freeze.json'),('样本与划分审计',DATA/'split-audit.json'),('当前/历史完整试验账本',DATA/'complete-trial-ledger.json'),('实际解释器和 lock',DATA/'environment.json'),('lock 快照',DATA/'environment.lock'),('来源核验 manifest',DATA/'verified-intakes.json'),('数字与边界复核',DATA/'arithmetic-review.json'),('冻结/确认边界哈希复核',DATA/'boundary-and-hash-review.json'),('修正后全结果',ART/'analysis/test-results-corrected.json'),('原始全结果（保留）',ART/'analysis/test-results.json'),('数值纠错记录',DATA/'post-confirmation-correction.json')]:add(f'- [{label}]({p})')
add(f"\n原始复现命令（当时按顺序执行）位于 RESULTS 的 run.commands。当前目录已封存；不要删除 freeze/test-opened 标记或在原目录重新拟合。离线复核程序读取已保存预测、核对哈希，并重算全部点/风险指标及 10000 次 bootstrap，结果已与封存汇总一致；它不读取原始确认数组或拟合模型，也不构成新确认。该只读输入的程序不依赖已结束 campaign 的日期/服务名，但仍强制 resource guard。每次指定一个尚不存在的输出目录：\n\n```bash\ncd {ROOT}\nbin/openlabs-resource-guard --task-type cpu -- \\\n  {ROOT}/labs/biomed/.venv/bin/python \\\n  labs/biomed/studies/replan_promoter_transfer_20261021/replay_saved.py \\\n  --artifact-root {ART} \\\n  --prediction-manifest {DATA}/test-predictions-saved.json \\\n  --output-dir {ART}/replays/manual-replay\n```\n")
add(f"冻结 SHA256：`{sha(DATA/'freeze.json')}`；环境 lock SHA256：`{sha(DATA/'environment.lock')}`；修正汇总 SHA256：`{sha(ART/'analysis/test-results-corrected.json')}`。代码逐文件哈希、输入和预测哈希见 RESULTS 与 evidence-manifest.json。\n")
add('本轮 3 个候选及 12 配置预算已用完，不继续换指标、种子或重开确认集追求正结果。继续研究需要新的未暴露面板或新实验、可审计的作者中间过滤资料，并在新确认之前补齐最接近的完整方法比较；现有确认结果只能作为未来开发证据。以当前新颖性与比较完整度，尚不能建立二区论文级贡献。\n')
report='FINAL_REPORT.md' if final else 'REPORT_DRAFT.md';(ART/report).write_text('\n'.join(lines))
if final:
    shutil.copyfile(ART/'RESULTS.json',DATA/'RESULTS.json')
    shutil.copyfile(ART/'FINAL_REPORT.md',DATA/'FINAL_REPORT.md')
print('wrote',dest,report)
