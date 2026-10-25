"""Launch private R reader under inherited lane guard and an RSS backstop."""
from intake import *
import subprocess

def run(script,log_name):
    assert 'openlabs-biomed-four-disease-cell-state-20261021.service' in Path('/proc/self/cgroup').read_text()
    root=ART/'spatial-r-core';home=root/'usr/lib/R'
    env=os.environ.copy()
    env.update(R_HOME=str(home),R_SHARE_DIR=str(root/'usr/share/R/share'),R_INCLUDE_DIR=str(root/'usr/share/R/include'),R_DOC_DIR=str(root/'usr/share/doc/R'),R_LIBS_USER=str(root/'private-library'),R_LIBS_SITE=str(root/'private-library'),LD_LIBRARY_PATH=str(home/'lib'),OPENBLAS_NUM_THREADS='2',OMP_NUM_THREADS='2')
    (root/'private-library').mkdir(exist_ok=True)
    peak=0;reason=None;start=time.monotonic()
    with (ART/log_name).open('w') as out:
        p=subprocess.Popen([str(home/'bin/exec/R'),'--vanilla','--slave','-f',str(script)],env=env,stdout=out,stderr=subprocess.STDOUT)
        while p.poll() is None:
            try:
                entries=Path(f'/proc/{p.pid}/status').read_text().splitlines()
                rss=int(next(x.split()[1] for x in entries if x.startswith('VmRSS:')))*1024
                peak=max(peak,rss)
                if rss>3600*1024**2:reason='R RSS exceeded 3600MiB backstop';p.terminate()
                if datetime.now(timezone.utc)>=datetime.fromisoformat('2026-10-22T11:46:31.613021+00:00'):reason='Campaign deadline';p.terminate()
                if reason:
                    try:p.wait(timeout=10)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
            except (FileNotFoundError,StopIteration):pass
            time.sleep(.5)
    record=dict(at=now(),script=str(script),script_sha256=hashlib.sha256(Path(script).read_bytes()).hexdigest(),returncode=p.returncode,peak_R_RSS_bytes=peak,seconds=time.monotonic()-start,stop_reason=reason)
    atomic(ART/(log_name+'.execution.json'),record)
    print(json.dumps(record));return p.returncode

if __name__=='__main__':sys.exit(run(Path(sys.argv[1]),sys.argv[2]))
