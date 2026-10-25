"""Extract preselected CSR rows by bounded remote ranges; save each row for resume."""
import hashlib
import json
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd
import h5py
from scipy.sparse import csr_matrix, save_npz
from intake import ART, DATA, atomic, status, now
from range_h5 import RangeFile

def extract(table, label, budget=2*1024**3, reader=RangeFile, summary_suffix=''):
    selected=pd.read_csv(table,index_col=0)
    obs=pd.read_csv(ART/'pseudobulk_obs.csv',index_col=0)
    positions=obs.index.get_indexer(selected.index)
    assert (positions>=0).all()
    out=ART/'extracted'/label;out.mkdir(parents=True,exist_ok=True)
    with reader(budget=budget) as r:
        # Uncompressed CSR: disabling the raw chunk cache lets HDF5 request only
        # the hyperslab's physical bytes. Validated against 16 complete NTC rows.
        with h5py.File(r,'r',rdcc_nbytes=0) as f:
            ptr=f['X/indptr'][:]
            nvar=int(f['X'].attrs['shape'][1]);done=0;last=time.monotonic()
            for name,pos in sorted(zip(selected.index,positions),key=lambda x:x[1]):
                dest=out/f'{pos}.npz'
                if dest.exists():done+=1;continue
                lo,hi=int(ptr[pos]),int(ptr[pos+1])
                values=f['X/data'][lo:hi]; indices=f['X/indices'][lo:hi]
                if not np.isfinite(values).all() or (values<0).any():raise ValueError('invalid counts')
                row=csr_matrix((values,indices,np.array([0,hi-lo])),shape=(1,nvar))
                save_npz(dest,row)
                atomic(dest.with_suffix('.json'),{'row_index':int(pos),'sample_id':str(name),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'source_object':r.key,'nnz':int(hi-lo),'sum':float(values.sum()),'sum_matches_metadata':bool(np.isclose(values.sum(),obs.iloc[pos].total_counts)),'retrieved_at_utc':now()})
                done+=1
                if done%10==0: print('rows_done',done,'of',len(selected),'range_bytes',r.used,flush=True)
                if time.monotonic()-last>300:
                    status('extracting_'+label,[f'{done}/{len(selected)} frozen rows extracted','Range 206 and SHA256 recorded'],['finish subset extraction','freeze/evaluate experiment','scientific report'],[str(table),str(out)])
                    last=time.monotonic()
    atomic(out/('extraction_summary'+summary_suffix+'.json'),{'row_count':done,'selection_file':str(table),'selection_sha256':hashlib.sha256(Path(table).read_bytes()).hexdigest(),'range_bytes_this_run':r.used})

if __name__=='__main__':
    from pathlib import Path
    extract(sys.argv[1],sys.argv[2],int(sys.argv[3]) if len(sys.argv)>3 else 2*1024**3)
