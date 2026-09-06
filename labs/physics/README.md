# OpenLabs Physics：物理研究实验室

这个实验室把理论、计算和公开实验数据驱动的物理开放问题改写成可审计、可计算、可证伪的研究课题，供 Codex 主导文献审计、解析推导、符号计算、数值研究、公开数据分析和独立复核。它不控制或执行现实世界的物理实验，但允许下载许可清晰的公开实验/观测数据进行研究。

这里的活跃组合只收录有跨机构权威依据、长期领域关注和明确基础影响的重大母问题。它不是对全球文献空白的永久保证；每次启动具体工作包前仍须重查近期论文，并把“母问题的重要性”“当前开放边界”和“本工作包的实质贡献”分开记录。

## 目录

- [`lab.json`](lab.json)：OpenLabs 运行时、协议、Skill 和能力注册。
- [`CONSTRAINTS.md`](CONSTRAINTS.md)：权限、资源、科研门禁和产物位置审计。
- [`problems/CATALOG.md`](problems/CATALOG.md)：8 个经复审的领域级重大开放问题。
- [`problems/SELECTION_POLICY.md`](problems/SELECTION_POLICY.md)：重要性、独立权威来源和工作包准入门槛。
- [`problems/portfolio.json`](problems/portfolio.json)：可机器校验的活跃问题组合。
- [`problems/SUBPROBLEMS.md`](problems/SUBPROBLEMS.md)：8 个母题下的 24 个共同体公认关键子问题。
- [`problems/SUBPROBLEM_POLICY.md`](problems/SUBPROBLEM_POLICY.md)：母题—子问题—工作包三层结构和 PRL 级科学门槛。
- [`problems/subproblems.json`](problems/subproblems.json)：可机器校验的公认子问题注册表。
- [`problems/AUDIT-2026-09-02.md`](problems/AUDIT-2026-09-02.md)：旧 TP-001—TP-050 的逐项判定。
- [`problems/SHORTLIST.md`](problems/SHORTLIST.md)：可考虑但尚未获批的工作包方向。
- [`problems/SOURCES.md`](problems/SOURCES.md)：官方战略、十年调查、奖项问题和社区前沿报告。
- `problems/archive/2026-08-26-paper-derived/`：旧目录、题面和来源，保留作历史证据但不得启动。
- [`skills/physics-research-loop`](skills/physics-research-loop/SKILL.md)：物理研究主循环与证据门。
- `skills/vendor/{astropy,qutip}`：固定版本、许可清晰的上游领域 Skill。
- [`protocols/physics_research_protocol.py`](protocols/physics_research_protocol.py)：提交前的数据、计算和结论证据验证。
- [`tools`](tools)：隔离环境检查、公开数据摄取、计算回执和客观问题判决工具。
- [`registries`](registries)：经审计的工具与公开数据源清单。

## 课题准入原则

1. **先过重要性门**：至少两个独立权威来源认可，且至少一个是官方战略、十年调查或公认奖项问题；单篇论文 outlook 不够。
2. **三层分级**：母题不直接执行；公认子问题必须有独立共同体依据；工作包必须说明它会改变哪个子问题判据。
3. **闭环**：必须能写出有限的完成条件，而不是只问“理解量子引力”。
4. **可核验**：至少产生一种可机器复核的对象，例如对偶证书、恒等式、积分基、数值区间、反例或公开代码。
5. **边界清楚**：区分定理、数值证据、物理猜想和经验规律。
6. **资源可控**：所有重计算使用仓库共享资源护栏；首轮实验按 30 GiB 软上限设计，超出时先缩小截断、对称扇区或运动学区域。
7. **新颖性审计**：开题、得到主结果、准备投稿三个节点都重新查重。
8. **双重复核**：关键推导至少用两条独立路线检查；数值结论保留输入、版本、精度和误差预算。

## 组合状态

- `active`：通过领域级重要性门的母问题。
- `recognized_open`：通过共同体认可和决定性边界门的子问题，但执行仍暂停。
- `watch`：可能重要，但权威共识或开放性证据仍不足。
- `archived`：保留历史与负结果，但没有启动资格。
- `aligned_work_package_only`：只可在明确推进某个 active 母问题时重新申请。

## 状态与产物位置

- 可版本化的小型研究状态：`$OPENLABS_WORKSPACE/openlabs-data/workspaces/physics/<campaign-id>/`
- 私有 attempt：`$OPENLABS_WORKSPACE/openlabs-artifacts/attempt-workspaces/`
- attempt 内大型数据、模型和数值输出：任务声明的 `artifact_staging_root`（physics runtime
  暴露其 `experiments_root`）
- 发布后的 payload：`$OPENLABS_WORKSPACE/openlabs-artifacts/objects/sha256/`；可浏览索引位于
  `openlabs-artifacts/experiments/.../manifest.json`
- 通过门禁的不可变结果：`$OPENLABS_WORKSPACE/openlabs-artifacts/result-bundles/`
- 活任务、租约和 attempt 索引：`$OPENLABS_WORKSPACE/openlabs-database/live/factory.sqlite`

`factory.sqlite` 的 `tasks.status=succeeded` 只表示一个有界任务通过门禁，不表示开放问题已经
解决。旧 TP 三题的历史科学判决保存在对应 workstream 的 `resolution_decision.json`；
`tools/problem_verdict.py` 只在某条预先声明路线的全部原子条件均为 `met` 且证据文件存在时，
才允许把 `problem_verdict: open` 改为解决态。项目协议在后续晋升时强制执行这条门禁。

不要把 payload 直接写入 live artifacts 路径。每个 artifact-stage 文件都必须出现在
`result.artifacts` 并携带 SHA-256；控制面只把小型引用 manifest 晋升进 campaign。

先用 `uv sync --all-groups` 安装锁定环境；该命令及其他重计算必须通过仓库根目录的 `bin/openlabs-resource-guard` 运行。`tools/dataset_intake.py` 只接受 HTTP(S) 公共来源，并要求记录许可/条款、引用和 SHA-256；凭据和受限数据不得进入仓库。
