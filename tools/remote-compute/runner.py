#!/usr/bin/env python3
"""Run inside a per-job systemd cgroup. Never calls the research database."""
import os,sys,json,time,signal,subprocess,datetime
from pathlib import Path
from protocol import validate,atomic,digest
from storage import entry_for_job,volumes

def main():
 job=Path(sys.argv[1]).resolve();r=validate(json.loads((job/'request.json').read_text()));resources=r['resources']
 volume=entry_for_job(job);storage_root=Path(volume['root']);scratch=job/'scratch';scratch.mkdir(mode=0o700,exist_ok=True)
 output=job/'result';output.mkdir(mode=0o700,exist_ok=True);(output/'outputs').mkdir(mode=0o700,exist_ok=True)
 env=dict(os.environ)
 env.update(OPENLABS_OUTPUT_DIR=str(output/'outputs'),OPENLABS_JOB_ID=r['job_id'],OMP_NUM_THREADS=str(resources['cpu_threads']),OPENBLAS_NUM_THREADS=str(resources['cpu_threads']),MKL_NUM_THREADS=str(resources['cpu_threads']),PYTHONUNBUFFERED='1',UV_CACHE_DIR=str(storage_root/'cache/uv'),OPENLABS_STORAGE_ID=volume['id'],OPENLABS_STORAGE_ROOT=str(storage_root),OPENLABS_STORAGE_ROOTS=json.dumps({v['id']:v['root'] for v in volumes()}),OPENLABS_SCRATCH_DIR=str(scratch),TMPDIR=str(scratch),TMP=str(scratch),TEMP=str(scratch))
 start=time.time();process=None;interrupted=[]
 for sig in [signal.SIGTERM,signal.SIGINT,signal.SIGHUP]:signal.signal(sig,lambda number,frame:interrupted.append(number))
 exitcode=125;error=None
 try:
  with (output/'stdout.log').open('wb') as stdout,(output/'stderr.log').open('wb') as stderr:
   process=subprocess.Popen(r['argv'],cwd=job/'payload',env=env,stdout=stdout,stderr=stderr,start_new_session=True)
   while process.poll() is None:
    if interrupted:raise InterruptedError('worker interrupted')
    if time.time()-start>resources['wall_seconds']:raise TimeoutError('wall time limit exceeded')
    # Jobs, scratch and uv caches use the selected independent experimental SSD.
    time.sleep(0.25)
   exitcode=process.returncode
 except (OSError,TimeoutError,InterruptedError) as exc:error=str(exc)
 finally:
  if process is not None:
   # Kill the session even after the leader exits, to clean background children.
   for sig in [signal.SIGTERM,signal.SIGKILL]:
    try:os.killpg(process.pid,sig)
    except ProcessLookupError:break
    if sig==signal.SIGTERM:time.sleep(0.5)
   process.wait()
 state='succeeded' if exitcode==0 and error is None else 'failed'
 cg=Path('/proc/self/cgroup').read_text().strip().split('::',1)[-1];root=Path('/sys/fs/cgroup')/cg.lstrip('/')
 actual={name:(root/name).read_text().strip() for name in ['cpu.max','memory.max','memory.high','memory.swap.max','pids.max'] if (root/name).exists()}
 atomic(output/'receipt.json',{'schema_version':'openlabs.remote-receipt.v1','job_id':r['job_id'],'backend':'ailab','state':state,'exit_code':exitcode,'error':error,'argv':r['argv'],'requested_resources':resources,'actual_cgroup':actual,'storage':volume,'scratch_directory':str(scratch),'payload_sha256':r['payload_sha256'],'elapsed_seconds':round(time.time()-start,3),'completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
 return 0 if state=='succeeded' else 1
if __name__=='__main__':sys.exit(main())
