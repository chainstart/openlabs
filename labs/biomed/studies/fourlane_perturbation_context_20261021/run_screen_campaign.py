"""Continue only unfinished frozen screen steps, under the original deadline."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import signal
import time
from intake import ART, DATA, atomic, now, status

CODE=Path(__file__).resolve().parent
GUARD=CODE.parents[3]/'bin/openlabs-resource-guard'
PY=CODE.parents[1]/'environments/singlecell/.venv/bin/python'
DEADLINE=dt.datetime.fromisoformat('2026-10-22T11:46:31.613021+00:00')

def record(obj):
    with (DATA/'screen_execution_ledger.jsonl').open('a') as f:f.write(json.dumps(dict(at_utc=now(),**obj))+'\n')

def run(script,*args):
    remaining=(DEADLINE-dt.datetime.now(dt.timezone.utc)).total_seconds()
    if remaining<=0:raise RuntimeError('original campaign deadline reached')
    cmd=list(map(str,[GUARD,'--task-type','cpu','--',PY,CODE/script,*args]))
    record({'event':'command_start','command':cmd,'script_sha256':hashlib.sha256((CODE/script).read_bytes()).hexdigest()})
    status(script+':'+str(args[0]),['bulk validation and once-only confirmation completed','screen proceeding under frozen plan'],['finish screen experiment','independent reconstruction','final report'],[str(DATA/'screen_execution_ledger.jsonl')])
    proc=subprocess.Popen(cmd,env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1'),start_new_session=True)
    try:
        while proc.poll() is None:
            if dt.datetime.now(dt.timezone.utc)>=DEADLINE:raise RuntimeError('deadline during command')
            time.sleep(10)
        record({'event':'command_end','command':cmd,'returncode':proc.returncode})
        if proc.returncode:raise RuntimeError('command failed: '+str(cmd))
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()

if __name__=='__main__':
    def interrupted(signum,frame):raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,interrupted)
    try:
        while not (ART/'extracted/development_controls/extraction_summary.json').exists():
            if dt.datetime.now(dt.timezone.utc)>=DEADLINE:raise RuntimeError('deadline waiting for controls')
            time.sleep(10)
        if not (DATA/'screen_selection_frozen.json').exists():run('screen_analysis.py','select')
        run('parallel_extract.py',DATA/'screen_development_rows.csv','screen_development',str(2*1024**3))
        if not (DATA/'screen_final_model_frozen.json').exists():run('screen_analysis.py','develop')
        if not (DATA/'screen_confirmation_opened.json').exists():run('screen_analysis.py','open')
        run('parallel_extract.py',DATA/'screen_confirmation_controls.csv','screen_confirmation_controls',str(512*1024**2))
        run('parallel_extract.py',DATA/'screen_confirmation_rows.csv','screen_confirmation',str(2*1024**3))
        if json.loads((DATA/'screen_confirmation_opened.json').read_text())['status']!='evaluated once':run('screen_analysis.py','confirm')
        record({'event':'screen_experiment_finished','scientific_review_pending':True})
        status('screen_results_review',['screen confirmation evaluated once','bulk confirmation evaluated once'],['results reconstruction','scientific disposition','final report'])
    except BaseException as e:
        record({'event':'screen_pipeline_interrupted','error':repr(e),'retain_frozen_plan':True})
        status('screen_pipeline_interrupted',['partial evidence retained','bulk confirmation completed'],['diagnose interruption; do not reopen confirmation','final report'],failures=[repr(e)])
        raise
