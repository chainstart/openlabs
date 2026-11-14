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
设置 `OPENLABS_ENV_FILES=<文件1>:<文件2>`（`os.pathsep` 分隔）时只读取列出的文件、完全不读上面
三个默认文件（包括 `zenodo.env`），适合隔离的演练或测试环境。配置默认从
`$OPENLABS_WORKSPACE/openlabs/config/openlabs.toml` 读取；`OPENLABS_CONFIG_FILE` 指定另一份
TOML（文件缺失即报错），容器实例就是这样读它自己的设置（见“容器实例”）。
`tick` 和 `bin/openlabs-codex` 在启动研究前还会执行严格网络门禁：依次探测当前进程继承的
代理和持久代理文件。有 `[runners]` 表时，门禁检查表中出现的每一家：Codex 端点和
`api.anthropic.com`（可用 `OPENLABS_AGENT_PREFLIGHT_URL_ANTHROPIC` 覆盖）各发一次不带凭据的
HEAD 请求，选中的代理必须两家都通；Claude 一侧另在本地确认配置的 `claude` 命令在 PATH 上、
`~/.claude/.credentials.json` 存在（不调用模型、不读凭据内容）。没有 runner 表时只查 Codex。若当前进程携带一个新的可用代理，它会原子更新
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
在 `card_errors` 写明原因，随后自动修正一次（`card_repair`）：先按现行校验重验原卡（规则放宽后可能
直接通过，不花模型额度），否则排一个 light 档 `topic_card_repair` 任务带错误清单重交；修正卡仍不合格
才是终态。立项审查是 `portfolio_review` 任务（路由原因 `topic_admission`、
lead 档、`exclude_provider` 为出题者模型族）；没有其他模型族可用时任务保持排队并写
`topic_admission_waiting` 事件，不回落。admit 的题目在有研究名额时按立项顺序物化成 campaign，
初始 `research_state.json` 带预注册主终点及其哈希、目标档位、routine 退路和成本预算。tick
报告的 `program` 字段给出候选池、等位题目、本 tick 排的 scout/立项任务和被拒卡片
（以及 `card_repairs`、`holds_released`、`revisions_scheduled`）。

立项判据（`openlabs.topic_admission_policy.v2`，2026-11-12，技能 `openlabs-topic-admission`）：
routine 档读过最近已有工作后仍有可陈述的增量差别、决定性数据已确认、设计原理上能识别所称效应、
在产线定位内且不在回避清单与许可证黑名单上，即 admit。reject 只用于致命问题（已有工作做过同一比较、
数据拿不到、原理上不可识别且无法修订修复、黑名单许可证、超出纯计算能力）。可修的缺口写成
`admission.conditions`（`description`、`due`：`before_precheck` / `before_decisive_analysis` /
`before_submission`）随 admit 一起下发：写入第一个研究任务说明与 `research_state.json` 的
`admission_conditions`，`before_submission` 的条件进入交付记录，`program assign-handler` 在业主加
`--conditions-met` 确认前拒绝指定投稿人。hold 与关口标 `revisable: true` 的 reject 会自动排一次
`topic_revision` 任务（worker 档），返回带 `revises`、`condition_responses` 的修订卡，关口只复核
这些复开条件；修订卡不再二次修订。人工认定某个 reject 可修时用
`python -m openlabs program mark-revisable --topic-id <id> --reason <理由>`。题目台账升为
`openlabs.topic_ledger.v2`（v1 照常读取，下次写入时升级）。

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

### 研究产线

选题按研究产线组织（2026-11-12 方向）。方向文件在数据仓库 `registry/research-lines.yaml`
（`[program].research_lines_path`，摘要 `research-lines.md`）：每条产线的定位、流水线骨架、最低验证
要求、每篇最小新意、目标期刊及费用证据等级、许可证白名单/黑名单、环境状态与回避方向。

- 计划项目的 `project.json` 带 `"research_line": "<id>"`；一个学科可有多条产线，各自出题、计数。
  学科只决定任务落在哪个 lab（技能与协议），产线自带环境，不依赖 lab 的 `uv sync`（physics、quant
  的 `research-program` 协议因此 `runtime_setup_ids: []`）。
- `[program].research_lines` 非空时只轮转这些产线的项目（每条产线一个 scout、间隔与在研计数按产线），
  没有产线的旧学科项目不再出题，但已有的立项审查和研究 campaign 照常进行。为空时仍按学科轮转。
- 产线卡片多三个字段：`feasibility_precheck`（低成本决定性预检、数值通过标准、`on_failure: freeze`）、
  `license_check`、`fee_check`（每本 routine 期刊的版面费/彩图费/投稿费与证据等级，至少一本已核实的
  免费途径）。例：`packages/contracts/examples/research-program/topic-card.research-line.example.json`。
- 立项后第一项研究任务就是预检；不通过时研究者返回 `freeze_reason_class: feasibility_precheck_failed`。
- 产线的 `environment.status` 不是 `ready` 时，立项关口的 admit 会被控制面改为 hold，复开条件类型
  `line_environment_ready`，关口的完整决定保留在立项记录里；方向文件把该产线标为 `ready` 后，控制面
  直接按原决定立项（`hold_released_admitted`），不需要新卡片。关口自己给出、只有
  `line_environment_ready` 一个条件的 hold 则回到 proposed 重新送关口（`hold_released_for_review`）；
  还有其他条件的 hold 走修订卡。每个题目只放行一次。
- 产线级原因冻结的题目可自动重开（`orchestrator/src/openlabs/reopen.py`）：题目台账的 `auto_reopen.when`
  列出可机械求值的条件，全部成立才算满足——`control_receipt`（产线对照回执 JSON 的点路径字段比较，
  `summary.` 读回执 `results_dir` 下的 summary.json）和 `line_capability`（`registry/research-lines.yaml`
  里该产线条目的某个键为真）。条件来自负责人冻结包的可选 `reopen_when`，或对旧冻结题目用
  `python -m openlabs program reopen-register --topic-id T --when-file F.json --by NAME [--note ...]`
  登记（只写题目台账，不碰数据库）；`program reopen-check` 只读地显示当前求值。控制面每轮检查：条件全成立、
  有空研究槽、campaign 仍有 Agent 预算、题目在负责人模式、自动重开次数未达 `[program].auto_reopen_max`
  （默认 1，0 关闭）时，题目 `frozen -> active`（`auto_reopen_conditions_met`），campaign 解冻，给原负责人会话
  派一个 `owner_reopened` 坐席并写明哪些条件变了。预注册、主终点、停止规则和预算都不变；再次冻结时若没有新的
  `reopen_when`，旧条件清空，不会因同一事实反复重开。
- 现有实例迁移：`python -m openlabs program init-instance --instance-dir <dir> --set-research-lines`
  先看 dry-run，再加 `--write`。它只新增缺少的产线项目，并在实例 TOML 的 `[program]` 里写入
  `research_lines`（其余键与注释不动，旧文件留 `.bak`），不改题目台账。回滚：恢复 `.bak`。

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
4. 本机有 `bwrap` 且能创建用户命名空间（Claude 执行者的文件边界，也是复现重放的沙箱）：
   `bwrap --die-with-parent --bind / / -- true` 应返回 0；报 `No permissions to create new
   namespace` 的环境（例如当前容器）不能运行 Claude 执行者。
5. 按上文手工验证一次 Claude 执行者。
6. 数据仓库的 git 身份或 `[program.git]`；`paper_writing_command` 在 tick 环境里可执行。
7. 依次打开 `enabled`、`auto_handoff`，确认首篇停在 `auto_release_off` 后再打开 `auto_release`。

## 可复用资产库

研究计划启用后可再打开资产库（`config/openlabs.toml` 的 `[program.assets]`，两个开关默认都关，
关闭时与上面完全一致）。索引在数据仓库 `[program] asset_index_path`（默认
`registry/reusable-assets.json`），本体在 `[program.assets] root`（默认 `assets/<kind>/<id>/`，
归档移到 `assets/archive/`，从不删除）。每项资产一行摘要：id、kind（`data_loader`、`analysis`、
`figure`、`pipeline`、`lesson`、`negative_result`）、标题、一句话说明、学科、数据源（与题目卡片
同一口径的 DOI/URL）、使用次数和最后验证时间。

- `enabled = true`：scout、立项、方向性决定的输入包带 `reusable_assets_summary`（只含 active，
  按学科和数据源相关性排序，最多 `summary_limit` 条、`summary_max_chars` 字符）；研究任务得到
  `reusable-asset-summary` 和卡片所引资产本体的只读 read resource。卡片 `reusable_assets[]`
  引用不存在或已归档的资产时卡片被拒；引用现成 pipeline/data_loader 的事实写进立项包的
  `asset_reuse`。结果包里的 `assets_used[]` 累加使用次数，`assets_broken[]` 连续
  `broken_reports_to_archive` 次即归档。每 `maintenance_interval_hours` 检查一次：注册后
  `unused_archive_days` 天从未使用的工具、被连续报告损坏的资产、超过 `max_lessons` 的最久未用
  lesson 归档。
- `retrospective_enabled = true`：题目进入 ready_queue 或 frozen 时排一个 `topic_retrospective`
  （light 档、空白会话、技能 `openlabs-asset-retrospective`，每题每个终态一次；开启前已到终态的
  题目不补排）。工具类提案的文件须在该题工作区内（或是本次结果的哈希绑定产物），并附智能体
  自己在资源护栏内跑过的最小验证命令的回执；编排器只核对回执哈希、命令和 `exit_code == 0`，
  不执行命令。冻结题目至少登记一条 `negative_result`；连续两次没有时，按台账事实登记一条。

命令（seed、list、show 只读，不建运行目录）：

```bash
python -m openlabs program assets seed --dry-run --output drafts.json  # 扫描 seed_paths，只出草稿
python -m openlabs program assets register drafts.json --by <name>    # 补全草稿与验证回执后登记
python -m openlabs program assets list [--all]
python -m openlabs program assets show <asset_id>
python -m openlabs program assets archive <asset_id> --reason <text>
python -m openlabs program assets cost   # 引用资产与否的题目：任务数、token、时长对比
```

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

## 容器实例

容器里的新自动研究用一个独立实例：自己的运行库、自己的设置文件、自己的项目，与 WSL 旧实例
共用数据仓库和制品库。三个变量选择实例（都不设时一切如前）：`OPENLABS_INSTANCE`（实例名）、
`OPENLABS_DATABASE_ROOT`（运行库目录，含它自己的 job/result inbox）、`OPENLABS_CONFIG_FILE`。
前两个必须同时设置，且运行库不能是默认的 `openlabs-database`。

初始化（默认只打印将要创建的内容，`--write` 才写；可重复执行，已有文件从不覆盖）：

```bash
cd /workspace/openlabs/openlabs
PYTHONPATH=orchestrator/src python3 -m openlabs program init-instance            # 预览
PYTHONPATH=orchestrator/src python3 -m openlabs program init-instance --write    # 创建
```

默认实例名 `cc-sg`、目录 `/workspace/openlabs/openlabs-instances/cc-sg/`：`database/`、
`openlabs.toml`（由仓库 TOML 加上实例设置生成，仓库那份不改）、`instance.env`、`state/`；数据
仓库里是五个学科（ai、biology、materials、physics、quant；数学不建）的计划项目
`workspaces/<domain>/instances/cc-sg/projects/`，以及空的 `registry/instances/cc-sg/topic-ledger.json`
和 `reusable-assets.json`。改预设：`--preset full --update-config --write`（旧文件留 `.bak`）。

| 开关 | observe（默认） | full |
| --- | --- | --- |
| `[program] enabled`、六个 `[runners]`（额度路由）、`enforce_admission` | 开 | 开 |
| `[program.assets] enabled`（先查资产库） | 关 | 开 |
| `[program.assets] retrospective_enabled`（沉淀） | 关 | 开 |
| `[program] auto_handoff`、`auto_release` | 关 | 开 |

两档都是 `max_active_topics = 5`、`max_parallel_agents = 3`、`compute_locations` 不含 `wsl_math`，
并带有下文“并行度与额度利用”的推荐值。
full 还需要 `--paper-writing-command`、`[program.git]` 身份（`--git-user-name/--git-user-email`）
和管理网站凭据，见“发布流水线”。

运行（容器里没有 systemd；整个循环在一个长驻资源护栏里，单次 tick 不能单独包护栏）：

```bash
bin/openlabs-container-loop start            # 后台启动
bin/openlabs-container-loop status           # 是否在跑、最近一次 tick
bin/openlabs-container-loop stop             # 跑完当前 tick 后退出；在跑的智能体随护栏结束，重启后重试
bin/openlabs-container-loop stop --drain     # 同上，但先等在跑的 worker 结束
bin/openlabs-container-loop cli -- status    # 以本实例身份执行任意 python -m openlabs 子命令
```

每次 tick 的报告追加到 `state/ticks.jsonl`，循环日志在 `state/loop.log`；tick 成功后有结果回执时提前唤醒
（同一批没被消费的回执只提前一次）。tick 非 0 退出（如 69 = 智能体网络预检失败）时不因回执提前，
而是指数退避：`OPENLABS_LOOP_BACKOFF_BASE_SECONDS`（30）起翻倍、上限 `OPENLABS_LOOP_BACKOFF_MAX_SECONDS`
（900），成功一轮复位，退避中仍响应 stop/--drain。`loop.log`、`tick.err`、`ticks.jsonl` 超过
`OPENLABS_LOOP_LOG_MAX_BYTES`（16 MiB）时轮转为 `*.1`。`OPENLABS_LOOP_AGENT_PROXY=http://HOST:PORT`
（默认不设 = 沿用启动者的代理环境）让 `run`/`cli` 显式使用该代理入口，预检和它拉起的 worker 都继承。
间隔等见脚本头部（`OPENLABS_LOOP_INTERVAL_SECONDS` 默认 180）。在容器环境文件里加
`OPENLABS_REQUIRE_INSTANCE=1` 后，没有选实例的 `python -m openlabs tick` 会被拒绝。

与 WSL 旧实例并存的边界：

- 项目：旧实例只扫 `workspaces/*/projects/*` 与 `workspaces/*/production/*`，看不到
  `instances/` 下的项目；新实例只扫自己的 `instances/<name>/projects/`，也不接旧的数学生产计划。
- 运行库、锁、事件、inbox、attempt 工作区（`openlabs-artifacts/instances/<name>/`）、
  program-control 各自独立；结果包、实验目录和内容寻址对象按 campaign/attempt 编号区分，共用无冲突。
  回执归档 `ledger/receipts/` 共用（文件名含任务与 attempt 编号）。
- 共用且需注意的：GPU 锁（本来就是两边共用来防冲突的）、ailab 队列（桥接最多 8 个并发、按
  CPU/内存准入，但不分实例、不限排队长度）、数据仓库的 Git 提交（两边同时提交时一边会因
  `index.lock` 失败后重试）。
- 新实例不认识旧实例的 13 个在研项目，旧实例跑完它们；不要把新实例的设置写进仓库 TOML。

### 并行度与额度利用

仓库 TOML 的默认值保持原行为（单个选题任务、静态并行上限、按余量选 provider）；两档预设都给出
下面的推荐值，已有实例按需把新键加进自己的 `openlabs.toml`（只加新键，下一轮 tick 生效）：

| 键 | 默认 | 推荐 | 含义 |
| --- | --- | --- | --- |
| `[program] max_concurrent_scouts` | 1 | 学科数（5） | 同时在跑的选题任务，每个学科至多一个；>1 时最小间隔按学科计 |
| `[program] scout_expected_cards` | 2.0 | 2.0 | 一个选题任务预期登记的卡片数；跑完三个后改用本实例的实测均值 |
| `[program] max_admissions_per_domain` | 1 | 2 | 一个学科同时审的立项批次（不同批次、不同出题模型族可并行） |
| `[program] max_concurrent_admissions` | 0（不限） | 0 | 全部学科同时审的立项任务上限 |
| `[routing] utilization_target` | 0（关） | 0.9 | 大于 0 即开启"按相对充裕度分配 + 吞吐监督"；数值本身不再是上限（上限见下文"额度上限与配速"） |
| `[routing] stale_refresh_minutes` | 未设 | 10 | 过期的 Codex 读数多久免费重读一次会话文件（Claude 探测仍按 `probe_idle_minutes`） |
| `[routing] stale_estimate_hours` | 0（关） | 48 | 这么久以内的过期读数做保守外推（上次读数 + 窗口平均速度 × 经过时间 + 本实例在该 provider 的智能体时长 × `estimate_fraction_per_agent_hour`），不再把该 provider 限为 1 个任务 |
| `[budget] adaptive_parallel` | false | true | 每轮按可运行任务、实测负载和额度配速调整并行上限，每轮最多变 `adaptive_step`（2）；`max_parallel_agents` 仍是硬顶 |
| `[budget] host_utilization_target` | 0.8 | 0.8 | 容器实测 CPU（cgroup，按上一轮以来）与内存（不含页缓存）的目标；达到即不再加并行 |
| `[budget] ailab_utilization_target` | 0.9 | 0.9 | ailab 已声明占用的目标，只用于报告和给智能体的指引 |

怎么理解：

- 相对充裕度 = （该类任务最后一天的上限 − 已用）÷ 窗口剩余时间占窗口的比例。大于 1 表示按平均速度用不完、
  应该多用；小于 1 表示要省着用。一个 runner 取它所有约束窗口里最小的（Claude 的 5 小时、每周、
  Fable 专属窗口都算），所以 5 小时窗口快满时会先被让开，撞到限额后已有的退避照常生效。
- 打开 `utilization_target` 后，普通任务按相对充裕度的比例分给两家：没有在跑任务时给最充裕的一家，
  它的在跑数超过自己份额后下一个任务给另一家，临近重置而剩余多的一家份额更大。评审、决策的
  独立性（与产出方不同模型族）、保留线和 Fable 的偏好不变。
- 原来的"超速"（按平均速度会在重置前用到 100% 就停普通任务）已并入下面的配速线，不再单独判断。
- 自适应上限：有可运行任务、某一家按当前速度到重置时会低于目标、容器实测负载低于目标减 0.1 时
  上调；负载达到目标或所有可用的 provider 都超出配速时每轮降 1；没有可运行任务时保持不动。
  智能体进程大多在等模型响应，CPU 空闲本身不会让上限越过额度配速和硬顶。

观察：打开 `adaptive_parallel` 或 `utilization_target` 后，每轮报告里多出 `parallel_limit`（本轮上限、上一轮、硬顶、`limited_by` 与原因）、`host_usage`、
`ailab`（共享队列只读统计）、`balance`（每一项的当前值 / 目标、是否低于目标、被什么限制：
`topic_slots` 名额、`candidate_pool` 候选池、`admission_pass_rate` 立项通过率、`quota_pacing`
额度配速、`hard_ceiling` 硬顶、`demand` 没有可运行任务等），`provider_quota` 里每家的
`abundance` 和各窗口的 `window_pace`。随时可以只读地看汇总：

```bash
bin/openlabs-container-loop cli -- program utilization            # --history N、--no-gpu
```

它列出在跑/排队任务按档位与 provider 的分布、各窗口已用比例、相对充裕度、按当前速度到重置时
的预计用量（对照目标）、容器 CPU/内存/GPU、ailab 占用（对照 0.9）和最近几轮的上限及原因；
运行库以只读方式打开。

### 额度上限与配速（所有者 2026-11-14）

两家提供方的每个额度窗口（Claude 的 5 小时、每周、Fable 专属窗口，Codex 的每周窗口）都按同一规则：

- **上限**：普通任务最多用到 `ordinary_ceiling`（80%）；所有自动任务（含评审、决策）最多用到
  `hard_ceiling`（90%），这是硬上限。
- **配速**：上限只在窗口最后一天才可能达到。窗口已过比例为 x 时，某类任务允许的累计用量 =
  `min(上限, max(上限 × pace(x), pace_lead))`。`pace` 是 `pace_curve` 给出的分段线性曲线，默认
  "前快后慢"：七日窗口第 1–6 天结束时系数为 0.3125、0.525、0.6875、0.8125、0.9125、1.0，即普通任务
  约 25%、42%、55%、65%、73%、80%，评审/决策按同一系数乘 90%。`pace_lead`（5 个百分点）是起步量，
  只让刚重置的窗口能开工，不会把已高于它的配速线再往上抬，所以重置前两天允许值不超过上限的 0.9125 倍，
  最后一段只能在最后一天用掉。短于 `pace_min_window_hours`（48 小时）的窗口（5 小时窗口）不配速，只用上限。
- **派活**：某提供方的某个窗口达到某类任务当前允许值后，该类任务不再派给它（`reason` 为 `pace` 表示
  配速线挡住、随时间上移后恢复；`ceiling` 表示到了最后一天的上限、只能等重置）；达到硬上限允许值后
  该提供方任何自动任务都不派。两家都不可用时循环照常每轮检查但不启动任务，排队任务保持排队，
  每个任务每次尝试只记一条 `routing_deferred`，暂停与恢复各记一条 `quota_paused`/`quota_resumed` 事件，
  不会生成新的 replan 或决策任务。tick 报告的 `quota_pause` 和 `program utilization` 的 `quota_pause`
  写明哪些类别暂停、原因和预计恢复时间（如"普通任务因额度配速暂停（pace），预计 … 恢复"）。
- **读数过期**：过期但窗口未重置的读数是用量下限，已达允许值的照样挡住；低于允许值的按"未知"处理
  （每家只放 1 个任务）。可外推的过期读数（`stale_estimate_hours`）照旧外推。
- **Fable**：原有更严的保护保留，与新规则取较严者：Fable 依赖的窗口上 `lead_decision_reserve` 只留给决策，
  Fable 自身的评审和普通任务到 `lead_review_ceiling` 为止；Fable 的决策也受 90% 配速线约束。

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `[routing] ordinary_ceiling` | 0.8 | 普通任务最后一天的上限 |
| `[routing] hard_ceiling` | 0.9 | 所有自动任务的硬上限 |
| `[routing] pace_curve` | 见上 | `[[已过比例, 系数], ...]`：比例从 0 起严格递增，系数在 [0,1] 内不减、末点为 1，否则配置报错。纯线性（第 6 天末到 1）写 `[[0, 0], [0.8571, 1]]`；`[[0, 1]]` 关闭配速 |
| `[routing] pace_lead` | 0.05 | 起步量（绝对值） |
| `[routing] pace_min_window_hours` | 48 | 短于此长度的窗口不配速 |
| `[routing] override_max_ceiling` | 0.99 | 人工覆盖可用的最高比例（只能调低，永不到 100%，避免碰付费余额） |

旧键 `review_reserve` 已删除（写了也不再生效）；`utilization_target` 只作开关。

**人工覆盖**（存在运行库 meta 里，带过期时间，过期后下一轮 tick 自动删除并记 `quota_override_expired`）：

```bash
bin/openlabs-container-loop cli -- program quota-override --provider openai-codex \
    --until 2026-11-21T00:00Z --ceiling 0.97 --reason "重置前用完"   # 默认 ceiling = hard_ceiling
bin/openlabs-container-loop cli -- program quota-override --list
bin/openlabs-container-loop cli -- program quota-override --provider openai-codex --revoke
```

覆盖期间该提供方所有类别不配速、统一用到覆盖上限为止（Fable 自身的保护仍在），达到即停；tick 报告的
`quota_pause.overrides` 和 `provider_quota.<provider>.override` 显示当前覆盖。人工入队的单个任务可以加
`enqueue ... --quota-override --quota-override-reason "..."`：它不受配速和类别上限约束（也不受负责人额度不足时
对立项/文献扫描的暂停），但仍以 `override_max_ceiling` 为限，限流退避中的提供方仍跳过。不带此标记的人工
入队任务与自动任务同样受配速约束。

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
