from remote_h5 import *
import h5py,numpy as np,pandas as pd
URL='https://datasets.cellxgene.cziscience.com/5f863718-02a6-46cb-83e7-52be988b915b.h5ad'
def decode(a):return np.asarray([x.decode() if isinstance(x,bytes) else x for x in a])
def readcol(h,name,inds):
    o=h['obs'][name]
    if isinstance(o,h5py.Group):
        cats=decode(o['categories'][:]);c=o['codes'][:][inds]
        return np.asarray([cats[i] if i>=0 else '' for i in c])
    # Our rows may be interspersed; read in contiguous runs to avoid large fancy indexing.
    chunks=[]
    for g in np.split(inds,np.where(np.diff(inds)!=1)[0]+1):
        if len(g):chunks.append(decode(o[int(g[0]):int(g[-1])+1]))
    return np.concatenate(chunks)
if __name__=='__main__':
    r=Remote(URL,21860171922)
    with h5py.File(r,'r') as h:
        cats=decode(h['obs/study/categories'][:]);codes=h['obs/study/codes'][:]
        for study in ['Banovich_Kropski_2020','Kaminski_2020']:
            ids=np.flatnonzero(codes==np.flatnonzero(cats==study)[0]);print(study,len(ids),'runs',1+sum(np.diff(ids)!=1),flush=True)
            d={'row':ids}
            for c in ['_index','donor_id','sample','original_ann_nonharmonized','ann_level_1','disease','age_or_mean_of_age_range','sex','total_counts']:
                d[c]=readcol(h,c,ids)
            df=pd.DataFrame(d);df.to_csv(ART/f'{study}_metadata.csv.gz',index=False)
            print(df.iloc[:2].to_string(index=False),flush=True)
        for layer in ['X','raw/X']:
            print(layer,dict(h[layer].attrs),[(k,h[layer][k].shape,h[layer][k].dtype.str,h[layer][k].chunks,h[layer][k].compression) for k in h[layer]],flush=True)
        print('VAR',list(h['raw/var']),flush=True)
    print('bytes',r.downloaded,flush=True)
