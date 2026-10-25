"""One opening of frozen confirmation. All planned endpoints and methods retained."""
from models import *

ENDPOINTS=['target_fit_auc','target_raw_auc','target_raw_unclipped_auc']

def pair_error(x,y):
    prod=np.sign(x)*np.sign(y)
    return (prod<0).astype(float)+.5*(prod==0)

def cluster_bootstrap(df,values,second='depmap_id',nboot=2000,seed=20261021):
    """Paired pigeonhole bootstrap; equal drug weights, cell weights within drug."""
    drugs=pd.Categorical(df.structure_key);cells=pd.Categorical(df[second])
    nd,nc=len(drugs.categories),len(cells.categories)
    sums=np.zeros((nd,nc,values.shape[1]));counts=np.zeros((nd,nc))
    np.add.at(sums,(drugs.codes,cells.codes),values)
    np.add.at(counts,(drugs.codes,cells.codes),1)
    rng=np.random.default_rng(seed);out=[]
    for _ in range(nboot):
        wd=rng.multinomial(nd,np.full(nd,1/nd));wc=rng.multinomial(nc,np.full(nc,1/nc))
        den=counts@wc;good=den>0
        means=np.einsum('dcv,c->dv',sums,wc,optimize=True)[good]/den[good,None]
        if wd[good].sum()==0:continue
        out.append(np.average(means,axis=0,weights=wd[good]))
    return np.asarray(out)

def ranking(df,pred):
    records=[];abstain=[]
    for drug,g in df.groupby('structure_key',sort=True):
        g=g.sort_values('sample_id');ix=g.index.to_numpy();a,b=np.triu_indices(len(g),1)
        if not len(a):continue
        for end in ENDPOINTS:
            yy=g[end].to_numpy();delta=yy[a]-yy[b]
            for name in NAMES:
                pp=pred.loc[ix,name].to_numpy()
                records.append({'structure_key':drug,'endpoint':end,'method':name,'n_cells':len(g),'n_pairs':len(a),'error':float(pair_error(pp[a]-pp[b],delta).mean())})
        reps=g[[f'source_rep{r}_aut' for r in [1,2,3]]].to_numpy()
        ds=reps[a]-reps[b];valid=np.isfinite(ds)
        stable=(valid.sum(axis=1)>=2)&(np.all((ds>0)|~valid,axis=1)|np.all((ds<0)|~valid,axis=1))
        k=int(stable.sum());fit=g.source_fit_auc.to_numpy();dd=fit[a]-fit[b]
        match=np.zeros(len(a),bool);match[np.argsort(-abs(dd),kind='stable')[:k]]=True
        # Use the agreed sign of matched repeats, not unequal-replicate averages.
        agreed_sign=np.nansum(np.sign(ds),axis=1)
        yy=g.target_raw_auc.to_numpy();err_stable=pair_error(agreed_sign,yy[a]-yy[b]);err_match=pair_error(dd,yy[a]-yy[b])
        abstain.append({'structure_key':drug,'n_cells':len(g),'n_pairs':len(a),'retained_pairs':k,'coverage':k/len(a),'repeat_consistent_error':float(err_stable[stable].mean()) if k else None,'same_coverage_difference_error':float(err_match[match].mean()) if k else None})
    pd.DataFrame(records).to_csv(ART/'ranking-by-drug.csv',index=False)
    pd.DataFrame(abstain).to_csv(ART/'abstention-by-drug.csv',index=False)
    r=pd.DataFrame(records);summ={}
    for (method,end),g in r.groupby(['method','endpoint']):
        v=g.error.to_numpy();rng=np.random.default_rng(20261021)
        bs=np.array([rng.choice(v,size=len(v),replace=True).mean() for _ in range(2000)])
        summ.setdefault(method,{})[end]={'macro_drug_error':float(v.mean()),'drug_only_ci95':np.quantile(bs,[.025,.975]).tolist(),'n_drugs':len(v)}
    aa=pd.DataFrame(abstain).dropna();v=(aa.repeat_consistent_error-aa.same_coverage_difference_error).to_numpy()
    rng=np.random.default_rng(20261021)
    bs=np.array([rng.choice(v,len(v),replace=True).mean() for _ in range(2000)]) if len(v) else np.array([np.nan])
    absum={'macro_coverage':float(aa.coverage.mean()),'repeat_consistent_error':float(aa.repeat_consistent_error.mean()),'same_coverage_difference_error':float(aa.same_coverage_difference_error.mean()),'error_difference':float(v.mean()),'drug_only_ci95':np.quantile(bs,[.025,.975]).tolist(),'n_drugs':len(aa),'zero_coverage_drugs':len(abstain)-len(aa),'rule':'same sign in all mutually available source X replicates, >=2, no ties; difference comparator uses equal count within each drug; stable deterministic tie break by sample IDs','uncertainty_limitation':'drug-only intervals do not capture shared cells or plates'}
    # Drug rankings are meaningful here only within the same measured common-dose interval.
    within=[]
    for cell,g in df.groupby('depmap_id'):
        ix=g.index.to_numpy();a,b=np.triu_indices(len(g),1)
        eligible=np.isclose(g.common_lo.to_numpy()[a],g.common_lo.to_numpy()[b],rtol=0,atol=1e-6)&np.isclose(g.common_hi.to_numpy()[a],g.common_hi.to_numpy()[b],rtol=0,atol=1e-6)
        a,b=a[eligible],b[eligible]
        if not len(a):continue
        y=g.target_raw_auc.to_numpy()
        for name in NAMES:
            p=pred.loc[ix,name].to_numpy();within.append({'depmap_id':cell,'method':name,'n_pairs':len(a),'error':float(pair_error(p[a]-p[b],y[a]-y[b]).mean())})
    within=pd.DataFrame(within);within.to_csv(ART/'ranking-by-cell-matched-support.csv',index=False)
    return {'within_drug':summ,'abstention':absum,'within_cell_matched_support':within.groupby('method').error.mean().to_dict(),'within_cell_n_models':int(within.depmap_id.nunique()),'note':'Secondary descriptive endpoints; never replace primary. Drug-only rank CIs conditional on measured cell panel.'}

def evaluate():
    assert not (ART/'confirmation-opened.json').exists(),'Confirmation already opened; audit persisted outputs, never reopen silently'
    ledger=json.loads((DATA/'trial-ledger.json').read_text())
    assert hashlib.sha256((ART/'models.joblib').read_bytes()).hexdigest()==ledger['model_sha256']
    freeze=json.loads((DATA/'freeze-ledger.json').read_text())
    for f,h in freeze['files'].items():assert hashlib.sha256((DATA/f).read_bytes()).hexdigest()==h
    write(ART/'confirmation-opened.json',{'at_utc':now(),'opening':1,'model_sha256':ledger['model_sha256'],'plan_sha256':freeze['files']['plan-frozen.json'],'evaluate_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'validation_selected_tree':ledger['validation_selected_tree'],'primary':'hgb_full versus identity_fit; fit_gain - measured_gain','implementation_details':'rank consistency uses same-X matching >=2 available; ties count .5; cell drug rank limited to common endpoints within1e-6 log10; chosen before confirmation'})
    df=pd.read_csv(ART/'sealed/test-curves.csv.gz');models=joblib.load(ART/'models.joblib');pred=predict(df,models)
    pred.to_csv(ART/'confirmation-predictions.csv.gz',index=False)
    keys=[];v=[]
    for name in NAMES:
        for end in ENDPOINTS:
            keys.append(name+'::'+end);v.append(abs(pred[name].to_numpy()-df[end].to_numpy()))
    values=np.column_stack(v)
    means=pd.DataFrame(values).groupby(df.structure_key).mean().mean().to_numpy()
    boot=cluster_bootstrap(df,values);poolboot=cluster_bootstrap(df,values,second='target_pool')
    pd.DataFrame(boot,columns=keys).to_csv(ART/'bootstrap-primary.csv.gz',index=False)
    results={}
    for i,key in enumerate(keys):
        name,end=key.split('::');results.setdefault(name,{})[end]={'macro_drug_mae':float(means[i]),'two_way_ci95':np.quantile(boot[:,i],[.025,.975]).tolist(),'drug_pool_ci95':np.quantile(poolboot[:,i],[.025,.975]).tolist()}
    def gain(name,end):
        i=keys.index('identity_fit::'+end);j=keys.index(name+'::'+end)
        return means[i]-means[j],boot[:,i]-boot[:,j],poolboot[:,i]-poolboot[:,j]
    allgains={}
    for name in NAMES:
        fg,fb,fp=gain(name,'target_fit_auc');mg,mb,mp=gain(name,'target_raw_auc')
        allgains[name]={'fit_gain':float(fg),'fit_gain_ci95':np.quantile(fb,[.025,.975]).tolist(),'measured_gain':float(mg),'measured_gain_ci95':np.quantile(mb,[.025,.975]).tolist(),'misalignment':float(fg-mg),'misalignment_ci95':np.quantile(fb-mb,[.025,.975]).tolist(),'misalignment_drug_pool_ci95':np.quantile(fp-mp,[.025,.975]).tolist()}
    primary=allgains['hgb_full'];primary['material_misalignment_supported']=bool(primary['misalignment_ci95'][0]>.02 and primary['fit_gain']>0)
    primary['sign_reversal_supported']=bool(primary['fit_gain_ci95'][0]>0 and primary['measured_gain_ci95'][1]<0)
    # Same contrast without clipping the held-out measured repeat.
    fg,fb,fp=gain('hgb_full','target_fit_auc');ug,ub,up=gain('hgb_full','target_raw_unclipped_auc')
    sensitivity={'unclipped_measured_gain':float(ug),'unclipped_measured_gain_ci95':np.quantile(ub,[.025,.975]).tolist(),'unclipped_misalignment':float(fg-ug),'unclipped_misalignment_ci95':np.quantile(fb-ub,[.025,.975]).tolist()}
    fitrow=abs(pred.identity_fit-df.target_fit_auc)-abs(pred.hgb_full-df.target_fit_auc)
    rawrow=abs(pred.identity_fit-df.target_raw_auc)-abs(pred.hgb_full-df.target_raw_auc)
    row=df[['sample_id','structure_key','depmap_id','target_pool','target_plate']].copy();row['fit_gain']=fitrow;row['measured_gain']=rawrow;row['misalignment']=fitrow-rawrow
    row.to_csv(ART/'primary-row-contrasts.csv.gz',index=False)
    plate=[]
    for p in sorted(df.target_plate.unique()):
        sub=row[row.target_plate!=p]
        if len(sub):plate.append({'excluded_plate':p,**sub.groupby('structure_key')[['fit_gain','measured_gain','misalignment']].mean().mean().to_dict(),'remaining_drugs':sub.structure_key.nunique()})
    sensitivity['leave_one_target_compound_plate_out']=plate
    ranks=ranking(df,pred)
    out={'at_utc':now(),'stage':'exploratory_pilot','paper_candidate':False,'counts':{'test_pairs':len(df),'test_drugs':df.structure_key.nunique(),'test_cells':df.depmap_id.nunique(),'target_pools':df.target_pool.nunique(),'target_compound_plates':df.target_plate.nunique()},'primary':primary,'all_baselines':results,'all_gains_vs_identity_fit':allgains,'sensitivity':sensitivity,'ranking':ranks,'validation_selected_tree':ledger['validation_selected_tree'],'tree_range':{k:allgains[k] for k in ['hgb_full','rf_leaf5','rf_leaf20']},'trials_run':11,'seed':20261021,'confirmation_openings':1,'limitations':['Same Broad technical redo program, not independent laboratories','Source response available for every pair; not de novo new drug prediction','Held-out X3 is noisy measured response, not true biological effect','Shared compound plates and pools limit identity bootstrap independence','Complete-case control QC defines selected analysis population','3PL fitted over full source doses and integrated on common support; not an exact reproduction of published truncated-fit protocol']}
    write(ART/'confirmation-results.json',out);write(DATA/'confirmation-results.json',out)
    print(json.dumps({'counts':out['counts'],'primary':primary,'ranking_abstention':ranks['abstention']},indent=2),flush=True)

if __name__=='__main__':evaluate()
