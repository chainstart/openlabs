# TP-005：有限 N SU(3) 的非平凡小 Wilson-loop 严格界

- 状态：`candidate`
- 开放性证据：A
- 最近审计：2026-08-26
- 首轮资源：H（从 L/M 级小基开始，硬上限 30 GiB）
- 基线：[arXiv:2502.14421](https://arxiv.org/abs/2502.14421)、[arXiv:2404.16925](https://arxiv.org/abs/2404.16925)

## 精确问题

现有有限 N lattice bootstrap 已对 SU(3) plaquette 给出严格界，并展示反射正性等增强。能否对一个预先固定的 6-link rectangle/chair 或 8-link rectangle，给出严格且明显窄于强耦合、弱耦合和平凡 positivity 包络的期望值区间？

维数、loop 形状和耦合扫描区间必须在运行前冻结；不得看到结果后换成容易的 loop。

## 首个成果的验收条件

- 至少在三个耦合点生成 primal/dual 可行证据；
- 对目标 loop 的区间宽度相对基线包络缩小至少 20%，或证明所用约束在该截断下不能改进并给出 dual obstruction；
- 2D 情形与已知可解/高精度结果核对，随后才进入 3D；
- 报告所有群积分、loop equations、Mandelstam 关系和 reflection-positivity conventions。

## 第一阶段

1. 复现 SU(3) plaquette 的一个公开表格或图中点。
2. 建立 loop canonicalization：平移、转动、反向、回溯消去与 trace identities。
3. 以长度分层生成 loop basis，并逐层记录约束数、块大小和内存。
4. 比较 Hermitian positivity、site/link reflection positivity 和 twist-reflection positivity 的边际收益。
5. 用小规模高精度解产生 dual certificate，再决定是否进入 H 级运行。

## 关键反证与停止条件

- loop canonicalization 必须通过随机闭合路径和群恒等式测试；发现重复/漏项时所有数值界作废。
- 若预计下一层峰值超过 30 GiB，先做对称分块或 column generation，不得直接扩大。
- 与 Monte Carlo 的比较只作 sanity check；严格性来自 SDP 与证书，而非统计吻合。

## 预期产物

- loop/约束生成器；
- 小 Wilson-loop 严格区间数据集；
- 可独立运行的 dual-certificate verifier；
- 约束族的收益与内存 scaling 报告。
