# OpenLabs 首次迁移报告

- 执行日期：2026-08-07
- 迁移方式：复制当前工作树，源仓库保持不变
- 目标：先形成可恢复、可验证、可继续研究的个人最小系统，不保留旧系统的全部复杂度
- 最终快照切点：2026-08-07 17:23（Asia/Hong_Kong）；源仓库此后新增内容需再次增量导入

## 1. 代码迁移

| 来源 | OpenLabs 位置 | 处理 |
|---|---|---|
| `amra` | `labs/math/skills/amra-research-loop`、`labs/math/tools/formal/` | 保留机制优先数学循环、阶段门、Schema、测试和 Lean 源码；排除 campaign、scratch、`.lake` 和构建缓存 |
| `aira` | `labs/ai/aira` | 保留 bundle、registry、基准、执行、深化、评估和实验记忆工具；全局调度交给 OpenLabs |
| `goai/matfactory` | `labs/materials/src/matfactory` | 保留材料协议、仿真/分析、数值门、队列、watchdog、审计和小型冻结科研输入；不迁入旧 `runs` 大型运行树 |
| `ara-paper-writing` | `workflows/paper` | 保留 registry/bundle/build/review/support 的确定性代码、三套协调 Skill 和已审计 vendored Skills；默认关闭 Zenodo 与远程 handoff 写操作 |
| `ara` | 新 `orchestrator` 与 `orchestrator/skills/vendor` | 复用经审计的 paper/database lookup Skill；manifest、dispatcher、bundle ingest、阶段限制和事件思路被精简重写，没有复制旧巨型固定流水线、dashboard、历史 projects 或重复论文逻辑 |

旧包名 `aira`、`matfactory` 和若干 `ara.*` Schema 暂时作为兼容标识保留。首次迁入时的任务
边界是 `openlabs.task.v2`；当前控制面已以加法迁移升级为带 attempt、Agent 和资源预留的
`openlabs.task.v3`。结果包保持 `openlabs.result_bundle.v1`，避免改写已有证据哈希；任务协议
升级不修改历史结果。

## 2. 新写的最小控制面

`orchestrator/src/openlabs` 是标准库实现，负责：

- 三个实验室 manifest 发现；
- SQLite campaign/task/event/result/research-record 索引；
- 原子任务文件、租约、心跳、有限重试和过期恢复；
- 独立 worker、Agent 有界超时和进程组终止；
- 结果 receipt、路径边界、SHA-256、Claim–evidence 和 paper-candidate 门；
- `cheap` / `balanced` / `frontier` runner 档位，具体模型留在本机配置；
- 文件状态到可移植数据库 JSON export 的重建脚本。

领域 Agent 不 import 或写 SQLite。任一任务进入 `needs_human`、`needs_replan` 或
`quarantined` 后，其他 campaign 仍能被调度。

## 3. 状态迁移

实际清单位于私有 data 仓库的
`ledger/migrations/legacy-import-2026-08-07.json`，当前包含：

- 38 个 AMRA campaign，归并为 4 个开放问题族；
- 1,029 个数学 campaign/探索文件；
- 活跃 `opg-1757-transverse-lift-round7` 的 scratch 探索/证书脚本；
- 2 个材料 campaign：已停止的 LLZTO 长周期研究以 `paused` 接入，当前隐藏有序/软模发现
  试点以 `active` 接入；共保留 99 个小型 supervisor/protocol/analysis 状态文件和最新
  novelty audit；
- 45 条论文 registry、2,608 个论文源码/证据文件、345 个 review 文件；
- 235 个旧 PDF/ZIP/TAR 本地兼容产物，物理迁入 artifacts，但被 Git 忽略；
- SQLite 中 40 条 campaign 与 89 条初始研究索引；database 仓库保存 JSON export，
  `live/factory.sqlite` 被忽略。

迁移过程中旧仓库仍被其他研究会话更新，因此只导入明确的已提交切点。增量同步后，
matfactory 已与清洁 commit `175c7b69291e48850055495e7dd60f942c54a761` 对齐；
`ara-paper-writing` 的 5 个已提交 release record 已同步至
`e772c743c0c24a7cd8399108e3487494188f2180`。该论文源仓库随后出现的 56 个未提交修改没有被
静默带入；清单记录了它们的 status 指纹。AMRA 仍有 1 个 dirty entry，ARA 与 AIRA 清洁。
本迁移过程没有写入这些源仓库。

matfactory 的旧 `runs` 树约 23 GiB，包含 587 个 DFT/轨迹/运行文件，没有复制进代码或
openlabs-data Git。依赖这些精确证据的 LLZTO 任务保持暂停；恢复前必须将所需文件迁入
openlabs-artifacts 或明确只读挂载，并逐项绑定 URI 与 SHA-256。

## 4. 验证结论

- OpenLabs 控制面、Agent 会话/角色隔离、结构化 handoff、attempt 绑定、预算、并发、
  自动续接/升级、重试/进程组清理及三实验室 smoke：29 项通过；
- AMRA research-loop：5 项通过；38 个迁移 campaign 中 31 个当前阶段门通过，7 个
  `independent_audit` campaign 因尚无 promotion decision/evidence 而按原规则失败；这是待审计
  科学状态，不是复制损坏；当前 `opg-1757-transverse-lift-round7` 验证通过；
- AIRA：55 项测试通过；
- 论文工作流：98 项通过；迁移后的 45 篇 registry 整体有效、0 error、81 warning。warning
  来自按策略未追踪的编译 PDF，以及部分早期论文尚无 claim map；
- matfactory：使用原项目完整 discovery 环境时 358 项通过；10 项依赖未迁入代码仓库的旧
  runtime hash-bound evidence/历史 lock，被显式标为可选 legacy-evidence integration test，
  默认跳过，绝不伪造通过；新迁入的候选采集、结构枚举、双模型弛豫、软模和 DFT 确认代码
  均包含在通过项中；
- 8 个 OpenLabs 协调 Skill 均通过 skill-creator 的结构校验。

合计 545 项测试通过、10 项外部 legacy-evidence 集成测试跳过。

## 5. 尚未自动执行

- 四个仓库使用与远端一致的本地名称；`openlabs` 公开，`openlabs-data`、
  `openlabs-artifacts`、`openlabs-database` 私有；
- 没有启用 systemd timer；
- 没有配置或启动收费 Agent；
- 没有自动续跑任何数学、AI 或材料研究任务；
- 没有投稿、公开发布、创建 Zenodo draft 或调用远程论文管理服务。

建议启用顺序是：配置一个本机 runner → 手工复核三领域 smoke → 只排入当前 OPG-1757 的
一个有界继续任务 → 检查结果门和成本 → 再启用 timer。不要一次性恢复旧 ARA 的全部项目
队列。
