# Physics Lab 运行约束审计

审计日期：2026-08-26。

## 权限边界

Codex worker 与 `bin/openlabs-codex` 都使用 `approval_policy=never` 和
`danger-full-access`。这符合“单人、本机、本人账号”的信任模型，也使编译器、求解器、网络和
跨仓库只读材料不被文件沙箱阻断。代价是 attempt workspace 只是默认 cwd 和事务约定，不是
内核写隔离；该配置不适合直接迁移到多用户主机或处理不可信脚本/数据包。

## 聚合与任务资源

- 所有 worker、交互式 Codex 和重计算共享 `openlabs-workers.slice`：本机 15 CPU（20 的
  75%）、30 GiB memory high、34 GiB memory max、4 GiB swap、512 tasks。
- 调度准入同样只暴露宿主机 75% CPU，并额外保留 8 GiB 内存和 64 GiB 临时盘；任务仍需声明
  CPU、内存和 scratch 峰值。
- `max_worker_processes=8` 是错误申报保险，同一 campaign 仍串行。
- 默认调度任务墙钟上限为 12 小时；示例 Agent 环境的 provider 超时为 4 小时，因而可能更早
  结束。普通 campaign/连续 production epoch 的 Agent 累计窗口是 24 小时，自动后继最多
  24 个任务，然后停下或换 epoch。

这些值适合当前约 39 GiB RAM/20 线程 WSL：内存、swap、tasks 与 OpenMath 对齐；OpenMath
没有 CPUQuota，15 CPU 来自 OpenLabs 原有的 75% 策略。它们防止整机失去响应，但不是每个
物理算法都应吃满的目标；高截断/大事件样本仍应从小规模收敛研究开始。

## 科学与副作用门禁

- 可做解析推导、符号/数值计算，也可下载并分析许可清晰的公开实验或观测数据。
- 不执行现实物理实验、不控制仪器、不提交量子硬件任务。
- 数据必须记录来源、条款、引用、版本、字节数和 SHA-256；原始数据不可覆盖，凭据/受限数据
  不进入仓库。
- 计算必须记录代码、输入、环境锁、输出、命令、精度、随机性、收敛和误差预算。
- `verified` 结论至少需要两个独立证据组；同一代码或同一推导被两个 Agent 重复不算独立。
- 当前尚未注册 physics 专用论文写作/审稿 rubric。研究结果可进入不可变 result bundle，但
  不会自动进入物理论文发布链；投稿、Zenodo、远程 handoff 等外部动作也没有默认授权。

这些科研门禁是合适的：它们约束证据强度和外部副作用，而不把研究过程硬编码成固定阶段。
物理论文 rubric 是明确的后续缺口，不应借用数学或材料 rubric 假装已经覆盖。

## 状态与产物

| 内容 | 位置 | 性质 |
|---|---|---|
| 项目/claim/小型代码与 manifest | `openlabs-data/workspaces/physics/...` | 私有、可版本化 canonical 状态 |
| 当前暂停的选题项目 | `openlabs-data/workspaces/physics/projects/physics-open-problems/` | 控制面可发现但不会启动 |
| 私有运行副本 | `openlabs-artifacts/attempt-workspaces/...` | 失败/取消时隔离保留 |
| 公共数据副本、数组、模型与大输出 | `openlabs-artifacts/experiments/<campaign-id>/` | 私有大产物，按 URI/哈希引用 |
| 通过门禁的结果快照 | `openlabs-artifacts/result-bundles/...` | 不可变归档 |
| campaign/task/lease/attempt 索引 | `openlabs-database/live/factory.sqlite` | 单写者活库，不直接手改 |

仓库中 `openlabs-data/openlabs-database/live/factory.sqlite` 还有一个空的历史重复路径；实际活库
是外层 `openlabs-database/live/factory.sqlite`。本次没有删除或迁移该文件，以免把路径清理
误当成授权的数据删除。
