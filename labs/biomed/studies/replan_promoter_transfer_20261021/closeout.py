"""Seal completed scientific pilot; no claims of achieving the paper target."""
from common import *
import math
guard_check()
result=json.loads((ART/'RESULTS.json').read_text())
assert result['status']=='needs_replan' and result['paper_candidate'] is False
start=datetime.datetime.fromisoformat(json.loads((DATA/'review-start.json').read_text())['documented_review_start_utc'])
elapsed=(datetime.datetime.now(datetime.timezone.utc)-start).total_seconds()
assert elapsed>=1800,'Final review not yet complete; do not idle merely to satisfy elapsed time.'
for name,h in result['run']['code_sha256'].items():assert sha(pathlib.Path(__file__).parent/name)==h
def finite(o):
    if isinstance(o,float):assert math.isfinite(o)
    elif isinstance(o,dict):
        for v in o.values():finite(v)
    elif isinstance(o,list):
        for v in o:finite(v)
finite(result)
assert sha(ART/'RESULTS.json')==sha(DATA/'RESULTS.json')
assert sha(ART/'FINAL_REPORT.md')==sha(DATA/'FINAL_REPORT.md')
assert len(json.loads((DATA/'complete-trial-ledger.json').read_text())['current_trials'])==12
review=dict(time=now(),review_duration_seconds=elapsed,review_start_utc=start.isoformat(),same_agent_independent_implementation=True,
    outcome='Arithmetic, freeze boundary, predictor invariance, provenance, cohort/units caveats and report tables reviewed; no publication-level claim.',
    primary_hypothesis_supported=False,closest_full_comparator_complete=False,paper_candidate=False)
write(DATA/'final-review.json',review)
state=dict(updated_at_utc=now(),status='needs_replan',phase='scientific_closeout',scientific_disposition=result['scientific_disposition'],
    research_question=result['research_question'],paper_candidate=False,deadline_utc=DEADLINE.isoformat(),
    completed=['3候选评估与重规划','真实数据/来源/独立单位核验','本地前瞻冻结','12配置及3预指定条件实验','一次确认预测与10000组bootstrap','原结果保留及数值平分纠错','独立算术实现/特征边界/哈希复核','中文报告、全结果、账本、图与证据包'],
    remaining=['论文贡献目标未达；未来须新未暴露确认、作者中间处理及最近完整方法比较，不能重新划分本轮确认集'],
    actual_command='bin/openlabs-resource-guard --task-type cpu -- '+str(ROOT/'labs/biomed/.venv/bin/python')+' labs/biomed/studies/replan_promoter_transfer_20261021/closeout.py',
    evidence_paths=[str(ART/'FINAL_REPORT.md'),str(ART/'RESULTS.json'),str(DATA/'complete-trial-ledger.json'),str(ART/'evidence-manifest.json')],
    failures=['主假设未达到实用增益门槛','最近915特征LASSO未复现，不能宣称全面方法优势','Tovar16094重处理队列不等于作者11656','后确认数值平分纠错已披露，原主结果不变','早期HTTP交接瞬时并发不可证始终<=2'],
    research_complete_within_scope=True,publication_goal_achieved=False,model_configurations_used=12,confirmation_open_count=1)
for d in (DATA,ART):write(d/'research_status.json',state)
files=[]
for d in ['payload','manifests','analysis_inputs','models','predictions','analysis','derived','figures','replays']:
    files.extend(p for p in (ART/d).rglob('*') if p.is_file())
files.extend(ART/p for p in ['FINAL_REPORT.md','RESULTS.json','freeze.json','test-opened.json','research_status.json','analysis-summary.log','analysis-corrected-summary.log'])
files.extend(p for p in DATA.iterdir() if p.is_file() and p.name!='evidence-manifest.json')
files.extend(pathlib.Path(__file__).parent.glob('*.py'))
entries=[dict(path=str(p),size_bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(set(files))]
manifest=dict(time=now(),kind='lane_scientific_evidence_manifest',formal_protocol_validator_passed=False,
    entries=entries,mutable_process_logs_excluded=['events.jsonl','agent.stderr','process-status.json','supervisor.log','agent-final-message.md'],
    original_artifacts_readonly=True,old_reference_audit=str(DATA/'reuse-hash-audit.json'),paper_candidate=False)
for d in (ART,DATA):write(d/'evidence-manifest.json',manifest)
print('sealed',len(entries),'files','status=needs_replan','review_seconds',elapsed)
