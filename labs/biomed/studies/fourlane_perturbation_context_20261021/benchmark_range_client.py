"""Serial same-host Range equivalence check; standard TLS and no access bypass."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
from intake import ART, DATA, atomic, now, fetch

group=Path('/proc/self/cgroup').read_text().strip().split('::')[1]
for pid in (Path('/sys/fs/cgroup')/group.lstrip('/')/'cgroup.procs').read_text().splitlines():
    try:args=(Path('/proc')/pid/'cmdline').read_bytes().split(b'\0')
    except FileNotFoundError:continue
    if any(x.endswith(b'/parallel_extract.py') for x in args):raise RuntimeError('extraction still active; do not exceed HTTP concurrency')
events=[json.loads(x) for x in (ART/'transfer-ledger.jsonl').read_text().splitlines()]
sources=[]
for folder in ART.glob('h5chunks_worker*'):
    for p in folder.glob('*.json'):
        m=json.loads(p.read_text())
        if m.get('retrieved_at_utc','')>'2026-10-21T13:06' and 65536<=m['bytes']<=131072:
            sources.append((m['retrieved_at_utc'],p,m))
checks=[]
for _,p,m in sorted(sources)[-3:]:
    offset=m['offset'];size=m['bytes'];start=time.monotonic()
    dest=fetch(f'urllib_transport_probe_{offset}_{size}.bin',m['source_url'],accession='GSE314342 transport equivalence only',unit='same previously staged raw byte range',terms='same original source terms; internal analysis only',terms_url='https://github.com/emdann/GWT_perturbseq_analysis_2025',max_bytes=size,headers={'Range':f'bytes={offset}-{offset+size-1}','If-Match':'"010c14e0af0dccbc2524529d28ca517e-5313"'})
    elapsed=time.monotonic()-start
    if dest is None:raise RuntimeError('standard HTTPS probe failed; do not bypass server restrictions')
    mm=json.loads((ART/'manifests'/(dest.name+'.json')).read_text());headers={k.lower():v for k,v in mm['response_headers'].items()}
    correct=headers['content-range']==f'bytes {offset}-{offset+size-1}/44566657140' and hashlib.sha256(dest.read_bytes()).hexdigest()==m['sha256']
    assert correct
    past=[e for e in events if e.get('name')==p.with_suffix('.bin').name and e.get('status')=='success']
    original_elapsed=(dt.datetime.fromisoformat(m['retrieved_at_utc'])-dt.datetime.fromisoformat(past[-1]['at_utc'])).total_seconds() if past else None
    checks.append({'offset':offset,'bytes':size,'exact_hash_match':correct,'standard_urllib_seconds':elapsed,'prior_direct_client_seconds':original_elapsed,'prior_manifest':str(p),'new_manifest':str(ART/'manifests'/(dest.name+'.json'))})
result={'at_utc':now(),'valid':len(checks)==3 and all(x['exact_hash_match'] for x in checks),'source_url_unchanged':True,'TLS_verification_disabled':False,'HTTP_concurrency':1,'observations':'transport timing, not biological experiment or model configuration','checks':checks}
atomic(DATA/'urllib_range_transport_validation.json',result)
print(json.dumps(result,indent=2))
