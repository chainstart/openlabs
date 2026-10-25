"""Inspect only corrected release headers/ranges before any large spatial intake."""
from intake import *
import struct,zlib

URL='https://ftp.ncbi.nlm.nih.gov/geo/series/GSE250nnn/GSE250346/suppl/GSE250346_Seurat_GSE250346_CORRECTED_SEE_RDS_README_082024.rds'

def main():
    with urllib.request.urlopen(urllib.request.Request(URL,method='HEAD'),timeout=45) as r:
        size=int(r.headers['Content-Length']);headers=dict(r.headers)
    assert size<=2500*1024**2
    records=[];parts=[]
    for lo,hi in [(0,65535),(size-16,size-1)]:
        start=time.monotonic()
        with urllib.request.urlopen(urllib.request.Request(URL,headers={'Range':f'bytes={lo}-{hi}'}),timeout=45) as r:
            assert r.status==206 and r.headers.get('Content-Range')==f'bytes {lo}-{hi}/{size}'
            data=r.read(hi-lo+2);assert len(data)==hi-lo+1
        with (ART/'transfer.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);p=ART/'transfer_bytes.json';used=json.loads(p.read_text())['bytes']+len(data);atomic(p,dict(bytes=used));assert used<=6*1024**3
        out=ART/'payload'/f'spatial_corrected_rds_{lo}_{hi}.bin';out.write_bytes(data)
        records.append(dict(url=URL,start=lo,end=hi,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),path=str(out),seconds=time.monotonic()-start));parts.append(data)
    compression='gzip' if parts[0][:2]==b'\x1f\x8b' else 'other'
    rec=dict(at=now(),file_bytes=size,source=URL,headers=headers,ranges=records,compression=compression,terms='source_registry_local.json',expression_opened=False)
    if compression=='gzip':
        rec['gzip_ISIZE_modulo_2pow32']=struct.unpack('<I',parts[1][-4:])[0]
        rec['serialization_header_hex']=zlib.decompressobj(31).decompress(parts[0],64)[:32].hex()
        rec['memory_warning']='Gzip ISIZE is modulo2^32 and cannot by itself establish an upper memory bound. No full RDS loading authorized by this probe.'
    atomic(DATA/'spatial_corrected_format_probe.json',rec);print(json.dumps(rec,indent=2))

if __name__=='__main__':main()
