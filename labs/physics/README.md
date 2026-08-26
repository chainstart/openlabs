# OpenLabs Physics：物理研究实验室

这个实验室把理论、计算和公开实验数据驱动的物理开放问题改写成可审计、可计算、可证伪的研究课题，供 Codex 主导文献审计、解析推导、符号计算、数值研究、公开数据分析和独立复核。它不控制或执行现实世界的物理实验，但允许下载许可清晰的公开实验/观测数据进行研究。

这里收录的是“候选开放问题”，不是对全球文献空白的永久保证。每次启动课题前都必须重新检索近期论文，确认目标没有被解决，并把“已知结果、真正缺口、最小可发表增量”分开记录。

## 目录

- [`lab.json`](lab.json)：OpenLabs 运行时、协议、Skill 和能力注册。
- [`CONSTRAINTS.md`](CONSTRAINTS.md)：权限、资源、科研门禁和产物位置审计。
- [`problems/CATALOG.md`](problems/CATALOG.md)：50 个候选课题及首个可闭环目标。
- [`problems/SHORTLIST.md`](problems/SHORTLIST.md)：优先级、选择理由和建议启动顺序。
- [`problems/SOURCES.md`](problems/SOURCES.md)：主要原始文献与证据索引。
- `problems/shortlist/TP-*/PROBLEM.md`：首批 6 个课题的可执行研究档案。
- [`skills/physics-research-loop`](skills/physics-research-loop/SKILL.md)：物理研究主循环与证据门。
- `skills/vendor/{astropy,qutip}`：固定版本、许可清晰的上游领域 Skill。
- [`protocols/physics_research_protocol.py`](protocols/physics_research_protocol.py)：提交前的数据、计算和结论证据验证。
- [`tools`](tools)：隔离环境检查、公开数据摄取和计算回执工具。
- [`registries`](registries)：经审计的工具与公开数据源清单。

## 课题准入原则

1. **闭环**：必须能写出有限的完成条件，而不是只问“理解量子引力”。
2. **可核验**：至少产生一种可机器复核的对象，例如对偶证书、恒等式、积分基、数值区间、反例或公开代码。
3. **边界清楚**：区分定理、数值证据、物理猜想和经验规律。
4. **资源可控**：所有重计算使用仓库共享资源护栏；首轮实验按 30 GiB 软上限设计，超出时先缩小截断、对称扇区或运动学区域。
5. **新颖性审计**：开题、得到主结果、准备投稿三个节点都重新查重。
6. **双重复核**：关键推导至少用两条独立路线检查；数值结论保留输入、版本、精度和误差预算。

## 状态与证据等级

- **A**：2025–2026 年原始论文明确留下缺口，或最新结果本身暴露出可定位的下一问题。
- **B**：权威综述或 2022–2024 年原始论文明确提出，快速检索未发现完整解决；开题时仍需近期查重。
- **C**：从已知结果推导出的自然延伸，研究价值可能高，但“仍开放”需要更严格的专题审计。

## 状态与产物位置

- 可版本化的小型研究状态：`$OPENLABS_WORKSPACE/openlabs-data/workspaces/physics/<campaign-id>/`
- 私有 attempt：`$OPENLABS_WORKSPACE/openlabs-artifacts/attempt-workspaces/`
- 大型数据、模型和数值输出：`$OPENLABS_WORKSPACE/openlabs-artifacts/experiments/<campaign-id>/`
- 通过门禁的不可变结果：`$OPENLABS_WORKSPACE/openlabs-artifacts/result-bundles/`
- 活任务、租约和 attempt 索引：`$OPENLABS_WORKSPACE/openlabs-database/live/factory.sqlite`

先用 `uv sync --all-groups` 安装锁定环境；该命令及其他重计算必须通过仓库根目录的 `bin/openlabs-resource-guard` 运行。`tools/dataset_intake.py` 只接受 HTTP(S) 公共来源，并要求记录许可/条款、引用和 SHA-256；凭据和受限数据不得进入仓库。
