# 两项并行公开数据研究：2026-10-21

用户授权：筛选并行开展两项纯计算生物医学研究，争取一天内取得具有中科院大类二区投稿潜力的结果。
时间窗：2026-10-21 08:10 至 2026-10-22 08:10（Asia/Hong_Kong）。这是研究时间预算，不是录用或正结果承诺。

本次用户明确指定二区，覆盖根目录 AGENTS.md 较早的四区选刊偏好，仅限本次两项研究。
如进入具体选刊，仍须核验 **2025 年中科院升级版大类分区**、团队拒稿记录和官方免强制作者费路线。
本次不授权投稿、付费或公开发布。科研结果成立之后才创建论文记录和稿件。

## 研究边界

- 两项研究独立立项，使用公开、可追溯数据；不做湿实验或临床工作。
- 先检索最近工作和验证文件可获取性，再确定科学问题。常规套模型和已发表方法的简单重复不算成果。
- 保存带时间戳的预先分析方案、输入与环境哈希、全部试验和失败。模型选择只用开发集。
- 确认性测试仅在方案冻结后执行；重用测试结果后的扩展一律标记为探索，不能重新包装成确认。
- 研究独立单位为分子/实验测定或基因/细胞系/研究来源；不能以重复测量数夸大有效样本量。
- 主分析有匹配预算的简单强基线、最近方法、适当的分组不确定性和失败条件。
- 到期交付可复现结果、来源与局限和继续/停止判断。无效或无新颖性的结果如实记录，不强行生成论文。

## 执行与资源

当前会话明确授权并行代理工作。化学研究、计算生物研究各有独立工作目录，第三位代理独立审查设计。
所有运行时、数据下载处理、训练和检查均经 `bin/openlabs-resource-guard --task-type cpu --`。
优先每项 2 个 CPU 线程、约 1.5 GiB 工作内存；依主机实际可用内存调整并发，CPU 研究不占 GPU。
若确有 CUDA 工作，必须另外取得 GPU 预约，不能以 CPU 标签执行。

## 当前进展与目录

首轮实验与替代选题见 [检查点](CHECKPOINT.md)，检索来源见 [检索记录](SEARCH_LOG.md)。
化学测定迁移候选已停止，CRISPR 和药物剂量支持的首轮计算已完成。
已实证启动两个有截止时间的后台研究进程，用新目录和合适的独立数据继续筛选/验证，见
[后台任务和当前状态查询](BACKGROUND.md)。尚未取得两项已达到二区发表标准的成果。

| 项目 | 代码 | 小型元数据 | 数据及结果 |
| --- | --- | --- | --- |
| 化学迁移候选 | `studies/chem_shift_20261021/` | `openlabs-data/workspaces/biology/projects/biomed-chem-shift-20261021/` | `openlabs-artifacts/artifact-stage/biomed/chem-shift-20261021/` |
| 生物跨实验室候选 | `studies/bio_shift_20261021/` | `openlabs-data/workspaces/biology/projects/biomed-bio-shift-20261021/` | `openlabs-artifacts/artifact-stage/biomed/bio-shift-20261021/` |
| 药物剂量支持替代研究 | `studies/drug_support_20261021/` | `openlabs-data/workspaces/biology/projects/biomed-drug-support-20261021/` | `openlabs-artifacts/artifact-stage/biomed/drug-support-20261021/` |
| 独立设计审查 | `studies/day1_review_20261021/` | — | — |

相对代码路径以 `labs/biomed/` 为根；数据和产物仓库为代码仓库的同级目录。
已有 `biomed-chem-generalization-pilot` 保留原始暂停状态，不用基础设施 smoke 测试充当研究结果。

## 初筛排除记录

通用“骨架外活性预测＋不确定性校准”与已有工作高度重合，不能作为本次贡献：
[Scaffold-shift uncertainty calibration…](https://doi.org/10.1016/j.compbiolchem.2026.109371)。
仅增加少量新 assay 数据校准也不能直接声称新颖，需区别于
[Machine Learning Strategies When Transitioning between Biological Assays](https://doi.org/10.1021/acs.jcim.1c00293)。
完整检索、最终问题及运行状态由各项目记录承载；此文件不宣称两项已取得可发表成果。
