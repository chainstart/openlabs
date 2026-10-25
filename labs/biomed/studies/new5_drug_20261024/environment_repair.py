from pathlib import Path
import json,hashlib,sys,subprocess,importlib.metadata,pandas as pd
R=Path('/home/biostar/work/projects/openlabs/openlabs');P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
env={'python':sys.version,'executable':sys.executable,'installed_distributions':sorted([x.metadata['Name']+'=='+x.version for x in importlib.metadata.distributions()]),'uv_lock_sha256':hashlib.sha256((R/'labs/biomed/uv.lock').read_bytes()).hexdigest(),'code_root_git_revision':subprocess.check_output(['git','-C',str(R),'rev-parse','HEAD'],text=True).strip()}
(P/'environment.json').write_text(json.dumps(env,indent=2)+'\n')
(P/'software-failure-001.json').write_text(json.dumps({'failure':'pip absent in uv-managed environment; PLAN and samples already frozen before export failure. Follow-up one-line shell export had a quoting SyntaxError before executing.','resolution':'importlib.metadata installed distribution export + uv lock SHA; no scientific plans/samples altered, no response read.','science_unchanged':True},indent=2)+'\n')
d=pd.read_csv(P/'samples-frozen.csv');print(d.groupby('split').agg(rows=('sample_id','size'),cells=('SIDM','nunique'),pairs=('pair','nunique')))
