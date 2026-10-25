# drug_support 20261021 新科学重规划

结论：预登记源侧可靠性模型没有在CTRPv2上证实超过原始差值的实质改善。结果是条件性负结果，paper_candidate=false。完整中文报告在本路线artifact根 `FINAL_REPORT.md`。

目录常量位于common.py；旧输入路径由metadata.py的OLD_ART/OLD_DATA指定，均只读。代码没有修改共享环境或依赖锁。使用既有 `labs/biomed/.venv/bin/python`，锁与版本见专属data/environment.json。所有命令从仓库根运行。

以下是原流程命令模板，**不是授权再次打开确认或覆盖冻结产物的运行脚本**。重建需先复制代码，将common.py内ART、DATA、CODE改至新的复算目录，复制当前冻结方案和已有payload引用，保留旧路径只读；新复算已经知道结果，不再标记盲测。不要直接重跑freeze.py/models.py/evaluate.py覆盖本轮封存结果。

```bash
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 /home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python labs/biomed/studies/replan_drug_support_20261021/metadata.py
```

同一guard/线程/解释器前缀下，历史科学顺序为：metadata.py → freeze.py → prepare_source.py → prepare_target.py → models.py → preopening_audit.py → evaluate.py。目标处理只生成封存积分；模型、分数与选择在效应打开前封存。evaluate.py的第一次运行失败后仅做索引修复，再使用 `--resume-after-indexing-failure` 继续；该选项是本次事件记录，不能作为一般重复确认开关。原版脚本与故障日志在artifact保留。

复算和补充审计脚本：

- review_integrals.py：原始PRISM控制归一化和CTRP逐行解析／独立线段积分。
- review_statistics.py：独立排序、逐药物指标、交叉bootstrap前50个抽样及百分位复算。
- audit_identity_models.py：完整结构、模型身份与训练内模型公平性。
- calibration_review.py：预登记次要校准、固定概率分箱、Brier区分。
- descriptive_strata.py：预登记训练身份、组织、池分层描述；保持原选择，不在分层内重新取50%。
- dependence_sensitivity.py、ancestry_review.py：确认后的源板／池及供体亲缘依赖敏感性；不替换主分析。
- make_figures.py：由结果文件生成图。
- closeout.py、final_audit.py、validate_delivery.py、seal_delivery.py：汇总报告、终末哈希和状态；不训练模型。

同一命令前缀替换脚本名即可复算相应步骤。已有结果复核也应写到新的复核目录，以免破坏终末哈希。原始payload来自有来源清单的只读路径或当前intake；不要重新下载已完整存在的数据。`execution-ledger.json`提供实际运行步骤及证据文件，不伪造未留存的精确启动时间。

复用原始PRISM完整MFI，所有新CTRP数据、模型及预测留artifact；小型设计／身份／状态留专属data。统计不确定性条件于已拟合模型与当前面板，原始CTRP板依赖不可恢复。439供体亲缘组来自2022Q2官方元数据，不代表临床验证样本。
