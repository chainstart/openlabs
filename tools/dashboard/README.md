# OpenLabs 研究监控面板

供研究者查看：哪些项目正在研究、研究进展、成果（论文阶段与投稿结果）、使用了哪些数据、主要发现和结论、目标期刊或会议，以及返修截止和长时间无进展的投稿。

```bash
bin/openlabs-dashboard serve              # http://127.0.0.1:8765/ ，投稿数据取 maintenance/ 下最新的网站快照
bin/openlabs-dashboard serve --site-api   # 实时读取管理网站（只发 GET；需要 ARA_PAPER_MANAGE_API_URL/KEY）
bin/openlabs-dashboard build --output ~/openlabs-dashboard.html   # 生成单文件静态页面，可离线打开
```

面板只读：不修改登记表、台账、网站，SQLite 以只读方式打开。默认只监听本机；需要局域网访问时显式加 `--host 0.0.0.0`，并自行确认网络安全，因为页面包含未发表的研究内容。

## 数据来源

| 页面内容 | 来源 |
|---|---|
| 论文、目标期刊/会议、分区/CCF、版面费 | `openlabs-data/registry/papers/*.yaml` |
| 主要发现 | 登记表 `key_findings`；没有时显示稿件摘要 |
| 使用的数据 | 登记表 `data_sources`；没有时显示稿件“数据可用性”部分提取的链接，并标注“未登记” |
| 投稿历史、审稿轮、拒稿理由 | 管理网站快照或 API；都没有时用 `registry/journal-rejections.json` |
| 研究项目、目标、最新进展、数据链接 | `openlabs-data/workspaces/<领域>/…` 的 `project.json`、`research_state.json`、README、数据清单 |
| 调度器课题与任务 | `openlabs-database/live/factory.sqlite`（只读） |

要让面板显示完整信息，新论文在登记表中填写 `data_sources` 和 `key_findings`，格式见 `workflows/paper/skills/overlays/quality-gate.md`。
