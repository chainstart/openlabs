"""Frozen bounded context-transfer analysis; prospective test opening is single-use."""
from common import *
for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[k]='2'
import numpy as np,pandas as pd,itertools,csv,gzip,sys,joblib
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from scipy.stats import spearmanr,pearsonr
from threadpoolctl import threadpool_info
SEED=20261021
rc=lambda s:s.translate(str.maketrans('ACGT','TGCA'))[::-1]

def check():
 assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
 for n,h in json.loads((PROJECT/'freeze-hashes.json').read_text()).items():assert sha(PROJECT/n)==h,n
 for n,h in json.loads((PROJECT/'code-freeze.json').read_text()).items():assert sha(CODE/n)==h,n
 assert all(x['num_threads']<=2 for x in threadpool_info())

def read_context(context,ids):
 tag={'MYC':'-pmyc-','GAPDH':'-pgapdh-','APOBEC3F':'-papobec3f-'}[context]
 p=next(x for x in (ART/'intakes').glob('*/data.tsv.gz') if tag in x.parent.name)
 m=json.loads((p.parent/'manifest.json').read_text());assert sha(p)==m['sha256']
 wanted={x:i for i,x in enumerate(ids)};v=np.full((len(ids),2,2),np.nan);dna=v.copy();seen=set()
 with gzip.open(p,'rt') as f:
  for r in csv.DictReader(f,delimiter='\t'):
   element,o=r['Element'].rsplit('.',1)
   if element not in wanted or o not in ['fwd','rev']:continue
   assert r['Element'] not in seen;seen.add(r['Element']);i=wanted[element];j=['fwd','rev'].index(o)
   for rep in range(2):
    d=float(r['DNA'+str(rep+1)]);rna=float(r['RNA'+str(rep+1)]);dna[i,rep,j]=d
    if d>0 and rna>0 and np.isfinite(d+rna):v[i,rep,j]=np.log2(rna/d)
 good=np.isfinite(v).all(axis=(1,2));return v,dna,good

def seq_features(samples):
 m=json.loads((PROJECT/'design-metadata.json').read_text())['sequences'];ks=[''.join(t) for k in [1,2,3] for t in itertools.product('ACGT',repeat=k)]
 f=[];a=[]
 for x in samples.sample_id:
  s=m[x];r=rc(s);L=len(s)
  f.append([sum(b in 'GC' for b in s)/L,s.count('CG')/(L-1),np.log(L)])
  a.append([(sum(s[i:i+len(k)]==k for i in range(L-len(k)+1))-sum(r[i:i+len(k)]==k for i in range(L-len(k)+1)))/(L-len(k)+1) for k in ks])
 return np.array(f),np.array(a)

def features(v,dna,seq,anti):
 contrasts=v[:,:,0]-v[:,:,1];delta=contrasts.mean(axis=1);avg=v.mean(axis=(1,2));sd=contrasts.std(axis=1,ddof=1)
 act=np.column_stack([avg,avg**2]);nu=np.column_stack([act,seq,sd,np.log1p(dna.min(axis=(1,2)))]);full=np.column_stack([nu,delta,delta*avg])
 return dict(activity=act,nuisance=nu,delta=delta[:,None],full=full,anti=anti,fullseq=np.column_stack([full,anti]))
KEY={'activity_ridge':'activity','nuisance_ridge':'nuisance','nuisance_hgb':'nuisance','delta_ridge':'delta','full_ridge':'full','full_hgb':'full','antisym_seq':'anti','full_plus_seq':'fullseq'}
def fit(f,y):
 models={'zero':0.,'median':float(np.median(y)),'identity_delta':None}
 for name,key in KEY.items():
  if name.endswith('hgb'):m=HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=7,min_samples_leaf=20,l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=SEED)
  else:m=make_pipeline(StandardScaler(with_mean=name!='antisym_seq'),Ridge(alpha=10,fit_intercept=name!='antisym_seq'))
  models[name]=m.fit(f[key],y)
 return models

def predict(models,f):
 return {n:(np.full(len(f['delta']),m) if isinstance(m,float) else f['delta'][:,0].copy() if n=='identity_delta' else m.predict(f[KEY[n]])) for n,m in models.items()}

def metrics(y,p):
 return dict(mse=float(np.mean((y-p)**2)),mae=float(np.mean(abs(y-p))),pearson=float(pearsonr(y,p).statistic) if np.std(p)>1e-12 and np.std(y)>1e-12 else None,spearman=float(spearmanr(y,p).statistic) if np.std(p)>1e-12 and np.std(y)>1e-12 else None,sign_concordance=float(np.mean(np.sign(y)==np.sign(p))))

def boot(y,b,p,groups,n=2000):
 unique=np.unique(groups);eb=(y-b)**2;ep=(y-p)**2
 sums=np.array([[sum(eb[groups==g]),sum(ep[groups==g]),sum(groups==g)] for g in unique]);rng=np.random.default_rng(SEED);out=[]
 for _ in range(n):
  s=sums[rng.integers(0,len(unique),len(unique))].sum(axis=0);out.append([(s[0]-s[1])/s[2],1-s[1]/s[0]])
 a=np.array(out)
 return dict(groups=len(unique),n_bootstrap=n,absolute_improvement_ci95=np.quantile(a[:,0],[.025,.975]).tolist(),relative_improvement_ci95=np.quantile(a[:,1],[.025,.975]).tolist())

def select():
 check();assert not (PROJECT/'frozen-selection.json').exists()
 status('training_validation','Plan/sample/splits/code frozen; independent study blocked by insert identity','Fit eleven fixed configurations on MYC→GAPDH train/validation')
 s=pd.read_csv(PROJECT/'samples.csv');s=s[s.split!='test'].reset_index(drop=True);seq,anti=seq_features(s)
 x,d,g=read_context('MYC',list(s.sample_id));y,_,h=read_context('GAPDH',list(s.sample_id));good=g&h;tr=(s.split=='train').to_numpy()&good;va=(s.split=='validation').to_numpy()&good
 assert tr.sum()>=50 and va.sum()>=20
 f=features(x,d,seq,anti);target=(y[:,:,0]-y[:,:,1]).mean(axis=1);models=fit({k:v[tr] for k,v in f.items()},target[tr]);vm={k:metrics(target[va],p) for k,p in predict(models,{k:v[va] for k,v in f.items()}).items()}
 bn=['zero','median','activity_ridge','nuisance_ridge','nuisance_hgb'];on=['identity_delta','delta_ridge','full_ridge','full_hgb','full_plus_seq'];b=min(bn,key=lambda n:vm[n]['mse']);o=min(on,key=lambda n:vm[n]['mse'])
 joblib.dump(models,ART/'models.joblib')
 residual_s=make_pipeline(StandardScaler(),Ridge(alpha=10)).fit(f['nuisance'][tr],f['delta'][tr,0]);residual_t=make_pipeline(StandardScaler(),Ridge(alpha=10)).fit(f['nuisance'][tr],target[tr]);joblib.dump((residual_s,residual_t),ART/'residual-models.joblib')
 # Exact mathematical sequence-model symmetry verified on training features only.
 sm=models['antisym_seq'];sym=float(np.max(np.abs(sm.predict(anti[tr])+sm.predict(-anti[tr]))));assert sym<1e-10
 atomic(PROJECT/'software-check.json',dict(antisymmetry_max_error=sym,threadpools=threadpool_info()))
 atomic(PROJECT/'trial-ledger.json',[dict(configuration=n,status='completed',seed=SEED,n_train=int(tr.sum()),n_validation=int(va.sum()),validation=vm[n],test_opened=False) for n in json.loads((PROJECT/'plan.json').read_text())['baselines']])
 atomic(PROJECT/'frozen-selection.json',dict(time=now(),baseline=b,orientation=o,validation_metrics=vm,models_sha256=sha(ART/'models.joblib'),train_source_activity_quantiles=np.quantile(f['activity'][tr,0],[1/3,2/3]).tolist(),train_precision_median=float(np.median(f['nuisance'][tr,-2])),qc=dict(n_train=int(tr.sum()),n_validation=int(va.sum()),excluded=int((~good).sum()))))
 print('SELECTION',b,o,vm[b],vm[o],flush=True)

def confirm():
 check();assert not (PROJECT/'confirmation.started.json').exists(),'One opening only'
 selection=json.loads((PROJECT/'frozen-selection.json').read_text());assert sha(ART/'models.joblib')==selection['models_sha256']
 atomic(PROJECT/'confirmation.started.json',dict(time=now(),selection_sha256=sha(PROJECT/'frozen-selection.json'),scope='test loci MYC/GAPDH/APOBEC3F, context confirmation only'))
 status('context_confirmation','Eleven configurations selected on train/validation only','One opening of disjoint test loci and frozen controls')
 s=pd.read_csv(PROJECT/'samples.csv');s=s[s.split=='test'].reset_index(drop=True);seq,anti=seq_features(s)
 # Joint positivity QC makes paired same-mapping/context stress comparison matched.
 contexts={c:read_context(c,list(s.sample_id)) for c in ['MYC','GAPDH','APOBEC3F']};good=np.logical_and.reduce([v[2] for v in contexts.values()]);s=s[good].reset_index(drop=True);seq=seq[good];anti=anti[good]
 contexts={c:(v[0][good],v[1][good]) for c,v in contexts.items()};models=joblib.load(ART/'models.joblib');b=selection['baseline'];o=selection['orientation'];groups=s.homology_group.to_numpy();results={};preds=s.copy()
 for label,source,target in [('primary_context_transfer','GAPDH','APOBEC3F'),('same_mapping','MYC','GAPDH')]:
  x,d=contexts[source];v,_=contexts[target];f=features(x,d,seq,anti);y=(v[:,:,0]-v[:,:,1]).mean(axis=1);p=predict(models,f);met={k:metrics(y,z) for k,z in p.items()};ci=boot(y,p[b],p[o],groups)
  results[label]=dict(source=source,target=target,n=len(s),blocks=int(s.block_id.nunique()),groups=len(set(groups)),metrics=met,relative_mse_improvement=1-met[o]['mse']/met[b]['mse'],bootstrap=ci)
  preds[label+'_observed']=y
  for k,z in p.items():preds[label+'_'+k]=z
  if label=='primary_context_transfer':
   primary=(y,f,p)
   strata={}
   av=f['activity'][:,0];prec=f['nuisance'][:,-2]
   for n,mask in [('proximal',(s.proximity=='Proximal').to_numpy()),('distal',(s.proximity=='Distal').to_numpy()),('activity_low',av<=selection['train_source_activity_quantiles'][0]),('activity_high',av>selection['train_source_activity_quantiles'][1]),('precision_low',prec>selection['train_precision_median']),('precision_high',prec<=selection['train_precision_median'])]:
    if mask.sum():strata[n]=dict(n=int(mask.sum()),baseline=metrics(y[mask],p[b][mask]),orientation=metrics(y[mask],p[o][mask]),bootstrap=boot(y[mask],p[b][mask],p[o][mask],groups[mask]))
   results['strata']=strata
   rs,rt=joblib.load(ART/'residual-models.joblib');sr=f['delta'][:,0]-rs.predict(f['nuisance']);yr=y-rt.predict(f['nuisance'])
   results['activity_conditioned_residual_pearson']=float(pearsonr(sr,yr).statistic)
   results['replicate_contrast_sensitivity']=[dict(replicate=j+1,baseline=metrics(v[:,j,0]-v[:,j,1],p[b]),orientation=metrics(v[:,j,0]-v[:,j,1],p[o])) for j in range(2)]
   results['target_replicate_delta_pearson']=float(pearsonr(v[:,0,0]-v[:,0,1],v[:,1,0]-v[:,1,1]).statistic)
 # Conditional controls: transform source delta while preserving all nuisance values.
 y,f,p=primary;rng=np.random.default_rng(SEED);unique=np.unique(groups);gm=np.array([f['delta'][groups==g,0].mean() for g in unique]);ga=np.array([f['activity'][groups==g,0].mean() for g in unique]);ter=np.digitize(ga,np.quantile(ga,[1/3,2/3]));index={g:i for i,g in enumerate(unique)};ix=np.array([index[g] for g in groups]);controls={'signflip':[],'permutation_activity_tertiles':[]}
 def alter(newdelta):
  z={k:v.copy() for k,v in f.items()};z['delta']=newdelta[:,None];z['full'][:,-2]=newdelta;z['full'][:,-1]=newdelta*f['activity'][:,0];z['fullseq'][:,:z['full'].shape[1]]=z['full'];return predict({o:models[o]},z)[o]
 for _ in range(1000):
  flip=rng.choice([-1,1],len(unique));controls['signflip'].append(float(np.mean((y-alter(f['delta'][:,0]*flip[ix]))**2)))
  shuffled=gm.copy()
  for t in range(3):j=np.where(ter==t)[0];shuffled[j]=rng.permutation(gm[j])
  controls['permutation_activity_tertiles'].append(float(np.mean((y-alter(shuffled[ix]))**2)))
 atomic(ART/'control-trials.json',controls)
 results['controls']={k:dict(n=len(v),mse_quantiles=np.quantile(v,[.025,.5,.975]).tolist(),fraction_control_mse_le_observed=float(np.mean(np.array(v)<=results['primary_context_transfer']['metrics'][o]['mse']))) for k,v in controls.items()}
 results['sign_flipped_identity']=metrics(y,-f['delta'][:,0]);preds.to_csv(ART/'test-predictions.csv',index=False)
 primaryresult=results['primary_context_transfer'];positive=primaryresult['n']>=100 and primaryresult['groups']>=30 and primaryresult['relative_mse_improvement']>=.05 and primaryresult['bootstrap']['absolute_improvement_ci95'][0]>0
 out=dict(stage='exploratory_pilot',time=now(),independent_unit='DNA locus, not small molecule',selected_baseline=b,selected_orientation=o,metrics=results,trials_run=11,positive_context_pilot=positive,independent_study_validation=False,paper_candidate=False,qc_test_excluded=int((~good).sum()),limitations=['Single study, K562 cultures and one vector family; contexts are not independent studies','Most eligible elements are distal; promoter-activity endpoint is not a promoter-only panel','Coordinates/reference build and author forward-sequence mapping not independently resequenced','Limited two-replicate precision; bootstrap conditional on study and grouped loci','21mer homology screening is not exhaustive sequence alignment','Prospective within-system stress test is incremental; no causal RNA stability mechanism'],run=dict(command='OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/promoter_portability_20261021/run.py confirm',code_sha256=sha(CODE/'run.py'),environment_sha256=sha(PROJECT/'environment.json'),seed=SEED))
 atomic(PROJECT/'results.json',out);atomic(PROJECT/'confirmation.completed.json',dict(time=now(),results_sha256=sha(PROJECT/'results.json')))
 print(json.dumps(out,indent=2),flush=True)
 status('analysis_complete',dict(positive_context_pilot=positive,primary=primaryresult),'Independent-route audit and result validation/final report')

if __name__=='__main__':
 if sys.argv[1]=='select':select()
 elif sys.argv[1]=='confirm':confirm()
