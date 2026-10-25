"""Close the authorized bounded phase after substantive review and final checks."""
from common import *
from datetime import timedelta
assert not (ART/'scientific_closeout.json').exists()
review=json.loads((DATA/'final_review_plan.json').read_text())
started=datetime.fromisoformat(review['started_at_utc'])
assert datetime.now(timezone.utc)>=started+timedelta(minutes=30),'Complete the reserved review period first'
assert datetime.now(timezone.utc)<datetime.fromisoformat(DEADLINE)
result=json.loads((ART/'RESULTS.json').read_text())
assert result['paper_candidate'] is False and result['trials_run']==12
assert result['primary_test']['n']==9 and result['primary_test']['k']==5 and result['primary_test']['supported'] is False
for name in ['output_semantic_audit.json','rank_and_secondary_numeric_review.json','integrity_review.json']:
 check=json.loads((ART/name).read_text());assert check.get('all_pass',check.get('all_checks_pass')),name
for name,ref in result['evidence'].items():assert sha(ref['path'])==ref['sha256'],(name,'stale result reference')
for name,h in result['run']['code_hashes'].items():assert sha(CODE/name)==h,(name,'code changed after final report')
for acc in ['GSE184316','GSE199949','GSE150910']:
 assert (ART/f'{acc}_independent_numeric_review.json').exists()
assert not list((ART/'payload').glob('*.part')),'Unfinished intake file remains'
assert sha(DATA/'RESULTS.json')==sha(ART/'RESULTS.json')
ledger=json.loads((DATA/'final_trial_ledger.json').read_text())
assert len(ledger['current']['configuration_outcomes'])==12
assert ledger['historical']['full_ledger_snapshot']==json.loads((OD/'final_trial_ledger.json').read_text())
assert ledger['historical']['full_results_snapshot']==json.loads((OLD/'RESULTS.json').read_text())
closed=now();disposition='bounded_phase_completed_primary_inconclusive_no_paper_candidate; original_attribution_source_gate_unresolved'
review.update(completed_at_utc=closed,elapsed_review_minutes=(datetime.fromisoformat(closed)-started).total_seconds()/60,completed_work=['Independent raw-row abundance and binomial-tail reconstruction','Published rank baseline and secondary slope implementation cross-check','Complete unit/exclusion/pair/one-time-exposure audit','Closest original-paper and official methods-supplement review','All baseline, unavailable-model, historical-ledger and Chinese report reconciliation','Frozen files, payload bytes, shared locks and resource integrity'])
atomic(DATA/'final_review_plan.json',review)
replan=json.loads((DATA/'replan.json').read_text())
replan.update(status='needs_replan',phase_completed_at_utc=closed,scientific_disposition=disposition,result_sha256=sha(ART/'RESULTS.json'),paper_candidate=False,old_confirmation_opened=False)
atomic(DATA/'replan.json',replan)
status_record=dict(updated_at_utc=closed,status='needs_replan',stage='scientific_closeout',scientific_disposition=disposition,authorized_phase_completed=True,scientific_goal_completed=False,paper_candidate=False,research_question=result['research_question'],actual_command=' '.join(sys.argv),completed=['3candidate assessments','12registeredconfiguration attempts;3fullcontextHC3 unavailable','One new independentstudy primary evaluation;5/9,CI0.2120085to0.8630043,notconfirmed','Atleast30minutesof numerical/source/report review','Chinese report, full historical/current ledger and hash-bound evidence'],remaining=[],stop_reason='Current candidate/configuration budget completed; narrow result lacks sufficient novelty/precision and original attribution source remains unresolved. No additional model or threshold search.',next_experiment='Requires a new justified design and budget; do not reuse exposed confirmation to choose thresholds',deadline_utc=DEADLINE,old_confirmation_opened=False,managed_jobs='All task-launched intake/experiment exec sessions finished; no task worker left running',evidence_paths=[str(ART/n) for n in ['FINAL_REPORT.md','RESULTS.json','final_trial_ledger.json','integrity_review.json','delivery_manifest.json']])
for root in [ART,DATA]:atomic(root/'research_status.json',status_record)
state=dict(schema_version='openlabs.biomed_pilot_state.v1',project_id=result['project_id'],workstream_id='disease_cell_state',status='needs_replan',paper_candidate=False,research_question=result['research_question'],independent_unit='lung_donor',next_experiment=status_record['next_experiment'],plan={'path':'plan_frozen_v1.json','sha256':sha(DATA/'plan_frozen_v1.json')},environment={'path':str(ART/'environment_actual.json'),'sha256':sha(ART/'environment_actual.json')},datasets=result['source_datasets'],evidence=result['evidence'],claims=[{'status':'provisional','claim':'Observed paired event count5/9; prespecified frequency criterion not confirmed; no equivalence claim','evidence':str(ART/'GSE199949_analysis.json')},{'status':'provisional','claim':'Disease programme direction replicated descriptively across3studies; no cell-state/causal identification','evidence':str(ART/'all_estimates.csv')}],scientific_disposition=disposition,contract_status=result['contract_status'],updated_at_utc=closed)
atomic(DATA/'state.json',state)
atomic(DATA/'project.json',dict(schema_version='openlabs.project.v1',project_id=result['project_id'],domain='biology',lab_id='biomed',protocol={'id':'biomed-public-data-pilot','primary_skill':'biomed-research-loop','adaptation':'Observational donor-repeated design; generic threeway validator not claimed'},workstreams=[{'workstream_id':'disease_cell_state','state':'state.json'}],status='needs_replan',paper_candidate=False))
close=dict(at=closed,scientific_disposition=disposition,review_minutes=review['elapsed_review_minutes'],deadline_utc=DEADLINE,authorized_phase_completed=True,scientific_goal_completed=False,paper_candidate=False,final_report_sha256=sha(ART/'FINAL_REPORT.md'),results_sha256=sha(ART/'RESULTS.json'),old_confirmation_opened=False,managed_jobs_finished=True)
for root in [ART,DATA]:atomic(root/'scientific_closeout.json',close)
paths=[p for root in [ART,DATA,CODE] for p in root.iterdir() if p.is_file() and p.suffix in ['.json','.jsonl','.csv','.md','.py','.png','.pdf','.svg','.txt'] and p.name!='delivery_manifest.json']
manifest=dict(at=closed,scope='Final top-level deliverables and study code; rawpayloads separately hash-bound in manifest.jsonl and integrity_review.json',files=[{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(paths)])
atomic(ART/'delivery_manifest.json',manifest)
print(json.dumps(dict(**close,delivery_manifest_sha256=sha(ART/'delivery_manifest.json'),files_bound=len(paths))))
