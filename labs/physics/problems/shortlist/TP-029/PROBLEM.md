# TP-029：两圈六点 MHV 的 137-letter alphabet 为何普适？

- 状态：`candidate`
- 开放性证据：A
- 最近审计：2026-08-26
- 首轮资源：M
- 基线：[arXiv:2510.20565](https://arxiv.org/abs/2510.20565)、[arXiv:2602.02783](https://arxiv.org/abs/2602.02783)、[arXiv:2606.27801](https://arxiv.org/abs/2606.27801)

## 精确问题

2025–2026 年的结果表明，两圈六胶子质量为零 MHV 最大权重部分只使用候选 167 个字母中的 137 个。能否从 Landau singularities、leading singularities、cluster adjacency、first/last-entry 和离散对称性推出这 137 个字母；或者构造一个满足同等已知物理约束却必须使用额外字母的合法 symbol？

目标不是重新计算已经完成的全部 MHV sector，而是解释 137 的选择机制或证明现有原则不足。

## 首个成果的验收条件

以下任一结果成立：

- 给出一组清晰、可算法检查的必要条件，其允许字母恰为 137 个；
- 证明某个被怀疑的几何原则排除恰好缺失的 30 个字母；
- 构造 integrable、满足指定 entry/adjacency/对称约束的反例 symbol，展示这些条件不足。

必须提供独立代码重建字母集合、关系矩阵与反例/证明检查。

这只是**本轮任务完成判据**。重建 `167/137/30` 集合和分类表属于必要基线，不等于解释了
137 的物理选择机制。

## 开放问题解决判据（hard gate）

以下任一路线全部满足即可作客观解决判决：

- `solved_positive`：精确重建候选与实现集合；从明确写出的 Landau/leading-singularity/
  entry/adjacency/对称原则推导一组必要且充分的规则；该规则在规范化后恰选 137 个并排除
  恰好 30 个；证明和独立实现均通过。
- `solved_negative`：构造一个非零、integrable 的 exact symbol；它满足冻结的全部 entry、
  adjacency、对称和物理约束却必用缺失字母；用有理算术或多素数证书及独立检查证明反例。

分类器分隔、orbit 清单或“尚未找到规则”均保持 `problem_verdict: open`。

## 第一阶段

1. 从论文补充材料重建 167 候选与 137 实现集合，逐字母校验 conventions。
2. 为 30 个缺失字母计算 orbit、Landau loci、leading-singularity 支撑和相邻关系特征。
3. 训练分类器只作模式发现；最终规则必须转成精确代数/组合陈述。
4. 解有限域上的 symbol integrability 线性系统，测试逐组加入约束后的维数。
5. 对最小反例做有理重建和多素数检查。

## 关键反证与停止条件

- 数据驱动分隔 137/30 不是物理解释，除非规则可从振幅原则推出。
- 不得把最大权重 MHV 的经验规律未经证明推广到 NMHV 或低权重。
- 若 conventions 造成字母表表面差异，先统一乘法独立性和代数关系。

## 预期产物

- 规范化 alphabet 数据集；
- 约束消融与 symbol-space 维数表；
- 137 选择定理的候选证明，或最小反例；
- 可复核的有限域/有理算术代码。
