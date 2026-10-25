"""Audited bounded Range reader: no full-atlas download or dense expression."""
from intake import *
import io,collections,http.client,ssl
class Remote(io.RawIOBase):
    def __init__(self,url,size,block=262144):
        self.url=url;self.size=size;self.pos=0;self.block=block;self.cache=collections.OrderedDict();self.downloaded=0
        self.disk=ART/'range_payload'/hashlib.sha256(url.encode()).hexdigest()[:16];self.disk.mkdir(parents=True,exist_ok=True)
        self.connection=None
    def get_range(self,lo,hi):
        target=urllib.parse.urlparse(self.url)
        assert target.scheme=='https' and target.hostname=='datasets.cellxgene.cziscience.com'
        for attempt in range(3):
            if datetime.now(timezone.utc)>=datetime.fromisoformat('2026-10-22T11:46:31.613021+00:00'):raise RuntimeError('Campaign deadline reached')
            try:
                if self.connection is None:
                    proxy=urllib.parse.urlparse(os.environ.get('https_proxy',os.environ.get('HTTPS_PROXY','')))
                    if proxy.hostname:
                        assert not proxy.username,'Authenticated proxy unsupported by this bounded reader'
                        self.connection=http.client.HTTPSConnection(proxy.hostname,proxy.port or 80,timeout=45,context=ssl.create_default_context())
                        self.connection.set_tunnel(target.hostname,443)
                    else:self.connection=http.client.HTTPSConnection(target.hostname,timeout=45,context=ssl.create_default_context())
                self.connection.request('GET',target.path,headers={'Range':f'bytes={lo}-{hi}'})
                r=self.connection.getresponse()
                if r.status!=206 or r.getheader('Content-Range')!=f'bytes {lo}-{hi}/{self.size}':raise RuntimeError('Invalid range response '+str(r.status))
                data=r.read(hi-lo+2)
                with (ART/'transfer.lock').open('a') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX)
                    p=ART/'transfer_bytes.json';used=json.loads(p.read_text())['bytes']+len(data)
                    atomic(p,dict(bytes=used))
                    if used>6*1024**3:raise RuntimeError('Aggregate transfer budget exceeded')
                if len(data)!=hi-lo+1:raise RuntimeError('Short range response')
                return data
            except Exception as e:
                with (ART/'range_failures.jsonl').open('a') as f:f.write(json.dumps(dict(at=now(),start=lo,end=hi,attempt=attempt,error=repr(e)))+'\n')
                if self.connection:self.connection.close()
                self.connection=None
                if isinstance(e,RuntimeError) or attempt==2:raise
                time.sleep(2)
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.pos
    def seek(self,offset,whence=0):
        self.pos=offset if whence==0 else self.pos+offset if whence==1 else self.size+offset
        return self.pos
    def readinto(self,b):
        result=self.read(len(b));b[:len(result)]=result;return len(result)
    def read(self,n=-1):
        if n<0:raise RuntimeError('Unbounded read forbidden')
        n=min(n,self.size-self.pos);pieces=[]
        while n:
            bid=self.pos//self.block;lo=bid*self.block;hi=min(lo+self.block,self.size)-1
            if bid not in self.cache:
                stored=self.disk/f'{lo}-{hi}.bin'
                parentlo=(lo//262144)*262144
                parent=self.disk/f'{parentlo}-{min(parentlo+262144,self.size)-1}.bin'
                if self.block<262144 and not stored.exists() and parent.exists():
                    stored.write_bytes(parent.read_bytes()[lo-parentlo:hi-parentlo+1])
                if stored.exists():
                    self.cache[bid]=stored.read_bytes()
                    if len(self.cache[bid]) != hi-lo+1:raise RuntimeError('Invalid cached range length: '+str(stored))
                    if len(self.cache)>256:self.cache.popitem(last=False)
                    continue
                t=time.monotonic()
                data=self.get_range(lo,hi)
                temp=stored.with_suffix('.tmp');temp.write_bytes(data);temp.replace(stored)
                with (ART/'h5_ranges.jsonl').open('a') as f:f.write(json.dumps(dict(url=self.url,start=lo,end=hi,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),path=str(stored),utc=now(),seconds=time.monotonic()-t))+'\n')
                self.downloaded+=len(data);self.cache[bid]=data
                if len(self.cache)>256:self.cache.popitem(last=False)
            data=self.cache[bid];offset=self.pos-lo;take=min(n,len(data)-offset)
            pieces.append(data[offset:offset+take]);self.pos+=take;n-=take
        return b''.join(pieces)
if __name__=='__main__':
    import h5py
    r=Remote('https://datasets.cellxgene.cziscience.com/5f863718-02a6-46cb-83e7-52be988b915b.h5ad',21860171922)
    with h5py.File(r,'r') as h:
        print('ROOT',list(h),flush=True)
        print('OBS',list(h['obs']),flush=True)
        for name in ['dataset','study','study_long','donor_id','_index']:
            if name in h['obs']:
                a=h['obs'][name];print(name,type(a).__name__,dict(a.attrs),flush=True)
                if isinstance(a,h5py.Group):print('categories',a['categories'][:],flush=True)
        print('RAW',list(h['raw']) if 'raw' in h else None,flush=True)
        print('X',dict(h['X'].attrs),list(h['X']) if isinstance(h['X'],h5py.Group) else h['X'].shape,flush=True)
    print('downloaded',r.downloaded)
