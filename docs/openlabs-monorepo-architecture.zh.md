# OpenLabs Monorepo 架构决策

- 状态：初始架构基线
- 日期：2026-08-07
- 适用范围：个人使用、可持续 24 小时运行的跨领域科研工厂
- 初始领域：数学、材料科学、AI/ML

## 1. 总体决策

科研工厂采用以下基本形态：

1. 所有稳定源代码进入一个干净的 OpenLabs monorepo。
2. 研究数据、大型产物和数据库与代码在物理目录上分离。
3. OpenLabs orchestrator 是薄控制面，不拥有任何领域的科研真相。
4. 数学、材料、AI/ML 实验室和论文写作系统是独立子项目。
5. 子项目之间不直接调用彼此的内部 Python API，只通过版本化文件协议、最小程序入口和 artifact URI 交换任务、状态和成果。
6. 工厂以短生命周期 tick、独立长任务和持久状态实现连续运行，不依赖一个永不退出的大 Agent 会话。
7. Agent 主导研究选择和执行；确定性代码掌握状态迁移、证据验证、资源限制和不可逆操作。

该结构优先满足当前个人使用的轻量要求，同时保留未来迁移到服务器、多用户和远程 artifact store 的边界。

项目、领域协议和 Codex 连续执行的可插拔接口见
[project-protocol-architecture.zh.md](project-protocol-architecture.zh.md)。控制面只理解通用
`openlabs.project.v1` 外壳；领域状态由实验室注册的 protocol validator 在发现和事务提交
两个时点验证。

## 2. 四层物理存储结构

~~~text
/home/biostar/work/projects/openlabs/       # 非 Git 工作空间
├── openlabs/                               # 代码 Git monorepo
├── openlabs-data/
├── openlabs-artifacts/
└── openlabs-database/
~~~

### 2.1 openlabs

内层 openlabs 子目录是真正的 Git monorepo，只保存：

- OpenLabs 编排控制面代码；
- 各领域实验室的稳定代码；
- 论文写作服务代码；
- 稳定、可复用的 Skill；
- 接口 Schema 和示例；
- 共享研究基础库；
- 单元测试、契约测试和部署配置；
- 架构与操作文档。

以下内容不得进入 openlabs 代码 Git：

- 运行数据库和 Agent 会话状态；
- campaign 工作区；
- 原始仿真输出；
- 模型权重、检查点和大型数据集；
- 临时日志、缓存和编译产物；
- 只为单次实验产生且尚未晋升的脚本。

### 2.2 openlabs-data

openlabs-data 保存可读、可审计、规模适中的研究记录和活动工作区：

~~~text
openlabs-data/
├── ledger/                 # 问题、Idea、Claim、决策和社区进展
├── workspaces/
│   ├── math/
│   ├── materials/
│   └── ai/
├── papers/                 # 论文源文件和期刊版本，统一由 openlabs-data 仓库追踪
├── literature/             # 文献清单、结构化笔记和索引清单
└── inbox/                  # 外部导入或待人工确认的材料
~~~

openlabs-data 是一个整体的私有 Git 仓库。结构化状态、实验脚本、论文 TeX/Bib、图源和审稿记录
统一追踪；运行 inbox、缓存、编译 PDF、压缩包、模型权重和可重建的大型输出通过
`.gitignore` 排除。个人阶段只有一个写入者，单仓库比为每个 campaign/论文维护大量小仓库
更简单；未来出现多用户高冲突后再按边界拆分。

### 2.3 openlabs-artifacts

openlabs-artifacts 保存大型、不可变、可通过哈希寻址的产物，例如：

- 材料模拟轨迹和波函数输出；
- AI/ML 数据集、模型权重和训练检查点；
- 大规模枚举结果；
- 压缩结果包；
- 本地编译 PDF、提交包、模型权重、轨迹和其他大型附件；
- 外部工具产生的大型中间文件。

论文相关产物在逻辑上属于论文，但在物理存储上仍属于 openlabs-artifacts。仓库同时保留按
业务对象组织的可浏览路径和内容哈希：

~~~text
openlabs-artifacts/
├── papers/
│   └── <paper-id>/<journal-id>/<version>/
│       ├── manuscript.pdf
│       ├── figures/
│       ├── supplement/
│       └── manifest.json
├── experiments/
│   └── <campaign-id>/...
└── objects/
    └── sha256/<前两位>/<完整哈希>/...
~~~

openlabs-data/papers 下的论文记录保存源码和 artifact manifest；编译 PDF、渲染图片和补充
材料实体位于 openlabs-artifacts/papers。底层 objects 目录按内容哈希去重，URI 使用 file
协议。

### 2.4 openlabs-database

openlabs-database 保存可重建的运行状态和查询索引。个人最小版本只使用一个
`live/factory.sqlite`，其中包含 campaign、task、lease、event、result 和 research-record
表；Git 只追踪 `exports/current/*.json` 及其哈希 manifest，SQLite/WAL 永远忽略。未来只有
在查询规模或多用户并发确实需要时，才拆分独立研究索引或迁移 PostgreSQL。

数据库不是研究事实的唯一来源。工厂应能从 ledger、事件日志和不可变结果包重建主要索引，避免单个数据库损坏后丢失研究历史。

### 2.5 Git 边界

| 路径 | 是否使用 Git | 理由 |
|---|---|---|
| 外层 openlabs | 否 | 它只是聚合多个存储域的工作空间 |
| 内层 openlabs | 是，一个 monorepo | 稳定代码、Schema、Skill、测试和部署配置需要统一版本 |
| openlabs-data | 是，一个私有仓库 | 追踪可合并的研究状态、实验源码、论文源码和 reviews；忽略运行/编译产物 |
| openlabs-artifacts | 是，一个私有 manifest 仓库 | 追踪 URI、哈希和小型最终记录；大型 payload、PDF 和可重建二进制忽略 |
| openlabs-database | 是，一个私有导出仓库 | 追踪可移植 JSON 导出和 manifest；live SQLite/WAL 永远忽略 |

四个子目录各自独立 Git，外层聚合目录不建 Git。Git 只解决源码和可合并状态的版本历史；
大型 artifact 仍需文件快照或未来对象存储，live SQLite 仍需一致性 backup，不能通过 Git 合并。

## 3. OpenLabs monorepo 目录

~~~text
openlabs/
├── orchestrator/                    # 薄控制面和编排 Skill
│   └── skills/
├── labs/
│   ├── math/
│   │   ├── skills/
│   │   └── tools/
│   ├── materials/
│   │   ├── skills/
│   │   └── tools/
│   └── ai/
│       ├── skills/
│       └── tools/
├── workflows/
│   └── paper/
│       ├── skills/
│       ├── paper_writing/
│       └── tests/
├── packages/
│   ├── contracts/
│   │   ├── schemas/
│   │   └── examples/
│   └── research-core/
├── deploy/
│   └── systemd/
├── tests/
│   └── contracts/
└── docs/
~~~

### 3.1 OpenLabs 编排控制面

orchestrator 只负责：

- 实验室发现和能力注册；
- 全局问题组合、优先级和预算；
- 任务队列、租约、并发、重试和隔离；
- 模型和 Agent runner 路由；
- 结果包接收与 Schema 校验；
- 跨领域 Claim 和论文候选索引；
- watchdog、通知和管理员控制。

orchestrator 不包含数学证明策略、材料物理判据或 AI/ML 评测细节。AMRA、matfactory、AIRA 等历史名称可以保留为内部 Python 包名和 manifest 中的 lab ID，但不再形成额外目录层级。

### 3.2 领域实验室

各实验室拥有自己的：

- 领域 Skill 和研究阶段；
- 实验与验证工具；
- 领域 oracle；
- 内部状态机；
- 结果包扩展 Schema；
- 环境、依赖和测试。

实验室不能直接 import 另一个实验室。跨领域研究由 OpenLabs orchestrator 建立多个子任务并组合结果包，不通过共享内部对象实现。

### 3.3 论文工作流

workflows/paper 是所有领域共用、按需调用的下游工作流，不是常驻服务：

- 只读取经过验证的 Claim、证据和结果包；
- 不直接读取实验室私有运行目录；
- 使用 Skill 生成提纲、草稿、图表说明、期刊改写和审稿任务；
- 使用确定性代码完成 registry、结果包、构建、引用、质量门和不可变版本校验；
- 初期默认在投稿、公开发布和产生外部副作用之前等待管理员批准。

对现有 ara-paper-writing 的检查表明，ara-ai-paper 和 ara-math-paper 已能作为 AI/ML 与数学论文的薄协调 Skill；审稿现由空白 Codex 与经 Packy 调用的空白 Claude Code Opus 5 组成双供应商面板。它们依赖 vendored 写作/统计/审稿 Skill、仓库 registry、claim-evidence map，以及约 7,400 行 paper_writing 确定性 Python。纯复制 Skill 只能获得写作方法，不能获得可审计论文流水线。

迁入 OpenLabs 时保留“Skill 决策层 + 薄确定性 workflow”：

- skills：领域写作、期刊适配、审稿和修订策略；
- src：registry、bundle、build、citation、保守双审阅人聚合和状态门；
- templates：论文、期刊 overlay、cover letter 和 response 模板；
- tests：协议、构建、引用和门禁测试。

Zenodo、远程 handoff 和真实投稿属于可选外部适配器，不进入第一版最小闭环。

### 3.4 共享包

共享包必须保持克制：

- contracts：Schema、状态枚举和协议示例；
- research-core：规范化 JSON、哈希、原子写入、事件日志和 artifact URI 等真正通用的机械能力；

数学、材料和 AI/ML 的工具直接归各自 labs/<domain>/tools。不得因为代码相似就把领域知识放入 research-core；只有至少两个领域以相同语义使用的能力才考虑进入工厂级公共包。

### 3.5 Workflow、package 和 Skill 的区别

三者不能全部由一个 Skill 替代：

| 类型 | 本质 | 示例 |
|---|---|---|
| workflow | 把 Skill、确定性代码和状态门组合成可恢复的完整任务 | 论文撰写、双供应商审稿和期刊版本构建 |
| package | 可导入、可测试、确定性的稳定代码 | Schema、哈希、统计、仿真分析器 |
| Skill | 告诉 Agent 如何完成某类任务的流程说明、约束和参考材料 | 文献调研、Idea 生成、论文审稿 |

Skill 可以携带少量辅助脚本，但不应承担数据库迁移、并发控制、恢复、数值 oracle 或大型共享库。典型组合是：Skill 决定如何工作，package 提供可靠工具，workflow 负责把多步过程、状态和门禁连接起来。只有未来确实需要独立常驻进程或网络 API 时，才新增 service 概念。

## 4. 接口和解耦规则

子项目间的耦合只允许存在于显式版本化协议中。初始需要三类协议。

### 4.1 openlabs.task.v3

描述控制面交给实验室的任务：

- task、attempt、campaign、domain 和 parent ID；
- Agent 角色、会话策略和仅限同 campaign/同角色的可恢复 session ID；
- 目标、阶段和成功标准；
- 输入 artifact URI；
- 墙钟时间以及 CPU 线程、内存、临时盘的峰值预留；
- 允许的工具和外部操作；
- checkpoint、超时和审批策略；
- 推荐模型能力等级，而不是写死供应商模型名称。

### 4.2 运行状态与心跳

worker 将心跳和 lease 续期写回控制面数据库，领域代码不直接写状态库。每次尝试有独立
`attempt_id`；任务、回执、精确输出路径和运行元数据必须绑定同一个 attempt。迟到回执、
非运行状态回执或 campaign/lab/domain/角色不一致的回执一律拒绝并归档。

### 4.3 openlabs.result_bundle.v1

描述实验室交付的成果：

- 输入、代码、环境和配置版本；
- artifact 清单和内容哈希；
- Claim、证据锚点和限制；
- 验证、复现和独立审计状态；
- 下一步建议；
- 论文就绪信号。

AMRA、matfactory 和 AIRA 可以保留更严格的内部结果 Schema，但必须由确定性 adapter 输出统一结果包。

所有状态文件先写临时文件，再通过同文件系统原子 rename 发布。并发写入使用租约或文件锁；大型 payload 只通过 URI 引用。

## 5. 源代码和研究数据的边界

实验期间产生的代码分为两种：

1. 工厂和实验室的稳定源代码；
2. 为单个科研任务即时生成的研究代码。

第二类代码初始属于 openlabs-data/workspaces 下的 campaign，应与该任务的配置、笔记和小型
结果一起冻结。结果包必须记录：

- 代码 Git commit 或不可变快照；
- 相对源码路径和 diff；
- 依赖锁文件；
- 容器或系统环境指纹；
- 数据和输入哈希；
- 参数、随机种子和执行命令；
- stdout、stderr 和结果哈希。

只有现实中出现第二个独立 campaign 的相同需求，并由普通代码审查补齐契约和回归测试后，
它才进入 `labs/<domain>/tools`。这样可避免为假设中的复用预建注册表，也避免 Agent 把一次性
脚本混入稳定代码历史。

### 5.1 论文数据与期刊版本规范

论文采用“逻辑聚合、物理分层”原则。每篇论文在 data 私有仓库下拥有独立目录，但初期不
再嵌套 Git：

~~~text
openlabs-data/papers/<paper-id>/
├── paper.yaml
├── canonical/
│   ├── manuscript/
│   ├── references.bib
│   └── figures-src/
├── journal-candidates.yaml
├── targets/
│   └── <journal-id>/
│       ├── journal.yaml
│       ├── manuscript/
│       ├── cover-letter.md
│       ├── highlights.md
│       ├── graphical-abstract/
│       └── revisions/
│           └── <round-id>/
│               ├── request.md
│               ├── response-to-reviewers.md
│               └── change-map.yaml
└── artifact-manifest.json
~~~

canonical 保存与具体期刊无关的科学内容基准。journal-candidates 记录候选期刊、匹配理由、约束和风险。选定期刊后，在 targets/<journal-id> 下形成实际投稿版本。

journal.yaml 至少记录：

- 期刊名称、稳定 ID、官方网站和要求访问日期；
- scope、文章类型、字数和图表限制；
- 模板、引用格式、双盲和补充材料要求；
- 数据、代码、AI 使用和开放获取政策；
- 模板或要求快照的哈希；
- based_on_commit，即该期刊版本源自 canonical 的哪个提交；
- 当前状态和修订轮次。

期刊目录初期使用普通目录而不是大量 Git branch。纯格式变化只保留在 target；新增实验、证明、数字、Claim 或实质性解释必须回灌 canonical，再从新的 canonical commit 形成期刊修订版本。

figures-src 保存可编辑、可复现的图源和绘图配方，而不是最终图片的链接。例如绘图脚本、样式配置、标注 SVG、Draw.io 源文件和 inputs.yaml。大型原始数据、显微图、模型输出或仿真快照仍位于 experiment artifacts，inputs.yaml 只记录其 URI 和哈希。

最终渲染和提交产物按论文、期刊和版本归档：

~~~text
openlabs-artifacts/papers/<paper-id>/<journal-id>/<version>/
├── manuscript.pdf
├── figures/
├── supplement/
├── cover-letter.pdf
├── response-to-reviewers.pdf
├── submission-package.zip
└── manifest.json
~~~

openlabs-data/papers/<paper-id>/artifact-manifest.json 把论文源码提交与上述产物绑定。工厂
数据库只保存论文状态、期刊、版本、哈希和 URI。

## 6. 24 小时运行模型

### 6.1 systemd timer 与 tick

systemd 是守护和监督层，factory tick 是短生命周期、幂等的一次性进程：

~~~text
systemd user timer
    ↓ 每 3 分钟
python -m openlabs tick
    ├── 接收并验证结果包
    ├── 回收过期租约
    ├── 恢复或隔离失败任务
    ├── 从通过门禁的 next_actions 续接一个有界任务
    ├── 将 NEEDS_REPLAN 升级到高级 runner
    ├── 按 CPU/内存/临时盘余量租赁并启动任务
    └── 保存状态并退出
~~~

3 分钟只是调度和回收的检查周期，不是 worker 超时。有效租约上的 worker 由 tick 启动为
`openlabs-worker-*.service` transient systemd user service，位于独立的
`openlabs-workers.slice`，可以跨越任意多个 tick，直到节点完成、硬超时或失去租约。这样
oneshot tick 自身保持无子进程，后续 tick 不会遇到遗留 cgroup；停止
`openlabs-factory.target` 会同时停止 timer 与完整 worker 进程组。科学恢复仍由 SQLite
心跳/租约负责，task/result 文件协议不依赖 systemd unit 生命周期。

### 6.2 故障和死循环处理

systemd 只能保证进程被启动，科学恢复必须由工厂 watchdog 实现：

| 情况 | 自动处理 |
|---|---|
| 进程退出/结果失败 | 有限重试、指数退避；达到次数上限后隔离 |
| worker 失去租约 | 终止 lab/Agent 进程组，等待后续 tick 重排 |
| Agent 无输出或命令死循环 | 达到任务硬超时后终止进程组并进入重新规划 |
| Agent 在截止前只写了一半状态 | attempt 私有工作树被隔离；正式 campaign 保持逐字节不变 |
| 结果引用随后会变化的 lane/state 文件 | 入库前复制为 attempt 专属不可变证据，后续节点只读取归档 |
| 文件提升后、SQLite 入库前崩溃 | 下个加锁 tick 根据事务日志自动回滚；若数据库已成功则完成清理 |
| 科学路线陷入僵局 | 合法 `NEEDS_REPLAN` 自动用 `frontier` runner 建立一个新任务 |
| 可逆决策十字路口 | Agent 可在单个有界任务内启动互不写冲突的子 Agent 分支 |
| 高成本或不可逆决策 | 进入 `NEEDS_HUMAN`，停止该链但继续其他 campaign |
| 连续成功但无实质进展 | 由领域状态门冻结当前路线；活动生产计划回收产线并从新 radar 周期继续 |

工厂连续性的定义是：任何单个任务都可以暂停、隔离或等待管理员，但不能阻塞其他研究任务；
活动 `production_plan.json` 中的产线还必须在安全窗口换轮后自动补种。控制面不凭空扫描全部
历史 campaign，而是把管理员已批准的生产计划当作期望状态，读取各 lane 的证据门、冻结记录
和受门禁 `next_actions`。每轮任务数和 Agent 时间仍是熔断窗口，但不再是连续产线的永久寿命。

### 6.3 Agent 进程、角色和会话

“同一个 Agent”指可按 session ID 恢复的逻辑会话，不指一个长期空转的操作系统进程。每个
worker 只执行一个有界 research episode：Agent 可在预算内自主完成多个科研子步骤，并在
形成一个持久证据 checkpoint 或等待长实验时退出；确定性实验进程通过
checkpoint、心跳和租约继续运行。这样保留对话连续性，同时避免把进程存活误当成可靠记忆。

保持 Codex 操作系统进程不退出，不能消除模型再次处理活动上下文的 token 成本；它主要只
保留本地 RAM、打开的文件句柄和子进程状态，反而会扩大崩溃恢复、租约回收、资源泄漏和凭据
生命周期。跨节点连续性因此采用“长寿命逻辑 session + 短寿命有界进程”：同角色、同
campaign、同使命使用 `codex exec resume`；节点输入应优先指向最新 checkpoint、变化清单和
必要证据，避免重复展开未变化的大文件。若两个所谓节点必须依赖尚未持久化的内存状态，它们
不是可靠的持久边界，应合并为同一
有界 Agent 节点，让一个 Codex 进程在节点内部跨越这些微步骤，直到产出原子 checkpoint 后
退出。外部等待、角色/权限变化、独立复核或科学门禁仍必须切断进程和会话。

| 场景 | 会话规则 | 原因 |
|---|---|---|
| 同一 campaign 的研究推进与结果解释 | 同一 `researcher` session | 避免重复读取背景、保留路线记忆 |
| 同一冻结实验协议的检查点续跑 | 同一 `experimenter` session | 保留执行环境与故障上下文 |
| 独立复现实验 | 新 `experimenter` session | 防止继承原实验解释和预期 |
| `NEEDS_REPLAN` | 新 `researcher` session | 打断失败路线的锚定和沉没成本偏差 |
| 同一稿件的连续修订 | 同一 `writer` session | 保留叙事、术语和修改历史 |
| 从研究/实验切换到写作 | 新 `writer` session | 作者只接收冻结且已验证的证据 |
| 论文就绪审计、结果审阅、独立复核 | 每位审阅人一个新 session/process | 禁止自己做自己评和审稿意见串扰 |
| 审阅通过后进入写作 | 新 `writer` session | 审阅者不直接改写自己刚审的对象 |
| 审阅要求文字修改 | 恢复祖先链中原 `writer` session | 保留同一稿件上下文，但不继承 reviewer 会话 |
| 审阅要求新证据 | 新 `researcher`/`experimenter`，完成后恢复原 `writer` | 让证据生产与写作独立，再重新审阅 |

控制面硬性保证 session 只能来自同一 campaign、同一角色且位于当前任务祖先链中的任务；reviewer
任务的 session mode 固定为 `fresh`。当前论文门禁先冻结 Codex reviewer-1，再以 Packy 上的
Claude Code Opus 5 启动 reviewer-2；第二位只能获得同一冻结科学输入和 reviewer-1 的哈希，
不得读取其内容。角色切换不能在一个对话里靠提示词“扮演”，必须新建任务。
结果包中的普通字符串 `next_action` 表示当前角色续接；需要换角色或启动独立同角色运行时，
必须写出含 `objective`、`agent_role`、`session_mode` 的结构化 action；审阅回流还必须声明
`text_revision` 或 `evidence_remediation`。控制面在角色切换时默认强制 `fresh`，唯一跨角色
恢复是从 paper reviewer 返回其祖先 writer；它恢复 writer 自己的 session，不传递 reviewer
session。研究/实验结果不能绕过 paper-readiness 审查直接生成 writer。

~~~text
研究/实验 paper_candidate
  → fresh paper_readiness reviewer
  → fresh writer
  → fresh Codex + fresh Packy Claude Opus 5 review panel
      ├── 通过：内部终止态
      ├── text_revision：恢复原 writer → 再次 fresh review
      └── evidence_remediation：fresh researcher/experimenter
                                → 恢复原 writer → 再次 fresh review
~~~

无论是否恢复会话，每次节点都必须把下列状态写入文件和结果包：

- 当前目标和阶段；
- 已确认事实和未决假设；
- 最近成功检查点；
- 已尝试路线和失败原因；
- 下一步候选动作；
- 预算、期限和审批边界。

模型对话上下文用于减少重复读取，但绝不能成为唯一记忆。

### 6.4 硬预算与资源护栏

每个任务有 `max_task_wall_seconds` 硬超时，每个 campaign 有累计
`max_campaign_agent_seconds = 86400` 上限。同一 campaign 同时最多运行一个任务，因此预算
不会被同 campaign 的并发尝试重复预支；达到上限后，剩余排队任务转为 `NEEDS_HUMAN`，其他
campaign 继续运行。每次 attempt 保存实际运行秒数、Agent 适配器版本、runner/profile、
session ID，以及 runner 能提供的模型、token、缓存和成本字段。控制面不内置会迅速过期的
价格表，也不伪造 Agent 未返回的成本。

并发不使用固定“全局 2 个任务”。每个任务保存 CPU 线程、内存和临时盘峰值预留；tick 用
主机总量减管理员保留量，并结合当前可用内存/磁盘压力计算本轮容量。活动任务预留加候选任务
预留不超过容量时才可启动。放不下的队首任务保持排队，调度器继续查看其他 campaign；资源
释放后的下一轮 tick 再尝试。`max_worker_processes` 只是不可信资源申报之外的进程数保险，
同一 campaign 串行规则继续独立生效。任务内存预留落实为 worker 的 `MemoryHigh` 回收提示，
不再误作工具硬上限；worker 仍由 `TasksMax`、`CPUQuota` 和完整进程组生命周期监督。所有
worker 与数学工具共同位于 `openlabs-workers.slice`，该 slice 以主机物理内存的 80% 为聚合
`MemoryMax` 且禁用 swap。数学工具另施加 profile 级物理内存 cgroup、地址空间、CPU/墙钟、
线程/进程数、文件和输出限制；Lean 单次上限动态取 WSL 内核可见物理内存和 CPU 的 75%，
且多个 Lean 校验串行。当前任务协议仍只声明 CPU 线程、内存和临时盘三种可调度资源，不增加
GPU 分配器。

### 6.5 只保留最小程序入口

个人使用的第一版不实现产品化 CLI、命令树或额外 CLI 框架。只提供一个稳定、可测试、可由 systemd 调用的 Python 模块入口：

~~~text
python -m openlabs tick
~~~

该命令执行一次幂等调度后退出。开发时可手工运行它；连续运行时由 systemd timer 调用同一入口。状态和日志初期直接使用 systemctl、journalctl、SQLite 和事件文件查看。

内部可以存在 main 函数，但不要求用户记忆仓库内某个 main.py 路径，也不依赖当前工作目录。只有出现多用户客户端、远程管理或频繁人工命令后，再在这个稳定入口之上增加正式 openlabs CLI。

## 7. 模型路由

### 7.1 基本原则

模型选择由以下因素决定：

- 科学影响和错误代价；
- 问题新颖性和歧义；
- 是否存在确定性 oracle；
- 上下文规模；
- 工具和编码需求；
- 先前失败次数；
- 剩余时间和成本预算。

核心判断是：越容易被确定性程序验证的输出，越适合便宜模型；越难验证、越新颖、影响越大的输出，越需要高级模型。

具体模型名称和价格变化很快，只能放在本机可更新的 runner/profile 配置中，不能散落硬
编码在工作流。工厂任务只记录 `cheap`、`balanced`、`frontier` 等能力/成本等级和实际运行
时解析出的模型 ID；升级由证据门失败、任务价值和错误代价触发。

### 7.2 初始路由

| 等级 | 模型类型 | 适用工作 |
|---|---|---|
| L0 | 不调用模型 | 调度、监控、Schema、指标、索引、资源控制 |
| L1 | 便宜模型 | 元数据、查询生成、日志分类、单篇结构化抽取、格式修复 |
| L2 | 平衡模型 | 常规实验代码、普通调试、限定材料综合、日常分析和初稿 |
| L3 | 高级模型 | Idea、实验设计、困难证明、复杂调试、科学解释和最终审计 |

高级模型重点用于：

- 研究问题和路线选择；
- 冲突文献综合和新假设；
- 能排除混杂因素的实验设计；
- 困难数学证明和关键反例；
- 普通模型连续失败后的复杂调试；
- 负结果解释和 Claim 形成；
- 论文核心论证、跨供应商独立终审；
- 高价值决策十字路口。

### 7.3 升级和审计

~~~text
便宜模型
  → 验证失败、结果不完整或不确定
平衡模型
  → 连续失败、模型分歧或高价值里程碑
高级模型
  → 空白 reviewer session 独立审计
~~~

路由不能只相信模型自报置信度。每次 attempt 至少记录：

- Agent 适配器及版本、runner、profile 和路由原因；
- session ID、是否恢复、prompt/task、Skill 和输入 artifact；
- 实际墙钟时间，以及 runner 事件中确实提供的模型、token、缓存和成本；
- 验证器结果、重试和升级原因；
- 最终是否采用该输出。

## 8. 实验代码边界

最小系统不实现自动工具发现、晋升任务或工具注册表。Agent 在 campaign 工作区产生的实验代码
保持任务私有，并在结果包中冻结代码、环境、输入、参数、输出和哈希。只有当现实中已经出现
第二个独立 campaign 需要同一实现时，管理员才把它作为普通代码变更移入相应实验室，补齐
契约和回归测试后提交。正在运行的实验不能修改共享库。

## 9. Agent 与确定性代码的责任

Agent 负责：

- 文献理解、Idea 和路线设计；
- 实验代码和证明草案；
- 结果解释、失败反思和重新规划；
- 子 Agent 分工和阶段内探索；
- 论文叙事与审稿意见分析。

确定性代码负责：

- 状态迁移和任务租约；
- 输入输出 Schema；
- 哈希、溯源和原子写入；
- 并发、预算、超时和资源上限；
- 数值、统计、形式证明和领域 invariant；
- 证据是否足以支持 Claim；
- 发布、投稿和高成本操作门禁。

日常研究行为可以约 70% 由 Agent 完成、30% 由确定性机制完成，但所有权威状态改变和不可逆操作必须经过确定性门禁。

## 10. 从现有项目迁移

迁移时不要直接把现有仓库整体复制到 monorepo。推荐顺序如下。

### M0：架构骨架

- 建立四层物理目录；
- 初始化内层 openlabs 代码 Git；
- 建立 monorepo 子目录和架构文档。

### M1：协议优先

- 建立 lab manifest v2；
- 建立 task、status 和 openlabs result bundle Schema；
- 建立契约测试和示例 fixture。

### M2：迁入稳定源代码

- 从旧 ARA 选择 manifest、registry、dispatcher、bundle ingest、stage limiter 和事件机制；
- 迁入 AMRA 的数学研究循环和审计门；
- 迁入 matfactory 的材料协议、campaign、watchdog 和结果验证；
- 迁入 AIRA 的 AI/ML 实验室骨架；
- 将 ara-paper-writing 的协调 Skill、必要 vendored Skill、registry/bundle/build/review 门禁代码迁入轻量 paper workflow；
- 暂不迁入 Zenodo 自动发布、远程 Manage handoff 等非 MVP 外部副作用。

旧 ARA 的固定串行 orchestrator、巨型 revision loop、重复写作流程和写死模型配置不迁入新核心。

现有仓库先保留为只读历史。若需要保留提交历史，可以随后使用过滤后的 subtree 或 history import；不要把历史运行数据一并带入。

### M3：运行数据迁移

- 给现有 campaign 和论文分类；
- 将可读研究记录迁入 ledger/workspaces；
- 将大型产物迁入 artifact store 并计算哈希；
- 建立旧路径到新 URI 的清单；
- 验证后再决定旧副本的保留策略。

### M4：连续运行

- 实现幂等 tick；
- 接入 systemd timer 和独立 worker；
- 实现心跳、租约、超时、恢复和隔离；
- 保证单个 campaign 失败不阻塞全局调度。

## 11. 初始非目标

第一阶段不做：

- PostgreSQL、Kafka、Kubernetes 或复杂微服务；
- 多用户权限和计费；
- 大型 Web 管理界面；
- 产品化完整 CLI 和命令树；
- 自动投稿或自动公开发布；
- 一个跨领域、固定七阶段的巨型确定性工作流；
- 永不退出并依赖自身上下文记忆的大 Agent。

## 12. 初始验收标准

在开始迁移大量研究任务前，最小系统应满足：

1. 三个实验室可以通过同一个 manifest 被发现。
2. OpenLabs orchestrator 能以相同 task 协议启动三个实验室的 smoke task。
3. 所有结果均通过统一 bundle adapter、证据门和契约测试。
4. task/campaign/lab/domain/角色、attempt 和精确输出路径任一不匹配时，结果不能入库。
5. 并发 tick 不会突破 CPU/内存/临时盘预留或进程数保险，同一 campaign 不会并行启动两个任务。
6. 杀死控制面后长任务继续运行；恢复 tick 后能够接收结果或回收租约。
7. 杀死长任务后，任务只能有限重试并最终隔离，迟到 attempt 回执不能污染新尝试。
8. 任一 campaign 进入 `NEEDS_HUMAN`、隔离或耗尽 24 小时预算时，其他 campaign 仍可推进。
9. session 只从同 campaign、同角色的任务祖先恢复；replan 和所有 reviewer 使用空白会话，
   reviewer 的文字意见只能返回原 writer session。
10. 每个 attempt 留存适配器版本、runner/profile、session、墙钟时间、可得 token/成本、门禁和路由原因；未提供的成本不猜测。

代码验收通过后，还需在目标机器启用 timer 做一次真实 24 小时 soak run；这是部署验证，不能
由快速单元测试替代。
