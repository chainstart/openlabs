"""Assemble truthful closeout from persisted evidence; never refit or select."""
from common import *
import importlib.metadata
import sys
import subprocess

result=json.loads((ART/'confirmation-results.json').read_text())
review=json.loads((ART/'result-review.json').read_text())
inputs=json.loads((ART/'final-input-audit.json').read_text())
trials=json.loads((DATA/'trial-ledger.json').read_text())
external=json.loads((DATA/'beataml-feasibility-reproducible.json').read_text())
freeze=json.loads((DATA/'freeze-ledger.json').read_text())
strong=json.loads((ART/'strong-baseline-comparisons.json').read_text())
assert result['confirmation_openings']==1 and review['retained_split_audit_valid']
assert all(review['freeze_unchanged'].values()) and all(x['matches'] for x in inputs['official_payload_checksum_checks'])
assert not result['primary']['material_misalignment_supported']
stamp=now()
environment={'at':stamp,'interpreter':sys.executable,'python':sys.version,'lock_sha256':hashlib.sha256((ROOT/'openlabs/labs/biomed/uv.lock').read_bytes()).hexdigest(),'versions':{p:importlib.metadata.version(p) for p in ['numpy','pandas','scipy','scikit-learn','rdkit','joblib','matplotlib']},'cgroup':Path('/proc/self/cgroup').read_text(),'threads':2,'cuda_used':False,'installed_packages_during_lane':False}
assert 'openlabs-workers.slice' in environment['cgroup'] and 'openlabs-biomed-four-drug-support-20261021.service' in environment['cgroup']
write(DATA/'environment-final.json',environment)
resource=subprocess.run(['systemctl','--user','show','openlabs-biomed-four-drug-support-20261021.service','-p','CPUQuotaPerSecUSec','-p','MemoryHigh','-p','MemoryMax','-p','MemorySwapMax','-p','TasksMax','-p','MemoryPeak'],check=True,text=True,capture_output=True).stdout
budget={'at':stamp,'download_actual_bytes':json.loads((ART/'download-ledger.json').read_text())['actual_bytes'],'artifact_tree_bytes':sum(p.stat().st_size for p in ART.rglob('*') if p.is_file()),'download_limit_bytes':6*1024**3,'scratch_limit_bytes':12*1024**3,'service_properties':resource,'worker_cleanup':'All explicitly launched Python job sessions completed; no background worker launched by this recovery.'}
assert budget['download_actual_bytes']<=budget['download_limit_bytes'] and budget['artifact_tree_bytes']<=budget['scratch_limit_bytes']
write(ART/'resource-final.json',budget)
candidates=[
 {'id':'C1','design':'CTRP/CCLE cross-institution raw-curve and independent-repeat validation','stage':'metadata_and_access_feasibility','disposition':'deprioritized; CCLE published aggregation cannot split independent repeats; old CTRP official route migrated and current public query failed. Official alternatives were audited; not a claim all routes impossible.','evidence':['intake/upstream-CCLE_README.md','intake/upstream-CTRP_README.md','intake/ccle-supp-europepmc.bin','intake/nci-public-schema.json.manifest.json'],'prediction_configurations':0},
 {'id':'C2','design':'PRISM same-pair original run to MTS010 redo, target fit X1/X2 versus measured X3','stage':'completed_frozen_experiment','disposition':'primary material-misalignment hypothesis unsupported; repeat-order filter did not beat same-coverage source-gap baseline; not paper candidate','evidence':['plan-frozen.json','confirmation-results.json','result-review.json'],'prediction_configurations':11,'curve_configurations':1},
 {'id':'C3','design':'BeatAML ex vivo same-specimen cross-run repeat validation','stage':'metadata_feasibility_completed','disposition':'Among fully specified sequencing-sample signatures only10 source>=2/target>=3 same-readtime cross-run pairs, all in1 donor; insufficient donor-independent external confirmation. Exact reagent structures also not established by drug-family workbook. No viability outcomes analyzed.','evidence':['beataml-feasibility-reproducible.json','beataml-official-mapping-schema.json'],'prediction_configurations':0}
]
write(DATA/'candidate-ledger.json',{'at':stamp,'max_candidates':3,'candidate_count':3,'count_not_reset_after_crash':True,'candidates':candidates})
events=[
 {'step':'original metadata intake','status':'completed_with_failures','detail':'Official CTRP redirects, publisher/PMC access failures, empty CCLE supplementary XLSX and NCI405 retained in manifests; used official alternatives.'},
 {'step':'SMILES metadata parser','status':'corrected_before_freeze','detail':'Comma-separated annotations initially parsed incorrectly; initial tables retained with .initial-incorrect-smiles-parser suffix; no model outcomes inspected for correction.'},
 {'step':'freeze','status':'completed','at':freeze['at_utc'],'sha256':freeze['files']['plan-frozen.json']},
 {'step':'curve processing before crash','status':'interrupted','detail':'Progress14000/20367,7194 eligible persisted only as counts; no completed fitted-curve result file. Normalized matrix survived.'},
 {'step':'recovery input audit','status':'completed','detail':'78 original payload SHA256 and all frozen hashes verified; empty derived CCLE audit JSON preserved, recreated separately from original archive.'},
 {'step':'curve recovery','status':'completed','detail':'Reused normalized matrix and reran identical curve math; no model/config/split/threshold change.8406 incomplete/control failures,1682 optimizer failures retained.'},
 {'step':'development baseline comparison','status':'completed','detail':'11 fixed prediction configurations,1 curve configuration; seed20261021. RF_leaf20 chosen by validation for secondary reporting; primary HGB unchanged. No optional seed repeats performed.'},
 {'step':'confirmation','status':'completed','detail':'One recorded opening after saved model hash and evaluation implementation; all eleven methods evaluated without retuning.'},
 {'step':'independent arithmetic reconstruction','status':'completed','detail':'Same agent separate segment integrator and stdlib group means; real raw plate normalization reproduced. Not independent human or laboratory validation.'},
 {'step':'BeatAML XLSX schema','status':'initial_dependency_failure_resolved','detail':'openpyxl absent; used bounded stdlib ZIP/XML, no installation. Kd annotations not mixed with viability endpoints.'},
 {'step':'external feasibility','status':'completed_no_go','detail':'Source/target repeat conditions concentrate in one donor, not a cohort validation.'}
]
write(DATA/'all-trials-ledger.json',{'at':stamp,'events':events,'models':trials,'candidate_ledger':'candidate-ledger.json','download_attempts':'artifact/intake/*.manifest.json and download-ledger.json','optimizer_failures':'artifact/curve-exclusions.csv.gz','confirmation_openings':1,'configurations_cumulative':12,'max_configurations':12})
compat={'at':stamp,'protocol':'biomed-public-data-pilot','fully_validated':False,'applicable_evidence':['Frozen plan/hash ledger','Exact locked interpreter/environment','Official byte/SHA256/MD5-bound inputs','Identifier split audits before and after exclusions','All configurations, failures, predictions and paired intervals','Chinese final report'],'not_covered':['Protocol scalar independent_unit does not encode structure x cell x assay plate/pool dependence','Frozen plan uses crossed drug AND cell split and same-pair source measurements','Artifact payload files live outside small data workspace, unlike validator-relative payload contract'],'meaning':'No claim of factory protocol pass or publication readiness; no factory SQLite write'}
write(DATA/'protocol-compatibility.json',compat)
source_registry={'at':stamp,'scope':'drug_support only, no shared registry write','primary':{'provider':'Broad DepMap','release':'PRISM19Q4 v4','doi':'10.6084/m9.figshare.9393293.v4','terms_url':'https://creativecommons.org/licenses/by/4.0/','upstream':'Corsello2020 + MTS010 technical redo','allowed_hosts':['api.figshare.com','ndownloader.figshare.com','s3-eu-west-1.amazonaws.com'],'verification':'Official file IDs, byte counts and MD5; all local payloads SHA256-bound','inputs':inputs['official_payload_checksum_checks']},'external_metadata':{'provider':'BeatAML investigators','commit':'6e403e142469dfb8ab20af0a4e6bf0fdaaf474e8','allowed_hosts':['api.github.com','raw.githubusercontent.com','media.githubusercontent.com'],'verification':'Pinned official repository; Git LFS pointer SHA256 and sizes match metadata XLSX; repository CC BY4.0','response_use':'No normalized_viability parsing/modeling'}}
write(DATA/'source-registry-scoped.json',source_registry)

def ci(d):return f"{d['macro_drug_mae']:.5f} [{d['two_way_ci95'][0]:.5f}, {d['two_way_ci95'][1]:.5f}]"
table='| 对照 | 拟合X1/X2 MAE [95%区间] | 实测X3 MAE [95%区间] | 药物内细胞排序错误率 |\n| --- | --- | --- | --- |\n'
for name,v in result['all_baselines'].items():
    rank=result['ranking']['within_drug'][name]['target_raw_auc']['macro_drug_error']
    table+=f"| {name} | {ci(v['target_fit_auc'])} | {ci(v['target_raw_auc'])} | {rank:.2%} |\n"
basecmd=f"{ROOT}/openlabs/bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 {environment['interpreter']}"
report=f'''# drug_support 路线最终报告

时间：{stamp}。**本轮冻结真实实验已完成，主假说未获支持，paper_candidate=false。未获得可以声称达到2025中科院升级版大类二区论文要求的成果。** 这是科学结案，不是用进程结束替代目标完成；不延长2026-10-22 11:46:31 UTC截止时间，不修改全局选刊政策，不选刊、投稿、付费或公开发布。

## 问题、用途与最近工作

用途是已有同药、同细胞源筛选结果时，向另一运行迁移并排序细胞敏感性。问题是：固定树模型对目标拟合摘要的改善，是否夸大对独立第三技术重复、实际浓度支持内响应的改善？所有确认配对均有源响应输入，故不是未知新药/新细胞的从零预测。精确结构留出不是骨架、机制或独立实验室留出。

[2016 adjusted AUC](https://doi.org/10.18632/oncotarget.10010)、[2025 specification game](https://doi.org/10.1186/s13321-025-00972-y)、[2026 potency benchmark](https://doi.org/10.1038/s42004-026-01916-9)、[2026 harmonization](https://doi.org/10.1093/bioinformatics/btag382)、[DrEval](https://doi.org/10.1038/s41467-026-72903-w)及[2026 intraclass generalization](https://doi.org/10.1371/journal.pcbi.1013232)已经覆盖浓度协调、评价混杂、强基线、原始曲线、跨研究与ex vivo等一般问题。本轮仅增加拟合重复与测量重复分离的窄检验；没有凭有限搜索认定首创。详细原始来源、代码commit和三个候选裁定见 [LITERATURE_AND_SOURCE_AUDIT.md]({DATA}/LITERATURE_AND_SOURCE_AUDIT.md)。

## 实际数据、冻结与独立性

使用[Broad PRISM19Q4 v4](https://doi.org/10.6084/m9.figshare.9393293.v4)官方原始MFI、精确SMILES与DepMap ModelID。源HTS002/MTS006对目标MTS010技术重做；确认集46结构来自HTS002、4结构来自MTS006。各plate按独立车辆/阳性对照做冻结归一化，无跨样本ComBat。这里的“实测响应”是归一化荧光/条码读数的曲线摘要，**不是无噪声药效真值或患者疗效**。

元数据候选56,626配对、146结构、473模型；双轴交叉划分只保留同分区组合，20,367配对进入处理。曲线完整性/对照质控排除8,406，固定3PL优化上限内未收敛排除1,682；均保留原因，不按响应强弱或拟合R²删除。实际保留：

| 分区 | 配对 | 精确结构 | 模型 |
| --- | ---: | ---: | ---: |
| 训练 | 4548 | 47 | 183 |
| 验证 | 987 | 20 | 90 |
| 确认 | 4744 | 50 | 178 |

确认涉及20个细胞池、5个目标化合物板，每结构63–136个细胞；这些数目不等于4,744个独立实验。训练/验证/确认的结构与ModelID均无交叉，`samples-frozen.csv`及保留后`samples-retained.csv`分别通过标识审计。共同剂量区间由元数据冻结，源/目标至少4个支持剂量且宽度至少1.2 log10；不比较不同全范围AUC，不混合IC50/Ki/Kd，不将拟合值粗化区间当IC50置信界。

源使用至少两次完整重复，目标X1/X2仅用于拟合标签，X3仅用于实测评价。源与目标归一化按各自检测板完成；技术重复共享Broad计划、池和化合物板，不能称为不同实验室或患者队列。确认字节曾用于预处理，但效果评价只开启一次，模型/阈值/特征均未据确认结果修改。原冻结时间 {freeze['at_utc']}；计划SHA256 `{freeze['files']['plan-frozen.json']}`。

断电恢复时重验78个原始payload SHA256及全部冻结哈希；归一化矩阵完整而14,000配对的中断曲线结果仅在内存，故只重算同参数曲线步骤。没有重置3候选/12配置预算。八个PRISM输入又与官方字节数和MD5逐一匹配。旧GDSC报告与75,627配对的原始实验未在本机复算，不将旧测试当新确认。

## 主结果与全部对照

冻结主比较是 HGB 相对 identity_fit 的收益差：拟合标签MAE下降量减去X3实测MAE下降量。按药物等权宏平均，2,000次药物×细胞双轴成对bootstrap，实际相关门槛+0.02。

- 拟合标签收益 **0.00613**，95%区间 **[−0.00079, 0.01330]**。
- 实测X3收益 **0.01068**，95%区间 **[0.00470, 0.01682]**。
- 主收益差 **−0.00455**，95%区间 **[−0.00994, 0.00121]**；药物×池敏感性区间 **[−0.01099, 0.00258]**。

因此没有达到+0.02的“拟合收益实质夸大”门槛，也没有“拟合改善而实测恶化”的反转。该条件区间上界低于预设门槛，但**区间包含零不表示两端点等价**，更不证明所有筛选标签都可靠。

{table}

以上MAE单位是归一化共同支持AUC。三个均值对照在双轴新身份确认中都退化成训练总体均值，这是规定的未知身份回退，不是数据泄漏。剂量对照与HGB使用相同容量；RF各200树，两个叶节点配置全部报告。验证选择RF_leaf20只作次要结果，主HGB未替换。11个预测配置加1个固定曲线配置，累计12/12；随机种子20261021，无额外种子选优。树模型间主收益差范围及全部未截断端点/排序区间在 `confirmation-results.json`。

HGB相对强简单对照identity_raw的实测收益仅 **0.00010 [−0.01059, 0.01142]**；不能建立新方法优势。其相对identity_raw的拟合收益较大是次要比较，不能据此换掉已冻结主比较制造正结果。相对affine_fit的实测收益 **0.00235 [−0.00153, 0.00677]**。最近协调方法只以已发表共同支持3PL方法家族作为identity_fit对照；没有精确复现2026最优截断后拟合流程，也没有完整DrEval调参基准，不能主张超过这些方法。

![所有基线与双轴区间](all-baseline-errors.png)

## 排序、敏感性与结果复核

源重复排序一致规则平均保留 **61.18%** 比较，X3排序错误 **33.36%**；相同覆盖的源拟合差值筛选为 **31.82%**，相差 **+1.54个百分点**，仅按药物重采样的条件区间 **[+0.12,+2.75]个百分点**。方向不支持重复一致规则更优；该排序区间未覆盖共享细胞/板的全部依赖，不能当作跨实验室显著结论。排序配对数不充当独立样本数。所有方法药物内排序、相同共同支持下的细胞内药物排序见CSV/JSON。

未将X3截断到[0,1]时，HGB实测收益 **0.00506 [−0.00131,0.01253]**，主收益差 **0.00107 [−0.00281,0.00481]**，仍不支持预设实质夸大。去掉每一目标化合物板后主差值均为负，范围 **−0.00576至−0.00368**；但仅5个板不能提供广泛板层推断。确认源/目标拟合R²中位数约0.097/0.108，负R²约40.8%/39.2%；这些弱响应和噪声曲线保留，不事后美化数据。

独立实现的逐线段积分重算全部4,744确认配对；标准库分组均值重算主效应；6个原始检测板、各499行的归一化重新计算，数值差为0。结构规范化1,413条有效注释、保留样本划分、冻结文件不变性均复核。复核由同一研究代理以独立实现完成，**不是独立研究人员审查或新实验验证**。数学软件检查只用于核对实现，合成数组不作为科学证据。

## 备选路线与停止判断

C1核查CTRP/CCLE原始路线和官方替代：CCLE公开聚合值不能分出第三原始重复；官方补充档案虽下载成功，XLSX成员为空；CTRP旧入口迁移后的访问与查询失败均保留，未绕过403/验证，也未宣称所有替代均不可用。

C3实际取得BeatAML原始表及官方样本/药物注释，只做元数据审计。虽然有3,009个至少三重复组合、266供体和28药物名称，严格保留完整测序样本身份后，具备源≥2重复、目标不同运行≥3重复且读数时间相同的仅 **10配对/10药物/1供体**。一个供体不能支持外部供体泛化；不同时间/不同样本不混作重复，药物家族表也不能替代精确结构映射。未解析该表的normalized_viability、未训练ex vivo模型，不能称为完成外部效果验证。

本轮停止理由是：已完成预定独立技术重复检验，主诊断假说不成立于这个预设门槛与分析总体；排序方案不胜强简单对照；最近工作已覆盖一般问题；可审计的外部重复门槛尚不足。保留负结果，**不声称整个药敏领域穷尽，也不把研究运行时长当贡献**。未来如继续，必须解决独立实验室或供体级源/目标重复、精确试剂身份和预定用途，再取得新的确认边界；本轮已暴露确认不能再用于选型。

## 文件、试验账本与复现

完整配置/失败/种子/恢复记录：[{DATA}/all-trials-ledger.json]({DATA}/all-trials-ledger.json)。候选裁定在`candidate-ledger.json`；排除逐行在`curve-exclusions.csv.gz`；预测/模型/2,000次bootstrap保留artifact。`result-review.json`、`final-input-audit.json`、`analysis-software-checks.json`、`protocol-compatibility.json`及`reproducibility-inventory.json`绑定证据。通用pilot协议没有完整表达本设计的多轴实验依赖和跨artifact路径，**未伪造协议通过或工厂接收**；未写工厂SQLite。

实际解释器：`{environment['interpreter']}`；锁SHA256：`{environment['lock_sha256']}`；软件实际版本见`environment-final.json`。本轮下载累计 **{budget['download_actual_bytes']:,} bytes**，收尾时artifact文件 **{budget['artifact_tree_bytes']:,} bytes**，均低于6GiB/12GiB。服务始终2CPU、4GiB软/5GiB硬、512MiB swap、96任务；无CUDA，无新包安装，无嵌套Codex或派生代理，无共享环境修改。实际资源峰值见`resource-final.json`。

以下可在当前已完成证据上复核，既不训练也不选型：

```bash
{basecmd} {CODE}/check_analysis.py
{basecmd} {CODE}/review_results.py
{basecmd} {CODE}/final_audits.py
{basecmd} {CODE}/audit_external_metadata.py
```

历史执行顺序为`prepare_curves.py → models.py → evaluate.py → review_results.py → final_audits.py`，全部使用上述护栏和解释器；模型及确认入口拒绝静默重跑已完成状态。完整重现实验须使用隔离副本并明确标记为已暴露数据的计算复现，不能把第二次运行当新确认。原冻结文件、旧失败文件和本轮负结果不覆盖。
'''
(ART/'FINAL_REPORT.md').write_text(report)
result.update(schema_version='openlabs.drug_support_research_results.v1',finished_at_utc=stamp,status='completed',scientific_disposition='completed_frozen_pilot_no_go_for_paper_target',research_question=json.loads((DATA/'plan-frozen.json').read_text())['research_question'],independent_unit=['exact chemical structure','official cell model','screening run','plate/pool'],baselines=result['all_baselines'],metrics={'primary_misalignment':result['primary']['misalignment'],'fit_gain':result['primary']['fit_gain'],'measured_gain':result['primary']['measured_gain']},candidate_ledger=candidates,configurations_cumulative=12,configuration_budget=12,external_validation={'completed':False,'feasibility':external},strong_baseline_comparisons=strong,protocol_compatibility=compat,resources=budget,run={'command':basecmd+' '+str(CODE/'evaluate.py'),'seed':20261021,'code_revision':'uncommitted task-scoped scripts, individually SHA256-bound in reproducibility-inventory.json','environment_sha256':hashlib.sha256((DATA/'environment-final.json').read_bytes()).hexdigest(),'plan_sha256':freeze['files']['plan-frozen.json'],'model_sha256':trials['model_sha256']})
for root in [ART,DATA]:write(root/'RESULTS.json',result)

def hash_file(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return {'path':str(p),'bytes':p.stat().st_size,'sha256':h.hexdigest()}
items=[*CODE.glob('*.py'),*(p for p in DATA.glob('*') if p.is_file() and p.name not in ['research_status.json','reproducibility-inventory.json']),*ART.glob('*.json'),*ART.glob('*.csv*'),ART/'models.joblib',ART/'FINAL_REPORT.md',*ART.glob('*.png'),*ART.glob('*.svg'),*ART.glob('development/*'),*ART.glob('sealed/*'),*ART.glob('intake/*.manifest.json')]
excluded={'research_status.json','reproducibility-inventory.json','process-status.json'}
inventory={'at':stamp,'files':[hash_file(p) for p in sorted(set(items)) if p.is_file() and p.name not in excluded],'primary_inputs':inputs['official_payload_checksum_checks'],'all_original_payload_checks':'recovery-integrity.json','scope':'Code, frozen/data records, predictions/models/curves/results, and manifests; raw payload hashes in manifests and verified recovery/final input audits.'}
write(ART/'reproducibility-inventory.json',inventory);write(DATA/'reproducibility-inventory.json',inventory)
s=json.loads((ART/'research_status.json').read_text())
s.update(status='completed',updated_at_utc=stamp,completed_at_utc=stamp,stage='scientific_closeout',paper_candidate=False,scientific_disposition='completed_frozen_pilot_no_go_for_paper_target',completed=['Recovered original frozen plan and verified payloads','Completed original3PL curve processing and11 baseline configurations','Opened independent technical-repeat confirmation once','Computed primary/secondary and cluster/plate sensitivity results','Reconstructed raw integration, group means, input checksums and selected raw normalization','Audited3 candidate data designs; BeatAML cross-run eligibility concentrates in1donor','Chinese FINAL_REPORT.md, RESULTS.json, full ledger and hashes written'],remaining=[],failures=['Primary material-overstatement hypothesis unsupported','Repeat consistency ranking did not beat equal-coverage source difference baseline','No independent laboratory or donor-cohort effect validation','Closest2026 truncated-fit protocol not exactly reproduced; no method-SOTA claim'],stop_reason='Frozen scientific comparison and necessary sensitivity/review completed; no supported paper contribution. Not stopping solely on a download failure or process liveness.',evidence_paths=[str(ART/'FINAL_REPORT.md'),str(ART/'RESULTS.json'),str(ART/'reproducibility-inventory.json'),str(DATA/'all-trials-ledger.json')])
s['actual_commands']+=[basecmd+' '+str(CODE/f) for f in ['evaluate.py','review_results.py','final_audits.py','audit_external_metadata.py','make_figures.py','finalize.py']]
for root in [ART,DATA]:write(root/'research_status.json',s)
print(json.dumps({'status':s['status'],'scientific_disposition':s['scientific_disposition'],'paper_candidate':False,'report':str(ART/'FINAL_REPORT.md'),'inventory_files':len(inventory['files']),'budget':budget},indent=2))
