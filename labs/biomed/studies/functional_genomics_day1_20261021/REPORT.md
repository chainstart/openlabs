# 功能基因组学一天研究结果包

结论：当前论文推进 **no-go**，`paper_candidate=false`。达到预登记的条件迁移试点阈值；这只支持所测报告系统中的条件预测增量。 尚不足以支持2025中科院升级版大类二区论文的成果判断；没有选刊、投稿、付费或公开发布。

筛查3个实质不同方向，停止蛋白活性/丰度解耦（2026近邻直接覆盖、独立蛋白面板不足）与酵母表达—适合度环境迁移（原研究已直接回答核心问题、仅一个启动子）；完成最强可接入方向的小规模研究。审计见 `candidate-screen.json`、`literature-audit.json`、`SEARCH_LOG.md`，未改写旧CRISPR负结果，也未打开其剩余4个细胞。检索使用官方原文、Europe PMC和公开API；专业文献MCP不可用，不能声称穷尽。

问题：控制来源总体活性、测量精度和共同正义链偏好后，HepG2的启动子个体正义减反义方向差能否经K562训练，迁移至未用WTC11及未用位点？数据为Agarwal等2025原始双方向大库 ENCSR022GQD/ENCSR382BVV/ENCSR244FWB 的当前released处理文件；官方实验release日期前两者为2021-09-01，后者为2023-12-21，三次培养重复/细胞。单方向joint库只作格式核查，全部排除。精确accession、release、官方MD5、SHA-256、原研究与使用条款在 `data-lock.json` 和13份 intake manifest 中。下载链接没有被当作独立实验。

身份冻结：3,578个共同200nt常染色体启动子位点；chr1–16训练2454、chr17–18验证368、chr19–22确认756。固定每方向每重复至少10条码及有限数值后，实际训练 **1982**、验证 **297**、确认 **454**。没有跨集合染色体/1Mb区块/位点重叠。独立单位是基因组DNA位点，不能把这些数量当作独立细胞、供体或研究数。三细胞来自同一研究，WTC11仅一个新背景。

8个预登记策略，种子20261021；仅K562验证集选择，之后未重拟合。另有两个固定残差诊断回归，不参与选择，其中目标回归与activity_ridge相同；全部配置低于12上限。模型选择为无个体方向特征基线 **activity_ridge**，方向策略 **full_ridge**。确认集仅评估一次，有开始/完成锁。

| 固定策略 | K562验证MSE | WTC11确认MSE（描述性） |
|---|---:|---:|
| zero | 0.229837 | 0.604857 |
| median | 0.230800 | 0.601471 |
| activity_ridge | 0.229232 | 0.598020 |
| activity_hgb | 0.234075 | 0.594308 |
| identity_delta | 0.210958 | 0.569705 |
| delta_ridge | 0.145271 | 0.508970 |
| full_ridge | 0.142636 | 0.507260 |
| full_hgb | 0.143621 | 0.503979 |

唯一主比较：MSE由 **0.598020** 至 **0.507260**，改善 **0.090760 log2²**，相对下降 **15.18%**。2000次1Mb配对区块bootstrap的95%区间 **[0.048718, 0.129311]**；同时整体重采样三次目标培养的敏感性区间 **[0.044044, 0.136944]**，126个确认区块。区间条件于固定来源测量、训练策略、四条染色体、单个WTC11背景和该研究；不是跨细胞/实验室总体区间。主阈值预定为相对下降≥10%且区块区间下限>0。

完整试验账本：`complete-trial-ledger.json`；逐位点预测、区块重采样、模型和来源特征在 artifact staging。培养重复相关性、各染色体误差、来源活性分层及预定来源可靠子集都在 `results.json`，仅作诊断，未据其挑选显著亚群。活动校正残差相关为 **0.392**，不是机制证据。

最近工作差异与局限：Roberts2021（10.1101/gr.270751.120）已发现跨细胞链偏差，并明确指出启动子类报告中总体活性与不对称程度相关；Agarwal2025（10.1038/s41586-024-08430-9）已有方向和跨细胞启动子相关性。Bose2025预印本（10.1101/2025.10.13.659964）还直接考察了启动子、载体位置与链方向。本轮仅量化控制活动与平均偏好后的个体对比迁移，没有新算法或新机制结论；官方公开全文审计见 `nearest-fulltext-audit.json`。2026 QUASARR-seq（10.1038/s41467-026-68780-y）的内源/双功能结论不能由此推出。共同载体、片段选择和处理流程可共同保留测量偏差，精确序列身份来自坐标及原研究设计而非重新测序，固定QC也限制推广。不同位点仍可能同源；染色体隔离不保证序列同源家族隔离。位点区间不能替代独立实验室、载体和多个新细胞背景的验证。即使本试点达到数值阈值，也仅值得在更独立的数据中复核。

数据锁 SHA-256：`e54b452274038859f1a755fff12fd36982701bad1c90421e9f2ebbe9287af604`  
代码锁 SHA-256：`1024a681bca6695383895176ec8d6bbb60225b6bfa3b6eee09e2f856361e68af`  
依赖uv锁 SHA-256：`587a1c0fd727c600bbb0e05ee390de7fbc9ef2db6662f06a3274ded2d7965399`  
冻结方案 SHA-256：`4517311bafc248c9e674bd73e21c9938519ae0419c92ec8842d6a0d1db8977c5`。实际Python及全部已安装版本在 `environment.json`；数据和每个代码文件的完整哈希均在对应锁/索引中。

原始执行顺序（每条均在2线程CPU guard下；详见代码README）：`probe.py` → `audit_sources.py` → `intake.py` / `prepare_metadata.py` → `screening.py` → `freeze.py` → `download_replicates.py` 与不透明确认下载 → `software_check.py` → `run.py select` → `run.py confirm` → `finalize.py`。

可复现数值回放（原始确认目录拒绝再次打开；回放不构成新验证）：

```bash
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 FG_PROJECT_ROOT=/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-functional-genomics-day1-20261021/replay FG_ARTIFACT_ROOT=/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-functional-genomics-20261021/replay labs/biomed/.venv/bin/python labs/biomed/studies/functional_genomics_day1_20261021/reproduce.py
```

资源：2 CPU、MemoryHigh1536/Max2048MiB、TasksMax96，HTTP≤2，无GPU或新依赖；payload共 146.42 MiB（含排除的格式核查文件），staging共 170.91 MiB。运行未触碰其他研究、全局factory/timer或SQLite。计算完成不等于论文或投稿就绪；后续只能经独立科学审查决定是否值得继续。
