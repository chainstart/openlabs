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

### 经代理的大体量下载只在闲时（2026-11-18）

用户 2026-11-18：“通过代理节点下载较大的数据时候，在闲时进行，是2：00-14：00这个时段，这个规则既落到
整个容器里，也特别加到产线上”。经代理节点（下载桥 `--route proxy`，或明知全部靠代理兜底的批量取数）
下载较大的数据只在北京时间 02:00–14:00 进行；较大 = 单个文件 ≥ 200 MB 或同一批合计 ≥ 1 GB；小文件与
`--route auto`（先走直连）不受限。时段外不提交大体量代理下载，安排到窗口开始，期间做不依赖该数据的工作；
不得拆小绕过；跨过 14:00 未完成的批量下载暂停补提交，下个窗口续传。走代理本身仍需直连失败的证据或用户
明确批准，本条只管时段。

- 配置：`[factory]` 的 `proxy_download_window = ["02:00", "14:00"]`、`proxy_download_timezone =
  "Asia/Shanghai"`、`proxy_download_large_file_mib = 200`、`proxy_download_large_batch_mib = 1024`、
  `proxy_download_codex_hook = false`（实现：`orchestrator/src/openlabs/download_window.py`）。
- 负责人简报的 Hard limits 第 1 条写入这条规则（数值读配置）；`AGENTS.md`、出题技能同步。
- 硬保险：lab runner 启动的 Claude Code 会话在生成的 `.claude/openlabs-settings.json` 里带 PreToolUse
  钩子（匹配 Bash），时段外拒绝不带 `PROXY_SMALL_OK=1` 声明的 `download-submit … --route proxy`。
  Codex 0.166 支持 PreToolUse，但尚未在产线会话里实测；`hooks.json` 若被 Codex 拒绝会连带丢失结果门禁的
  Stop 钩子（引擎随即 fail closed），所以 Codex 的同一钩子默认关闭，用一个有界任务实测后再置
  `proxy_download_codex_hook = true`。钩子只看得到命令文本：脚本内部调用桥的批量下载必须自己判断时段
  （`python -m openlabs.download_window status`，窗口内退出码 0、窗口外 3）。
- 最可靠的落点是 WSL 侧下载桥本身：建议桥在接收 `route=proxy` 任务时按同一窗口与体量界线排队
  （窗口外只入队、到 02:00 再开始，14:00 暂停未完成的分片），这样任何会话、脚本都绕不过去；这需要 WSL 侧改桥。

### 模型分工：哪类任务用哪一档（2026-11-18）

三档 runner 各司其职（用户 2026-11-18：“opus和sol各自负责这三个功能，fable和astra只做最最重要的
关键节点”）：

| 档位 | Claude / GPT | 做什么 |
| --- | --- | --- |
| lead | Claude Fable 5.2 / gpt-6.2-astra | 只做关键节点：方向决策（`direction_decision`）、组合规划、失败诊断、非负责人流程里的统一评审承载任务；交付前正式评审的审稿人由数据仓库 `registry/settings.yaml#review.roles` 单独配置 |
| worker | Claude Opus 5.5 / gpt-6.2-sol | 负责人坐席、实验与写作，以及立项评审（`portfolio_review:topic_admission`）、负责人稿件的重算式复审（`paper_review:owner_recompute_review`）、重规划（`replan`）、候选成熟（`candidate_maturation`）、其他组合评审、改投时的修订与就绪评估、负责人流程与发布流水线里的统一评审承载任务（`paper_review:owner_review`、`paper_review:release_full_review`：它们只运行 `paper-writing review unified-run` 并做一次预注册原文核对，真正的编辑与审稿人由 settings.yaml 决定） |
| light | Claude Haiku 5.5 / gpt-6-luna | 修卡、文献筛选、数据下载、格式修正、复盘入库 |

**单一的分工表**是 `orchestrator/src/openlabs/config.py` 的 `DEFAULT_TASK_TIERS`：键是任务类型，可以细到
`任务类型:routing_reason`（细分键优先于类型键），值是档位。所有派发点写入的 runner 名都由这张表
（`config.dispatch_runner`）给出，路由器再按同一张表（`budget.requested_tier`）选档，所以两处不会不一致；
表里没有的任务类型才沿用它的 runner 名（`frontier/balanced/cheap`）或角色。

**调整**：在实例配置里写 `[routing.task_tiers]`，只写要改的条目，例如

```toml
[routing.task_tiers]
"portfolio_review:topic_admission" = "lead"   # 立项评审升回 Fable / astra
replan = "worker"
```

档位只能是 `lead`/`worker`/`light`（旧名 `frontier`/`balanced`/`cheap` 会被换算）；`类型:原因` 键的
类型和原因都必须是代码已知的（`config.KNOWN_ROUTING_REASONS`），写错会在加载配置时报错并列出可选值；
单独的任务类型键可以是自定义类型。下一轮 tick 生效，已排队的任务在被领取时按新表选档。
`program utilization` 的 `division_of_labour` 段列出当前每档的两家模型、各档任务，以及实例相对代码默认
改了哪些条目（`overrides`）；`argv_model_mismatch` 列出 `[runners.<name>].model` 与
`OPENLABS_AGENT_COMMAND_<NAME>_JSON` 里 `-m/--model` 不一致的 runner——前者是路由、独立性比较和成本核算
的依据，后者才是实际启动的模型，升级模型时两处要一起改。

**独立性在同档内成立**：评审与决策类任务排除作者的模型族，worker 档的评审因此落到另一家的 worker
（sol 写的由 Opus 审，Opus 写的由 sol 审）。另一家因额度不可用时回退到“同族不同模型”，先试请求档位，再
往上、最后才往下，并跳过作者自己的模型：作者是 sol 时回退到 astra，作者是 Opus 时回退到 Fable；路由事件带
`independence: same_family_different_model` 与 `tier_changed_for_independence`。立项评审的作者是出题的
scout：修卡任务（light 档）只改格式，修好的卡片保留原 scout 为作者（`proposer_task_id`、
`proposer_provider`），评审不会因为修卡换了模型而落到与出题方相同的模型上；同一批卡片的作者模型都写进
评审包的 `producer_models`。

**额度类别**：降到 worker 档的决策类任务（立项评审等，`decision_task_types` 里的类型）按 review 类
计额度：90% 硬上限并配速，不得动用 Fable 在共享窗口上的 `lead_decision_reserve`；若因独立性回退落到
Fable，再受 `lead_review_ceiling`。仍在 lead 档的方向决策照旧按 decision 类。立项评审不再需要 lead，
所以 lead 额度紧张时 `lead_shortage_paused` 不再暂停出题与立项（立项评审改回 lead 时自动恢复暂停）。

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

### 空转防护（2026-11-16）

起因：天文线候选队列抽空后，`topic_scout` 每约 8 分钟抽一次空队列，两天约 250 次零产出。现有四道防护，
都只读台账/队列/数据库、不调用模型，状态写在 meta 与 events 里：

- **出题空抽退避**（`program_flow.record_scout_outcomes` / `scout_supply_blocks`）。一个 scout 结束后，
  它交回的卡片在台账里没有一张不是 rejected，即为空抽（原因 `candidate_queue_exhausted`、`no_cards`
  或 `cards_rejected`）。每条产线（无产线时按学科）记一个“供给指纹”：产线在 `research-lines.yaml` 里的条目
  （模板、能力声明如带斑配置）、各 `candidate_queue` 文件的哈希、held 条目的放行情况、该产线台账题目的
  编号与状态。指纹不变时连续空抽第 n 次后，下一次 scout 等 `[program].scout_empty_backoff_hours[n-1]`
  （默认 1→6→24 小时，末值重复）；连续 `scout_exhausted_after`（默认 4，0 关闭）次后该线标为
  `candidates_exhausted`：不再出题，并在 tick 报告的 `production_blocked` 和 `program.scout_supply_blocked`
  写明空抽次数、最后一次 scout 的摘要和解除条件。指纹一变（刷新队列、登记新能力、台账题目变化）下一轮立即
  解除（事件 `topic_scout_backoff_released`），有产出的 scout 也会清零。人工解除：改动该产线在
  `research-lines.yaml` 的条目或队列文件即可。`program.scout_blocked` 相应为 `scout_empty_backoff` /
  `candidates_exhausted`。
- **远程作业重复 yield**（`remote_wait.rewait_block`）。agent yield 的作业在两个队列里都不存在
  （`remote_job_missing`），或全部已终态且本任务链（沿 `parent_task_id` 向上，含中间的 replan/换座）早先的
  等待已经因它们释放过（`remote_jobs_already_released`），后继直接建为 `needs_human`，不再停车→立即释放→
  再启动。首次 yield 在刚结束的作业上仍停车一次，让 agent 看到结果。释放时：开始等待时就不存在的作业转
  `needs_human`；开始时存在、现在目录不见了（如挂载丢失）的作业不算完成，继续等到期限。释放与等待记录在
  同一事务提交；一条等待读取出错只记入 `remote_waits.errors`，不挡其他等待。`auto_continue = false` 或
  协议自管续接的 campaign 不再停车。
- **通用无进展保险**（`spin_guard.py`，所有非负责人任务类型）。同一 campaign 最近连续结束的任务若都没有
  进展——`needs_replan`/`needs_human`/`failed`/`quarantined`、yield 在已出现过的作业上、或成功但没有新的
  非输入类产物哈希、卡片或论文候选（决定类任务 `direction_decision`、`portfolio_review`、评审等成功即算
  进展）——连续 `[factory].no_progress_backoff_after`（默认 4）次起，该 campaign 排队的任务按
  `no_progress_backoff_minutes`（默认 60→240→1440 分钟）推迟（事件 `no_progress_backoff`），到
  `no_progress_escalate_after`（默认 8）次转 `needs_human`（`no_progress_circuit`，事件
  `no_progress_circuit_open`），连续产线的补种也随之停下等人。摘要、时间戳、任务编号的变化不算进展。负责人
  坐席仍用 `[program.owner].no_progress_seats` 的方向决策熔断（2026-11-17 加固：只认实质产出——新作业、
  新的非日志类产物、研究文件变化、阶段推进、awaiting_remote/ready_for_review/frozen；OWNER_LOG、
  OWNER_HANDOVER、research_state.json 与额度/utilization/检查点回执不算；短于 `short_seat_seconds`
  的坐席不靠文件变化计进展；连续第 2 个无进展坐席起下一坐席按 `no_progress_backoff_minutes`
  （10→30→120 分钟）推迟），tick 的 `idle_metrics` 也把无进展的负责人坐席计入 `zero_output`；
  `program utilization` 的 `providers.<p>.dispatch_allowed` 给出控制面按任务类别能否派发（`signal`
  只是配速预测，不是停工指令）；scout 用上面的空抽退避。已有的 replan 退避
  （30 分钟翻倍、6 小时封顶）保留，现在由本保险在第 8 次封住。
- **同状态停派与统一报告**（2026-11-20，W3）。负责人坐席每次结束都会记录状态签名（`spin_guard.state_signature`）。签名字段为：phase、状态包 status、研究文件摘要、job id、review stage/round、写作者记录、台账状态。签名不变且无实质产出时计数加 1，方向决策和评审请求都不清零。
  - 连续 `[factory].stall_signature_repeats` 次（默认 6）：安排一次带诊断的方向决策，trigger 为 `owner_stalled`。诊断包含签名字段、最近几次坐席的 next_step 和写作计划。
  - 决策后仍不变 `stall_seats_after_decision` 次（默认 3）：不再派坐席，补种也跳过。owner_state 记 `stall.stopped`，台账写备注 `owner_stalled`。
  - 解除：规范工作区的研究文件或台账状态一有变化就自动解除，事件 `owner_stall_cleared`。
  - tick 报告的 `program.stuck_topics` 汇总四道防护，每行注明 `source`：`same_state`、`owner_no_progress`、`campaign_no_progress`、`replan_backoff`。
  - `program.topics_without_next_step` 列出所有非终态台账课题中没有可执行下一步的，原因包括 campaign 暂停、campaign 缺失、负责人停派、交付流水线 exhausted、无活任务。
  - 写作者切换（同日修复）：简报与切换共用 `owner.writing_plan`。有评审历史或已在写的课题明确由负责人自己写，记 `writing.status = owner`，并写台账备注 `writing_owner`。写作者与负责人是同一 runner 时照旧由负责人写。
- **台账对账**（2026-11-20）：`python3 -m openlabs program reconcile` 默认只读，列出每个课题或任务记录的现状态、建议状态和依据。加 `--apply` 才通过 `transition_topic`、`freeze_topic`、`mark_topic_delivered`、`close_needs_human` 写入，规则见 `program_reconcile.py`。停滞判据为 `[program].reconcile_stale_days`（默认 5 天）。
- **人工重排被隔离的任务**（2026-11-20）：`python3 -m openlabs program requeue TASK_ID --reason "<修好了什么>" [--by NAME]`。只接受 `quarantined` 的任务（`needs_human` 要另加 `--allow-needs-human`），所属 campaign 须为 active；任务回到 `queued`，多给一次 attempt，写一条 `manual_requeue` 事件（谁、为什么、原状态与次数）。用于基础设施分流不会自动重试的失败，例如评审因配置错误三次失败被隔离。tick 报告 `program.topics_without_next_step` 里，若课题最新任务是这类被隔离/needs_human 的任务，会附 `blocked_task` 和 `suggested_command`。
- **同刊复审关口**。同一目标刊第 2 轮起，完整评审启动前须提交 `--response RESPONSE.json`。
  文件用 `decision_sha256` 绑定上一轮计数决定，`items` 逐条填写 `item` 原文、
  `status`（`addressed` 或 `unaddressed`）、`explanation` 和 `evidence`。已处理项填写仓库相对
  路径及行号（如 `papers/ID/manuscript/appendix.tex:42`）、`sha256:<哈希>` 或 `job:<作业号>`。
  未处理项说明原因。要求新计算、新数据或新分析的项须引用与上一轮相比新增的已登记支撑数据字节，
  可填其 SHA-256，或填写登记 JSON 结果顶层的 `job_id`。零必改项时使用空数组。
- 关口比较展开的正文与附录、评审图件哈希及登记的支撑数据文件哈希。默认有效词差异至少
  80 个，或有新图件、支撑数据字节。同内容重命名和仅改打包版本不算新证据。旧决定缺少逐文件
  哈希时，可用上一轮的支撑材料总摘要核实新增文件。复审默认在上一轮决定完成 3 小时后启动。
  在数据仓库 `registry/settings.yaml#review` 用 `round_min_changed_words`、`round_cooldown_hours`
  调整阈值。人工可在同一位置的 `round_cooldown_overrides` 加入带 `paper_id`、`target_journal`、
  `decision_sha256`、`actor` 和 `reason` 的单轮授权，实际使用会写入决定记录。
- 被拦时返回 `review_round_blocked`，`round_guard` 列出缺项和最早重试时间。负责人和交付承载任务
  应记录该结果，需要时交回写作或分析。仅剩冷却期时，负责人的下一坐席延至 `retry_at`，
  结束当前尝试，避免循环调用。
  合格的免轮次差异复核沿用原流程。轮次上限、独立评审和投稿人工确认继续生效。
- **评审面板的加载校验**（2026-11-20）：两位审稿人模型必须不同，这条规则在加载 `settings.yaml` 时就检查（`review_flow.check_referee_models`，与 `unified-run` 运行时同一个函数），改错面板会立刻报错，不会等到每次评审启动才失败。
- **审稿人的只读运行环境**（2026-11-20）：Codex 审稿人原用 `-s read-only`，它依赖 bubblewrap；容器的 seccomp
  禁止用户命名空间时，审稿人的每条命令都在启动前失败（"bwrap: No permissions to create new namespace"），
  打不开登记的复现文件。`review_launcher.run_role` 对全部 Codex 评审角色按可执行文件在进程内探测一次 `codex sandbox -- true`：能起就照旧用原生只读沙箱；
  起不来则改用“只读副本模式”（`paper_writing/review_sandbox.py`）：把登记文件复制到工作区之外的新目录
  （`OPENLABS_REVIEW_COPY_ROOT` / `OPENLABS_SCRATCH_DIR` / 系统临时目录），去掉全部写权限，审稿人以
  `danger-full-access` 在副本里运行，提示词里的路径改指副本，只允许写单独的输出目录。运行前后对副本逐文件
  哈希、对副本重算登记的 `support_sources_sha256`、运行后复核原文件；有任何改动则本次评审无效（`LaunchError`）。
  回执写 `sandbox_mode: readonly-copy`、`isolation: readonly_copy_danger_full_access` 和 `readonly_copy`
  摘要，完整清单在角色目录的 `readonly-copy.json`；副本用完即弃。容器换成允许用户命名空间的 seccomp 后探测
  成功，自动回到原生沙箱。`OPENLABS_REVIEW_SANDBOX=native|readonly_copy` 可强制模式。编辑、决定信和正式书目核验同样探测；内联核验包保持逐字节可复核，图片附件从校验过的副本传入。
  `paper-writing review runtime-preflight --paper-id P [--attachment ZIP] [--verifier CMD] [--out DIR]`
  按同一方式起一个审稿人进程，只核对登记文件与附件 `SHA256SUMS` 的校验值并运行复现脚本，写 `preflight.json`
  （`ok` 等平铺字段可直接用作 `reopen-register` 的 `control_receipt` 条件），不做评审、不记决定。
- **空转指标**：每个 tick 报告带 `idle_metrics`：最近 24 小时每个任务类型的 `attempts`、`zero_output`
  （任务按上面的口径无进展；scout 为无有效卡片）、`agent_hours` 与 `zero_output_agent_hours`，以及合计。
  例：`tail -1 state/ticks.jsonl | jq .report.idle_metrics`。
- **token 与等价成本**（2026-11-16，`usage.py`）：旁边的 `token_cost` 给同一窗口
  （`[reporting].token_window_hours`，默认 24）每个任务类型的 `attempts`、`agent_hours`、`tokens_read`
  （未缓存+缓存读+缓存写的输入）、`output_tokens`、`equivalent_usd`（按 `[reporting.prices]` 的列表价，
  默认取 2026-11-16 成本核算的价格；不是账单）和 `unpriced_attempts`（模型不在价格表里）。
  `topic_economics` 给每个在研（active/in_review）题目一行：`seats`（负责人坐席数）、`agent_hours`、
  `tokens_read`、`output_tokens`、`equivalent_usd`、`cpu_core_hours`、`phase`（`precheck`/`solving`/
  `writing` 由负责人在状态包里声明；`recompute_review_N`、`revision_after_round_N`、`minor_revision`、
  `unified_review`、`direction_decision`、`awaiting_confirmation` 由控制面判断），以及
  `per_ready_paper`：进入 ready 队列（待人工确认）的论文平均成本，`direct_*` 只算该题 campaign 自己的尝试，
  `loaded_equivalent_usd` 把窗口内全部尝试（出题、立项、决策、冻结题）摊到这些论文上。只统计
  `[reporting].economics_since` 之后结束的尝试（未设则全部）；建议设为重启时刻。CPU 核时取自作业状态文件：
  ailab 作业为 `result/receipt.json` 的 `elapsed_seconds` × 线程数，本机作业为 `started_at` 到
  `finished_at`（运行中算到现在）；只有任务曾 yield 等待过的作业，或本机作业的 `source` 在该题 campaign
  或其尝试工作区里，才归到该题。`program utilization` 输出同样的 `token_cost` 与 `topic_economics`。
- **token 记账改为每次尝试的增量**（2026-11-16）。成本核算发现：续接会话时 Codex 的 token 计数和 Claude 的
  `total_cost_usd` 是整个会话的累计值（Codex 相加虚高 4.6 倍，Claude 续接费用约 3 倍），Claude 的 token 计数
  则是本次调用的。现在入库时（`usage.record_increment`）按同一会话之前的记录扣除：原始值留在
  `usage_cumulative`，会话此前的累计在 `usage_session_base`，顶层字段改为本次增量，`usage_basis:
  attempt_increment`；计数比会话此前累计还小（进程重启后从零计）时原样保留。历史行不改写，
  `usage.normalized_attempts` 读的时候用同样的方法校正，所以上面的报表对旧数据也成立；`budget.execution_summary`
  与资产复用对比直接读顶层字段，今后自然是增量。配速与额度估算（`estimate_stale_readings`）用的是 Agent 秒数和
  额度读数，不读 token，不受影响。lab runner 另外记录 Claude 的缓存写入
  （`cache_write_input_tokens`、`cache_write_1h_input_tokens`），它们按缓存写价计。口径限制：runtime
  只有整次尝试的 token，没有逐请求的模型，所以全部按该尝试的模型计价——配置为 gpt-6-astra、把大量工作交给
  gpt-6.1-sol 子会话的负责人坐席会被高估（用 2026-11-16 前的数据核对：V0651 Hya 课题按此口径约 108 美元，
  逐请求实测 37 美元；全期 Codex 输入 token 由原始相加的 6,812M 校正为 1,365M，实测 1,471M）；单次请求超过
  长上下文阈值的加价未计。精确核算仍用 `maintenance/20261116-cost-review/` 的逐请求脚本。

### 算力节奏：计算积压闸门与每题在队线程上限（2026-11-18）

起因：2026-11-16 重启后 10 小时立项 9 个课题，负责人按模板每题提交几十到上百个剖面作业（一次两批各 135 个），
ailab（4 物理核 8 线程）一度排队 22 个作业、申报线程为容量的 11.9 倍，课题都在等计算。两道限制，都不新增流程：

- **计算积压闸门**（`[program].compute_backlog_gate`，默认 true；`utilization.compute_backlog`）。每个
  tick 读 ailab 队列（`/workspace/.openlabs-remote/jobs`）与本机队列（`/workspace/.openlabs-local-compute/jobs`）
  的状态文件，统计**排队中**（READY、未撤回）的作业数与申报线程数；容量 = ailab `cpu_threads`
  （`config/remote-compute.json`）+ 本机队列 `max_cpus`（`config/local-compute.json`）。排队线程数超过
  `compute_backlog_ratio`（默认 2.0）× 容量，或排队作业数超过 `compute_backlog_max_queued_jobs`（默认 0，不按作业数）
  时，暂停新的出题（scout）、立项评审（admission）和已立项题目的建 campaign（materialize）；在研课题不受影响。
  tick 报告 `production_blocked` 写 `{"reason": "compute_backlog", "detail": ...}`，`program.compute_backlog`
  给完整快照（排队/运行线程、容量、阈值、两个队列各自的数），`program.scout_blocked` 为 `compute_backlog`。
  积压回落后下一个 tick 自动恢复，不需要人工解除。队列读不出来时不拦。
- **每题在队线程上限**（`[program].campaign_compute_threads`，默认 8，约一个 ailab；0 关闭）。负责人简报
  “Resources”一段写明 ailab 真实容量（8 线程、约 61 GB；4 物理核，两个 4 进程作业同时跑各慢约 1.6 倍）、本机
  队列容量、坐席开始时两个队列的排队/运行作业与线程数和本题在队数，以及这条限制和“大批量剖面分批提交、先粗后细、
  前一批结果决定下一批”。硬保险在提交入口：lab runner 给 agent 进程设 `OPENLABS_CAMPAIGN_ID`、
  `OPENLABS_TASK_ID`（所有任务）和 `OPENLABS_CAMPAIGN_COMPUTE_THREADS`（负责人坐席）；`openlabs-remote submit`
  （天文线 `solver/submit.sh`、toolkit `qprofile_run` 都经它）把提交者写进作业目录的 `submitter.json`
  （不改 `request.json`，桥与 ailab 网关看到的请求不变；移到本机的作业随之复制），提交前统计本题在两个队列里
  排队+运行作业的申报线程，加上本次超过上限即拒绝（退出码 4，不写任何作业文件），提示里写明在队作业数、线程数、
  上限、作业号和建议做法（等这些作业 / 以 awaiting_remote 结束坐席，分批提交）。本题队列为空时单个作业总能提交。
  没有 `OPENLABS_CAMPAIGN_ID` 的会话（人工、ad-hoc）不受限；2026-11-18 之前提交的作业没有 `submitter.json`，
  不计入任何题目。

建议取值见 `config/openlabs.toml` 的注释；重启时按 ailab 8 线程、本机 12 线程（与智能体共用）、单星课题
60–120 核时估计。

### 暂存区未登记文件由控制面补登记（2026-11-18）

起因：2026-11-16T19:44Z 负责人尝试 `await:f501e220`（课题 7504c471）把两个远程作业打包目录
（`profile_job_0/`、`profile_job_1/`：天文线 `astrosolve`/`contact_photometry` 代码副本 66 个 `.py`、`run.sh`、
`plan.json`、光变曲线和 53 MB 通带表）留在产物暂存区；Stop 钩子按旧规则登记了其中的非脚本文件，脚本留给负责人，
提交关口因“暂存区有未登记文件”把整个结果判为 needs_replan。现在入库时（`attempts.settle_unlisted_staging`，
所有带产物策略的任务；负责人坐席在 Stop 钩子里用同一套分类 `classify_unlisted_staging`）：

- **作业打包目录**：暂存区里某目录含有与 `/workspace/openlabs/build/lines/*/solver` 下文件字节相同的副本
  （按哈希与相对路径后缀确定复制根），整个目录的未登记文件合为一条清单；Python 缓存（`__pycache__`、`*.pyc`）、
  未登记脚本（`.py`/`.sh` 需要重放闭包，只能作者登记）和超限文件也各合为一条清单。清单（`_openlabs_unlisted/*.json`，
  schema `openlabs.staging_unlisted_manifest.v1`：文件数、总字节、逐文件 sha256 与匹配的共享代码路径、
  `listing_sha256`）登记为 `staging_unlisted_manifest` 产物；对应文件移到暂存区旁的
  `<attempt>/staging-unlisted/`，不进产物库。
- **其余未登记文件**逐个登记为 `staging_unlisted` 产物（id `staged-<sha16>`、sha256 由控制面计算），上限单个
  64 MiB、合计 256 MiB、200 个，超出的进 `over-limit` 清单。
- 仍然拒绝：暂存区里的符号链接、像凭据的文件名（`.ssh` 等目录、`id_rsa*`、`.env`、`*.pem`/`*.key` 等，提交时报
  “protected (credential-like) files”）、在暂存区与 campaign 工作区之外新写的文件。
- 记录：runtime `staging_unlisted`（登记的文件、各清单的文件数/字节/哈希、拒绝的路径）与事件
  `staging_unlisted_registered`。负责人自己登记的文件不受影响。

### 负责人模式：一直负责到复审“小修/接受”（2026-11-14，2026-11-16 扩展）

`[program].owner_mode` 打开后，立项的题目由一个负责人 agent（`topic_owner` 坐席，一次一个进程，按
`[program.owner].runners` 的顺序选 runner）从头负责：做不做子 agent、何时调用另一家模型都由它决定。控制面
只给目标、资源、工具和硬限制（简报约 4.3 KB，`owner.render_brief`），并按负责人与评审交回的结果自动衔接。

**目标**是稿件达到独立“重算式复审”的小修或接受，而不只是写出稿件。状态机（存于 meta `owner_state:<campaign>`
的 `review_round`、`review_stage`、`review_history`）：

```
负责人坐席 --ready_for_review--> 重算式复审第 N 轮（paper_review，routing owner_recompute_review）
   accept  ------------------------------------------------> 统一评审（routing owner_review）
   minor   --> 负责人小修 + 自查一致性 --ready_for_review----> 统一评审
   major   --> 负责人修改（可提交作业并 awaiting_remote）--ready_for_review--> 第 N+1 轮（新评审会话）
   major 且 N = review_max_rounds、或 reject --> 方向决策（owner_review_rounds_exhausted / owner_review_rejected）
   结论无法解析 --> 同一轮换新会话重审一次；再失败 --> 回负责人
统一评审 ready --> ready 队列（待人工确认、交付流水线）；统一评审要求修改 --> 回负责人 --> 再次统一评审
```

投稿前由人全面审核全文及相关材料。投稿操作仍由人单独确认。

- **重算式复审**：`paper_review` 任务、技能 `openlabs-recompute-review`、空白会话、父任务是负责人坐席，所以
  路由按父任务避开负责人的模型族（只有一个模型族、或另一族因额度不可用时同族不同模型，见"额度上限与配速"一节的独立性回退）。每轮都是新任务新会话，不继承上一轮
  评审的上下文；输入包（`program_control/recompute-reviews/<campaign>/round-N-*.json`）列出负责人结果、campaign
  目录、`research_state.json`、工作日志、该线规格、核对清单和此前各轮的意见与作者答复（`REVIEW_RESPONSE.md`
  的路径与哈希，以及状态包的 `response` 字段）。核对清单取研究线的 `review_checklist`（见下节），没有时用通用
  清单：关键数值复现、数据与时间/单位系统、误差预算与敏感性、文献抽查、表图正文一致性、流程用语与过强表述。
  评审交回 `recompute_review`：`verdict`（accept/minor/major/reject）、`required`、`optional`、`unverified`、
  `checks`、`scripts`（重算脚本路径）、`summary`。
- **与统一评审的分工**：重算式复审是负责人循环内的质量环节，只管“核心结论能否从数据重算出来”；统一评审
  （`paper-writing review unified-run`）仍是交付/投稿前的正式关口（编辑筛查、盲审、预注册原文逐字核对、文献与
  公式核验）。二者不重复：重算式复审不做预注册逐字核对和期刊筛查；统一评审的任务说明列出重算记录与脚本，要求
  不再重算，只核对重算提出的必改项已解决，并在复审轮把记录写进答复信供审稿人参考。重算式复审通过（minor 完成
  或 accept）后，负责人再交 ready_for_review 只走统一评审。方向决策选定点分析后重算轮次从零开始
  （`review_cycle` 加一，历史保留）；选换刊时证据不变，已通过的重算保留，只再走统一评审，未通过的从零开始。
  方向决策次数仍受 `[program.direction_limits]` 约束。
- **长会话成本**：默认每个坐席都是新会话（`session_max_seats = 1`），从负责人自己写的交接文件
  `OWNER_HANDOVER.md`（当前状态、待办、关键文件路径、待完成作业、上一轮评审与答复）开始；控制面只检查它是否存在、
  是否超过 `handover_max_bytes`（默认 8192 字节），在下一份简报里附上（超长截断并提示），并附上工作日志路径和
  上一轮复审的结论与必改项，不替负责人写摘要，也不因缺失或超长退回结果。`session_max_seats = N` 允许同一会话
  连续 N 个坐席（0 = 不限，即旧行为）；`session_max_tokens_read > 0` 时该会话已读输入 token 达到阈值也换新会话。
  远程作业等待后的唤醒坐席遵循同一规则。两种 runner 的效果：Claude runner 新会话不带 `--resume`，不必在缓存
  过期（最长 1 小时）后把整段旧上下文重新写入缓存（续接一个四小时坐席后的会话，常见一次几美元的缓存写入）；
  Codex runner 新会话是新的 thread，不再每次请求重读累计的旧上下文，`total_token_usage` 也从零计。负责人在
  坐席内自己开的子 agent 不受此影响。
  短续写续接（2026-11-20，缓存成本复盘）：`short_resume_context_tokens > 0` 时，紧接上一坐席排队的坐席在超过
  `session_max_seats` 后仍可续接原会话，条件全部满足：上一坐席最终上下文（最后一次请求的输入，运行记录
  `last_context_tokens`）小于该值；距上一坐席结束不超过 `short_resume_gap_minutes`（默认 10 分钟，在 1 小时缓存
  有效期内）；同一模型；同一课题；该会话累计读入小于 `short_resume_max_tokens_read`（默认 1M，防滚雪球）。
  排队超过间隔仍未启动的续接坐席由 `owner.supervise` 改回新会话。远程作业唤醒坐席不走此规则。默认 0（关）：
  11-18 至 11-20 的 sol 负责人坐席回放显示，新会话首请求约 20K token 且约 64% 命中缓存，续接带入的 40–100K 旧
  上下文在后续每次请求里重读，净多花。换 runner 时（`switch_after_minutes`）只有同一模型才保留会话；普通任务
  经额度路由换到同提供方的另一模型时也改为新会话（缓存按模型隔离）。
- **写作规范（2026-11-19）**：简报的 Tools 段有一行“Writing rules (binding, not optional)”（`owner.WRITING_RULES`），
  要求负责人动笔前、每次改稿前读 `workflows/paper/skills/openlabs-paper-readability/SKILL.md`，先写
  `papers/<id>/writing/storyline.md`，交 ready_for_review 前跑 `paper-writing narrative-check`（正文超限、修订史用语为失败）
  和 `paper-writing reader-check`（一遍读者自查，写稿者会话内的工具调用，不是新任务）。重算式复审与统一评审意见回到负责人时
  附 `owner.REVISION_RULE`：补充内容默认进附录和回复信，正文不得净增。写稿仍由一个负责人从头写到尾，没有新增任务类型。
  细节见 `workflows/paper/docs/WRITING_STYLE.zh.md`。
- **写稿者交接（2026-11-19）**：`[program.owner].writing_runner`（如 `"worker_claude"`，缺省为空 = 负责人自己写，
  行为不变）。求解仍由原负责人做；写稿与之后所有改稿由写稿者一个模型完成，直到交付。
  - **切换点**：负责人某个坐席成功交回、其状态包写明求解完成——`phase: "writing"`（status `continuing`），或在任何评审
    之前就交 `ready_for_review`——从下一个坐席起换成写稿者（新会话，routing `owner_writing_handover`，objective 说明
    “你是写稿者、整篇自己写、不拆给多个模型”）。判定在 `owner.writing_switch_due`，用的是交回前的 owner 状态。
  - **不换人的在研课题**：此前已记录 `phase: writing`（稿件已由原负责人开写，例如本设置上线前）、已有复审轮次或评审历史
    （`review_round`、`review_stage`、`review_history`，即稿件已在复审/修改中）、已交接或已回退过、或负责人本就是写稿者。
  - **交接**：配置了写稿者时，求解者的简报有 “## Writing” 一段，要求求解完成后不动笔，把结果清单（数值及产出它的文件/
    脚本）、可用图表、终点判定、负结果、已知局限、未完成事项、paper_id 与目标刊写进 `OWNER_HANDOVER.md`，再以
    `continuing` + `phase: writing` 结束坐席；写稿者的简报写明它的角色。交接记录在 owner 状态的 `writing` 字段
    （`status: active|fallback`、`runner`、`solver_runner`、`trigger`、`trigger_task_id`），并作为 `writing_handover`
    记在课题台账历史里。
  - **评审独立性**：写稿者在位时，重算式复审和统一评审任务带 `exclude_provider` = 写稿者的模型族（不再只看父坐席），
    所以 Opus 写的稿件由另一族复审；另一族额度不可用时“同族换模型并标注”的既有回退规则照旧，且不会选写稿者本身的模型。
  - **名额**：写稿坐席不计入 `max_topics_per_runner`（`current_owners` 跳过写稿课题），也不被 `supervise` 按
    `switch_after_minutes` 挪给其他负责人；同时运行的写稿坐席至多 `max_writing_topics`（缺省 2），多出的排队坐席以
    `not_before` 每 15 分钟复查。
  - **额度等待与回退**：写稿者额度不可用（达到上限或被配速，坐席被路由器按 pinned runner 推迟）或名额满时坐席等待，
    不回退给 sol；连续等待满 `writing_wait_hours`（缺省 12 小时）才改派回原负责人（新会话），owner 状态改为
    `fallback`，课题台账记 `writing_fallback`。此后由原负责人写；回退后评审按交回稿件的坐席避开其模型族（既有规则）。
  - 名额与回退检查在 `owner.supervise_writing`，随路由开启时的 tick 运行（`[routing]` 关闭时不做名额限制，也不会有额度等待）。
- 状态包可带 `phase`（`precheck`/`solving`/`writing`），只用于上面的 `topic_economics` 和写稿者交接。
- 配置（`[program.owner]`）：`recompute_review`（默认 true；false 时 ready_for_review 直接进统一评审，
  即 2026-11-16 之前的行为）、`review_max_rounds`（默认 3）、`session_max_seats`（默认 1）、
  `session_max_tokens_read`（默认 0，不按 token 切）、`handover_max_bytes`（默认 8192）。其余键见
  `config.OwnerSettings`。

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
- **立项前的机械预检与核时下限**（2026-11-16，`card_precheck.py`）。卡片在登记为 proposed 之前由控制面处理，
  不调用模型；没有声明的产线/模板不受影响。`[program].card_precheck`（默认 true）、
  `card_precheck_max_seconds`（默认 900，封顶每个命令的超时）、`card_compute_floor`（默认 true）可在实例里关掉。
  字段（产线条目里；`admission_precheck` 的形式由天文线 2026-11-16 写下的 draft 定，编排器按它读取）：

  ```yaml
  admission_precheck:            # 产线级；按卡片的 paper_template 选命令
    schema: draft-2026-11-16
    model_calls: none
    network: none
    per_template:
      contact-binary-solution:
        command: /abs/venv/bin/python /abs/enumerate/admission_precheck.py {entry_id} --json
        inputs: [...]            # 说明性
        pass_condition: exit code 0 and JSON verdict == "pass"   # 说明性；判定规则见下
        hard_checks: [...]       # 说明性
        soft_checks: [...]       # 说明性
        typical_seconds: 0.1-1
        output: JSON {verdict, failed, warnings, checks[{name, pass, hard, value, rule}]}
        timeout_seconds: 60      # 可选，编排器扩展；默认 120
        cwd: /abs/path           # 可选，编排器扩展；默认本卡的预检输出目录
  card_compute_floor:            # 可选，产线或模板；缺省时取 per_paper_cost 的下界
    ailab_core_hours: 60         # compute_plan.ailab 的 cpus × hours 不得低于此
    agent_hours: 6               # cost_estimate.agent_seconds 不得低于此 × 3600
  review_checklist:              # 可选，产线：重算式复审的核对清单（字符串列表，或文档的一节）
    path: registry/research-lines/sop-astro-survey-photometry.md
    section: "8.4"
  ```

  命令是字符串（按 shell 词法切分，但不经过 shell）或 argv 列表。占位符：`{entry_id}`（卡片
  `candidate_queue_entry.entry_id`，即队列条目或批次号）、`{tic}`（`TIC...` 条目的数字部分）、`{card}`（存好的
  卡片 JSON）、`{line}`、`{template}`、`{data}`（数据仓库根）；环境变量 `OPENLABS_CARD_PATH`、
  `OPENLABS_QUEUE_ENTRY_ID`、`OPENLABS_RESEARCH_LINE`、`OPENLABS_PAPER_TEMPLATE`。判定读退出码和 stdout 上的
  JSON 对象（stdout 原样存为 `program_control/<项目>/prechecks/topic-<卡片哈希>/precheck.json`）：
  - **pass**：退出码 0 且 `verdict == "pass"`；结果（含 `warnings`）写进题目 `card_check.precheck`，随卡进入
    立项评审包。
  - **fail**：JSON 的 verdict 不是 pass（`fail`、`not_found`）且退出码为 0/1/2，或卡片缺少命令需要的
    `candidate_queue_entry.entry_id`。卡片记为 rejected（`card_precheck_failed`，不自动修正，不算对题目的判定，
    `card_errors` 写失败的硬检查项：名称、值、规则），不进立项评审，退回出题方的结果里可见；每条线的累计数在
    tick 报告 `program.card_prechecks.by_line.<线>.rejected`。
  - **error**（基础设施问题）：超时、命令起不来、stdout 不是带 verdict 的 JSON、其他退出码。卡片保持 proposed
    但不送立项评审（`schedule_topic_admission` 原因 `admission_precheck_error`），每个 tick 重跑一次
    （`program.card_prechecks.retried`，`card_check.precheck.attempts` 计数），每次出错都写进 tick 报告
    `errors`，直到通过（照常送评审）或不通过（记 rejected）。既不静默放行，也不静默拦截；
    `by_line.<线>.waiting_on_error` 是正在等待的卡片数。线上去掉该模板的命令或在实例里关掉预检时，等待的卡片放行。

  预检在 tick 里同步运行，只应声明不联网、几秒内跑完、读缓存数据的检查（天文线两个命令实测 0.1–0.3 秒）。
  核时下限：卡片 `compute_plan.ailab` 的核时低于下限时把 `hours` 上调到下限、`agent_seconds` 低于下限时上调，
  改动写进 `card_check.normalized`，不退回卡片。`per_paper_cost` 的下界只取以数字开头的值
  （`"60-120 ..."` → 60；`"< 5"` 不设下限），优先 `ailab_core_hours`，其次 `cpu_core_hours`；天文线模板 v2 的
  `cpu_core_hours: 60-120 per single-star paper ...` 与审计模板的 `400-560` 都能直接读出。
- **多模板的枚举队列**（2026-11-16，队列 qp-2.0）。一条线可以有多个带 `candidate_queue` 的模板（天文线：
  `contact-binary-solution` 的 `queue/queue.json`，`nn-catalogue-audit` 的 `queue/nn_audit_batches.json`）。出题说明
  要求按各队列 `candidates` 的 `rank` 抽取，按条目的 `ledger_occupancy` 跳过占用的目标，把 `card_fields` 的全部键
  原样抄进卡片（含 `reopens` 与 `reopen_basis`：旧规则下冻结的目标靠它们按新模板版本重新立项，台账按“问题+数据源+
  主终点”指纹判重，重开类型须在旧题目声明过的类型内，未声明时不限），其余按该模板条目的 `card_rules` 写，不再写
  单星口径的对称性/对照星门槛；同一目标出现在两个模板里是两个题目，不互相判重。空转退避的供给指纹包含每个模板
  队列文件的哈希；另按模板记空抽次数（meta `program_scout_supply:<线>` 的 `templates`，有该模板的卡片立住即清零、队列
  文件变了从 1 重计），写进出题说明的“Queue state”和退避信息，供 scout 跳过已抽空的模板。不依赖
  `environment.standard_solver.spot_config` 或任何具体能力键。
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
  （默认 1，0 关闭）时，题目 `frozen -> active`（`auto_reopen_conditions_met`），campaign 解冻，给原负责人
  派一个 `owner_reopened` 坐席并写明哪些条件变了（会话按负责人模式的会话规则：默认新会话，从交接文件开始）。预注册、主终点、停止规则和预算都不变；再次冻结时若没有新的
  `reopen_when`，旧条件清空，不会因同一事实反复重开。
- 业主授权的文字修改重开（2026-11-20）：稿件在评审中、因流程性耗尽被冻结的题目（`freeze_reason_class` 为
  `review_stalled` 或 `overdue`，例如方向决策次数 `[program.direction_limits]` 用尽后被迫冻结），业主可再给一次
  写稿者修改：
  `python -m openlabs program reopen-grant --topic-id T --reason "<理由>" --by <谁> [--scope text_revision]`
  （实例上经 `bin/openlabs-container-loop --instance-dir <实例> cli -- program reopen-grant ...` 调用）。
  只接受从 `in_review` 冻结的题目；`primary_endpoint_failed`、`feasibility_precheck_failed`、
  `decisive_data_unavailable`、`contribution_insufficient` 这类科学性冻结直接拒绝（这类题目要靠带 `reopens`
  的新卡片重开），`budget_exhausted`、`infrastructure`、`no_eligible_venue` 也拒绝；另外要求负责人模式、campaign
  还有 Agent 预算，且上一轮统一评审没有用完本刊轮次（`rounds_for_target < max_rounds_per_target`；轮次上限属于
  settings.yaml 的用户决定，本命令不改）。每题可授权次数由 `[program].operator_reopen_max`（默认 1，0 关闭）
  限制，与 `auto_reopen_max` 分开计数，不消耗自动重开次数。命令执行后：题目 `frozen -> in_review`（受保护理由
  `operator_reopen_granted`，history 记 by、理由与时间，并另记一条 `operator_reopen_granted` 说明），台账写
  `reopen_grant: {scope: text_revision, slot_exempt: true, grants: [...]}`；campaign 解冻；给该稿件原写稿者
  （有 writer 时为 writer，否则为最近的负责人 runner，不换模型）派一个 `owner_operator_reopen` 坐席，说明由台账
  `reopen_conditions` 的修改清单加本次授权理由组成，只做稿件修改、不做新分析。写稿者交 ready_for_review 后照常进入
  下一轮统一评审；通过则进 ready 队列，不通过则照常排方向决策，次数已用尽时再次冻结。
  名额：在授权下处于 `in_review` 的题目不占 `max_active_topics` 与 `line_max_active_topics`（它是已成稿题目的收尾，
  不是新开研究）；调度报告里非零时单列为 `grant_exempt_topics` 和各线的 `grant_exempt`，不计入 `occupied`。豁免只在
  授权那次转入 `in_review` 之后、没有被接受的非冻结方向决策（定点分析或换刊）之前有效；之后的
  `ready_queue -> in_review` 全量复审或重新研究照常占位。其他题目的计数不变。命令在 ledger 已写、campaign 或坐席
  未建时中断的，下一轮调度（`reopen_repaired`）补完。
- 现有实例迁移：`python -m openlabs program init-instance --instance-dir <dir> --set-research-lines`
  先看 dry-run，再加 `--write`。它只新增缺少的产线项目，并在实例 TOML 的 `[program]` 里写入
  `research_lines`（其余键与注释不动，旧文件留 `.bak`），不改题目台账。回滚：恢复 `.bak`。

### 多线并行：按线在研上限、暂停课题、GPU 本地队列（2026-11-19）

起因：用户 2026-11-19 要求天文、电力市场（`power-market-backtest`，quant 实验室承载）、故障诊断评测审计
（`phm-evaluation-audit`，ai 实验室承载）三条线同时试做，比较哪条线更容易出成果；合计在研不超过 5 个。

- **按线在研上限** `[program].line_max_active_topics = { "<线>" = N, ... }`（默认空表，不按线限）。每条列出的线单独数
  自己的 admitted + active + in_review 课题：满额（或空位已被等待立项的卡片填满）的线不出题、不送立项评审，立项评审一批
  最多送该线剩余空位张卡；该线已立项的课题在研数达到上限时不建 campaign（保持 admitted 排队，不丢弃）。全局
  `max_active_topics` 照旧生效；**只因本线满额而等待的 admitted 课题不占全局名额**，否则它会把别的线也堵住。
  出题包里有 `line_free_slots`，`max_cards` 不超过本线剩余空位。tick 报告 `program.lines.<线>` 给
  `{limit, occupied, researching, free_slots}`，出题被拦的原因为 `line_slots_full`。
- **暂停的课题不占名额**（全局与按线都一样）：campaign 为 `production_paused` 且其 `research_state.json` 的
  `status` 为 `paused`（人工或负责人有意暂停）的课题，台账里仍是 active、预注册不变，但不计入任何上限
  （`program.paused_topics`）；把状态改回 `active` 后重新计数。因绑定错误、协议钩子等其他原因暂停的 campaign 照旧占名额。
  2026-11-19 修正前，天文线 4 个暂停课题仍占名额，全局占用 12 个、上限 7，任何线都无法立项。
- **线条目的资源字段**（负责人简报“Tools”段只读这些，不写死任何一条线的文字；`research_lines.line_resources`）：
  `environment.standard_solver.entry` / `environment.tools` / `standard_tools.path`（标准入口；与分析包同路径时只列一次）、
  `environment.activate`、`analysis_package.path`+`entry`、对照回执（`environment.standard_solver.control_receipt`、
  `environment.control_receipt` 或 `control.receipt`）、`environment.data`（无则 `data_access`）、`environment.sop`、
  `environment.gpu`（文字，或 `{usage, memory_mib}`；`none` 表示不用 GPU）。声明了 GPU 的线，简报“Resources”段多一条
  GPU 规则（一块卡、一次一个作业、长作业走本地队列并以 awaiting_remote 结束坐席）。
- **线自定期刊分层** `venues.tier_policy`：电力线与 PHM 线以中科院 2025 大类 1 区刊为常规目标刊，大类 2 区混合刊只作订阅路径、
  不付费的兜底刊；立项评审按线的分层判断，不套默认的 3–4 区（`settings.yaml#journal_target_policy` 对其他线不变）。
- **卡片 GPU 时下限**：`card_compute_floor.gpu_hours`（或模板 `per_paper_cost.gpu_hours_lower_bound` / `gpu_hours` 的下界）。
  计算计划含 `container_gpu` 或已申报 GPU 时的卡片，`cost_estimate.gpu_hours` 低于下限时上调并记入 `card_check.normalized`。
- **GPU 作业进本地队列**：`bin/openlabs-local submit --gpu-memory-mib N [--gpu-device 0] --source DIR --cpus N --memory-mib M
  --timeout-seconds S -- CMD`。作业在 `openlabs-resource-guard --task-type gpu` 内按该显存预约运行，队列同时只跑一个 GPU 作业；
  GPU 被队列外的作业占着时守护进程立即拒绝（退出码 75），作业退回排队（`gpu_requeues` 计数）而不是失败。互斥本身由
  守护进程的主机级 GPU 锁保证（`RESOURCE_GUARD.md`：每个 GPU 一个声明作业，第二个预约立即失败），队列只负责排队与续等。
  排队中的 GPU 作业不计入 CPU 计算积压闸门（它们等的是 GPU，不是 CPU），报告里单列 `local.queued_gpu`。
  2026-11-19 真卡实测后补充：显存申请超过设备上限（RTX 5070 为 11004 MiB）在提交时即拒绝（此前会每次派发都退回排队、无限循环）；
  守护进程拒绝分两类——锁被占（"GPU already reserved"）无限期等待，显存余量不足（"GPU reservation rejected"）最多重试 20 次后
  判失败并提示减小申请；被拒的作业 60 秒内不再尝试（`gpu_retry_after`）。GPU 作业有自己的槽位，不受本机队列 `max_jobs`/`max_cpus`
  限制（CPU 溢出作业按设计会占满它们），但每个 GPU 作业最多声明 4 个 CPU。
- **没有 `ledger_occupancy` 的队列**（电力、PHM 线的队列由各自脚本生成，只有天文线的枚举器写占用）：出题说明列出
  台账里已被课题占用的条目（按卡片 `candidate_queue_entry.entry_id`），可抽取数也扣除它们；格式错误或机械预检不过而被
  拒的卡片对应的条目可以再抽。同一个队列文件被多个模板共用时，每个模板只数 `card_fields.paper_template` 是自己的条目，
  从共用队列抽到卡片不算其他模板的空抽。
- **线级期刊分层进入选刊校验**（2026-11-19）：线条目 `venues.tier_rules: {routine_tiers: [1], fallback_tiers: [2]}`
  是 `tier_policy` 的机器形式。论文登记记录写 `research_line: <线>` 时，`paper_writing.venue_policy` 按该线的分层判断：
  1 区目标刊是常规目标（不走升级通道、不要求 target_escalation 与 7 分门槛），2 区可作兜底刊；收费规则不变。没写
  `research_line` 或线没有 `tier_rules` 时照旧按 `settings.yaml#journal_target_policy` 的全局默认。负责人简报会提示写这个字段。
- **智能体并发不被本机溢出作业压住**（可选，2026-11-19）：`[budget].host_load_excludes_local_compute = true` 时，自适应
  并发上限看的 CPU 负载扣除本机队列运行中作业申报的 CPU（这些作业按设计占满容器、上限为 `max_cpus`）。默认关闭。
- 新线的计划项目用 `python -m openlabs program init-instance --instance-dir <dir>`（先 dry-run，再 `--write`）补建：
  它只新建缺少的项目文件，已有文件一律不覆盖；不要同时加 `--set-research-lines`（那会把 `research_lines` 改成全部八条线）。

### 发布流水线（评审 ready → 交付）

每个 tick 对每篇 ready 论文先运行 `paper-writing program release-status`（只读），再走下一步；
任何一步失败或中断，下个 tick 从实际状态重新判断，每步写 events 和题目台账 `release` 字段
（`stage`、各阶段 `attempts`、`writer_rounds`、`last_error`、`commits`）：

| 阶段 | 调用 | 失败或不满足时 |
|---|---|---|
| 形式修正（确定性） | `zenodo prepare`（重建支撑包身份：回执、版本、DOI、记录标题） | 计次重试 |
| 形式修正（文字） | 轻活档 `format_fix` writer，只改列出的问题，不改数字、表格、结论和标题 | 轮次用尽即停 |
| 差异复核 | `review unified-run --delta-only`（不调编辑和审稿人、不计轮次） | 超出差异规则（`full_review_required`）：题目回 `in_review`，排一次完整 `paper_review`；预检/核验类结果（`preflight_failed`、`formal_check_blocked` 等）按失败计次重试，用尽后等人处理 |
| 提交 | 本地 `git commit --only`，只含本论文的登记、`papers/<id>/`、评审记录和台账 | 无身份时等待 |
| 支撑材料发布 | `support-check` → `zenodo release` | 计次重试 |
| 交付 | `program deliver`（无投稿人），随后再提交一次 `delivery` 块 | `handoff_max_attempts` |

黑名单词只作备注，不阻断。改标题、数字、表格或结论段的改动超出差异规则，走完整评审。
用尽 `release_max_attempts` 的论文列在 tick 报告的 `program.release_exhausted` 并写入
`errors`，不再重试；人处理后运行
`python -m openlabs program release-retry --paper-id <id> --by <name> --reason <处理了什么>`：
`release.status` 回到 `pending`、清零停下那一阶段的 attempts（写作阶段还清零 writer_rounds），交付用尽的
`handoff` 回到 `queued`；原错误、阶段和次数记在 `release.retries`，并写一条 `release_retry` 事件，下个 tick
从实际状态重新判断。同一命令还处理两种情形（同样要 `--by`/`--reason`，记在 `release.retries` 和
`release_retry` 记录里）：一是已交付旧版本后论文出了新版本（`release-status` 的 `delivered` 为 false 且登记
`delivery.version` 与当前 `version` 不同），`handoff` 回到 `queued`（保留 `previous_package_id`、
`previous_delivered_version`），`release` 回到 `pending`/`check`；当前版本已交付、登记没有交付版本时拒绝。
二是流水线退回评审（`release.status: returned_to_review`）但论文其实 ready 且 current：课题回
`ready_queue`，暂停其 campaign（取消排队中的 `release-review:` 完整评审，结果列出被取消的任务），交付重新排队；
评审不是 ready+current、或该完整评审已在运行（leased/running）时拒绝。不要手改台账。提交只含 Git 会跟踪的路径：数据仓库有意忽略且未跟踪的实例台账
（运行时状态，如 `registry/instances/cc-sg/topic-ledger.json`）不随提交，也不 `-f` 强加。

- 凭据（2026-11-20）：交付要 `ARA_PAPER_MANAGE_API_URL`/`ARA_PAPER_MANAGE_API_KEY`，Zenodo 步骤要
  `ZENODO_ACCESS_TOKEN`。先看 tick 进程环境；缺的再从 `[program] credentials_file`（绝对路径，NAME=VALUE，
  属当前用户、权限 0600 或更严、不放在任何 Git 仓库里）读，只读这三个名字，只放进交付/Zenodo 那一个子进程的
  环境，不写进 tick 的 `os.environ`：研究坐席继承 tick 的环境，看不到这些值。文件缺失、权限过宽、属主不对时不读，
  流水线照旧 `waiting_credentials`，事件和 tick 报告里多一项 `credentials_file`（只说原因，不含值）。配置每个
  tick 重新读取，改这一项不用重启循环。

交付链状态（2026-11-20 起）：每个 tick 的 `program.delivery_chain` 列出评审 ready 到交付完成之间的每篇论文，
`program.delivery_stuck` 只列卡住的。每篇恰好处于一种状态：`in_progress`（下一步由流水线或它排的 writer /
完整评审承担）、`auto_retry`（某步失败，自动重试，带 `attempt`/`max_attempts`）、`waiting`（等外部条件，
`condition` 写明：凭据缺哪个变量、Git 身份、`auto_release`、常设授权等）、`needs_human`（`action` 写明人要做
什么）。分类器不认识的状态记为 `needs_human`（`unrecognized: true`）并写入 tick `errors`，不留无主状态。
用尽次数而停下的阶段或交付，若停下后代码仓库 HEAD 变了（修复已合入 main），下个 tick 自动重试一次
（`release_retry` 记录，`decided_by: orchestrator:code_update`，每篇最多 2 次）；代码没变就一直等人。
paper-writing 命令失败时记录命令自己的错误（stdout 的 JSON `error` 或其输出），资源守护的准入横幅
（`OpenLabs container guard:` / `OpenLabs resource guard:`）不算错误内容；守护拒绝（`STOP:`）照记。

期刊资格本地登记：`registry/verified-venues.yaml`（数据仓库）。每条写明 2025 中科院升级版大类分区、SCIE、
APC/版面费/彩图费/投稿费、证据（URL 或本地文件）、核实日期和核实人；`verified` 仅当分区、SCIE、四项收费
都有证据且（1 区，或有免费路线）。查询先走登记：`paper-writing venue lookup|alternatives|mark-pending`。
负责人坐席因出版方页面拒绝（403/406 等）而返回 `blocked_human` 时，控制面改为 `continuing`，下一席的说明
要求先 `venue mark-pending` 记为待核实，再继续或改选登记中已核实的替代刊（每个课题最多 2 次，之后照常
`needs_human`）。

- `auto_release`（默认 false）：为 false 时流水线停在第一次 Zenodo 写入之前，`release.status`
  为 `waiting`、`waiting_for: auto_release_off`；为 true 时还要求
  `settings.yaml#support_publication.standing_production_release_authorization: true` 和
  `ZENODO_ACCESS_TOKEN`，外部写开关只对该子进程设置。
- 登记（adopt）：负责人模式的稿件在题目的 campaign 工作区里写作和评审（数据仓库不跟踪该目录）。
  数据仓库根下没有 `registry/papers/<id>.yaml` 时，第一步运行 `paper-writing program adopt`：把登记、
  `papers/<id>/`、`reviews/unified/<id>/`、`reviews/formal-check/<id>/` 复制到根下，登记的支撑源文件复制到
  `papers/<id>/support-materials/`；已存在且内容不同的文件一律不覆盖（报错计次）。attempt 归档没放进工作区的
  文件从 ready 评审任务的结果包恢复：形式核查证据只按报告绑定的 SHA-256 恢复，PDF 只取能复现 ready 决定
  所绑定的稿件快照的那一份。形式核查复验允许评审时的 `evidence_root` 路径标签与当前根不同，其余字节必须一致。
  两处都找不到登记时等待（`paper_not_found`），不计次。登记写成 `workspace: .`（稿件在工作区根下的
  `manuscript/`、`evidence/` 等）时 adopt 迁移：登记里点名的根层目录整体移到 `papers/<id>/` 下，只改写这些
  路径字段和 `workspace`，逐文件 SHA-256 对照记在 `papers/<id>/production/workspace-relocation.json`
  （登记 `relocation` 指向它），复制后再逐个核对；稿件字节不变，ready 决定绑定的稿件快照（相对稿件目录）
  照样复现，不需要重新评审。其他非规范布局一个文件也不复制，等待负责人（`layout_unsupported`）。
  恢复归档文件时依次用 ready 评审任务和该 campaign 其余任务的结果包；稿件快照所需的图、`.bbl`/`.aux`
  与 PDF 只在组合后快照与决定完全一致时保留。新稿件一律 `paper-writing paper create`（新建登记
  必须在 `papers/<id>/` 下，否则 `write_paper_metadata` 拒绝；已有的根相对登记照常加载，在 `validate` 警告和
  `release-status.layout_problems` 里报出，由 adopt 迁移）。
- 撤销支撑材料豁免：`paper-writing program unwaive-support --paper-id <id> --by <name> --reason <理由>`，
  恢复 `settings.yaml#support_publication.default_mode`（或 `--mode`），原豁免与撤销记在
  `support.publication.waiver_history`。
- 数据可得性：交付出口检查 `DATA-AVAILABILITY-LOCATION`，可得性一节既无 DOI/URL/引用，也没有
  supplementary/supporting material，也没有“全部在文中/未用数据”时报问题（writer 修文字）。
- 稿件源缺失（登记的稿件目录或 `main.tex` 不存在）时所有形式问题判为 `human`，等待负责人，不排文字 writer；
  `format_fix` writer 不跑实验室运行环境准备（与 direction_decision 一样只改文字）。
- 冻结构建产物：`zenodo release` 与交付只接受 Git 冻结的发布文件。被忽略的 PDF/.bbl 在 Zenodo 发布之前由
  `paper-writing program bind-release-artifacts` 复制到 `openlabs-artifacts/paper-support/sha256/` 并写
  `papers/<id>/production/release-artifacts.json`（登记 `submission_package.artifact_manifest`），随
  `commit-before-zenodo-release`（不做存档时随 `release-ready`）提交。已有清单但当前 PDF/.bbl 不在其中或
  SHA-256 不符（交付旧版本后出了新版本）时视为未绑定，按全部当前候选文件重写清单并更新登记指针。
  只含 `artifact_manifest` 的 `submission_package` 不视为已配置期刊源码包，交付用规范源文件清单。
- 超限文件：数据仓库的 pre-commit 钩子拒收大于 5 MiB 的 blob。`release-status` 的
  `oversize_payloads_unbound` 列出本论文提交路径下新进 Git（未跟踪且未忽略，或被拒的提交留在暂存区）且超过
  5 MiB 的文件（例如 formal-check 的证据正文 `.body`）。流水线在任何提交之前跑
  `paper-writing program bind-oversize-payloads`：复制到 `openlabs-artifacts/paper-support/sha256/<SHA-256>/`，
  把路径、大小、SHA-256 与 artifact URI 写进 `papers/<id>/production/payload-artifacts.json`，在文件所在目录的
  `.gitignore` 加锚定条目，并去掉暂存区里的残留条目；磁盘上的字节不动，复核照旧读原文件。清单和 `.gitignore`
  随下一次提交入库。绑定后字节变化的文件会再次列出并重新绑定。
- `support_release`（默认 `"zenodo"`，即上表的 Zenodo 步骤）：设为 `"none"` 时从不建 Zenodo 或其他公开记录。
  支撑记录仍是 `planned` 的论文由 `paper-writing program waive-support` 写入
  `support.publication.mode: not_required` 和 `support_none_reason`（写明不做公开存档）；已有 Zenodo 记录
  （draft/published）或稿件数据可得性一节提到 Zenodo 存档时不改，等待负责人
  （`support_record_exists` / `manuscript_cites_deposit`）。此时 `auto_release` 不起作用，可保持 false。
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

### 选题供给与早筛（2026-11-20，改造 W1）

配置在 `[program.supply]`（默认全开，见 `config/openlabs.toml`）；实现见
`orchestrator/src/openlabs/line_facts.py` 与 `supply_screen.py`。

- **线级共享事实**：负责人请求 `feasibility_precheck_failed` 冻结时，若失败依据是该线的共享参照
  （`environment.standard_solver.control_receipt` 的作业号/标签、线条目 `shared_references`、或同线其他课题也引用的作业），
  不冻结课题：该线被阻塞（不侦察、不评审、不开新 campaign），代表课题排一次方向决策（`line_reference_review`），
  其他引用同一参照的课题进入等待。结果里仍在排队/运行的作业 → 停泊等作业，不冻结（每题至多 `reference_wait_max` 次）。
  差距小于测量不确定度（无不确定度时 ≤ 容差 × `borderline_relative_margin`）→ 方向决策 `criterion_borderline`。
  负责人在 `gate_result.failed_criteria` 中逐项声明 `{name, delta, tolerance, uncertainty, reference}` 最准确。
  `python -m openlabs program line-block` 列出/`--clear LINE --reason ...` 解除阻塞；
  `python -m openlabs program line-reopen-report` 只读列出按新规则属于线级问题的已冻结课题（不重开）。
- **能力表与数据**：线条目 `capabilities`，卡片/模板 `required_capabilities`；卡片/模板 `data_requirements`
  （`glob`、`columns`、`header: csv|aemo_mms`、`months`、`min_fraction`）。不满足 → `card_capability_missing` / `card_data_unavailable`。
- **试算关口**：模板 `admission_pilot`（`stage`、`cpus`、`memory_mib`、`timeout_seconds`、`core_hours`、`verdict_file`），
  在 ailab 上运行，单作业 ≤ `pilot_max_threads`（≤8）线程、≤ `pilot_core_hours_max` 核时；预算与结论写入台账 `card_check.pilot`。
- **目标记忆**：同一 (线, entry_id) 因机械原因失败且队列条目未变、或有冻结课题而新卡未 `reopens` → `card_target_repeat_failure`。
- **侦察退避**：队列无可抽条目时不派侦察（`candidate_queue_empty`）；空跑退避超出列表后翻倍至 `scout_backoff_max_hours`；
  调度报告 `program.line_supply` 给出“题源枯竭”信号。

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
也拒绝 artifact-stage 中未声明、哈希不符、符号链接逃逸或发布后改变的文件。同一条数据边界规则在
Stop 钩子里先查一次（`attempts.campaign_data_boundary_violations`）：有违规时第一次 Stop 被拦下，提示
把文件移到 artifact-stage（写明路径）并在 `result.artifacts` 声明，避免整次运行在入库时才被拒（2026-11-20
电力线侦察把 AEMO 规格 PDF 放进 `evidence/`）；SessionStart 也写明 artifact-stage 的位置。数据库确认入库
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

停产与恢复（不停循环）：实例 TOML 的 `[factory] launch_jobs = false` 使每个 tick 不领取、不启动任何智能体
任务（出题、立项、负责人、评审、方向决策、组合评审、候选成熟、重规划都留在队列里），循环照常入库结果、
释放远程等待、做台账簿记；在跑的会话自然结束本坐席。此时 tick 也不做额度探测（`[routing.probe_commands]`
的 `claude -p` 会花一次模型调用）。本机计算队列默认随 `launch_jobs` 一起停；要让纯 CPU 的本机作业照常开工，
另设 `[factory] launch_local_compute = true`（或手动 `bin/openlabs-local dispatch`）。论文工具链等直接命令行
调用不经过派发，不受影响。恢复：改回 `launch_jobs = true`（必要时恢复 probe 配置），下一轮 tick 起派发；恢复
前先看队列里积压的任务（`bin/openlabs-container-loop cli -- status`），以免一次性启动过多。

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
`abundance` 和各窗口的 `window_pace`（其中 `ceiling`/`cap` 按该提供方自己的上限计算，见下文
"按提供方覆盖"）。随时可以只读地看汇总：

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
- **提供方限时停用**（2026-11-20）：`[routing.provider_suspensions.<provider>]` 写 `until`（带时区的 ISO 时间）和决定来源 `by`、`date`、`quote`（`reason` 可选）。`until` 之前，该提供方的 runner 在读配置时整体移除：负责人、写作、立项、评审、方向决策、轻活档都不派给它；`writing_runner` 属于它时回落为负责人自己写；`protected_models` 里它的模型不再保护；`probe_commands` 跳过它；`provider_ceilings` 里它的条目搁置（不报“未知提供方”）；路由按单族（`same_family_different_model`）运行。配置每轮重读，到 `until` 后下一轮起一切按配置原文恢复，无需人工。tick 报告 `provider_suspensions` 列出每条停用、是否生效和剩余小时数；开始和到期各记一次 `provider_suspension_active` / `provider_suspension_expired` 事件。正在运行的任务不受影响。代码见 `suspensions.py`。论文流水线一侧对应的是 `settings.yaml` 的 `review.temporary_panels`（`paper_writing/temporary_panels.py`）：评审在 `since`～`until` 之间启动就用限时面板和它的编辑改写配置，之后启动用标准面板；同一轮评审始终绑定启动时的面板。
- **按提供方覆盖**（2026-11-16 起）：`[routing.provider_ceilings.<provider>]` 可为单个提供方单独设
  `ordinary_ceiling` 和/或 `hard_ceiling`，未列出的提供方、未写的键沿用 `[routing]` 的全局值。覆盖后的值
  用于该提供方的一切：类别上限、配速线（按该提供方的上限缩放）、恢复时间与 `projected_at_reset` 对照、
  tick 报告 `provider_quota.<provider>.window_pace` 的 `ceiling`/`cap`、`program utilization` 的
  `quota_rule.provider_ceilings`、`quota-override` 不带 `--ceiling` 时的默认值，以及负责人坐席说明里的上限。
  值须在 (0, 1]，显式写的 `ordinary_ceiling` 不得高于该提供方的 `hard_ceiling`，键名或提供方名
  （须是 `[runners]` 里出现的 provider）写错都会在加载配置时报错。所有者 2026-11-16 要求：自动研究中
  Claude 的普通任务上限由 80% 改为 70%，Codex 仍为 80%，硬上限都保持 90%：

  ```toml
  [routing.provider_ceilings.anthropic]
  ordinary_ceiling = 0.7
  ```

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `[routing] ordinary_ceiling` | 0.8 | 普通任务最后一天的上限 |
| `[routing] hard_ceiling` | 0.9 | 所有自动任务的硬上限 |
| `[routing.provider_ceilings.<provider>]` | 无 | 该提供方自己的 `ordinary_ceiling`/`hard_ceiling`，未写的沿用全局值 |
| `[routing] pace_curve` | 见上 | `[[已过比例, 系数], ...]`：比例从 0 起严格递增，系数在 [0,1] 内不减、末点为 1，否则配置报错。纯线性（第 6 天末到 1）写 `[[0, 0], [0.8571, 1]]`；`[[0, 1]]` 关闭配速 |
| `[routing] pace_lead` | 0.05 | 起步量（绝对值） |
| `[routing] pace_min_window_hours` | 48 | 短于此长度的窗口不配速 |
| `[routing] override_max_ceiling` | 0.99 | 人工覆盖可用的最高比例（只能调低，永不到 100%，避免碰付费余额） |

旧键 `review_reserve` 已删除（写了也不再生效）；`utilization_target` 只作开关。

**另一模型族额度不可用时的独立性回退**（用户 2026-11-16 决定）：需要与产出方不同模型族的任务——立项评审
（`portfolio_review`，routing_reason `topic_admission`）、方向决策（`direction_decision`）、负责人稿件的重算式复审
（`paper_review`，`owner_recompute_review`）以及编排器派发的其他评审/决策任务——当另一模型族在 `[runners]` 里
有配置、但它所有可承担该任务的 runner 都因额度不可用（状态 unavailable：到上限 `ceiling`、超配速 `pace`、
保留线 `reserve`/`lead_reserve`、限流退避 `backoff`、读数判定不可用）时，不再一直等，而是交给产出方同族的
另一个模型（先试请求的档位，再按 lead→worker→light；产出方自己的模型永不选），与只配一个模型族时的已有机制相同。
`task_routed` 事件里写 `independence: same_family_different_model`、`producer_model`，另加
`independence_fallback: other_family_quota_unavailable`、`unavailable_providers`、`other_family_quota_reasons`
和 `other_family_resume_at`（另一族的预计恢复时间，未知时为 null）。

- 另一族只是忙（可用但并行数已满、读数未知只放 1 个）时照常等，不回退。
- 同族里没有不同模型可用时继续等（`routing_deferred` 带同样的回退字段），不会自己审自己。
- 另一族恢复后，新派发的任务自动回到跨模型族；已派出的任务不追回。
- 续接会话（`session_mode = resume`）、固定 runner 的任务不受影响；Fable 的保护规则（`protected_models`、
  `lead_review_ceiling`、`lead_decision_reserve`）照常适用于回退后选中的 runner。
- `workflows/paper` 的统一评审（`paper-writing review unified-run`）审稿人由数据仓库
  `registry/settings.yaml` 的评审设置决定，不走这里的路由，也不受此开关影响。

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `[routing] independence_fallback_on_quota` | true | 关闭（false）后另一族额度不可用时一直等 |
| `[routing] independence_fallback_min_wait_minutes` | 0 | 另一族预计在这么多分钟内恢复就等（`routing_deferred` 的 reason 为 `independent_family_resumes_soon`）；0 表示只要不可用就回退；恢复时间未知时不阻止回退 |

**人工覆盖**（存在运行库 meta 里，带过期时间，过期后下一轮 tick 自动删除并记 `quota_override_expired`）：

```bash
bin/openlabs-container-loop cli -- program quota-override --provider openai-codex \
    --until 2026-11-21T00:00Z --ceiling 0.97 --reason "重置前用完"   # 默认 ceiling = 该提供方的 hard_ceiling
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

已交付稿需要新增研究时，运行 `program revise-delivered --topic-id T --package-id PKG --reason "补充分析任务" --by NAME`。命令绑定当前交付包，调度器等到方向有研究槽和剩余预算后恢复原 campaign，派一次负责人坐席。负责人从已交付版本开启 paper start-revision，保留预注册和已有证据，再走统一评审、版本发布和网站交付。只在收到新包后由人确认投稿。
