"""Lane-local bounded HTTPS intake. Run only through resource guard."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import tempfile
import urllib.request
import urllib.parse

ROOT = Path('/home/biostar/work/projects/openlabs')
ART = ROOT/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/perturbation_context'
DATA = ROOT/'openlabs-data/workspaces/biology/projects/biomed-fourlane-perturbation-context-20261021'
HOSTS = {'api.crossref.org','pmc.ncbi.nlm.nih.gov','www.ncbi.nlm.nih.gov','eutils.ncbi.nlm.nih.gov','www.ebi.ac.uk','www.biorxiv.org','api.biorxiv.org','www.nature.com','raw.githubusercontent.com','api.github.com','github.com','genome-scale-tcell-perturb-seq.s3.amazonaws.com','ftp.ncbi.nlm.nih.gov','api.figshare.com','ndownloader.figshare.com','s3-eu-west-1.amazonaws.com','www.cell.com'}

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def atomic(p, obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=p.parent,prefix=p.name+'.',suffix='.tmp',delete=False) as f:
        json.dump(obj,f,indent=2);f.flush();os.fsync(f.fileno());tmp=Path(f.name)
    tmp.replace(p)
    fd=os.open(p.parent,os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
def status(stage, completed, remaining, evidence=(), failures=()):
    old=json.loads((DATA/'research_status.json').read_text())
    old.update(updated_at_utc=now(), stage=stage, completed=completed, remaining=remaining,evidence_paths=list(evidence),failures=list(failures))
    for r in [ART,DATA]: atomic(r/'research_status.json',old)
def check(url):
    u=urllib.parse.urlsplit(url)
    if u.scheme!='https' or u.hostname not in HOSTS or u.username: raise ValueError('unregistered HTTPS host: '+str(u.hostname))
class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        check(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)
def fetch(name,url, *, accession='literature_metadata', unit='not biological observations', terms='source-specific metadata; no redistribution', terms_url=None, citation=None, max_bytes=256*1024**2, headers=None):
    check(url); target=ART/'payload'/name
    manifest=ART/'manifests'/(name+'.json')
    if manifest.exists(): return target
    target.parent.mkdir(parents=True,exist_ok=True)
    ledger=ART/'transfer-ledger.jsonl'
    opener=urllib.request.build_opener(Redirect)
    for attempt in range(3):
        count=0; start=time.monotonic(); event={'at_utc':now(),'url':url,'name':name,'attempt':attempt}
        try:
            total=sum(json.loads(x).get('bytes',0) for x in ledger.read_text().splitlines()) if ledger.exists() else 0
            if total+max_bytes>6*1024**3: raise RuntimeError('download budget exceeded')
            with opener.open(urllib.request.Request(url,headers=headers or {}),timeout=45) as response:
                check(response.url)
                if headers and 'Range' in headers and response.status!=206: raise RuntimeError('range not honored')
                length=response.headers.get('Content-Length')
                if length and int(length)>max_bytes: raise RuntimeError('file exceeds predeclared limit')
                h=hashlib.sha256()
                with target.with_suffix(target.suffix+'.part').open('wb') as out:
                    while chunk:=response.read(65536):
                        count+=len(chunk)
                        if count>max_bytes or time.monotonic()-start>600: raise RuntimeError('byte/time ceiling')
                        if dt.datetime.now(dt.timezone.utc)>dt.datetime.fromisoformat('2026-10-22T11:46:31.613021+00:00'): raise RuntimeError('campaign deadline')
                        out.write(chunk); h.update(chunk)
                target.with_suffix(target.suffix+'.part').replace(target)
                m={'schema_version':'openlabs.biomed_dataset.v1','dataset_id':name,'source_id':'perturbation_context_lane_local','release_or_accession':accession,'independent_unit':unit,'source_url':url,'final_url':urllib.parse.urlunsplit(urllib.parse.urlsplit(response.url)._replace(query='')),'retrieved_at_utc':now(),'terms_url':terms_url or url,'reuse_basis':terms,'citation':citation or accession,'upstream_study_ids':[accession],'artifact_uri':target.as_uri(),'staging_root':str(ART),'bytes':count,'sha256':h.hexdigest(),'access_scope':'public','raw_immutable':True,'response_headers':dict(response.headers)}
                atomic(manifest,m)
            event.update(bytes=count,status='success')
            with ledger.open('a') as f: f.write(json.dumps(event)+'\n')
            print(name,count,flush=True); return target
        except BaseException as e:
            event.update(bytes=count,status='failed',error=str(e))
            with ledger.open('a') as f: f.write(json.dumps(event)+'\n')
            print(name,repr(e),flush=True)
            if isinstance(e,(KeyboardInterrupt,SystemExit)): raise
            if '403' in str(e) or '404' in str(e) or attempt==2: return None
            time.sleep(2)
    return None

if __name__=='__main__':
    atomic(DATA/'source_registry.json',{'hosts':sorted(HOSTS),'scope':'this lane only','policy':'official author/documentation links; file-specific terms recorded individually'})
    dois=['10.1038/s41592-025-02772-6','10.1093/bioinformatics/btaf317','10.1016/j.cell.2026.08.002','10.64898/2026.02.04.703804','10.64898/2026.08.11.744177','10.64898/2026.09.30.755756','10.1038/s41587-026-03307-w']
    for i,doi in enumerate(dois): fetch(f'crossref_{i}.json','https://api.crossref.org/works/'+urllib.parse.quote(doi,safe=''),accession=doi,max_bytes=4*1024**2)
    fetch('pmc_ids.json','https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?ids='+','.join(dois)+'&format=json',max_bytes=1024**2)
    fetch('data_sharing_readme.md','https://raw.githubusercontent.com/emdann/GWT_perturbseq_analysis_2025/master/metadata/data_sharing_readme.md',accession='GSE314342',max_bytes=1024**2)
    fetch('s3_list.xml','https://genome-scale-tcell-perturb-seq.s3.amazonaws.com/?list-type=2&prefix=marson2025_data/&max-keys=100',accession='GSE314342',max_bytes=1024**2)
    fetch('author_repo.json','https://api.github.com/repos/emdann/GWT_perturbseq_analysis_2025',max_bytes=1024**2)
    fetch('geo.html','https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE314342',accession='GSE314342',max_bytes=2*1024**2)
