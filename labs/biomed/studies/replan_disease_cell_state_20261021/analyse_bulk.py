"""Fixed donor-level inference; regional pairs never treated as independent people."""
from bulk_io import *
from scipy.stats import beta,t,spearmanr
from itertools import combinations
SEED=20261021
B=2000

def interval(x):
 x=np.asarray(x,float);x=x[np.isfinite(x)]
 return np.quantile(x,[.025,.975]).tolist() if len(x) else None

def mean_ci(x,rng):
 x=np.asarray(x,float)
 if len(x)<2:return dict(mean=float(np.mean(x)) if len(x) else None,ci95=None,n=len(x))
 boot=x[rng.integers(len(x),size=(B,len(x)))].mean(axis=1)
 return dict(mean=float(x.mean()),ci95=interval(boot),n=len(x))

def cp(k,n):
 return [float(beta.ppf(.025,k,n-k+1)) if k else 0.,float(beta.ppf(.975,k+1,n-k)) if k<n else 1.]

def icc(groups):
 k=len(groups);n=sum(map(len,groups))
 if k<2 or n<=k:return np.nan
 sizes=np.array([len(g) for g in groups]);means=np.array([np.mean(g) for g in groups]);grand=np.dot(sizes,means)/n
 msb=np.sum(sizes*(means-grand)**2)/(k-1);msw=sum(np.sum((g-np.mean(g))**2) for g in groups)/(n-k)
 n0=(n-np.sum(sizes**2)/n)/(k-1);den=msb+(n0-1)*msw
 return float((msb-msw)/den) if den>0 else np.nan

def hc3(x,y,names):
 x=np.asarray(x,float);y=np.asarray(y,float)
 # Only all-constant nuisance columns are removable without changing column span.
 removed=[i for i in range(2,x.shape[1]) if np.ptp(x[:,i])==0]
 keep=[i for i in range(x.shape[1]) if i not in removed];x=x[:,keep];kept=[names[i] for i in keep]
 rank=int(np.linalg.matrix_rank(x));n=len(y)
 if rank<x.shape[1] or n<=rank+1:return dict(status='unavailable',reason='rank deficient or too few residual degrees of freedom',n=n,rank=rank,columns=kept,constant_nuisance_removed=[names[i] for i in removed])
 bread=np.linalg.inv(x.T@x);b=bread@x.T@y;res=y-x@b;lev=np.sum((x@bread)*x,axis=1)
 if np.max(lev)>=1-1e-10:return dict(status='unavailable',reason='HC3 leverage1',n=n)
 cov=bread@(x.T@((res/(1-lev))[:,None]**2*x))@bread
 se=float(np.sqrt(max(cov[1,1],0)));crit=t.ppf(.975,n-rank)
 return dict(status='estimated',n=n,disease_coefficient=float(b[1]),ci95=[float(b[1]-crit*se),float(b[1]+crit*se)],se=se,residual_df=n-rank,columns=kept,constant_nuisance_removed=[names[i] for i in removed],condition_number=float(np.linalg.cond(x)),max_leverage=float(lev.max()),interpretation='Conditional descriptive association; batch/unmeasured confounding unresolved')

def donor_frame(df):
 rows=[]
 for donor,g in df.groupby('donor_id'):
  assert g.diagnosis.nunique()==1
  assert g.age.dropna().nunique()<=1
  sexes=g.sex.astype(str).unique().tolist();conf=any('CONFLICT' in z for z in sexes) or len(sexes)!=1
  r=dict(donor_id=donor,diagnosis=g.diagnosis.iloc[0],age=g.age.iloc[0],sex=sexes[0] if not conf else 'CONFLICT',sex_conflict=conf,n_regions=len(g))
  for name in SCORE_NAMES:r[name]=float(g[name].mean())
  for extra in ['sample type','institution','batch','plate','ever_smoked']:
   if extra in g:
    assert g[extra].nunique(dropna=False)==1
    r[extra]=g[extra].iloc[0]
  rows.append(r)
 return pd.DataFrame(rows)

def analyse(acc):
 assert not (ART/f'{acc}_analysis.json').exists(),'Do not overwrite evidence'
 df=pd.read_csv(ART/f'{acc}_scores.csv');adult=df[df.eligible_adult].copy();primary=adult[adult.diagnosis.isin(['IPF','Control'])].copy()
 rng=np.random.default_rng(SEED);result=dict(at=now(),accession=acc,primary_adult_sample_count=len(primary),primary_adult_donors=primary.donor_id.nunique(),by_score={},seed=SEED,bootstrap_draws=B,paper_candidate=False,stage='exploratory_pilot',independent_unit='lung_donor');allpairs=[]
 donors=donor_frame(primary);donors.to_csv(ART/f'{acc}_donor_scores.csv',index=False)
 for name in SCORE_NAMES:
  threshold=.2 if name=='singscore_bidirectional' else .1 if name.startswith('singscore') else 1.
  entry=dict(regional_threshold=threshold,regional={},disease_effect={})
  for disease,g in adult.groupby('diagnosis'):
   per=[];groups=[]
   for donor,gd in g.groupby('donor_id'):
    if len(gd)<2:continue
    v=gd[name].to_numpy(float);groups.append(v)
    pairs=[]
    for i,j in combinations(range(len(v)),2):
     delta=float(abs(v[i]-v[j]));pairs.append(delta)
     allpairs.append(dict(accession=acc,donor_id=donor,diagnosis=disease,score=name,sample_a=gd.sample_id.iloc[i],sample_b=gd.sample_id.iloc[j],abs_difference=delta,exceeds_margin=delta>=threshold))
    pairs=np.array(pairs);per.append(dict(donor_id=donor,mean_absolute_difference=float(pairs.mean()),event_fraction=float((pairs>=threshold).mean()),range=float(np.ptp(v))))
   if not per:continue
   pp=pd.DataFrame(per);event=mean_ci(pp.event_fraction,rng);difference=mean_ci(pp.mean_absolute_difference,rng)
   ix=rng.integers(len(groups),size=(B,len(groups)))
   booticc=[icc([groups[i] for i in inds]) for inds in ix]
   reg=dict(donors=len(per),individual_donor_metrics=per,mean_pair_event_frequency=event,mean_absolute_pair_difference=difference,icc1=float(icc(groups)),icc1_ci95=interval(booticc),icc_note='One-way method-of-moments, may be negative; conditional on systematic regions sampled, not technical replicate reliability')
   if all(len(v)==2 for v in groups):
    k=int(pp.event_fraction.sum());reg['exact_pair_event']=dict(k=k,n=len(pp),proportion=k/len(pp),ci95=cp(k,len(pp)))
   if acc=='GSE199949':
    pivot=g.pivot(index='donor_id',columns='region',values=name).dropna();assert {'central','peripheral'}<=set(pivot)
    rho=spearmanr(pivot.central,pivot.peripheral).statistic
    reg['central_peripheral_spearman']=float(rho) if np.isfinite(rho) else None
    # Signed contrast includes regional direction, no adaptive region ordering.
    reg['peripheral_minus_central']=mean_ci((pivot.peripheral-pivot.central).to_numpy(),rng)
   entry['regional'][disease]=reg
  a=donors.loc[donors.diagnosis.eq('IPF'),name].to_numpy();b=donors.loc[donors.diagnosis.eq('Control'),name].to_numpy()
  boots=a[rng.integers(len(a),size=(B,len(a)))].mean(axis=1)-b[rng.integers(len(b),size=(B,len(b)))].mean(axis=1)
  se=np.sqrt(np.var(a,ddof=1)/len(a)+np.var(b,ddof=1)/len(b))
  aa=primary.loc[primary.diagnosis.eq('IPF'),name].to_numpy();bb=primary.loc[primary.diagnosis.eq('Control'),name].to_numpy()
  naive=np.sqrt(np.var(aa,ddof=1)/len(aa)+np.var(bb,ddof=1)/len(bb))
  entry['disease_effect']['unadjusted']=dict(difference=float(a.mean()-b.mean()),ci95=interval(boots),n_ipf=len(a),n_control=len(b),donor_mean_welch_se=float(se),naive_region_se=float(naive),donor_to_naive_se_ratio=float(se/naive),note='Naive region SE is a diagnostic baseline only, not valid independent-sample inference')
  if name.startswith('abundance_'):
   dd=donors[~donors.sex_conflict&donors.age.notna()].copy();male=dd.sex.str.lower().isin(['m','male']).astype(float)
   x=np.column_stack([np.ones(len(dd)),dd.diagnosis.eq('IPF').astype(float),(dd.age-dd.age.mean())/10,male]);names=['intercept','IPF','age_per10','male']
   entry['disease_effect']['age_sex_adjusted']=hc3(x,dd[name],names)
   if acc=='GSE150910':
    extra=pd.get_dummies(dd[['sample type','institution']],drop_first=True,dtype=float)
    entry['disease_effect']['age_sex_sampling_institution_adjusted']=hc3(np.column_stack([x,extra.to_numpy()]),dd[name],names+extra.columns.tolist())
  if acc=='GSE184316':
   slopes=[]
   for donor,g in adult[adult.diagnosis.eq('IPF')].groupby('donor_id'):
    xx=pd.to_numeric(g['surface density'],errors='coerce').to_numpy()/0.001;yy=g[name].to_numpy();valid=np.isfinite(xx)&np.isfinite(yy);xx=xx[valid];yy=yy[valid]
    if len(xx)<2 or np.ptp(xx)==0:continue
    slope=np.sum((xx-xx.mean())*(yy-yy.mean()))/np.sum((xx-xx.mean())**2);slopes.append(dict(donor_id=donor,slope=float(slope),n_regions=len(xx)))
   entry['within_donor_surface_density_slope']=dict(per_donor=slopes,summary=mean_ci([x['slope'] for x in slopes],rng),units='score units per0.001 surface-density increase; association only')
  result['by_score'][name]=entry
 if len(allpairs):pd.DataFrame(allpairs).to_csv(ART/f'{acc}_regional_pairs.csv',index=False)
 if acc=='GSE199949':
  e=result['by_score']['abundance_balance']['regional']['IPF']['exact_pair_event']
  result['primary_test']=dict(**e,null='frequency<=0.25',supported=e['ci95'][0]>.25,interpretation='Frozen pair-instability criterion; no clinical threshold claim; no composition or causal identification')
 elif acc=='GSE184316':
  result['primary_development']=result['by_score']['abundance_balance']['regional']['IPF']['mean_pair_event_frequency']
 # Prespecified assay floor diagnostic, reported without silently excluding donors.
 result['assay_floor']={p:dict(ipf_donors_with_any_region_over20pct_floor=int(primary[primary.diagnosis.eq('IPF')].groupby('donor_id')['floor_fraction_'+p].max().gt(.2).sum()),ipf_donors=int(primary[primary.diagnosis.eq('IPF')].donor_id.nunique())) for p in PLAN['programs']}
 atomic(ART/f'{acc}_analysis.json',result)
 print(acc,json.dumps(result.get('primary_test',result.get('primary_development',{}))))
 return result

if __name__=='__main__':
 for acc in sys.argv[1:]:analyse(acc)
