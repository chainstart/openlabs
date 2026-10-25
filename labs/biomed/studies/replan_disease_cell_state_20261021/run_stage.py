"""Record guarded executions of frozen experiment/review stages."""
from common import *
import subprocess

allowed={'bulk_io.py','analyse_bulk.py','open_confirmation.py','reconstruct_results.py','plot_results.py','integrity_review.py','write_report.py','verify_math.py'}
script=sys.argv[1];assert script in allowed
assert not (ART/'scientific_closeout.json').exists(),'Campaign already scientifically closed'
assert datetime.now(timezone.utc)<datetime.fromisoformat(DEADLINE)
command=[str(ROOT/'openlabs/bin/openlabs-resource-guard'),'--task-type','cpu','--',sys.executable,str(CODE/script),*sys.argv[2:]]
start=now();tag=start.replace(':','').replace('+','_')+'_'+script.removesuffix('.py')
log=ART/'execution_logs'/f'{tag}.log';log.parent.mkdir(exist_ok=True)
record=dict(started_at_utc=start,command=command,script_sha256=sha(CODE/script),plan_sha256=sha(DATA/'plan_frozen_v1.json'),log=str(log),cgroup=Path('/proc/self/cgroup').read_text())
with log.open('w') as out:
 result=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,cwd=ROOT/'openlabs',check=False)
record.update(finished_at_utc=now(),returncode=result.returncode,log_sha256=sha(log))
with (ART/'executions.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
print(log.read_text()[-15000:]);print(json.dumps(record))
if result.returncode:
 atomic(DATA/f'software_failure_{tag}.json',dict(**record,classification='Execution failure; preserve partial outputs and exposure before any repair; not a new scientific configuration'))
raise SystemExit(result.returncode)
