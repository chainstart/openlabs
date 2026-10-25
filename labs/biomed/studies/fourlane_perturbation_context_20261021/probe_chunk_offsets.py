"""Offline engineering validation: discover HDF raw chunk offsets without downloading them.

Normal HDF hyperslab reads request a known unfiltered raw chunk. A Python
exception stops the read before returning ANY invented bytes. The observed
physical request can then address the exact row slice in that chunk. This file
does not access the network and tests only already verified control samples.
"""
import bisect
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import h5py
import numpy as np
import pandas as pd
from scipy.sparse import load_npz
from intake import ART, DATA, atomic, now

SIZE=44566657140

class ChunkAddressFound(Exception):pass

class OfflineRanges(io.RawIOBase):
    def __init__(self):
        self.pos=0;self.capture_size=None;self.last_offset=None;self.verified=set();ranges=[]
        for folder in ART.glob('h5chunks*'):
            for p in folder.glob('*.bin'):
                parts=p.stem.split('_')
                if len(parts)!=2 or not p.with_suffix('.json').exists():continue
                start,size=map(int,parts);ranges.append((start,start+size,p,p.with_suffix('.json')))
        for p in (ART/'payload').glob('GWCD4i.pseudobulk_merged.h5ad.range_*.bin'):
            a,b=map(int,re.search(r'range_(\d+)_(\d+)\.bin$',p.name).groups())
            m=ART/'manifests'/(p.name+'.json')
            if m.exists():ranges.append((a,b+1,p,m))
        self.ranges=sorted(ranges);self.starts=[x[0] for x in self.ranges]
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.pos
    def seek(self,n,whence=0):
        self.pos=n if whence==0 else self.pos+n if whence==1 else SIZE+n
        return self.pos
    def cached(self,start,n):
        end=start+n;parts=[]
        while start<end:
            ix=bisect.bisect_right(self.starts,start);candidates=[]
            for k in range(ix-1,-1,-1):
                a,b,p,m=self.ranges[k]
                if start-a>2*1024**2:break
                if a<=start<b:candidates.append((b,a,p,m))
            if not candidates:raise RuntimeError(f'offline metadata/cache miss at {start}, n={n}')
            b,a,p,m=max(candidates)
            if p not in self.verified:
                manifest=json.loads(m.read_text())
                if hashlib.sha256(p.read_bytes()).hexdigest()!=manifest['sha256']:raise ValueError('cache hash mismatch')
                self.verified.add(p)
            size=min(end,b)-start
            with p.open('rb') as f:f.seek(start-a);piece=f.read(size)
            if len(piece)!=size:raise ValueError('short cache')
            parts.append(piece);start+=size
        return b''.join(parts)
    def read(self,n=-1):
        if n<0:raise ValueError('unbounded read')
        if self.capture_size==n:
            self.last_offset=self.pos
            raise ChunkAddressFound(str(self.pos))
        result=self.cached(self.pos,n);self.pos+=n;return result
    def readinto(self,b):
        data=self.read(len(b));b[:len(data)]=data;return len(data)

def locate(reader,dataset,coord):
    assert dataset.ndim==1 and dataset.compression is None
    assert dataset.id.get_create_plist().get_nfilters()==0
    size=dataset.chunks[0]*dataset.dtype.itemsize
    reader.capture_size=size;reader.last_offset=None
    try:
        dataset[coord:coord+1]
    except ChunkAddressFound:
        if reader.last_offset is None:raise RuntimeError('no physical offset')
        return reader.last_offset,size
    finally:reader.capture_size=None
    raise RuntimeError('unexpected cached HDF raw data; no offset guessed')

def validate():
    obs=pd.read_csv(ART/'pseudobulk_obs.csv',index_col=0)
    selected=pd.read_csv(DATA/'development_controls.csv',index_col=0)
    ids=np.unique(np.linspace(0,len(selected)-1,8,dtype=int));positions=obs.index.get_indexer(selected.iloc[ids].index)
    records=[];mapping={}
    with OfflineRanges() as reader:
        with h5py.File(reader,'r',rdcc_nbytes=0) as f:
            ptr=f['X/indptr'][:]
            for pos in positions:
                lo,hi=int(ptr[pos]),int(ptr[pos+1]);arrays={};addresses=[]
                for name in ['data','indices']:
                    d=f['X/'+name];step=d.chunks[0];pieces=[]
                    for coord in range(lo//step*step,hi,step):
                        key=(name,coord)
                        if key not in mapping:mapping[key]=locate(reader,d,coord)
                        offset,size=mapping[key];a=max(lo-coord,0);b=min(hi-coord,step)
                        raw=reader.cached(offset+a*d.dtype.itemsize,(b-a)*d.dtype.itemsize)
                        pieces.append(np.frombuffer(raw,dtype=d.dtype));addresses.append({'dataset':name,'coord':coord,'raw_chunk_offset':offset,'raw_chunk_bytes':size,'selected_offset':offset+a*d.dtype.itemsize,'selected_bytes':len(raw)})
                    arrays[name]=np.concatenate(pieces)
                expected=load_npz(ART/'extracted/development_controls'/f'{pos}.npz')
                valid=np.array_equal(arrays['data'],expected.data) and np.array_equal(arrays['indices'],expected.indices)
                records.append({'position':int(pos),'nnz':hi-lo,'exact_array_match':valid,'ranges':addresses})
                if not valid:raise ValueError('row differs from already-verified full-chunk extraction')
    report={'at_utc':now(),'network_requests':0,'raw_bytes_fabricated':0,'sample_scope':'8 frozen development NTC rows across row-index range; no perturbation responses','valid':all(x['exact_array_match'] for x in records),'checks':records,'potential_full_chunk_bytes':sum(a['raw_chunk_bytes'] for r in records for a in r['ranges']),'selected_byte_count':sum(a['selected_bytes'] for r in records for a in r['ranges'])}
    atomic(DATA/'partial_chunk_engineering_validation.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},indent=2))

if __name__=='__main__':validate()
