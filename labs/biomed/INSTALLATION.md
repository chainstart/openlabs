# 本机建立与验证记录

检查日期：2026-10-20。此记录描述本次本机部署，不表示任何科学发现或论文质量通过。

## 已就绪

| 部分 | 本机状态 | 关键版本或证据 |
|---|---|---|
| 实验室接入 | 已注册 `biomed` / `biology` | 通用 runner、CLI、manifest schema、研究/论文 Skill 路由 |
| 基础与化学 Python | 已安装、导入通过 | Python 3.12.3；RDKit 2026.9.1；scikit-learn 1.9.1；XGBoost CPU 3.4.1 |
| 常规组学 Python | 已安装、导入通过 | PyDESeq2 0.5.4；GSEApy 1.3.1 |
| 单细胞 CPU | 已安装、导入与计算通过 | Scanpy 1.12.4；AnnData 0.12.19；Leidenalg 0.12.0 |
| R/Bioconductor | 已安装、导入与计算通过 | R 4.4.3；GEOquery 2.74.0；DESeq2 1.46.0；limma 3.62.1；edgeR 4.4.0 |
| GPU / scVI / Census 客户端 | 可选组已锁定，未部署 | 不影响 CPU 研究；启用前需验证驱动、模型和资源预算 |
| 首个项目 | 已创建、协议两种模式通过、保持暂停 | `biomed-chem-generalization-pilot`；尚未选择科学 assay 或启动研究 |

Python 环境精确依赖与包哈希见 `uv.lock` 和 `environments/singlecell/uv.lock`。
R 的 208 个 conda 包已导出同平台 explicit 锁，含 SHA-256，并通过缓存离线 dry-run 解析检查。
额外注释包的原始 URL、镜像和双校验和保存在 `environments/r-annotation-lock.json`。

## 实际验证

- 实验室测试：38 项通过，包含化学标准化、训练/测试边界、篡改证据、数据大小限制、
  分组泄漏、HTTP 续传与 R 注释补装修复。测试中的模拟标签不是科学结果。
- 非数学领域的实验室发现与调度冒烟：7 项通过，2 项数学相关测试未纳入该次筛选。
- 配置与资源准入检查：10 项通过；合并验证共 55 项通过、2 项数学相关测试未纳入。
- 新代码 Ruff 检查、格式检查与研究 Skill 校验通过。
- 真实暂停项目经通用项目加载和协议执行器验证，discovery/commit 均通过。
- 单细胞软件验证：128 个模拟细胞、64 个基因，保留 counts 层并完成归一化、PCA、
  邻居图和 Leiden 聚类；没有下载真实单细胞图谱，也没有生物学结论。
- R 软件验证：全部必需 namespace 可加载，100 个模拟基因、6 个模拟样本完成
  DESeq2 size-factor 估计与 limma 拟合。
- R 安装器曾退出成功，但 `GenomeInfoDbData` 实际缺失，导致多个包无法加载；已从安装器
  登记的 Galaxy 镜像补装同版 1.2.13，核对上游 MD5 与 SHA-256，并验证包的 namespace/版本。
  注释档案 SHA-256 为 `51a33c432e65261ef81a7c2039b17cbdf7a0b417376fdb7ada4d618566f7074e`。
- ChEMBL 实际下载验证：API 报告 `ChEMBL_37`；固定参考记录 `CHEMBL25` 下载成功，
  生成 1 行 RDKit 描述符与 Morgan 指纹统计；版本检查前后一致，原响应与输出均有 SHA-256。
  默认网络路径曾返回 HTTP 500，列表查询亦发生超时；改用固定记录和可访问的官方 HTTPS
  路径验证成功。失败尝试保留，没有被记成成功数据集。
- PubChem 实际探测：当前网络将 PUG REST 请求重定向到 `misuse.ncbi.nlm.nih.gov`，
  工具按来源登记拒绝该响应，未生成成功 manifest；尚未宣称 PubChem 已连通。
- GEO、DepMap 和第二阶段数据源已登记访问/版本/条款与重叠风险，尚未下载研究数据。

本机额外尝试了原有集成检查，存在两项与本次新代码无关的环境缺项：

- 数学冒烟启动被既有门禁阻止：本机 `openlabs-workers-math.slice` 未设置要求的
  16/18 GiB、无 swap 上限。
- 原 runner 契约测试 17 项通过、1 项因缺少 `bubblewrap` 失败。该测试使用自定义非 Codex
  agent 的隔离工作区；本次未改动 runner 或放宽其要求。

## 本机状态与产物位置

代码环境位于本目录 `.venv` 与 `environments/singlecell/.venv`，不进入 Git。
小型项目位于：

```text
/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-chem-generalization-pilot/
```

本次安装与软件验证记录位于：

```text
/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/setup-20261020/
/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/chembl-reference-smoke-20261020/
```

前者含环境、R 修复与单细胞软件测试 JSON；后者含真实 ChEMBL 响应、manifest、描述符与 smoke report。
它们是本机 artifact staging，尚未由工厂晋升为正式研究证据或公开发布。

所有安装、测试与计算均使用仓库资源护栏。未执行 GPU 工作负载，未启动定时器、
正式研究或论文投稿，未修改既有论文的选刊与审稿状态。

当前 WSL 可见内存约 8 GiB，原调度预留 8192 MiB 会阻止任何任务启动。
`config/openlabs.toml` 已将本机调度预留设为 2048 MiB，并增加 3 GiB 试点准入回归检查；
聚合 cgroup 的 CPU/内存/GPU 规则保持原值，实际任务仍受当前可用内存与总预留限制。
本机只读准入探测已确认 3072 MiB 试点在当时可用容量内；没有实际启动研究 worker。
