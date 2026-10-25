from pathlib import Path
import json,zipfile,hashlib,pandas as pd,numpy as np
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
plan=json.loads((P/'EXTERNAL_PLAN_FROZEN.json').read_text());mapping=plan['source_target_family_maps']['source'];drugs=pd.read_csv(P/'compound-metadata.csv');idname=drugs.set_index('ID').name.to_dict();f=next((A/'gdsc-combination-raw-25266697').glob('*.zip'));manifest=json.loads((P/'sanger-raw-intake.json').read_text());assert hashlib.sha256(f.read_bytes()).hexdigest()==manifest['sha256'];z=zipfile.ZipFile(f)
cols=['PROJECT_NAME','BARCODE','MASTER_CELL_ID','CELL_LINE_NAME','CELL_ID','CANCER_TYPE','POSITION','cmatrix','lib1_drug_id','lib2_drug_id','lib1_conc','lib2_conc','lib1_y','lib2_y','lib1_yhat','lib2_yhat','lib1_RMSE','lib2_RMSE','inhibition','Bliss_additivity','Bliss_excess']
parts=[];readrows=0;counts={};max_identity_error=0.
for member in z.namelist():
 if not member.endswith('.csv'):continue
 count=0
 for d in pd.read_csv(z.open(member),usecols=cols,chunksize=100000,low_memory=False):
  readrows+=len(d);d=d[d.CANCER_TYPE.eq('Melanoma')].copy();d['drug1']=d.lib1_drug_id.map(idname);d['drug2']=d.lib2_drug_id.map(idname);d['family1']=d.drug1.map(mapping);d['family2']=d.drug2.map(mapping);d=d.dropna(subset=['family1','family2']);d=d[d.family1!=d.family2]
  if not len(d):continue
  for c in ['lib1_conc','lib2_conc','lib1_y','lib2_y','lib1_yhat','lib2_yhat','lib1_RMSE','lib2_RMSE','inhibition','Bliss_additivity','Bliss_excess']:d[c]=pd.to_numeric(d[c],errors='coerce')
  fin=np.isfinite(d[['lib1_conc','lib2_conc','lib1_y','lib2_y','lib1_yhat','lib2_yhat','inhibition','Bliss_excess']]).all(axis=1);d=d.loc[fin&(d.lib1_RMSE<=.3)&(d.lib2_RMSE<=.3)&(d.lib1_conc>0)&(d.lib2_conc>0)].copy()
  q=d.inhibition-(d.lib1_yhat+d.lib2_yhat-d.lib1_yhat*d.lib2_yhat);max_identity_error=max(max_identity_error,float(np.max(np.abs(q-d.Bliss_excess))) if len(d) else 0.)
  switch=d.family1>d.family2
  d['family_pair']=d.apply(lambda r:'|'.join(sorted([r.family1,r.family2])),axis=1)
  d['e1']=np.where(switch,d.lib2_y,d.lib1_y);d['e2']=np.where(switch,d.lib1_y,d.lib2_y);d['fitted_e1']=np.where(switch,d.lib2_yhat,d.lib1_yhat);d['fitted_e2']=np.where(switch,d.lib1_yhat,d.lib2_yhat);d['conc1']=np.where(switch,d.lib2_conc,d.lib1_conc);d['conc2']=np.where(switch,d.lib1_conc,d.lib2_conc)
  d['empirical_bliss']=np.clip(d.inhibition,0,1)-np.clip(d.e1,0,1)-np.clip(d.e2,0,1)+np.clip(d.e1,0,1)*np.clip(d.e2,0,1);d['e1']=d.e1.clip(0,1);d['e2']=d.e2.clip(0,1);d['fitted_bliss']=d.Bliss_excess
  d['chemical_pair']=d.apply(lambda r:'|'.join(sorted([r.drug1.lower(),r.drug2.lower()])),axis=1)
  d['screen']=d.PROJECT_NAME;count+=len(d);parts.append(d[['screen','MASTER_CELL_ID','CELL_LINE_NAME','CELL_ID','BARCODE','cmatrix','POSITION','family_pair','chemical_pair','e1','e2','fitted_e1','fitted_e2','conc1','conc2','empirical_bliss','fitted_bliss']])
 counts[member]=count
assert max_identity_error<1e-10,max_identity_error
d=pd.concat(parts,ignore_index=True);d.to_csv(A/'source-selected-raw-points.csv',index=False)
keys=['screen','MASTER_CELL_ID','CELL_LINE_NAME','family_pair','chemical_pair','conc1','conc2'];a=d.groupby(keys,as_index=False)[['e1','e2','fitted_e1','fitted_e2','empirical_bliss','fitted_bliss']].mean();a.to_csv(A/'source-points-technical-averages.csv',index=False)
out={'raw_archive_rows_streamed':readrows,'selected_raw_points':len(d),'technical_average_points':len(a),'independent_cell_lines':a.MASTER_CELL_ID.nunique(),'family_pairs':a.family_pair.nunique(),'chemical_pairs':a.chemical_pair.nunique(),'native_Bliss_identity_max_absolute_error':max_identity_error,'selected_per_member':counts,'native_vs_empirical_mean_difference':float((a.fitted_bliss-a.empirical_bliss).mean()),'native_vs_empirical_rmse':float(np.sqrt(np.mean((a.fitted_bliss-a.empirical_bliss)**2))),'source_points_sha256':hashlib.sha256((A/'source-points-technical-averages.csv').read_bytes()).hexdigest(),'target_combination_response_not_read':True}
(P/'SOURCE_POINT_RECONSTRUCTION.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
