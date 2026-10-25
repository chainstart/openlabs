"""Integrity-only comparison of already acquired original MTX prefix to atlas.

First complete columns, independent of outcomes; never used to refit models.
"""
from remote_h5 import *
from atlas_metadata import URL
from reconcile import devkey
import zlib,gzip,h5py,numpy as np,pandas as pd

prefix=ART/'payload/GSE135893_matrix_first64K.gzpart'
lines=zlib.decompressobj(31).decompress(prefix.read_bytes()).splitlines()
triples=np.array([list(map(int,x.split())) for x in lines[2:-1]])
last=int(triples[:,1].max())
barcodes=gzip.open(ART/'payload/GSE135893_barcodes.tsv.gz','rt').read().splitlines()
original_genes=gzip.open(ART/'payload/GSE135893_genes.tsv.gz','rt').read().splitlines()
assert len(original_genes)==33694 and len(barcodes)==220213
atlas_genes=pd.read_csv(ART/'atlas_genes.csv')
symbols=atlas_genes.feature_name.astype(str).tolist()
original_mapping={g:i for i,g in enumerate(original_genes)}
common=[(j,original_mapping[g]) for j,g in enumerate(symbols) if g in original_mapping]
meta=pd.read_csv(ART/'Banovich_Kropski_2020_metadata.csv.gz')
keys=set(barcodes);meta['cell_id']=meta._index.map(lambda x:devkey(x,keys))
lookup=meta.set_index('cell_id').row.to_dict()
r=Remote(URL,21860171922,block=32768)
records=[];differences=[]
with h5py.File(r,'r') as h:
 raw=h['raw/X'];ptr=raw['indptr'][:]
 for col in range(1,last):
  cell=barcodes[col-1]
  if cell not in lookup:continue
  row=int(lookup[cell]);a,b=int(ptr[row]),int(ptr[row+1])
  original=np.zeros(len(original_genes));sel=triples[triples[:,1]==col];original[sel[:,0]-1]=sel[:,2]
  atlas=np.zeros(len(symbols));atlas[raw['indices'][a:b]]=raw['data'][a:b]
  unequal=[]
  for j,k in common:
   if atlas[j]!=original[k]:unequal.append(dict(gene=symbols[j],original=float(original[k]),atlas=float(atlas[j])))
  records.append(dict(cell_id=cell,row=row,original_total=float(original.sum()),atlas_total=float(atlas.sum()),common_genes=len(common),unequal_common_genes=len(unequal)))
  differences.append(dict(cell_id=cell,differences=unequal))
atomic(DATA/'original_prefix_integrity.json',dict(at=now(),source_prefix_sha256=hashlib.sha256(prefix.read_bytes()).hexdigest(),complete_original_columns=last-1,matched_cells=records,new_network_bytes=r.downloaded,purpose='Transport integrity only; not training or confirmation; incomplete gzip prefix intentionally excludes last column'))
atomic(ART/'original_prefix_gene_differences.json',differences)
print(json.dumps(records),flush=True)
