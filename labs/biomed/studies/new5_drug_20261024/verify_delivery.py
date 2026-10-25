from pathlib import Path
import argparse,csv,json,hashlib,collections,datetime,numpy as np,pandas as pd
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=P/'DETERMINISTIC_DELIVERY_VERIFICATION.json');args=ap.parse_args()
def digest(f,alg='sha256'):
 h=hashlib.new(alg)
 with Path(f).open('rb') as x:
  for b in iter(lambda:x.read(1024**2),b''):h.update(b)
 return h.hexdigest()
sources=[r['dataset'] for r in json.loads((P/'intake-index.json').read_text())]+[json.loads((P/'sanger-raw-intake.json').read_text())]+json.loads((P/'melanoma-intake-index.json').read_text());sources +=[json.loads(Path(r['manifest']).read_text()) for r in json.loads((P/'EXTERNAL_CHEMICAL_QUALIFICATION.json').read_text())['compound_matches']]
payloads=[]
for m in sources:
 f=Path(m['artifact_uri'].removeprefix('file://'));h=digest(f);assert h==m['sha256'] and f.stat().st_size==m['bytes'],f;payloads.append({'file':str(f),'sha256':h,'bytes':m['bytes']})
published=[]
for aid in [22362769,22362793,22362802,22362808,22362760,25266697]:
 m=json.loads((A/f'figshare-{aid}.json').read_text());fmeta=m['files'][0];folder='gdsc-combination-raw-'+str(aid) if aid==25266697 else 'gdsc-combination-'+str(aid);f=A/folder/fmeta['name'];h=digest(f,'md5');assert h==fmeta['computed_md5'];published.append({'article':aid,'published_md5_matched':h})
res=json.loads((P/'EXTERNAL_RESULTS.json').read_text());names=list(res['metrics']);groups=collections.defaultdict(lambda:collections.defaultdict(lambda:collections.defaultdict(list)));maxerr=0.
with (A/'external-point-predictions.csv').open() as f:
 for row in csv.DictReader(f):
  e1,e2,e12=map(float,[row['e1'],row['e2'],row['combo_inhibition_raw']]);v=min(1,max(0,e12))-e1-e2+e1*e2;maxerr=max(maxerr,abs(v-float(row['empirical_bliss'])));key=(row['Sample'],row['family_pair']);dose=(row['conc1'],row['conc2'])
  for c in ['empirical_bliss',*names]:groups[key][dose][c].append(float(row[c]))
assert maxerr<1e-12
ident={}
with (P/'external-cell-identities-frozen.csv').open() as f:
 for row in csv.DictReader(f):ident[row['raw_name']]=row
units=collections.defaultdict(lambda:collections.defaultdict(list));matrices=0;tumormatrices=0
for (cell,fam),ds in groups.items():
 if len(ds)<12:continue
 matrices+=1
 if ident[cell]['is_melanoma']!='True':continue
 tumormatrices+=1;donor=ident[cell]['donor_id'];means={c:sum(sum(values[c])/len(values[c]) for values in ds.values())/len(ds) for c in ['empirical_bliss',*names]}
 for c,v in means.items():units[(donor,fam)][c].append(v)
loss=collections.defaultdict(lambda:collections.defaultdict(list))
for (donor,fam),vals in units.items():
 y=sum(vals['empirical_bliss'])/len(vals['empirical_bliss'])
 for n in names:v=sum(vals[n])/len(vals[n]);loss[n][fam].append((v-y)**2)
checks=[]
for n,fs in loss.items():
 mse=sum(sum(v)/len(v) for v in fs.values())/len(fs);old=res['metrics'][n]['family_donor_balanced_mse'];assert abs(mse-old)<1e-12,(n,mse,old);checks.append({'model':n,'mse_reconstructed':mse,'absolute_error':abs(mse-old)})
assert matrices==res['counts']['eligible_matrices'] and tumormatrices==res['counts']['tumor_matrices'] and len(units)==res['counts']['donor_family_units']
old=pd.read_csv(A/'predictions.csv');rp=A/'computational-replay-first-v2';new=pd.read_csv(rp/'artifacts/predictions.csv');assert list(old)==list(new);delta={}
for c in old:
 if pd.api.types.is_numeric_dtype(old[c]):assert np.allclose(old[c],new[c],atol=1e-12,rtol=1e-12,equal_nan=True);delta[c]=float(np.nanmax(np.abs(old[c]-new[c])))
 else:assert old[c].equals(new[c])
a=json.loads((P/'RESULTS.json').read_text());b=json.loads((rp/'records/RESULTS.json').read_text());fields=['metrics','baselines','all_metrics','contrasts','negative_control','counts','exclusions','trials_run','limitations'];assert all(a[f]==b[f] for f in fields)
replay={'passed':True,'metric_fields_exactly_equal':fields,'prediction_byte_identical':digest(A/'predictions.csv')==digest(rp/'artifacts/predictions.csv'),'largest_numeric_prediction_difference':max(delta.values()),'numeric_tolerance':1e-12,'differences_restricted_to_parallel_tree_predictions':{c:v for c,v in delta.items() if v!=0},'same_original_scientific_code':digest(Path(__file__).parent/'analyze.py')==json.loads((P/'CONFIRMATION_OPENED.json').read_text())['analysis_sha256'],'new_independent_confirmation':False}
out={'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':True,'review_type':'Deterministic provenance/arithmetic/replay checks only; not independent scientific review or approval.','payloads':payloads,'published_figshare_md5_checks':published,'external_primary_bliss_point_formula_max_absolute_error':maxerr,'external_metrics_reconstructed_from_points_and_frozen_donor_table':checks,'external_matrices':matrices,'external_tumor_matrices':tumormatrices,'external_donor_family_units':len(units),'first_pilot_complete_replay':replay,'external_predictor_reconstruction_receipt_sha256':digest(P/'EXTERNAL_PREDICTION_RECONSTRUCTION.json'),'crossnull_diagnostic_receipt_sha256':digest(P/'CROSSNULL_DIAGNOSTIC_RESULTS.json')}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({'passed':True,'payload_hashes':len(payloads),'official_md5_checks':len(published),'external_metric_reconstructions':len(checks),'C1_replay_max_difference':replay['largest_numeric_prediction_difference'],'output':str(args.output)},indent=2))
