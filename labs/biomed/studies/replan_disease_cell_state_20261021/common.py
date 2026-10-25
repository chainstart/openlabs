import os
for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']: os.environ[k]='2'
import sys,json,hashlib,time,urllib.request,urllib.parse,signal,fcntl
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('/home/biostar/work/projects/openlabs')
CODE=ROOT/'openlabs/labs/biomed/studies/replan_disease_cell_state_20261021'
ART=ROOT/'openlabs-artifacts/artifact-stage/biomed/replan-three-sixhour-20261021/disease_cell_state'
DATA=ROOT/'openlabs-data/workspaces/biology/projects/biomed-replan-disease-cell-state-20261021'
OLD=ROOT/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/disease_cell_state'
OD=ROOT/'openlabs-data/workspaces/biology/projects/biomed-fourlane-disease-cell-state-20261021'
DEADLINE='2026-10-21T19:51:45.199167+00:00'
def now(): return datetime.now(timezone.utc).isoformat()
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def atomic(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2));t.replace(p)
def status(stage,done,remaining,failures=[]):
 x=dict(updated_at_utc=now(),status='running',stage=stage,paper_candidate=False,scientific_disposition='pending',research_question='成人IPF来源核验及跨队列程序效应稳定性的可证伪研究',actual_command=' '.join(sys.argv),completed=done,remaining=remaining,failures=failures,deadline_utc=DEADLINE,evidence_paths=[str(DATA/'assessment.json'),str(DATA/'replan.json'),str(ART/'manifest.jsonl')])
 for d in [ART,DATA]:atomic(d/'research_status.json',x)
def fetch(url,name,cap=256*1024**2,timeout=120,metadata=None):
 allowed={'ftp.ncbi.nlm.nih.gov','www.ncbi.nlm.nih.gov','eutils.ncbi.nlm.nih.gov','api.crossref.org','www.ebi.ac.uk','europepmc.org','pmc.ncbi.nlm.nih.gov','api.github.com','raw.githubusercontent.com','github.com','www.nature.com','static-content.springer-cdn.com','www.science.org','api.cellxgene.cziscience.com','datasets.cellxgene.cziscience.com'}
 assert urllib.parse.urlparse(url).hostname in allowed
 out=ART/'payload'/name;out.parent.mkdir(exist_ok=True)
 if out.exists():return out
 for attempt in range(3):
  n=0;h=hashlib.sha256();start=time.monotonic();record=dict(url=url,name=name,retrieved_at_utc=now(),attempt=attempt,release='current response '+now(),independent_unit='metadata; not a biological replicate',terms_url='https://www.ncbi.nlm.nih.gov/home/about/policies/' if 'ncbi' in url else url,reuse_basis='Official public metadata for internal attributed research; file-specific experimental reuse requires separate audit',upstream_study_ids=[])
  record.update(metadata or {})
  try:
   if datetime.now(timezone.utc)>=datetime.fromisoformat(DEADLINE):raise RuntimeError('campaign deadline')
   def alarm(*_):raise TimeoutError('bounded total timeout')
   signal.signal(signal.SIGALRM,alarm);signal.alarm(timeout)
   with urllib.request.urlopen(url,timeout=30) as r,out.with_suffix(out.suffix+'.part').open('wb') as f:
    assert urllib.parse.urlparse(r.url).hostname in allowed,r.url
    record.update(final_url=r.url,status_code=r.status)
    while True:
     b=r.read1(65536)
     if not b:break
     n+=len(b)
     with (ART/'transfer.lock').open('a') as lock:
      fcntl.flock(lock,fcntl.LOCK_EX)
      counter=ART/'transfer_bytes.json';used=json.loads(counter.read_text())['bytes'] if counter.exists() else 0;atomic(counter,dict(bytes=used+len(b)))
     if n>cap or used+len(b)>6*1024**3:raise RuntimeError('byte budget')
     f.write(b);h.update(b)
   out.with_suffix(out.suffix+'.part').replace(out);record.update(status='complete',bytes=n,sha256=h.hexdigest(),path=str(out))
  except Exception as e:record.update(status='failed',bytes=n,error=repr(e))
  finally:signal.alarm(0)
  with (ART/'manifest.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
  print(json.dumps(record),flush=True)
  if record['status']=='complete':return out
  if any(z in record.get('error','') for z in ['403','budget','deadline']):break
  time.sleep(1)
 return None
if __name__=='__main__':
 status('assessment',['Mandatory instructions read; service cgroup and limits verified','Old report, frozen plan and all-trial ledger reviewed'],['Hash old evidence and audit sources','Literature and candidate feasibility','Freeze new plan then experiments'])
 oldfiles=[OLD/'FINAL_REPORT.md',OLD/'RESULTS.json',OD/'plan_frozen_v1.json',OD/'final_trial_ledger.json']
 atomic(DATA/'assessment.json',dict(at=now(),old_evidence={str(p):sha(p) for p in oldfiles},prior_candidates_used=2,prior_configurations=8,prior_outcomes='Primary NNLS improvement unsupported; source count mismatch unresolved; confirmation unopened',limitations='Historical original experiments absent on this host; report hashes do not revalidate experiments',new_candidate_limit=3,new_configuration_limit=12,confirmation_gate='Cannot open unless original-count source reconciliation and new preregistration applicability pass',paper_candidate=False))
 atomic(DATA/'replan.json',dict(at=now(),status='feasibility_not_frozen',deadline_utc=DEADLINE,candidates=[dict(id='C1',question='Can exact original counts be restored or their transformation verified for epithelial ECM attribution?',gate='Official counts or fully explained exact-cell/common-gene transformation',timebox_end_utc='2026-10-21T14:51:45+00:00'),dict(id='C2',question='Are adult IPF ECM/alveolar bulk programme effects transportable across independent cohorts after age/common-support audit?',gate='Official small matrices, adult donor metadata, overlap audit, distinct question beyond DEG'),dict(id='C3',question='Can author donor-by-cell-type summaries identify prespecified programme reference-composition failure boundaries?',gate='Source-verified summaries and independent new confirmation')],freeze_target_utc='2026-10-21T15:21:45+00:00',review_start_latest_utc='2026-10-21T19:21:45+00:00',paper_candidate=False))
 atomic(ART/'environment.json',dict(at=now(),executable=sys.executable,version=sys.version,cgroup=Path('/proc/self/cgroup').read_text(),lock_hashes={str(p):sha(p) for p in [ROOT/'openlabs/labs/biomed/uv.lock',ROOT/'openlabs/labs/biomed/environments/singlecell/uv.lock']}))
