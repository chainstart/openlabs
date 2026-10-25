from pathlib import Path
import argparse,json,hashlib,datetime
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
ap=argparse.ArgumentParser();ap.add_argument('--index',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();index=json.loads(args.index.read_text());checked=[]
for rec in index['files']:
 f=Path(rec['path']);h=hashlib.sha256()
 with f.open('rb') as x:
  for b in iter(lambda:x.read(1024**2),b''):h.update(b)
 assert h.hexdigest()==rec['sha256'] and f.stat().st_size==rec['bytes'],str(f);checked.append(str(f))
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'valid':True,'files_checked':len(checked),'index_sha256':hashlib.sha256(args.index.read_bytes()).hexdigest(),'no_scientific_approval':True},indent=2)+'\n');print(json.dumps({'valid':True,'files_checked':len(checked),'output':str(args.output)}))
