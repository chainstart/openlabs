# 论文配图元件库：选源与许可记录

元件库位于 `$OPENLABS_FIG_ASSETS`（默认 `/workspace/openlabs/build/figure-assets`），不进 git。本目录的 `manifest.json` 列出每个元件的来源、许可和校验值；`fetch_assets.py` 经 WSL 下载桥重建整个库，写出每件的 `.license.json` 和库根的 `catalog.json`（`paper-writing figures assets` 据此检索）。

```sh
python3 workflows/paper/figure-assets/fetch_assets.py            # 重建或补齐
python3 workflows/paper/figure-assets/fetch_assets.py --dry-run  # 只列清单
```

## 2026-11-23 首次建库

总计 289 件，其中新取 271 件、仓库内自绘 18 件（17 件 CC0，望远镜为 Twemoji CC BY 4.0，2026-11-20 已入库）。按学科：生物医学 100、能源 70、通用 50、可靠性 44、天文 25。下载共 52 个桥任务和 3 个 npm 包，全部 `state=completed`、`route=direct`，没有代理兜底。库加缓存约 13 MB，远低于闲时规则的界线。

| 库 | 版本 | 许可 | 件数 | 署名（写进致谢或图注） |
|---|---|---|---:|---|
| Tabler Icons | 3.52.0 | MIT | 125 | Tabler Icons |
| Material Symbols（Outlined，400） | npm @material-symbols/svg-400 0.49.0 | Apache-2.0 | 48 | Google Material Symbols |
| Phosphor Icons（regular） | @phosphor-icons/core 2.1.1 | MIT | 46 | Phosphor Icons |
| Bioicons | git 30f1dd7 | 逐件：CC0 22 件，CC BY 3.0 21 件（均为 Servier Medical Art） | 43 | CC0 不必署名；Servier 件写 “Servier Medical Art (smart.servier.com), via Bioicons, CC BY 3.0” |
| Reactome Icon Library | 2026-11-23 取 | CC BY 4.0 | 9 | Reactome icon library（CSHL、OICR、EBI） |
| OpenLabs 自绘 | 仓库 figure-templates/assets | CC0 | 17 | 不必署名 |

`figures check` 会核对 CC BY 和 MIT/Apache 元件的署名是否出现在稿件中，缺了就给出建议句。

### 选源过程

- **npm 图标包（Tabler、Material Symbols、Phosphor、Lucide）。** 国内可靠源是 npmmirror（`registry.npmmirror.com`，阿里云 npm 镜像，与 npm 官方同步）。它的单文件接口 `/<pkg>/<ver>/files/<path>` 对 WSL 直连返回 403（2 个任务已取消），因此改取整个包的 tarball：Tabler 1.3 MB、Material 1.9 MB、Phosphor 1.4 MB。每个 tarball 都与 npmmirror 元数据中的 sha512 `integrity` 比对，并且另经桥从 `registry.npmjs.org` 取了同一版本的官方元数据，核对 integrity 完全一致。库内只解出清单中列出的图标和 LICENSE，tarball 留在 `_sources/npm/` 作离线重建缓存。Lucide（ISC，lucide-static 1.78.0）解包后 58 MB，所含图标与 Tabler 基本重合，这次没有取。
- **Bioicons。** 没有国内镜像。官方仓库在 GitHub `duerrsimon/bioicons`，用 GitHub tree API 固定到提交 30f1dd7，取得逐件路径、大小和 git blob id；许可按目录区分（cc-0、cc-by-3.0、cc-by-4.0、cc-by-sa-*、mit、bsd）。`raw.githubusercontent.com` 从 WSL 直连超时（curl 28），桥把这两个任务按大小未知挂到了闲时窗口，已取消。jsDelivr 的 `cdn.jsdelivr.net/gh/duerrsimon/bioicons@30f1dd7/...` 直连可用，内容是同一提交，且逐件按 git blob id 校验，所以采用它；README 的 blob id 也已核对。CC BY-SA 目录不入库。
- **Reactome。** 只有官方源 `reactome.org/icon/R-ICO-xxxxxx.svg`，直连成功。许可页（`reactome.org/license`）存于 `_sources/licenses/`：CC BY 4.0，署名 CSHL、OICR、EBI。
- **Servier Medical Art。** 官网 smart.servier.com 提供 PNG 和 PPT，矢量版需要从 PPT 中拆出。Bioicons 收录的 Servier 矢量件是同一作品（CC BY 3.0，署名 Servier），这次经 Bioicons 取得。
- **NIH BioArt。** 网站由脚本渲染，下载要经过交互页面；部分条目除公有领域外另有署名要求，需要逐件核对。普通下载桥做不了，这次没有取。
- **SciDraw。** 逐件许可，下载需要页面交互，这次没有取。
- **NASA/ESA 图像。** 主要是照片类位图，不适合做矢量示意，并且机构标志受限。天文示意改由代码生成：`contact-binary` 模板直接从 Roche 势计算包层、天空投影和光变曲线。
- **circuitikz。** 本地 TeX 已装（`~/texmf/tex/latex/circuitikz/circuitikz.sty`）。电路图走 TikZ 路线，不进元件库；另有 Tabler 的 circuit-* 图标 13 件，可在 HTML 图中当符号用。
- **不采用。** BioRender、Flaticon 等许可受限或需付费的来源；OpenMoji（图形许可带 SA）；聚合站中逐件许可不清的素材。

### 安全与一致性

所有 SVG 入库前都会检查：不得含脚本、事件属性、`foreignObject`、外部链接。渲染时元件以内联 `<svg>` 嵌入，id 自动加前缀以免冲突；元件内的 `<style>` 类规则会改写到各元素的 `style` 上，不会影响整页样式。上游文件不做修改，重着色只在使用时进行（`data-recolor`）。
