# Quant Lab 复用与依赖审计

- 审计日期：2026-08-21
- 目标：让 Codex 主导量化科研判断，成熟软件承担数据、模型、回测、执行仿真和实验记录
- 范围：研究与论文；不包含实盘交易、券商账户操作或资金配置

## 决策摘要

Quant Lab 不复制第二套调度器，也不把固定多 Agent 流程套在 Codex 外面。OpenLabs 继续掌握
任务、租约、隔离、Hook 和结果归档；Codex 使用 `quant-research-loop` 自主选择研究路线。
领域确定性代码只验证时点数据、全试验账本、封存测试、交易成本和结果身份。

## 直接采用的成熟组件

| 组件 | 用途 | 采用方式 | 主要边界 |
|---|---|---|---|
| Microsoft Qlib | 因子表达式、数据处理、ML、组合回测与实验分析 | Python 依赖；优先研究底座 | 不采用其 Agent 作为总调度器 |
| VectorBT | 大批量向量化策略与参数初筛 | Python 依赖 | 只作研究筛选；执行敏感结论需事件驱动复核 |
| NautilusTrader | 事件驱动、订单簿与成交仿真 | 可选 execution 依赖 | 没有盘口数据时不能伪造队列或冲击精度 |
| MLflow + Optuna | 运行血缘与数值超参数搜索 | Python 依赖 | 全部试验仍需进入 Quant trial ledger |
| Polars + DuckDB + PyArrow | 大型时序/面板数据存取与查询 | Python 依赖 | 原始数据留在 `openlabs-artifacts` |
| statsmodels + arch | HAC、时间序列、波动率与诊断 | Python 依赖 | 统计显著性不能替代经济机制 |
| CVXPY | 约束组合和风险模型 | Python 依赖 | 优化输入和约束必须冻结并记录 |
| exchange-calendars | 交易日历 | Python 依赖 | 仍需处理具体市场的停牌、夜盘和临时规则 |

RD-Agent 的本机参考副本位于
`/home/biostar/work/projects/lab/mle-lab/rd-agent`，并使用 MIT 许可证；Qlib 则由上游 Python 依赖
固定。RD-Agent(Q) 的因子—模型
循环和 Qlib 接口值得参考，但其默认的微小年化收益改善替换规则不适合论文发现，也与 Codex
主 Agent 架构冲突，因此不迁入运行时。

## 数据源

初始 registry 只登记可追溯的一手来源：Binance 官方公开归档、Kenneth French Data Library、
Open Source Asset Pricing、SEC EDGAR 和 FRED/ALFRED。下载器必须保存来源 URL、获取时间、许可
或使用条款、内容哈希、时点字段、修订政策和退市/退出资产政策。收费的 CRSP/Compustat、
Databento、交易所逐笔数据只在管理员提供合法权限后注册。

## Skill 审计

| 候选 | 结论 | 原因 |
|---|---|---|
| OpenLabs 现有 paper/database lookup、统计分析、科研写作 | 复用 | 已审计、已固定版本，适合文献与论文阶段 |
| LLMQuant Skills | 不直接安装 | MIT，但核心工作流绑定 LLMQuant Data；可参考其数据日期和风险披露思想 |
| ALAGENT X2Strategy | 暂不迁入 | 论文到策略规格的思路有用，但审计快照未提供明确许可证，且默认 Backtrader/HITL 流程过重 |
| quant-strategy-builder-skill | 暂不迁入 | 时点/费用检查有价值，但审计快照未提供许可证，并主要面向中国市场手工策略设计 |
| OpenMobius Skill | 不采用 | 面向 ICT/SMC 和零售交易知识，不是可发表量化科研协议 |
| stock-trade-analysis-skills | 不采用 | 面向单股买卖建议，而非新因子、机制和论文证据 |

由于没有一个已审计的公开 Skill 同时满足许可证、Codex 主控、科研证据、全试验登记和
OpenLabs 结果契约，仓库新增两个薄 Skill：`quant-research-loop` 负责科学方法，
`quant-backtest-audit` 负责可选的对抗检查。它们不重写 Qlib 或回测引擎。

skfolio 本身是成熟的 BSD-3-Clause 组合研究库，但当前版本依赖 `cvxpy-base`，与 Qlib 所需的
完整 `cvxpy` 发行包安装到同一个 Python namespace 后会产生可复现的导入冲突。因此它没有
进入主环境；需要时应建独立环境，不能让“已安装但无法导入”的状态通过运行门禁。

## 明确不采用

- 不把 Backtrader、Zipline 或自写撮合器设为唯一研究真相；
- 不使用 Yahoo Finance 作为确认性论文数据的唯一来源；
- 不将当前成分股列表回填历史；
- 不把同一封存测试集反复暴露给 Codex；
- 不因 Sharpe、年化收益或 IC 的微小改善自动晋级；
- 不在本仓库保存 API key、券商凭据、付费数据或实盘下单能力。

## 上游和版本固定

精确依赖版本由 `labs/quant/uv.lock` 固定。外部项目的采用依据和官方入口记录在
`labs/quant/registries/tooling.json` 与 `data_sources.json`；升级必须重新运行 Quant Lab 契约
测试和最小无网络 smoke。
