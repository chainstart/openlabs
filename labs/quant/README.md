# OpenLabs Quant Lab

Quant Lab 是 OpenLabs 的量化金融领域包。Codex 负责文献边界、假设、实验取舍、失败解释和
论文主张；Qlib、VectorBT、NautilusTrader、MLflow、Optuna 以及统计库承担确定性计算。

实验室面向可发表的因子、策略、市场微观结构、组合构造和风险研究，不提供投资建议，不接入
实盘账户，也不会根据一个回测指标自动宣布发现。它把四类容易被忽略的证据做成硬约束：

- 数据必须有来源、获取时间、哈希和 point-in-time/修订/退市政策；
- 所有尝试（包括失败和调参）必须进入 trial ledger；
- 确认性测试集只能按预先登记的规则使用一次；
- 回测必须明确执行延迟、费用、滑点、换手和多重检验处理。

## 环境

本领域固定 Python 3.11，并使用独立环境：

```bash
cd labs/quant
uv sync --all-groups
uv run python tools/quant_runtime.py doctor --lab-root .
uv run pytest
```

默认组足以进行数据与统计研究；`research` 组含 Qlib、VectorBT、MLflow、Optuna 和组合优化；
`execution` 组含 NautilusTrader/CCXT，仅用于需要事件驱动复核的工作，不授权交易。

## 运行边界

版本库中的协议、示例和 registry 是只读模板。实际研究状态写入
`$OPENLABS_WORKSPACE/openlabs-data/workspaces/quant/<campaign-id>/`；下载数据、特征矩阵、模型、
预测和大规模回测输出写入 `openlabs-artifacts/experiments/<campaign-id>/`。任何论文候选都应能从
trial ledger、data manifest 和 backtest receipt 追溯到冻结输入。

最小协议样例在 `protocols/examples/`。外部工具和数据源采用理由见
[`../../docs/quant-lab-reuse-audit.zh.md`](../../docs/quant-lab-reuse-audit.zh.md)。
