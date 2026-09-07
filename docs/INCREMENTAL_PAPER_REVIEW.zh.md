# 论文增量复审

首版支持科学内容已经通过完整独立审阅后的引用、措辞与局部排版小修。
审阅者仍是新进程，每次检查相对最近一次全文审阅的**全部累计差异**和待处理问题。
旧分数、旧建议和原始审阅文件不修改。出现科学变化或无法判定影响时转回全文审阅。

在数据仓库 `registry/settings.yaml` 的 `quality_gate` 中配置：

```yaml
incremental_review:
  enabled: true
  scope: editorial_only
```

现有单审阅者 CAS 门槛、总修订预算、证据和期刊要求继续适用。双审阅者合同暂走全文。
配置缺失默认关闭。改变门槛或配置会使既有增量基线失效。

## 操作

以下命令从代码仓库运行，所有进程经过资源保护。`DATA` 应替换为实际数据仓库，
`ID` 为论文 ID，`MODEL` 为当前实际配置的模型；这些是示例占位符。

```bash
bin/openlabs-resource-guard -- env PYTHONPATH=workflows/paper python3 -m paper_writing paper start-revision --paper-id ID --reason '补充引用' --root DATA
# 修改并构建 canonical PDF，准备必要的当前版本支持包，然后分流：
bin/openlabs-resource-guard -- env PYTHONPATH=workflows/paper python3 -m paper_writing review route --paper-id ID --root DATA
```

`metadata_reuse` 已完成确定性复用；`full` 使用原全文流程；`blocked` 表示现有预算不允许
再审，停止启动新审阅；`delta` 返回冻结的差异包，可继续：

```bash
bin/openlabs-resource-guard -- python3 workflows/paper/skills/openlabs-paper-review/scripts/run_delta_reviewer.py --paper-id ID --root DATA --model MODEL --effort high
bin/openlabs-resource-guard -- env PYTHONPATH=workflows/paper python3 -m paper_writing review validate-delta --paper-id ID --root DATA --receipt RECEIPT
bin/openlabs-resource-guard -- env PYTHONPATH=workflows/paper python3 -m paper_writing review apply-delta --paper-id ID --root DATA --receipt RECEIPT
```

`RECEIPT` 为运行器返回的相对数据仓库路径。运行器需要本地 Codex、latexmk、pdftotext 和
pdftoppm。它先在独立目录构建，要求新构建文本与 canonical PDF 一致，再渲染页面供审阅。
构建、输入检查、运行或记录验证失败都不会放行；日志保留用于修复技术问题。

`resolved` 应用后才会 ready；`unresolved` 保持未就绪并携带新问题；`escalate` 要求全文
重新审阅。可选润色单列，不会触发新的必须修订。上述命令不发布、不投稿、不更新外站。

## 边界与审计

- 必须在修改前 `start-revision`。没有可信旧快照时转全文，不能事后声称旧版被审过。
- 基线可为“科学就绪但文字未就绪”；有科学阻塞、低于分数/建议门槛则不可用。
- 不以改动行数证明安全。定理、证明、公式环境、量词/假设、全局宏或依赖变化会触发全文。
  其余改动仍需独立语义判断；首版不宣称自动证明数学等价或自动构造数学依赖图。
- 新增/删除文件、支持证据或重要 registry 内容改变，首版走全文。源文件体积超界也走全文。
- 应用时重新生成当前差异包；发布时再次检查基线、所有历史回执、当前输入、累计差异和
  待办覆盖。更换文件、删除审阅链、修改旧分数或漏掉一处改动都会被拒绝。
- 每次实际应用的增量判断消耗现有总轮次预算，单独记录基线已用轮次和之后的增量次数。
  运行失败和输出格式修复未应用时不消耗判断轮次，但保留凭据；不因启用增量扩大总预算。
- 运行凭据和哈希证明记录的一致性，不是对记录作者身份的密码学认证；与原门禁相同，
  不得伪造运行或检查记录。测试中的模拟回执明确仅为离线 fixture。

证据保存在数据仓库 `reviews/delta-baselines/`、`delta-packets/` 和 `delta-runs/`。
发布路径要求基线和审阅记录遵循既有 Git 冻结要求。渲染图、重复构建 PDF 和运行日志等
过程产物只保留在私有运行目录，不要求提交 Git；其绑定文件仍须存在，每次发布前重新验哈希。
生产内容依然仅从原稿件与
原发布包导出，增量回执属于私有审查依据。

现有 `reuse-metadata` 继续处理作者/发布元数据；已采用增量审查链的稿件后续通过 `review route`
重新验证，不能通过旧复用入口丢失审查链。原 `closeout-minor` 仍保留其逐篇授权边界。
