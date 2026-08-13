# 可插拔科研项目与连续 Codex 运行架构

## 四层职责

OpenLabs 将科研运行拆成四层，依赖方向只能自上而下：

| 层 | 稳定接口 | 拥有的内容 |
|---|---|---|
| 工厂内核 | task/result/receipt、事务、资源、会话、角色 | 队列、并发、租约、隔离、哈希归档和原子提交 |
| 领域协议插件 | lab `protocols` 注册和 validator 命令 | 领域状态/证据完整性与可重放 oracle；开放研究协议不规定科研阶段 |
| 项目配置 | `openlabs.project.v1` | 科研目标、选用协议、Skill、workstream、审查触发和会话策略 |
| Codex 自主执行 | Skill、工具和项目状态 | 路线推导、实验设计、反例、计算、证明和下一科学决策 |

对应实现位置：

- 工厂内核：`orchestrator/src/openlabs/{engine,db,attempts,contracts}.py`；
- 项目与协议接口：`orchestrator/src/openlabs/{projects,protocols,labs}.py`；
- 项目契约：`packages/contracts/schemas/openlabs.project.v1.schema.json`；
- 数学协议插件：`labs/math/protocols/{autonomous_math_protocol,amra_math_protocol}.py` 和
  `labs/math/lab.json`；
- Codex 行为边界：工厂 Skill、领域 Skill 与 `packages/research-core/lab_runner.py`。

通用项目路径不识别 RH、AMRA 阶段或材料计算细节。增加新项目只需：

1. 选择一个已由实验室注册的 protocol；
2. 写一个 `project.json`；
3. 创建项目声明的 workstream 状态文件；
4. 将项目状态切换为 `active`。

增加全新领域协议时，在对应 `labs/<domain>/lab.json` 注册：

```json
{
  "protocol_id": "example-protocol",
  "primary_skill": "example-skill",
  "runtime_skills": ["example-skill"],
  "validator": {
    "command": [
      "{python}",
      "protocols/validate.py",
      "--project", "{project_config}",
      "--workstream", "{workstream_state}",
      "--mode", "{validation_mode}"
    ]
  }
}
```

validator 是可信、确定性的只读程序，输出：

```json
{"valid": true, "errors": []}
```

控制面在项目发现时以 `discovery` 模式调用，在私有 attempt 提交前以 `commit` 模式再次
调用。后者验证的是私有工作副本，而不是尚未修改的正式状态。协议验证失败时 attempt 被
隔离，不能晋升到正式工作区。

workstream 可选 `continuous` 或 `review_on_new_results`。后者只按“出现了尚未审查的新
结果”这一机械事实启动空白 reviewer；候选判断仍由 reviewer 完成。reviewer 写出的
`candidate_branches` 被原样物化为独立、连续的 researcher campaign，原自由研究 campaign
不停止。候选状态模板和深化目标来自项目配置，随后还要通过项目所选 protocol 的 discovery
验证；外层不设置候选分数、数量、期刊目标或固定路线。candidate Codex 将状态写为
`paused`/`completed` 后，控制面机械停止续种，不用 fallback 推翻其证伪或放弃判断。

`runtime_skills` 只决定本协议实际生效的 Skill 和 authority policy。实验室的其他 Skill 只以
`.agents/optional-methods/` 下可读的方法指南暴露，不注册成当前 Codex 的 active Skill，也不会
把自己的状态机暗中施加到当前
项目。工具 `runtime_setup` 与 Skill 激活相互独立，因此自主 RH 仍可使用 Lean、Sage、Arb、
SMT，而不必遵循 AMRA phase。

项目可用 `read_resources` 声明领域历史档案或可信代码资料。attempt 不复制这些大目录，只把
解析后的 canonical 绝对路径作为只读输入交给 Codex；正式写入仍只能发生在 staged campaign。
`research_index.source_campaign_ids` 则声明需要机械迁移/重建的旧 campaign。索引只从数据库中
状态成功、结果文件存在且 SHA-256 一致的归档重建，不做科学排序。

review packet、cursor 位于 `openlabs-artifacts/portfolio-control/`，不在 reviewer 可晋升的研究
目录中；packet 自带内容哈希。候选物化或 cursor 写入若中断，下一 tick 会从成功 reviewer 的
不可变结果幂等重试，cursor 只在全部分支落地后推进。派生索引也可从数据库与结果包重建。

旧的数学 `production_plan.json` 暂时保留兼容适配器。新项目应使用
`packages/contracts/examples/project.example.json`，无需修改 orchestrator。

## Codex 连续性

协议阶段是持久化状态和审计检查点，不是进程边界。默认执行策略为：

```json
{
  "checkpoint_policy": "role_boundary_or_budget",
  "continue_across_protocol_phases": true,
  "default_session_mode": "resume",
  "fresh_session_boundaries": [
    "independent_replication",
    "adversarial_review",
    "portfolio_review",
    "route_reselection"
  ]
}
```

同一 researcher/experimenter 应在一次 Codex 进程中完成尽可能多的同权限推导、实验和
阶段迁移。只有以下情况才结束当前进程：

- 进入独立或对抗审查；
- 进行组合层路线重选；
- 得到终态结果或遇到真实阻塞；
- 剩余 wall time 只够安全落盘；
- 进程或基础设施发生故障。

不得因为“阶段刚刚改变”或“另一 worker 开始运行”而退出。多个 worker 由资源准入并行
运行，彼此没有关闭对方的权力。

如果进程确实需要退出，同一角色优先恢复原 Codex session。rollover 和普通 replan 不再
自动清空会话；只有没有可恢复 session，或显式 fresh boundary，才启动空白会话。
AMRA 的七个 phase 因而只写入 `campaign_state.json` 和 history；它们不再对应七个 Codex
进程。同一权限可以连续跨过多个已通过 gate 的 phase，`independent_audit` 才切给空白 reviewer。
`autonomous-math` 更薄：AMRA 只是 Codex 可自由选用的方法之一，完全不要求经过这七个 phase。

## 数学研究工作区

AMRA Skill 目录不是实际科研工作空间。三类路径必须区分：

1. 稳定协议代码和 Skill：

   `/home/biostar/work/projects/openlabs/openlabs/labs/math/skills/amra-research-loop/`

   这里保存可复用的说明、Schema、模板、状态机代码和测试，不保存正在运行的 RH 研究。

2. 正式、权威的数学研究状态：

   `/home/biostar/work/projects/openlabs/openlabs-data/workspaces/math/<workstream-id>/`

   例如 RH Weil 路线位于
   `openlabs-data/workspaces/math/math-rh-weil-pair-correlation/`。这里的
   `production_lane.json`、`research/cycle-*`、AMRA artifacts 和程序摘要才是正式科研记录。

3. 某次 Codex 任务的可写事务副本：

   `/home/biostar/work/projects/openlabs/openlabs-artifacts/attempt-workspaces/.../workspaces/math/...`

   Codex 实际只写这里。通过结果门禁、领域 protocol validator 和证据归档后，控制面才将
   整个副本原子晋升到 `openlabs-data`；失败或中断的副本保留为隔离记录。

大型不可变证据保存在 `openlabs-artifacts`，运行队列和 session 索引保存在
`openlabs-database/live/factory.sqlite`。SQLite 不是科研事实的唯一来源。

数学实验室还通过通用 `runtime_setup` 接口准备固定的 Lean 4.26/Mathlib 4.26 运行时。共享
编译器和依赖缓存在 `openlabs-artifacts/toolchains/`，项目 `.lean` 源码与
`openlabs.lean_verification.v1` 收据在私有 attempt 的 AMRA `formal/lean/` 下。正式化状态为
`passed` 时，`amra-math` 在提交前核对全部输入哈希并重新运行 Lean；共享 runtime 本身不会
随 campaign 晋升。

同一接口还准备三种可插拔计算 profile：Sage 10.8 精确计算、Sage/Arb 严格球算术，以及
Z3 4.12.6 与 cvc5 1.1.2 双求解器一致性检查。源码和
`openlabs.math_computation.v1` 收据分别位于 attempt 内的 `experiments/sage/`、
`experiments/arb/`、`experiments/smt/`。数学协议将显式列入状态的计算收据视为可重放证据，
但仍要求自然证明说明有限计算、区间覆盖或 SMT 编码为何足以支持目标结论。

数学工具子进程不是只做资源“预留”：能够连接 user systemd 时使用独立 scope；Codex 原生
隔离隐藏 user D-Bus 时直接继承 `openlabs-workers.slice` 聚合硬上限，并继续设置地址空间、
CPU 时间、墙钟、线程/进程数、单文件、打开文件数和捕获输出上限。Lean
验证动态取 WSL 内核可见物理内存与 CPU 线程的 75%，当前 44 GiB/20 核配置对应
33105 MiB 与 15 线程，墙钟仍为 300 秒；任务的 4 GiB/2 线程申报只是调度估算，不会再压低
Lean profile。多个 Lean 校验串行。worker 的任务级内存值改为 `MemoryHigh` 软提示，所有
worker 与数学工具则共同继承 `openlabs-workers.slice` 的约 80% 聚合 `MemoryMax`、零 swap
护栏，因此并发工具也不能把 WSL 整体内存耗尽。worker 的 `TasksMax` 下限为 512，不再用
64 个 task/thread 阻断 Codex code host 或 Lean。数学实验室 worker 的 CPU cgroup 允许按
lab 配置突发到主机线程的 75%（当前为 `CPUQuota=1500%`），所以 D-Bus 不可用、Lean 继承
父 cgroup 时也不会被旧的 2 核调度估算压回 200%。

当前 RH 项目的通用入口是
`openlabs-data/workspaces/math/production/math-rh-direct-v2/project.json`。其状态仍为
`paused`，与上一轮定时运行已经结束的事实一致；本次架构迁移没有擅自恢复科研任务。它现在
只声明 `math-rh-free-exploration` 与 `math-rh-portfolio-review` 两个服务型 workstream；原三条
路线保留为历史知识而非准入边界。reviewer 发现候选后，运行时按稳定 candidate id 动态创建
并行深化 workstream。项目索引已机械回填旧三路线的 129 个成功、哈希一致结果；项目仍暂停，
本次迁移没有启动新 worker。
