# 选题检索与决策记录

日期：2026-10-21。此为针对最近工作的有限检索，不是系统综述，也不能证明题目没有前人做过。

使用 `nature-academic-search` 的多源检索流程。当前工具清单未提供 PubMed/CrossRef/arXiv 专用 MCP；
先以网络检索访问出版社、PubMed/PMC 和作者仓库的一手记录，再用技能提供的 OpenAlex 脚本补充发现。
不使用检索结果数量、引用数或模型判断替代创新性核查。

## 原始发现记录

在资源护栏内运行 `/home/biostar/.codex/skills/nature-academic-search/scripts/academic_search.py`：

| 查询 | 参数 | 原始输出 |
| --- | --- | --- |
| cross assay calibration anchor selection bioactivity | `--limit 10 --year-from 2021` | `openlabs-artifacts/artifact-stage/biomed/campaign-20261021-literature/assay-openalex.json` |
| CRISPR screen reproducibility context specific prediction | 同上 | `openlabs-artifacts/artifact-stage/biomed/campaign-20261021-literature/crispr-openalex.json` |

两次脚本均退出 0，stderr 为空。结果含大量词汇相关但科学问题无关的文章，不能整体计为支持文献。
OpenAlex 元数据仅用于发现；最终文献事实以一手页面核实。同 DOI 的预印本/期刊记录不算独立研究。

## 决策所依据的近邻

| 主题 | 一手来源 | 对本次研究的约束 |
| --- | --- | --- |
| 骨架偏移下活性预测校准 | [2026 多靶点 benchmark](https://doi.org/10.1016/j.compbiolchem.2026.109371) | 排除通用 scaffold/conformal 对比作为新贡献 |
| 新旧测定迁移 | [2021 JCIM](https://doi.org/10.1021/acs.jcim.1c00293) | 少量新测定标签校准本身已建立 |
| 跨测定噪声 | [2024 JCIM](https://doi.org/10.1021/acs.jcim.4c00049)、[作者数据仓库](https://github.com/rinikerlab/overlapping_assays) | 重复噪声估计不新；衍生数据要保留 ChEMBL 上游许可和测定语义 |
| 配对活性差异 | [2025 Journal of Cheminformatics](https://doi.org/10.1186/s13321-025-00956-y) | 配对差异抵消测定差异不是可独占的新结论 |
| 少样本选样偏差 | [CRA 2024 预印本](https://arxiv.org/abs/2410.20711) | 广义选样偏差已有方法；该文 anchor 指表征聚类中心，与本次配对测定翻译有别 |
| 测定语义标注 | [ChEMBL 团队 2026 工作](https://pubmed.ncbi.nlm.nih.gov/41680846/) | 发现 assay_type 粗糙或添加文本分类器不足以单独声称创新 |
| 两实验室 CRISPR 一致性 | [2019 原始分析](https://pmc.ncbi.nlm.nih.gov/articles/PMC6925302/) | 总体一致性和跨实验室比较已建立，不能重复作为贡献 |
| 稀疏 CRISPR 信号可重复性 | [2023 Cell Systems](https://pmc.ncbi.nlm.nih.gov/articles/PMC10266068/) | 不能用全局相关性代替特定背景依赖的可靠性；风险过滤必须保留有信息的信号 |
| 扰动预测与评价目标 | [2026 预印本](https://arxiv.org/abs/2610.18880) | 已讨论全体误差可靠性与重要基因子集可靠性的区别；本次不能声称首次发现这种区别 |
| 剂量范围和药物预测评价 | [2025 specification game](https://doi.org/10.1186/s13321-025-00972-y) | MAXCONC 捷径与固定药物评价已有直接前例，剂量基线不可遗漏 |
| 跨数据集药物敏感性整合 | [2016 原始工作](https://pmc.ncbi.nlm.nih.gov/articles/PMC5239501/) | 共同剂量范围及调整 AUC 已研究，不能把改用 AUC 或浓度截断当成新贡献 |
| 近期 IC50 深度学习评价 | [2026 Communications Chemistry](https://doi.org/10.1038/s42004-026-01916-9) | 已讨论超出最大实验浓度的拟合值；本次聚焦更窄的操作性排序支持问题 |

## 尚未完成的证明义务

化学问题需要真正可比而非只在数据库同为 B/IC50 的测定、独立文献来源、足够的共同分子，
以及覆盖源活性范围的强简单选样基线。已知 source 活性时的推理是同分子测定翻译，不能写成全新分子的结构预测。

CRISPR 问题需要两轴分组的目标标签留出、训练范围内的尺度标定、与效应强度/基因方差基线比较，
并单独报告有信息依赖子集。两个实验室只支持这一实验室组合内的结论，不能外推未见实验室。

候选问题只有在这些边界成立、实际结果有实质贡献后才进入论文准备。完整稿件或具体选刊尚未启动。
