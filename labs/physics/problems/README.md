# 问题库使用说明

先读 [`SELECTION_POLICY.md`](SELECTION_POLICY.md) 和 [`SUBPROBLEM_POLICY.md`](SUBPROBLEM_POLICY.md)。从 [`CATALOG.md`](CATALOG.md) 确认母题，再从 [`SUBPROBLEMS.md`](SUBPROBLEMS.md) 选择一个 `recognized_open` 子问题，最后才能提出有界工作包。`SHORTLIST.md` 只是待审方向，不授予启动资格；机器真源是 [`portfolio.json`](portfolio.json) 和 [`subproblems.json`](subproblems.json)。

工作包申请必须同时回答：

1. 它推进哪个 `PHY-NNN-SP-NN` 公认子问题及其 `PHY-NNN` 母题；
2. 它会排除、证明或显著收紧子问题的哪项物理可能性；
3. 为什么它不是单篇论文的自然下一步、一个额外系数、图族或 benchmark；
4. 当前文献边界、可证伪条件、独立复核和停止条件是什么。

旧 TP-001—TP-050 已逐项复审，结论见 [`AUDIT-2026-09-02.md`](AUDIT-2026-09-02.md)。旧目录和详细题面保存在 `archive/2026-08-26-paper-derived/`，用于 provenance 和负结果追踪，不能直接重启。

运行 `python labs/physics/tools/problem_portfolio.py labs/physics/problems/portfolio.json --subproblems labs/physics/problems/subproblems.json` 可检查两级问题的独立权威来源、父子关系、决定性结果、ID、日期和暂停状态。
