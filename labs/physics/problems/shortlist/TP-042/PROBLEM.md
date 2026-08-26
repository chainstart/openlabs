# TP-042：n≥5 宇宙学图的 cluster alphabet 与唯一性

- 状态：`candidate`
- 开放性证据：A
- 最近审计：2026-08-26
- 首轮资源：M
- 基线：[arXiv:2603.08670](https://arxiv.org/abs/2603.08670)

## 精确问题

近期工作在 de Sitter cubic scalar 的 chain/loop 图中发现 A/B 型 cluster alphabets 和 adjacency，并在低点展示 symbol 可由物理条件唯一固定。这个结构是否延续到首个 n=5 chain 或 loop？若不延续，额外自由度来自新字母、adjacency 松弛还是物理约束不足？

2026-08-26 的首轮审计发现，后续文献已经给出 all-`n` chain 结构，因此历史提问中
“cluster 结构是否延续”的宽泛部分不再开放。当前可判决问题收窄为：在冻结 conventions
下，原始 bootstrap 条件是否唯一固定 `P5` symbol；loop 分支必须另立范围，不能与 chain
合并判决。

## 首个成果的验收条件

1. 独立复现至少一个 n≤4 结果及其 symbol-space 维数。
2. 生成 n=5 图的候选 alphabet、cluster embedding 与允许 adjacency。
3. 依次施加 integrability、图对称、奇点、flat-space limit 和 factorization/cutting，记录每步维数。
4. 最终得到唯一 symbol，或给出剩余空间的显式基/最小反例。
5. 对直接积分可达的切片做数值或级数核对。

以上是**首轮完成条件**；低点复现、字母数或可行性估计本身不证明 `P5` 唯一性。

## 开放问题解决判据（hard gate）

对当前 `P5 chain` 范围，以下任一路线全部满足才算解决：

- `solved_positive`：冻结 44-letter alphabet、first-entry 和 adjacency；构造完整 exact
  integrability/物理约束矩阵；给出可复核 rank/nullspace 证书证明解空间一维（扣除整体
  归一化）；所得 symbol 满足 factorization/flat-space/soft 条件，并在可直接积分切片核对。
- `solved_negative`：使用同一完整 exact 矩阵给出至少二维 nullspace 证书；展示一个非零
  剩余方向满足全部冻结条件且不是 conventions/gauge/归一化冗余；由独立检查器复核。

all-`n` alphabet 文献、`n=2` 复现和 `n=5` 搜索空间计数只更新问题边界，仍保持当前
`problem_verdict: open`。

## 第一阶段

1. 把论文中的字母和 seed 变换编码为精确有理/符号对象。
2. 自动生成 chain 与 loop 的 dihedral orbits，先做重复字母消除。
3. 在有限域上求 integrability 和 adjacency 线性系统，再做有理重建。
4. 保留每一类约束加入前后的 kernel dimension，防止把唯一性误归因。
5. 若 n=5 过大，先固定 parity/对称 sector，但明确这只是部分结果。

## 关键反证与停止条件

- “求解器只找到一个解”不等于唯一；必须给矩阵秩或精确 nullspace 证书。
- cluster 识别须区分坐标变换下的等价字母，避免虚假新增。
- flat-space limit 和 boundary contact terms 的 conventions 必须与基线一致。

## 预期产物

- n≤4 复现测试；
- n=5 alphabet/adjacency 数据；
- 逐约束维数表与 exact nullspace；
- 唯一 symbol 或非唯一性的显式反例。
