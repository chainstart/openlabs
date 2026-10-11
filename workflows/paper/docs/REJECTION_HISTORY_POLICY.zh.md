# 缺失历史原拒信的逐篇授权政策

默认规则仍要求独立编辑逐一核对历史拒信，只有有依据的 `resolved` 或 `compatible`
才能进入审稿。2026-10-11 用户明确授权四篇论文：缺失原信这一事实本身不阻断正常
编辑与唯一 Codex referee B 的判断。它不是免除科学要求，也不授权投稿。

数据仓库的逐篇元数据可登记以下结构。实际授权收据必须是
`openlabs.actual_author_instruction.v1`，来源为当前会话的真实用户消息；读取 JSON
pointer 后的对象必须具有同一 mode、包含当前 paper_id、同一 authorization 文字，
以及唯一对应当前论文且逐项相同的 missing_decision_ids。收据文件须安全且 SHA-256
完全一致；不能用内部模型输出或作者推断替代。

```yaml
missing_rejection_letter_policy:
  mode: available_originals_only
  paper_id: 20260506aiuncertainty0010
  missing_decision_ids:
    - 4a26c4a0bf21570c2e3a
    - 1f90ad7745ad6413762d
  authorization:
    path: maintenance/20261011-six-paper-continuation/author-facts/ACTUAL-FOUR-PAPER-POLICY-AND-MODEL-INSTRUCTION-20261011.json
    sha256: 9f47231c93410328e9c99dcac515e6ef5444e7c976de251143c91e0e51a41bbc
    json_pointer: /missing_original_letters
    summary: "Missing original rejection letters do not by themselves block normal independent editor/referee evaluation or conditional supporting-material publication. Available authentic letters remain included; substantive scientific and editorial standards continue."
```

同一真实收据还覆盖 `20260415aiuncertainty0003`、
`20261004-math-group-projective-root-row-sums` 和
`20261005-biology-genetics-reference-orientation-depth`；它们当前的授权缺信列表为空。
各篇仍须显式登记自己的 paper_id 与准确列表，不在收据范围的论文不能套用。
空列表不允许跳过后来新增的缺信决定。原收据保留原文与历史来信状态，代码不编辑它。

对于列出的、当前确实缺少原文的决定，编辑必须逐项返回 `not_assessable`、
`answered: false`，并说明不可核对的知识边界。不能称原信已经恢复、已解决或与现稿
兼容。现有所有真实原信、认证专家报告和真实已投稿稿件仍完整提供给编辑和审稿人。
已有拒信的未回应理由、科学缺口或矛盾判断仍阻断。登记过的原信文件缺失、SHA 错误、
错误期刊/编号绑定、空原文或不安全路径属于坏证据，不能利用这项政策当作缺信跳过。

此前必须项原文仍进入 fresh referee 的待核对列表。仅要求提供被授权的缺失原信的
项，新审稿人可以依据当前政策认定不再适用，记录 `resolved: true` 和具体原因；
这指请求的政策关闭，不能伪造历史科学异议已经被回答。包含科学/已有原信异议的
混合项不得自动关闭。历史模型决定和分数不修改。

政策及授权 SHA 纳入当前逐篇 `review_policy_sha256`；登记、变更或撤销授权均要求
新评审。其他没有启用该字段的论文仍使用完全相同的旧默认 fingerprint。新原信恢复
或证据改变也使旧 `not_assessable` 结论失效。应用决定和交付时都会重查。

该模块不放宽目标期刊、正文、支撑包、作者事实、独立评审或科学标准，不将内部模拟
结论改为外部期刊决定。已有有效用户收据无需再次询问授权。真实内部统一编辑/审稿
流程及所有其他条件通过后，发布仍由既有主流程办理。
