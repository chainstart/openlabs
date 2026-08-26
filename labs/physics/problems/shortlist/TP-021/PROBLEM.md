# TP-021：d>2 无质量粒子的 dual S-matrix bootstrap 原型

- 状态：`candidate`
- 开放性证据：B
- 最近审计：2026-08-26
- 首轮资源：M
- 基线：[arXiv:2203.02421](https://arxiv.org/abs/2203.02421)

## 精确问题

能否在 d>2 为一个固定、尽可能简单的无质量散射问题构造同时包含 crossing、解析性和可控 IR 处理的 primal/dual 优化，并在有限基下数值验证强对偶？

首选模型是具有单一内部对称通道、树级 EFT 答案已知的标量或受保护 helicity sector。若无质量极限本身不可控，应把“哪条假设导致不可闭合”作为结果，而不是隐藏 IR regulator。

## 首个成果的验收条件

1. 明确 observable、IR prescription、subtractions 和解析域。
2. 写出有限维 primal 与 dual，并证明 weak duality。
3. 对至少一个已知 EFT benchmark，primal/dual gap 随基大小下降。
4. 给出排除点的可复核 dual functional，或给出强对偶失败的明确机制。

## 第一阶段

1. 从 massive toy model 复现一个 dual bound。
2. 引入质量/维数 regulator，逐项跟踪 soft/collinear singularities。
3. 比较 partial waves、energy correlators 或 celestial variables 中哪一组最少引入不可观测假设。
4. 只在解析定义稳定后实现 SDP/LP 基。
5. 对 regulator removal 做顺序极限和 basis-size 消融。

## 关键反证与停止条件

- 如果目标量不是 IR safe，不能把有限 regulator 下的界解释为物理界。
- 数值 primal/dual 接近不能代替 weak-duality 推导。
- 如果最近文献已有同一 helicity/observable 的 dual 构造，应换到其未覆盖的约束，而非重复。

## 预期产物

- 一份约束和解析域的形式说明；
- primal/dual 实现及 benchmark；
- regulator 与 basis 收敛报告；
- 对偶 functional 或 obstruction certificate。
