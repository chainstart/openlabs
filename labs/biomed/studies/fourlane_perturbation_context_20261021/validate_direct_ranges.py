"""Offline equivalence of HDF5 direct row reads with disabled raw chunk cache."""
import json
import h5py
import numpy as np
import pandas as pd
from scipy.sparse import load_npz
from probe_chunk_offsets import OfflineRanges
from intake import ART, DATA, atomic, now

class RecordingRanges(OfflineRanges):
    def __init__(self):super().__init__();self.calls=[]
    def read(self,n=-1):
        self.calls.append({'offset':self.pos,'bytes':n})
        return super().read(n)

def validate():
    obs=pd.read_csv(ART/'pseudobulk_obs.csv',index_col=0)
    selected=pd.read_csv(DATA/'development_controls.csv',index_col=0)
    ids=np.unique(np.linspace(0,len(selected)-1,16,dtype=int));positions=obs.index.get_indexer(selected.iloc[ids].index)
    records=[]
    with RecordingRanges() as reader:
        with h5py.File(reader,'r',rdcc_nbytes=0) as f:
            ptr=f['X/indptr'][:]
            for pos in positions:
                lo,hi=int(ptr[pos]),int(ptr[pos+1]);arrays={};ranges=[];full=0
                for name in ['data','indices']:
                    d=f['X/'+name]
                    assert d.compression is None and d.id.get_create_plist().get_nfilters()==0
                    before=len(reader.calls);arrays[name]=d[lo:hi]
                    ranges+=reader.calls[before:]
                    full+=len(range(lo//d.chunks[0]*d.chunks[0],hi,d.chunks[0]))*d.chunks[0]*d.dtype.itemsize
                expected=load_npz(ART/'extracted/development_controls'/f'{pos}.npz')
                good=np.array_equal(arrays['data'],expected.data) and np.array_equal(arrays['indices'],expected.indices)
                if not good:raise ValueError('not equivalent')
                records.append({'position':int(pos),'nnz':hi-lo,'exact_array_match':good,'HDF_reads':ranges,'full_chunk_bytes':full,'actual_requested_bytes_including_metadata':sum(x['bytes'] for x in ranges)})
    result={'at_utc':now(),'network_requests':0,'raw_bytes_fabricated':0,'valid':True,'scope':'16 already verified development NTC rows; no new perturbation observations','hdf_parameter':'rdcc_nbytes=0; HDF5 itself reads exact uncompressed hyperslab byte regions','full_chunk_bytes':sum(x['full_chunk_bytes'] for x in records),'direct_requested_bytes':sum(x['actual_requested_bytes_including_metadata'] for x in records),'checks':records}
    atomic(DATA/'direct_range_equivalence_validation.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='checks'},indent=2))

if __name__=='__main__':validate()
