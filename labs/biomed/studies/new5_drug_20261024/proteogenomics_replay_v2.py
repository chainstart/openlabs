"""Replay corrected frozen scripts only in a new private clone, no network."""
from pathlib import Path
import argparse,shutil,subprocess,sys,json
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
ap=argparse.ArgumentParser();ap.add_argument('--output-root',type=Path,required=True);args=ap.parse_args();V=args.output_root;V.mkdir(parents=True,exist_ok=False);C=V/'code';C.mkdir();source=Path(__file__).parent
A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-root-20261024')
for f in source.iterdir():
 if f.is_file() and f.suffix in ['.py','.json','.csv']:shutil.copy2(f,C/f.name)
# No canonical QUALIFICATION/samples/pair_universe writes: P resolves to new clone.
jobs=[('analyze.py',[str(A/'proteogenomics'),str(V/'primary')]),('sensitivity.py',[str(A/'proteogenomics'),str(V/'primary'),str(V/'sensitivity')]),('external_ccle.py',[str(A),str(V/'external-qualification')]),('segment_external.py',[str(A),str(V/'segment-external')]),('complex_followup.py',[str(A),str(V/'complex'),str(V/'primary')])]
records=[]
for n,a in jobs:
 cmd=[sys.executable,str(C/n),*a];print('START '+n,flush=True);p=subprocess.run(cmd,capture_output=True,text=True);(V/(n+'.log')).write_text(p.stdout+p.stderr);records.append({'argv':cmd,'exit_code':p.returncode});(V/'EXECUTION.json').write_text(json.dumps(records,indent=2)+'\n');assert p.returncode==0,p.stderr
print('all five corrected phases completed; computational replay, not new confirmation',flush=True)
