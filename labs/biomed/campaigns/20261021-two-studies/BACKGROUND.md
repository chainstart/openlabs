# 一天研究任务的后台运行

2026-10-21 08:51（香港时间）实际检查：两个独立研究进程均已启动模型会话、执行读取命令和文献检索。
它们是 systemd 用户服务，独立于本次前台聊天的生命周期，最晚于 **2026-10-22 08:10** 停止。
充分完成或候选穷尽时可以提前结束；没有设置循环重启或后续定时任务。
这是执行状态，不代表已经得到两项论文成果。

| 研究线 | 服务 | 新的小型研究工作区 |
| --- | --- | --- |
| 功能基因组学：从已完成的 CRISPR 负结果出发，筛选独立问题和数据 | `openlabs-biomed-day1-functional-genomics-20261021.service` | `openlabs-data/workspaces/biology/projects/biomed-functional-genomics-day1-20261021/` |
| 药物反应：审计剂量支持下的性能失真，并用独立数据继续验证 | `openlabs-biomed-day1-drug-response-20261021.service` | `openlabs-data/workspaces/biology/projects/biomed-drug-response-day1-20261021/` |

每条研究线最多筛选六个实质不同候选，选最强一个实际研究；不是要求在同一测试集反复找显著性。
已完成的三个试点目录全部只读。新方案/数据/结果写新目录，负结果、原始输入与已用测试标记保留。
最新目标为 2025 年中科院升级版大类二区的科研质量潜力，尚未选刊，不授权支出、投稿或公开发布。

## 日志、进展和报告

运行根目录：`/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-workers-20261021/`。
每条研究线各有一个子目录 `functional_genomics/` 或 `drug_response/`：

- `process-status.json`：监督进程的 PID、cgroup、心跳、截止时间和最终退出状态。
- `events.jsonl`、`agent.stderr`：真实执行事件和运行日志。
- `research_status.json`：研究者按实质步骤更新的科学进展，创建前不能视为已有结果。
- `FINAL_REPORT.md`：研究者完成时写的中文科学报告；超时可能只有已有检查点。
- `agent-final-message.md`：该工作者正常结束时的最后消息。

`launch-receipt.json` 保存 08:51 的真实服务快照、已启动的会话 ID、监督代码和任务提示哈希。
进程完成不代表科研目标实现，监督器始终不自动认证 `paper_candidate`。
判断是否仍在运行，应以服务当前状态为准，不能凭旧的 `running` 字段或已过时的日志判断。

## 资源和终止

两者均在 `openlabs-workers.slice` 内，各限 2 个 CPU、1.5 GiB 内存软限制、2 GiB 硬限制、
512 MiB swap、96 tasks。两者共享仓库总护栏，不使用 CUDA。原始数据/模型由该服务的同一 cgroup 约束。
systemd 运行时限和监督器 UTC/单调时钟双重截止，`KillMode=control-group` 清理剩余后代。
启动器的四项检查验证了无护栏拒绝、过期拒绝、双任务独立上限及重复启动保护。

从代码仓库根目录查询当前状态：

```bash
bin/openlabs-resource-guard --task-type cpu -- labs/biomed/.venv/bin/python labs/biomed/campaigns/20261021-two-studies/workers.py status
```

如需提前终止两者：

```bash
bin/openlabs-resource-guard --task-type cpu -- systemctl --user stop openlabs-biomed-day1-functional-genomics-20261021.service openlabs-biomed-day1-drug-response-20261021.service
```

不重复运行 `workers.py launch`。它会拒绝覆盖已有进程记录；恢复失败任务前必须保留原始证据、检查失败原因，
并确认没有实际研究进程或被消耗的测试集被重复运行。

## 启动中的已解决问题

首个启动尝试因 systemd 用户服务未继承当前 shell 的代理环境，在网络预检阶段退出 69，未开始科研。
原始日志完整保存在各研究线 `attempt-0-network-preflight-failed/`。
随后通过仓库现有 `network-preflight` 验证当前代理，并同步其私有配置和用户服务环境，再重新启动；
第二次尝试已实证产生会话、工具执行和检索事件。没有绕过网络或资源预检。

执行使用现有 `bin/openlabs-codex` 和
[官方非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)，结果输出由监督器保存在本地。
不涉及外部通知或自动向本聊天发送到期消息。
