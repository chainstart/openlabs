# disease_cell_state：冻结分析的复核

这是 2026-10-21 六小时 campaign 的独立重规划代码。`common.py` 固定本路线的代码、data 和 artifact 根目录。旧实验脚本没有作为运行时依赖；唯一只读实验输入是已核验的 GSE134692 基因长度注释。所有解释器、下载、解析与绘图须经资源 guard，且保留本路线 service 的 CPU 与内存限制。

以下是本轮实际使用的复核命令，保留用于核对。交付目录封存后不要直接重跑这些写记录的命令；应先按下文建立隔离副本，再使用完整解释器路径：

```bash
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python labs/biomed/studies/replan_disease_cell_state_20261021/verify_math.py
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python labs/biomed/studies/replan_disease_cell_state_20261021/reconstruct_results.py GSE184316 GSE199949 GSE150910
bin/openlabs-resource-guard --task-type cpu -- /home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python labs/biomed/studies/replan_disease_cell_state_20261021/integrity_review.py
```

`verify_math.py` 只检查软件代数与表头解析。`reconstruct_results.py` 从官方矩阵逐行重建同一冻结分析，独立反演二项分布尾概率，并用 statsmodels 复核 HC3 区间；它不调用评分和主分析函数、不选择模型、不构成新的确认或独立生物实验。此复核会更新本轮复核记录；若要保留首次复核时间，应先复制相应 JSON 记录。

实际实验的顺序是 `bulk_io.py inspect`（仅标识与形状）、`bulk_io.py freeze`（共同基因标识集合）、`bulk_io.py score GSE184316 GSE150910`、`analyse_bulk.py GSE184316 GSE150910`、`open_confirmation.py`、`bulk_io.py score GSE199949`、`analyse_bulk.py GSE199949`。冻结文件、逐供体输出、一次打开标记和代码哈希共同界定实际分析。

`score`、`analyse`、`freeze` 和 `open_confirmation` 均拒绝覆盖已有关键结果。不要删除标记或输出以重开确认。完整重放须在新的隔离副本中进行，明确标为同一冻结分析的确定性复算；在副本的 `common.py` 修改输出根目录、只读引用原 payload、保留全部冻结输入和原打开记录。此路径修改应另记哈希，不能声称原代码文件未变。

原始文件 URL、实际传输量、重试及 SHA-256 见 artifact `manifest.jsonl`。已经完整存在的 payload 不重新下载。实际环境与锁哈希见 `environment_actual.json`；未安装新依赖。`plot_results.py` 只把冻结估计转成表格和图片。

这套设计采用开发、独立研究确认和背景队列，未拟合预测模型；通用三分 train/validation/test 合同不适用。不能把自定义复核记录冒充该合同的通过记录。
