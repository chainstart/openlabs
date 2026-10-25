from pathlib import Path
import json,hashlib,datetime,sys,math
import numpy as np,pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import ExtraTreesRegressor
from scipy.stats import spearmanr
R=Path('/home/biostar/work/projects/openlabs/openlabs');P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
plan=json.loads((P/'PLAN_FROZEN.json').read_text());assert hashlib.sha256((P/'samples-frozen.csv').read_bytes()).hexdigest()==plan['frozen_sample_sha256']
if (P/'CONFIRMATION_OPENED.json').exists():raise RuntimeError('Confirmation already opened; immutable predictions must be audited, not re-fit.')
(P/'CONFIRMATION_OPENED.json').write_text(json.dumps({'opened_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'analysis_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'protocol_sha256':hashlib.sha256((P/'PLAN_FROZEN.json').read_bytes()).hexdigest(),'one_shot':True},indent=2)+'\n')
frames=[]
for rec in json.loads((P/'intake-index.json').read_text()):
 f=Path(rec['dataset']['artifact_uri'].removeprefix('file://'));assert hashlib.sha256(f.read_bytes()).hexdigest()==rec['dataset']['sha256'];d=pd.read_csv(f);d['screen']=f.name.split('_matrix')[0];frames.append(d)
d=pd.concat(frames,ignore_index=True);d['pair']=d.apply(lambda r:'|'.join(sorted([str(r.lib1_name).lower(),str(r.lib2_name).lower()])),axis=1)
d['growth_numeric']=pd.to_numeric(d.growth_rate,errors='coerce')
gsource=d[['SIDM','screen','BARCODE','growth_numeric']].drop_duplicates().query('growth_numeric>0.25 and growth_numeric<8').groupby(['SIDM','screen']).growth_numeric.median()
cross={}
for (sid,screen),v in gsource.items():
 others=gsource.loc[sid];vals=others.loc[others.index!=screen];cross[(sid,screen)]=float(vals.median()) if len(vals) else np.nan
d['growth_cross']= [cross.get((sid,s),np.nan) for sid,s in zip(d.SIDM,d.screen)]
for c in ['lib1_MaxE','lib2_MaxE','lib1_RMSE','lib2_RMSE','Bliss_matrix','growth_cross','growth_numeric']:d[c]=pd.to_numeric(d[c],errors='coerce')
quality=pd.DataFrame({'missing_outcome_or_inputs':~np.isfinite(d[['lib1_MaxE','lib2_MaxE','Bliss_matrix','growth_cross','growth_numeric']]).all(axis=1),'growth_range':~d.growth_numeric.between(.25,8),'single_fit_rmse':(d[['lib1_RMSE','lib2_RMSE']].max(axis=1)>.3)|(~np.isfinite(d[['lib1_RMSE','lib2_RMSE']]).all(axis=1)),'monotherapy_max_range':~d.lib1_MaxE.between(-.1,1.1)|~d.lib2_MaxE.between(-.1,1.1)})
keep=~quality.any(axis=1);exclusions={'raw_rows':len(d),'excluded_any':int((~keep).sum()),'reasons_nonexclusive':quality.sum().astype(int).to_dict()};d=d.loc[keep].copy()
numcols=['lib1_MaxE','lib2_MaxE','lib1_RMSE','lib2_RMSE','lib1_minc','lib1_maxc','lib2_minc','lib2_maxc','growth_cross','growth_numeric','Bliss_matrix','HSA_matrix','combo_MaxE']
keys=['pair','SIDM','screen'];agg={c:'mean' for c in numcols};agg.update({c:'first' for c in ['TISSUE','CANCER_TYPE','lib1_name','lib2_name','lib1_pathway','lib2_pathway']});agg['BARCODE']='size'
d=d.groupby(keys,as_index=False).agg(agg).rename(columns={'BARCODE':'matrix_replicates'})
samples=pd.read_csv(P/'samples-frozen.csv');x=samples.merge(d,on=['pair','SIDM','screen'],how='left',suffixes=('','_source'),validate='one_to_one');missing=x.Bliss_matrix.isna();exclusions['frozen_sample_exclusions_by_split']=x.loc[missing].groupby('split').size().to_dict();x=x.loc[~missing].copy();x.to_csv(A/'analysis-units.csv',index=False)
counts=x.groupby('split').agg(rows=('sample_id','size'),cells=('SIDM','nunique'),pairs=('pair','nunique')).to_dict('index');assert counts['test']['pairs']>=10 and counts['test']['cells']>=40,counts
tr=x.split=='train';va=x.split=='validation';te=x.split=='test';y=x.Bliss_matrix.to_numpy()
def features(row,mode,growth_field='growth_cross'):
 e=sorted([row.lib1_MaxE,row.lib2_MaxE]);g=float(row[growth_field]);lo=sorted([np.log10(row.lib1_minc),np.log10(row.lib2_minc)]);hi=sorted([np.log10(row.lib1_maxc),np.log10(row.lib2_maxc)])
 drugs=sorted([str(row.lib1_name).lower(),str(row.lib2_name).lower()]);paths=sorted([str(row.lib1_pathway),str(row.lib2_pathway)])
 f={'e_min':e[0],'e_max':e[1],'e_product':e[0]*e[1],'e_difference':e[1]-e[0],'dose_low_min':lo[0],'dose_low_max':lo[1],'dose_high_min':hi[0],'dose_high_max':hi[1],'rmse_max':max(row.lib1_RMSE,row.lib2_RMSE),'tissue':str(row.TISSUE),'pathway_pair':'|'.join(paths)}
 for drug in drugs:f['drug='+drug]=1
 for p in paths:f['pathway='+p]=1
 if mode>=2:f.update({'growth':g,'growth_squared':g*g})
 if mode==3:
  for p in paths:f['pathway_growth='+p]=g
 if mode==4:
  for drug in drugs:f['drug_growth='+drug]=g
 return f
models={};pred={'M0_mean':np.full(len(x),y[tr].mean())};features_by_model={}
for name,mode,kind in [('M1_ridge',1,'ridge'),('M2_global_growth',2,'ridge'),('M3_pathway_growth',3,'ridge'),('M4_drug_growth',4,'ridge'),('M5_extra_trees_no_growth',1,'tree'),('M6_extra_trees_growth',3,'tree')]:
 records=[features(r,mode) for _,r in x.iterrows()];dv=DictVectorizer(sparse=False);Xtr=dv.fit_transform([r for r,t in zip(records,tr) if t]);X=dv.transform(records);im=SimpleImputer(strategy='median');Xtr=im.fit_transform(Xtr);X=im.transform(X);sc=StandardScaler();Xtr=sc.fit_transform(Xtr);X=sc.transform(X)
 model=Ridge(alpha=10) if kind=='ridge' else ExtraTreesRegressor(n_estimators=128,min_samples_leaf=20,max_features=1.0,n_jobs=2,random_state=20261024)
 model.fit(Xtr,y[tr]);pred[name]=model.predict(X);models[name]=(dv,im,sc,model,mode)
 if kind=='ridge':pd.DataFrame({'feature':dv.get_feature_names_out(),'coefficient_standardized':model.coef_}).to_csv(A/(name+'-coefficients.csv'),index=False)
print('Models fit. No tuning. Evaluating frozen validation/test.',flush=True)
for k,v in pred.items():x['pred_'+k]=v
x.to_csv(A/'predictions.csv',index=False)
metrics={};pair_losses={}
for split in ['train','validation','test']:
 z=x[x.split==split];m={};loss=pd.DataFrame(index=sorted(z.pair.unique()))
 for name in pred:
  err=(z['pred_'+name]-z.Bliss_matrix)**2;p=err.groupby(z.pair).mean();loss[name]=p;m[name]={'pair_weighted_mse':float(p.mean()),'row_weighted_mse':float(err.mean()),'pair_weighted_mae':float((z['pred_'+name]-z.Bliss_matrix).abs().groupby(z.pair).mean().mean()),'spearman':float(spearmanr(z['pred_'+name],z.Bliss_matrix).statistic) if name!='M0_mean' else 0.}
 metrics[split]=m;loss.to_csv(A/(split+'-pair-losses.csv'));pair_losses[split]=loss
z=x[x.split=='test'].copy();pairs=sorted(z.pair.unique());cells=sorted(z.SIDM.unique());pi={p:i for i,p in enumerate(pairs)};ci={p:i for i,p in enumerate(cells)};pp=z.pair.map(pi).to_numpy();cc=z.SIDM.map(ci).to_numpy();nP=len(pairs);nC=len(cells);rng=np.random.default_rng(20261024)
comps=[('M3_pathway_growth','M1_ridge'),('M3_pathway_growth','M2_global_growth'),('M6_extra_trees_growth','M5_extra_trees_no_growth'),('M4_drug_growth','M3_pathway_growth')];boots={a+'__vs__'+b:[] for a,b in comps}
for it in range(1000):
 pw=rng.multinomial(nP,np.full(nP,1/nP));cw=rng.multinomial(nC,np.full(nC,1/nC));den=np.bincount(pp,weights=cw[cc],minlength=nP);good=den>0;den=np.maximum(den,1)
 losses={name:float(np.sum(pw[good]*np.bincount(pp,weights=cw[cc]*(z['pred_'+name]-z.Bliss_matrix)**2,minlength=nP)[good]/den[good])/pw[good].sum()) for name in pred}
 for a,b in comps:boots[a+'__vs__'+b].append(100*(losses[b]-losses[a])/losses[b])
contrasts={}
for a,b in comps:
 k=a+'__vs__'+b;v=np.array(boots[k]);ma=metrics['test'][a]['pair_weighted_mse'];mb=metrics['test'][b]['pair_weighted_mse'];contrasts[k]={'relative_mse_improvement_percent':100*(mb-ma)/mb,'two_way_bootstrap_95_percent':np.quantile(v,[.025,.975]).tolist(),'bootstrap_replicates':len(v),'unit':'drug_pair and cell_line crossed bootstrap; same study, selected drug panel'}
(A/'bootstrap-relative-gains.json').write_text(json.dumps(boots)+'\n')
diagnostics=[]
for pair,g in z.groupby('pair'):
 diagnostics.append({'pair':pair,'n_cells':len(g),'mean_bliss':float(g.Bliss_matrix.mean()),'growth_bliss_spearman':float(spearmanr(g.growth_cross,g.Bliss_matrix).statistic),'M3_vs_M1_relative_gain_percent':100*(np.mean((g.pred_M1_ridge-g.Bliss_matrix)**2)-np.mean((g.pred_M3_pathway_growth-g.Bliss_matrix)**2))/np.mean((g.pred_M1_ridge-g.Bliss_matrix)**2)})
pd.DataFrame(diagnostics).to_csv(A/'test-pair-diagnostics.csv',index=False)
# Prespecified negative control: shuffle test cross-screen growth at cell-line level within tissue.
dv,im,sc,model,mode=models['M3_pathway_growth'];celltab=z[['SIDM','TISSUE','growth_cross']].drop_duplicates('SIDM');permutation=[]
for it in range(200):
 shuffled={}
 for tissue,g in celltab.groupby('TISSUE'):
  vals=rng.permutation(g.growth_cross.to_numpy());shuffled.update(dict(zip(g.SIDM,vals)))
 zz=z.copy();zz['growth_cross']=zz.SIDM.map(shuffled);X=dv.transform([features(r,mode) for _,r in zz.iterrows()]);pv=model.predict(sc.transform(im.transform(X)));err=pd.Series((pv-zz.Bliss_matrix.to_numpy())**2,index=zz.index);permutation.append(float(err.groupby(zz.pair).mean().mean()))
observed=metrics['test']['M3_pathway_growth']['pair_weighted_mse'];negative={'within_tissue_cell_growth_permutations':200,'observed_mse':observed,'permuted_mse_mean':float(np.mean(permutation)),'fraction_permuted_mse_le_observed_plusone':float((1+sum(t<=observed for t in permutation))/201),'interpretation':'feature dependence diagnostic, not causal randomization or biological independence'}
limitations=['One upstream Sanger/AstraZeneca study; held-out screen does not establish cross-laboratory replication.','Only selected 37 compounds/109 pairs; exact same-name cross-DrugID chemical identity not independently verified.','Monotherapy effects and untreated control growth measured during the assay are conditional inputs, not pre-assay molecular discovery.','Shared day4 normalization can induce statistical dependencies despite use of other-screen growth features.','Technical matrix repeats are collapsed within biological cell-line/drug-pair units; cell lines recur across pairs.','No patient/normal tissue/toxicity outcomes; no clinical efficacy, therapeutic window or causal mechanism inferred.','Growth-rate effects and synergy benchmarking are established; this pilot alone does not meet Zone2 novelty/evidence standards.','Source pathway label for Dasatinib varies by screen; retained as recorded, not mechanistic ground truth.','Validation and test evaluated once under frozen models; no further optimization on these holdouts.']
result={'stage':'exploratory_pilot','independent_unit':'cell_line','metrics':{'test_M3_pair_mse':metrics['test']['M3_pathway_growth']['pair_weighted_mse'],'test_M1_pair_mse':metrics['test']['M1_ridge']['pair_weighted_mse'],'test_rows':counts['test']['rows'],'test_cells':counts['test']['cells'],'test_pairs':counts['test']['pairs']},'baselines':{k:v for k,v in metrics['test'].items()},'all_metrics':metrics,'contrasts':contrasts,'negative_control':negative,'counts':counts,'exclusions':exclusions,'trials_run':7,'limitations':limitations,'run':{'command':str(sys.executable)+' '+str(Path(__file__)),'code_revision':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'seed':20261024,'environment_sha256':hashlib.sha256((P/'environment.json').read_bytes()).hexdigest(),'plan_sha256':hashlib.sha256((P/'PLAN_FROZEN.json').read_bytes()).hexdigest()},'completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(P/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps({'counts':counts,'contrasts':contrasts,'negative_control':negative},indent=2))
