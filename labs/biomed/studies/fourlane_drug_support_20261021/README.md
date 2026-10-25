# Drug-support 四路研究：恢复后结案

本路线源数据、冻结方案和结果不在代码目录。固定位置见 `common.py`：数据项目 `biomed-fourlane-drug-support-20261021`，artifact `four-lanes-20261021/drug_support`。最终中文科学结论在 artifact `FINAL_REPORT.md` / `RESULTS.json`，研究状态在同根及数据项目的 `research_status.json`。

计算顺序为 metadata/feasibility → freeze → prepare_curves → models → evaluate → review_results → final_audits → finalize。原来的冻结文件不可覆盖；已有确认后，prepare_curves/models/evaluate 会拒绝静默重跑。复制重现实验需要独立目录和明确的“已暴露数据计算复现”标签，不会生成新的独立确认。

在现有产物上，可用以下入口检查证据，不训练、选型或改变主终点：

```bash
/home/biostar/work/projects/openlabs/openlabs/bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 /home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python /home/biostar/work/projects/openlabs/openlabs/labs/biomed/studies/fourlane_drug_support_20261021/review_results.py
/home/biostar/work/projects/openlabs/openlabs/bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 /home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python /home/biostar/work/projects/openlabs/openlabs/labs/biomed/studies/fourlane_drug_support_20261021/final_audits.py
```

`check_analysis.py` 使用构造数组验证数学实现，不产生科学证据。`audit_external_metadata.py` 和 `beataml_mapping_audit.py` 只检查独立ex vivo路线的元数据，不解析原始表的 normalized_viability。`make_figures.py` 只绘制已保存评价。

累计预算不因断电恢复重置：3个候选数据设计，11个预测配置+1个固定曲线配置；确认开启一次。负结果和近邻方法覆盖情况不能通过改对照、阈值、终点或再次确认规避。此次实验不涉及CUDA、外发消息、投稿、环境安装或工厂SQLite写入。
