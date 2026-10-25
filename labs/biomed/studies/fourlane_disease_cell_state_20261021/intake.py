"""Bounded, serial, audited official-source intake for this lane only."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='2'
import sys,json,hashlib,time,urllib.request,urllib.parse,fcntl,signal
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('/home/biostar/work/projects/openlabs')
ART=ROOT/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/disease_cell_state'
DATA=ROOT/'openlabs-data/workspaces/biology/projects/biomed-fourlane-disease-cell-state-20261021'
def now(): return datetime.now(timezone.utc).isoformat()
def atomic(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False));tmp.replace(path)
def status(stage,done,remaining):
    obj=dict(updated_at_utc=now(),status='running',stage=stage,paper_candidate=False,research_question='成人IPF的ECM/肺泡修复跨研究信号能否可靠区分捕获组成与细胞内表达变化？',completed=done,remaining=remaining,actual_command=' '.join(sys.argv),evidence_paths=['manifest.jsonl'],failures=[],scientific_disposition='pending',deadline_utc='2026-10-22T11:46:31.613021+00:00')
    if (DATA/'plan_frozen_v1.json').exists():
        obj['research_question']=json.loads((DATA/'plan_frozen_v1.json').read_text())['research_question']
    if (DATA/'recovery_integrity_audit.json').exists():
        obj['evidence_paths'].append(str(DATA/'recovery_integrity_audit.json'))
        obj['failures']=['Power-loss cache corruption quarantined; original evidence preserved in recovery/']
    for root in (ART,DATA): atomic(root/'research_status.json',obj)
def fetch(url,name,cap=32*1024**2,metadata=None):
    allowed={'ftp.ncbi.nlm.nih.gov','www.ncbi.nlm.nih.gov','api.crossref.org','www.nature.com','pmc.ncbi.nlm.nih.gov','www.ebi.ac.uk','europepmc.org','static-content.springer-cdn.com','api.github.com','raw.githubusercontent.com','www.science.org','eutils.ncbi.nlm.nih.gov','api.cellxgene.cziscience.com','datasets.cellxgene.cziscience.com'}
    allowed.add('mirrors.tuna.tsinghua.edu.cn')  # Signed Ubuntu package URI from local apt metadata; tools only.
    assert urllib.parse.urlparse(url).hostname in allowed
    out=ART/'payload'/name;out.parent.mkdir(exist_ok=True)
    if out.exists(): return out
    totalfile=ART/'transfer_bytes.json'
    def account(n):
        with (ART/'transfer.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            used=json.loads(totalfile.read_text())['bytes'] if totalfile.exists() else 0
            atomic(totalfile,dict(bytes=used+n))
            return used+n
    for attempt in range(3):
        count=0;sha=hashlib.sha256();start=time.monotonic()
        rec=dict(url=url,name=name,started_at_utc=now(),attempt=attempt,terms_url='https://www.ncbi.nlm.nih.gov/home/about/policies/' if 'ncbi' in url else url,reuse_basis='Public official metadata/internal attributed research; accession-specific restrictions pending review; no redistribution',upstream_study_ids=[name.split('_')[0]],independent_unit='donor (unverified)',release='retrieved '+now())
        rec.update(metadata or {})
        try:
            def alarm_handler(*args): raise TimeoutError('total download deadline exceeded')
            signal.signal(signal.SIGALRM,alarm_handler);signal.alarm(900)
            with urllib.request.urlopen(url,timeout=45) as r, out.with_suffix(out.suffix+'.part').open('wb') as f:
                assert urllib.parse.urlparse(r.url).hostname in allowed, r.url
                rec.update(final_url=r.url,http_status=r.status)
                while True:
                    b=r.read1(64*1024)
                    if not b: break
                    count+=len(b);used=account(len(b))
                    if count>cap or used>6*1024**3 or time.monotonic()-start>900: raise RuntimeError('budget/time exceeded')
                    sha.update(b);f.write(b)
            out.with_suffix(out.suffix+'.part').replace(out)
            rec.update(status='complete',bytes=count,sha256=sha.hexdigest(),path=str(out))
        except Exception as e: rec.update(status='failed',bytes=count,error=repr(e))
        signal.alarm(0)
        with (ART/'manifest.jsonl').open('a') as f:f.write(json.dumps(rec)+'\n')
        print(json.dumps(rec),flush=True)
        if rec['status']=='complete':return out
        if '403' in rec.get('error','') or 'budget' in rec.get('error',''):break
        time.sleep(2)
    return None
if __name__=='__main__':
    status('metadata_and_literature_intake',['cgroup and service limits verified','protocol and campaign read'],['literature audit','donor mapping','freeze feasible design','real experiments'])
    atomic(ART/'environment.json',dict(executable=sys.executable,version=sys.version,cgroup=Path('/proc/self/cgroup').read_text(),locks={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'openlabs/labs/biomed/uv.lock',ROOT/'openlabs/labs/biomed/environments/singlecell/uv.lock']}))
    for acc in ['GSE134692','GSE135893','GSE136831','GSE250346']:
        fetch(f'https://ftp.ncbi.nlm.nih.gov/geo/series/{acc[:-3]}nnn/{acc}/suppl/',acc+'_files.html')
        fetch(f'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={acc}&targ=self&form=text&view=full',acc+'_series.txt')
    for doi in ['10.1038/s41467-025-56623-1','10.1186/s13059-025-03776-3','10.1038/s41467-025-62579-z','10.1038/s41592-026-03007-y','10.1038/s41588-025-02080-x']:
        fetch('https://api.crossref.org/works/'+urllib.parse.quote(doi,safe=''),doi.split('/')[-1]+'_crossref.json')
