"""Bounded corrected spatial RDS intake, exact HTTP206 chunks and streamed validation."""
from intake import *
import concurrent.futures,threading,zlib
from spatial_probe import URL

SIZE=1014335925
CHUNK=4*1024**2
DIRECTORY=ART/'spatial_rds_chunks'
DEADLINE=datetime.fromisoformat('2026-10-22T11:46:31.613021+00:00')
LAST_MODIFIED='Thu, 20 Mar 2025 21:16:28 GMT'
LOCK=threading.Lock()

def log(name,obj):
    with LOCK:
        with (ART/name).open('a') as f:f.write(json.dumps(obj)+'\n');f.flush();os.fsync(f.fileno())

def get_chunk(bounds):
    lo,hi=bounds;path=DIRECTORY/f'{lo}-{hi}.bin'
    if path.exists():
        rec=json.loads(path.with_suffix('.json').read_text())
        assert path.stat().st_size==hi-lo+1 and hashlib.sha256(path.read_bytes()).hexdigest()==rec['sha256']
        return rec
    failures=0
    logfile=ART/'spatial_range_failures.jsonl'
    if logfile.exists():
        failures=sum(json.loads(line).get('start')==lo for line in logfile.read_text().splitlines())
    for attempt in range(failures,3):
        if datetime.now(timezone.utc)>=DEADLINE:raise RuntimeError('Original campaign deadline reached')
        part=path.with_suffix('.part')
        if part.exists():part.rename(path.with_suffix('.interrupted-'+str(time.time_ns())))
        count=0;sha=hashlib.sha256();started=time.monotonic()
        try:
            req=urllib.request.Request(URL,headers={'Range':f'bytes={lo}-{hi}','If-Unmodified-Since':LAST_MODIFIED})
            with urllib.request.urlopen(req,timeout=45) as r,part.open('wb') as f:
                assert r.status==206 and r.headers.get('Content-Range')==f'bytes {lo}-{hi}/{SIZE}'
                assert r.headers.get('Last-Modified')==LAST_MODIFIED
                while True:
                    if time.monotonic()-started>900 or datetime.now(timezone.utc)>=DEADLINE:raise TimeoutError('Chunk/campaign deadline reached')
                    data=r.read1(min(65536,hi-lo+2-count))
                    if not data:break
                    count+=len(data)
                    with (ART/'transfer.lock').open('a') as lock:
                        fcntl.flock(lock,fcntl.LOCK_EX)
                        p=ART/'transfer_bytes.json';used=json.loads(p.read_text())['bytes']+len(data);atomic(p,dict(bytes=used))
                        if used>6*1024**3:raise RuntimeError('Total download budget exhausted')
                    if count>hi-lo+1:raise RuntimeError('Oversized Range body')
                    sha.update(data);f.write(data)
                f.flush();os.fsync(f.fileno())
            assert count==hi-lo+1
            part.replace(path)
            rec=dict(at=now(),source=URL,start=lo,end=hi,bytes=count,sha256=sha.hexdigest(),path=str(path),attempt=attempt,seconds=time.monotonic()-started,last_modified=LAST_MODIFIED)
            atomic(path.with_suffix('.json'),rec);log('spatial_range_manifest.jsonl',rec)
            return rec
        except Exception as e:
            log('spatial_range_failures.jsonl',dict(at=now(),start=lo,end=hi,attempt=attempt,bytes=count,error=repr(e)))
            if isinstance(e,RuntimeError) or '403' in repr(e) or '412' in repr(e) or attempt==2:raise
            time.sleep(2)
    raise RuntimeError('Per-range retry budget previously exhausted')

def assemble(bounds):
    out=ART/'payload/GSE250346_corrected2025.rds'
    assert not out.exists(),'Refuse overwrite complete spatial payload'
    tmp=out.with_suffix('.tmp');sha=hashlib.sha256();uncompressed_sha=hashlib.sha256();decoder=zlib.decompressobj(31);total=0;written=0
    with tmp.open('wb') as f:
        for lo,hi in bounds:
            with (DIRECTORY/f'{lo}-{hi}.bin').open('rb') as inp:
                while b:=inp.read(65536):
                    f.write(b);sha.update(b);written+=len(b);pending=b
                    while pending:
                        d=decoder.decompress(pending,4*1024**2);pending=decoder.unconsumed_tail
                        total+=len(d);uncompressed_sha.update(d)
                        if total>8*1024**3:raise RuntimeError('Uncompressed stream exceeds inspection cap; no full R object load')
        f.flush();os.fsync(f.fileno())
    assert written==SIZE and decoder.eof and not decoder.unused_data
    tmp.replace(out)
    record=dict(at=now(),provider='NCBI GEO',accession='GSE250346',release='corrected file published2025-03-20; original filename ends082024',source=URL,path=str(out),bytes=written,sha256=sha.hexdigest(),gzip_crc_verified=True,uncompressed_bytes=total,uncompressed_sha256=uncompressed_sha.hexdigest(),uncompressed_file_materialized=False,terms_url='https://creativecommons.org/licenses/by/4.0/',reuse_basis='Vannan2025 article/supplement CC BY4.0 and corrected GEO README; attributed internal research',upstream_study_ids=['GSE250346','10.1038/s41588-025-02080-x'],independent_unit='donor after source-overlap exclusions; NOT cells',r_load_admissible_size=total<=3.5*1024**3,r_child_rss_cap_bytes=int(3.6*1024**3),paper_candidate=False)
    atomic(ART/'spatial_corrected_intake.json',record);print(json.dumps(record),flush=True)

def main():
    assert (DATA/'spatial_large_intake_plan.json').exists()
    DIRECTORY.mkdir(exist_ok=True)
    bounds=[(lo,min(lo+CHUNK,SIZE)-1) for lo in range(0,SIZE,CHUNK)]
    remaining=list(bounds);done=0
    while remaining:
        # Main analysis releases its network slot only after both scRNA intakes.
        workers=2 if (DATA/'singlecell_downloads_completed.json').exists() else 1
        batch=remaining[:workers];remaining=remaining[workers:]
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            recs=list(pool.map(get_chunk,batch))
        done+=len(recs)
        progress=dict(at=now(),chunks_complete=done,chunks_total=len(bounds),complete_bytes=sum(hi-lo+1 for lo,hi in bounds[:done]),total_bytes=SIZE,http_workers=workers,stage='corrected_spatial_payload_download',paper_candidate=False)
        atomic(ART/'spatial_download_progress.json',progress)
        if done%8==0 or done==1:print(json.dumps(progress),flush=True)
    assemble(bounds)

if __name__=='__main__':main()
