"""Assemble truthful final records from retained results; no new fitting/evaluation."""
from common import *
import subprocess

def main():
    r=json.loads((ART/'confirmation-results.json').read_text());a=json.loads((ART/'ancestry-review.json').read_text())
    ledger=json.loads((DATA/'all-trials-ledger.json').read_text())
    for fn,typ in [('dependence-sensitivity.json','post_confirmation_plate_pool_sensitivity'),('ancestry-review.json','post_confirmation_donor_parent_sensitivity'),('descriptive-strata.json','predeclared_descriptive_strata')]:
        obj=json.loads((ART/fn).read_text())
        if not any(t['type']==typ for t in ledger['current_campaign']['trials']):ledger['current_campaign']['trials'].append({'at':obj['at'],'type':typ,'new_models':False,'configuration_count_unchanged':12,'primary_unchanged':True,'evidence':str(ART/fn)})
    write(DATA/'all-trials-ledger.json',ledger)
    rows=[]
    labels=['原始差值／identity','拟合差值','训练药物＋细胞均值','源重复一致率','标准化差值','NRFE曲线级适配','差值保序回归','全特征Ridge','仅差值HGB','全特征HGB（主方法）','仅剂量HGB']
    for label,(name,v) in zip(labels,r['all_baselines'].items()):
        lo,hi=v['two_way_ci95'];rows.append(f"| {label} (`{name}`) | {100*v['error_at_50pct']:.3f} | [{100*lo:.3f}, {100*hi:.3f}] | {100*v['error_at_25pct']:.3f} | {100*v['error_at_75pct']:.3f} |")
    table='\n'.join(rows)
    report=f'''# drug_support：源侧可靠性对跨筛选排序的迁移检验

本轮已完成新问题评估、方案冻结、真实数据实验及复核，科学裁定为**预登记外部筛选检验未支持实质增益**；`paper_candidate=false`。这不是已达到2025中科院升级版大类二区论文标准的声明，也没有开展选刊、投稿或公开发布。

在50%固定比较覆盖率下，源侧全特征模型将错误率从36.124%降至35.996%，改善 **0.128个百分点**，药物结构×细胞模型双向bootstrap 95%区间 **[−0.449, 0.871]个百分点**。预先定义的最小实际相关改善为2个百分点。当前条件区间上限低于该阈值，但区间包含零不能解释为等价，也不能排除其他设计或其他筛选上的收益。

## 科学问题、候选与先验

用途是在已有源筛选剂量反应测量时，决定哪些同药物内的细胞敏感性排序值得转移到另一个筛选。可证伪问题：从PRISM技术重做开发证据学习的源重复精度、曲线质量、饱和度与剂量设计，能否在未用于本轮模型选择的CTRPv2响应中，比“保留响应差值最大的比较”带来至少2个百分点错误率下降？本轮研究的是同身份跨筛选迁移，不是未知药物、未知细胞或临床结局预测。

三个实质候选均有裁定，见[候选账本]({DATA}/candidate-ledger.json)。C1执行上述检验；C2（剂量截断与排名保存）与Chen 2026已公开分析过近，未进入结果实验；C3的新PRISM MTS021–026只有三个控制药物，且同研究计划，不能提供广泛药物层面的独立证据。没有通过更换主终点继续寻找正结果。

旧PRISM确认及GDSC测试全部视为已暴露开发证据。旧GDSC原始目录在本机不存在，只核验旧报告，未声称复验其原始实验。历史12配置及本轮12配置分别保留，不能把旧预算重置视为重新确认的授权。

## 最近工作与真实差异

[完整原始文献与来源审计]({DATA}/LITERATURE_AND_SOURCE_AUDIT.md)保留本轮检索响应和读取证据。共同支持范围积分已有[2016 adjusted AUC](https://doi.org/10.18632/oncotarget.10010)基础；[2025 specification game](https://doi.org/10.1186/s13321-025-00972-y)、[2026 potency benchmark](https://doi.org/10.1038/s42004-026-01916-9)和[DrEval](https://doi.org/10.1038/s41467-026-72903-w)已覆盖强基线与跨筛选评估，不能据此宣称新方法。[Chen 2026](https://doi.org/10.1093/bioinformatics/btag382)已研究截断、积分和敏感细胞重合；[intraclass generalization](https://doi.org/10.1371/journal.pcbi.1013232)限制了药物盲测的解释。

最直接的[plateQC 2025](https://doi.org/10.1016/j.isci.2025.113470)已有质量与重复偏差关联；本轮窄差异是目标响应不可见时仅用源侧信息、固定保留率、预测先封存。[iDRR/DRS 2026](https://doi.org/10.64898/2026.04.29.721574)为预印本，已研究多筛选可靠性；本轮没有使用其包含目标响应的共识特征。NRFE对照只采用发表公式的曲线级3PL适配，不是完整4PL板级plateQC复现，不能声称击败该完整方法。检索未命中不作为首创证据。

## 数据、身份及独立性

CTRP来自作者[Zenodo17981848](https://doi.org/10.5281/zenodo.17981848)的`20251212_CTRP_replicates_logdose.csv`，823,603,861字节，官方MD5匹配，CC BY 4.0；12,470,175测量行、532药物名、847细胞名。这是CTRPv2上游实验的作者重整理，重新整理不增加实验独立性。PRISM源来自只读复用的[Broad Figshare9393293 v4](https://doi.org/10.6084/m9.figshare.9393293.v4)原始MFI及归一化数据；未重新下载已有完整payload。

药物采用完整立体canonical SMILES精确匹配，并独立核验InChIKey；不合并盐、互变异构体或立体异构体。57个结构匹配经源重复完整性等门槛后剩50个结构。细胞由唯一官方CCLE标准化名称链接至PRISM的DepMap ModelID及STR通过记录；CTRP作者表缺少原始master_ccl_id，故这是重建的名称→官方ID链，不是重新对CTRP做STR鉴定。50个结构、444个模型形成15,675个源合格配对，目标剂量门槛排除1对，最终15,674个药物–模型配对，产生2,600,017个有依赖的细胞两两比较。

复核[官方DepMap 22Q2 sample_info](https://api.figshare.com/v2/articles/19700056)后，444模型对应**439个patient_id／供体亲缘连通组**，没有缺失patient_id，5组各含两个模型；结合全表parent_depmap_id连通关系，仍为439组。元数据MD5与官方匹配，许可CC BY 4.0。它们不是439个临床患者验证样本。源侧共有26个化合物板和20个细胞池。PRISM与CTRP是不同上游筛选／读出，但均来自Broad；不能称独立实验室。目标重复编号缺原始plate/experiment ID，故没有把它们当生物重复。

已知训练重叠：外部50结构中39进入训练、8进入验证、3不在旧完整案例开发集合；444模型中336在训练，108不在训练；2,792个精确结构–模型对在训练中。训练/验证均来自历史已暴露PRISM技术重做，9292/987条开发曲线；外部CTRP响应未用于拟合或选择。相关细节见[暴露账本]({DATA}/exposure-ledger.json)。读取旧归一化容器时其中也有旧目标列，不宣称旧目标字节从未读取。

## 冻结设计与公平比较

冻结前按50药物、药物间差异标准差0.03/0.05/0.10估计，正态95%区间半宽约0.832/1.386/2.772个百分点，80%功效最小可检测差异约1.188/1.980/3.960个百分点；这是假设情景精度评估，没有把测量行数当样本量。方案在目标效应打开前冻结，SHA256为`43269824650306c76e32b2c6d3911c11ac2fa6411477361ca8c40f73cd13676a`。共同log10剂量支持区间由元数据确定，区间边缘收缩2×10⁻⁶、宽度至少1.2；源至少两个完整技术重复；目标在区间内至少四个剂量点并满足覆盖；每药至少20模型。目标先在实际剂量内取重复中位数，再将响应截到[0,1]进行分段线性积分。没有按结果、R²或拟合成败筛选主样本。

源侧统一有界3PL最多300次函数评价，旧拟合仅在原数组完全一致时复用。3,075个复用、12,600个新拟合，其中1,188个失败保留在主分析，拟合对照回退原始积分；NRFE缺失排在最差端，学习模型只用训练中位数填充。旧开发集是完整拟合案例、部署集保留失败，存在明确的资格分布迁移。

本轮12配置＝11预测／选择器＋1曲线处理，种子20261021；全部配置见[完整试验账本]({DATA}/all-trials-ledger.json)。主模型预先固定为全特征HGB；验证选择的Ridge仅为次要比较。三个HGB同为200迭代、15叶、min_samples_leaf=50、L2=5、learning_rate=.05，不早停，同训练配对、药物平衡权重和种子。每药最多2000训练配对，共193,284对。差值保序回归、Ridge及HGB的填补／缩放均训练内确定。

主终点为同药物内保留50%比较后的排名错误率，药物等权；方向相同记0、不同记1、平局记0.5。正的“改善”＝原始差值错误率−模型错误率。25%/75%覆盖是预登记次要终点；全部比较也是描述结果。identity包含在原始差值对照内；正斜率affine不改变本任务排名，故没有把等价变换冒充额外模型。均值对照由训练药物／细胞边际效应构成。剂量设计在同一药物内固定，故仅剂量HGB在同药物内分数相同，按冻结哈希打破并列；它是信息消融对照，不是能区分同药物内细胞的强对照。主比较和强基线判断依赖原始差值、差值HGB及保序回归。

## 全基线及不确定性

下表单位均为百分比，低者更好。50%覆盖区间为1000次结构×全局模型ID交叉bootstrap；同一细胞出现在不同药物中时共享抽样权重。比较对不是独立样本。模型及选择集合固定，因此区间条件于开发样本、已拟合模型和当前面板，不覆盖重新训练／模型选择不确定性。

| 方法 | 50%覆盖错误率 | 95%区间 | 25%覆盖错误率 | 75%覆盖错误率 |
|---|---:|---:|---:|---:|
{table}

主方法对同容量仅差值HGB改善0.144个百分点，95%区间[−0.442,0.838]；对差值保序回归改善0.127个百分点，[−0.447,0.844]。没有证实强简单基线之上的收益。所有预登记学习模型相对原始差值的点估计范围为−5.244至0.128个百分点；该范围是配置敏感性描述，不是重新训练不确定性区间。对较弱NRFE适配对照的明显优势不能挽救主比较，也不是对完整plateQC的优势结论。

![主比较]({ART}/primary-benefit.png)

未截断目标响应的预登记敏感性：改善0.219个百分点，区间[−0.365,0.916]。逐一留出源板的点估计范围0.073–0.206个百分点。确认后新增的依赖审计不替换主分析：源板×源池区间[−0.575,0.885]个百分点；结构×供体亲缘组区间[{100*a['chemical_by_ancestry_benefit_ci95'][0]:.3f},{100*a['chemical_by_ancestry_benefit_ci95'][1]:.3f}]个百分点。两种审计都仍缺CTRP原始板依赖，不能解释为解决了所有聚类问题。

预登记校准分析显示，全HGB在所有比较上预测平均错误风险37.036%，实际41.384%，低估4.348个百分点，条件95%区间[2.807,5.954]。全模型期望二元Brier为0.239111，差值保序回归0.238652，改善−0.000459，区间[−0.002176,0.001211]；没有可靠的校准优势。平局的0.5标签MSE与期望二元Brier分别保存，未混称。没有在CTRP上重新校准；这只是一个筛选上的迁移失准，不能推成普遍机制。

预登记分层描述已保留在`descriptive-strata-summary.csv`及逐药表：训练中出现的39结构上，原始差值／全模型错误率为35.782%／35.607%；其余11结构为37.335%／37.372%。两细胞均在训练中为36.933%／36.675%，均不在训练中为33.267%／33.409%。这些分层保持全局冻结选择，层内覆盖率并非统一50%，方法间层内组成可不同，只作描述，不能称作新药或新细胞盲测证据。组织及源池完整描述也保留，未选择显著子群。

## 错误、暴露与复核

确认只打开一次。第一次评估在首个药物的pandas索引断言处失败：目标表已载入，但尚未输出目标值或计算效应。原脚本及日志保留，仅将有歧义的`.loc`改为显式`xs/reindex`，经检查后继续同一冻结评估；模型、分数、选择、种子及终点均未改变。见`evaluation-indexing-failure.json`、`evaluation-indexing-repair.json`及两次日志。没有把错误续跑伪装为新盲测。

本代理使用独立实现复算，不是第三方独立审稿：①从原始MFI按板重算归一化，456,243个有限值完全一致，缺失掩码一致；②逐行读取全部CTRP测量，独立中位数和线段积分复算15,674个目标及15,675个源积分，最大误差约6.7×10⁻¹⁶；③另一种排序实现核对1,650组覆盖选择，复核前50次bootstrap权重／统计量及百分位；④核验50完整结构键、444唯一细胞链接、训练内填补与同容量预算；⑤再次验证439供体亲缘组和源板／池依赖。图中数值经结果文件生成并查看。

证据协议仅部分适用：标准biomed-public-data-pilot未直接表示同身份跨筛选配对、条件性双向bootstrap等设计；`protocol-compatibility.json`明确记录不声明通用协议通过，以冻结计划及定制审计补足。没有写入工厂SQLite或修改共享配置。

## 可复现记录、资源与交付

代码在[{CODE.name}]({CODE})；执行说明见[README]({CODE}/README.md)。数据与状态在[专属项目]({DATA})，原始payload、模型与预测在本artifact目录。解释器`{ROOT}/openlabs/labs/biomed/.venv/bin/python`，环境锁SHA256 `587a1c0fd727c600bbb0e05ee390de7fbc9ef2db6662f06a3274ded2d7965399`，版本见`environment.json`。完整文件哈希见`scientific-manifest.json`；执行命令索引见`execution-ledger.json`。冻结模型文件SHA256 `{r['run']['model_sha256']}`；CTRP文件SHA256 `a9772410cfaacfca897347a95e57beea35731b28d58004a28dca9b53062e003c`。

所有运行时经CPU guard，核验处于本路线service及openlabs-workers.slice，CPUQuota200%、软4GiB／硬5GiB、Swap512MiB、Tasks96，数值线程至多2；未用GPU、未安装新依赖、未派生代理、未接管第三路或旧后台任务。终末核查实际累计下载841,881,942字节（约842 MB），当前scratch约1.14 GB，内存峰值1,725,153,280字节（约1.73 GB）。详细下载、scratch及关闭时资源读数见`final-audit.json`。旧冻结方案、旧报告和复用payload的终末哈希核对也在该文件。排除动态agent／supervisor日志及自身哈希清单，避免把持续变化的日志包装为科学冻结产物。

本campaign从2026-10-21 13:51:45 UTC至19:51:45 UTC，绝对deadline未延长。复核自14:29:43 UTC开始，结束时间见`research_status.json`；完成至少30分钟复核与报告后提前结案，不空转耗满六小时。

## 停止判断与下一步

可部署的源侧质量特征在这一面板上未提供预定的实质排序收益，技术重做的校准也未可靠迁移。现有证据不足以把该条件性负结果提升为二区论文候选：只有50结构、一个外部筛选，来自同机构，目标原板ID缺失，完整已发表质量控制方法尚未公平复现，开发完整案例偏差也未被新实验排除。

若另获授权，下一步应取得带原始板／批次标识、不同实验室的原始剂量重复，并在重新冻结方案后验证源风险校准；先解决独立性与缺失拟合的开发代表性，再讨论扩展模型。当前CTRP已经暴露，今后只作开发或复算，不能再次标成独立确认。不继续在本确认集调阈值或选择有利子群。
'''
    for base in (ART,DATA):(base/'FINAL_REPORT.md').write_text(report)
    out={**r,'stage':'completed','original_evaluation_stage':r['stage'],'status':'completed','scientific_disposition':'negative_registered_external_test','paper_candidate':False,'ancestry_audit':a,'confirmation_is_new_upstream_screen':True,'independent_lab_validation':False,'clinical_validation':False,'review_is_third_party':False,'post_confirmation_dependency_sensitivity':json.loads((ART/'dependence-sensitivity.json').read_text()),'calibration':json.loads((ART/'calibration-results.json').read_text()),'descriptive_strata':json.loads((ART/'descriptive-strata.json').read_text()),'report_path':str(ART/'FINAL_REPORT.md'),'trial_ledger':str(DATA/'all-trials-ledger.json')}
    for base in (ART,DATA):write(base/'RESULTS.json',out)
    print('Report and RESULTS assembled; final audit/status still pending.')
if __name__=='__main__':main()
