# OpenLabs 计算生物医学与化学信息学实验室

`lab_id: biomed`，`domain: biology`。从公开生物、化学和医学相关分子数据开展纯计算研究；
不执行湿实验、患者招募、临床干预或临床诊断服务。初期只接入公开访问数据。
公开来源中的人类分子数据仍需核对实际使用条件，不能自动宣称伦理豁免。

阶段进展见 [2026-10-21 研究结果汇总](RESULTS-20261021.md)，包括功能基因组学两轮验证、失败方向和下一步条件。

## 研究与证据

首批方向为化学活性预测的骨架外泛化、跨研究表达信号稳定性、细胞系依赖性预测。
单细胞为扩展方向。候选方向不是已核验的新颖成果，不承诺发表。

`lab.json` 接入已有 runner 和 `biomed-public-data-pilot` 协议。
研究主 Skill 是 [`biomed-research-loop`](skills/biomed-research-loop/SKILL.md)，论文沿用
`openlabs-biology-paper`。协议只验证探索试点的身份、计划、环境哈希、数据溯源、划分和
结果账本；不能把 pilot 提升为 paper candidate，不能替代独立科学审查。

完成的试点必须重新验证真实 payload 的 SHA-256，并从样本表重新计算分组重叠检查。
计划、状态与结果的具体字段见 [证据契约](skills/biomed-research-loop/references/evidence-contract.md)。
化学测定需保留单位、关系/删失标志、assay 和文献来源；不能直接混合 IC50/Ki/Kd。
组学需保留供体、研究、平台、基因组版本和处理信息；细胞数不是独立供体数。
归一化、插补、特征选择与调参必须在训练边界内完成。解释图与富集不是机制证明。

## 环境

所有下列命令从仓库根目录运行，始终通过资源护栏。环境安装不启用定时器或研究任务。

基础环境与化学/常规组学 Python 依赖锁在 `uv.lock`；单细胞使用独立项目/锁文件，
R/Bioconductor 使用独立 micromamba 环境。不要 `--all-groups` 安装单细胞深度学习依赖。
`uv` 引导版本为 0.13.3；安装进本地 `.venv`，不改动系统 Python。

```bash
bin/openlabs-resource-guard --task-type cpu -- python3 -m venv labs/biomed/.venv
bin/openlabs-resource-guard --task-type cpu -- labs/biomed/.venv/bin/python -m pip install uv==0.13.3
bin/openlabs-resource-guard --task-type cpu -- labs/biomed/.venv/bin/uv sync --project labs/biomed --frozen --group chem --group bulk --group dev
bin/openlabs-resource-guard --task-type cpu -- labs/biomed/.venv/bin/uv sync --project labs/biomed/environments/singlecell --frozen
```

R 环境的维护入口为 `environments/bulk-r.yaml`；本机的精确包 URL 与 SHA-256 已导出到
`environments/bulk-r-linux-64.explicit.txt`，后者用于同平台重建。

```bash
bin/openlabs-resource-guard --task-type cpu -- micromamba create -y -p "$PWD/labs/biomed/environments/bulk-r/.venv" -f labs/biomed/environments/bulk-r-linux-64.explicit.txt
```

本次遇到 conda 安装器完成后 `GenomeInfoDbData` 仍无法加载，需补装同版注释数据。
`environments/r-annotation-lock.json` 记录原始 URL、可用镜像、上游 MD5 与实测 SHA-256。
重建后先运行下面的 R 检查；若缺失该包，从登记 URL 获取正确命名的
`GenomeInfoDbData_1.2.13.tar.gz`，使用以下命令核验双校验和并安装到独立 R prefix：

```bash
../../bin/openlabs-resource-guard --task-type cpu -- .venv/bin/python -m tools.repair_r_annotation --archive /path/to/GenomeInfoDbData_1.2.13.tar.gz --output /path/to/artifact-stage/r-annotation-repair.json
```

此命令从实验室目录运行，不升级其他 R 包；修复后再运行 R 检查。

包版本检查之外，可从实验室目录执行两个模拟数据的软件验证；它们不产生研究结论：

```bash
../../bin/openlabs-resource-guard --task-type cpu -- environments/singlecell/.venv/bin/python -m tools.singlecell_smoke --output /path/to/artifact-stage/singlecell-smoke.json
../../bin/openlabs-resource-guard --task-type cpu -- environments/bulk-r/.venv/bin/Rscript --vanilla tools/check_bulk_r.R /path/to/artifact-stage/r-environment.json
```

GPU 深度学习环境按课题启用 `singlecell` 的 `deep` 组，锁定适合驱动的 PyTorch/CUDA
组合后重新验证。这里不预装或训练大型基础模型。安装成功不代表该模型能在 GPU 预算内运行。
任何 CUDA 计算都必须使用 `--task-type gpu --gpu-memory-mib 4096 --gpu-device 0` 重新预约，
即使父进程已在 CPU 护栏内。首批 CPU 任务建议 2 线程、3 GiB 内存、2 GiB 临时盘；
以实际可用内存为准，不能把护栏 30 GiB 软上限当成主机实际容量。
本机约 8 GiB 可见内存对应的调度预留已在 `config/openlabs.toml` 设为 2048 MiB，
避免原 8192 MiB 预留使所有任务都无法准入；聚合 cgroup 上限不变。

## 数据与存储

[`registries/data_sources.json`](registries/data_sources.json) 登记官方文档、访问路线、许可检查、
引用方式与数据重叠风险。第一阶段 ChEMBL、PubChem、GEO、DepMap；第二阶段
CELLxGENE、GDC 开放分子数据、Open Targets 和 Reactome。
登记不代表已经下载、条款统一、外部独立或能绕过网站验证；DepMap 用官方发布下载，
CELLxGENE 用版本化客户端查询，不爬取门户或复制整库。

- 小型状态：`$OPENLABS_WORKSPACE/openlabs-data/workspaces/biology/projects/<project-id>/`。
- 大型原始文件、模型、预测表：任务的 `artifact_staging_root`。
- 手工接入可用外部 `openlabs-artifacts/artifact-stage/biomed/<run-id>/`，不得直接写 published objects。
- 完成后由控制面校验并晋升。这里的工具不直接写工厂 SQLite。

`dataset_intake` 必须指定来源、版本/accession、样本单位、文件级使用条款、引用和上游研究标识。
默认每文件上限 64 MiB；更大的文件需显式预算。下载流式进行，失败不产生完成 manifest；
同一调用内最多两次重试，有 HTTP validator 时可续传。跨调用重新接入使用新 dataset ID，
失败目录保留以便审计，不覆盖既有原始数据。不会自动解压未知档案或执行下载内容。
当前 HTTP 工具不接受需提供凭据的起始地址。公开发布入口产生的临时签名重定向仅在内存中
使用，最终 URL 的敏感查询不写入 manifest；遇到新的官方重定向 host，应核实后更新登记。

从实验室目录使用以下模块（Python 路径按仓库位置替换）；完整 CLI 参数见 `--help`：

```bash
../../bin/openlabs-resource-guard --task-type cpu -- .venv/bin/python -m tools.dataset_intake --help
../../bin/openlabs-resource-guard --task-type cpu -- .venv/bin/python -m tools.split_audit --help
../../bin/openlabs-resource-guard --task-type cpu -- .venv/bin/python -m tools.chemistry --help
../../bin/openlabs-resource-guard --task-type cpu -- .venv/bin/python -m tools.chemical_baseline --help
../../bin/openlabs-resource-guard --task-type cpu -- .venv/bin/python -m tools.environment_report --group core --group chem --group bulk
```

样本 CSV 含 `sample_id,split` 和独立单位列，split 为 train/validation/test。
化学 scaffold 划分需 `molecule_id,scaffold_id`；供体需 `donor_id`；细胞系需 `cell_line_id`；
跨研究需 `study_id`。工具检查列值是否跨集合，但无法证明上游标识符规范化、时间顺序或
真实独立性；这些仍需研究审查，不能只比较下载链接。

`tools.chemistry` 为小分子 CSV 提供有限预算的标准化：Cleanup、FragmentParent、去电荷、
规范互变异构体、保留规范化后的异构 SMILES，并计算分子/骨架标识。原 SMILES 和测定字段
保留，拒绝行另存。所有无环分子保守地归为一个骨架组。混合物、金属、立体化学和盐形式
需根据问题审查；该操作不负责活性标签和单位合并，不能直接把任意测定变成可靠训练集。

`tools.chemical_baseline` 接收已审查的、带 split 与标准结构的兼容实测活性表，比较中位数预测
与固定参数 Morgan 指纹随机森林。默认只评估 validation，不转换或使用 test 特征和标签；
只有显式 `--evaluate-test` 才评估最终测试集。输出预测、计划相关运行记录和输入/代码/环境哈希，
不自动晋升结果或声明新颖性。真实项目仍需匹配最近方法、多随机种子、不确定性和外部验证。
当前生成的首个项目还没有选择具体 assay，因此不自动训练此基线。

## 建立暂停的首个项目

从实验室目录运行，`--data-root` 指向实际私有数据仓库。命令不覆盖已有项目，不创建论文 ID。

```bash
../../bin/openlabs-resource-guard --task-type cpu -- .venv/bin/python -m tools.init_project --data-root /path/to/openlabs-data
```

生成 `project.status: paused` 与 `workstream.startup: paused`，优先开展近期文献与 assay
可行性审计，尚未选定科学数据集或宣称新颖性。激活项目必须是后续明确的研究操作。
论文选刊遵循届时根目录 AGENTS.md 和数据 registry 的实际策略，不在本实验室固定期刊等级。

## 验证

```bash
bin/openlabs-resource-guard --task-type cpu -- labs/biomed/.venv/bin/python -m pytest labs/biomed/tests -q
bin/openlabs-resource-guard --task-type cpu -- labs/biomed/.venv/bin/python -m pytest orchestrator/tests/test_labs.py orchestrator/tests/test_tick_smoke.py -q
```

真实联网小测试从实验室目录运行：

```bash
../../bin/openlabs-resource-guard --task-type cpu -- .venv/bin/python -m tools.live_smoke --staging-root /path/to/openlabs-artifacts/artifact-stage/biomed/unique-smoke-run
```

它在 ChEMBL API 版本检查前后获取固定参考分子 CHEMBL25，计算 RDKit 描述符和指纹，
保存原始响应/manifest/描述符哈希；只验证基础设施，不训练模型、不宣称生物发现。
当前机器的实际安装与验证结果见 [安装记录](INSTALLATION.md)。
