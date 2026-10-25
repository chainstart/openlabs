from pathlib import Path
import json,hashlib,shutil,datetime
import numpy as np,pandas as pd
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-proteogenomics-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-root-20261024');V=A/'proteogenomics-repair-v2';C=V/'code';R=Path('/home/biostar/work/projects/openlabs/openlabs-data/maintenance/biomed-new-five-4h-20261024/reviews/proteogenomics')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
verify=json.loads((V/'VERIFICATION_V2.json').read_text());assert verify['all_checks_passed']
primary=json.loads((V/'primary/results.json').read_text());sens=json.loads((V/'sensitivity/results.json').read_text());seg=json.loads((V/'segment-external/results.json').read_text());comp=json.loads((V/'complex/results.json').read_text());d=pd.read_csv(V/'primary/pair_effects.csv');x=d[~d.same_chr].copy()
for n in ['CORRECTION_REGISTRATION_V2.json','VERIFICATION_V2.json']:shutil.copy2(V/n,P/n)
scale='''# 来源特定CNA尺度及2022–2026近邻（v2）

| 来源 | 已核对原始说明 | 本研究可用解释 |
|---|---|---|
| LUAD CPTAC2020 | 固定cBioPortal README的CNA段：CNVEX adjusted log2-transformed gene-level coverage ratios；离散阈值为(-∞,−1)→−2、[−1,−0.1)→−1、[−0.1,0.1]→0、(0.1,1]→1、(1,∞)→2 | 来源阈值派生类别，不是已校正纯度/倍性的绝对一拷贝变化 |
| UCEC CPTAC2020 | 固定README的CNA段：WGS gene-level ratio，Table S2 F-gene-CNV；相同数值阈值派生类别 | README用ratio描述，不能因为相同阈值就推断与LUAD同一物理剂量或擅自补写未证实的变换 |
| BRCA CPTAC2020 | 固定README：continuous data由原表推得，discrete calls由作者应请求提供 | 使用原作者类别；没有在本研究证明其阈值与LUAD/UCEC相同，不统一称GISTIC |
| CCLE2019 gene CNA | 本次文件原始类别及重复组全排除后的类别都只有−2、0、+2 | 九候选无预定−1/+1，原路线不可估计，不是生物阴性；原始平均重复组可能制造±1的bug已修复 |
| CCLE hg19 SEG | 同一文件的区间连续分数，GRCh37基因跨度加权，覆盖门槛90% | 连续关联斜率和±0.1描述组为另外的探索估计量；不是绝对拷贝或上游外显子加权重现 |

来源精确路径：旧索引中的A/cbio_public_luad_cptac_2020_README.md、A/cbio_public_ucec_cptac_2020_README.md及A/proteogenomics/brca_cptac_2020-README-md/README.md；A为本项目new5-root-20261024私有artifact根。本次不改动这些历史源文件。

## 直接核对的近邻

- Schukken与Sheltzer，2022，*Extensive protein dosage compensation in aneuploid human cancers*，DOI [10.1101/gr.276378.121](https://doi.org/10.1101/gr.276378.121)，PMC9341510。Crossref身份与EuropePMC完整原文一致。该文已分析染色体gain/loss的RNA及蛋白响应，发现广泛剂量缓冲与复合物成员富集。本项目不能把gain/loss或复合物缓冲作为首次发现。本次明确补列此原论文，不把未完整核实的10.1016/j.mcpro.2022.100384当作它的替代，也不篡改旧文献记录。
- Venkatesh等，2025，*Proteomic compensation by paralogs preserves protein interaction networks after gene loss in cancer*，DOI [10.1038/s44320-025-00122-4](https://doi.org/10.1038/s44320-025-00122-4)，PMC12322171。已研究trans-paralog loss、RNA残差、跨染色体和相互作用，有HAP1敲除证据；其更大CPTAC面板包含本项目队列。本项目不同在按癌种同时估计partner的gain/loss类别关联，并未要求先证实own-loss降低自身蛋白；这些是估计目标/资格规则差别，尚未形成稳定新结论。
- Heller等，2026，*Protein buffering of aneuploidy is driven by coordinated factors identified through machine learning*，DOI [10.1038/s44320-026-00187-9](https://doi.org/10.1038/s44320-026-00187-9)，PMC13046899。主要是自身cis剂量/蛋白缓冲比，已有gain/loss、复合物、多个数据库和工程细胞证据。它与本项目partner-trans条件关联不完全相同；本项目也不能广称首次gain/loss不对称或以通用稳态解释代替证据。

查询记录：Crossref /works/{DOI}、EuropePMC DOI精确检索及/fullTextXML，三篇均200响应，完整原始JSON/XML及URL/时间/SHA见私有v2/literature/LOOKUP_MANIFEST.json并绑定新索引。本次只补正必要近邻，不声称穷尽文献或以未检出证明首创。
'''
(P/'SOURCE_SCALE_AND_LITERATURE_V2.md').write_text(scale)
table='\n'.join('| '+r['study']+' | '+str(r['n_directional_pairs'])+' | '+str(r['loss_q05_n'])+' | '+str(r['gain_q05_n'])+' | '+str(r['asymmetry_q05_n'])+' |' for r in primary['summary'] if not r['same_chr'])
report=f'''# 旁系同源蛋白与CNA关联：独立审查修订v2

更新时间{now}。计算修复完成，科学状态仍为needs_replan，paper_candidate=false，Q2目标未达到。本版替代旧报告受影响文字和数值；旧200文件、旧索引、原结果和独立审查全部保留，不静默覆盖。v2是已曝光数据上的bug修复/复算，不是新的独立验证或预注册确认。

## 离散CNA重复symbol的真实缺陷及修复

原matrix/load/mat对所有矩阵按symbol取均值，可能将离散CNA的−2与0等合成−1/+1，或制造0.5。v2所有相关加载器调用同一保守函数：仅对data_cna.txt，凡symbol有多行，**整组全部排除**，不看类别取值、蛋白、RNA或结果。LUAD排除20组43行，UCEC86组176行，BRCA6组12行，CCLE数量见VERIFICATION_V2。RNA、蛋白和连续CNA仍按symbol算术均值，属于延续原定连续聚合，可能掩盖异构体/共享肽差异；不赋予稳定ID消歧或绝对剂量意义。

代码及ANALYSIS_REGISTRATION等历史计划复制到私有proteogenomics-repair-v2/code，补充CORRECTION_REGISTRATION_V2后执行。analyze.py产生的QUALIFICATION/samples/pair_universe只写该私有clone，未触碰旧小型项目。primary、sensitivity、原生CCLE资格、SEG及complex五阶段全部重跑；complex明确读取v2 primary，而不是旧结果。

## 主分析复算及九候选

患者样本109/95/122，共326，样本与基因对身份宇宙不变；这些是不重叠来源患者ID，不是新招募或基因型去重。v2主跨染色体结果：

| 队列 | 有向对 | loss q<.05 | gain q<.05 | 类别对比系数和q<.05 |
|---|---:|---:|---:|---:|
{table}

BRCA合格跨染色体对5940→5938，同染色体981；LUAD4943、UCEC56不变。全部主模型12719→12717，删除DST←MACF1与MYO18B←MYO18A，具体见REMOVED_PRIMARY_MODELS_V2.csv。审查提到3条是触及重复symbol的更宽统计；MACF1为target、DST为partner的反向模型保留，因为此处仅使用MACF1的连续自身CNA/RNA/蛋白和唯一的DST离散暴露，未使用被排除的MACF1离散调用。主发现数保持24/2/5、0/9/0、1/0/0，不能把此修复夸大成推翻整个pilot。LUAD→BRCA共同对2826→2825，loss/gain Spearman更新为0.107150/0.093556；UCEC仅13共同对，不能作充分阴性泛化。所有存活模型的非置换主系数、SE及p与原结果误差为0；BH按修正检验族重新计算，独立BH最大误差1.20e−13。敏感性模型33076→33070，存活系数/p误差为0。删除模型会改变之后置换/家族bootstrap的RNG消耗，完整复算这些固定诊断，不选择有利输出。

原LUAD九个gain候选的身份、效应及q保持不变，未重新筛选候选。原loss短名单仍无合格候选。gain外部分支在看过肿瘤结果后登记；即使九候选固定，也不能把此前已见的肿瘤结果重新称前瞻确认。BRCA只有四个候选满足相同支持门槛，两个同向，均无名义gain p<.05；其他缺资格者不是零效应。

## 外部资格失败及完整反例

CCLE重复组全排除后，原始类别仍只有−2/0/+2。八个目标蛋白可用候选仍无预定浅类别，原生验证不可估计，不是生物学阴性；另一个CPXM1蛋白缺失。SEG是新的连续代理估计量，同时改变暴露、自身CNA和病例覆盖。八连续主要模型8/8同向但九假说BH无人通过.05；KIF3A–KIF3B q=0.05301不能四舍五入算通过。分类SEG只有4/8同向，批次连续6/7同向，RAB1A翻转，SESN1批次不满秩；SESN1主模型仅52条线/22参数，不能与约368线模型等精度看待。v2逐项核实SEG结果数值不变，未隐藏反例或把相关方向算独立成功。

interact探索也读取修正primary重新计算。BRCA/LUAD/UCEC三个gain均值差为0.000318/−0.011173/0.033909，家族区间均跨零；BRCA loss未调整均值差0.019957，家族区间[0.000762,0.039636]为局部阳性，但调整后系数−0.016963、p=0.073855，反例并列保留，不能用于救gain假设。没有扩展新队列或新注释追逐显著性。全部精确新结果见私有v2/complex/results.json及新索引。

## 尺度、文献与推断边界

LUAD为CNVEX调整后log2覆盖比的阈值派生类别；UCEC原README称WGS gene ratio，并给同样数值阈值；BRCA为原作者提供的离散类别。不能将三者统一称GISTIC或−1/+1“一份拷贝变化”。βloss+βgain检验类别对比系数和，不是可识别的剂量曲线机制不对称。SEG跨度均值不是绝对拷贝或上游外显子加权调用。逐来源阈值、精确固定README及文献原文证据见SOURCE_SCALE_AND_LITERATURE_V2.md。

新增核对Schukken/Sheltzer2022 Genome Research DOI10.1101/gr.276378.121，连同2025 trans-paralog、2026 cis-buffering原始全文，说明gain/loss与复合物缓冲早有研究。本项目估计目标有差别，但当前弱重复和无机制证据尚不构成实质新增结论，不声称首次、SOTA优越或因果补偿。

HC3/纯度/连续阈值敏感性全部保留；不能挑发现数最多的规格。RNA调整不识别转录后因果效应，仍有测量误差、纯度、谱系、WGD/性别、共享肽及共同CNA混杂。每队列/染色体层/endpoint内的BH不提供全部分支联合FDR保证。家族bootstrap只条件于已拟合患者系数，不传播患者层估计误差；第一轮审查的九个所选患者bootstrap也不消除发现筛选偏差，不是新独立确认。行政细胞ID不能证明供者完全独立。

## 验证与当前处置

独立于修正分析的核验脚本从原始CNA表检查每个重复组及整组排除计数，确认没有新增离散值，核对所有存活主系数、独立BH、九候选、CCLE资格和SEG输出。旧200文件哈希全部保持。运行全程CPU guard，主计算串行，2CPU/4GiB内层scope、BLAS1，无GPU/依赖安装。新文献网络查验为低CPU补充；未声称从空环境安装。

本轮未新增独立生物材料、机制实验或可投稿论文。保留可审计探索，下一步先界定不同于近邻的新命题，并取得未曝光、剂量和身份可解释且匹配RNA/蛋白的独立扰动证据；没有此材料就维持停止/重设计。需要新的空白独立复核；计算检查不是科研或投稿批准。未修改现有五稿、数据库、期刊、Git提交或发布。

当前入口CURRENT_RESEARCH_STATE.json；修正注册CORRECTION_REGISTRATION_V2.json；逐项回应RESPONSE_TO_REVIEW_V2.md；新证据REVIEW_INPUT_INDEX_V2.json；旧输入及旧审查作为历史一并hash绑定。
'''
(P/'REPORT_zh_V2.md').write_text(report)
response='''# 独立审查回应v2

接受审查的真实处理缺陷和解释边界；不调整假设、筛选门槛或模型。

1. **离散重复symbol**：修正所有matrix/load/mat，统一cna_loader_v2.py，data_cna.txt整组排除。连续变量均值聚合保留并披露局限。五阶段串行重跑，私有clone避免analyze.py写回旧项目；整组计数与原始值集合由独立脚本复核。BRCA主模型减少2条（DST←MACF1、MYO18B←MYO18A），发现数不变。审稿所述3条是target或partner触及重复symbol的宽口径；反向MACF1←DST保留，因为使用MACF1连续协变量而不使用其离散调用、DST暴露唯一。另有原本不合格重复基因不进入模型，不能将排除行数当受影响模型数。
2. **原生CCLE与SEG**：资格仍失败、不是生物阴性；SEG独立探索估计量。原九候选完全不变，原生支持及SEG数值与旧输出核对，保留4/8分类、6/7批次与不满秩反例。没有重选短名单或更换holdout。
3. **来源尺度**：SOURCE_SCALE_AND_LITERATURE_V2.md逐来源给README和阈值，BRCA仅称作者类别，UCEC严格按ratio原描述；不统一GISTIC、绝对拷贝或浅一拷贝。敏感性的common threshold只是数值阈值规格，不证明剂量可比。
4. **选择/不确定性/因果**：新版报告明确gain/SEG/interact分支曝光顺序，family区间不替代患者误差；所选候选患者bootstrap不克服选择偏差。BH只限各规定检验族；RNA调整/跨染色体不识别因果。complex改读v2 primary并完整复算，局部BRCA loss阳性及调整后反例均保留。
5. **近邻与2022引用**：Crossref+EuropePMC精确DOI检索并获取2022/2025/2026原始全文，原始JSON/XML和请求manifest入新索引。明确2025是trans-paralog最近邻、2026主要cis-buffering，gain/loss及complex已有前作；估计量差别未产生稳定新贡献。10.1016/j.mcpro.2022.100384历史记录保留未核实，不替换为2022论文身份。

旧REPORT/QUALIFICATION/pilot_results/VERIFICATION/REPLAY/research_state/project均保持历史。新REPORT_zh_V2、research_state_v2/project_v2、pilot_results_v2及CURRENT_RESEARCH_STATE为当前入口。旧plan与四分支注册不是外部预注册证明，不篡改；CORRECTION_REGISTRATION_V2只登记曝光数据修复。旧200文件逐一hash验证，旧REVIEW_INPUT_INDEX不改。新clone/generated输出及旧完整证据都由新索引绑定。scientific needs_replan、paper_candidate=false、Q2false不变；等待空白复核，不自评通过。
'''
(P/'RESPONSE_TO_REVIEW_V2.md').write_text(response)
pilot=json.loads((P/'pilot_results.json').read_text());pilot['revision']=2;pilot['metrics'].update(cross_chromosome_directional_effects=len(x),LUAD_BRCA_common_pairs=2825,LUAD_BRCA_loss_spearman=.10715029231920904,LUAD_BRCA_gain_spearman=.09355631891877945)
for b,loss,gain in [('unadjusted_group_effect','raw_loss','raw_gain'),('rna_and_own_cna_adjusted_effect','adjusted_loss_beta','adjusted_gain_beta'),('within_study_permuted_partner_cna','permuted_loss_beta','permuted_gain_beta')]:pilot['baselines'][b]={'median_abs_loss':float(x[loss].abs().median()),'median_abs_gain':float(x[gain].abs().median())}
pilot['limitations'] += ['Discrete CNA duplicate symbols fully excluded; continuous aggregates retained. Source categories are not equal absolute copy-number steps.','Post-review correction on exposed data; no new confirmation or biological mechanism.'];pilot['run'].update(command=json.loads((V/'EXECUTION.json').read_text())[0]['argv'],code_revision='working-tree-code-sha256:'+sha(C/'analyze.py'));dump(P/'pilot_results_v2.json',pilot)
state=json.loads((P/'research_state.json').read_text());state.update(status='needs_replan',revision=2,paper_candidate=False,results={'path':'pilot_results_v2.json','sha256':sha(P/'pilot_results_v2.json')},current_report='REPORT_zh_V2.md',scientific_assessment={'status':'needs_replan','q2_target_reached':False,'independent_peer_review':'initial review completed; v2 fresh review pending','scope':'Exposed-data correction, not new confirmation or paper admission.'});state['evidence'] += [{'path':n,'sha256':sha(P/n)} for n in ['VERIFICATION_V2.json','CORRECTION_REGISTRATION_V2.json','SOURCE_SCALE_AND_LITERATURE_V2.md']];dump(P/'research_state_v2.json',state)
project=json.loads((P/'project.json').read_text());project['revision']=2;project['workstreams'][0]['state_path']='research_state_v2.json';project['workstreams'][0]['objective']='Review post-review discrete-CNA correction; scientific needs_replan; no new selection on exposed data.';dump(P/'project_v2.json',project)
dump(P/'CURRENT_RESEARCH_STATE.json',{'revision':2,'recorded_at':now,'project':'project_v2.json','state':'research_state_v2.json','report':'REPORT_zh_V2.md','review_index':'REVIEW_INPUT_INDEX_V2.json','scientific_status':'needs_replan','q2_target_reached':False,'paper_candidate':False,'prior_versions_preserved':True,'independent_v2_review':'pending'})
# Snapshot orchestration and verification scripts outside frozen original project.
for name in ['proteogenomics_repair_v2.py','proteogenomics_verify_v2.py','proteogenomics_literature_v2.py','proteogenomics_seal_v2.py','proteogenomics_replay_v2.py','run-guarded']:shutil.copy2(Path(__file__).parent/name,C/name)
commands='''# v2代码、实际命令及安全重放

私有执行根：/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-root-20261024/proteogenomics-repair-v2

实际五阶段argv/exit_code见该根EXECUTION.json，逐阶段stdout/stderr为*.py.log。修复规则先登记CORRECTION_REGISTRATION_V2，然后串行执行。所有解释器通过run-guarded：聚合CPU护栏及内层CPUQuota200%、MemoryMax4GiB、MemoryHigh3GiB、swap0，BLAS/OMP/MKL各1；无GPU。旁路文献查验只访问三篇官方书目API及全文，结果在literature中。

重放必须使用新的空私有目录；不得直接运行旧项目analyze.py，也不要调用固定原执行根的proteogenomics_repair_v2.py或seal脚本：

```bash
C=/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-root-20261024/proteogenomics-repair-v2/code
PY=/home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python
"$C/run-guarded" "$PY" "$C/proteogenomics_replay_v2.py" --output-root /ABS/NEW/PRIVATE/EMPTY/ROOT
```

该程序复制修正源码及冻结资格计划到新根/code，重建全部输出，complex只读取该新根primary。不会写原项目或原输出、下载网络数据、改模型或重选候选。

轻量独立算术/旧200完整性复核，指定审稿人自己的新输出路径：

```bash
"$C/run-guarded" "$PY" "$C/proteogenomics_verify_v2.py" --output /ABS/NEW/PRIVATE/verification.json
```

脚本不导入修正分析模块，从原始离散表统计重复组及值集合，比较全部存活主系数/独立BH/冻结九候选/native资格/SEG，原始路径均由新索引绑定。第一轮审查旧全模型独立重构仍作为历史证据；本轮未冒称另一次全模型独立拟合。
'''
(P/'CODE_AND_COMMANDS_V2.md').write_text(commands)
old=json.loads((P/'REVIEW_INPUT_INDEX.json').read_text());files={f['path']:f for f in old['files']}
for f in files.values():assert sha(Path(f['path']))==f['sha256'],f['path']
extras=[P/'REVIEW_INPUT_INDEX.json']+[P/n for n in ['REPORT_zh_V2.md','RESPONSE_TO_REVIEW_V2.md','SOURCE_SCALE_AND_LITERATURE_V2.md','CORRECTION_REGISTRATION_V2.json','VERIFICATION_V2.json','pilot_results_v2.json','research_state_v2.json','project_v2.json','CURRENT_RESEARCH_STATE.json','CODE_AND_COMMANDS_V2.md']]+[f for f in V.rglob('*') if f.is_file() and '__pycache__' not in f.parts]+[R/'REVIEW_zh.md',R/'ASSESSMENT.json',R/'COMMANDS.md']
for f in extras:files[str(f)]={'path':str(f),'sha256':sha(f),'bytes':f.stat().st_size}
index={'revision':2,'frozen_at':now,'project_id':'biomed-new5-proteogenomics-20261024','scope':'Duplicate-symbol discrete CNA correction on exposed data; prior frozen200 evidence retained. All five phases recomputed privately; no new confirmatory experiment.','read_first':[str(P/n) for n in ['CURRENT_RESEARCH_STATE.json','REPORT_zh_V2.md','RESPONSE_TO_REVIEW_V2.md','VERIFICATION_V2.json']],'prior_index_sha256':sha(P/'REVIEW_INPUT_INDEX.json'),'creator_scientific_approval':False,'paper_candidate':False,'files':list(files.values()),'replay':'See CODE_AND_COMMANDS_V2.md; never execute analyze.py from canonical old project. Private clone only.'};dump(P/'REVIEW_INPUT_INDEX_V2.json',index);print(json.dumps({'files':len(files),'index_sha256':sha(P/'REVIEW_INPUT_INDEX_V2.json'),'old_files_preserved':len(old['files'])},indent=2))
