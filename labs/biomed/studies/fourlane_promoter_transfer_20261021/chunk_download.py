from common import *
def download():
    prefix=json.loads((ART/'manifests/GSE301246_PARM_Training_Library_v2_MH4_raw_counts.txt.gz.prefix.json').read_text())
    url=prefix['source_url'];total=198979633;chunk=1024*1024
    target=ART/'payload/parm-v2-range-counts.txt.gz';part=target.with_suffix('.gz.part');mp=ART/'manifests/parm-v2-range-counts.json'
    if target.exists():return
    record=dict(source_url=url,accession='GSE301246',upstream_study='10.1038/s41586-025-10093-z',terms_url='https://www.ncbi.nlm.nih.gov/geo/info/disclaimer.html',reuse_basis='Internal attributed analysis of official processed data',time=now(),expected_bytes=total,chunks=[],status='downloading',actual_bytes=0)
    write(DATA/'chunk-download-plan.json',dict(time=now(),reason='Official Range API explicitly supported; use sequential 1MiB chunks with exact 206 validation and stable Last-Modified',max_bytes=256*1024**2,expected_bytes=total,memory_max_mib=16,attempts_per_chunk=2,total_timeout_seconds=7200,concurrency=1))
    starttime=time.monotonic();last_status=starttime
    with part.open('wb') as out:
        for start in range(0,total,chunk):
            end=min(total,start+chunk)-1
            if time.monotonic()-starttime>7200:raise TimeoutError('total download time budget')
            for attempt in range(2):
                data=b''
                try:
                    request=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}','If-Range':prefix['headers']['Last-Modified'],'User-Agent':'OpenLabs-promoter-research/1.0'})
                    with urllib.request.urlopen(request,timeout=40) as r:
                        assert r.status==206 and r.headers.get('Content-Range')==f'bytes {start}-{end}/{total}'
                        assert r.headers.get('Last-Modified')==prefix['headers']['Last-Modified']
                        data=r.read(end-start+2);assert len(data)==end-start+1
                    out.write(data);record['actual_bytes']+=len(data)
                    record['chunks'].append(dict(start=start,end=end,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),http_status=206));write(mp,record)
                    break
                except Exception as e:
                    record.setdefault('failures',[]).append(dict(start=start,attempt=attempt+1,error=str(e),bytes=len(data)));record['actual_bytes']+=len(data);write(mp,record)
                    if attempt==1:raise
                    time.sleep(2)
            if time.monotonic()-last_status>60:
                print(end+1,total,'elapsed',time.monotonic()-starttime,flush=True)
                status('fragment_metadata_download',[f'validated 206 byte ranges through {end+1}/{total}'],['complete coordinate-pair audit'],download_bytes=end+1)
                last_status=time.monotonic()
    part.replace(target);record.update(status='downloaded',payload=str(target),payload_bytes=target.stat().st_size,sha256=sha(target),completed_at=now());write(mp,record)
    print('complete',record['payload_bytes'],record['sha256'],flush=True)
if __name__=='__main__':
    p=ART/'payload/GSE301246_PARM_Training_Library_v2_MH4_raw_counts.txt.gz.part'
    if p.exists():write(ART/'manifests/parm-v2-alternate-aborted.json',dict(status='incomplete',actual_bytes=p.stat().st_size,sha256=sha(p),payload=str(p),reason='Slow official alternate full stream; replaced with supported range requests'))
    download()
