# OpenLabs 个人运行手册

论文评审只走统一评审 `review unified-run`；编辑、审稿人、模型与轮次上限以数据仓库
`registry/settings.yaml#review` 为准。已停用的增量复审文档见 `archive/`。

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
论文就绪审查任务。通过后依次进入写作和空白会话的统一评审（面板按
`settings.yaml#review` 配置，跨模型）；评审通过即停止，
文字问题返回原 writer session，证据问题先交给空白 researcher/experimenter，完成后再返回
原 writer 并重新审阅；需要换方向的评审结论在研究计划中交给方向性决定（见下文）。这些阶段
都不产生外部发布副作用。

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
临时盘，调度任务墙钟上限为 12 小时；示例 env 中的 Agent provider 超时为 4 小时，所以可能
更早退出。普通 campaign 的 Agent 运行时间累计上限为 24 小时，连续产线则
每个生产轮次拥有同样的 24 小时窗口并保留终身累计账本。主机默认保留
2 个 CPU 线程、8 GiB 内存和 64 GiB 磁盘不给工厂使用，且调度准入最多使用宿主机逻辑 CPU
的 75%。共享 `openlabs-workers.slice` 对所有 worker、交互式 Codex 和重计算合计施加
15 CPU（本机 20 线程）、30 GiB soft/34 GiB hard 内存、4 GiB swap 和 512 tasks 上限。
`max_worker_processes = 8` 只是
异常保险，不是日常并发目标。普通 campaign 预算耗尽后排队任务转为 `NEEDS_HUMAN`（研究计划
题目改为方向性决定）；连续产线在没有运行中任务时换轮并继续。两者都不会占用其他 campaign 的资源。

## Agent runner

真实研究任务通过一个明确的 argv 模板调用本机 Agent。不要把 API key 写入仓库：

```bash
mkdir -p "$HOME/.config/openlabs"
${EDITOR:-vi} "$HOME/.config/openlabs/env"
```

文件内容示意：

```text
OPENLABS_AGENT_COMMAND_CHEAP_JSON='["codex","exec","--profile","openlabs-cheap","-c","web_search=\"live\"","-"]'
OPENLABS_AGENT_COMMAND_BALANCED_JSON='["codex","exec","--profile","openlabs-balanced","-c","web_search=\"live\"","-"]'
OPENLABS_AGENT_COMMAND_FRONTIER_JSON='["codex","exec","--profile","openlabs-frontier","-c","web_search=\"live\"","-"]'
OPENLABS_AGENT_RESUME_COMMAND_JSON='["codex","exec","resume","-c","web_search=\"live\"","{session_id}","-"]'
OPENLABS_AGENT_TIMEOUT_SECONDS=14400
OPENLABS_AGENT_PREFLIGHT_TIMEOUT_SECONDS=10
OPENLABS_AGENT_PREFLIGHT_STRICT=false
OPENLABS_AGENT_STARTUP_GRACE_SECONDS=120
OPENLABS_AGENT_TRANSPORT_FAILURE_THRESHOLD=3
OPENLABS_CLAUDE_COMMAND=claude
# OPENLABS_CLAUDE_SETTINGS=/home/you/.claude/settings.json
```

先在本机 Codex 配置中建立三个确实使用不同模型/effort 的 profile；如果只有一个档位，就只
配置通用的 `OPENLABS_AGENT_COMMAND_JSON`，不要把三个相同命令伪装成路由。新会话命令不得
包含 `--ephemeral`，否则研究链无法恢复。模板可使用 `{workspace}`、`{agent_workspace}`、
`{prompt_file}`、`{output_file}`、`{output_dir}`、`{skill_path}` 和 `{task_file}`；恢复命令还
必须包含独立的 `{session_id}` 参数。如果 runner 未配置，
工厂会安全地产生 `needs_human`，不会假装完成研究。
所有 `python -m openlabs` 入口都会以“当前进程环境优先”的规则读取
`~/.config/openlabs/env`、`~/.config/environment.d/90-openlabs-proxy.conf`，以及可选的
`~/.config/ara/zenodo.env`，因此手工
`tick`、timer 和 worker 使用同一份 Agent/proxy 配置；这些文件按数据解析，不经过 shell。
Zenodo 文件必须是当前用户拥有的普通文件且权限不宽于 `0600`，只允许
`ZENODO_ACCESS_TOKEN`、`ZENODO_SANDBOX_ACCESS_TOKEN` 和 `ZENODO_ENVIRONMENT`；OpenLabs
启动的 Codex/worker 可以继承它们，但普通登录 shell 仍不会自动携带密钥。该加载机制也不会
设置 `OPENLABS_ENABLE_EXTERNAL_WRITES`，外部写操作仍须按下文针对一次明确操作单独开启。
`tick` 和 `bin/openlabs-codex` 在启动研究前还会执行严格网络门禁：依次探测当前进程继承的
代理和持久代理文件。若当前进程携带一个新的可用代理，它会原子更新
`90-openlabs-proxy.conf`，并通过 `systemctl --user import-environment` 同步大小写代理变量；
随后启动的 transient worker 会继承同一组值。如果所有候选都不可达，则在领取或启动科研
任务前以退出码 69 拒绝运行，不会消耗任务墙钟预算。可独立执行
`PYTHONPATH=orchestrator/src python3 -m openlabs network-preflight` 查看不含凭据的报告。
这个机制不扫描随机端口：它只信任调用环境或用户配置中明确提供的候选，因此无法发现候选时
会安全失败。`OPENLABS_PROXY_AUTO_SYNC=false` 可禁止写回文件，
`OPENLABS_PROXY_SYNC_SYSTEMD=false` 可禁止同步 systemd，代理文件位置可用
`OPENLABS_PROXY_ENV_FILE` 覆盖。
Codex 启动前会对命令中声明的 provider `base_url` 做有界 HEAD 预检。由于 urllib 与 Codex
可能使用不同的认证或代理传输栈，网络失败默认只作提示，URL 语法错误仍会拒绝启动；只有在
确认两者传输路径一致时才设置 `OPENLABS_AGENT_PREFLIGHT_STRICT=true`。真实 Codex 启动后若
只反复出现 transport 错误、没有任何有效 item/turn 进展，startup watchdog 会提前停止并
写入 `needs_human`，不会把网络故障耗满整段科研预算。未在命令里声明 base URL 的自定义
provider 可用 `OPENLABS_AGENT_PREFLIGHT_URL` 明确指定预检地址。
模板只描述 provider、model/profile 与会话参数。runner 会统一加入 JSONL、私有工作目录、
`approval_policy=never`、Codex 原生 `danger-full-access` 和受信 project hook 参数。外层模板
不得覆盖这些工厂运行参数。Codex 以 worker 的普通 Linux 用户权限运行，可以自由调用已安装
工具、网络、缓存、编译器和跨目录材料；它仍受 systemd/cgroup 的 CPU、内存、进程和时间
护栏约束。attempt workspace 仍是约定的研究与成果写入位置，正式成果只由控制面在协议验证
后晋升。先用 smoke task 验证文件协议，再接入真实 Agent。

受信 Agent request 本身携带任务、权限、Skill、隔离事务与结果路径等必要上下文。
`SessionStart` hook 是额外的上下文增强通道；若某个非交互式 Codex CLI 版本未触发项目级
`SessionStart`，但受信 request 完整且最终 `Stop` 闸门通过，控制面会记录兼容性告警并允许
结果进入后续验证。最终 `Stop` 闸门仍是硬条件，缺失或失败时结果不得晋升。修复此类已确认的
基础设施误判后，只能通过 `tools/replay_protocol_receipt.py` 按已归档 receipt、精确错误片段和
白名单 runtime error key 重放；工具不提供通用状态覆盖能力。

研究者、同一实验执行链和同一稿件修订链可按 session ID 恢复，但每个节点仍启动一个有界
进程并在完成后退出。节点内部可以跨越多个不应持久化为边界的微步骤；等待外部实验、形成
原子 checkpoint、改变角色或进入独立审阅时才结束节点。让同一 Codex OS 进程空转两天不会
免除模型处理活动上下文的 token 成本，还会扩大恢复和资源泄漏面，因此不作为连续性机制。
独立复现实验、从研究切换到首次写作，以及所有 reviewer 都启动空白会话；普通
`needs_replan` 在同一研究角色与有效 session 存在时可恢复，否则启动空白会话；
reviewer 不接收作者或其他 reviewer 的 session。
结果中的普通字符串 `next_action` 续接当前角色；跨角色或独立同角色运行必须使用结果合同中的
结构化 action。角色切换默认强制为 `fresh`；唯一例外是 `paper_review` 返回
`handoff_kind: text_revision` 时，控制面从任务祖先链恢复原 writer 的 session，而不是恢复
reviewer session。`evidence_remediation` 永远先启动空白 researcher/experimenter。

项目 workstream 可同时声明单任务 `wall_seconds` 与 campaign 全生命周期累计
`max_agent_seconds`；后者会同步到 campaign 账本并在实际启动时再次收紧任务墙钟。
production epoch 只刷新自动任务数量窗口和保留 lineage，绝不重置累计时间。预算耗尽后
campaign 进入 `budget_exhausted`；只有显式把预算提高到大于已累计用量，才能重新授权。
研究 workstream 只使用 `continuation: continuous`。中间证据增量不能终止活动课题；有效
`needs_replan` 会连同私有状态原子晋级，并按其可执行动作继续。只有达到目标/质量门禁、总
Agent-time 耗尽、真实外部阻塞、明确的独立角色边界，或协议状态被 Codex 标为终态时才停链。
`review_on_new_results` 仅用于按新结果机械触发独立组合审查。

论文评审面板（编辑与两位不同模型家族的审稿人，均为全新进程）以
`registry/settings.yaml#review` 为准。任何审稿凭据只从用户自己的配置读取，仓库、env 示例、
prompt 和审阅产物都不得保存密钥。

### Claude Code 研究执行者与六个 runner

Claude Code 与 Codex 走同一条研究执行路径：可信实验室运行时准备（lab `runtime_setup`）、
同一份结果门禁 Stop hook 与 hook 回执、启动看门狗、按 session 恢复，以及事务隔离。差异只在
lab runner 的适配层：

- 控制面为每个 attempt 同时生成 `.codex/hooks.json` 与
  `.claude/openlabs-settings.json`（只含 SessionStart/Stop 两个 hook，命令都是
  `python -m openlabs.codex_hook ... --context .codex/openlabs-context.json`，Claude 加
  `--adapter claude`）。回执写入同一个 `.codex/hook-receipts.jsonl`，引擎对 `adapter` 为
  `codex` 或 `claude` 的完成结果一律要求最终 Stop 回执通过，缺失即 `needs_replan`。
  `.claude/` 与 `.agents/`、`.codex/` 一样是 attempt 运行时目录，不复制、不晋升。
- 激活的 Skill 同时链接到 `.agents/skills/<name>`（Codex）和 `.claude/skills/<name>`
  （Claude Code 的项目 Skill 目录）；Claude 的请求改为“用 Skill 工具调用 `<name>`”，并给出
  可直接阅读的 SKILL.md 位置。
- lab runner 强制加入 `-p --add-dir <attempt_root> --allowedTools <研究工具清单>
  --permission-mode dontAsk --setting-sources project --settings <生成的设置文件>
  --output-format stream-json --verbose`，拒绝 `--dangerously-skip-permissions`、
  `--allow-dangerously-skip-permissions`、其他 `--permission-mode`、`--bare`、`--safe-mode`、
  `--disable-slash-commands` 以及自带的 `--settings`/`--setting-sources`。`dontAsk` 拒绝一切未
  预先批准的调用，无人值守时不会卡在权限提示上；真正的文件边界是 bubblewrap（attempt root
  可写，`openlabs`、`openlabs-data`、`openlabs-artifacts`、`openlabs-database` 只读），因此
  Claude 执行者要求本机已安装 `bwrap`，缺失时 fail closed。资源护栏与 Codex 相同（worker 的
  systemd/cgroup）。
- 启动看门狗读取 stream-json：在 `OPENLABS_AGENT_STARTUP_GRACE_SECONDS` 内一个事件都没有、
  或只有无 HTTP 状态的 `api_retry`（连接错误）达到 `OPENLABS_AGENT_TRANSPORT_FAILURE_THRESHOLD`
  时停止进程并写 `needs_human`；429/529 重试交给额度分类处理。
- 研究执行者使用本机已登录的 Claude 订阅（`~/.claude/.credentials.json`），不要为这些 runner
  设置 `ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN`，否则额度读数不再
  对应订阅；`run-metadata.json` 的 `runtime.claude_endpoint` 记录实际继承的是默认登录还是
  自定义端点（只记主机名，不记凭据）。也不要设置 `CLAUDE_CODE_RETRY_WATCHDOG`：它让 Claude 在
  进程内等待限额重置，而控制面已按 `[budget]` 退避重排。

配置六个 runner：把 `config/openlabs.env.example` 中三条 GPT 与三条 Claude 的
`OPENLABS_AGENT_COMMAND_<NAME>_JSON`、`OPENLABS_AGENT_RESUME_COMMAND_<NAME>_JSON`
（`LEAD/WORKER/LIGHT` × `GPT/CLAUDE`）复制到 `~/.config/openlabs/env`，再取消
`config/openlabs.toml` 中六个 `[runners.<name>]` 表的注释（各档模型以该文件为准，
`settings.yaml#research_portfolio.autonomy.model_roles` 只记录这一决定；GPT 三条按本机 Codex
profile 填写）。
存在 `[runners]` 表即启用额度路由；
`[routing]` 的保留比例与 `[routing.probe_commands]` 无需改动。只想先试 Claude 时，也可以只在当前
shell 里把 `OPENLABS_AGENT_COMMAND_BALANCED_JSON` 设为 worker_claude 的命令（进程环境优先于
env 文件），用一个有界 `enqueue --runner balanced` 任务走完整链路。

验证 Claude 执行者（操作者在有额度时自己运行，会消耗一次最便宜模型的调用）：

```bash
cd "$(mktemp -d)" && printf 'Reply with the single word ok.' | claude -p \
  --output-format stream-json --verbose --permission-mode dontAsk --setting-sources project \
  --settings '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"cat > stop-event.json"}]}]}}' \
  --model claude-haiku-5-5 --max-turns 1 > stream.jsonl; \
python3 -c 'import json; ev=[json.loads(l) for l in open("stream.jsonl") if l.strip()]; \
print(sorted({e["type"] for e in ev}), ev[-1].get("subtype"), ev[-1].get("is_error")); \
print("stop hook:", json.load(open("stop-event.json")).get("hook_event_name"))'
```

期望看到 `system`、`assistant`、`result`（`success`、`is_error` 为 `False`）、通常还有
`rate_limit_event`，并且 `stop hook: Stop`，说明订阅登录、stream-json、`--settings` 注入的
Stop hook 与 `dontAsk` 在本机都可用。之后再用一个有界任务检查 `run-metadata.json`：
`runtime.adapter == "claude"`、`runtime.hooks.stop_passed == true`、`runtime.session_id`、
`runtime.quota_snapshot` 与 `runtime.filesystem_sandbox == "bubblewrap"`。

## 研究计划：自动选题与立项关口

研究计划默认关闭（`config/openlabs.toml` 的 `[program] enabled = false`），关闭时 tick 与以前
完全一致。启用步骤：

1. 配置 `[runners]`（至少两家模型族各有一个 lead 档 runner）。立项判定者必须与出题者不同模型族；
   没有 runner 表时无法区分模型族，scout 与立项都不会排（报告 `provider_routing_not_configured`）。
2. 为每个参与的学科建一个计划项目：把 `packages/contracts/examples/research-program/` 下的
   `project.json`、`scout_state.json`、`admission_state.json` 复制到
   `openlabs-data/workspaces/<domain>/projects/research-program/`，改 `project_id`、`domain`、
   `protocol.primary_skill`（该学科 lab.json 中 `research-program` 协议的主技能）和两个
   `workstream_id`。项目必须带 `"program": true`；计划项目里不允许声明静态研究 workstream，
   研究 campaign 只能由立项关口物化产生。
3. 先运行 `python -m openlabs program backfill`（默认 dry-run）检查现有在研 campaign，确认后加
   `--write`，把它们登记为 `admission: grandfathered` 的 active 题目，使名额计数如实。
4. 设 `[program] enabled = true`。可选：`domains` 指定参与轮转的学科；`enforce_admission = true`
   让普通项目里新的研究 workstream 必须对应已立项题目（否则报告 `topic_not_admitted`）。人工
   题目用 `python -m openlabs program submit-card --project <计划项目 project.json> --card card.json`
   提交，与 scout 的卡片一样过立项关口。

每个 tick：有空位、未暂停立项、候选池（proposed）低于 `candidate_pool_low_water`、距上次 scout
超过 `scout_min_interval_hours`、负责人额度充足时，为在研题目最少的学科排一个 `topic_scout`
（worker 档）。卡片按 `openlabs.topic_card.v1` 校验后登记为 proposed；不合格的记为 rejected 并
在 `card_errors` 写明原因。立项审查是 `portfolio_review` 任务（路由原因 `topic_admission`、
lead 档、`exclude_provider` 为出题者模型族）；没有其他模型族可用时任务保持排队并写
`topic_admission_waiting` 事件，不回落。admit 的题目在有研究名额时按立项顺序物化成 campaign，
初始 `research_state.json` 带预注册主终点及其哈希、目标档位、routine 退路和成本预算。tick
报告的 `program` 字段给出候选池、等位题目、本 tick 排的 scout/立项任务和被拒卡片。

立项之后由控制面闭环，决定不再等人确认，每一项都写入 events 与题目台账历史：

- 已立项题目的研究结果须带主终点判定和台账里的预注册哈希。主终点失败、超过
  `max_days_from_admission_to_ready`、用完题目预算（卡片 `cost_estimate.agent_seconds` 与
  `topic_max_agent_seconds` 的较小者），或评审的 `review_outcome` 为 `direction_decision`、
  `retarget_required`、停滞、轮次用尽时，排一个 `direction_decision` 任务（lead 档、空白会话、
  避开该题研究执行者的模型族，技能 `openlabs-direction-decision`）。它在
  `[program.direction_limits]` 内选择一次定点分析、换刊/短文形式或冻结；次数用尽、决定任务
  两次失败或达到 `topic_max_agent_seconds` 时题目冻结。研究者返回的有据冻结直接登记。
- 评审通过的论文离开研究名额进入 ready 队列；队列超过 `max_ready_unsubmitted` 时暂停新立项。
  `auto_handoff = true` 时每篇走下面的发布流水线，交付到管理网站，不指定投稿人；业主审阅后运行
  `python -m openlabs program assign-handler --paper-id <id>`（默认第二作者）。实际投稿、付费
  和署名变更仍由人确认。
- 有 `[runners]` 表时按各模型族剩余额度派活，并为评审与决策保留余量（`[routing]`）；额度
  错误按 `[budget]` 退避，不消耗重试次数。Claude 的子 agent 工具（Task/Agent）只给 lead 档，
  `[runners.<name>] allow_subagents` 可改。

开关与上限只在 `config/openlabs.toml` 的 `[program]` 里配置，编排器不读
`settings.yaml#research_portfolio.autonomy`（那里只记业主的决定及日期）。

### 发布流水线（评审 ready → 交付）

每个 tick 对每篇 ready 论文先运行 `paper-writing program release-status`（只读），再走下一步；
任何一步失败或中断，下个 tick 从实际状态重新判断，每步写 events 和题目台账 `release` 字段
（`stage`、各阶段 `attempts`、`writer_rounds`、`last_error`、`commits`）：

| 阶段 | 调用 | 失败或不满足时 |
|---|---|---|
| 形式修正（确定性） | `zenodo prepare`（重建支撑包身份：回执、版本、DOI、记录标题） | 计次重试 |
| 形式修正（文字） | 轻活档 `format_fix` writer，只改列出的问题，不改数字、表格、结论和标题 | 轮次用尽即停 |
| 差异复核 | `review unified-run --delta-only`（不调编辑和审稿人、不计轮次） | 超出差异规则：题目回 `in_review`，排一次完整 `paper_review` |
| 提交 | 本地 `git commit --only`，只含本论文的登记、`papers/<id>/`、评审记录和台账 | 无身份时等待 |
| 支撑材料发布 | `support-check` → `zenodo release` | 计次重试 |
| 交付 | `program deliver`（无投稿人），随后再提交一次 `delivery` 块 | `handoff_max_attempts` |

黑名单词只作备注，不阻断。改标题、数字、表格或结论段的改动超出差异规则，走完整评审。
用尽 `release_max_attempts` 的论文列在 tick 报告的 `program.release_exhausted` 并写入
`errors`，不再重试；人处理后把台账该题的 `release.status` 改回 `pending` 即从头再判断。

- `auto_release`（默认 false）：为 false 时流水线停在第一次 Zenodo 写入之前，`release.status`
  为 `waiting`、`waiting_for: auto_release_off`；为 true 时还要求
  `settings.yaml#support_publication.standing_production_release_authorization: true` 和
  `ZENODO_ACCESS_TOKEN`，外部写开关只对该子进程设置。
- `[program.git]`：`user_name`、`user_email`（缺省用数据仓库自己的 git 配置，都没有则等待并
  在报告里提示）和提交标题 `message`（字段 `{action} {paper_id} {version} {topic_id}`）。只提交、
  不 push；工作区里与该论文无关的改动保持原样。

### 启用前检查清单

1. 回填台账：`python -m openlabs program backfill`，确认后加 `--write`。
2. 配置六个 `[runners.<name>]`（上文），确认 lead 档两家模型族都有。
3. 环境变量：`ARA_PAPER_MANAGE_API_URL/_KEY`、`ZENODO_ACCESS_TOKEN`（或 `~/.config/ara/zenodo.env`）；
   不要全局设置 `OPENLABS_ENABLE_EXTERNAL_WRITES`。
4. 本机有 `bwrap`（Claude 执行者的文件边界）。
5. 按上文手工验证一次 Claude 执行者。
6. 数据仓库的 git 身份或 `[program.git]`；`paper_writing_command` 在 tick 环境里可执行。
7. 依次打开 `enabled`、`auto_handoff`，确认首篇停在 `auto_release_off` 后再打开 `auto_release`。

## 聚合资源护栏与 systemd user timer

先安装资源 slice；该命令不会启用 factory timer。另行安装结果监听器后，worker 以原子
rename 发布完整收据时会立即触发一次幂等 tick，完成门禁、成果晋升、后继动作和 SQLite
更新；它不依赖三分钟 timer，也不会向正在运行的 Codex TUI 注入文字：

```bash
bin/install-resource-guard
bin/install-completion-watcher
bin/openlabs-resource-guard -- python path/to/heavy_search.py
# 新的交互式 Codex 会话：
bin/openlabs-codex
```

```bash
systemctl --user status openlabs-results.path
journalctl --user -u openlabs-tick.service
```

护栏内存、swap 和 tasks 参数与 OpenMath 对齐；OpenMath 当前没有 CPUQuota，因此 OpenLabs
的 CPU 上限来自本仓库原有 75% CPU 策略。详见 [RESOURCE_GUARD.md](../RESOURCE_GUARD.md)。

结果监听器只负责“已有 worker 完成后的立即入库”。若还需要定时同步项目期望状态、恢复
过期租约和启动尚未运行的排队任务，再启用完整 factory target：

```bash
mkdir -p "$HOME/.config/systemd/user"
cp deploy/systemd/openlabs-factory.target deploy/systemd/openlabs-workers.target \
  deploy/systemd/openlabs-workers.slice \
  deploy/systemd/openlabs-tick.service deploy/systemd/openlabs-tick.timer \
  deploy/systemd/openlabs-results.path \
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
共享工厂中还有其他项目需要继续运行时，加 `--keep-factory`；此时仍会取消并终止目标项目的
已登记 worker，但不会停止 `openlabs-factory.target` 或其他项目的 worker。

每个 Agent attempt 都在 `openlabs-artifacts/attempt-workspaces/` 的私有 campaign 副本中开始。
新 attempt 同时获得独立的 `artifact-stage/`：可演化的小型状态写入私有 campaign，原始数据、
求解器日志、数组、模型、归档和批量输出写入 artifact-stage，并逐项出现在
`result.artifacts` 中。Agent 不得直接写 live `openlabs-artifacts/experiments/` 或 `objects/`。
Codex adapter 使用原生 `danger-full-access`，因此它调起的 shell、Python、证明器、编译器和
包管理器不会再被文件系统沙盒阻断。隔离目录此时是事务约定和默认 cwd，而不是内核强制的
写边界；正式成果仍必须通过结果合同、协议验证、不可变归档和目录交换才能晋升。非 Codex
adapter 仍由 worker 使用 bubblewrap 只开放本 attempt；本机缺少 bubblewrap 时拒绝启动，
不会降级为共享写入。
只有状态为完成、通过文件门禁且所有证据已冻结到 `openlabs-artifacts/result-bundles/` 不可变
归档的节点，才会发布 `objects/sha256/` 对象与 `experiments/.../manifest.json`，并以目录交换
方式把小型 campaign 状态及 `artifact-references/*.json` 提升到正式 data。门禁拒绝超过
5 MiB 的单个新 campaign 文件、artifact-only 格式、超过 1000 个变更文件或 50 MiB 变更总量，
也拒绝 artifact-stage 中未声明、哈希不符、符号链接逃逸或发布后改变的文件。数据库确认入库
前保留原目录作为回滚副本；确认后清理成功 attempt 的临时 payload。取消、超时、失败和门禁
拒绝的 attempt 只留下带原因的隔离 checkpoint。tick 与
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

OpenLabs 不自动投稿或创建期刊事件。论文适配器默认拒绝外部写操作；只有管理员针对一次明确
操作设置 `OPENLABS_ENABLE_EXTERNAL_WRITES=1` 才会解除代码门禁。两个常设例外：已经准备、远端
回读且哈希绑定的 Zenodo 支撑材料（论文 `ready` 门禁授权 `zenodo release`，该命令再次核验
门禁、Git 状态和本地/远端材料后才发布）；以及 `[program] auto_handoff = true` 时把 ready 论文
交付到管理网站。两者都不延伸到投稿、付费或论文发表事实。

## 24 小时部署验收

启用 timer 前先运行 `pytest -q` 和 `ruff check .`。随后用 smoke 或低成本 campaign 做一次
真实 24 小时 soak run，检查：无重复 attempt、无跨 campaign 入库、无超过资源预留/进程保险/
预算的启动、队首大任务不会阻塞可运行小任务、
过期 lease 能恢复或隔离、reviewer 均为 fresh session。单元测试证明状态机边界，soak run
证明目标机器上的 systemd、PATH、Codex profile、凭据和休眠策略确实可连续工作。
