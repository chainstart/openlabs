from common import *
import urllib.request, urllib.error, time
from urllib.parse import urlsplit
import contextlib,fcntl
ALLOWED={'api.crossref.org','api.biorxiv.org','www.ebi.ac.uk','www.ncbi.nlm.nih.gov','ftp.ncbi.nlm.nih.gov','api.github.com','raw.githubusercontent.com','www.nature.com','static-content.springer-cdn.com','media.springernature.com','pmc.ncbi.nlm.nih.gov','www.biorxiv.org'}
@contextlib.contextmanager
def bounded_open(request,timeout=35):
    """Aggregate lane HTTP cap across separate intake processes and threads."""
    folder=ART/'http-slots';folder.mkdir(parents=True,exist_ok=True);held=None
    while held is None:
        guard_check()
        for i in range(2):
            f=(folder/str(i)).open('a+')
            try:
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB);held=f;break
            except BlockingIOError:f.close()
        if held is None:time.sleep(.1)
    try:
        with urllib.request.urlopen(request,timeout=timeout) as r:yield r
    finally:
        fcntl.flock(held.fileno(),fcntl.LOCK_UN);held.close()
def fetch(name,url,limit=16*1024**2,kind='literature_metadata',terms=None,study=None):
    guard_check(); p=ART/'payload'/name; m=ART/'manifests'/(name+'.json')
    assert urlsplit(url).scheme=='https' and urlsplit(url).hostname in ALLOWED
    used=sum(json.loads(x.read_text()).get('actual_bytes',json.loads(x.read_text()).get('bytes',0)) for x in (ART/'manifests').glob('*.json'))
    assert used+3*limit<6*1024**3
    if p.exists():
        z=json.loads(m.read_text()); assert sha(p)==z['sha256']; assert z['source_url']==url, 'cache filename/source URL collision'; return p
    p.parent.mkdir(parents=True,exist_ok=True)
    attempts=[]
    for attempt in range(3):
        part=p.with_suffix(p.suffix+'.part'); n=0; start=time.monotonic()
        try:
            with bounded_open(urllib.request.Request(url,headers={'User-Agent':'OpenLabs-research/1.0'}),timeout=35) as r, open(part,'wb') as f:
                queue_seconds=time.monotonic()-start;start=time.monotonic()
                code=r.status
                assert urlsplit(r.url).hostname in ALLOWED, 'unreviewed redirect host'
                assert int(r.headers.get('Content-Length',0))<=limit
                final_url=r.url;headers=dict(r.headers)
                while True:
                    b=r.read(128*1024)
                    if not b: break
                    n+=len(b)
                    if n>limit or time.monotonic()-start>180: raise RuntimeError('byte/time cap')
                    f.write(b)
            part.replace(p)
            z=dict(time=now(),source_url=url,final_url=final_url,headers=headers,status=code,bytes=n,actual_bytes=n+sum(x['bytes'] for x in attempts),sha256=sha(p),kind=kind,terms=terms,upstream_study=study,queue_seconds=queue_seconds,attempts=attempts)
            write(m,z); return p
        except Exception as e:
            attempts.append(dict(attempt=attempt,bytes=n,error=str(e),time=now()))
            write(m,dict(source_url=url,status='failed',actual_bytes=sum(x['bytes'] for x in attempts),attempts=attempts))
            if isinstance(e,urllib.error.HTTPError) and e.code in (400,401,403,404): break
            time.sleep(2)
    return None
