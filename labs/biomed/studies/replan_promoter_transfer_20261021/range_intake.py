"""Lane-only bounded, audited two-connection range intake. No bypass of HTTP errors."""
from intake import *
import concurrent.futures, re
def ranged(name,url,limit=64*1024**2):
    guard_check(); target=ART/'payload'/name; manifest=ART/'manifests'/(name+'.ranges.json')
    if target.exists():
        print('already complete',name); return target
    req=urllib.request.Request(url,method='HEAD')
    with bounded_open(req,timeout=35) as r:
        length=int(r.headers['Content-Length']); headers=dict(r.headers)
    assert 0<length<=limit and headers.get('Accept-Ranges')=='bytes'
    validator=headers.get('ETag') or headers.get('Last-Modified'); assert validator
    chunk=256*1024; folder=ART/'ranges'/name;folder.mkdir(parents=True,exist_ok=True)
    plan=dict(time=now(),source_url=url,accession='GSE279057',upstream_study='Bose2025',independent_unit='TSS/locus, not barcode; pending metadata audit',terms_url='https://www.ncbi.nlm.nih.gov/home/about/policies/',reuse_basis='Official public data; source preprint CC BY. Private attributed research, no redistribution.',length=length,headers=headers,validator=validator,chunk_bytes=chunk,http_concurrency=2,max_retries_per_chunk=2,stream_memory_bytes=2*128*1024,status='downloading')
    write(manifest,plan)
    def part(i):
        start=i*chunk;end=min(length-1,start+chunk-1); p=folder/(str(i)+'.bin');m=folder/(str(i)+'.json')
        if p.exists() and m.exists():
            rec=json.loads(m.read_text());assert rec['validator']==validator and rec['sha256']==sha(p);return rec
        attempts=[]
        for trial in range(3):
            guard_check(); count=0;t0=time.monotonic();tmp=p.with_suffix('.part')
            try:
                req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}','If-Range':validator,'User-Agent':'OpenLabs-research/1.0'})
                with bounded_open(req,timeout=35) as r,tmp.open('wb') as f:
                    t0=time.monotonic()
                    assert r.status==206,(r.status,'Range not respected')
                    assert r.headers.get('Content-Range')==f'bytes {start}-{end}/{length}'
                    while True:
                        b=r.read(65536)
                        if not b:break
                        count+=len(b)
                        assert count<=end-start+1 and time.monotonic()-t0<100
                        f.write(b)
                assert count==end-start+1
                tmp.replace(p)
                rec=dict(range=[start,end],bytes=count,actual_bytes=count+sum(a['bytes'] for a in attempts),sha256=sha(p),validator=validator,attempts=attempts,seconds=time.monotonic()-t0)
                write(m,rec);return rec
            except Exception as e:
                attempts.append(dict(time=now(),attempt=trial,bytes=count,error=str(e)))
                write(m,dict(status='failed',validator=validator,attempts=attempts,actual_bytes=sum(a['bytes'] for a in attempts)))
                if isinstance(e,urllib.error.HTTPError) and e.code in (401,403,404):break
                time.sleep(2)
        raise RuntimeError('range failed '+str(i))
    n=(length+chunk-1)//chunk; records=[];last=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for rec in pool.map(part,range(n)):
            records.append(rec)
            if time.monotonic()-last>45:
                plan.update(chunks_complete=len(records),bytes_complete=sum(x['bytes'] for x in records),updated_at_utc=now());write(manifest,plan)
                print(name,len(records),'/',n,flush=True);last=time.monotonic()
    with target.with_suffix(target.suffix+'.assembling').open('wb') as out:
        for i in range(n):
            with (folder/(str(i)+'.bin')).open('rb') as f:
                for b in iter(lambda:f.read(65536),b''):out.write(b)
    target.with_suffix(target.suffix+'.assembling').replace(target)
    plan.update(status='downloaded',bytes=target.stat().st_size,actual_bytes=sum(x['actual_bytes'] for x in records),sha256=sha(target),completed_at_utc=now(),chunks=records)
    write(manifest,plan);print(name,'complete',length,flush=True);return target
if __name__=='__main__':
    for tail in ['annotations','barcode_pairing','counts']:
        name='GSE279057_kyono_library_'+tail+'.txt.gz'
        ranged(name,'https://ftp.ncbi.nlm.nih.gov/geo/series/GSE279nnn/GSE279057/suppl/'+name)
