"""Close the bounded lane honestly; no shared state or manuscript promotion."""
from common import *
import collections, csv, math

res=json.loads((DATA/'c3-results.json').read_text())
review=json.loads((DATA/'c3-independent-review.json').read_text())
assert review['passed']
meta=json.loads((DATA/'c3-metadata-feasibility.json').read_text())
trials=json.loads((DATA/'c3-trial-ledger.json').read_text())
commands=[f'{ROOT}/bin/openlabs-resource-guard --task-type cpu -- {ROOT}/labs/biomed/.venv/bin/python {CODE}/{script}' for script in ['c3_metadata.py','c3_freeze.py','c3_run.py select','c3_run.py evaluate','c3_verify.py']]
sources=[
 ('Roberts2021','10.1101/gr.270751.120','journal','跨报告链不对称及与活性的关系已属直接先行工作；分箱轨迹不是精确克隆配对。','roberts.xml'),
 ('Agarwal2025','10.1038/s41586-024-08430-9','journal','原共同方向库及跨细胞相关性已发表；旧K562 ENCSR382BVV不独立。','agarwal.xml'),
 ('Zhang2025','10.1186/s13059-025-03828-8','journal','已经系统比较多种MPRA；泛称平台差异不能构成创新。','zhang.xml'),
 ('QUASARR2026','10.1038/s41467-026-68780-y','journal','已研究双启动子/增强子功能与载体启动子背景；完整精确插入与旧200nt库无匹配。','quasarr.xml'),
 ('PARM2026','10.1038/s41586-025-10093-z','journal','已有跨系统/多背景序列模型与突变验证；本轮未训练或调用该模型，不声称胜过它。','parm.xml'),
 ('Tan2026','10.64898/2026.06.25.734173','preprint','已比较六报告设计、识别转录/RNA混杂、拟合响应性、开展motif扰动并连接内源CRISPR。C3只增加旧类别在固定新面板的增量校准检验。','tan.xml'),
 ('RegTrust-XAI2026','10.64898/2026.08.20.745945','preprint','已讨论预测可靠性、独立lentiMPRA解释迁移和PKLR突变验证。不能以泛称可靠性为创新；本条核查官方API摘要而非已读全文。','regtrust_biorxiv.json'),
 ('Bergman2022','10.1038/s41586-022-04877-w','journal','已提出P1/P2类别与响应性及GABPA/YY1解释。C3类别效果不能被重命名为新机制。','bergman-nature.html')]
lit=[]
for name,doi,kind,difference,payload in sources:
    lit.append(dict(name=name,doi=doi,publication_status=kind,original_source='https://doi.org/'+doi,scope_difference=difference,payload=str(ART/'payload'/payload),sha256=sha(ART/'payload'/payload)))
write(DATA/'nearest-work-audit.json',dict(time=now(),skill='paper-lookup',sources=lit,databases=['Crossref works/{DOI}','Europe PMC search?query=DOI:...&format=json and /{PMCID}/fullTextXML','bioRxiv details/biorxiv/{DOI}/na/json'],raw_responses='Artifact payload/*_crossref.json, *_epmc.json, *_biorxiv.json; exact endpoints in manifests',limitations=['No claim of exhaustive literature coverage or novelty from absence of hits.','Bergman fullTextXML/BioC retrieval failed; official publisher abstract, figure captions, supplementary tables and official repository inspected instead.','RegTrust-XAI full text not archived; technical comparison limited to official preprint abstract.']))

candidates=[dict(id='C1',question='精确同一插入的跨原始研究方向性迁移',disposition='data_gate_not_met_in_audited_libraries',evidence=['exact-library-audit.json','sequence-gate-independent-verification.json','new-library-cross-intersections.json'],models=0,reason='旧200nt序列去掉文档明确的15nt两侧接头后，与QUASARR/Tan/Klein/PARM已完整下载设计无全长正向或反向互补匹配；PARM大随机片段文件未完成且仅坐标/计数不能自动确认克隆。不是所有公开库皆无匹配的证明。'),dict(id='C2',question='同一原始研究内六种报告设计的方向失效边界',disposition='insufficient_independent_loci_and_prior_art',evidence=['tan-exact-orientation-audit.json'],models=0,reason='六设计共用的小库只有2个精确正反配对增强子位点。大203E库有11对但不是六设计独立扩充，也不是启动子方向终点；Tan已直接比较正反一致性。不能用测量对数扩大独立n。'),dict(id='C3',question=res['limitations'][0] if False else '旧STARR启动子类别对新体系响应性的条件校准',disposition='pilot_positive_but_scientific_target_not_met',evidence=['c3-plan.frozen.json','c3-results.json','c3-independent-review.json'],models=8,reason='达到冻结的无类别主对照试点阈值，但相对class_only的区间包含零；不是原方向终点，不是新机制，且只有一个目标体系与发布端跨面板归一化。')]
write(DATA/'candidate-ledger.json',dict(time=now(),maximum=3,used=3,candidates=candidates))

network=[];hashchecks=[]
for p in sorted((ART/'manifests').glob('*.json')):
    d=json.loads(p.read_text());network.append(dict(manifest=str(p),status=d.get('status'),actual_bytes=d.get('actual_bytes',0),attempts=d.get('attempts',[]),source_url=d.get('source_url'),stop_reason=d.get('stop_reason',d.get('reason'))))
    if d.get('payload') and d.get('sha256') and Path(d['payload']).is_file():hashchecks.append(dict(path=d['payload'],matches=sha(d['payload'])==d['sha256']))
assert all(x['matches'] for x in hashchecks)
parts=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p),usable=False) for p in (ART/'payload').glob('*.part')]
known=sum(x['actual_bytes'] for x in network)
scratch=sum(p.stat().st_size for p in ART.rglob('*') if p.is_file())
write(DATA/'complete-trial-ledger.json',dict(time=now(),candidate_ledger=candidates,model_trials=trials,model_configurations_used=8,maximum_configurations=12,seeds=[20261021],failed_model_trials=[],other_failures=[dict(step='HTML extraction recovery',error='bs4 absent in locked environment',handling='Used Python standard-library HTMLParser; no package installation'),dict(step='Bergman supplementary archive',error='296-byte response is not ZIP',handling='Preserved and excluded; used official separate text tables'),dict(step='download interruption',error='6 .part payloads incomplete',handling='SHA recorded; none included as complete scientific data; original failures and alternatives retained')],download_operations=network,partial_files=parts,no_new_candidate_or_model_after_test=True))
write(DATA/'resource-accounting.json',dict(time=now(),known_manifest_network_bytes=known,conservative_partial_extra_bytes=sum(p['bytes'] for p in parts),network_accounting_note='Sum of recorded transfer bytes; interrupted partials added separately as conservative potential extra (can double-count). A power failure prevents exact count of in-flight transport bytes; never label this an exact network total.',scratch_bytes=scratch,download_limit_bytes=6*1024**3,scratch_limit_bytes=12*1024**3,threads=2,http_concurrency_max=2,gpu_used=False,packages_installed=0,cgroup=Path('/proc/self/cgroup').read_text()))

write(DATA/'c3-limitations-after-freeze.json',dict(time=now(),plan_unchanged=True,observations=['Frozen use-case suggested triage after basal activity/quality measurement. n_for_P_resp already requires enhancer assays, so full model has only retrospective calibration interpretation; cost-saving/prospective utility is not established.','Source numerical activity and source repeat precision were not fitted. No claim beyond source-class annotation is justified.','Primary no-class contrast is not the strongest overall simple-baseline contrast. class_only must be prominent; its improvement CI contains zero.'],new_models_or_endpoints=0))

artifact_hashes={str(p.relative_to(ART)):dict(bytes=p.stat().st_size,sha256=sha(p)) for sub in ('payload','sequences','c3') for p in (ART/sub).rglob('*') if p.is_file()}
write(DATA/'artifact-hash-index.json',artifact_hashes)
write(DATA/'final-code-hashes.json',{str(p):sha(p) for p in CODE.glob('*.py')})
result=dict(schema_version='openlabs.promoter_transfer_results.v1',stage='exploratory_pilot',status='needs_replan',scientific_disposition='Original directionality transfer lacks an eligible audited independent-system panel; C3 supports source-class informativeness but not a demonstrated advantage over its strongest simple source-class baseline or the requested novel evidence standard.',paper_candidate=False,candidate_budget_used=3,model_configurations_used=8,original_question_answered=False,exploratory_pilot=res,strongest_simple_comparison=review['strongest_simple_comparison'],verification_passed=review['passed'],nearest_work=lit,candidate_ledger=candidates,resource_accounting=json.loads((DATA/'resource-accounting.json').read_text()),protocol_applicability={'supported':'hash-bound source files, frozen plan, grouped samples, complete 8-model ledger, numeric results and review','not_claimed':'full biomed-public-data-pilot validator pass; cross-root artifacts and transductively normalized reporter labels require explicit extension, not fabricated donor/study independence'},reproduction_commands=commands,environment=json.loads((DATA/'environment.json').read_text()),hash_indexes=['artifact-hash-index.json','final-code-hashes.json','c3-freeze-hashes.json','c3-code-freeze.json'],remaining_for_future=['Independent exact opposite-orientation reporter panel with sequence/genome/endpoint provenance for original question','For C3, independent target panel and frozen endpoint scaling; source continuous activity/repeat precision controls; genuinely prospective features; innovation beyond already published P1/P2 biology'],stop_reason='Three cumulative candidate designs evaluated; C3 necessary review complete. End early rather than tune exposed test or fill the 24-hour window.')
for root in (ART,DATA):write(root/'RESULTS.json',result)

primary=res['primary'];simple=review['strongest_simple_comparison']
lines=[]
for tr in trials:
    n=tr['configuration'];metric=res['metrics'][n]
    lines.append(f"| {n} | {tr['validation_MSE']:.6f} | {metric['MSE']:.6f} | [{metric['MSE_CI95'][0]:.6f}, {metric['MSE_CI95'][1]:.6f}] |")
litlines='\n'.join(f"- {n}（{'预印本' if k=='preprint' else '已发表'}），[原始来源](https://doi.org/{doi})：{diff}" for n,doi,k,diff,_ in sources)
report=f'''# promoter_transfer 科学结项报告

本轮状态 **needs_replan，paper_candidate=false**。三个候选设计已评估，完成一个新的、提前冻结的真实数据校准试点及结果复核。原问题“启动子方向性在独立报告体系何时保留或失效”仍未被检验；没有达到2025中科院升级版大类二区及以上创新性与证据目标，也不把数值试点通过当成论文候选。

替代试点发现旧STARR启动子类别含有新报告体系响应性的信息，但复杂模型相对最强简单类别基线的优势不确定：MSE **0.197531 对 0.229240**，绝对改善 **{simple['absolute_MSE_reduction']:.6f}**，95%组bootstrap区间 **[{simple['absolute_CI95'][0]:.6f}, {simple['absolute_CI95'][1]:.6f}]**。区间跨零不等于两者等效。这个结论应优先于下面较弱的无类别对照改善数字。

## 断电恢复与边界

原截止时间为2026-10-22 11:46:31.613021 UTC，本轮提前结束；未延长。恢复时核对专属service和openlabs-workers.slice，2 CPU、4 GiB软/5 GiB硬内存、512 MiB swap、96 tasks。旧running只作为历史状态，未接管旧进程。首轮83个有哈希已完成文件核验一致，6个部分下载保留为不可用；后续重新核验已完成payload，未发现哈希变化。旧Agarwal/QUASARR报告只读，旧原始实验不在本机，**没有复算或重新验证旧原始结果**。

本轮没有改动共享依赖、源注册表、全局配置、factory SQLite或选刊政策，没有GPU、子代理、嵌套Codex、外发、投稿、付费、公开发布或git提交。资源记录见resource-accounting.json。记录的网络接收量{known/1024**2:.2f} MiB；额外未完成文件共{sum(p['bytes'] for p in parts)/1024**2:.2f} MiB，保守另计但可能重复。断电在途字节无法精确恢复，故不声称精确总流量。结项前scratch约{scratch/1024**2:.2f} MiB，远低于12 GiB。

## 三个累计设计及裁定

1. **C1：精确同一插入的跨研究方向迁移。** 新获取原Agarwal设计库；仅按文档剥离两端各15nt接头，保留200nt元件，逐条做全长DNA或完整反向互补比较。QUASARR的1733条设计序列（1728条唯一）、Tan各库、Klein的2336条设计记录（2302条唯一）与该旧元件全集均未建立全长匹配。QUASARR仅7条为200nt，也无匹配。PARM完整合成验证表3556条barcode记录实际是889个序列、没有非回文正反配对、没有旧库全长匹配。另一50条PARM子库也无匹配。原始随机片段库下载只到部分且只有坐标/计数格式，不能以重叠坐标冒充克隆同一性。独立XML序列抽取复核结果一致。**限于已审计文件的数据门槛未过，不宣称所有公开数据都不存在可行配对。**
2. **C2：同研究六报告设计方向边界。** Tan六设计小库只有2个可核实正反配对的独立增强子位点。大203E库有11对，但不是六体系的独立扩充，也不是启动子方向终点。Tan已直接分析正反一致性；不能将两位点乘以promoter、重复或构建数当独立n。对2位点的总体失效规律估计没有可用精度，停止。Klein注释中无反向序列行不等于实验未测反向，不能这样推断；这里拒绝的是与原200nt库的精确匹配及未建立新独立面板。
3. **C3：旧STARR启动子类别对新体系响应性的校准。** 在Bergman 2022的1000条启动子设计与Tan 2026的503条设计之间，找到**433条完整、同向、精确DNA匹配**。这解锁了不同终点的有限试点，不解锁原方向题。按冻结QC得到267条合格位点并完成8配置实验。结果及局限如下。

C1/C2保留exact-library-audit.json、sequence-gate-independent-verification.json、new-library-cross-intersections.json及tan-exact-orientation-audit.json；所有下载失败及替代路线见complete-trial-ledger.json。未因单次下载失败或模型不优放弃领域，没有重置候选/配置预算。

## C3：问题、用途与数据独立性

可证伪问题：在已知新体系基础活性、测量质量和简单序列组成之后，旧体系发表的P0/P1/P2类别能否改善新体系P_resp的留出预测？来源是Bergman ExP STARR-seq（GSE184426，补充表1），目标是Tan整合于K562 AAVS1位点的upstream 21E×500P（GSE334082，补充表4，预印本）。上游是两次原始研究/不同实验与报告位置，但共享K562、部分作者和设计沿革；**不是独立实验室或独立供体验证**。

序列匹配为完整264nt同向字面相等；未用基因组重叠替代。Tan说明默认hg19；本轮未从参考基因组重新提取或重测物理克隆，不能扩展为已验证所有参考版本和克隆方向。源表位置与目标实验身份由原始表/方法追踪，不臆造跨组装转换。

P_resp是log2 enhancer effect对平均enhancer effect的无截距斜率；不是正向减反向，也不是基础RNA/DNA活性。其尺度依赖原作者全库平均效应及78P/500P共同启动子的比例校准，故本分析显式使用**发布端跨面板归一化的终点**，不宣称严格归纳或新独立确认。来源类别是离散标签，没有兼容的来源标量可作identity/affine方向复制；这些原题对照不适用，不能将缺失记为胜出。也没有开展sequence-only prediction，因此没有声称击败PARM、ProCapNet或RegTrust模型。

冻结时用途设想包含实验分流；复核发现n_for_P_resp等质量变量已经需要目标enhancer测量。因此本结果只支持**事后校准/关联信息**，并未证明可减少实验成本的前瞻工具。此限制单独记录于c3-limitations-after-freeze.json，原冻结计划没有改写。

## 元数据、划分和预登记

433条匹配进一步排除源负控、作者TSS QC失败、缺失终点/质量信息，以及不足2个负控或5个enhancer配对，最终267条。503条目标记录中236条未纳入，排除理由可重叠，完整逐条表在c3-metadata-feasibility.json。未按终点大小删除样本。

训练135位点/112组，验证39位点/33组，测试93位点/84组。基因、坐标重叠、同1Mb区块以及≥20%共享canonical 21-mer的连接分量不跨集合。此前看到的前13行及关联基因/分组、与26P/78P重复的序列均强制进入训练。原公布终点整体归一化仍不能由这种分组消除。训练侧选择/标准化，验证集只选一次，未重拟合，测试单次打开；有开始和完成标记。

测试84组的正态近似80%功效要求标准化组级配对损失效应约0.306 SD；没有在标签未读时虚报5%改善必有功效。实际相关效应预设为绝对MSE降低≥0.01且相对≥5%、95%改善区间下限>0，并且点估计胜过class_only。0.1单位P_resp误差在log2 enhancer effect=5时对应0.5 log2输出误差，是试点容差而不是期刊标准。

8个固定配置、单一种子20261021，HGB固定100轮/4叶/learning_rate .05/min_leaf15/l2=10，不早停、不调参；ridge alpha=1。特征：目标基础活性、负控数、enhancer配对数、TSS内reads比例、GC、CpG，额外类别用固定one-hot。所有数值变换只在训练拟合，无插补、阈值搜索、额外筛选。完整配置和代码哈希在冻结文件中。

## 全部结果与不确定性

| 冻结配置 | 验证MSE | 测试MSE | 测试MSE的95%组bootstrap区间 |
| --- | ---: | ---: | --- |
{chr(10).join(lines)}

验证选出无类别nuisance_hgb和含类别full_hgb。主比较绝对MSE改善{primary['absolute_MSE_reduction']:.6f}，95%区间[{primary['absolute_CI95'][0]:.6f}, {primary['absolute_CI95'][1]:.6f}]；相对改善{primary['relative_MSE_reduction']*100:.2f}%，区间[{primary['relative_CI95'][0]*100:.2f}%, {primary['relative_CI95'][1]*100:.2f}%]。冻结的有限试点标准通过。

**nuisance_hgb只是无旧类别的强对照，不是全部简单模型中的最强者。** class_only MSE=0.229240；full_hgb对它的改善13.83%，绝对区间跨零，不能确认复杂模型额外价值。full_ridge MSE=0.211598，也是相近表现。候选测试MSE范围0.197531–0.211598；所有无类别控制0.328097–0.550225；没有事后将测试最优配置重新命名主模型。

10,000次配对连接分量bootstrap，按整组重采样再按位点聚合。区间条件于当前训练、源类别、发布端归一化及单目标实验，不含实验室/供体/培养重复层面的不确定性。类别0测试只有1个位点，类别1有27、类别2有65；分层结果留存但不能据此提出可靠失效边界或新确认。未把细胞数、条码数、enhancer–promoter测量对数当独立样本数。未拟合源连续活性与源重复精度，不回答原题要求的完整强基线比较。

## 最近工作与创新门槛

{litlines}

检索按paper-lookup技能保留Crossref、Europe PMC、bioRxiv API原始JSON和精确URL，见nearest-work-audit.json、literature-index.json及artifact/manifests。Bergman官方全文API失败后改用出版社页面、图注、独立补充文件与固定版本代码；RegTrust仅按官方摘要审阅，未夸称读完全文。不能用“没有搜到”证明首创。

本试点没有提出超出已发表P1/P2生物学的新规律。跨实验的类别信息量可复核，但无法替代独立体系方向性数据、新机制或验证过的前瞻用途。正结果有限，零结果也没有足够精度被宣称等价或有论文级新负发现。

## 复核、复现与证据契约

所有8模型的验证/测试MSE从保存预测逐项独立算术重算；100次bootstrap用另一种逐行重采样实现逐项一致。503条目标补充表与作者仓库序列全部一致，759个有限P_resp/P_basal数值差异为0。**同一数据两份文件一致不是外部独立复现。** 冻结数据、方案、代码哈希均通过；源类别和目标序列来源留痕。未重新打开测试以调参或换指标。

实际解释器：{ROOT}/labs/biomed/.venv/bin/python。锁文件SHA256：`{sha(ROOT/'labs/biomed/uv.lock')}`。方案SHA256：`{sha(DATA/'c3-plan.frozen.json')}`。代码冻结索引SHA256：`{sha(DATA/'c3-code-freeze.json')}`。预测SHA256：`{sha(ART/'c3/test_predictions.csv')}`。完整payload/代码索引在artifact-hash-index.json与final-code-hashes.json。

原执行命令依次为（全部通过CPU guard；代码冻结/分组审计记录同时保留）：

```bash
{chr(10).join(commands)}
```

现有目录有single-open保护，不应删除标记后再次运行select/evaluate；数值复核直接运行最后一条c3_verify.py，使用保存预测而不重开确认。验证只重建算术证据，不是新增科学验证。完整下载/失败/试验账本为complete-trial-ledger.json，原始失败和6个部分payload全部保留。

证据契约适用部分包括冻结方案、锁哈希、来源及文件条款、实际样本分组、全试验账本、结果和复核。跨data/artifact路径、已发布跨面板归一化终点及实验单位不是该通用协议完整覆盖的设计，**未伪造biomed-public-data-pilot完整验证通过**，未写factory数据库。源公开补充表只作私有有署名研究；Tan预印本CC BY-NC-ND 4.0、仓库无独立LICENSE，未将其错误标成可任意再分发数据。

## 停止判断与下一步条件

三候选累计预算已用尽，8/12配置已完成；剩余配置额度不是继续在已暴露测试上搜索的许可。本轮提前结束，不以进程存活或耗满24小时替代科学进展。恢复原方向题需新的、明确正反克隆且全长同一插入、报告终点兼容的独立体系面板；继续C3需独立目标实验、固定归一化锚点、来源连续活性及重复精度对照、真正可前瞻获得的特征，并明确超出既有类别效应的贡献。没有选刊、投稿或录用承诺。
'''
for root in (ART,DATA):
    p=root/'FINAL_REPORT.md';tmp=p.with_suffix('.md.tmp');tmp.write_text(report);tmp.replace(p)
write(DATA/'result_bundle.json',dict(schema_version='openlabs.result_bundle.v1',lab_id='biomed',domain='biology',paper_candidate=False,status='needs_replan',protocol_validation='not_claimed',evidence=[dict(path=str(p),sha256=sha(p)) for p in [ART/'FINAL_REPORT.md',ART/'RESULTS.json',DATA/'c3-independent-review.json',DATA/'complete-trial-ledger.json',DATA/'artifact-hash-index.json',DATA/'final-code-hashes.json']]))
state=dict(updated_at_utc=now(),status='needs_replan',stage='scientific_closeout',paper_candidate=False,research_question='Original promoter directionality transfer plus explicitly distinct C3 source-class responsiveness calibration',scientific_disposition=result['scientific_disposition'],command=' '.join(sys.argv),completed=['recovery integrity audit','three cumulative candidate designs','C3 frozen metadata/plan and eight configurations','single exploratory holdout','saved-prediction arithmetic and official supplement verification','Chinese final report and result bundle'],remaining=result['remaining_for_future'],stop_reason=result['stop_reason'],candidate_budget_used=3,model_configurations_used=8,evidence_paths=[str(ART/'FINAL_REPORT.md'),str(ART/'RESULTS.json'),str(DATA/'result_bundle.json')])
for root in (ART,DATA):write(root/'research_status.json',state)
with (ART/'progress.jsonl').open('a') as f:f.write(json.dumps(state,ensure_ascii=False)+'\n')
print(json.dumps(dict(status=state['status'],report=str(ART/'FINAL_REPORT.md'),results=str(ART/'RESULTS.json'),verified_payload_files=len(hashchecks),known_network_bytes=known,scratch_bytes=scratch),indent=2))
