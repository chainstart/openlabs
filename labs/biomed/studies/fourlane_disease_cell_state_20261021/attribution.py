"""Frozen donor-held-out RNA-source attribution; no tissue-fraction inference."""
from intake import *
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import nnls

EPITHELIAL={'AT1','AT2','disease_epithelial','other_epithelial'}
PLAN=json.loads((DATA/'plan_frozen_v1.json').read_text())
SEED=PLAN['seed']

def load(tag):
    x=sparse.load_npz(ART/f'{tag}_raw_cells.npz')
    meta=pd.read_csv(ART/f'{tag}_raw_cells.csv')
    gene_table=pd.read_csv(ART/'atlas_genes.csv')
    genes=gene_table.feature_name.astype(str).to_numpy()
    assert x.shape==(len(meta),len(genes))
    shared=json.loads((DATA/'common_genes_frozen.json').read_text())['atlas_gene_ids']
    keep=gene_table['_index'].astype(str).isin(shared).to_numpy()
    x=x[:,keep];genes=genes[keep]
    assert meta.cell_id.is_unique
    rows=[];means=[];sums=[]
    for (donor,comp),g in meta.groupby(['donor_id','compartment'],sort=True):
        idx=g.index.to_numpy();total=np.asarray(x[idx].sum(axis=0)).ravel().astype(float)
        rows.append(dict(donor_id=donor,compartment=comp,disease=g.disease.iloc[0],age=float(g.age.iloc[0]),n=len(g),population_cells=int(g.population_cells.iloc[0]),weight=float(g.weight.iloc[0])))
        means.append(total/len(g));sums.append(total)
    return pd.DataFrame(rows),np.array(means),np.array(sums),genes

def targets(meta,sums,genes):
    rows=[]
    for donor,g in meta.groupby('donor_id',sort=True):
        ix=g.index.to_numpy();w=g.weight.to_numpy();weighted=sums[ix]*w[:,None]
        row=dict(donor_id=donor,disease=g.disease.iloc[0],age=float(g.age.iloc[0]),sampled_cells=int(g.n.sum()),population_cells=int(g.population_cells.sum()))
        for name,program in PLAN['programs'].items():
            mask=np.isin(genes,program);a=weighted[:,mask].sum(axis=1);raw=sums[ix][:,mask].sum()
            row[name+'_observed_counts']=float(raw)
            row[name+'_weighted_counts']=float(a.sum())
            row[name+'_truth']=float(a[g.compartment.isin(EPITHELIAL)].sum()/a.sum()) if a.sum()>0 else np.nan
            row[name+'_eligible']=bool(raw>=PLAN['sampling']['minimum_total_ECM_counts'])
        rows.append(row)
    return pd.DataFrame(rows)

def reference(meta,means,genes,kind,donors=None):
    # Donor bootstrap repeats whole donor blocks rather than treating cells as replicates.
    if donors is None:donors=meta.donor_id.unique().tolist()
    use=pd.concat([meta[meta.donor_id==d] for d in donors])
    if kind=='healthy':use=use[use.disease=='Control']
    elif kind=='IPF':use=use[use.disease=='IPF']
    comps=sorted(use.compartment.unique())
    raw=np.column_stack([means[use[use.compartment==c].index].mean(axis=0) for c in comps])
    ref=raw/raw.sum(axis=0)[None,:]*1e6
    exclude=set(sum(PLAN['programs'].values(),[]))
    allowed=np.array([g not in exclude and not g.startswith(('MT-','RPL','RPS')) for g in genes])
    specificity=ref/np.maximum(ref.sum(axis=1)[:,None],1e-15)
    markers=set()
    for j in range(len(comps)):
        ok=np.flatnonzero(allowed&(ref[:,j]>=1))
        # Stable tie breaking follows fixed source gene order, never confirmation values.
        ranked=ok[np.argsort(-specificity[ok,j],kind='stable')]
        markers.update(ranked[:50].tolist())
    return comps,raw,ref,np.array(sorted(markers),dtype=int)

def predict(refpack,bulk,genes):
    comps,raw,ref,markers=refpack
    y=bulk/bulk.sum()*1e6
    coef,resid=nnls(ref[markers],y[markers],maxiter=1000)
    # Column scaling equivalence: source shares are invariant to raw-vs-CPM
    # reference units for unregularized NNLS. Coefficients are NOT tissue fractions.
    cr,rr=nnls(raw[markers],y[markers],maxiter=1000)
    out={'nnls_residual':float(resid),'markers':len(markers),'reference_compartments':len(comps)}
    for name,program in PLAN['programs'].items():
        ix=np.isin(genes,program);contribution=ref[ix].sum(axis=0)*coef
        contribution_raw=raw[ix].sum(axis=0)*cr
        ep=np.isin(comps,list(EPITHELIAL))
        out[name+'_prediction']=float(contribution[ep].sum()/contribution.sum()) if contribution.sum()>0 else np.nan
        raw_share=float(contribution_raw[ep].sum()/contribution_raw.sum()) if contribution_raw.sum()>0 else np.nan
        out[name+'_raw_CPM_difference']=raw_share-out[name+'_prediction']
    return out

def run_predictions(training,testing,loo=False,bootstrap_donors=None):
    tm,mean,ts,genes=training;vm,_,vs,vg=testing
    assert np.array_equal(genes,vg)
    truth=targets(vm,vs,genes);trtruth=targets(tm,ts,genes)
    rows=[];refcache={}
    for _,target in truth.iterrows():
        donor=target.donor_id
        donors=bootstrap_donors if bootstrap_donors is not None else tm.donor_id.unique().tolist()
        if loo:donors=[d for d in donors if d!=donor]
        t=trtruth.set_index('donor_id').loc[donors]
        selected=t[(t.disease=='IPF')&t.primary_ECM_eligible]
        base=target.to_dict();base['model']='constant'
        for name in PLAN['programs']:
            good=t[(t.disease=='IPF')&t[name+'_eligible']]
            base[name+'_prediction']=float(good[name+'_truth'].median()) if len(good) else np.nan
        rows.append(base)
        group=vm[vm.donor_id==donor];ix=group.index.to_numpy()
        bulk=(vs[ix]*group.weight.to_numpy()[:,None]).sum(axis=0)
        for kind in ['healthy','IPF','pooled']:
            r=target.to_dict();r['model']='NNLS_'+kind
            try:
                if loo:pack=reference(tm,mean,genes,kind,donors)
                else:
                    if kind not in refcache:refcache[kind]=reference(tm,mean,genes,kind,donors)
                    pack=refcache[kind]
                r.update(predict(pack,bulk,genes));r['failure']=''
            except Exception as e:r['failure']=repr(e)
            rows.append(r)
    return pd.DataFrame(rows)

def summary(pred):
    rng=np.random.default_rng(SEED);out={}
    for disease in ['IPF','Control']:
        for program in PLAN['programs']:
            table=pred[(pred.disease==disease)&pred[program+'_eligible']].copy()
            models={}
            for name,g in table.groupby('model'):
                good=g[np.isfinite(g[program+'_prediction'])&np.isfinite(g[program+'_truth'])]
                e=np.abs(good[program+'_prediction'].to_numpy()-good[program+'_truth'].to_numpy())
                if len(e):
                    rng=np.random.default_rng(SEED+int(hashlib.sha256((disease+program+name).encode()).hexdigest()[:8],16))
                    bs=e[rng.integers(len(e),size=(2000,len(e)))].mean(axis=1)
                    models[name]=dict(n=len(e),mae=float(e.mean()),ci95=np.quantile(bs,[.025,.975]).tolist(),bias=float((good[program+'_prediction']-good[program+'_truth']).mean()),failed_or_nonfinite=len(g)-len(e))
            table['absolute_error']=abs(table[program+'_prediction']-table[program+'_truth'])
            wide=table.pivot(index='donor_id',columns='model',values='absolute_error')
            comparisons={}
            for a,b in [('NNLS_healthy','NNLS_pooled'),('constant','NNLS_pooled'),('NNLS_IPF','NNLS_pooled')]:
                if a not in wide or b not in wide:continue
                diff=(wide[a]-wide[b]).dropna().to_numpy()
                if len(diff):
                    rng=np.random.default_rng(SEED+int(hashlib.sha256((disease+program+a+b).encode()).hexdigest()[:8],16))
                    bs=diff[rng.integers(len(diff),size=(2000,len(diff)))].mean(axis=1)
                    comparisons[a+'_minus_'+b]=dict(n=len(diff),mean_error_reduction=float(diff.mean()),ci95=np.quantile(bs,[.025,.975]).tolist(),minimum_relevant_effect=.05)
            out[disease+'_'+program]=dict(models=models,paired_comparisons=comparisons)
    return out

def main():
    tag=sys.argv[1];assert tag in ['development','confirmation']
    if tag=='confirmation':
        assert (DATA/'confirmation_open_authorization.json').exists()
        assert not (ART/'confirmation_predictions.csv').exists(),'Confirmation evaluation already recorded'
    out=ART/f'{tag}_predictions.csv'
    if out.exists():raise RuntimeError('Refuse overwrite; use explicit recovery/replay artifact')
    train=load('development');test=train if tag=='development' else load('confirmation')
    status(tag+'_models',['raw expression intake','fixed marker and source attribution implementation'],['donor uncertainty','reference uncertainty','result review'])
    pred=run_predictions(train,test,loo=(tag=='development'));pred.to_csv(out,index=False)
    result=summary(pred);atomic(ART/f'{tag}_metrics.json',result)
    targets(test[0],test[2],test[3]).to_csv(ART/f'{tag}_donor_truth.csv',index=False)
    ledger=dict(at=now(),phase=tag,models=['constant','NNLS_healthy','NNLS_IPF','NNLS_pooled'],unique_model_configurations=4,seed=SEED,folds=int(test[0].donor_id.nunique()) if tag=='development' else 1,code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),plan_sha256=hashlib.sha256((DATA/'plan_frozen_v1.json').read_bytes()).hexdigest(),prediction_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),command=' '.join(sys.argv),interpreter=sys.executable)
    atomic(DATA/f'{tag}_trial_ledger.json',ledger);print(json.dumps(result,indent=2))

if __name__=='__main__':main()
