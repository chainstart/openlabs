# 四路并行生物医学研究，2026-10-21

用户授权四路深入研究，以2025中科院升级版大类二区及以上论文所需的科学贡献与证据为目标。首轮监督窗口24小时，实际截止时间和授权原文见 `campaign.json`。科学结果不由运行时间或进程完成状态判定。

| 路线 | 研究问题 | 专属代码目录 |
| --- | --- | --- |
| promoter_transfer | 启动子方向性跨报告体系的迁移与失效边界 | `studies/fourlane_promoter_transfer_20261021` |
| drug_support | 药敏拟合标签改善是否对应实验支持的响应与排序改善 | `studies/fourlane_drug_support_20261021` |
| perturbation_context | CRISPRi效力差异与真实供体/刺激情境依赖效应 | `studies/fourlane_perturbation_context_20261021` |
| disease_cell_state | 成人肺纤维化跨队列信号的细胞组成/细胞内状态归因 | `studies/fourlane_disease_cell_state_20261021` |

每路先做近期原始文献和真实数据审计，再冻结方案、执行小规模实验及必要独立验证。每路最多3种有实质差异的候选设计，保留失败、负结果和完整试验账本。旧已暴露确认集不得作为新确认。新论文候选需后续独立科学复核。

当前机器已按仓库锁文件重建基础化学/常规组学和单细胞CPU环境。旧报告的 `/home/biostar/work/openlabs*` 路径属于另一运行环境，原始payload未同步；不能把报告哈希验证当作原实验复算。

每路service在 `openlabs-workers.slice` 内：2核CPU、内存软上限4GiB/硬上限5GiB、swap512MiB、96任务；四路共8核和最多20GiB内存。单一路线下载<=6GiB、scratch<=12GiB，优先小型处理后数据和流式稀疏聚合，CPU工作不启动GPU模型。服务退出时清理同组子进程，不自动重启或延长截止时间。

小型状态在工作区数据仓库 `workspaces/biology/projects/biomed-fourlane-<lane-with-hyphens>-20261021/`；科学payload、模型和进程日志在artifact仓库 `artifact-stage/biomed/four-lanes-20261021/<lane>/`。`process-status.json`是进程状态，`research_status.json`是实际研究进展，`FINAL_REPORT.md`和`RESULTS.json`是科学交付，不能混用。

从代码仓库根运行：

```bash
bin/openlabs-resource-guard --task-type cpu -- python3 labs/biomed/campaigns/20261021-four-lanes/workers.py status
```

首次启动使用同入口的 `launch`，重复启动会拒绝，保留现有日志。各路线说明由 `common.prompt.txt` 与对应路线prompt组成；服务使用本机已配置的Codex模型，不另行覆盖。仅开展研究，不触发全局工厂、投稿、付费、对外消息或公开发布。

2026-10-21 非正常关机后按用户授权恢复，单路硬限降至5GiB、软限4GiB，原截止时间及二区研究目标保持。旧运行日志归档于各路线artifact的recovery目录，科学计划和产物原地保留。
