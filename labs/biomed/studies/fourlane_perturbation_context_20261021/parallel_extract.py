"""Two CPU/HTTPS workers in the same service; row shards do not alter scientific splits."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import time
import pandas as pd
from intake import ART, DATA, atomic, now, status

CODE=Path(__file__).resolve().parent
GUARD=CODE.parents[3]/'bin/openlabs-resource-guard'
PYTHON=CODE.parents[1]/'environments/singlecell/.venv/bin/python'

def run(table,label,budget):
    group=Path('/proc/self/cgroup').read_text()
    assert 'openlabs-workers.slice' in group and 'openlabs-biomed-four-perturbation-context-20261021.service' in group
    selected=pd.read_csv(table,index_col=0)
    processes=[];logs=[]
    try:
        for shard in range(2):
            sub=selected.iloc[shard::2];p=DATA/f'{label}_transport_shard{shard}.csv';sub.to_csv(p)
            env=os.environ.copy();env.update(OPENLABS_RANGE_CACHE=f'h5chunks_worker{shard}',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
            log=(ART/f'{label}_worker{shard}.log').open('a');logs.append(log)
            cmd=[str(GUARD),'--task-type','cpu','--',str(PYTHON),str(CODE/'parallel_extract.py'),'worker',str(p),label,str(budget),str(shard)]
            processes.append(subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT))
        while any(p.poll() is None for p in processes):
            if any(p.poll() not in [None,0] for p in processes):raise RuntimeError('extraction worker failed; preserve partials and logs')
            time.sleep(10)
        if any(p.returncode for p in processes):raise RuntimeError('extraction worker failed')
        atomic(ART/'extracted'/label/'extraction_summary.json',{'at_utc':now(),'row_count':len(selected),'selection_file':str(table),'selection_sha256':hashlib.sha256(Path(table).read_bytes()).hexdigest(),'method':'two disjoint row transport shards, private writable caches, same service; original cached fragments reused','worker_exit_codes':[p.returncode for p in processes]})
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            if p.poll() is None:
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        for log in logs:log.close()

if __name__=='__main__':
    def interrupted(signum,frame):raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,interrupted)
    if sys.argv[1]=='worker':
        from exact_extract import ExactRangeFile
        from extract_subset import extract
        extract(sys.argv[2],sys.argv[3],int(sys.argv[4]),reader=ExactRangeFile,summary_suffix='_shard'+sys.argv[5])
    else:run(sys.argv[1],sys.argv[2],int(sys.argv[3]))
