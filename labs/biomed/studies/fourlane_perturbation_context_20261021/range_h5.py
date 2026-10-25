"""Auditable Range-only HDF5 metadata/subset reader; never fetch full remote object."""
import io
import json
import re
import sys
from pathlib import Path
import h5py
from intake import ART, DATA, fetch, atomic

class RangeFile(io.RawIOBase):
    def __init__(self, key='GWCD4i.pseudobulk_merged.h5ad', size=44566657140, budget=256*1024**2):
        self.key=key; self.size=size; self.pos=0; self.block=1024*1024; self.budget=budget; self.used=0
        self.url='https://genome-scale-tcell-perturb-seq.s3.amazonaws.com/marson2025_data/'+key
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self,offset,whence=0):
        self.pos=offset if whence==0 else self.pos+offset if whence==1 else self.size+offset
        return self.pos
    def read(self,n=-1):
        if n<0: raise ValueError('unbounded reads forbidden')
        end=min(self.pos+n,self.size); parts=[]
        while self.pos<end:
            start=self.pos//self.block*self.block; stop=min(start+self.block,self.size)-1
            name=self.key+'.range_'+str(start)+'_'+str(stop)+'.bin'
            if not (ART/'manifests'/(name+'.json')).exists():
                if self.used+stop-start+1>self.budget: raise RuntimeError('range phase budget exceeded')
                self.used+=stop-start+1
            p=fetch(name,self.url,headers={'Range':f'bytes={start}-{stop}'},max_bytes=stop-start+1,accession='GSE314342',unit='guide x donor x stimulation pseudobulk',terms='Author public dataset; internal noncommercial attributed research; Cell article CC BY-NC 4.0; range fragments not redistributed',terms_url='https://creativecommons.org/licenses/by-nc/4.0/',citation='Zhu et al. Cell 2026 DOI10.1016/j.cell.2026.08.002')
            if p is None: raise RuntimeError('range fetch failed')
            m=json.loads((ART/'manifests'/(name+'.json')).read_text())
            headers={k.lower():v for k,v in m['response_headers'].items()}
            if headers.get('content-range')!=f'bytes {start}-{stop}/{self.size}' or m['bytes']!=stop-start+1: raise RuntimeError('invalid Content-Range/bytes')
            b=p.read_bytes(); a=self.pos-start; z=min(end-start,len(b));parts.append(b[a:z]);self.pos=start+z
        return b''.join(parts)
    def readinto(self,b):
        data=self.read(len(b)); b[:len(data)]=data;return len(data)

if __name__=='__main__':
    with RangeFile() as r:
        with h5py.File(r,'r',rdcc_nbytes=8*1024**2) as f:
            desc={}
            def visit(name,obj):
                desc[name]={'type':type(obj).__name__,'attrs':{k:str(v) for k,v in obj.attrs.items()}}
                if isinstance(obj,h5py.Dataset):desc[name].update(shape=list(obj.shape),dtype=str(obj.dtype),chunks=obj.chunks,compression=obj.compression,offset=obj.id.get_offset())
            # H5Ovisit traversed expensive allocation metadata in this remote file.
            # Inspect only the known AnnData paths; no recursive object traversal.
            for name in ['X','X/data','X/indices','X/indptr','obs','var']:
                visit(name,f[name])
            atomic(DATA/'remote_h5_layout.json',desc)
            print(json.dumps(desc,indent=2),flush=True)
            from anndata.io import read_elem
            obs=read_elem(f['obs']);var=read_elem(f['var'])
            obs.to_csv(ART/'pseudobulk_obs.csv'); var.to_csv(ART/'pseudobulk_var.csv')
            atomic(DATA/'pseudobulk_metadata_summary.json',{'obs_shape':list(obs.shape),'var_shape':list(var.shape),'columns':list(obs.columns),'donors':obs['donor_id'].value_counts().to_dict(),'conditions':obs['culture_condition'].value_counts().to_dict(),'range_bytes_this_run':r.used})
