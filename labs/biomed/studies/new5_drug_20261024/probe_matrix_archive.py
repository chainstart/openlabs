from pathlib import Path
import requests,json,struct,hashlib,datetime
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
url='https://media.springernature.com/full/springer-static/esm/art%3A10.1038%2Fs43856-026-01583-w/MediaObjects/43856_2026_1583_MOESM18_ESM.zip';size=515355059
def fetch(start,end):
 r=requests.get(url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'},stream=True,timeout=30)
 if r.status_code!=206 or r.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}':
  status={'http_status':r.status_code,'Content-Range':r.headers.get('Content-Range'),'Content-Length':r.headers.get('Content-Length')};r.close();raise RuntimeError(status)
 data=r.raw.read(end-start+2);r.close();assert len(data)==end-start+1;return data
out={'url':url,'expected_size':size,'metadata_only':True,'external_outcome_not_read':True}
try:
 tail=fetch(size-65536,size-1);(A/'melanoma-matrix-zip-tail.bin').write_bytes(tail);i=tail.rfind(b'PK\x05\x06');assert i>=0;fields=struct.unpack('<4s4H2LH',tail[i:i+22]);count=fields[4];cdsize=fields[5];offset=fields[6];assert cdsize<=8*1024**2
 cd=fetch(offset,offset+cdsize-1);(A/'melanoma-matrix-zip-cd.bin').write_bytes(cd);pos=0;names=[]
 while pos<len(cd):
  assert cd[pos:pos+4]==b'PK\x01\x02';f=struct.unpack('<4s6H3L5H2L',cd[pos:pos+46]);nl,xl,cl=f[10:13];name=cd[pos+46:pos+46+nl].decode('utf-8',errors='replace');names.append(name);pos+=46+nl+xl+cl
 assert len(names)==count
 (A/'melanoma-matrix-archive-members.json').write_text(json.dumps(names,indent=2)+'\n');out.update({'success':True,'members':count,'central_directory_bytes':cdsize,'file_extensions':dict(__import__('collections').Counter(Path(n).suffix for n in names)),'first_members':names[:15],'tail_sha256':hashlib.sha256(tail).hexdigest(),'central_directory_sha256':hashlib.sha256(cd).hexdigest()})
except Exception as exc:out.update({'success':False,'failure':repr(exc)})
(P/'EXTERNAL_RAW_MATRIX_ARCHIVE_FEASIBILITY.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
