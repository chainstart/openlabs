# Codex 自主科研运行时

OpenLabs 的自动化边界按“科研判断归 Codex、状态确定性归控制面”划分。外层工作流不编码
数学路线、不枚举科研微步骤，也不根据启发式分数替 Codex 决定下一项证明操作。

```text
管理员期望状态（plan / lane / budget）
                 │
                 ▼
短生命周期 tick：租约、资源准入、attempt 事务、自动续接
                 │
                 ▼
私有 campaign 副本
  ├─ .agents/skills  ──► 工厂 Skill + 当前实验室 Skills
  ├─ .codex/hooks.json ─► 简短 SessionStart 上下文 + Stop 结果自检
  └─ Codex 原生 workspace-write sandbox
                 │
                 ▼
Codex 自主分析、分解、调用工具并连续跨越同角色协议阶段
                 │
                 ▼
结果身份封装 → 契约/证据门禁 → 不可变归档 → campaign 原子晋升
                 │                         └─ 失败：attempt 隔离并按策略续接
                 └─ 仅在角色边界、终态、阻塞或预算边界产生 next_actions
```

## 职责边界

Codex 与领域 Skill 负责：

- 阅读持久状态并判断当前科学前沿、障碍和最高信息量操作；
- 在一次有界 episode 中自主完成必要的搜索、推导、计算、反例与修正；
- 区分猜想、证据、证明、反证和未知，保存负结果；
- 形成可恢复 checkpoint，并提出可执行的后继目标。
- 将协议阶段作为可恢复状态记录；同一权限和预算内不因阶段变化退出当前进程。

Hook 只负责：

- 在会话开始时注入很短的角色、私有工作区、Skill 和结果路径上下文；
- 在会话停止时检查结果 JSON 的契约与任务身份；
- 最多阻止停止一次，让 Codex 自己补齐交付，而不规定补齐步骤；续接后的 Stop 必须重新
  验证最终结果并写入明确的通过或终态失败回执，不能把重入本身当作成功或忽略。

确定性 Python 代码只负责：

- 租约、心跳、资源与时间上限；
- 创建私有 attempt、Codex 原生沙箱策略和受信 Hook；
- 绑定任务身份、验证本地证据、不可变存储和事务晋升；
- 对每一种终止路径关闭 attempt，并从持久状态自动续接；
- 阻止提交、发布、越权写入和其他不可逆外部动作。

## 运行时不变量

1. Codex 不再套入会破坏其子进程工具调用的第二层 bubblewrap；非 Codex adapter 仍使用
   外层隔离。Codex 命令由 runner 强制归一为 `workspace-write`，拒绝 sandbox bypass、额外
   可写目录和受保护的配置覆盖。聚合工作区与 canonical 不得位于系统临时根。
2. `.agents` 与 `.codex` 是 attempt 临时运行时，不属于科研状态，不复制自 canonical，
   也不晋升回 canonical。
3. `requested_output_path` 永远是用户任务意图；`output_path` 永远是当前 attempt 的绑定，
   初始化数据库不得把后者回写到前者。
4. 通过身份校验的当前回执一旦发现结果损坏，立即终结并隔离 attempt；不等待租约过期。
5. 启动失败、结果拒绝、租约过期、取消和预算停止都必须给 attempt 写入终态。
6. 只有通过结果契约、证据门禁和不可变快照的 `completed` 结果可以原子晋升 campaign。

## 项目与协议插件

控制面只发现 `openlabs.project.v1`，不解释项目的科学配置。项目通过 `protocol.id` 选择
实验室在 `lab.json` 注册的领域协议，协议 validator 在项目发现和 attempt 提交前分别验证
正式状态与私有修改状态。项目目标、workstream、Skill、优先级和连续会话策略都由
`project.json` 替换，无需修改调度器。详见
[project-protocol-architecture.zh.md](project-protocol-architecture.zh.md)。

新增故障应先判断它违反了哪一条不变量，再修改所属职责层；禁止在科研调度路径上继续堆叠
针对单个课题、单个错误字符串或单次运行的特殊分支。
