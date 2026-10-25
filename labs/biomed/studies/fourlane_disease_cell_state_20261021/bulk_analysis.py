"""Exploratory adult bulk corroboration, never causal composition/state truth."""
from attribution import *
from scipy.stats import t

def fit_hc3(x,y):
    removed=[]
    if "--drop-zero-nuisance" in sys.argv:
        removed=[j for j in range(2,x.shape[1]) if np.all(x[:,j]==0)]
        x=x[:,[j for j in range(x.shape[1]) if j not in removed]]
    rank=np.linalg.matrix_rank(x)
    if rank<x.shape[1]:return dict(status='unavailable',reason='Rank-deficient explanatory design',rank=int(rank),columns=x.shape[1])
    inv=np.linalg.inv(x.T@x);beta=inv@x.T@y;res=y-x@beta
    h=np.sum((x@inv)*x,axis=1)
    meat=x.T@(((res/(1-h))**2)[:,None]*x)
    cov=inv@meat@inv;se=np.sqrt(max(0,cov[1,1]));crit=t.ppf(.975,len(y)-rank)
    return dict(status='estimated',all_zero_nuisance_columns_removed=removed,disease_coefficient=float(beta[1]),ci95=[float(beta[1]-crit*se),float(beta[1]+crit*se)],independent_units=len(y),residual_df=len(y)-int(rank),condition_number=float(np.linalg.cond(x)),uncertainty='HC3 heteroscedasticity-robust SE with t residual df; conditional on reference estimates')

def main():
    suffix="_zero_column_repair" if "--drop-zero-nuisance" in sys.argv else ""
    assert (DATA/'bulk_analysis_registration.json').exists()
    assert not (ART/f'bulk_secondary_results{suffix}.json').exists()
    train=load('development');tm,means,_,symbols=train
    allgenes=pd.read_csv(ART/'atlas_genes.csv')
    shared=json.loads((DATA/'common_genes_frozen.json').read_text())['atlas_gene_ids']
    genes=allgenes[allgenes['_index'].isin(shared)].reset_index(drop=True)
    assert np.array_equal(genes.feature_name.to_numpy(),symbols)
    samples=pd.read_csv(DATA/'bulk_sample_frozen_recovery.csv')
    samples=samples[samples.eligible_sex_adjusted].reset_index(drop=True)
    counts=pd.read_csv(ART/'payload/GSE134692_raw_counts_recovery.txt.gz',sep='\t',index_col=0)
    ann=pd.read_csv(ART/'payload/GSE134692_gene_annotation.txt.gz',sep='\t').set_index('ensembl')
    assert counts.index.is_unique and ann.index.is_unique
    available=genes['_index'].isin(counts.index)&genes['_index'].isin(ann.index)
    lengths=ann.ExonLength.reindex(genes['_index']).to_numpy(float)
    available &= np.isfinite(lengths)&(lengths>0)
    raw=counts.reindex(genes['_index'])[samples.sample_id].fillna(0).to_numpy(float)
    abundance=np.zeros_like(raw);abundance[available]=raw[available]/lengths[available,None]
    abundance=abundance/abundance.sum(axis=0)[None,:]*1e6
    references={kind:reference(tm,means,symbols,kind) for kind in ['healthy','pooled']}
    coefficients={};composition={}
    for kind,pack in references.items():
        comps,_,ref,markers=pack;markers=markers[available.to_numpy()[markers]]
        c=np.array([nnls(ref[markers],abundance[markers,j],maxiter=1000)[0] for j in range(abundance.shape[1])])
        c=c/c.sum(axis=1)[:,None];coefficients[kind]=(comps,c)
        composition[kind]={name:c@ref[np.isin(symbols,program)].sum(axis=0) for name,program in PLAN['programs'].items()}
    comps,c=coefficients['pooled']
    # A single registered explanatory design; final RNA mixture column omitted.
    x=np.column_stack([np.ones(len(samples)),samples.DiseaseStatus.eq('IPF').astype(float),(samples.Age-samples.Age.mean())/10,samples.sex.eq('M').astype(float),samples.Batch.eq(2).astype(float),c[:,:-1]])
    rows=samples[['Sample.property','DiseaseStatus','Age','sex','Batch']].copy()
    for i,comp in enumerate(comps):rows['estimated_RNA_fraction_'+comp]=c[:,i]
    rng=np.random.default_rng(SEED);result={}
    case=samples.DiseaseStatus.eq('IPF').to_numpy();control=~case
    for name,program in PLAN['programs'].items():
        y=np.log2(abundance[np.isin(symbols,program)].sum(axis=0)+1)
        z=np.log2(composition['healthy'][name]+1)
        def contrast(values):
            a=values[case];b=values[control]
            bs=a[rng.integers(len(a),size=(2000,len(a)))].mean(axis=1)-b[rng.integers(len(b),size=(2000,len(b)))].mean(axis=1)
            return dict(mean_difference=float(a.mean()-b.mean()),ci95=np.quantile(bs,[.025,.975]).tolist(),n_ipf=len(a),n_control=len(b))
        rows[name+'_log2_exon_length_adjusted_CPM']=y
        rows[name+'_healthy_reference_mixture_only_log2']=z
        result[name]=dict(unadjusted_bulk=contrast(y),healthy_reference_mixture_only=contrast(z),conventional_RNA_mixture_covariate_adjusted=fit_hc3(x,y))
    rows.to_csv(ART/f'bulk_secondary_donor_values{suffix}.csv',index=False)
    atomic(ART/f'bulk_secondary_results{suffix}.json',dict(at=now(),metrics=result,available_common_genes=int(available.sum()),design_columns=['intercept','IPF','age_per10years','male','batch2']+['RNA_'+k for k in comps[:-1]],limitations=['Exploratory corroboration only; bulk cohort was already deconvolved in Adams2020','Sample.property identity is provisional and repeated libraries excluded','ExonLength is source-release annotation, not per-sample RSEM effective transcript length; cross-assay normalization remains approximate','Estimated fractions are RNA mixture coefficients, not tissue cell proportions','Covariate adjustment is statistical, not causal; composition and within-cell state are not separately identified in real bulk','Intervals conditional on one development reference; adult clinical selection and unmeasured confounding remain'],counts_semantics='RSEM fractional estimated counts; not raw integer UMI data',paper_candidate=False))
    atomic(DATA/f'bulk_secondary_trial_ledger{suffix}.json',dict(at=now(),configuration='bulk_explanatory_OLS',model_slot=8,command=' '.join(sys.argv),code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),primary_confirmation=False,seed=SEED))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
