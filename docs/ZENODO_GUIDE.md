# Zenodo 支撑材料指南

仓库采用两条简单规则：

- 静态支撑材料、最终实验脚本、结果表格、附录和数据说明：只发 Zenodo。
- 需要安装、持续维护、Issue 或二次开发的软件：GitHub 维护，Zenodo 固定论文所引用版本。

模式登记在 OpenLabs 数据仓库 `registry/papers/<paper_id>.yaml` 的
`support.publication.mode`：
`zenodo_only`、`github_zenodo` 或 `not_required`。正式论文引用具体 Version DOI；Concept DOI
用于指向该材料的所有版本。

是否强制执行由 `registry/settings.yaml#support_publication.gates` 配置，而不是写死在某个学科：

```yaml
support_publication:
  default_mode: zenodo_only
  default_license: cc-by-4.0
  gates:
    before_review:
      minimum_status: draft
      require_version_doi: true
      require_manuscript_citation: true
    before_support_release:
      minimum_status: draft
      require_version_doi: true
      require_manuscript_citation: true
      require_quality_gate_package_binding: true
    before_handoff:
      minimum_status: published
      require_version_doi: true
      require_manuscript_citation: true
      require_quality_gate_package_binding: true
  not_required:
    require_reason: true
```

`support-check` 实现审稿前门禁：非豁免论文必须至少具有已准备的 Zenodo 草稿、稳定的 Version
DOI，以及正文首处材料说明、参考文献和 Data Availability 中一致的引用。`zenodo release`
使用独立的发布前门禁，允许状态仍为 `draft`，但要求当前包已绑定通过审阅的快照；发布完成后，
`handoff release` 再要求状态为 `published`。确实无需公开材料的论文可以选择 `not_required`，
但必须登记具体原因。调整这些配置即可改变研究政策，无需修改学科 Skill 或新增常驻 Hook。

公开归档命名是强制规则：ZIP 文件名和 ZIP 内唯一顶层目录都以 registry 的 domain-scoped
`display_id` 开头，后接 `-support-vX.Y.Z`。不可变技术 `paper_id` 只出现在内部仓库路径、
manifest、receipt 和 API。已发布 Zenodo 版本不可改名；需要纠正时在同一 concept record
创建新版本。

## 发布边界

Zenodo 使用两阶段流程，质量门禁不会调用网络：

1. `zenodo prepare`：验证已提交的材料源，创建或恢复 Zenodo 草稿，预留 Version DOI，
   生成确定性 ZIP、内部 manifest、`SHA256SUMS` 和外部 `.zip.sha256`，上传后核对远端
   文件大小与校验和，并把草稿回执写回论文 registry。
2. 用不依赖发布状态的客观措辞将当前 Version DOI 写入论文（如需），运行
   `zenodo verify-draft` 与 `support-check`，重新编译、独立审稿并通过当前质量门禁，然后提交
   稿件、PDF、registry、材料包和草稿回执。草稿、预留、发布步骤和旧版沿革只写入内部
   registry、回执或返修记录，绝不写入正式论文或当前 ZIP 内面向读者的 claim map/README。
3. 采用 `registry/settings.yaml#support_publication.standing_production_release_authorization`
   中登记的长期作者授权运行 `zenodo release`，无需逐篇再次询问；命令仍必须传入生产环境和
   精确 paper ID 确认参数，并重新核对门禁快照、Git HEAD、本地 ZIP
   SHA-256 与 Zenodo 草稿文件，全部一致才正式发布。命令写回 Version DOI、Concept DOI 和
   发布回执，但不会提交 Git。
4. 提交 DOI/回执更新并推送；OpenLabs 的完成与投影流程随后同步结构化状态。仅在自动任务
   失败时手工运行 `handoff release` 恢复。该步骤只同步写作产物，不创建投稿或期刊事件。

质量门禁是公开发布的必要条件。仓库已配置长期生产发布授权，因此通过门禁且材料整理完成后
默认直接执行 `zenodo release`，不再向作者重复提问；生产确认参数仍作为精确目标和不可逆操作
的机器安全边界。命令自身会重新校验门禁、Git 状态与远端文件，门禁失效、未达标或未绑定材料包
时一律拒绝发布。生产**草稿**（`prepare`、`create-draft`、`new-version`）同样需要
`--confirm-production`。

门禁授权的外部动作仅限支撑材料发布。投稿、期刊事件、录用/拒稿与论文发表状态始终由人类作者
决定并由对应的外部管理系统记录，门禁绝不代替。

## 默认上传规则：代码优先，不上传巨大中间产物

公开支撑包不等于完整本地证据归档。默认只选择复现所需源码、依赖锁定、参数／种子、
运行命令、数据来源说明、少量对照摘要和必要的小型示例。外部原始数据应注明稳定出处、
版本／日期、标识符或校验和、获取步骤及许可；不要重复打包。可再生成的证书、矩阵、
数组、计数缓存、轨迹、检查点、全量运行输出留在本地 artifacts，不进入公开 source_files。
不能再生成的独有原始证据不是中间产物，不得删除或假称有出处；确有必要公开时先取得
明确人工确认并调整上传政策，不能自行提高阈值。

`registry/settings.yaml#support_publication.package_policy` 默认限制单文件 10 MiB、
全部源文件未压缩合计 50 MiB、2000 个文件。`zenodo prepare` 在任何联网前检查，
`zenodo release` 在发布前重检。压缩的科学数据或嵌套归档、常见数组／模型／轨迹格式和
缓存／检查点／原始数据目录默认阻断；代码依赖须以选定源文件提供，不用嵌套 ZIP 隐藏内容。
校验不会静默过滤文件；报错后须明确修订公开文件清单和复现说明。
不得靠改后缀、分片、重复压缩或 artifact 清单绕过。大小检查不是语义审阅，所有小文件
也应逐项判断是否必要，而不是把阈值当作可以塞满的配额。

删除公开生成结果前，确认生成器不再隐式依赖这些预存结果；保留完整参数及执行入口，
明确耗时／资源要求和实际已验证的复现范围。源码存在不等于全参数复现已验证。
材料范围变化须更新 README、claim map、正文可用性说明、版本和精确包哈希，再按
既有定向审阅／质量门禁流程处理。不能用精简材料为理由放宽科学或发布门禁。
已有公开不可变版本不回改；历史只读核验不受新上传限制影响。

对人工明确批准的代码优先精简，可在既有 `targeted_review_closeout` 机制中绑定
`support_repackaging_authorization`，但不能走 metadata reuse：授权必须指向精确的新旧
完整文件清单哈希；隔离定向审阅必须收到完整当前代码包，逐项覆盖增删改并明确确认没有
丢失必要输入、正文与材料一致。原完整证据包仍按哈希核验，科学构造模块、保留的入口、
依赖与许可不得变化，仅可新增复现调度入口和小型摘要。新增科学模块或科学源码修改不属于
此路径。原评分、全文审阅、累计轮次及全部发布前检查保留；缺授权、缺审阅、负面结论或
任一快照不符均阻断。这是经授权的定向材料审阅，不是自动降低证据门槛。

## 本地大型科学证据：Git 清单与 sibling artifacts 双重绑定

`openlabs-data` 的 5 MiB 新文件限制不得提高、绕过或通过拆分数据规避。科学上必需的完整
大型数组保存在 sibling `openlabs-artifacts`；data 中相同逻辑路径只保留被忽略的组包缓存。
本地原始文件保持完整，不删行、不转换浮点、不把 URI 当成数据。上述存储机制不代表
必须公开上传全部数据，也不豁免代码优先上传政策。公开 source_files 只登记明确选定的
轻量复现材料；完整证据另留本地来源及 SHA-256 记录。

使用既有 `artifact_uri` + SHA-256 约定，以一个小型、已提交且与 Git HEAD 逐字节相同的 JSON
manifest 明确登记每个逻辑文件。论文配置 `support.publication.artifact_manifests` 为这些内部
清单的 data-repo 相对路径列表；它们不要加入公开 `source_files`，以免暴露本地存储 URI。

```json
{
  "schema_version": "ara.paper_writing.support_artifacts.v1",
  "files": [{
    "path": "papers/PAPER/support-materials/public-support-vVERSION/results/full.npz",
    "artifact_uri": "file:///WORKSPACE/openlabs-artifacts/paper-support/sha256/ACTUAL_SHA256/full.npz",
    "size": 7255196,
    "sha256": "ACTUAL_LOWERCASE_64_CHARACTER_SHA256"
  }]
}
```

上例仅说明字段，实际 URI 必须包含本项真实 SHA-256 的内容寻址目录。可在资源 guard 内调用
`paper_writing.support.write_support_artifact_manifest(repo_root, paths, manifest_path)`，机械地
复制完整字节并生成清单。该函数不会提交 Git、改变 registry 或调用网络；已经存在但内容不符的
内容寻址对象绝不会被覆盖。只提交小清单、声明和常规小源文件，不强行暂存大型缓存。

`prepare` 与 `release` 都重新验证清单的 Git HEAD 字节、每个本地缓存和对应 artifact 原件的
size/SHA-256；任何缺缓存、缺原件、同长度篡改、清单未提交或 dirty、重复绑定、越界路径、符号
链接或非内容寻址 URI 都会阻断。Git 的 `assume-unchanged` / `skip-worktree` 状态提示不能隐藏
清单字节变化。已由 Git 跟踪的源仍必须通过原有 HEAD 未修改检查，不能用 manifest 绕过。

超过 5 MiB 的生成 ZIP 也自动保存完整 artifact 副本，并产生同目录小型 `.artifacts.json`；
`prepare` 将该清单追加到论文的 `artifact_manifests`。发布前须提交它和 `.zip.sha256`、registry、
回执等小记录，ZIP 本身继续被忽略。较小包保持原有 Git 冻结方式，旧已发布包不会自动迁移。

这种双端绑定不弱于把 payload 内容冻结进 Git：已提交清单固定精确逻辑路径、大小和 SHA-256，
组包时必须读取匹配的完整字节，review snapshot 仍逐字节哈希全部科学源（不是只哈希指针），
ZIP 内部 manifest / SHA256SUMS、本地 ZIP SHA-256、当前源对照和远端传输校验仍全部执行。
机器迁移时必须恢复声明 URI 的完整原件和缓存，或显式提交新的存储绑定；不能静默接受另一个位置
或同名文件。artifact 存储清单属于内部 provenance，不是 Zenodo 发布回执或作者核验声明。

## 配置材料与账号

稿件构建产物同样不必进入 Git。对 Git 忽略且从未跟踪的稿件 `.pdf` / `.bbl`，
可用上述内容寻址双副本机制生成 `papers/<paper_id>/production/release-artifacts.json`，
并在 `submission_package.artifact_manifest` 绑定其 `path` 和 `sha256`。
清单本身必须提交且与 HEAD 字节一致；交付时同时核验两个文件副本及原审阅快照。
这个入口不适用于 TeX、科学源、评阅记录或已经由 Git 跟踪的文件，也不改变质量门禁。

材料源通过 registry 的 `support.publication.source_files` 声明，也可在准备时重复传入
`--source`。只要显式传入了 `--source`，这些参数就构成本次完整公开文件集并替换旧的
`source_files`，不会与上一版本合并；不传时才沿用 registry。目录会递归展开，最终 registry
记录展开后的逐文件路径。不得包含密钥、未获
授权的数据、缓存或可重建的 LaTeX 中间文件。`default_license` 是负责人已经作出的长期选择；
当前配置为 `cc-by-4.0`，后续论文无需重复询问。论文级 `license` 仅用于明确覆盖。若第三方材料
条款与默认许可证冲突，必须停止并报告，不能静默改许可证或删减文件：

```yaml
support:
  publication:
    mode: zenodo_only
    status: planned
    license: cc-by-4.0
    source_files:
      - papers/<paper_id>/evidence/release
```

Token 只放进当前 shell、被 Git 忽略的 `.env` 或个人密钥管理器：

```bash
export ZENODO_SANDBOX_ACCESS_TOKEN='...'
export ZENODO_ACCESS_TOKEN='...'
```

OpenLabs 入口还会以数据文件而非 shell 脚本的方式读取
`~/.config/ara/zenodo.env`。该文件必须由当前用户拥有、是普通文件且权限不宽于 `0600`，并且
只允许 `ZENODO_ACCESS_TOKEN`、`ZENODO_SANDBOX_ACCESS_TOKEN` 和 `ZENODO_ENVIRONMENT`。
这样由 `bin/openlabs-codex`、`python -m openlabs tick` 和 factory 启动的进程可正常继承
Zenodo 凭据，同时普通 shell 仍保持默认无凭据。当前进程已有的同名变量优先；
`OPENLABS_ENABLE_EXTERNAL_WRITES` 不会从该文件加载，仍须为一次明确的外部写操作单独设置。

Zenodo Sandbox 与 Production 使用不同账号/token。token 至少需要创建/更新 deposit 和
执行 publish action 的权限；绝不把 token 写进 registry、回执或命令输出。

## 准备草稿并预留 DOI

先在 Sandbox 验证账号和元数据；Sandbox DOI 不能写进正式论文：

```bash
python -m paper_writing zenodo prepare \
  --paper-id <paper_id> --environment sandbox \
  --source papers/<paper_id>/evidence/release
```

生产草稿需要显式确认：

```bash
python -m paper_writing zenodo prepare \
  --paper-id <paper_id> --environment production --confirm-production \
  --source papers/<paper_id>/evidence/release
```

如果网络中断但草稿已经建立，错误信息会保留 deposition ID。使用
`--deposition-id <id>` 恢复同一草稿；命令会替换草稿文件，不会创建重复发布记录。

准备命令之后，把数据仓库中的 registry、`draft.json`、ZIP 和 `.zip.sha256` 与最终稿件一起提交。
如果 DOI 被写进稿件，必须重新编译、重新审稿并重新运行质量门禁。

准备完成后可只读核验远端元数据、文件名、大小和校验和，不会改变草稿：

```bash
python -m paper_writing zenodo verify-draft \
  --paper-id <paper_id> --environment production
```

### 准备阶段 registry 字段的含义

`prepare` 之后、`release` 之前，registry 里这两组字段指向**不同的记录**，这是设计如此，
不是数据错误：

| 字段 | 含义 |
|---|---|
| `support.publication.version_doi` / `record_url` | 当前材料版本的 Version DOI 与稳定 DOI URL；稿件只引用这一身份。 |
| `support.publication.zenodo.reserved_version_doi` | 当前准备版本的预留 DOI；与活动 `version_doi` 相同。 |
| `support.publication.zenodo.version` | 本次准备的新版本号，与 `reserved_version_doi` 配对。 |
| `support.publication.status` | 准备阶段为 `draft`；只有 `release` 成功后才变成 `published`。 |
| `support.publication.zenodo.previous_published` | 仅供内部审计的上一公开记录身份；不得写入正式论文。 |

预留 DOI 在发布前解析为 404 是正常的，但内部状态不应成为论文叙述的一部分。正式正文只需
客观说明“该 Version DOI 标识的支撑材料记录包含哪些材料”，不得出现“生产草稿”“预发布
期间”“发布后”“旧版本/新版本如何演变”等过程文字，也不得在尚未发布时声称材料已经公开
可下载。`release` 成功后同一 DOI 保持不变。

审阅时核对的是稿件引用当前 DOI、题名、作者、版本与文件名，且措辞在发布前后都成立。运行：

```bash
python -m paper_writing support-check --paper-id <paper_id>
```

该检查还会读取实际登记的 ZIP，要求 `public-support-vX.Y.Z` 源目录、外层包版本、当前 Zenodo
版本以及包内面向读者的 claim map/README 一致。工具或依赖版本、不可变的嵌套旧归档可以保留
自己的真实标签，但不得被表述为当前记录。

`writing_release.support_package_sha256` 必须绑定当前版本的包。科学内容或支撑证据有变化时，
只能由新的 `review apply` 重新绑定。若返修从通过的门禁启动，且只改作者、邮箱、单位、通讯
作者或发布封装元数据，`zenodo prepare` 会比较独立的科学内容指纹和支撑源文件指纹，并在确定
二者未变后自动复用原评审、绑定新 PDF 与新 ZIP；不会启动 LLM 复评，也不会修改原评分。也可
显式执行：

```bash
python -m paper_writing review reuse-metadata --paper-id <paper_id>
```

正文、公式、图表、摘要、参考文献、结论、题名或支撑证据只要有一项变化，该命令就会失败
关闭并要求新的隔离评审。绑定不一致时 `release` 仍会拒绝发布。

## 正式发布

门禁通过后，依据仓库长期授权直接执行：

```bash
python -m paper_writing zenodo release \
  --paper-id <paper_id> --environment production \
  --confirm-production --confirm-paper-id <paper_id>
```

`--confirm-production` 与 `--confirm-paper-id` 均为生产发布的显式授权边界；后者必须与
`--paper-id` 完全一致。

命令会拒绝以下情况：质量门禁未通过或快照失效、稿件/registry/材料未提交、材料包哈希
变化、草稿 DOI/版本不符，或 Zenodo 远端文件名、大小、校验和与本地不一致。发布成功后：

```bash
git add registry/papers/<paper_id>.yaml papers/<paper_id>/support-materials/zenodo
git commit -m 'release: record <paper_id> Zenodo support DOI'
git push origin main
```

材料未变化的纯文字返修可继续引用原 Version DOI；材料内容发生变化时使用同一 Zenodo
记录创建新版本。旧 Version DOI 永久保留，新版本获得新的 Version DOI，Concept DOI 不变。

材料自身版本与论文版本不同的情况下，显式设置
`support.publication.release_version`。该字段只控制材料的 ZIP、目录、回执与 Zenodo
版本，不改变论文的 `version` 或评审快照；未设置时保留沿用论文版本的兼容行为。
不要用旧 `publication.version` 或上一条 Zenodo 记录推断本次材料版本。

Zenodo 的 `version` 元数据接受任意字符串，只是建议采用语义化版本标签；Zenodo 不要求版本号
连续。因此，从 `1.0.0` 直接登记为 `1.2.4` 在平台层面是有效的，不需要补建中间版本。不过，
本仓库只在该标签确实是材料自身的既有版本标识时允许跳号：不得为了追随论文版本、掩盖缺失
发布或制造并不存在的版本沿革而任意改号。版本号应单调且可追溯，其变更依据保留在 registry、
回执或返修记录中，不写入论文正文。

`zenodo plan`、`create-draft`、`new-version` 和 `publish` 保留为诊断/底层接口。正式流程使用
`prepare` 与 `release`；CLI 已禁止旧 `publish` 子命令直接操作 Production。不要手工拼接
API 调用或只把网页状态留在聊天记录中。
