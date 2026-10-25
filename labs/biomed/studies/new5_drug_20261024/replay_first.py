from pathlib import Path
import json,hashlib,shutil,subprocess,sys,datetime,argparse,pandas as pd,numpy as np
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024');C=Path(__file__).parent
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
original=C/'analyze.py';sha=hashlib.sha256(original.read_bytes()).hexdigest();receipt=json.loads((P/'CONFIRMATION_OPENED.json').read_text());assert sha==receipt['analysis_sha256']
parser=argparse.ArgumentParser();parser.add_argument('--output-root',type=Path);args=parser.parse_args()
case=args.output_root or A/'computational-replay-first-v2';case.mkdir(exist_ok=False,parents=True);rp=case/'records';ra=case/'artifacts';rp.mkdir();ra.mkdir()
for name in ['PLAN_FROZEN.json','samples-frozen.csv','environment.json','intake-index.json']:shutil.copyfile(P/name,rp/name)
src=original.read_text();assert src.count(str(P))==1 and src.count(str(A))==1;src=src.replace(str(P),'__REPLAY_RECORD_ROOT__').replace(str(A),str(ra)).replace('__REPLAY_RECORD_ROOT__',str(rp));script=case/'analyze-replay.py';script.write_text(src)
subprocess.run([sys.executable,str(script)],check=True)
old=json.loads((P/'RESULTS.json').read_text());new=json.loads((rp/'RESULTS.json').read_text());fields=['metrics','baselines','all_metrics','contrasts','negative_control','counts','exclusions','trials_run','limitations']
for f in fields:assert old[f]==new[f],f
h1=hashlib.sha256((A/'predictions.csv').read_bytes()).hexdigest();h2=hashlib.sha256((ra/'predictions.csv').read_bytes()).hexdigest()
aa=pd.read_csv(A/'predictions.csv');bb=pd.read_csv(ra/'predictions.csv');assert list(aa)==list(bb) and len(aa)==len(bb);deltas={}
for c in aa:
 if pd.api.types.is_numeric_dtype(aa[c]):
  assert np.allclose(aa[c],bb[c],atol=1e-12,rtol=1e-12,equal_nan=True),c;deltas[c]=float(np.nanmax(np.abs(aa[c]-bb[c])))
 else:assert aa[c].equals(bb[c]),c
out={'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':True,'original_analysis_sha256':sha,'original_freeze_sha256':receipt['protocol_sha256'],'replay_transformation':'Only absolute writable project/artifact paths replaced; original scientific source unchanged; original hash matches initial execution receipt.','original_scientific_source_retained':str(original),'replay_script':str(script),'replay_script_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),'scientific_result_fields_identical':fields,'predictions_byte_identical':h1==h2,'original_prediction_sha256':h1,'replay_prediction_sha256':h2,'per_numeric_column_max_absolute_difference':deltas,'numeric_comparison_tolerance':1e-12,'new_independent_confirmations':0,'new_scientific_configurations':0,'note':'Computational numerical replay of exposed frozen data, not biological replication or new hypothesis test; parallel tree reduction can differ at machine-roundoff level.'}
(case/'REPLAY_VERIFICATION.json' if args.output_root else P/'C1_REPLAY_VERIFIED.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
