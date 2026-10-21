"""Bounded CPU orchestration while the two guarded intake sessions finish."""
import json,time,sys,subprocess,signal,os,traceback
from common import *

deadline=dt.datetime.fromisoformat('2026-10-22T00:10:00+00:00')
guard='/home/biostar/work/openlabs/bin/openlabs-resource-guard'
python=str(CODE.parents[1]/'.venv/bin/python')
expected=['encff511xtz','encff774dyo','encff631lha','encff971uba',
          'encff131cmc','encff855whd','encff986rez',
          'encff563oup','encff859zrh','encff857lyj',
          'encff145ldy','encff476dyq','encff355pae']
last=0
try:
    while True:
        remaining=(deadline-dt.datetime.now(dt.timezone.utc)).total_seconds()
        if remaining<=0:raise TimeoutError('Campaign deadline reached')
        ready=[x for x in expected if (ART/'intakes'/x/'manifest.json').exists() and (ART/'intakes'/x/'official-md5-check.json').exists()]
        received=sum(p.stat().st_size for x in expected for p in (ART/'intakes'/x).glob('data.*'))
        partial=sum(p.stat().st_size for x in expected for p in (ART/'intakes'/x).glob('.download-*'))
        assert received+partial<=1024**3
        if len(ready)==len(expected):break
        if time.monotonic()-last>=60:
            info=dict(at_utc=now(),complete_official_md5_files=len(ready),planned_files=len(expected),
                      received_bytes=received+partial,real_task='Two existing guarded HTTP intake sessions; driver waits for official-MD5-complete manifests',
                      remaining_files=[x for x in expected if x not in ready])
            atomic(PROJECT/'driver-progress.json',info)
            status('waiting_for_immutable_inputs','Frozen promoter-specific orientation transfer',
                   'guarded driver.py readiness wait; download_replicates.py and intake.py ENCFF857LYJ are the real download tasks',
                   [PROJECT/'driver-progress.json',PROJECT/'intake-progress.json'])
            print(json.dumps(info),flush=True);last=time.monotonic()
        time.sleep(min(20,remaining))
    for script,args in [('run.py',['select']),('run.py',['confirm']),('finalize.py',[])]:
        command=[guard,'--task-type','cpu','--','env','OMP_NUM_THREADS=2','OPENBLAS_NUM_THREADS=2','MKL_NUM_THREADS=2',python,str(CODE/script),*args]
        print('EXECUTING',json.dumps(command),flush=True)
        remaining=(deadline-dt.datetime.now(dt.timezone.utc)).total_seconds()
        if remaining<=0:raise TimeoutError('Deadline before next phase')
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
        try:out,_=process.communicate(timeout=min(600,remaining))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM);out,_=process.communicate(timeout=20)
            raise TimeoutError('Bounded phase timeout: '+script+' '+str(args))
        log=(ART if script!='finalize.py' else PROJECT)/(script+'-'+('-'.join(args) or 'package')+'.log')
        log.write_text(out)
        print(out,flush=True)
        if process.returncode:raise RuntimeError('Phase failed: '+script+' '+str(args)+'; '+str(log))
    print('All computation and evidence packaging completed. No background models were launched.',flush=True)
except Exception as e:
    atomic(PROJECT/'execution-failure.json',dict(time_utc=now(),error=str(e),traceback=traceback.format_exc(),confirmation_started=(PROJECT/'confirmation.started.json').exists()))
    status('execution_stopped','Frozen promoter contrast pilot requires failure review',
           'driver.py stopped: '+str(e),[PROJECT/'execution-failure.json'],state='failed')
    raise
