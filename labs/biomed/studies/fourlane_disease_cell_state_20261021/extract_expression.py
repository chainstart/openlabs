from remote_h5 import *
from atlas_metadata import URL,decode
import h5py,numpy as np,pandas as pd
from scipy import sparse
tag=sys.argv[1]
assert tag in ['development','confirmation']
if tag=='confirmation' and not (DATA/'confirmation_open_authorization.json').exists():raise RuntimeError('Confirmation remains sealed')
samples=pd.read_csv(DATA/f'{tag}_sample_frozen.csv').sort_values('row')
out=ART/f'{tag}_raw_cells.npz'
if out.exists():raise RuntimeError('Refuse overwrite original extraction')
r=Remote(URL,21860171922,block=32768)
with h5py.File(r,'r') as h:
    raw=h['raw/X'];ptr=raw['indptr'][:]
    def gene_column(k):
        obj=h['raw/var'][k]
        if isinstance(obj,h5py.Group):
            cats=decode(obj['categories'][:]);codes=obj['codes'][:]
            return np.asarray([cats[c] if c>=0 else '' for c in codes])
        return decode(obj[:])
    genes=pd.DataFrame({k:gene_column(k) for k in ['_index','feature_name','feature_length']})
    if not (ART/'atlas_genes.csv').exists():genes.to_csv(ART/'atlas_genes.csv',index=False)
    blocks=set();chunk_bytes={}
    for name in ['data','indices']:
        d=raw[name];cs=d.chunks[0];chunkids=set()
        for row in samples.row:
            a,b=int(ptr[row]),int(ptr[row+1]);chunkids.update(range(a//cs,(b-1)//cs+1))
        # Traverse the index once, instead of one metadata query per cell chunk.
        # Persist this source-bound metadata for the later sealed-study forecast.
        index_path=ART/f'atlas_raw_{name}_chunk_index.npy'
        if index_path.exists():index=np.load(index_path,allow_pickle=False)
        else:
            entries=[]
            def collect(info):entries.append((info.chunk_offset[0],info.byte_offset,info.size))
            d.id.chunk_iter(collect)
            index=np.asarray(entries,dtype=np.uint64)
            tmp=index_path.with_suffix('.tmp')
            with tmp.open('wb') as f:np.save(f,index,allow_pickle=False)
            tmp.replace(index_path)
            atomic(index_path.with_suffix('.json'),dict(at=now(),source=URL,source_file_bytes=r.size,shape=d.shape,chunks=d.chunks,entries=len(index),sha256=hashlib.sha256(index_path.read_bytes()).hexdigest()))
        selected=index[np.isin(index[:,0]//cs,list(chunkids))]
        assert len(selected)==len(chunkids)
        total=int(selected[:,2].sum())
        for _,offset,size in selected:
            offset=int(offset);size=int(size)
            blocks.update(range(offset//32768,(offset+size-1)//32768+1))
        chunk_bytes[name]=total
    forecast=dict(at=now(),tag=tag,cells=len(samples),raw_chunk_compressed_bytes=chunk_bytes,range_block_upper_bound_bytes=len(blocks)*32768,metadata_transfer_bytes=r.downloaded,source=URL)
    atomic(DATA/f'{tag}_download_forecast.json',forecast);print(json.dumps(forecast),flush=True)
    if len(blocks)*32768>2500*1024**2:raise RuntimeError('Selective fetch exceeds declared per-stage estimate; replan before data')
    used=json.loads((ART/'transfer_bytes.json').read_text())['bytes']
    if used+len(blocks)*32768>6*1024**3:raise RuntimeError('Conservative stage forecast exceeds remaining cumulative budget')
    arrays=[];indices=[];indptr=[0]
    for j,row in enumerate(samples.row):
        a,b=int(ptr[row]),int(ptr[row+1]);val=raw['data'][a:b];col=raw['indices'][a:b]
        if (val<0).any() or not np.allclose(val,np.rint(val)):raise RuntimeError('Raw layer is not nonnegative integer counts')
        arrays.append(val.astype(np.float32));indices.append(col.astype(np.int32));indptr.append(indptr[-1]+len(val))
        if j%100==0:
            atomic(ART/f'{tag}_extraction_progress.json',dict(at=now(),cells_done=j+1,cells_total=len(samples),network_bytes=r.downloaded,paper_candidate=False))
            if j%500==0:print(tag,j+1,'/',len(samples),'new network MB',r.downloaded/1024**2,flush=True)
    matrix=sparse.csr_matrix((np.concatenate(arrays),np.concatenate(indices),np.asarray(indptr)),shape=(len(samples),len(genes)))
    sparse.save_npz(out,matrix,compressed=True);samples.to_csv(ART/f'{tag}_raw_cells.csv',index=False)
    totals=np.asarray(matrix.sum(axis=1)).ravel()
    field='nCount_RNA' if tag=='development' else 'nUMI';original=samples[field].to_numpy(float)
    audit=dict(at=now(),cells=len(samples),donors=samples.donor_id.nunique(),genes=len(genes),nnz=matrix.nnz,integer_counts=True,median_total_ratio=float(np.median(totals/original)),minimum_total_ratio=float(np.min(totals/original)),maximum_total_ratio=float(np.max(totals/original)),exact_total_matches=int(np.sum(totals==original)),source=URL,network_bytes=r.downloaded,payload_sha256=hashlib.sha256(out.read_bytes()).hexdigest())
    atomic(ART/f'{tag}_expression_intake.json',audit);print(json.dumps(audit),flush=True)
