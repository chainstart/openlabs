# Zenodo 支撑材料指南

仓库采用两条简单规则：

- 静态支撑材料、最终实验脚本、结果表格、附录和数据说明：只发 Zenodo。
- 需要安装、持续维护、Issue 或二次开发的软件：GitHub 维护，Zenodo 固定论文所引用版本。

模式登记在 OpenLabs 数据仓库 `registry/papers/<paper_id>.yaml` 的
`support.publication.mode`：
`zenodo_only`、`github_zenodo` 或 `not_required`。正式论文引用具体 Version DOI；Concept DOI
用于指向该材料的所有版本。

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
3. `zenodo release`：重新核对门禁快照、Git HEAD、本地 ZIP SHA-256 与 Zenodo 草稿文件，
   全部一致即正式发布，无需额外人工确认。命令写回 Version DOI、Concept DOI 和发布回执，
   但不会提交 Git。
4. 提交 DOI/回执更新并推送；OpenLabs 的完成与投影流程随后同步结构化状态。仅在自动任务
   失败时手工运行 `handoff release` 恢复。该步骤只同步写作产物，不创建投稿或期刊事件。

通过质量门禁即构成支撑材料的公开发布授权：门禁为 `ready` 后可以直接执行 `zenodo release`，
不需要用户再次确认。`release` 自身会重新校验门禁、Git 状态与远端文件，门禁失效、未达标或
未绑定材料包时一律拒绝发布。生产**草稿**（`prepare`、`create-draft`、`new-version`）仍需
`--confirm-production`，因为它发生在门禁之前。

门禁授权的外部动作仅限支撑材料发布。投稿、期刊事件、录用/拒稿与论文发表状态始终由人类作者
决定并由对应的外部管理系统记录，门禁绝不代替。

## 配置材料与账号

材料源通过 registry 的 `support.publication.source_files` 声明，也可在准备时重复传入
`--source`。只要显式传入了 `--source`，这些参数就构成本次完整公开文件集并替换旧的
`source_files`，不会与上一版本合并；不传时才沿用 registry。目录会递归展开，最终 registry
记录展开后的逐文件路径。不得包含密钥、未获
授权的数据、缓存或可重建的 LaTeX 中间文件。许可证必须由负责人选择，不能由 Codex 猜测：

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

Zenodo Sandbox 与 Production 使用不同账号/token。token 至少需要创建/更新 deposit 和
执行 publish action 的权限；绝不把 token 写进 registry、回执或命令输出。

## 准备草稿并预留 DOI

先在 Sandbox 验证账号和元数据；Sandbox DOI 不能写进正式论文：

```bash
python -m paper_writing zenodo prepare \
  --paper-id <paper_id> --environment sandbox \
  --source papers/<paper_id>/evidence/release \
  --license cc-by-4.0
```

生产草稿需要显式确认：

```bash
python -m paper_writing zenodo prepare \
  --paper-id <paper_id> --environment production --confirm-production \
  --source papers/<paper_id>/evidence/release \
  --license cc-by-4.0
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

门禁通过后直接执行，无需用户确认：

```bash
python -m paper_writing zenodo release \
  --paper-id <paper_id> --environment production
```

`--confirm-production` 与 `--confirm-paper-id` 仍被接受以兼容旧脚本；`--confirm-paper-id`
如果给出则必须与 `--paper-id` 完全一致。

命令会拒绝以下情况：质量门禁未通过或快照失效、稿件/registry/材料未提交、材料包哈希
变化、草稿 DOI/版本不符，或 Zenodo 远端文件名、大小、校验和与本地不一致。发布成功后：

```bash
git add registry/papers/<paper_id>.yaml papers/<paper_id>/support-materials/zenodo
git commit -m 'release: record <paper_id> Zenodo support DOI'
git push origin main
```

材料未变化的纯文字返修可继续引用原 Version DOI；材料内容发生变化时使用同一 Zenodo
记录创建新版本。旧 Version DOI 永久保留，新版本获得新的 Version DOI，Concept DOI 不变。

Zenodo 的 `version` 元数据接受任意字符串，只是建议采用语义化版本标签；Zenodo 不要求版本号
连续。因此，从 `1.0.0` 直接登记为 `1.2.4` 在平台层面是有效的，不需要补建中间版本。不过，
本仓库只在该标签确实是材料自身的既有版本标识时允许跳号：不得为了追随论文版本、掩盖缺失
发布或制造并不存在的版本沿革而任意改号。版本号应单调且可追溯，其变更依据保留在 registry、
回执或返修记录中，不写入论文正文。

`zenodo plan`、`create-draft`、`new-version` 和 `publish` 保留为诊断/底层接口。正式流程使用
`prepare` 与 `release`；CLI 已禁止旧 `publish` 子命令直接操作 Production。不要手工拼接
API 调用或只把网页状态留在聊天记录中。
