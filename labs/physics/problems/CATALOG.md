# 物理开放问题目录（50 题，以理论与计算研究为主）

最后快速检索：**2026-08-26**。这里的 A/B/C 是“开放性证据等级”，不是难度。所有题目在正式开题前仍需做一次专题查重；尤其 C 级条目应先被当成选题假设。

## A. 非微扰量子场论与 bootstrap

| ID | 候选开放问题 | 首个可闭环目标 | C/V | 资源 | 证据 |
|---|---|---|---:|---|---|
| **TP-001** | 超对称单矩阵量子力学 bootstrap 中随截断移动的伪 kink 能否被系统消除？ | 重现实有下界；比较矩、对偶和精度截断，给出 kink 的收敛/消失判据，并输出可验证对偶证书。 | 5/4 | M | A · [S01](SOURCES.md#s01) |
| **TP-002** | BFSS 基态低阶关联函数能否得到更高 word length 的严格区间？ | 在固定对称扇区把 word length 从现有基线推进一档，报告上下界、收敛曲线与高精度证书。 | 5/5 | H | A · [S02](SOURCES.md#s02) |
| **TP-003** | 热矩阵量子力学的长弦激发能和相互作用能否由 bootstrap 分离？ | 在一个固定两矩阵模型中加入最小的新热矩约束，判断第一激发态区间是否闭合。 | 4/4 | H | A · [S03](SOURCES.md#s03) |
| **TP-004** | 有限 N 与大 N 矩阵 bootstrap 的界如何定量衔接？ | 对同一势能在 3–5 个 N 上求同一观测量的认证区间，拟合并检验首个 `1/N²` 标度律。 | 5/4 | M | C · [S04](SOURCES.md#s04) |
| **TP-005** | 有限 N、SU(3) lattice bootstrap 能否从 plaquette 推进到非平凡小 Wilson loop？ | 为一个指定 6–8-link loop 给出比强/弱耦合平凡包络更窄的严格界。 | 4/5 | H | A · [S05](SOURCES.md#s05) |
| **TP-006** | 能否直接得到 Creutz ratio 或 string tension 的严格有限 N 界？ | 在 SU(2) 或 SU(3) 的固定二维/三维设置中，联合四个 loop 构造第一个非平凡 Creutz-ratio 区间。 | 4/5 | H | B · [S05](SOURCES.md#s05) |
| **TP-007** | Wilson-loop bootstrap 能否约束最轻 glueball 谱？ | 构造带时间分离的最小相关矩阵，验证反射正性是否给出优于变分平凡界的谱隙约束。 | 3/5 | H | C · [S06](SOURCES.md#s06) |
| **TP-008** | 三维 lattice Ising 临界关联函数能否得到系统收敛的严格区间？ | 在小格点/有限算符基上复现已知初步界，并新增一个距离或算符类型的认证区间。 | 4/4 | M | B · [S07](SOURCES.md#s07) |
| **TP-009** | 三维或四维 gauge–fermion 理论 conformal window 的候选固定点能否被排除/孤立？ | 固定一个群和费米子数，用混合关联函数建立可复现的排除图，而非一次解决整个 conformal window。 | 3/5 | H | B · [S08](SOURCES.md#s08) |
| **TP-010** | 数值 conformal-bootstrap 边界背后的解析 functional 能否被重建？ | 选一个低维截断端点，从数值 dual 解猜出闭式/递推 functional，并在更高精度验证零点结构。 | 5/4 | M | B · [S08](SOURCES.md#s08) |
| **TP-011** | 能否为 conformal bootstrap 设计低内存、带后验误差界的 functional 基？ | 在同一 benchmark 上将峰值内存减半，同时保持排除结论并给出舍入误差证书。 | 5/4 | M | B · [S08](SOURCES.md#s08) |
| **TP-012** | CFT island 的 subleading spectrum 是否随 crossing/gap 假设稳定收敛？ | 对一个已有 island 做受控假设消融，输出次领维数的稳健区间或显式不稳定性反例。 | 4/4 | H | B · [S08](SOURCES.md#s08) |

## B. Hamiltonian 方法、量子多体与符号问题

| ID | 候选开放问题 | 首个可闭环目标 | C/V | 资源 | 证据 |
|---|---|---|---:|---|---|
| **TP-013** | d>2 CFT 三点函数的通用动量空间 Fourier 核能否整理成 Hamiltonian truncation 可直接调用的形式？ | 对一类自旋配置给出含接触项、支撑和解析延拓的公式，并与数值 Fourier 积分交叉验证。 | 5/4 | L | B · [S09](SOURCES.md#s09) |
| **TP-014** | 2+1 维 Yukawa 等模型的 Hamiltonian-truncation counterterm 能否系统化？ | 对固定截断方案推导首个缺失 counterterm，并验证两个低能本征值的 cutoff 漂移阶数改善。 | 5/4 | M | B · [S09](SOURCES.md#s09) |
| **TP-015** | 如何从 Hamiltonian truncation 数据稳定提取散射振幅？ | 在一个有已知精确/微扰答案的 1+1 维模型中实现有限体积到 LSZ 振幅的误差受控流程。 | 4/4 | M | B · [S09](SOURCES.md#s09) |
| **TP-016** | 三维 O(2) 模型的实时输运能否由截断谱可靠得到？ | 先在可解 benchmark 上验证谱函数重建，再给出一个频率窗内的 conductivity 区间。 | 3/5 | H | B · [S09](SOURCES.md#s09) |
| **TP-017** | coarse-grained bootstrap 能否扩展到真正二维的量子格点系统？ | 在二维横场 Ising 小型局域块上给出热力学极限能量密度上下界，并证明随块大小单调。 | 4/4 | M | A · [S10](SOURCES.md#s10) |
| **TP-018** | 非可积自旋链的热力学极限谱隙能否获得更强严格界？ | 选一个已有弱界的 frustration-free/近 frustration-free 链，增加局域约束并认证改进量。 | 4/4 | M | B · [S11](SOURCES.md#s11) |
| **TP-019** | 仅凭谱相关量能否重建连续、projective 或 non-invertible 隐对称？ | 构造有/无目标对称的成对数据集，给出可辨识条件或不可辨识反例，并扩展现有离散群算法。 | 4/4 | M | A · [S12](SOURCES.md#s12) |
| **TP-020** | 哪些局域基变换把量子 Monte Carlo 的指数符号问题降为代数级？ | 对一个参数化哈密顿量族，枚举有限深度局域变换，证明一个充分条件或找到反例边界。 | 4/5 | M | B · [S13](SOURCES.md#s13) |

## C. S-matrix 与 EFT 一致性

| ID | 候选开放问题 | 首个可闭环目标 | C/V | 资源 | 证据 |
|---|---|---|---:|---|---|
| **TP-021** | d>2 无质量粒子的 dual S-matrix bootstrap 能否形成可计算原型？ | 固定粒子种类和 helicity，写出 primal/dual 有限基并在树级 EFT benchmark 上验证强对偶。 | 4/5 | M | B · [S14](SOURCES.md#s14) |
| **TP-022** | 含自旋 massive 粒子的 S-matrix bootstrap 能否同时实施解析性、幺正性和 crossing？ | 对 2+1 或 3+1 维单一自旋种类构造最小 partial-wave SDP，输出首个耦合界。 | 4/5 | H | B · [S14](SOURCES.md#s14) |
| **TP-023** | 2+1 维 relativistic anyon 的 S-matrix bootstrap 如何系统建立？ | 固定统计角和单一弹性道，推导 crossing/analytic continuation 并复现两个可解极限。 | 4/5 | M | B · [S14](SOURCES.md#s14) |
| **TP-024** | 非弹性道的加入会怎样改变低能 S-matrix bootstrap 界？ | 用一个可控双通道模型比较纯弹性与首个非弹性阈值下的允许区，量化界的位移。 | 4/4 | M | B · [S14](SOURCES.md#s14) |
| **TP-025** | 四维质量为零理论是否存在适合 bootstrap 的 IR-safe 可观测量？ | 对一个能流/天球相关量证明有限性、crossing 和 positivity 的最小闭合约束集。 | 3/5 | M | B · [S14](SOURCES.md#s14) |
| **TP-026** | D=5–11 maximal supergravity 的高阶曲率 Wilson 系数能否由 bootstrap 收紧？ | 固定维数和一个次领系数，纳入已知低能/高能信息后给出可复现数值界。 | 4/5 | H | B · [S14](SOURCES.md#s14) |
| **TP-027** | 含圈修正的多场 EFT positivity region 能否自动构造并认证？ | 对两标量、固定维数-8 基底，完成 IR 减除、basis reduction 和凸锥的机器证书。 | 5/4 | M | A · [S15](SOURCES.md#s15) |
| **TP-028** | 含 graviton loops 时，EFT positivity 的可允许负性边界是什么？ | 在一个固定引力-标量 EFT 中实现 crossing-symmetric dispersion，分离 scheme/IR 依赖并给出数值区间。 | 4/5 | M | A · [S15](SOURCES.md#s15) |

## D. 散射振幅、Feynman 积分与 double copy

| ID | 候选开放问题 | 首个可闭环目标 | C/V | 资源 | 证据 |
|---|---|---|---:|---|---|
| **TP-029** | 两圈六点质量为零 MHV 振幅出现的 137-letter symbol alphabet 是否普适，为什么？ | 独立枚举 Landau/前导奇点候选；证明必要条件，或找到满足物理约束但需要第 138 个字母的反例。 | 5/5 | M | A · [S16](SOURCES.md#s16) |
| **TP-030** | 两圈六胶子 NMHV 最大 transcendental weight 部分能否由 bootstrap 确定？ | 固定一个 helicity 分量，以已知字母表和 factorization/collinear 数据解出 symbol 或严格缩小 ansatz。 | 5/5 | H | A · [S16](SOURCES.md#s16) |
| **TP-031** | 六点 QCD 振幅低权重部分的代数 prefactor 如何分类？ | 对一个 helicity sector 建立无冗余 prefactor 基，证明完备性并匹配一组 cuts。 | 5/4 | M | A · [S16](SOURCES.md#s16) |
| **TP-032** | 如何把六点 QCD 的 symbol 提升到满足分支和实区域条件的函数？ | 对一个已知最大权重 symbol 构造单值/物理分支函数表示，并做高精度数值点检查。 | 5/4 | M | A · [S16](SOURCES.md#s16) |
| **TP-033** | 仅用 Landau 分析能否预测完整六点 alphabet 及 adjacency？ | 对一个已算振幅盲预测字母与相邻规则，再与结果对照，记录漏报/误报的结构性原因。 | 5/4 | M | A · [S16](SOURCES.md#s16) |
| **TP-034** | 非平面或任意多重度 QCD 的 leading-singularity 基是否有统一组合描述？ | 在一个七点一圈或六点两圈非平面 sector 中枚举并化简 leading singularities，输出可验证基。 | 5/5 | M | A · [S16](SOURCES.md#s16) |
| **TP-035** | 生成函数 IBP 化简能否附带完整性、终止性或失败证书？ | 选一个未在基线论文处理的两圈 family，与 Laporta 基准比较 master 数、时间和遗漏，并形式化充分条件。 | 5/4 | M | A · [S17](SOURCES.md#s17) |
| **TP-036** | 含多个 elliptic sectors 的两圈积分几何能否算法分类？ | 对一个具体 multi-scale family 求 maximal cuts、Picard–Fuchs 算子和曲线同构类，判断是否需 hyperelliptic 数据。 | 5/5 | M | C · [S18](SOURCES.md#s18) |
| **TP-037** | 含物质振幅在圈级是否存在局域 color–kinematics dual numerators？ | 固定一个两圈四点理论/粒子内容，求解 Jacobi、unitarity cuts 与幂次计数，给出解或 obstruction certificate。 | 4/5 | H | B · [S19](SOURCES.md#s19) |
| **TP-038** | kinematic algebra 能否在 off-shell 或有限截断下显式闭合？ | 在自对偶/简化模型中计算低阶生成元与 Jacobiator，找出可消去它的最小同伦修正或证明障碍。 | 4/5 | M | B · [S19](SOURCES.md#s19) |

## E. 引力、宇宙学、弦论与超共形理论

| ID | 候选开放问题 | 首个可闭环目标 | C/V | 资源 | 证据 |
|---|---|---|---:|---|---|
| **TP-039** | 振幅方法能否补齐一个带 spin/finite-size 的下一阶 post-Minkowskian 波形系数？ | 先审计最新阶数，锁定一个尚缺 operator coefficient，完成 cuts-to-observable 推导并与 PN 极限核对。 | 4/5 | H | B · [S20](SOURCES.md#s20) |
| **TP-040** | radiation reaction、tail 与 BMS frame 在 amplitude/MPM 描述中如何一致匹配？ | 对一个已知辐射过程逐项比较 soft、memory 与 tail，定位并消除首个 convention-independent mismatch。 | 4/5 | M | B · [S20](SOURCES.md#s20) |
| **TP-041** | self-force、PM 与 EOB 在小质量比重叠区的高阶不变量是否一致？ | 选一个 scattering angle 或 redshift invariant，把两套公开表达式展开到共同阶并完成符号/数值等价检查。 | 5/4 | L | C · [S20](SOURCES.md#s20) |
| **TP-042** | 宇宙学 chain/loop 图的 cluster alphabet 与唯一性是否延续到 n≥5？ | 生成首个 n=5 实例；用奇点、adjacency、flat-space limit 和对称性尝试唯一固定 symbol，或给出反例维数。 | 5/4 | M | A · [S21](SOURCES.md#s21) |
| **TP-043** | cluster adjacency 能否扩展到一般宇宙学图、非 cubic 相互作用或 spinning exchange？ | 选一个最小非 chain/loop 图，计算字母表并检验 A/B 型 cluster 嵌入和禁邻规则。 | 5/5 | M | A · [S21](SOURCES.md#s21) |
| **TP-044** | loop-level cosmological correlator 的 cutting/unitarity 约束能否唯一固定一个具体 integrand/symbol？ | 在固定 de Sitter 标量一圈图上联合 cuts、奇点与 flat-space limit，比较直接积分。 | 4/5 | M | B · [S22](SOURCES.md#s22) |
| **TP-045** | nonperturbative de Sitter bootstrap 能否在 dS2/dS3 给出新的四点 positivity 界？ | 扩展一个已知 dS2 例子到额外质量/通道，构造有限 SDP 并报告收敛或不可行原因。 | 3/5 | H | B · [S22](SOURCES.md#s22) |
| **TP-046** | 高 genus 超弦振幅的低能展开与 modular graph identities 能否推进一个新阶？ | 固定 genus、点数和 `α′` 阶，化简一组 modular objects，给出可数值验证的恒等式或积分值。 | 5/5 | M | B · [S23](SOURCES.md#s23) |
| **TP-047** | 固定质量维数的 higher-derivative double-copy/KLT 相容 EFT 能否完整分类？ | 在四点、固定导数阶枚举 local operators，施加 factorization/KLT，输出独立系数空间及机器可查基。 | 5/4 | L | B · [S19](SOURCES.md#s19) |
| **TP-048** | 强耦合 SCFT 的分类/紧化不变量能否在一个窄 rank 与维数窗口补全？ | 从 4d N=2 rank-2 或一个 5d→4d 紧化族中任选其一，枚举离散数据并用 anomaly/几何约束排除不一致项。 | 4/5 | M | B · [S24](SOURCES.md#s24) |

## F. 张量网络与格点规范理论

| ID | 候选开放问题 | 首个可闭环目标 | C/V | 资源 | 证据 |
|---|---|---|---:|---|---|
| **TP-049** | 非阿贝尔格点规范理论的 tensor-network 连续极限能否带受控误差取得？ | 在 2+1 维最小 SU(2) benchmark 中分解有限 bond、有限体积和格距误差，并给出可复现实验包。 | 4/5 | H | B · [S25](SOURCES.md#s25) |
| **TP-050** | 有限密度或实时 tensor-network 规范理论能否同时控制 Gauss-law 和截断误差？ | 对一个 Schwinger/简化非阿贝尔 quench，给出随时间增长的两类误差上界及守恒量审计。 | 4/5 | H | B · [S25](SOURCES.md#s25) |

## 不纳入首轮的宏大问题

宇宙常数、完整量子引力、弦景观中的标准模型真空、一般四维 Yang–Mills 存在性与质量隙等当然更重大，但目前不具备适合 Codex 单独主导的有限验收条件。它们只应作为母方向；必须先切成类似上表的可证伪子问题。
