# OpenLabs 论文标识与公开文件命名规范

本规范适用于 OpenLabs 所有领域实验室的新论文工作区、注册表、公开支撑材料和交付给读者
的稿件文件。研究题号、论文技术主键、期刊稿号是三类不同标识，不得混用。

## 1. 新论文的不可变 `paper_id`

统一格式为：

```text
YYYYMMDD-domain-subdomain-keywords
```

- `YYYYMMDD` 是论文工作区的 `created_at` 日期，不是研究项目启动日、投稿日或版本日期。
- `domain` 和 `subdomain` 必须与论文 registry 字段完全一致。
- `keywords` 使用一至五个小写英文或数字词组，描述稳定的科学对象、方法或研究目标。
- 整个 ID 只使用小写字母、数字和连字符，长度不超过 80 个字符。
- 创建后 `paper_id` 是跨目录、manifest、receipt 和 API 使用的不可变技术主键。标题、结论、
  版本或目标期刊变化都不触发改名。

合规示例：

```text
20260828-physics-hep-p5-chain-bootstrap
20260830-materials-battery-llzto-soft-modes
20260804-math-erdos-866-sumfree-lower-bound
20260814-ai-health-conformal-deployment-shift
```

不要把下列内容写入新 `paper_id`：

- OpenLabs 自编题号、任务号、轮次或 workstream，例如 `tp-042`、`problem-29`、`round-5`；
- 期刊名称、作者、稿件版本、审稿或投稿状态；
- 尚未由证据支持的结论，例如在结果仍开放时写入 `solved`、`proof` 或 `complete`。

业界可识别且来源明确的外部目录编号可以保留命名空间，例如 `erdos-866`、`opg1757`。
OpenLabs 自编题号应放在 `project_name`、研究 provenance 或 artifact 名称中。

## 2. `display_id` 与旧论文

`display_id` 是面向界面、公开归档和读者文件的可读标识，也必须使用上述 domain-scoped
格式。对新论文，`display_id` 与 `paper_id` 相同。

旧格式 `paper_id` 不迁移、不重命名，以免破坏历史路径和回执；为其登记合规的
`display_id`。公开名称只使用 `display_id`，旧技术主键只留在内部路径、manifest、receipt
和 API 中。已经公开的 Zenodo 版本不可原地改名，只能在同一 concept record 的新版本中
应用新名称。

## 3. 对外文件名

读者获得的主稿 PDF 统一命名为：

```text
<display_id>-v<MAJOR.MINOR.PATCH>.pdf
```

例如：

```text
20260828-physics-hep-p5-chain-bootstrap-v0.2.1.pdf
```

公开支撑材料继续使用：

```text
<display_id>-support-v<MAJOR.MINOR.PATCH>.zip
```

不得用实验室题号、临时标题、`latest`、`final`、`new` 或本机下载序号替代这些名称。
期刊系统分配的正式 manuscript/preprint number 属于投稿系统事实，不反写为 `paper_id`。

## 4. 工具与迁移边界

新建工作区必须使用 `paper-writing paper create`；命令校验日期、领域、小领域和明显的内部
追踪号。复制或交付 PDF 前，用下列命令取得规范文件名：

```bash
python -m paper_writing paper public-name --paper-id <paper_id> --root <paper-root>
```

发现既有 ID 不理想时，不直接移动论文目录或修改已发布记录。先判断它是否已成为不可变
主键；若是，则补充或纠正 `display_id`，并从下一次公开版本开始使用规范名称。
