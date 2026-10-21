import os,json,hashlib,datetime,urllib.request
from pathlib import Path
CODE=Path(__file__).resolve().parent
ART=Path('/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/promoter-portability-20261021')
PROJECT=Path('/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-promoter-portability-20261021')
WORKER=Path('/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/promoter-deepening-workers-20261021/functional_genomics')
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def atomic(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_name(p.name+'.tmp');q.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n');os.replace(q,p)
def status(stage,completed,remaining,live=True):
 v=dict(question='Does activity-conditioned promoter directionality transfer across independent reporter systems, and when does it fail?',actualstage=stage,completed_newresults=completed,remaining=remaining,time=now(),paper_candidate=False,live_worker=live)
 for p in [WORKER/'research_status.json',PROJECT/'research_status.json']:atomic(p,v)
 with (PROJECT/'events.jsonl').open('a') as f:f.write(json.dumps(v)+'\n')
def fetch(url,name,limit=8388608):
 p=ART/'metadata'/name;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():return p.read_bytes()
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'OpenLabs public-data research','Accept':'*/*'}),timeout=40) as r:
   b=r.read(limit+1)
   if len(b)>limit:raise ValueError('metadata limit')
   p.write_bytes(b);atomic(str(p)+'.access.json',dict(url=url,time=now(),sha256=sha(p),bytes=len(b),headers=dict(r.headers)))
   return b
 except Exception as e:atomic(str(p)+'.failure.json',dict(url=url,time=now(),error=str(e)));return b''
