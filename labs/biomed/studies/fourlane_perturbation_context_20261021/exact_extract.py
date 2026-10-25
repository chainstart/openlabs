"""Read HDF5-requested chunks directly over persistent exact HTTPS ranges.

Unlike H5Dget_chunk_info_by_coord/H5Ovisit, normal hyperslab reading follows
the chunk B-tree without enumerating the entire allocation table.
"""
import sys
from range_h5 import RangeFile
from sparse_chunks import transfer, cache_chunk, CHUNKDIR
from extract_subset import extract

class ExactRangeFile(RangeFile):
    def read(self,n=-1):
        if n<0 or n>256*1024**2:raise ValueError('unbounded/oversized HDF read rejected')
        n=min(n,self.size-self.pos)
        if not n:return b''
        if n>=65536:
            start=self.pos;size=n
        else:
            start=self.pos//65536*65536;size=min(((self.pos+n-start+65535)//65536)*65536,self.size-start)
        item={'offset':start,'bytes':size}
        CHUNKDIR.mkdir(exist_ok=True)
        p=cache_chunk(item)
        if p is None:
            if self.used+size>self.budget:raise RuntimeError('exact-range phase budget exceeded')
            self.used+=size;p=transfer(item)
        with p.open('rb') as f:
            f.seek(self.pos-start);out=f.read(n)
        if len(out)!=n:raise RuntimeError('short cached read')
        self.pos+=n
        return out

if __name__=='__main__':
    extract(sys.argv[1],sys.argv[2],int(sys.argv[3]) if len(sys.argv)>3 else 2*1024**3,reader=ExactRangeFile)
