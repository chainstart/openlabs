# OpenLabs 个人运行手册

## 手工演练

所有命令都以外层工作空间为边界：

```bash
cd "$HOME/work/projects/openlabs/openlabs"
export OPENLABS_WORKSPACE="$HOME/work/projects/openlabs"
export PYTHONPATH="$PWD/orchestrator/src"
python3 -m openlabs init
python3 -m openlabs status
python3 -m openlabs tick
```

`init` 也会把现有本地 SQLite 以加列方式迁移到 v5；不会删除 campaign、task 或研究索引。

继续当前数学 campaign 的最小任务示例（先不要启用 timer）：

```bash
python3 -m openlabs enqueue \
  --campaign-id opg-1757-transverse-lift-round7 \
  --domain math \
  --skill amra-research-loop \
  --runner frontier \
  --cpu-threads 2 \
  --memory-mib 4096 \
  --scratch-mib 4096 \
  --input "$OPENLABS_WORKSPACE/openlabs-data/workspaces/math/opg-1757-transverse-lift-round7" \
  --objective "在 survivor_deepening 阶段执行一个最小、可证伪、可检查点恢复的推进步骤"
python3 -m openlabs tick
```

只有结果包通过证据门且显式给出 `paper_candidate: true` 时，控制面才自动排入相同领域的
论文就绪审查任务。通过后依次进入写作和空白会话的双供应商审阅面板；面板通过即停止，
文字问题返回原 writer session，证据问题先交给空白 researcher/experimenter，完成后再返回
原 writer 并重新审阅。所有阶段都使用 `frontier` 档，但不产生任何外部发布副作用。

`tick` 是一次短生命周期、幂等调度，不是永不退出的大 Agent。3 分钟是调度检查周期，不是
worker 的寿命：tick 先接收完成结果，再回收过期租约，最后按 CPU、内存和临时盘余量启动
能放下的新任务；仍有心跳和有效租约的 worker 会跨越许多 tick 继续运行。队首任务暂时放不下
时会保留排队并尝试其他 campaign。单个任务失败、等待人工或被隔离，不会阻塞其他 campaign。

普通有界 campaign 只需播种第一个任务。通过门禁的结果若给出 `next_actions`，控制面只取
第一项生成后继；合法的 `needs_replan` 自动升级到 `frontier`，而 `needs_human`、隔离、
无下一步或达到任务上限会停止该链。被活动 `production_plan.json` 声明的产线则是持久期望
状态：控制面自动绑定、在空闲时从产线状态或最后结果补种任务，并在任务数或 Agent 时间窗口
耗尽后换到新 `production_epoch`。历史任务和累计用量不删除，只重置本轮安全窗口。因此
`max_auto_tasks_per_epoch` 是连续产线的单轮保险，而不是工厂寿命。可将 `auto_continue = false`
切回每步人工排队模式；这不会关闭生产计划的状态同步。

每个 campaign 同时只运行一个任务。默认单任务预留 2 个 CPU 线程、4 GiB 内存和 4 GiB
临时盘，最多运行 4 小时；普通 campaign 的 Agent 运行时间累计上限为 24 小时，连续产线则
每个生产轮次拥有同样的 24 小时窗口并保留终身累计账本。主机默认保留
2 个 CPU 线程、8 GiB 内存和 64 GiB 磁盘不给工厂使用。`max_worker_processes = 8` 只是
异常保险，不是日常并发目标。普通 campaign 预算耗尽后排队任务转为 `NEEDS_HUMAN`；连续
产线在没有运行中任务时换轮并继续。两者都不会占用其他 campaign 的资源。

## Agent runner

真实研究任务通过一个明确的 argv 模板调用本机 Agent。不要把 API key 写入仓库：

```bash
mkdir -p "$HOME/.config/openlabs"
${EDITOR:-vi} "$HOME/.config/openlabs/env"
```

文件内容示意：

```text
OPENLABS_AGENT_COMMAND_CHEAP_JSON='["codex","exec","--profile","openlabs-cheap","-"]'
OPENLABS_AGENT_COMMAND_BALANCED_JSON='["codex","exec","--profile","openlabs-balanced","-"]'
OPENLABS_AGENT_COMMAND_FRONTIER_JSON='["codex","exec","--profile","openlabs-frontier","-"]'
OPENLABS_AGENT_RESUME_COMMAND_JSON='["codex","exec","resume","{session_id}","-"]'
OPENLABS_AGENT_TIMEOUT_SECONDS=14400
OPENLABS_CLAUDE_COMMAND=claude
# OPENLABS_CLAUDE_SETTINGS=/home/you/.claude/settings.json
```

先在本机 Codex 配置中建立三个确实使用不同模型/effort 的 profile；如果只有一个档位，就只
配置通用的 `OPENLABS_AGENT_COMMAND_JSON`，不要把三个相同命令伪装成路由。新会话命令不得
包含 `--ephemeral`，否则研究链无法恢复。模板可使用 `{workspace}`、`{agent_workspace}`、
`{prompt_file}`、`{output_file}`、`{output_dir}`、`{skill_path}` 和 `{task_file}`；恢复命令还
必须包含独立的 `{session_id}` 参数。如果 runner 未配置，
工厂会安全地产生 `needs_human`，不会假装完成研究。
模板只描述 provider、model/profile 与会话参数。runner 会统一加入 JSONL、私有工作目录、
`approval_policy=never`、Codex 原生 `danger-full-access` 和受信 project hook 参数。外层模板
不得覆盖这些工厂运行参数。Codex 以 worker 的普通 Linux 用户权限运行，可以自由调用已安装
工具、网络、缓存、编译器和跨目录材料；它仍受 systemd/cgroup 的 CPU、内存、进程和时间
护栏约束。attempt workspace 仍是约定的研究与成果写入位置，正式成果只由控制面在协议验证
后晋升。先用 smoke task 验证文件协议，再接入真实 Agent。

研究者、同一实验执行链和同一稿件修订链可按 session ID 恢复，但每个节点仍启动一个有界
进程并在完成后退出。节点内部可以跨越多个不应持久化为边界的微步骤；等待外部实验、形成
原子 checkpoint、改变角色或进入独立审阅时才结束节点。让同一 Codex OS 进程空转两天不会
免除模型处理活动上下文的 token 成本，还会扩大恢复和资源泄漏面，因此不作为连续性机制。
独立复现实验、`needs_replan`、从研究切换到首次写作，以及所有 reviewer 都启动空白会话；
reviewer 不接收作者或其他 reviewer 的 session。
结果中的普通字符串 `next_action` 续接当前角色；跨角色或独立同角色运行必须使用结果合同中的
结构化 action。角色切换默认强制为 `fresh`；唯一例外是 `paper_review` 返回
`handoff_kind: text_revision` 时，控制面从任务祖先链恢复原 writer 的 session，而不是恢复
reviewer session。`evidence_remediation` 永远先启动空白 researcher/experimenter。

论文门禁的第二位审阅人不复用上述 Codex session。它由
`run_claude_reviewer.py` 启动一次全新的 Claude Code `claude-opus-5` 进程，并从用户自己的
Claude settings 读取 Packy endpoint 和凭据。仓库、env 示例、prompt 和审阅产物都不得保存
Packy key。第一位 Codex 审阅结果先冻结；适配器只计算其 SHA-256 绑定，不把内容发给 Claude。

## systemd user timer

仓库只提供 unit，不自动启用：

```bash
mkdir -p "$HOME/.config/systemd/user"
cp deploy/systemd/openlabs-factory.target deploy/systemd/openlabs-workers.target \
  deploy/systemd/openlabs-workers.slice \
  deploy/systemd/openlabs-tick.service deploy/systemd/openlabs-tick.timer \
  "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now openlabs-factory.target
systemctl --user status openlabs-tick.timer
journalctl --user -u openlabs-tick.service
```

若 OpenLabs 不在默认 `$HOME/work/projects/openlabs`，先修改复制后的 unit。停机使用：

```bash
systemctl --user disable --now openlabs-factory.target
```

该命令同时停止调度 timer 和 `openlabs-worker-*.service` 的完整进程组；仅停止
`openlabs-tick.timer` 不等于全厂停机。

有绝对截止时间的试运行应通过控制面停机，以便计划、campaign、task 和 attempt 状态与
进程同时收敛，而不是只杀进程：

```bash
python3 -m openlabs halt-production \
  --plan "$OPENLABS_WORKSPACE/openlabs-data/workspaces/math/production/example/production_plan.json" \
  --reason timebox_expired \
  --report "$OPENLABS_WORKSPACE/openlabs-data/workspaces/math/production/example/timebox_stop_report.json"
```

该命令把计划置为 `paused_timebox_complete`，取消所属排队与运行任务、结算已用 Agent 时间、
终止已登记 worker 进程组，并停用 `openlabs-factory.target`。如需准点运行，应由独立于 factory
target 的 persistent systemd timer 调用此命令；否则停机动作会随 factory 一起被停止。
新的通用 `project.json` 项目使用对应的项目级命令，不要求其领域配置恰好是旧 production plan：

```bash
python3 -m openlabs halt-project \
  --project "$OPENLABS_WORKSPACE/openlabs-data/workspaces/math/production/example/project.json" \
  --reason timebox_expired \
  --report "$OPENLABS_WORKSPACE/openlabs-data/workspaces/math/production/example/project_stop.json"
```

它会在同一控制面锁下暂停项目，并取消所有静态或动态生成的绑定 campaign。

每个 Agent attempt 都在 `openlabs-artifacts/attempt-workspaces/` 的私有 campaign 副本中开始。
Codex adapter 使用原生 `danger-full-access`，因此它调起的 shell、Python、证明器、编译器和
包管理器不会再被文件系统沙盒阻断。隔离目录此时是事务约定和默认 cwd，而不是内核强制的
写边界；正式成果仍必须通过结果合同、协议验证、不可变归档和目录交换才能晋升。非 Codex
adapter 仍由 worker 使用 bubblewrap 只开放本 attempt；本机缺少 bubblewrap 时拒绝启动，
不会降级为共享写入。
只有状态为完成、通过文件门禁且所有证据已复制到 `openlabs-artifacts/result-bundles/` 不可变
归档的节点，才会以目录交换方式提升到正式 campaign；数据库确认入库前保留原目录作为回滚
副本。取消、超时、失败和门禁拒绝的 attempt 只留下带原因的隔离 checkpoint。tick 与
`halt-production` 共用跨进程排他锁，因此截止停机不能与结果提升交错执行。

systemd 只保证 tick 被再次调用；科学恢复由 SQLite 租约、心跳、超时、有限重试、结果
门禁和 `quarantined`/`needs_replan` 状态负责。Agent 有界超时后会终止其进程组。复杂且
不可逆的十字路口进入 `needs_human`，但工厂继续运行其他课题。

## 台式机与笔记本交接

同一时间只允许一台机器写 `openlabs-database/live/factory.sqlite`。推荐流程：

1. 在当前机器停止 timer，等待或停止活动 worker；
2. 运行 `python3 tools/index_workspace.py`，刷新可追踪的 JSON 导出；
3. 提交并推送 `openlabs`、`openlabs-data`、`openlabs-database` 三个仓库的代码/状态/导出；
   大型本地产物按需另行同步 `openlabs-artifacts`；
4. 在另一台机器拉取后，从导出重建索引或复制一个停写状态下生成的一致 SQLite backup；
5. 确认旧机器 timer 已停止，再启动新机器 timer。

不要通过 Git、网盘同步或双向复制合并两个正在写入的 SQLite/WAL 文件。活库很小并不
意味着它可合并；可移植 JSON 状态才是跨设备的交接面。

## 外部副作用

第一版不自动投稿、公开发布或远程 handoff。论文适配器默认拒绝外部写操作；只有管理员
针对一次明确操作设置 `OPENLABS_ENABLE_EXTERNAL_WRITES=1` 才会解除代码门禁。论文
`ready` 状态本身不是这类授权。

## 24 小时部署验收

启用 timer 前先运行 `pytest -q` 和 `ruff check .`。随后用 smoke 或低成本 campaign 做一次
真实 24 小时 soak run，检查：无重复 attempt、无跨 campaign 入库、无超过资源预留/进程保险/
预算的启动、队首大任务不会阻塞可运行小任务、
过期 lease 能恢复或隔离、reviewer 均为 fresh session。单元测试证明状态机边界，soak run
证明目标机器上的 systemd、PATH、Codex profile、凭据和休眠策略确实可连续工作。
