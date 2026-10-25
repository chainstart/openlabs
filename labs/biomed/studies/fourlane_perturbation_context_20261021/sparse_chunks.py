"""Bounded CSR chunk extraction with two persistent HTTPS connections, no full atlas.

Supports this explicitly audited uncompressed, unfiltered 1-D HDF5 layout only.
Chunk byte offsets are obtained from h5py, never guessed from row ordering.
"""
from pathlib import Path
import concurrent.futures
import datetime as dt
import hashlib
import http.client
import json
import os
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import h5py
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, save_npz
from intake import ART, DATA, atomic, now, status, Redirect
from range_h5 import RangeFile

LOCK=threading.Lock()
LOCAL=threading.local()
OBJ='GWCD4i.pseudobulk_merged.h5ad'
SIZE=44566657140
HOST='genome-scale-tcell-perturb-seq.s3.amazonaws.com'
URL='https://'+HOST+'/marson2025_data/'+OBJ
CHUNKDIR=ART/os.environ.get('OPENLABS_RANGE_CACHE','h5chunks')
assert CHUNKDIR.parent==ART and CHUNKDIR.name.startswith('h5chunks')

def cache_chunk(item):
    start,size=item['offset'],item['bytes'];dest=CHUNKDIR/f'{start}_{size}.bin'
    if dest.exists():
        if dest.stat().st_size!=size:raise ValueError('chunk cache wrong size')
        return dest
    original=ART/'h5chunks'/dest.name
    if original!=dest and original.exists() and original.with_suffix('.json').exists():
        m=json.loads(original.with_suffix('.json').read_text())
        if original.stat().st_size==size and hashlib.sha256(original.read_bytes()).hexdigest()==m['sha256']:
            return original
    # Reuse already audited exact 1-MiB HTTP ranges where all needed blocks exist.
    lo=start//1048576*1048576;end=start+size;parts=[]
    for b in range(lo,end,1048576):
        last=min(b+1048576,SIZE)-1
        p=ART/'payload'/f'{OBJ}.range_{b}_{last}.bin'
        if not p.exists() or not (ART/'manifests'/(p.name+'.json')).exists():return None
        parts.append(p.read_bytes())
    data=b''.join(parts)[start-lo:start-lo+size]
    assert len(data)==size
    dest.write_bytes(data)
    atomic(dest.with_suffix('.json'),{'origin':'existing audited range cache','offset':start,'bytes':size,'sha256':hashlib.sha256(data).hexdigest(),'source_url':URL,'created_at_utc':now()})
    return dest

def transfer(item):
    if p:=cache_chunk(item):return p
    start,size=item['offset'],item['bytes'];stop=start+size-1
    dest=CHUNKDIR/f'{start}_{size}.bin';ledger=ART/'transfer-ledger.jsonl'
    for attempt in range(3):
        response=None;transport=os.environ.get('OPENLABS_HTTP_TRANSPORT','urllib')
        count=0;event={'at_utc':now(),'url':URL,'offset':start,'requested_bytes':size,'name':dest.name,'attempt':attempt,'method':'stdlib_urllib_range' if transport=='urllib' else 'persistent_https_range'}
        try:
            if dt.datetime.now(dt.timezone.utc)>dt.datetime.fromisoformat('2026-10-22T11:46:31.613021+00:00'):raise RuntimeError('campaign deadline')
            with LOCK:
                used=sum(json.loads(x).get('bytes',0) for x in ledger.read_text().splitlines())
                if used+2*size>6*1024**3:raise RuntimeError('6GiB lane ceiling')
            request_headers={'Range':f'bytes={start}-{stop}','If-Match':'"010c14e0af0dccbc2524529d28ca517e-5313"'}
            if transport=='urllib':
                opener=getattr(LOCAL,'opener',None)
                if opener is None:opener=urllib.request.build_opener(Redirect);LOCAL.opener=opener
                response=opener.open(urllib.request.Request(URL,headers=request_headers),timeout=45)
            else:
                conn=getattr(LOCAL,'conn',None)
                if conn is None:
                    conn=http.client.HTTPSConnection(HOST,timeout=45,context=ssl.create_default_context());LOCAL.conn=conn
                conn.request('GET','/marson2025_data/'+OBJ,headers=request_headers)
                response=conn.getresponse()
            hdr=dict(response.getheaders())
            if response.status!=206 or response.getheader('Content-Range')!=f'bytes {start}-{stop}/{SIZE}':raise RuntimeError('server did not honor exact Range')
            if int(response.getheader('Content-Length','-1'))!=size:raise RuntimeError('Content-Length mismatch')
            if response.getheader('ETag')!='"010c14e0af0dccbc2524529d28ca517e-5313"':raise RuntimeError('source object validator changed')
            h=hashlib.sha256();began=time.monotonic()
            with dest.with_suffix('.part').open('wb') as f:
                while block:=response.read(min(65536,size-count+1)):
                    count+=len(block)
                    if count>size or time.monotonic()-began>120:raise RuntimeError('range byte/time ceiling')
                    f.write(block);h.update(block)
            if count!=size:raise RuntimeError('short range')
            dest.with_suffix('.part').replace(dest)
            atomic(dest.with_suffix('.json'),{'schema_version':'openlabs.biomed_range_fragment.v1','source_url':URL,'offset':start,'bytes':size,'sha256':h.hexdigest(),'release_or_accession':'GSE314342','upstream_study_ids':['GSE314342'],'independent_unit':'guide x donor x stimulation pseudobulk','terms_url':'https://github.com/emdann/GWT_perturbseq_analysis_2025','reuse_basis':'Author-linked public research data, internal attributed analysis only; no raw redistribution; see lane source/terms audit','citation':'Zhu et al Cell 2026 DOI10.1016/j.cell.2026.08.002','response_headers':hdr,'retrieved_at_utc':now()})
            event.update(bytes=count,status='success')
            with LOCK:
                with ledger.open('a') as f:f.write(json.dumps(event)+'\n')
            return dest
        except BaseException as e:
            if getattr(LOCAL,'conn',None):LOCAL.conn.close();LOCAL.conn=None
            event.update(bytes=count,status='failed',error=repr(e))
            with LOCK:
                with ledger.open('a') as f:f.write(json.dumps(event)+'\n')
            if isinstance(e,(KeyboardInterrupt,SystemExit)):raise
            if isinstance(e,urllib.error.HTTPError) and e.code in (403,404,412):raise
            if attempt==2:raise
            time.sleep(2)
        finally:
            if transport=='urllib' and response is not None:response.close()

def plan(table,label):
    selected=pd.read_csv(table,index_col=0);obs=pd.read_csv(ART/'pseudobulk_obs.csv',index_col=0)
    positions=obs.index.get_indexer(selected.index);assert (positions>=0).all()
    chunks={};rows=[]
    with RangeFile(budget=128*1024**2) as r:
        with h5py.File(r,'r',rdcc_nbytes=8*1024**2) as f:
            ptr=f['X/indptr'][:];nvar=int(f['X'].attrs['shape'][1])
            for name,pos in sorted(zip(selected.index,positions),key=lambda x:x[1]):
                lo,hi=int(ptr[pos]),int(ptr[pos+1]);rr={'sample_id':str(name),'position':int(pos),'lo':lo,'hi':hi,'chunks':{}}
                for key in ['data','indices']:
                    d=f['X/'+key];assert d.compression is None and d.ndim==1
                    assert d.id.get_create_plist().get_nfilters()==0
                    step=d.chunks[0];ids=[]
                    for coord in range(lo//step*step,hi,step):
                        chunk_id=f'{key}_{coord}'
                        if chunk_id not in chunks:
                            ci=d.id.get_chunk_info_by_coord((coord,));assert ci.filter_mask==0
                            chunks[chunk_id]={'offset':int(ci.byte_offset),'bytes':int(ci.size),'coord':coord,'dtype':d.dtype.str,'elements':step}
                        ids.append(chunk_id)
                    rr['chunks'][key]=ids
                rows.append(rr)
    p={'created_at_utc':now(),'selection':str(table),'selection_sha256':hashlib.sha256(Path(table).read_bytes()).hexdigest(),'label':label,'nvar':nvar,'source':URL,'rows':rows,'chunks':chunks,'projected_raw_chunk_bytes':sum(x['bytes'] for x in chunks.values()),'phase_ceiling_bytes':2500*1024**2,'memory_plan':'one row ~290KiB; 2 HTTPS streams of64KiB; HDF metadata8MiB; never dense full atlas','independent_units':'four donors, guide IDs retained; metadata only in planning'}
    if p['projected_raw_chunk_bytes']>p['phase_ceiling_bytes']:raise RuntimeError('selection too large: revise design BEFORE outcome access')
    atomic(DATA/(label+'_chunk_plan.json'),p);print('PLANNED',label,len(rows),'rows',len(chunks),'chunks',p['projected_raw_chunk_bytes'],'bytes',flush=True)
    return p

def run(table,label):
    CHUNKDIR.mkdir(exist_ok=True)
    pfile=DATA/(label+'_chunk_plan.json')
    p=json.loads(pfile.read_text()) if pfile.exists() else plan(table,label)
    assert p['selection_sha256']==hashlib.sha256(Path(table).read_bytes()).hexdigest()
    chunks=p['chunks'];last=time.monotonic();done=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending={pool.submit(transfer,x):k for k,x in chunks.items()}
        for future in concurrent.futures.as_completed(pending):
            future.result();done+=1
            if done%50==0:print('CHUNKS',done,'/',len(chunks),flush=True)
            if time.monotonic()-last>300:
                status('extracting_'+label,[f'{done}/{len(chunks)} selected sparse chunks staged','2 persistent HTTPS streams, exact206 byte validation'],['finish extraction','prospective analysis','scientific review'],[str(pfile)])
                last=time.monotonic()
    out=ART/'extracted'/label;out.mkdir(parents=True,exist_ok=True)
    obs=pd.read_csv(ART/'pseudobulk_obs.csv',index_col=0)
    for rr in p['rows']:
        arrays={}
        for key,ids in rr['chunks'].items():
            pieces=[]
            for cid in ids:
                x=chunks[cid];buf=np.fromfile(CHUNKDIR/f'{x["offset"]}_{x["bytes"]}.bin',dtype=x['dtype'])
                a=max(rr['lo']-x['coord'],0);b=min(rr['hi']-x['coord'],x['elements']);pieces.append(buf[a:b])
            arrays[key]=np.concatenate(pieces) if pieces else np.array([],dtype=float if key=='data' else int)
        vals=arrays['data'];idx=arrays['indices'];assert np.isfinite(vals).all() and (vals>=0).all() and (idx>=0).all() and (idx<p['nvar']).all()
        row=csr_matrix((vals,idx,np.array([0,len(vals)])),shape=(1,p['nvar']))
        dest=out/f'{rr["position"]}.npz';save_npz(dest,row)
        atomic(dest.with_suffix('.json'),{'row_index':rr['position'],'sample_id':rr['sample_id'],'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'source_object':OBJ,'nnz':len(vals),'sum':float(vals.sum()),'sum_matches_metadata':bool(np.isclose(vals.sum(),obs.iloc[rr['position']].total_counts)),'chunks':rr['chunks'],'retrieved_at_utc':now()})
    atomic(out/'extraction_summary.json',{'rows':len(p['rows']),'chunk_plan_sha256':hashlib.sha256(pfile.read_bytes()).hexdigest(),'selection_sha256':p['selection_sha256']})
    print('EXTRACTION_COMPLETE',label,len(p['rows']),flush=True)

if __name__=='__main__':run(sys.argv[1],sys.argv[2])
