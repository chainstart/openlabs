"""Scoped, bounded research intake; no shared writes."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.parse
import requests
import fcntl

ROOT = Path('/home/biostar/work/projects/openlabs')
ART = ROOT/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/drug_support'
DATA = ROOT/'openlabs-data/workspaces/biology/projects/biomed-fourlane-drug-support-20261021'
CODE = ROOT/'openlabs/labs/biomed/studies/fourlane_drug_support_20261021'
ALLOWED = {'api.crossref.org','pmc.ncbi.nlm.nih.gov','www.ncbi.nlm.nih.gov','eutils.ncbi.nlm.nih.gov','www.ebi.ac.uk','api.github.com','raw.githubusercontent.com','github.com','zenodo.org','api.figshare.com','ndownloader.figshare.com','depmap.org','portals.broadinstitute.org','ctd2-data.nci.nih.gov','www.nature.com','academic.oup.com','journals.plos.org','link.springer.com'}
# Official Figshare redirects verified in Broad 9393293 v4 metadata intake.
ALLOWED.add('s3-eu-west-1.amazonaws.com')

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def write(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n');tmp.replace(path)

def status(stage, completed, remaining, evidence=(), failures=()):
    old=json.loads((ART/'research_status.json').read_text())
    old.update(updated_at_utc=now(),stage=stage,completed=completed,remaining=remaining,evidence_paths=list(evidence),failures=list(failures))
    for base in (ART,DATA):write(base/'research_status.json',old)

def fetch(name,url,limit=16*1024**2, provenance=None):
    with (ART/'intake.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _fetch(name,url,limit,provenance)

def _fetch(name,url,limit=16*1024**2, provenance=None):
    """Serial HTTPS, explicit allowlist, max two retries, byte/deadline accounting."""
    dest=ART/'intake'/name
    manifest=dest.with_name(dest.name+'.manifest.json')
    if manifest.exists():
        m=json.loads(manifest.read_text())
        if m.get('success'):
            assert hashlib.sha256(dest.read_bytes()).hexdigest()==m['sha256']
            return dest
        return None
    dest.parent.mkdir(parents=True,exist_ok=True)
    ledger=ART/'download-ledger.json'
    accounting=json.loads(ledger.read_text()) if ledger.exists() else {'actual_bytes':0,'requests':[]}
    record={'source_url':url,'retrieved_at_utc':now(),'provenance':provenance,'attempts':[],'success':False}
    for attempt in range(3):
        received=0;start=time.monotonic();sha=hashlib.sha256()
        try:
            current=url
            for redirect in range(6):
                parsed=urllib.parse.urlparse(current)
                if parsed.scheme!='https' or parsed.hostname not in ALLOWED:raise ValueError('unregistered host: '+str(parsed.hostname))
                r=requests.get(current,timeout=(15,45),stream=True,allow_redirects=False)
                if r.is_redirect:
                    current=urllib.parse.urljoin(current,r.headers['location']);r.close();continue
                break
            r.raise_for_status()
            if int(r.headers.get('content-length',0))>limit:raise ValueError('content-length exceeds file budget')
            with dest.with_suffix(dest.suffix+'.part').open('wb') as f:
                for chunk in r.iter_content(65536):
                    received+=len(chunk);accounting['actual_bytes']+=len(chunk)
                    if received>limit or accounting['actual_bytes']>6*1024**3:raise ValueError('download budget exceeded')
                    if time.monotonic()-start>600:raise TimeoutError('total download deadline')
                    f.write(chunk);sha.update(chunk)
            dest.with_suffix(dest.suffix+'.part').replace(dest)
            record.update(success=True,bytes=received,sha256=sha.hexdigest(),final_url=current.split('?')[0],status_code=r.status_code)
            record['attempts'].append({'attempt':attempt,'bytes':received,'status':r.status_code})
            break
        except Exception as e:
            record['attempts'].append({'attempt':attempt,'bytes':received,'error':str(e)})
            if '403' in str(e) or '404' in str(e) or 'unregistered' in str(e) or 'budget' in str(e):break
            time.sleep(2)
        finally:
            accounting['requests'].append({'name':name,'attempt':attempt,'bytes':received,'at':now()});write(ledger,accounting)
    write(manifest,record)
    print(name, 'OK '+str(record.get('bytes')) if record['success'] else record['attempts'][-1],flush=True)
    return dest if record['success'] else None
