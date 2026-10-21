"""Bounded progress inspection; no scientific outcome reads."""
import json
from common import *
intakes=[];total=0
for directory in sorted((ART/'intakes').iterdir()):
    if not directory.is_dir():continue
    manifest=directory/'manifest.json'
    if manifest.exists():
        m=json.loads(manifest.read_text());size=m['bytes'];state='complete'
    else:
        size=sum(p.stat().st_size for p in directory.glob('.download-*'));state='receiving'
    intakes.append(dict(dataset=directory.name,bytes=size,state=state));total+=size
assert total<1024**3
cg=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::')[1].lstrip('/')
resources={n:(cg/n).read_text().strip() for n in ['cpu.max','memory.high','memory.max','memory.current','memory.events','pids.max','pids.current']}
active=[]
for pid in (cg/'cgroup.procs').read_text().split():
    try:
        args=Path('/proc',pid,'cmdline').read_bytes()[:8192].decode().strip('\0').split('\0')
        if args and 'python' in Path(args[0]).name and any(str(CODE) in a or 'labs/biomed/studies/functional_genomics_day1_20261021/' in a for a in args[1:]):
            active.append(dict(pid=int(pid),argv=args))
    except (FileNotFoundError,PermissionError):pass
record=dict(at_utc=now(),intakes=intakes,received_payload_bytes=total,resources=resources,
            real_tasks=active,
            deadline_utc='2026-10-22T00:10:00Z')
atomic(PROJECT/'intake-progress.json',record)
status('bounded_intake_progress','Frozen individual promoter orientation contrast portability',
       json.dumps(active,ensure_ascii=False)+'; progress.py inspected byte counts only',
       [PROJECT/'intake-progress.json',PROJECT/'plan.json'])
print(json.dumps(record,indent=2))
