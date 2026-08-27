# OpenLabs

OpenLabs 是一个面向个人使用、可恢复、可连续运行的轻量科研工厂。它以短生命周期 tick
维护全局任务、租约和质量门，以 Agent + Skill 完成文献理解、Idea、证明/实验、解释和
写作；数学、AI/ML、材料、量化金融和物理实验室彼此不 import，只交换版本化任务文件和结果包。

```text
/home/biostar/work/projects/openlabs/   # 聚合目录，不是 Git 仓库
├── openlabs/                           # 公开代码 Git monorepo（本仓库）
├── openlabs-data/                      # 私有研究状态与论文源码 Git 仓库
├── openlabs-artifacts/                 # 私有产物 manifest Git 仓库；大文件忽略
└── openlabs-database/                  # 私有数据库导出 Git 仓库；活 SQLite 忽略
```

当前已迁入：

- AMRA 数学研究循环、38 个 campaign 及当前 OPG-1757 探索脚本；
- AIRA 的 bundle、基准、实验执行/评估和实验记忆工具；
- Quant Lab 的时点数据契约、全试验账本、回测证据门和独立研究环境；
- Physics Lab 的 50 个开放问题、物理证据协议、公开实验/观测数据摄取、Astropy/QuTiP
  领域 Skill 和分组锁定环境；
- matfactory 的材料协议、仿真、分析、队列、审计、隐藏有序/软模发现代码及小型冻结输入；
- 两个材料接续状态：暂停的 LLZTO 长周期 campaign，以及 CPU 校准完成、仍受模型/新颖性
  门约束的隐藏有序/软模试点；旧 23 GiB 运行证据没有混入代码或 openlabs-data Git；
- ara-paper-writing 当前工作树中的 45 篇论文、registry、reviews、确定性工作流和四套
  OpenLabs 领域写作 Skill；
- 旧 ARA 中经审计的文献/数据库查询 Skill，以及其 manifest、租约、bundle、阶段限制等
  思路的精简重写。旧 ARA 巨型固定流水线没有整体复制。

最小控制面位于 `orchestrator/src/openlabs`，只负责发现实验室、SQLite 状态、attempt/租约、
心跳、资源准入、硬预算、有限重试、结果接收和证据门禁。实验室 runner 只读
`openlabs.task.v3` 并输出
`openlabs.result_bundle.v1`，不能直接写数据库。

管理员为一个 campaign 播种首个有界任务后，通过门禁的 `next_actions` 可自动续接下一步；
`needs_replan` 升级到高级 runner，`needs_human`、隔离、无下一步或 campaign 任务上限会停链。
第一版没有让一个永久“大 Agent”自行扫描全部课题并无限消费预算。
同 campaign、同角色的研究/实验/写作后继任务可恢复逻辑 session，但每个 OS 进程仍在一个
有界节点后退出；3 分钟 tick 只检查和调度，不会结束仍有租约与心跳的 worker。普通字符串
action 续接当前角色，结构化 action 才能显式交给另一角色或启动独立同角色运行。replan 和
reviewer 一律从空白 session 启动；审阅后的文字修订只恢复当前任务祖先链中的原 writer
session，绝不继承 reviewer 会话。

工厂不再把“全局同时 2 个任务”当作主限制。每个任务声明 CPU 线程、内存和临时盘峰值，tick
按主机当前余量与活动任务预留量准入；`max_worker_processes` 只是防止错误申报的小任务产生
过多进程的最后保险。同一 campaign 仍串行运行。

快速检查：

```bash
export OPENLABS_WORKSPACE=/home/biostar/work/projects/openlabs
export PYTHONPATH="$OPENLABS_WORKSPACE/openlabs/orchestrator/src"
python3 -m openlabs status
python3 -m openlabs tick
```

重计算、包同步和交互式 Codex 研究必须进入共享资源护栏；安装和用法见
[资源护栏](RESOURCE_GUARD.md)。Codex 本身保留 `danger-full-access` 与网络能力，护栏只限制
OpenLabs 研究负载的聚合 CPU、内存、swap 和任务数。

真实 Agent runner、systemd timer、跨设备 SQLite 交接和外部操作门禁见
[个人运行手册](docs/operations.zh.md)。完整设计见
[架构决策](docs/openlabs-monorepo-architecture.zh.md)，Codex、Skill、Hook 与确定性控制面的
边界见 [自主科研运行时](docs/autonomous-runtime.zh.md)，本次来源与过滤情况见
[迁移报告](docs/migration-report.zh.md)，量化工具与 Skill 的选型见
[量化实验室复用审计](docs/quant-lab-reuse-audit.zh.md)，物理工具与 Skill 的选型见
[物理实验室开源复用审计](docs/physics-lab-open-source-audit.zh.md)。仓库没有自动启用 timer，也没有启动昂贵研究任务。

## License

OpenLabs 原创代码以 [Apache License 2.0](LICENSE) 开源。`orchestrator/skills/vendor`、
`workflows/paper/skills/vendor` 及文件内另有许可声明的第三方组件继续遵循各自许可证和署名。
