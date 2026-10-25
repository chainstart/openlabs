"""Execute pinned upstream ReDeconv components on development cells only.

Keep original normalization and MLMD estimator; endpoint genes cannot be markers.
Streaming gene rows avoids densifying the full single-cell count matrix.
"""
from attribution import *
import importlib.util
import contextlib
os.environ['MPLBACKEND']='Agg'
os.environ['MPLCONFIGDIR']=str(ART/'mplconfig')

def upstream(which):
    path=ART/'payload'/f'redeconv___ReDeconv_{which}.py'
    spec=importlib.util.spec_from_file_location('upstream_redeconv_'+which,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def build(kind):
    directory=ART/'redeconv'/kind;directory.mkdir(parents=True,exist_ok=True)
    record=directory/'reference_record.json'
    if record.exists():raise RuntimeError('Refuse reference overwrite')
    N=upstream('N');P=upstream('P')
    x=sparse.load_npz(ART/'development_raw_cells.npz')
    meta=pd.read_csv(ART/'development_raw_cells.csv')
    genes=pd.read_csv(ART/'atlas_genes.csv')
    shared=json.loads((DATA/'common_genes_frozen.json').read_text())['atlas_gene_ids']
    gene_keep=genes['_index'].astype(str).isin(shared).to_numpy()
    x=x[:,gene_keep];genes=genes[gene_keep].reset_index(drop=True)
    keep=np.ones(len(meta),bool)
    if kind=='healthy':keep=meta.disease.eq('Control').to_numpy()
    if kind=='IPF':keep=meta.disease.eq('IPF').to_numpy()
    x=x[keep].astype(float);meta=meta[keep].reset_index(drop=True)
    meta[['cell_id','compartment','donor_id']].to_csv(directory/'meta.tsv',sep='\t',index=False)
    totals=np.asarray(x.sum(axis=1)).ravel()
    sp_tp={}
    for (d,c),group in meta.groupby(['donor_id','compartment']):
        sp_tp.setdefault(d,{})[c]=totals[group.index].tolist()
    sizes=str(directory/'sizes.tsv');counts=str(directory/'counts.tsv')
    N.get_sample_cell_type_exp_mean(sp_tp,sizes,counts,{c:1 for c in meta.compartment},10)
    base=N.get_sample_baseline(sizes,.95)
    means=N.read_sp_tp_mean(sizes)
    corr,neighbors=N.get_Pearson_correlation_samples(means,.95)
    donors=sorted(corr);base_donor=donors[base]
    chosen=[donors[j] for j,c in enumerate(corr[base_donor]) if c>=.95]
    rec=dict(at=now(),kind=kind,baseline_donor=base_donor,offered_donors=donors,normalization_retained_donors=chosen,source_hashes={k:hashlib.sha256((ART/'payload'/f'redeconv___ReDeconv_{k}.py').read_bytes()).hexdigest() for k in ['N','P']},settings=dict(min_cells_per_donor_type=10,normalization_correlation=.95,signature_pvalue=.05,signature_fold_change=2,signature_max_per_type=50,signature_min_cells_type=30,MLMD_iterations=6),adaptations=['Frozen ECM/alveolar endpoint programmes excluded from signature eligibility','Fixed max50 markers per type matches NNLS budget; no outcome-based tuning','Original raw counts used as input; no total-RNA gene-length correction needed for donor UMI pseudobulk'],interpretation='Published components with stated benchmarking constraints, not a new algorithm; normalization discards some donors and may change reference population')
    if len(chosen)<2:
        rec.update(status='unavailable',reason='Upstream default normalization retains fewer than two development donors');atomic(record,rec);return rec
    ratios=N.get_cellType_sample_CellNo_and_tSizeMean(sizes,str(directory/'meta.tsv'),base)
    norm=np.array([ratios[c] for c in meta.cell_id],float)
    if not np.all(np.isfinite(norm)&(norm>0)):raise RuntimeError('Invalid upstream normalization ratio')
    mask=meta.donor_id.isin(chosen).to_numpy()
    normalized=x.multiply(norm[:,None]).tocsr()[mask]
    meta=meta[mask].reset_index(drop=True)
    meta[['cell_id','compartment','donor_id']].to_csv(directory/'selected_meta.tsv',sep='\t',index=False)
    # Sparse CSC conversion permits bounded one-gene dense vectors only.
    normalized=normalized.tocsc()
    excluded=set(sum(PLAN['programs'].values(),[]))
    exp=directory/'signature_input.tsv'
    with exp.open('w') as f:
        f.write('Gene\t'+'\t'.join(meta.cell_id)+'\n')
        for j,g in enumerate(genes.feature_name.astype(str)):
            if g in excluded or g.startswith(('MT-','RPL','RPS')):continue
            values=normalized[:,j].toarray().ravel()
            # Ensembl IDs keep duplicate gene symbols from silently overwriting rows.
            f.write(str(genes.iloc[j]['_index'])+'\t'+'\t'.join(format(v,'.9g') for v in values)+'\n')
    P.get_initial_Signature_Candidates(str(directory/'selected_meta.tsv'),str(exp),str(directory/'initial.tsv'),.05,2.,30,2)
    P.Get_signature_gene_matrix(str(exp),str(directory/'selected_meta.tsv'),str(directory/'initial.tsv'),str(directory/'signature.tsv'),50,str(directory/'signature.png'),str(directory/'signature_extra.tsv'))
    sig,comps=P.read_sig_gene_mean_std(str(directory/'signature.tsv'))
    if not sig:raise RuntimeError('No upstream signatures')
    source_means=np.column_stack([np.asarray(normalized[meta.compartment.eq(c).to_numpy()].mean(axis=0)).ravel() for c in comps])
    if not np.all(np.isfinite(source_means)):raise RuntimeError('Nonfinite source reference')
    np.savez_compressed(directory/'reference.npz',source_means=source_means,compartments=np.array(comps),gene_ids=genes['_index'].astype(str).to_numpy(),gene_symbols=genes.feature_name.astype(str).to_numpy())
    rec.update(status='ready',retained_cells=len(meta),signature_genes=len(sig),compartments=comps,reference_sha256=hashlib.sha256((directory/'reference.npz').read_bytes()).hexdigest(),signature_sha256=hashlib.sha256((directory/'signature.tsv').read_bytes()).hexdigest())
    atomic(record,rec)
    return rec

def evaluate():
    assert (DATA/'confirmation_open_authorization.json').exists()
    out=ART/'confirmation_redeconv_predictions.csv'
    assert not out.exists(),'Refuse second confirmation evaluation'
    P=upstream('P');vm,_,vs,genes=load('confirmation');truth=targets(vm,vs,genes)
    rows=[]
    for kind in ['healthy','IPF','pooled']:
        directory=ART/'redeconv'/kind;record=json.loads((directory/'reference_record.json').read_text())
        for _,t in truth.iterrows():
            row=t.to_dict();row['model']='ReDeconv_'+kind
            try:
                if record['status']!='ready':raise RuntimeError(record.get('reason',record['status']))
                ref=np.load(directory/'reference.npz',allow_pickle=False)
                assert np.array_equal(ref['gene_symbols'],genes)
                sig,comps=P.read_sig_gene_mean_std(str(directory/'signature.tsv'))
                mapping={g:j for j,g in enumerate(ref['gene_ids'])}
                group=vm[vm.donor_id==t.donor_id];ix=group.index.to_numpy()
                bulk=(vs[ix]*group.weight.to_numpy()[:,None]).sum(axis=0)
                bulk=bulk/bulk.sum()*1e6
                y={g:float(bulk[mapping[g]]) for g in sig}
                percentages,fractions=P.MLMD({'target':y},sig,6)
                coefs=np.array([fractions['target'][c] for c in comps])
                for name,program in PLAN['programs'].items():
                    contribution=ref['source_means'][np.isin(genes,program)].sum(axis=0)*coefs
                    ep=np.isin(comps,list(EPITHELIAL))
                    row[name+'_prediction']=float(contribution[ep].sum()/contribution.sum()) if contribution.sum()>0 else np.nan
                row['failure']=''
            except Exception as e:row['failure']=repr(e)
            rows.append(row)
    result=pd.DataFrame(rows)
    for name in PLAN['programs']:
        if name+'_prediction' not in result:result[name+'_prediction']=np.nan
    result.to_csv(out,index=False)
    atomic(ART/'confirmation_redeconv_metrics.json',summary(result))

if __name__=='__main__':
    if sys.argv[1]=='evaluate':evaluate()
    else:
        kind=sys.argv[1];assert kind in ['healthy','IPF','pooled']
        directory=ART/'redeconv'/kind;directory.mkdir(parents=True,exist_ok=True)
        try:
            with (directory/'upstream.log').open('w') as log,contextlib.redirect_stdout(log):rec=build(kind)
        except Exception as e:
            rec=dict(at=now(),kind=kind,status='failed',reason=repr(e));atomic(directory/'reference_record.json',rec)
        print(json.dumps(rec))
