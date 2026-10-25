from pathlib import Path
import json,zipfile,hashlib,collections,sys
import numpy as np,pandas as pd
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
plan=json.loads((P/'CROSSNULL_DIAGNOSTIC_PLAN.json').read_text());s=pd.read_csv(A/'source-points-technical-averages.csv');primary=pd.read_csv(A/'external-point-predictions.csv');coef=pd.read_csv(A/'external-B3-source-model.csv');pars=json.loads((A/'external-B3-intercept.json').read_text());cellmeta=pd.read_csv(P/'external-cell-identities-frozen.csv',keep_default_na=False)
def b3(fam,e1,e2):
 values={'e1':e1,'e2':e2,'e1_squared':e1*e1,'e2_squared':e2*e2,'e_product':e1*e2};xx=np.array([float(fam==f.removeprefix('family=')) if f.startswith('family=') else values[f] for f in coef.feature]);return float(np.dot((xx-coef.center.to_numpy())/coef.scale.to_numpy(),coef.coefficient_standardized.to_numpy())+pars['intercept'])
groups={}
for (fam,cell),g in s.groupby(['family_pair','MASTER_CELL_ID']):groups.setdefault(fam,[]).append((cell,g[['e1','e2']].to_numpy(),g.empirical_bliss.to_numpy()))
def b4(fam,e1,e2):
 vals=[]
 for cell,xx,yy in groups[fam]:
  dist=np.sqrt(np.sum((xx-[e1,e2])**2,axis=1));md=float(dist.min())
  if md<=.20:vals.append((md,cell,float(yy[np.abs(dist-md)<=1e-10].mean())))
 vals.sort(key=lambda q:(q[0],q[1]));vals=vals[:5];return float(np.mean([q[2] for q in vals])) if len(vals)>=3 else b3(fam,e1,e2)
# This reconstruction does not import either original analysis module or fit any model.
errors=[]
for r in primary.itertuples():errors.append((abs(b3(r.family_pair,r.e1,r.e2)-r.B3_family_global_activity),abs(b4(r.family_pair,r.e1,r.e2)-r.B4_activity_knn)))
maxerr=np.max(errors,axis=0);assert np.all(maxerr<1e-10),maxerr
(P/'EXTERNAL_PREDICTION_RECONSTRUCTION.json').write_text(json.dumps({'passed':True,'all_points_reconstructed':len(primary),'B3_max_absolute_error':float(maxerr[0]),'B4_max_absolute_error':float(maxerr[1]),'new_model_fits':0,'method':'Saved standardized ridge coefficients and independent NumPy nearest-cell/tie-average reconstruction, no original analysis imports.'},indent=2)+'\n')
sel=pd.read_csv(A/'external-selected-treatment-metadata.csv');sel=sel[sel.n_treatments==1].copy();sel['key']=sel.Sample.astype(str)+'|'+sel['Destination Plate Barcode'].astype(str)+'|'+sel['Destination Well'].astype(str);keys=set(sel.key);parts=[];z=zipfile.ZipFile(next((A/'melanoma2026-media-supp15').glob('*.zip')))
for d in pd.read_csv(z.open('data.csv'),usecols=['Sample','Destination Plate Barcode','Destination Well','Drug','Drug Concentration','Inhibition'],chunksize=100000):
 d['key']=d.Sample.astype(str)+'|'+d['Destination Plate Barcode'].astype(str)+'|'+d['Destination Well'].astype(str);parts.append(d[d.key.isin(keys)])
d=pd.concat(parts,ignore_index=True);d.Drug=d.Drug.str.strip();curves={};split_counts=collections.Counter();assignments=[]
for (cell,drug,conc),g in d.groupby(['Sample','Drug','Drug Concentration']):
 g=g[np.isfinite(g.Inhibition)].copy();g['h']=g.key.map(lambda key:hashlib.sha256(('20261024:'+cell+':'+drug+':'+str(conc)+':'+key).encode()).hexdigest());g=g.sort_values('h');n=len(g);split_counts[n]+=1
 if n<2:continue
 cut=n//2;va=float(np.median(g.Inhibition.iloc[:cut].clip(0,1)));vb=float(np.median(g.Inhibition.iloc[cut:].clip(0,1)));curves.setdefault((cell,drug),[]).append((float(conc),va,vb))
 for i,r in enumerate(g.itertuples()):assignments.append({'cell':cell,'drug':drug,'concentration':conc,'well_key':r.key,'group':'A' if i<cut else 'B'})
pd.DataFrame(assignments).to_csv(A/'crossnull-well-partitions.csv',index=False)
for k in curves:curves[k]=np.array(sorted(curves[k]))
def mono(cell,drug,conc,part):
 arr=curves.get((cell,drug))
 if arr is None or conc<arr[:,0].min() or conc>arr[:,0].max():return np.nan
 xx=arr[:,0];yy=arr[:,part+1];match=np.isclose(xx,conc,rtol=1e-6,atol=1e-9)
 return float(np.median(yy[match])) if match.any() else float(np.interp(np.log10(conc),np.log10(xx),yy))
rows=[];excluded=0
for r in primary.itertuples():
 a1=mono(r.Sample,r.drug1,r.conc1,0);a2=mono(r.Sample,r.drug2,r.conc2,0);b1=mono(r.Sample,r.drug1,r.conc1,1);b2=mono(r.Sample,r.drug2,r.conc2,1)
 if not np.isfinite([a1,a2,b1,b2]).all():excluded+=1;continue
 e12=float(np.clip(r.combo_inhibition_raw,0,1));ya=e12-a1-a2+a1*a2;yb=e12-b1-b2+b1*b2
 for fold,(u1,u2,own,other) in enumerate([(a1,a2,ya,yb),(b1,b2,yb,ya)]):
  rows.append({'Sample':r.Sample,'family_pair':r.family_pair,'fold':fold,'conc1':r.conc1,'conc2':r.conc2,'coupled_label':own,'disjoint_label':other,'B2_family_mean':pars['family_means'][r.family_pair],'B3_family_global_activity':b3(r.family_pair,u1,u2),'B4_activity_knn':b4(r.family_pair,u1,u2)})
p=pd.DataFrame(rows);p.to_csv(A/'crossnull-point-predictions.csv',index=False);num=['coupled_label','disjoint_label','B2_family_mean','B3_family_global_activity','B4_activity_knn'];point=p.groupby(['Sample','family_pair','fold','conc1','conc2'],as_index=False)[num].mean();counts=point.groupby(['Sample','family_pair','fold']).size();eligible=counts[counts>=12].index;matrix=point.set_index(['Sample','family_pair','fold']).loc[eligible].reset_index().groupby(['Sample','family_pair','fold'],as_index=False)[num].mean();matrix=matrix.merge(cellmeta,left_on='Sample',right_on='raw_name',how='left',validate='many_to_one');matrix=matrix[matrix.is_melanoma.astype(bool)];matrix.to_csv(A/'crossnull-matrix-predictions.csv',index=False)
gaps=[];lossrecords=[];names=num[2:]
for (cell,fam),g in matrix.groupby(['Sample','family_pair']):
 if set(g.fold)!={0,1}:continue
 g=g.set_index('fold')
 for name in names:
  coupled=float(np.mean((g[name]-g.coupled_label)**2));disjoint=float(np.mean((g[name]-g.disjoint_label)**2));expected=-(g.loc[0,name]-g.loc[1,name])*(g.loc[0,'coupled_label']-g.loc[1,'coupled_label']);gaps.append(abs((coupled-disjoint)-expected));lossrecords.append({'cell':cell,'donor_id':g.loc[0,'donor_id'],'family_pair':fam,'model':name,'coupled_mse':coupled,'disjoint_mse':disjoint,'algebraic_coupling_gap':coupled-disjoint})
assert max(gaps)<1e-10,max(gaps)
loss=pd.DataFrame(lossrecords);loss.to_csv(A/'crossnull-losses.csv',index=False);units=loss.groupby(['donor_id','family_pair','model'],as_index=False)[['coupled_mse','disjoint_mse','algebraic_coupling_gap']].mean();units.to_csv(A/'crossnull-donor-family-losses.csv',index=False)
metrics={}
for label in ['coupled_mse','disjoint_mse']:
 mm=units.groupby(['model','family_pair'])[label].mean().groupby('model').mean().to_dict();metrics[label]={'mse':mm,'B4_vs_B2_gain_percent':100*(mm['B2_family_mean']-mm['B4_activity_knn'])/mm['B2_family_mean'],'B4_vs_B3_gain_percent':100*(mm['B3_family_global_activity']-mm['B4_activity_knn'])/mm['B3_family_global_activity']}
rng=np.random.default_rng(20261024);base=units.pivot(index=['donor_id','family_pair'],columns='model',values=['coupled_mse','disjoint_mse']);ds=sorted(units.donor_id.unique());fs=sorted(units.family_pair.unique());di=base.index.get_level_values(0).map({x:i for i,x in enumerate(ds)}).to_numpy();fi=base.index.get_level_values(1).map({x:i for i,x in enumerate(fs)}).to_numpy();boots={'coupled_B4_vs_B2':[],'disjoint_B4_vs_B2':[],'coupled_B4_vs_B3':[],'disjoint_B4_vs_B3':[]}
for _ in range(1000):
 dw=rng.multinomial(len(ds),np.full(len(ds),1/len(ds)));fw=rng.multinomial(len(fs),np.full(len(fs),1/len(fs)));den=np.bincount(fi,weights=dw[di],minlength=len(fs));ok=(den>0)&(fw>0);den=np.maximum(den,1)
 for label in ['coupled_mse','disjoint_mse']:
  mm={name:float(np.sum(fw[ok]*np.bincount(fi,weights=dw[di]*base[(label,name)].to_numpy(),minlength=len(fs))[ok]/den[ok])/fw[ok].sum()) for name in names}
  for b,short in [('B2_family_mean','B2'),('B3_family_global_activity','B3')]:boots[label.removesuffix('_mse')+'_B4_vs_'+short].append(100*(mm[b]-mm['B4_activity_knn'])/mm[b])
out={'stage':'same_holdout_mechanistic_diagnostic','not_new_confirmation':True,'new_model_fits':0,'well_split_group_sizes_distribution':{str(k):int(v) for k,v in split_counts.items()},'excluded_points_missing_split_mono_support':excluded,'target_points':len(p)//2,'matrix_folds':len(matrix),'donors':len(ds),'family_pairs':len(fs),'metrics':metrics,'crossed_bootstrap_95':{k:np.quantile(v,[.025,.975]).tolist() for k,v in boots.items()},'algebraic_pairing_identity_max_absolute_error':float(max(gaps)),'predictor_reconstruction_max_errors':maxerr.tolist(),'interpretation':'Disjoint technical monotherapy wells remove direct reuse of the same single-agent measurement in input and label. Shared culture/control normalization remains; this cannot identify true causal interaction or create new biologicalreplicates.','registered_plan_sha256':hashlib.sha256((P/'CROSSNULL_DIAGNOSTIC_PLAN.json').read_bytes()).hexdigest()}
(P/'CROSSNULL_DIAGNOSTIC_RESULTS.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
