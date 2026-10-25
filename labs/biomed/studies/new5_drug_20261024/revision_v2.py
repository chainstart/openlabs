"""Post-review corrections only. Frozen predictions; no fitting or new confirmation."""
from pathlib import Path
import argparse, hashlib, json, datetime
import numpy as np
import pandas as pd
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024')
A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
ap=argparse.ArgumentParser();ap.add_argument('--output-root',required=True);args=ap.parse_args();O=Path(args.output_root);O.mkdir(parents=True,exist_ok=False)
names=['B2_family_mean','B3_family_global_activity','B4_activity_knn']
cross=pd.read_csv(A/'crossnull-matrix-predictions.csv')
# Align C2: matrix means already saved, then average related cells per donor,
# then square within each fold; fold-average losses; family-balanced donor mean.
aligned=cross.groupby(['donor_id','family_pair','fold'],as_index=False)[['coupled_label','disjoint_label']+names].mean()
records=[]
for (donor,family),g in aligned.groupby(['donor_id','family_pair']):
 assert set(g.fold)=={0,1}
 r={'donor_id':donor,'family_pair':family}
 for mode in ['coupled','disjoint']:
  for m in names:r[mode+'_'+m]=float(((g[m]-g[mode+'_label'])**2).mean())
 records.append(r)
units=pd.DataFrame(records);units.to_csv(O/'crossnull-aligned-units.csv',index=False)
def score(frame):
 mm=frame.groupby('family_pair').mean(numeric_only=True).mean().to_dict();out={'mse':mm}
 for mode in ['coupled','disjoint']:
  for b in names[:2]:out[mode+'_vs_'+b]=100*(mm[mode+'_'+b]-mm[mode+'_'+names[2]])/mm[mode+'_'+b]
 for b in names[:2]:out['disjoint_minus_coupled_vs_'+b+'_pp']=out['disjoint_vs_'+b]-out['coupled_vs_'+b]
 return out
metrics=score(units);ds=sorted(units.donor_id.unique());fs=sorted(units.family_pair.unique());di=units.donor_id.map({x:i for i,x in enumerate(ds)}).to_numpy();fi=units.family_pair.map({x:i for i,x in enumerate(fs)}).to_numpy();rng=np.random.default_rng(20261024);draw=[]
for _ in range(1000):
 dw=rng.multinomial(len(ds),np.ones(len(ds))/len(ds));fw=rng.multinomial(len(fs),np.ones(len(fs))/len(fs));den=np.bincount(fi,weights=dw[di],minlength=len(fs));ok=(den>0)&(fw>0);mm={}
 for mode in ['coupled','disjoint']:
  for m in names:
   k=mode+'_'+m;num=np.bincount(fi,weights=dw[di]*units[k].to_numpy(),minlength=len(fs));mm[k]=float(np.average(num[ok]/den[ok],weights=fw[ok]))
 r={}
 for mode in ['coupled','disjoint']:
  for b in names[:2]:r[mode+'_vs_'+b]=100*(mm[mode+'_'+b]-mm[mode+'_'+names[2]])/mm[mode+'_'+b]
 for b in names[:2]:r['disjoint_minus_coupled_vs_'+b+'_pp']=r['disjoint_vs_'+b]-r['coupled_vs_'+b]
 draw.append(r)
pd.DataFrame(draw).to_csv(O/'crossnull-paired-bootstrap.csv',index=False)
ci={k:np.quantile([r[k] for r in draw],[.025,.975]).tolist() for k in draw[0]}
# Diagnostic alternative only: square at dose point, then mean within matrix,
# then related cells within donor, donors within family, families equally.
point=pd.read_csv(A/'external-point-predictions.csv');meta=pd.read_csv(P/'external-cell-identities-frozen.csv',keep_default_na=False);pn=['B0_zero','B1_global_mean']+names+['B5_fitted_null_knn','B6_concentration_knn'];point=point.groupby(['Sample','family_pair','conc1','conc2'],as_index=False)[['empirical_bliss']+pn].mean();counts=point.groupby(['Sample','family_pair']).size();eligible=counts[counts>=12].index;point=point.set_index(['Sample','family_pair']).loc[eligible].reset_index()
for m in pn:point[m]=(point[m]-point.empirical_bliss)**2
mat=point.groupby(['Sample','family_pair'],as_index=False)[pn].mean().merge(meta,left_on='Sample',right_on='raw_name',validate='many_to_one');mat=mat[mat.is_melanoma.astype(bool)];doseunits=mat.groupby(['donor_id','family_pair'],as_index=False)[pn].mean();doseunits.to_csv(O/'dosewise-loss-units.csv',index=False);dosemse=doseunits.groupby('family_pair')[pn].mean().mean().to_dict()
# Recompute auxiliary-screen availability from raw original controls, not reviewer counts.
parts=[]
for r in json.loads((P/'intake-index.json').read_text()):
 f=Path(r['dataset']['artifact_uri'].removeprefix('file://'));d=pd.read_csv(f,usecols=['SIDM','BARCODE','growth_rate']);d['screen']=f.name.split('_matrix')[0];parts.append(d)
d=pd.concat(parts);d['growth_rate']=pd.to_numeric(d.growth_rate,errors='coerce');g=d[d.growth_rate.between(.25,8,inclusive='neither')].drop_duplicates().groupby(['SIDM','screen']).growth_rate.median();tr=pd.read_csv(A/'analysis-units.csv');tr=tr[tr.split=='train'];hold=[s for s in sorted(d.screen.unique()) if '010' in s][0];cells=set(g.xs(hold,level='screen').index)
aux={'heldout_screen':hold,'training_cells':int(tr.SIDM.nunique()),'training_rows':len(tr),'training_cells_with_GDSC010_auxiliary_control_available':int(tr[tr.SIDM.isin(cells)].SIDM.nunique()),'training_rows_with_GDSC010_auxiliary_control_available':int(tr.SIDM.isin(cells).sum()),'interpretation':'Combination-label holdout with cross-screen auxiliary controls; not screen-naive. Availability in other-screen median candidate pool, not proof each control changes median.'}
out={'revision':2,'new_model_fits':0,'not_new_confirmation':True,'crossnull_estimand':'Within each fold average matrix predictions and labels across related cells per donor-family BEFORE square; average fold losses, then donors within family, then families equally.','crossnull_donor_family_units':len(units),'crossnull_metrics':metrics,'paired_crossed_bootstrap_95':ci,'bootstrap_seed':20261024,'bootstrap_replicates':1000,'dosewise_diagnostic_mse':dosemse,'dosewise_diagnostic_not_primary':True,'primary_endpoint':'Mean point predictions and labels within matrix, then related cells within donor-family, THEN squared error; family-balanced mean. It evaluates dose-surface mean effect, not local dose-surface accuracy.','auxiliary_control_disclosure':aux,'limitations':'Frozen implementations missed specified improvement thresholds; does not falsify biological mechanisms or identify cause of transfer failure. Crossnull paired gain difference CI includes zero; no demonstrated coupling explanation. Shared control/culture normalization and drug-node dependence remain.'}
(O/'RESULTS_V2.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
