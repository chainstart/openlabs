"""Read selected official ZIP members through verified HTTP byte ranges."""
from common import *
import io,zipfile,re
class RemoteZip(io.RawIOBase):
    def __init__(self,url,size):self.url=url;self.size=size;self.pos=0;self.calls=0
    def seekable(self):return True
    def readable(self):return True
    def tell(self):return self.pos
    def seek(self,n,whence=0):
        self.pos=n if whence==0 else self.pos+n if whence==1 else self.size+n
        return self.pos
    def read(self,n=-1):
        if n<0:n=self.size-self.pos
        n=min(n,self.size-self.pos)
        if n<=0:return b''
        assert n<=128*1024**2,'Single range exceeds plan'
        start=self.pos;end=start+n-1;self.calls+=1
        name=f'agarwal-zip-range-{start}-{end}.bin'
        target=ART/'payload'/name;mp=ART/'manifests'/(name+'.json')
        if target.exists() and mp.exists():raw=target.read_bytes()
        else:
            rec=dict(source_url=self.url,range=f'bytes={start}-{end}',upstream_study='10.1038/s41586-024-08430-9',purpose='Selective ZIP member metadata; not full archive',attempts=[],time=now())
            for attempt in range(2):
                raw=b''
                try:
                    req=urllib.request.Request(self.url,headers={'Range':rec['range'],'User-Agent':'OpenLabs-promoter-research/1.0'})
                    with urllib.request.urlopen(req,timeout=40) as r:
                        rec.update(http_status=r.status,headers=dict(r.headers))
                        assert r.status==206 and r.headers.get('Content-Range')==f'bytes {start}-{end}/{self.size}','Invalid Range response'
                        raw=r.read(n+1)
                        assert len(raw)==n,'Invalid byte count'
                    target.write_bytes(raw);rec.update(actual_bytes=n,sha256=sha(target),payload=str(target),status='partial_archive');write(mp,rec);break
                except Exception as e:
                    rec['attempts'].append(dict(error=str(e),bytes=len(raw)));write(mp,rec)
                    if attempt==1:raise
                    time.sleep(1)
        self.pos+=len(raw);return raw
if __name__=='__main__':
    url=json.loads((ART/'manifests/agarwal-tables.zip.json').read_text())['source_url']
    with zipfile.ZipFile(RemoteZip(url,342234089)) as z:
        inv=[dict(name=i.filename,size=i.file_size,compressed=i.compress_size,offset=i.header_offset) for i in z.infolist()]
        write(DATA/'agarwal-remote-zip-inventory.json',inv);print(json.dumps(inv,indent=2),flush=True)
        # Explicitly requested members only, each separately budgeted after inventory.
        for wanted in sys.argv[1:]:
            item=z.getinfo(wanted);assert item.file_size<=256*1024**2 and item.compress_size<=128*1024**2
            raw=z.read(item);p=ART/'payload'/Path(wanted).name;p.write_bytes(raw)
            write(ART/'manifests'/(p.name+'.json'),dict(source_url=url,zip_member=wanted,actual_bytes=0,uncompressed_bytes=len(raw),sha256=sha(p),payload=str(p),status='extracted_CRC_verified',upstream_study='10.1038/s41586-024-08430-9',terms_url='https://creativecommons.org/licenses/by/4.0/'))
