# 统一评审流程设计（编辑初审 + 审稿人评审）

状态：已确认并实现（2026-10-06）；2026-10-09 临时调整见下。用户确认：取消 5/10 分数门槛；每个目标期刊最多 3 轮（2026-10-07 用户改为 10 轮）；旧 closeout 类路径停用；
当前编辑与唯一启用的审稿人 B 均使用独立 Codex（gpt-6.1-sol）进程。Claude 审稿人 A 因不可用暂时关闭，依据用户 2026-10-09 指令；原双模型设计留作历史说明。
暂缓：新格式下的元数据复用（目前统一流程模式下一律重新评审）。

## 1. 目标

评审只做一件事：在投稿前尽量逼真地模拟**目标期刊**的编辑和审稿人，尤其是尽量避免桌拒。
内部评审的结论必须能和真实期刊的决定对得上；对不上就是流程的缺陷，而不是论文的运气。

不变的原则：审阅者在全新进程中工作，看不到作者会话和以往评分；确定性代码只做校验和合并，
不产生判断；任何阻塞问题不能被投票或分数抹掉；评审结论不授权投稿、发布或任何外部写入。

## 2. 现状的问题（证据见 2026-10-06 分析）

1. **路径过多。** 全文评审、增量评审、元数据复用、minor closeout、targeted closeout、
   editorial closeout（Bubblewrap 重放）、editorial follow-up（两处 elsarticle 排版）、
   目标期刊编辑筛查，共 8 条，多数为单次事件临时增加；另有 71 份门禁例外记录。
2. **标尺与目标脱节。** 数学稿件对照 Annals/Inventiones/JAMS/Acta 打分，再给一个泛化的
   “中科院 1 区”意见。注册表中有内部评审的 39 篇里，35 篇“1 区”意见为接收或小修，
   而“高标准”意见几乎全是拒稿：泛化意见没有区分力。实际投稿的 8 篇 12 次全部桌拒。
3. **顺序颠倒。** 真实流程是编辑先决定是否送审；这里编辑筛查是事后追加，拒稿信只在这一步使用。
4. **迭代过拟合。** 单篇最多 22、31 轮。每次“结论过强”的意见都被一句免责声明打发，
   稿件因此堆满“我们不声称……”。流程不禁止这种回应。
5. **单一审阅者且与作者同系**（Codex 写、Codex 审），第二审阅者默认关闭。

## 3. 新流程（唯一主线）

```
投前检查 ──► 编辑初审 ──► 审稿人评审（2 人，盲审） ──► 编辑决定 ──► ready / 返修 / 补证据 / 换刊
   ▲              │ 桌拒或投前需改                                          │
   └──────────────┴──────────────── 返修（逐条回复，最多 10 轮/目标期刊） ◄──┘
```

### 阶段 0：投前检查（确定性，不打分）

复用现有检查：`style-check`、`support-check`、AI 声明、目标期刊记录（分区、收费、格式、
契合度、拒稿记录）、源码包清洁度（新增：源码包中不得有未被编译读取的 `.tex/.sty/.cls/图`）。
任一失败即停止，不启动任何模型。

### 阶段 1：编辑初审（模拟桌拒）

一个全新进程扮演**该目标期刊的处理编辑**，只看编辑真正会先看的东西：

- 输入：标题、摘要、引言、主要定理/结果的陈述、参考文献列表、投稿信（若有）；
  目标期刊的官方范围说明与注册表中的近期同类文章；最接近的已发表工作；
  **本论文及其前身收到的全部拒稿信**（原文摘录，标明哪些是编辑原话、哪些是内部解读）。
- 不给：证明细节、内部评审、分数、作者会话。
- 必须产出：
  - `contribution_in_two_sentences`：编辑用自己的话复述贡献。复述不出或与摘要不符，即表达不过关。
  - `closest_prior_work` 与 `advance_over_prior_work`：在相同假设下比较。
  - `strongest_desk_reject_reason`：编辑最可能的拒稿理由，归入固定类别
    `scope | significance | readership | novelty_unclear | presentation | incremental`。
  - `prior_rejections_addressed`：逐封拒稿信说明当前稿件如何回应；仅换刊或改措辞不算回应。
  - `decision`：`send_to_review` | `desk_reject` | `revise_before_submission`。
- 标尺：**目标期刊本身**的一般送审标准（按其分区和近期文章校准），不再对照顶刊或泛化的 1 区。

`desk_reject` 时不进入审稿；依理由类别给出唯一的下一步：`revise_before_submission`（表达）、
`evidence_remediation`（需要新结果）或 `retarget_required`（需要用户决定换刊）。

### 阶段 2：审稿人评审（两人，盲审，互不可见）

- 两个全新进程，**不同模型**（有条件时不同厂商）。每人读完整冻结稿、证据映射与支撑材料。
- 检查正确性（证明依赖、量词、边界情形）、文献与先前工作、论据与代码/数据的对应、清晰度。
- 建议用**目标期刊**的词汇：`accept | minor_revision | major_revision | reject`，并分开列出
  `scientific_blockers`、`required_changes`（每条注明类型 `text | evidence | claim_narrowing`）、
  `optional_suggestions`。
- 新增硬性规则：凡出现“为回应批评而增加的免责/限定段落”而非修改结论或结构，审稿人须列为
  `presentation` 问题；内部流程叙述（脚本名、版本沿革、审阅过程）一律列为阻塞。

### 阶段 3：编辑决定（确定性合并 + 一次编辑综合）

- 确定性合并：两份建议取更保守者；阻塞问题取并集；任何阻塞都不能被抹掉。
- 编辑综合（全新进程，可见两份审稿意见但不可见作者会话）只写决定信，不得改变合并结论。
- `ready` 的条件：阶段 1 为 `send_to_review`，阶段 3 合并结论为 `accept` 或 `minor_revision`
  且只剩文字类意见，阶段 0 全部通过。不再使用 5/10 分数门槛（分数仍记录，仅供参考和校准）。

### 返修（唯一的返修路径）

- 作者逐条写回复信（`response_letter`），每条说明“改了什么、在哪里”。
- 复审：同样两个审稿角色在**新进程**中看累计差异、回复信和上一轮意见（不看分数）。
  现有增量机制（冻结基线、累计差异、哈希绑定）并入这里。
- 禁止以增加免责声明回应“结论过强”；必须改结论、改结构或补证据。
- 每个目标期刊最多 10 轮（2026-10-07 由 3 轮改为 10 轮）。用尽后状态为 `blocked`，由用户决定（换刊、补研究或放弃），
  不再新增轮次例外。
- 元数据复用（只改作者/联系方式等）保留为确定性路径，不启动模型。

## 4. 记录格式

新增三个 schema（JSON，放在 `reviews/<run_id>/<paper_id>/`）：

- `openlabs.review.editor_screen.v2`：阶段 1 的全部字段，加 `target_journal`、
  `manuscript_snapshot_sha256`、`inputs_manifest`、`model`、`provider`。
- `openlabs.review.referee.v1`：阶段 2 每位审稿人一份。
- `openlabs.review.decision.v1`：阶段 3 合并结果与决定信，引用前两者的哈希。

`writing_release` 只认 `decision.v1` 产生的结论；旧格式（`ara.paper_writing.review.v2`、
`review.single.v1`、各类 closeout 证书）保持可读，但不能再使任何论文进入 `ready`。

## 5. 模型与独立性

- 审阅进程通过一个与厂商无关的启动器运行，配置在 `registry/settings.yaml#review`：
  每个角色指定 `provider`、`model`。记录必须写入**实际**运行的模型，不得冒充。
- 本机只有 Claude Code，没有 Codex。建议本机配置：编辑与审稿人 A 用 `claude-opus-5-5`，
  审稿人 B 用另一模型（如 `claude-fable-5-1`）；有 Codex 的机器上，审稿人 B 改用 Codex。
  若两位审稿人同一厂商，决定记录中如实标注 `same_provider_panel: true`。
- 已知局限：这 8 篇是由 Claude Opus 5.5 修改的，用同一模型审稿存在相关盲点；所以至少一位
  审稿人应使用不同模型。

## 6. 校准

新增 `review calibration` 命令：从管理网站拉取真实投稿事件（送审、桌拒、录用），与当时的
阶段 1/3 结论对照，输出混淆表。若内部 `send_to_review` 的论文仍频繁被桌拒，则收紧阶段 1
标尺。校准只读，不修改任何历史记录。

## 7. 代码改动

| 位置 | 改动 |
|---|---|
| `paper_writing/review_flow.py`（新） | 阶段编排、记录校验、确定性合并、`ready` 判定 |
| `paper_writing/review_launcher.py`（新） | 与厂商无关的审阅进程启动器（Claude Code、Codex），输入清单与哈希绑定 |
| `paper_writing/operations.py` | `record_quality_gate` 改为只接受 `decision.v1`；保留旧记录读取 |
| `paper_writing/review_delta.py` | 作为返修复审的差异包生成器复用 |
| `paper_writing/__main__.py` | 新命令 `review run / screen / referee / decide / respond / calibration`；旧 closeout 命令对新工作返回明确错误 |
| `paper_writing/handoff.py` | 交接时校验 `decision.v1` 与编辑初审记录（替换 `editorial_screen` 绑定） |
| `skills/openlabs-paper-review/` | SKILL.md 重写为本流程；新增编辑、审稿人提示与评分细则（按目标期刊层次） |
| `skills/overlays/quality-gate.md`、`docs/` | 同步改写；旧文档标为历史 |
| `registry/settings.yaml` | 新增 `review` 配置；`quality_gate` 去掉分数门槛与 CAS 1 区标准 |
| `tests/` | 新流程单元测试；旧路径“不能使论文 ready”的回归测试 |
| 调度器 `engine.py` | 不改：评审任务仍只返回“通过 / 文字返修 / 补证据”三者之一 |

## 8. 迁移

- 当前已无任何“可投稿”论文（2026-10-06 全部撤下）。
- 旧评审记录、分数、例外记录一律不改，只读保留。
- 首批用新流程评审：本次改写的 8 篇，以及 3 篇旧流程门禁（20260608mathgraph0006、
  20260815-math-number-green28-zero-one-factors、20260506aiuncertainty0010）。

## 9. 需要用户确认的事项

1. 是否采用上述流程与 `ready` 条件（取消 5/10 分数门槛）。
2. 本机审稿模型：编辑与审稿人 A 用 `claude-opus-5-5`，审稿人 B 用不同模型；是否接受
   本机暂无 Codex 的“同厂商双审稿人”，或先在本机安装并登录 Codex。
3. 每个目标期刊最多 3 轮返修，用尽即停，不再新增例外。
4. 旧 closeout 类路径对新工作停用（历史记录保留可读）。

## 2026-10-09 实施调整

编辑初审必须逐封读取原拒信（原文与源 SHA-256），将当前稿件判为已实质克服
`resolved`，或以目标期刊的具体范围、读者和贡献门槛说明仍与原拒信不矛盾
`compatible`。缺原文、漏评、未克服或矛盾的情况不能继续到审稿。仅换刊、改措辞
或作者自称已修复不满足条件。拒信缺失须恢复原信，不得由摘要生成原文。

`review.referee_roles: [referee_b]` 暂时只启动一个 Codex 审稿人；不假装完成 Claude
或双模型评审。原文证据与活动角色配置均绑定决定记录，政策改变后旧门禁不能沿用。
网站可投稿状态仅由当前政策和最新版稿件的完整 ready 决定产生。
