"""Campaign-local bounded I/O and atomic evidence records."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import urllib.request

CODE = Path(__file__).resolve().parent
PROJECT_BASE = Path('/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-functional-genomics-day1-20261021')
ART_BASE = Path('/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-functional-genomics-20261021')
PROJECT = Path(os.environ.get('FG_PROJECT_ROOT',str(PROJECT_BASE))).resolve()
ART = Path(os.environ.get('FG_ARTIFACT_ROOT',str(ART_BASE))).resolve()
assert PROJECT.is_relative_to(PROJECT_BASE) and ART.is_relative_to(ART_BASE), 'Stay within dedicated campaign scope'
WORKER = (Path('/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-workers-20261021/functional_genomics')
          if PROJECT==PROJECT_BASE else ART/'worker')

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.'+str(os.getpid())+'.tmp')
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    os.replace(tmp, path)

def status(step, question, command, evidence=(), state='running'):
    obj = dict(updated_at_utc=now(), status=state, step=step,
               research_question=question, actual_command=command,
               evidence_paths=list(map(str,evidence)), paper_candidate=False,
               deadline_utc='2026-10-22T00:10:00Z',
               stop_conditions=['deadline', 'access/terms/independence failure',
                                'resource budget exceeded', 'novelty or validation inadequate'],
               resources=dict(cpu_threads=2,memory_high_mib=1536,memory_max_mib=2048,
                              tasks_max=96,download_max_bytes=1073741824,
                              per_file_max_bytes=134217728,scratch_max_bytes=3221225472))
    atomic(WORKER/'research_status.json',obj)
    atomic(PROJECT/'research_status.json',obj)
    with (PROJECT/'events.jsonl').open('a') as f:
        f.write(json.dumps(obj,ensure_ascii=False)+'\n')

def fetch(url, name, ceiling=8*1024**2, accept='application/json'):
    """Small metadata only; scientific payloads use canonical dataset_intake."""
    dest=ART/'metadata'/name
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        return dest.read_bytes()
    req=urllib.request.Request(url,headers={'User-Agent':'OpenLabs-biomed/0.1 public research','Accept':accept})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            b=r.read(ceiling+1)
            if len(b)>ceiling: raise ValueError('metadata ceiling exceeded')
            dest.write_bytes(b)
            atomic(dest.with_suffix(dest.suffix+'.access.json'),dict(url=url,status=r.status,
                   retrieved_at_utc=now(),bytes=len(b),sha256=sha(dest)))
            return b
    except Exception as e:
        atomic(dest.with_suffix(dest.suffix+'.failure.json'),dict(url=url,time=now(),error=str(e)))
        raise
