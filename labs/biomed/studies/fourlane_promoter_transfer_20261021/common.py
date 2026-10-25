"""Lane-local bounded provenance utilities; no shared state writes."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[k]='2'
import sys,json,hashlib,datetime,time,urllib.request,urllib.parse
from pathlib import Path
CODE=Path(__file__).resolve().parent
ROOT=CODE.parents[3]
ART=ROOT.parent/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/promoter_transfer'
DATA=ROOT.parent/'openlabs-data/workspaces/biology/projects/biomed-fourlane-promoter-transfer-20261021'
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def write(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    q=p.with_suffix(p.suffix+'.tmp');q.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n');q.replace(p)
def status(stage,done,remaining,**kwargs):
    v=dict(updated_at_utc=now(),status='running',stage=stage,paper_candidate=False,
       research_question='Which measured source features predict retention or failure of promoter directionality in an independent reporter system?',
       command=' '.join(sys.argv),completed=done,remaining=remaining,**kwargs)
    for root in (ART,DATA):write(root/'research_status.json',v)
    with (ART/'progress.jsonl').open('a') as f:f.write(json.dumps(v,ensure_ascii=False)+'\n')
def fetch(name,url,*,limit=32*1024**2,terms='Metadata for internal attributed scientific audit; file reuse not yet authorized',study='',accession='',attempts=2,max_seconds=180):
    """Sequential HTTP, strict byte cap, bounded retry, preserve failure metadata."""
    assert urllib.parse.urlsplit(url).scheme=='https'
    allowed={'api.crossref.org','www.ebi.ac.uk','api.biorxiv.org','www.ncbi.nlm.nih.gov','ftp.ncbi.nlm.nih.gov','api.github.com','raw.githubusercontent.com','media.springernature.com','static-content.springer-cdn.com','www.encodeproject.org','encode-public.s3.amazonaws.com','eutils.ncbi.nlm.nih.gov','www.nature.com'}
    assert urllib.parse.urlsplit(url).hostname in allowed, 'Unreviewed source host'
    assert datetime.datetime.now(datetime.timezone.utc)<datetime.datetime.fromisoformat('2026-10-22T11:46:31.613021+00:00'),'Campaign deadline'
    target=ART/'payload'/name;target.parent.mkdir(exist_ok=True)
    manifest=ART/'manifests'/f'{name}.json'
    if target.exists() and manifest.exists():return target
    previous=sum(x.get('actual_bytes',0) for p in (ART/'manifests').glob('*.json') for x in [json.loads(p.read_text())]) if (ART/'manifests').exists() else 0
    assert previous+limit<=6*1024**3
    record=dict(source_url=url,accession=accession,upstream_study=study,terms=terms,retrieved_at_utc=now(),attempts=[])
    for attempt in range(attempts):
        count=0;start=time.monotonic();last_progress=start;part=target.with_suffix(target.suffix+'.part')
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'OpenLabs-promoter-research/1.0'})
            with urllib.request.urlopen(req,timeout=40) as response,part.open('wb') as out:
                record['final_url']=response.url;record['headers']=dict(response.headers)
                if int(response.headers.get('Content-Length',0))>limit:raise ValueError('Content-Length exceeds budget')
                while True:
                    b=response.read(65536)
                    if not b:break
                    count+=len(b)
                    if count>limit or time.monotonic()-start>max_seconds:raise ValueError('Byte/time budget exceeded')
                    if datetime.datetime.now(datetime.timezone.utc)>=datetime.datetime.fromisoformat('2026-10-22T11:46:31.613021+00:00'):raise ValueError('Campaign deadline')
                    out.write(b)
                    if time.monotonic()-last_progress>120:
                        status('data_download_in_progress',[f'{name}: {count} bytes received'],['complete bounded stream and metadata audit'],download=dict(file=name,bytes=count,elapsed_seconds=time.monotonic()-start))
                        last_progress=time.monotonic()
            part.replace(target)
            record.update(actual_bytes=count+sum(a['bytes'] for a in record['attempts']),payload_bytes=count,sha256=sha(target),payload=str(target),status='downloaded')
            record['attempts'].append(dict(attempt=attempt+1,bytes=count,status='success'));write(manifest,record)
            return target
        except Exception as e:
            record['attempts'].append(dict(attempt=attempt+1,bytes=count,error=str(e)))
            record.update(status='failed',actual_bytes=sum(a['bytes'] for a in record['attempts']))
            write(manifest,record)
            if attempt+1<attempts:time.sleep(2)
    return None
if __name__=='__main__':
    assert 'openlabs-biomed-four-promoter-transfer-20261021.service' in Path('/proc/self/cgroup').read_text()
    status('literature_and_data_gate',['resource limits and required instructions read'],['nearest work audit','exact insert metadata feasibility','freeze eligible design or document failure'])
    write(DATA/'environment.json',dict(interpreter=sys.executable,version=sys.version,lock=str(ROOT/'labs/biomed/uv.lock'),lock_sha256=sha(ROOT/'labs/biomed/uv.lock'),cgroup=Path('/proc/self/cgroup').read_text(),threads=2,cuda_used=False))
