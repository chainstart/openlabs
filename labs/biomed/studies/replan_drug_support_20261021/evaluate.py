"""Single frozen external evaluation with chemical x cell clustered uncertainty."""
from common import *
from prepare_source import check_freeze
from pair_math import METHODS, LEARNED, selected, method_error
import numpy as np
import pandas as pd
import argparse

def weighted_pair_mean(W,i,j,values,n):
    den=np.zeros((n,n),dtype=float);num=np.zeros((n,n),dtype=float)
    den[i,j]=1.;num[i,j]=values
    denominator=np.sum((W@den)*W,axis=1)
    assert np.all(denominator>0),'Degenerate cluster bootstrap sample'
    return np.sum((W@num)*W,axis=1)/denominator

def software_check():
    i=np.array([0,0,1]);j=np.array([1,2,2]);v=np.array([0.,.5,1.])
    w=np.array([[1,1,1],[2,1,3],[0,1,2]],dtype=float)
    got=weighted_pair_mean(w,i,j,v,3)
    expected=[]
    for a in w:
        weights=[a[ii]*a[jj] for ii,jj in zip(i,j)]
        expected.append(sum(x*y for x,y in zip(weights,v))/sum(weights))
    assert np.allclose(got,expected,atol=1e-14)
    return {'cluster_matrix_matches_explicit_pairs':True,'synthetic_is_software_only':True}

def main(resume=False):
    check_freeze()
    if resume:
        assert (ART/'confirmation-opened.json').exists()
        assert not (ART/'confirmation-results.json').exists()
        failure=json.loads((ART/'evaluation-indexing-failure.json').read_text())
        assert failure['effects_computed'] is False
        assert not (ART/'evaluation-indexing-repair.json').exists()
    else:
        assert not (ART/'confirmation-opened.json').exists(),'One opening already used; only arithmetic review allowed.'
    frozen=json.loads((ART/'models-frozen.json').read_text())
    assert sha256_file(ART/'models.joblib')==frozen['model_sha256']
    for name,h in frozen['code'].items():assert sha256_file(CODE/name)==h,name
    for item in frozen['scores']:assert sha256_file(item['path'])==item['sha256']
    target_record=json.loads((ART/'target-preparation-complete.json').read_text())
    for p,h in target_record['hashes'].items():assert sha256_file(p)==h,p
    write(ART/'evaluation-software-checks.json',software_check())
    if resume:
        write(ART/'evaluation-indexing-repair.json',{'at':now(),'evaluation_attempt':2,'confirmation_opening_count':1,'code_sha256':sha256_file(__file__),'repair':'Explicit per-drug xs then ModelID reindex; frozen models/scores/selection/seed/statistical procedure unchanged','prior_failure':'evaluation-indexing-failure.json'})
    else:
        write(ART/'confirmation-opened.json',{'at_utc':now(),'opening':1,'plan_sha256':frozen['plan_sha256'],'models_frozen_sha256':sha256_file(ART/'models-frozen.json'),'evaluation_code_sha256':sha256_file(__file__),'primary':'hgb_full vs gap_raw at50% coverage','validation_selected_secondary':frozen['validation_selected_secondary'],'preprocessing_exposure':'target preprocessing logged separately; this is first source-target effect evaluation'})
    target=pd.read_csv(ART/'sealed/external-target.csv.gz').set_index(['structure_key','depmap_id'])
    keys=[x['structure_key'] for x in frozen['scores']]
    cellids=sorted(target.index.get_level_values('depmap_id').unique())
    cell_index={c:i for i,c in enumerate(cellids)}
    B=1000;D=len(keys);M=len(METHODS)
    rng=np.random.default_rng(20261021)
    dw=rng.multinomial(D,np.full(D,1/D),size=B).astype(float)
    cw=rng.multinomial(len(cellids),np.full(len(cellids),1/len(cellids)),size=B).astype(float)
    boot=np.zeros((B,D,M));unclipboot=np.zeros((B,D,2))
    point=np.zeros((D,M));unclippoint=np.zeros((D,2))
    rows=[];calibration=[];progress=[]
    for di,item in enumerate(frozen['scores']):
        key=item['structure_key'];z=np.load(item['path'],allow_pickle=False)
        modelids=z['models'];i=z['i'];j=z['j'];n=len(modelids);tie=z['tie']
        aligned=target.xs(key,level='structure_key').reindex(modelids)
        y=aligned.target_auc.to_numpy()
        yu=aligned.target_unclipped_auc.to_numpy()
        # Explicit alignment protects against MultiIndex order assumptions.
        assert aligned.index.tolist()==modelids.tolist()
        assert np.isfinite(y).all() and np.isfinite(yu).all()
        diff=y[i]-y[j];udiff=yu[i]-yu[j]
        directions={x:z[x+'_direction'] for x in ['raw','fit','mean']}
        W=cw[:,[cell_index[c] for c in modelids]]
        for mi,name in enumerate(METHODS):
            score=z['scores'][:,mi];error=method_error(name,directions,diff)
            rec={'structure_key':key,'drug':item['drug'],'method':name,'n_cells':n,'n_comparisons':len(i),'source_plate':item['source_plate'],'all_pair_error':float(error.mean())}
            for coverage in [.25,.5,.75]:
                ix=selected(score,tie,coverage)
                rec['error_'+str(coverage)]=float(error[ix].mean())
                rec['selected_'+str(coverage)]=len(ix)
                if coverage==.5:
                    point[di,mi]=rec['error_0.5']
                    boot[:,di,mi]=weighted_pair_mean(W,i[ix],j[ix],error[ix],n)
                    if name in ['gap_raw','hgb_full']:
                        ui=['gap_raw','hgb_full'].index(name)
                        ue=method_error(name,directions,udiff)
                        unclippoint[di,ui]=float(ue[ix].mean())
                        unclipboot[:,di,ui]=weighted_pair_mean(W,i[ix],j[ix],ue[ix],n)
            if name in LEARNED:
                risk=z['risks'][:,LEARNED.index(name)]
                # Squared error to fractional tie-coded labels, as used in development.
                rec['tie_coded_probability_mse']=float(np.mean((risk-error)**2))
                # Expected binary Brier includes the irreducible coin-tie component.
                rec['expected_binary_brier']=float(np.mean(risk*risk-2*risk*error+error))
                binid=np.minimum((risk*5).astype(int),4)
                for b in range(5):
                    hit=binid==b
                    if hit.any():calibration.append({'structure_key':key,'method':name,'bin':b,'n_comparisons':int(hit.sum()),'predicted':float(risk[hit].mean()),'observed':float(error[hit].mean())})
            rows.append(rec)
        progress.append({'structure_key':key,'n_cells':n,'n_comparisons':len(i)})
        write(ART/'evaluation-progress.json',{'at':now(),'drugs_done':di+1,'total':D,'effects_opened':True})
        print('Evaluated',di+1,D,item['drug'],flush=True)
    table=pd.DataFrame(rows);table.to_csv(ART/'external-by-drug.csv',index=False)
    pd.DataFrame(calibration).to_csv(ART/'external-calibration-by-drug.csv',index=False)
    macro=np.einsum('bd,bdm->bm',dw,boot)/D
    drug_only=dw@point/D
    u_macro=np.einsum('bd,bdm->bm',dw,unclipboot)/D
    np.savez_compressed(ART/'bootstrap-results.npz',methods=np.array(METHODS),two_way=macro,drug_only=drug_only,unclipped_primary=u_macro,drug_weights=dw,cell_weights=cw)
    metrics={}
    for mi,name in enumerate(METHODS):
        v=table[table.method==name]
        metrics[name]={'error_at_50pct':float(point[:,mi].mean()),'two_way_ci95':np.quantile(macro[:,mi],[.025,.975]).tolist(),
                       'drug_only_ci95':np.quantile(drug_only[:,mi],[.025,.975]).tolist(),'error_at_25pct':float(v['error_0.25'].mean()),
                       'error_at_75pct':float(v['error_0.75'].mean()),'all_pair_error':float(v.all_pair_error.mean())}
        if name in LEARNED:
            metrics[name]['tie_coded_probability_mse']=float(v.tie_coded_probability_mse.mean())
            metrics[name]['expected_binary_brier']=float(v.expected_binary_brier.mean())
    base=METHODS.index('gap_raw');full=METHODS.index('hgb_full')
    delta=macro[:,base]-macro[:,full]
    diffpoint=point[:,base]-point[:,full]
    primary={'benefit':float(diffpoint.mean()),'two_way_ci95':np.quantile(delta,[.025,.975]).tolist(),
             'drug_only_ci95':np.quantile(drug_only[:,base]-drug_only[:,full],[.025,.975]).tolist(),
             'minimum_practical_effect':.02,'material_benefit_supported':bool(np.quantile(delta,.025)>.02),
             'registered_material_benefit_excluded_conditionally':bool(np.quantile(delta,.975)<.02),
             'between_drug_sd':float(diffpoint.std(ddof=1))}
    strong={}
    for name in ['hgb_gap','isotonic_gap','gap_fit','ridge_full','standardized_gap','nrfe_curve']:
        k=METHODS.index(name);v=macro[:,k]-macro[:,full]
        strong[name]={'benefit_of_hgb_full':float((point[:,k]-point[:,full]).mean()),'two_way_ci95':np.quantile(v,[.025,.975]).tolist()}
    up=u_macro[:,0]-u_macro[:,1]
    unc={'benefit':float((unclippoint[:,0]-unclippoint[:,1]).mean()),'two_way_ci95':np.quantile(up,[.025,.975]).tolist()}
    plates=sorted({p for v in frozen['scores'] for p in v['source_plate'].split('|')})
    leave=[]
    for plate in plates:
        mask=np.array([plate not in v['source_plate'].split('|') for v in frozen['scores']])
        if mask.any():leave.append({'excluded_source_plate':plate,'retained_drugs':int(mask.sum()),'primary_benefit':float(diffpoint[mask].mean())})
    write(ART/'leave-source-plate-out.json',leave)
    result={'at_utc':now(),'stage':'exploratory_pilot','paper_candidate':False,
            'counts':{'drug_structures':D,'cell_models':len(cellids),'drug_cell_pairs':len(target),'cell_comparisons':sum(x['n_comparisons'] for x in progress),'source_compound_plates':len(plates)},
            'primary':primary,'all_baselines':metrics,'strong_baseline_comparisons':strong,'unclipped_sensitivity':unc,
            'validation_selected_secondary':frozen['validation_selected_secondary'],
            'model_selection_range_benefit':[float(min(metrics['gap_raw']['error_at_50pct']-metrics[k]['error_at_50pct'] for k in LEARNED)),float(max(metrics['gap_raw']['error_at_50pct']-metrics[k]['error_at_50pct'] for k in LEARNED))],
            'uncertainty':'Chemical x cell bootstrap, fixed fitted models and selection sets. Cell comparisons not independent units; no independent laboratory/clinical inference.',
            'limitations':['Only50 chemical structures and one external assay screen, same Broad institution.','CTRP author repeat labels lack original plate/experiment IDs; target collapsed within dose; no independent donor claim.','Source training uses historical complete-case PRISM fits; deployed raw rows retain fit failures, inducing a known development/target eligibility shift.','Curve-level NRFE is an adapted published formula, not full4PL plateQC reproduction; no superiority over plateQC or DRS claimed.','Exact structures held constant across screens; no unseen-drug generalization.','Bootstrap conditional on development data/model selection and available panel; target shared-plate dependence unmeasured.'],
            'run':{'seed':20261021,'configurations':12,'confirmation_openings':1,'plan_sha256':frozen['plan_sha256'],'model_sha256':frozen['model_sha256'],'code_sha256':sha256_file(__file__)}}
    write(ART/'confirmation-results.json',result);write(DATA/'confirmation-results.json',result)
    ledger=json.loads((DATA/'all-trials-ledger.json').read_text())
    ledger['current_campaign']['trials'].append({'at':now(),'type':'single_external_confirmation','configuration_count_unchanged':12,'opening':1,'primary':primary,'results_path':str(ART/'confirmation-results.json')})
    write(DATA/'all-trials-ledger.json',ledger)
    status('external_confirmation_complete_review_pending',['frozen12 configurations','one CTRP confirmation','all baselines and clustered intervals'],['independent arithmetic/data review','limitations and Chinese report'],[str(ART/'confirmation-results.json'),str(ART/'external-by-drug.csv')])
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--resume-after-indexing-failure',action='store_true')
    main(resume=parser.parse_args().resume_after_indexing_failure)
