from pathlib import Path
import csv,json,math,hashlib,collections,sys
R=Path('/home/biostar/work/projects/openlabs/openlabs');P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
r=json.loads((P/'RESULTS.json').read_text());sums=collections.defaultdict(lambda:collections.defaultdict(lambda:[0.,0]));sets={s:{'cells':set(),'pairs':set()} for s in ['train','validation','test']};seen=set();retained=[];rows=0
with (A/'predictions.csv').open() as f:
 for row in csv.DictReader(f):
  key=row['sample_id'];assert key not in seen;seen.add(key);sp=row['split'];sets[sp]['cells'].add(row['SIDM']);sets[sp]['pairs'].add(row['pair']);y=float(row['Bliss_matrix']);assert math.isfinite(y)
  for name in r['baselines']:
   v=float(row['pred_'+name]);assert math.isfinite(v);item=sums[(sp,name)][row['pair']];item[0]+=(v-y)**2;item[1]+=1
  rows+=1;retained.append({'sample_id':key,'split':sp,'cell_line_id':row['SIDM'],'drug_pair_id':row['pair']})
checks=[]
for (sp,name),gs in sums.items():
 mse=sum(v[0]/v[1] for v in gs.values())/len(gs);ref=r['all_metrics'][sp][name]['pair_weighted_mse'];assert abs(mse-ref)<1e-12,(sp,name,mse,ref);checks.append({'split':sp,'model':name,'pair_mse_recomputed':mse,'absolute_error':abs(mse-ref)})
for i,a in enumerate(sets):
 for b in list(sets)[i+1:]:
  assert not sets[a]['cells']&sets[b]['cells'];assert not sets[a]['pairs']&sets[b]['pairs']
for a,b in [('M3_pathway_growth','M1_ridge'),('M3_pathway_growth','M2_global_growth'),('M6_extra_trees_growth','M5_extra_trees_no_growth')]:
 ma=r['all_metrics']['test'][a]['pair_weighted_mse'];mb=r['all_metrics']['test'][b]['pair_weighted_mse'];gain=100*(mb-ma)/mb;assert abs(gain-r['contrasts'][a+'__vs__'+b]['relative_mse_improvement_percent'])<1e-12
sources=[]
for obj in json.loads((P/'intake-index.json').read_text()):
 m=obj['dataset'];f=Path(m['artifact_uri'].removeprefix('file://'));h=hashlib.sha256(f.read_bytes()).hexdigest();assert h==m['sha256'] and f.stat().st_size==m['bytes'];sources.append({'file':str(f),'sha256':h,'bytes':m['bytes']})
out={'passed':True,'method':'Independent standard-library CSV arithmetic; does not import or execute analyze.py, fit any model, or create a new confirmation.','rows':rows,'unique_units':len(seen),'metric_checks':checks,'cell_and_pair_overlap_zero':True,'source_payload_hashes_rechecked':sources,'prediction_sha256':hashlib.sha256((A/'predictions.csv').read_bytes()).hexdigest(),'plan_sha256':hashlib.sha256((P/'PLAN_FROZEN.json').read_bytes()).hexdigest()}
(P/'FIRST_DETERMINISTIC_VERIFICATION.json').write_text(json.dumps(out,indent=2)+'\n')
with (P/'samples-retained.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=['sample_id','split','cell_line_id','drug_pair_id']);w.writeheader();w.writerows(retained)
sys.path.insert(0,str(R/'labs/biomed'));from tools.split_audit import audit
au=audit(P/'samples-retained.csv',independent_unit='cell_line',group_columns=['cell_line_id','drug_pair_id'],strategy='group',project_root=P);assert au['valid'];(P/'split-audit-retained.json').write_text(json.dumps(au,indent=2)+'\n')
print(json.dumps({'passed':True,'rows':rows,'metric_checks':len(checks),'all_source_hashes_verified':len(sources)},indent=2))
