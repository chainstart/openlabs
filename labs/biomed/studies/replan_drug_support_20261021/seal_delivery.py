"""Seal final science deliverables after the required review window."""
from common import *
import shutil

def main():
    started=datetime.datetime.fromisoformat(json.loads((ART/'review-start.json').read_text())['at']);ended=datetime.datetime.now(datetime.timezone.utc)
    minutes=(ended-started).total_seconds()/60
    assert minutes>=30,'Required review/report interval not yet complete; no status change.'
    assert ended<datetime.datetime.fromisoformat('2026-10-21T19:51:45.199167+00:00')
    assert json.loads((ART/'delivery-validation.json').read_text())['all_passed']
    for p in [ART/'FINAL_REPORT.md',ART/'RESULTS.json',DATA/'all-trials-ledger.json',ART/'execution-ledger.json',ART/'final-audit.json']:assert p.exists()
    r=json.loads((ART/'research_status.json').read_text());r.update(status='completed',stage='completed',updated_at_utc=now(),scientific_disposition='negative_registered_external_test',paper_candidate=False,completed=['assessment and 3-candidate feasibility','frozen 12 configurations','one new upstream-screen confirmation','raw normalization and integration review','independent statistical implementation','donor/parent and plate/pool dependence audit','Chinese report and full ledger'],remaining=[],stop_reason='Registered material improvement unsupported; all 3 candidates adjudicated; no new independent confirmation remains in scope. No further tuning on exposed CTRP.',review_started_utc=started.isoformat(),review_ended_utc=ended.isoformat(),review_report_minutes=minutes,command={'interpreter':sys.executable,'argv':sys.argv,'guard':'bin/openlabs-resource-guard --task-type cpu --','threads':2},evidence_paths=[str(ART/f) for f in ['FINAL_REPORT.md','RESULTS.json','confirmation-results.json','final-audit.json','delivery-validation.json']],failures=['One confirmation evaluation indexing failure repaired without changing frozen science; full record retained.','1188 external source curve fits failed and were retained with registered handling.'])
    for base in (ART,DATA):write(base/'research_status.json',r)
    execution=json.loads((ART/'execution-ledger.json').read_text())
    execution['records'].append({'script':str(CODE/'seal_delivery.py'),'command':f'{ROOT}/openlabs/bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 {sys.executable} {CODE}/seal_delivery.py','sha256':sha256_file(__file__),'status':'executed','at':now()})
    write(ART/'execution-ledger.json',execution)
    for fn in ['execution-ledger.json','delivery-validation.json','dependence-sensitivity.json','descriptive-strata.json']:shutil.copyfile(ART/fn,DATA/fn)
    excluded={'scientific-manifest.json','events.jsonl','agent.stderr','supervisor.log','process-status.json','intake.lock'}
    files=[]
    for base in (CODE,DATA,ART):
        for p in sorted(base.rglob('*')):
            if not p.is_file() or p.name in excluded or '__pycache__' in p.parts or 'mpl-cache' in p.parts:continue
            files.append({'path':str(p),'bytes':p.stat().st_size,'sha256':sha256_file(p)})
    manifest={'created_at_utc':now(),'description':'Final scientific snapshot; self and mutable process/supervisor/agent logs excluded; all scores/models and original confirmation retained.','excluded_names':sorted(excluded),'excluded_directories':['__pycache__','mpl-cache'],'files':files,'review_report_minutes':minutes}
    for base in (ART,DATA):write(base/'scientific-manifest.json',manifest)
    print(json.dumps({'status':'completed','scientific_disposition':r['scientific_disposition'],'paper_candidate':False,'review_report_minutes':minutes,'files_hashed':len(files),'manifest_sha256':sha256_file(ART/'scientific-manifest.json'),'report':str(ART/'FINAL_REPORT.md')},indent=2))
if __name__=='__main__':main()
