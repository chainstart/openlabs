"""Read-only reconstruction from already evaluated pilot outputs. Never fits models."""
import hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

CODE = Path(__file__).resolve().parent
OUT = Path('/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-drug-response-20261021')
PROJECT = Path('/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-drug-response-day1-20261021')
STATUS = Path('/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-workers-20261021/drug_response/research_status.json')
OLD = OUT.parent / 'drug-support-20261021'
OLDPROJECT = PROJECT.parent / 'biomed-drug-support-20261021'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()
def save(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    q=p.with_suffix(p.suffix+'.tmp'); q.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n'); os.replace(q,p)
def status(stage,next_step,evidence,stop='Direct duplicate prior art, inadequate independence, or no reliable incremental result: stop; no paper promotion.'):
    save(STATUS,dict(updated_at_utc=datetime.now(timezone.utc).isoformat(),question='Independent drug-response/cheminformatics evidence audit and bounded candidate validation',stage=stage,worker=dict(pid=os.getpid(),role='drug_response',argv=sys.argv,cgroup=Path('/proc/self/cgroup').read_text().strip(),process_state='status_writer_running_at_record_time',background_jobs=[]),paper_candidate=False,evidence_paths=evidence,next_step=next_step,stop_conditions=stop,deadline_utc='2026-10-22T00:10:00Z'))
def main():
    status('auditing_existing_evidence','Verify input hashes, splits and published aggregate arithmetic without fitting or selecting against old test.',[])
    hashes={}
    for base in [OLD,OLDPROJECT,Path('/home/biostar/work/openlabs/labs/biomed/studies/drug_support_20261021')]:
        for p in sorted(base.rglob('*')):
            if p.is_file(): hashes[str(p)]=sha(p)
    manifests=[]
    for p in OLD.glob('*/manifest.json'):
        m=json.loads(p.read_text()); f=Path(m['artifact_uri'].removeprefix('file://'))
        assert f.stat().st_size==m['bytes'] and sha(f)==m['sha256']
        manifests.append(dict(manifest=str(p),bytes=m['bytes'],sha256=m['sha256']))
    s=pd.read_csv(OLDPROJECT/'samples.csv'); splits={}
    for col in ['drug_id','cell_line_id']:
        groups={k:set(s.loc[s.split==k,col]) for k in ['train','validation','test']}
        assert all(not groups[a]&groups[b] for a,b in [('train','validation'),('train','test'),('validation','test')])
        splits[col]={k:len(v) for k,v in groups.items()}
    r=json.loads((OLD/'results.json').read_text())
    rank=pd.read_csv(OLD/'rank-support-by-drug.csv'); rank=rank[rank.support=='own_support']
    for k,v in r['metrics'].items(): assert np.isclose(rank[k].mean(),v['drug_macro'],atol=1e-12)
    trans=pd.read_csv(OLD/'translation-by-drug.csv')
    for row in r['translation_drug_macro']:
        g=trans[(trans.method==row['method'])&(trans.subset==row['subset'])]
        assert np.isclose(g.mae.mean(),row['mae'],atol=1e-12)
    # Existing predictions are a previously opened test, used only to check arithmetic.
    pred=pd.read_csv(OLD/'test-predictions.csv.gz')
    for row in trans.itertuples():
        g=pred[pred.DRUG_NAME==row.drug]
        inside=(g.LN_IC50_t>=np.log(g.MIN_CONC_t))&(g.LN_IC50_t<=np.log(g.MAX_CONC_t))
        if row.subset!='all': g=g[inside if row.subset=='destination_supported' else ~inside]
        assert len(g)==row.n
        assert np.isclose(np.abs(g['prediction_'+row.method]-g.LN_IC50_t).mean(),row.mae,atol=1e-12)
    # Independent non-numeric split check and pre-existing code/plan/environment binding.
    oldcode=Path('/home/biostar/work/openlabs/labs/biomed/studies/drug_support_20261021/run_pilot.py')
    assert sha(oldcode)==r['run']['code_sha256']
    assert sha(OLDPROJECT/'plan.json')==r['run']['plan_sha256']
    assert sha(OLDPROJECT/'environment.uv.lock')==r['run']['environment_sha256']
    result=dict(audit_type='retrospective_arithmetic_and_provenance_only',new_confirmatory_evaluations=0,new_models_fitted=0,checks_passed=True,manifests=manifests,splits=splits,counts=r['counts'],translation_rows_checked=len(trans),original_test_already_opened=True,rank_macro_recomputed={k:float(rank[k].mean()) for k in r['metrics']},limitations=['No raw workbook reparse: parsed caches are hash recorded, not independently proven equal to workbooks.','No reconstruction of original timestamp from current files.','Drug-name separation does not establish molecular/scaffold separation.','Old bootstrap conditions on fixed cells and models.','No new inferential claim or repeated confirmatory test.'])
    save(OUT/'existing-evidence-audit.json',result); save(OUT/'existing-input-hashes.json',hashes)
    save(PROJECT/'audit-record.json',dict(result_path=str(OUT/'existing-evidence-audit.json'),sha256=sha(OUT/'existing-evidence-audit.json'),environment_lock_sha256=sha(OLDPROJECT/'environment.uv.lock')))
    status('existing_evidence_audit_passed','Check recent direct neighbors and access/independence of at most six distinct candidates.',[str(OUT/'existing-evidence-audit.json'),str(OUT/'existing-input-hashes.json')])
    print(json.dumps(result,indent=2))
if __name__=='__main__': main()
