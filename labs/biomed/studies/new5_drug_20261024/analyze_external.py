from pathlib import Path
import json,zipfile,hashlib,datetime,sys,collections
import numpy as np,pandas as pd
from scipy.stats import spearmanr
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
plan=json.loads((P/'EXTERNAL_PLAN_FROZEN.json').read_text());metadata=json.loads((P/'EXTERNAL_METADATA_QUALIFICATION.json').read_text());assert hashlib.sha256((A/'external-frozen-points-metadata.csv').read_bytes()).hexdigest()==plan['target']['point_metadata_sha256']
if (P/'EXTERNAL_CONFIRMATION_OPENED.json').exists():raise RuntimeError('External confirmation already opened. Reconstruct saved outputs; no retuning/re-fitting exposed target.')
s=pd.read_csv(A/'source-points-technical-averages.csv');reconstruction=json.loads((P/'SOURCE_POINT_RECONSTRUCTION.json').read_text());assert hashlib.sha256((A/'source-points-technical-averages.csv').read_bytes()).hexdigest()==reconstruction['source_points_sha256']
familymean=s.groupby(['family_pair','MASTER_CELL_ID']).empirical_bliss.mean().groupby('family_pair').mean().to_dict();globalmean=float(np.mean(list(familymean.values())))
def record(family,e1,e2):return {'family':family,'e1':e1,'e2':e2,'e1_squared':e1**2,'e2_squared':e2**2,'e_product':e1*e2}
records=[record(r.family_pair,r.e1,r.e2) for r in s.itertuples()];dv=DictVectorizer(sparse=False);X=dv.fit_transform(records);sc=StandardScaler();X=sc.fit_transform(X)
npoints=s.groupby(['family_pair','MASTER_CELL_ID']).size();ncells=s.groupby('family_pair').MASTER_CELL_ID.nunique();weights=np.array([1/(npoints[(r.family_pair,r.MASTER_CELL_ID)]*ncells[r.family_pair]) for r in s.itertuples()]);weights*=len(s)/weights.sum();reg=Ridge(alpha=10);reg.fit(X,s.empirical_bliss,sample_weight=weights)
pd.DataFrame({'feature':dv.get_feature_names_out(),'coefficient_standardized':reg.coef_,'center':sc.mean_,'scale':sc.scale_}).to_csv(A/'external-B3-source-model.csv',index=False)
(A/'external-B3-intercept.json').write_text(json.dumps({'intercept':float(reg.intercept_),'global_mean':globalmean,'family_means':familymean},indent=2)+'\n')
sourcegroups={}
for (fam,cell),g in s.groupby(['family_pair','MASTER_CELL_ID']):sourcegroups.setdefault(fam,[]).append((cell,g))
def predict_knn(fam,e1,e2,c1,c2,mode,fallback):
 estimates=[]
 for cell,g in sourcegroups[fam]:
  if mode=='activity':dist=np.hypot(g.e1.to_numpy()-e1,g.e2.to_numpy()-e2);resp=g.empirical_bliss.to_numpy();radius=.20
  elif mode=='fitted':dist=np.hypot(g.fitted_e1.to_numpy()-e1,g.fitted_e2.to_numpy()-e2);resp=g.fitted_bliss.to_numpy();radius=.20
  else:dist=np.hypot(np.log10(g.conc1.to_numpy())-np.log10(c1),np.log10(g.conc2.to_numpy())-np.log10(c2));resp=g.empirical_bliss.to_numpy();radius=.5
  md=float(dist.min())
  if md<=radius:estimates.append((md,cell,float(resp[np.abs(dist-md)<=1e-10].mean())))
 estimates.sort(key=lambda t:(t[0],t[1]));estimates=estimates[:5]
 return (float(np.mean([v[2] for v in estimates])),len(estimates)) if len(estimates)>=3 else (fallback,len(estimates))
source_identity=json.loads((P/'EXTERNAL_CHEMICAL_QUALIFICATION.json').read_text());same_parent={r['target_name']:r['source_name'] for r in source_identity['compound_matches'] if r['same_parent_isomeric_structure']}
source_pair_by_family={fam:set(g.chemical_pair) for fam,g in s.groupby('family_pair')}
(P/'EXTERNAL_CONFIRMATION_OPENED.json').write_text(json.dumps({'opened_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan_sha256':hashlib.sha256((P/'EXTERNAL_PLAN_FROZEN.json').read_bytes()).hexdigest(),'analysis_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'one_shot':True,'source_model_frozen_before_target_response_read':True},indent=2)+'\n')
# Long-format rows repeat the same measured well once per administered drug.
points=pd.read_csv(A/'external-frozen-points-metadata.csv');points['key']=points.Sample.astype(str)+'|'+points.plate.astype(str)+'|'+points.well.astype(str);assert not points.key.duplicated().any()
sel=pd.read_csv(A/'external-selected-treatment-metadata.csv');mono=sel[sel.n_treatments==1].copy();mono['key']=mono.Sample.astype(str)+'|'+mono['Destination Plate Barcode'].astype(str)+'|'+mono['Destination Well'].astype(str);keys=set(points.key)|set(mono.key)
f=next((A/'melanoma2026-media-supp15').glob('*.zip'));manifest=json.loads((A/'melanoma2026-media-supp15/manifest.json').read_text());assert hashlib.sha256(f.read_bytes()).hexdigest()==manifest['sha256'];z=zipfile.ZipFile(f);parts=[]
for chunk in pd.read_csv(z.open('data.csv'),usecols=['Sample','Destination Plate Barcode','Destination Well','Combination ID','Drug','Drug Concentration','Unit','CPS','Viability','Inhibition'],chunksize=100000):
 chunk['key']=chunk.Sample.astype(str)+'|'+chunk['Destination Plate Barcode'].astype(str)+'|'+chunk['Destination Well'].astype(str);chunk=chunk[chunk.key.isin(keys)];parts.append(chunk)
d=pd.concat(parts,ignore_index=True);d['Drug']=d.Drug.str.strip()
for c in ['CPS','Viability','Inhibition','Drug Concentration']:d[c]=pd.to_numeric(d[c],errors='coerce')
error=float(np.nanmax(np.abs((1-d.Viability)-d.Inhibition)));assert error<1e-8,error
duplicated_response=d.groupby('key')[['CPS','Viability','Inhibition']].nunique(dropna=False).max().max();assert duplicated_response==1,duplicated_response
raw_wells=d.drop_duplicates('key').set_index('key');mono_measure=d[d.key.isin(set(mono.key))].copy();assert mono_measure.Unit.eq('μM').all();mono_measure['clipped_inhibition']=mono_measure.Inhibition.clip(0,1)
monocurves={}
for (cell,drug),g in mono_measure.groupby(['Sample','Drug']):
 g=g.groupby('Drug Concentration')[['Inhibition','clipped_inhibition']].median().sort_index();monocurves[(cell,drug)]=g
def interpolate(cell,drug,conc,unclipped=False):
 g=monocurves.get((cell,drug));col='Inhibition' if unclipped else 'clipped_inhibition'
 if g is None:return np.nan,'missing_curve'
 g=g[np.isfinite(g[col])&np.isfinite(g.index)&(g.index>0)];xx=g.index.to_numpy();yy=g[col].to_numpy()
 if not len(xx):return np.nan,'empty_curve'
 match=np.isclose(xx,conc,rtol=1e-6,atol=1e-9)
 if match.any():return float(np.median(yy[match])),'exact'
 if conc<xx.min() or conc>xx.max():return np.nan,'outside_support'
 return float(np.interp(np.log10(conc),np.log10(xx),yy)),'interpolated'
out=[];exclusions=collections.Counter();monomatch=collections.Counter()
for r in points.itertuples():
 if r.key not in raw_wells.index:exclusions['missing_combo_well']+=1;continue
 wr=raw_wells.loc[r.key];e12=float(wr.Inhibition)
 e1,h1=interpolate(r.Sample,r.drug1,r.conc1);e2,h2=interpolate(r.Sample,r.drug2,r.conc2);monomatch[h1]+=1;monomatch[h2]+=1
 if not np.isfinite([e12,e1,e2]).all():exclusions['nonfinite_or_unsupported_monotherapy']+=1;continue
 e1raw,_=interpolate(r.Sample,r.drug1,r.conc1,True);e2raw,_=interpolate(r.Sample,r.drug2,r.conc2,True);y=np.clip(e12,0,1)-e1-e2+e1*e2;yr=e12-e1raw-e2raw+e1raw*e2raw
 b3=float(reg.predict(sc.transform(dv.transform([record(r.family_pair,e1,e2)])))[0]);b4,n4=predict_knn(r.family_pair,e1,e2,r.conc1,r.conc2,'activity',b3);b5,n5=predict_knn(r.family_pair,e1,e2,r.conc1,r.conc2,'fitted',b3);b6,n6=predict_knn(r.family_pair,e1,e2,r.conc1,r.conc2,'dose',b3)
 same=False
 if r.drug1 in same_parent and r.drug2 in same_parent:
  cp='|'.join(sorted([same_parent[r.drug1].lower(),same_parent[r.drug2].lower()]));same=cp in source_pair_by_family[r.family_pair]
 out.append({'Sample':r.Sample,'family_pair':r.family_pair,'drug1':r.drug1,'drug2':r.drug2,'conc1':r.conc1,'conc2':r.conc2,'plate':r.plate,'well':r.well,'key':r.key,'e1':e1,'e2':e2,'combo_inhibition_raw':e12,'empirical_bliss':y,'unclipped_bliss':yr,'B0_zero':0.,'B1_global_mean':globalmean,'B2_family_mean':familymean[r.family_pair],'B3_family_global_activity':b3,'B4_activity_knn':b4,'B5_fitted_null_knn':b5,'B6_concentration_knn':b6,'activity_neighbors':n4,'fitted_neighbors':n5,'concentration_neighbors':n6,'same_parent_chemical_pair':same,'monotherapy1_match':h1,'monotherapy2_match':h2})
print('Frozen target points predicted; no parameter search.',len(out),flush=True)
p=pd.DataFrame(out);p.to_csv(A/'external-point-predictions.csv',index=False);names=list(plan['models']);aggcols=['empirical_bliss','unclipped_bliss',*names];g=p.groupby(['Sample','family_pair','conc1','conc2'],as_index=False)[aggcols].mean();cnt=g.groupby(['Sample','family_pair']).size();eligible=cnt[cnt>=12].index
matrix=g.set_index(['Sample','family_pair']).loc[eligible].reset_index().groupby(['Sample','family_pair'],as_index=False)[aggcols].mean();matrix=matrix.merge(cnt.rename('n_points').reset_index(),on=['Sample','family_pair']);same=p.groupby(['Sample','family_pair']).same_parent_chemical_pair.all().rename('same_parent_chemical_pair').reset_index();matrix=matrix.merge(same,on=['Sample','family_pair'])
identities=pd.read_csv(P/'external-cell-identities-frozen.csv',keep_default_na=False);identities['overlap_donor']=identities.groupby('donor_id').source_name_or_alias_overlap.transform('any');matrix=matrix.merge(identities,left_on='Sample',right_on='raw_name',how='left',validate='many_to_one');assert matrix.donor_id.notna().all();matrix.to_csv(A/'external-matrix-predictions.csv',index=False)
tumor=matrix[matrix.is_melanoma.astype(bool)].copy();unit=tumor.groupby(['donor_id','family_pair'],as_index=False)[aggcols].mean();assert unit.family_pair.nunique()>=8 and unit.donor_id.nunique()>=15,(unit.family_pair.nunique(),unit.donor_id.nunique());unit.to_csv(A/'external-donor-family-predictions.csv',index=False)
def evaluate(frame,label='empirical_bliss'):
 ans={}
 for n in names:
  loss=(frame[n]-frame[label])**2;ans[n]={'family_donor_balanced_mse':float(loss.groupby(frame.family_pair).mean().mean()),'family_donor_balanced_mae':float((frame[n]-frame[label]).abs().groupby(frame.family_pair).mean().mean()),'spearman':float(spearmanr(frame[n],frame[label]).statistic) if frame[n].nunique()>1 else 0.}
 return ans
metrics=evaluate(unit);sensitivity={'unclipped_target_endpoint_fixed_predictions':evaluate(unit,'unclipped_bliss')};
for label,subset in [('same_chemical',tumor[tumor.same_parent_chemical_pair]),('substituted_family',tumor[~tumor.same_parent_chemical_pair]),('name_or_donor_overlap',tumor[tumor.overlap_donor]),('name_nonoverlap',tumor[~tumor.overlap_donor]),('healthy_immortalized',matrix[~matrix.is_melanoma.astype(bool)]),('complete_16_points',tumor[tumor.n_points==16])]:
 if len(subset):
  u=subset.groupby(['donor_id','family_pair'],as_index=False)[aggcols].mean();sensitivity[label]={'donors':u.donor_id.nunique(),'families':u.family_pair.nunique(),'units':len(u),'metrics':evaluate(u)}
rng=np.random.default_rng(20261024);families=sorted(unit.family_pair.unique());donors=sorted(unit.donor_id.unique());fi=unit.family_pair.map({v:i for i,v in enumerate(families)}).to_numpy();di=unit.donor_id.map({v:i for i,v in enumerate(donors)}).to_numpy();Nf=len(families);Nd=len(donors);comparisons=[('B4_activity_knn','B2_family_mean'),('B4_activity_knn','B3_family_global_activity'),('B4_activity_knn','B0_zero'),('B4_activity_knn','B5_fitted_null_knn')];bootstrap={a+'__vs__'+b:[] for a,b in comparisons}
for _ in range(1000):
 fw=rng.multinomial(Nf,np.full(Nf,1/Nf));dw=rng.multinomial(Nd,np.full(Nd,1/Nd));den=np.bincount(fi,weights=dw[di],minlength=Nf);valid=(den>0)&(fw>0);den=np.maximum(den,1);losses={n:float(np.sum(fw[valid]*np.bincount(fi,weights=dw[di]*(unit[n]-unit.empirical_bliss)**2,minlength=Nf)[valid]/den[valid])/fw[valid].sum()) for n in names}
 for a,b in comparisons:bootstrap[a+'__vs__'+b].append(100*(losses[b]-losses[a])/losses[b])
contrasts={}
for a,b in comparisons:
 k=a+'__vs__'+b;ma=metrics[a]['family_donor_balanced_mse'];mb=metrics[b]['family_donor_balanced_mse'];contrasts[k]={'relative_mse_gain_percent':100*(mb-ma)/mb,'crossed_donor_family_bootstrap_95':np.quantile(bootstrap[k],[.025,.975]).tolist()}
(A/'external-bootstrap.json').write_text(json.dumps(bootstrap)+'\n')
influence=[]
for family in sorted(set('|'.join(families).split('|'))):
 keep=unit[~unit.family_pair.str.split('|').map(lambda q:family in q)];mm=evaluate(keep);influence.append({'removed_target_family':family,'remaining_pairs':keep.family_pair.nunique(),'B4_vs_B3_gain_percent':100*(mm['B3_family_global_activity']['family_donor_balanced_mse']-mm['B4_activity_knn']['family_donor_balanced_mse'])/mm['B3_family_global_activity']['family_donor_balanced_mse']})
coverage=p.assign(activity_qualified=p.activity_neighbors>=3).groupby('family_pair').agg(points=('key','size'),activity_qualified_fraction=('activity_qualified','mean'),max_drug1_uM=('conc1','max'),max_drug2_uM=('conc2','max'));coverage.to_csv(A/'external-activity-support.csv')
result={'stage':'exploratory_pilot','research_question':plan['research_question'],'metrics':metrics,'contrasts':contrasts,'sensitivity':sensitivity,'leave_target_family_out_influence':influence,'counts':{'raw_target_rows_selected':len(d),'candidate_combination_points':len(points),'retained_points':len(p),'eligible_matrices':len(matrix),'tumor_matrices':len(tumor),'tumor_donors':Nd,'family_pairs':Nf,'donor_family_units':len(unit),'raw_samples':d.Sample.nunique()},'exclusions':dict(exclusions),'monotherapy_dose_matches':dict(monomatch),'response_integrity':{'one_minus_viability_vs_inhibition_max_error':error,'max_distinct_response_per_duplicate_drug_long_row_well':int(duplicated_response)},'activity_support_fraction':float((p.activity_neighbors>=3).mean()),'fixed_configurations':7,'qualified_as_zone2_paper':False,'limitations':['Target intendedfamily mapping is not full targetprofile equivalence; only3 sameparentchemicalpairs.','One independent external laboratory, overlapping cell lines and related xenograft derivatives; donor groups merged conservatively.','Only11pairfamilies and7drugnodes; bootstrap assumes familyclusters and cannot create independentmechanisms.','Source observedmonotherapy values and target medians/within-rangeinterpolation are imperfect and noisy; interaction outcomes share monotherapynull uncertainty with conditionalfeatures.','Targetcombination wells single biologicalmeasurement; numericalhashes and donorresampling do not substitute independent culture replicates.','Actual rawCSV22cellnames differs article25initial/23qualityreported andAUCtable23; onlyactual frozenuploadedrows analyzed, not inventedmissingdata.','Sameactive-parent names/SMILES qualification does not authenticate vial contents, saltmolarity, off-targetaction or targetengagement.','One immortalized normalmelanocyte line cannot establish toxicityor clinicaltherapeuticwindow.','No head-to-head fullSOTA molecular model or broadexternal clinicalvalidation; positivepilot wouldnot prove Zone2readiness.','Targetresponse opened once underfrozenprotocol; no subsequent methodselection on thisholdout.'],'run':{'command':str(sys.executable)+' '+str(Path(__file__)),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'plan_sha256':hashlib.sha256((P/'EXTERNAL_PLAN_FROZEN.json').read_bytes()).hexdigest(),'seed':20261024},'completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(P/'EXTERNAL_RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps({'counts':result['counts'],'contrasts':contrasts,'activity_support_fraction':result['activity_support_fraction'],'monotherapy_dose_matches':result['monotherapy_dose_matches']},indent=2))
