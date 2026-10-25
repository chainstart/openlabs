from pathlib import Path
import json,sys,argparse,hashlib,datetime
R=Path('/home/biostar/work/projects/openlabs/openlabs');P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=P/'NATIVE_PILOT_GATE.json');args=ap.parse_args();sys.path.insert(0,str(R/'labs/biomed'))
from tools import dataset_intake
from protocols import public_data_pilot
local={s['source_id']:s for s in json.loads((P/'source_registry_local.json').read_text())['sources']};original=dataset_intake.source_record
dataset_intake.source_record=lambda sid:local[sid] if sid in local else original(sid)
errors=public_data_pilot.validate(P/'project.json',P/'state.json',mode='commit')
out={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'valid':not errors,'errors':errors,'validator':'labs/biomed/protocols/public_data_pilot.py existing validate(mode=commit)','validator_sha256':hashlib.sha256((R/'labs/biomed/protocols/public_data_pilot.py').read_bytes()).hexdigest(),'scoped_extension':'Loads project-local source registry in-process only. Global registry unchanged; bare CLI without scoped source registration would reject unknown GDSCcombination source.','plan_adapter':'native-pilot-plan.json serializes original structured holdout field as string only; original freeze SHA-bound.','scientific_approval':False,'paper_candidate':False,'covers':'C1 exploratory pilot provenance bookkeeping, payload checks, cell-line/pair disjoint splits and frozen baseline results. C2andcrossnull have separately frozen protocols, arithmetic/hashes and model reconstruction; native C1threewaygate does not certify their scientific independence.'}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2));raise SystemExit(bool(errors))
