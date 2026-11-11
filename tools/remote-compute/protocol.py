"""Shared wire/archive validation for the fixed ailab compute endpoint."""
from pathlib import Path, PurePosixPath
import hashlib,json,os,re,tarfile,shutil,tempfile
SCHEMA='openlabs.remote-compute.v1'
MAX_PAYLOAD=1024**3
MAX_EXTRACT=4*1024**3

def atomic(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 fd,name=tempfile.mkstemp(prefix='.new-',dir=path.parent)
 try:
  with os.fdopen(fd,'w') as out:json.dump(data,out,ensure_ascii=False,indent=2);out.write('\n')
  os.chmod(name,0o600);os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)

def digest(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def validate(r):
 if r.get('schema_version')!=SCHEMA or not re.fullmatch('[0-9a-f]{32}',str(r.get('job_id',''))):raise ValueError('invalid job identity')
 if r.get('backend')!='ailab':raise ValueError('unsupported backend')
 if r.get('task_type','cpu') not in ['cpu','math']:raise ValueError('invalid task type')
 if r.get('storage','auto') not in ['auto','ssd1','ssd2','ssd3','ssd4','ssd5','ssd6']:raise ValueError('invalid storage volume')
 argv=r.get('argv')
 if not isinstance(argv,list) or not argv or not all(isinstance(x,str) and x and '\0' not in x and len(x)<65536 for x in argv):raise ValueError('invalid argv')
 values=r.get('resources',{})
 for k,low,high in [('cpu_threads',1,8),('memory_mib',128,62961),('wall_seconds',1,31536000)]:
  v=values.get(k)
  if type(v) is not int or not low<=v<=high:raise ValueError('resource exceeds approved budget: '+k)
 if not re.fullmatch('[0-9a-f]{64}',str(r.get('payload_sha256',''))):raise ValueError('missing payload checksum')
 if type(r.get('payload_bytes')) is not int or not 0<r['payload_bytes']<=MAX_PAYLOAD:raise ValueError('payload exceeds limit')
 return r

def receive(stream,path,size,expected):
 path=Path(path);h=hashlib.sha256();remaining=size
 with path.open('wb') as out:
  path.chmod(0o600)
  while remaining:
   chunk=stream.read(min(1024*1024,remaining))
   if not chunk:raise ValueError('truncated archive')
   out.write(chunk);h.update(chunk);remaining-=len(chunk)
 if h.hexdigest()!=expected:raise ValueError('archive checksum mismatch')

def extract(archive,directory,max_bytes=MAX_EXTRACT):
 directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
 seen=set();total=0;count=0
 with tarfile.open(archive,'r:gz') as tar:
  for m in tar:
   p=PurePosixPath(m.name);parts=p.parts
   if not parts or p.is_absolute() or '..' in parts or '\\' in m.name or m.name in seen:raise ValueError('unsafe/duplicate archive path')
   seen.add(m.name);count+=1;total+=m.size
   if count>20000 or total>max_bytes or not (m.isfile() or m.isdir()):raise ValueError('unsafe archive type or size')
   target=directory.joinpath(*parts)
   if m.isdir():target.mkdir(parents=True,exist_ok=True,mode=0o700);continue
   target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
   with tar.extractfile(m) as src,target.open('xb') as out:shutil.copyfileobj(src,out,1024*1024)
   target.chmod(0o700 if m.mode&0o111 else 0o600)

def pack(directory,destination):
 directory=Path(directory)
 total=0;count=0
 with tarfile.open(destination,'w:gz') as tar:
  for p in sorted(directory.rglob('*')):
   if p.is_symlink() or not (p.is_file() or p.is_dir()):raise ValueError('refusing symlink/special output')
   count+=1;total+=p.stat().st_size if p.is_file() else 0
   if count>20000 or total>MAX_EXTRACT:raise ValueError('result exceeds transfer limit; original outputs retained on ailab')
   tar.add(p,arcname=str(p.relative_to(directory)),recursive=False)
 Path(destination).chmod(0o600)
