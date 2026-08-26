# TP-035：生成函数 IBP 化简的完整性与失败证书

- 状态：`candidate`
- 开放性证据：A
- 最近审计：2026-08-26
- 首轮资源：M
- 基线：[arXiv:2605.09541](https://arxiv.org/abs/2605.09541)

## 精确问题

近期生成函数方法能高效地产生 Feynman-integral symbolic reductions。对一个未在基线样例中覆盖、但传统 Laporta 仍可完成的两圈多尺度 family，能否证明生成函数化简所得 master basis 完整，或在算法无法闭合时输出可解释的失败证书？

## 首个成果的验收条件

- family、sector ordering、允许的维数移位和 numerator degree 在运行前固定；
- 生成函数与独立 Laporta/有限域流程得到相同 master count；
- 随机有限域点上至少完成两种独立 reduction 路径的恒等核对；
- 提出并验证一个完整性充分条件，或输出遗漏 sector/秩亏的具体 certificate；
- 公布时间、内存、表达式大小和失败率，而不只报告最快案例。

## 第一阶段

1. 复现基线论文的最小例子，锁定正规化和排序约定。
2. 选择“略超出论文、但可由现成 Laporta 工具交叉验证”的 family。
3. 在多个素数上计算关系矩阵秩、syzygies 和 master count。
4. 对生成函数的特殊化点做奇异性审计，避免 accidental rank drop。
5. 尝试把终止/覆盖条件写成 sector graph 上的可判定条件。

## 关键反证与停止条件

- 单个随机有限域点的一致不构成完整性证明。
- 若两个程序共享同一 IBP 生成器或排序实现，不算真正独立复核。
- 若 family 超过资源上限，必须缩小 numerator degree，而不是删除失败日志。

## 预期产物

- 固定积分族和双实现 benchmark；
- master-count 与 reduction 一致性证书；
- 完整性充分条件、失败分类或明确反例；
- 可复现实验脚本与资源统计。
