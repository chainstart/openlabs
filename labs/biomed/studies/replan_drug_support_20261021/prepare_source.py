"""Re-derive source features in NEW artifacts; old artifacts are strictly read-only."""
from common import *
from metadata import OLD_ART, OLD_DATA, verify_old
from curve_math import empirical_auc, fit_curve, logistic, fitted_auc, self_check
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore',message='All-NaN slice encountered')

def check_freeze():
    for f,h in json.loads((DATA/'freeze-ledger.json').read_text())['files'].items():
        assert sha256_file(DATA/f)==h,f

def describe(dose,reps,lo,hi,known=None):
    dose=np.asarray(dose,dtype=float)
    vals=np.array(list(reps.values()),dtype=float)
    aucs=np.array([empirical_auc(dose,y,lo,hi) for y in vals])
    if known is not None:
        params=[known['source_bottom'],known['source_logec50'],known['source_slope']]
        fit={'success':True,'auc':fitted_auc(params,lo,hi),'bottom':params[0],'logec50':params[1],'slope':params[2]}
    else:fit=fit_curve(dose,vals,lo,hi)
    if fit['success']:
        params=[fit['bottom'],fit['logec50'],fit['slope']]
        pred=logistic(np.log10(dose),params)
        nrfe=float(np.mean(100*abs(vals-pred)*(1+4*pred*(1-pred))))
        rmse=float(np.sqrt(np.mean((vals-pred)**2)))
        f_auc=fit['auc']
    else:nrfe=rmse=float('nan');f_auc=float(aucs.mean())
    medcurve=np.clip(vals,0,1).mean(axis=0)
    record={'raw_auc':float(aucs.mean()),'fit_auc':f_auc,'rep_sd':float(aucs.std(ddof=1)),
            'nrep':len(vals),'nrfe':nrfe,'rmse':rmse,'fit_failed':int(not fit['success']),
            'saturation_low':float(np.mean(vals<=.05)),'saturation_high':float(np.mean(vals>=.95)),
            'dynamic_range':float(medcurve.max()-medcurve.min()),
            'common_lo':lo,'common_hi':hi,'support_width':hi-lo,
            'source_log_min':float(np.log10(dose.min())),'source_log_max':float(np.log10(dose.max())),
            'source_n_doses':len(dose)}
    for k in [1,2,3]:
        record['rep'+str(k)+'_auc']=empirical_auc(dose,reps[k],lo,hi) if k in reps else np.nan
    return record,fit

def main():
    check_freeze();verify_old()
    assert not (ART/'source-preparation-complete.json').exists(),'Already prepared; verify instead of overwriting'
    write(ART/'math-self-check.json',self_check())
    write(ART/'source-preparation-start.json',{'at':now(),'command':'bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 /home/biostar/work/projects/openlabs/openlabs/labs/biomed/.venv/bin/python labs/biomed/studies/replan_drug_support_20261021/prepare_source.py','code_sha256':sha256_file(__file__),'freeze_sha256':sha256_file(DATA/'plan-frozen.json')})
    support=pd.read_csv(DATA/'common-support-metadata.csv').set_index('structure_key')
    inventory=json.loads((OLD_ART/'reproducibility-inventory.json').read_text())
    hashes={x['path']:x['sha256'] for x in inventory['files']}
    old_curves=[];old_features=[]
    for part,base in [('train','development'),('validation','development'),('test','sealed')]:
        p=OLD_ART/base/(part+'-curves.csv.gz');assert sha256_file(p)==hashes[str(p)]
        old_features.append(pd.read_csv(p))
        old_curves.extend(json.loads((OLD_ART/base/(part+'-curves-raw.json')).read_text()))
    oldf=pd.concat(old_features).set_index(['structure_key','depmap_id'])
    cache={};oldraw={};dev=[];failures=[]
    for i,r in enumerate(old_curves):
        key=r['structure_key'];model=r['depmap_id'];f=oldf.loc[(key,model)]
        if key in support.index:
            lo,hi=float(support.loc[key,'common_lo']),float(support.loc[key,'common_hi'])
        else:lo,hi=float(f.common_lo),float(f.common_hi)
        reps={int(k):np.array(v) for k,v in r['source_replicates'].items()}
        features,fit=describe(r['source_doses'],reps,lo,hi,known=f)
        rec=dict(structure_key=key,depmap_id=model,row_name=r['row_name'],source_screen=f.source_screen,
                 source_plate=f.source_plate,target_pool=f.target_pool,old_split=r['split'],
                 role='validation' if r['split']=='validation' else 'train',**features)
        rec['target_auc']=empirical_auc(r['target_doses'],r['target_replicates']['3'],lo,hi)
        rec['target_unclipped_auc']=empirical_auc(r['target_doses'],r['target_replicates']['3'],lo,hi,clip=False)
        dev.append(rec);cache[(key,model)]=features;oldraw[(key,model)]=r
    pd.DataFrame(dev).to_csv(ART/'development-features.csv.gz',index=False)
    print('Old exposed development rows',len(dev),flush=True)

    selected=pd.read_csv(DATA/'metadata-qualified-pairs.csv')
    selected=selected[selected.source_eligible].sort_values(['structure_key','depmap_id'])
    normalized=pd.read_pickle(OLD_ART/'normalized-selected-mfi.pkl')
    ex=pd.read_csv(OLD_ART/'selected-well-metadata.csv')
    ex=ex[ex.screen_id==ex.source_screen]
    groups={}
    for (key,screen),g in ex.groupby(['structure_key','screen_id']):
        if key not in set(selected.structure_key):continue
        clusters=[]
        for d in sorted(g.dose.unique()):
            if not clusters or abs(np.log10(d/clusters[-1][0]))>.001:clusters.append([d])
            else:clusters[-1].append(d)
        dose=np.array([np.median(x) for x in clusters])
        dmap={d:j for j,cl in enumerate(clusters) for d in cl}
        g=g.copy();g['dose_index']=g.dose.map(dmap)
        reps={}
        for rep,h in g.groupby('replicate'):
            cols=[h[h.dose_index==j].column_name.tolist() for j in range(len(dose))]
            if any(not cs for cs in cols):continue
            reps[int(rep)]=np.column_stack([np.nanmedian(normalized[cs].to_numpy(),axis=1) for cs in cols])
        groups[(key,screen)]=(dose,reps,'|'.join(sorted(g.compound_plate.unique())))
    rowindex={r:i for i,r in enumerate(normalized.index)}
    output=[];raw=[];reused=0;refit=0
    for i,r in enumerate(selected.itertuples(index=False)):
        checktime=datetime.datetime.now(datetime.timezone.utc)
        if checktime>=datetime.datetime.fromisoformat('2026-10-21T19:21:45+00:00'):raise TimeoutError('Review reserve reached')
        dose,allreps,plate=groups[(r.structure_key,r.source_screen)]
        reps={k:v[rowindex[r.row_name]] for k,v in allreps.items() if np.isfinite(v[rowindex[r.row_name]]).all()}
        assert len(reps)>=2
        key=(r.structure_key,r.depmap_id)
        if key in cache:
            old=oldraw[key]
            assert np.allclose(dose,old['source_doses'],rtol=0,atol=1e-12)
            assert set(reps)=={int(k) for k in old['source_replicates']}
            for k,v in reps.items():assert np.allclose(v,old['source_replicates'][str(k)],rtol=0,atol=1e-12)
            feat=cache[key];reused+=1
        else:
            feat,fit=describe(dose,reps,r.common_lo,r.common_hi);refit+=1
            if not fit['success']:failures.append({'structure_key':r.structure_key,'depmap_id':r.depmap_id,'reason':fit})
        out=dict(drug=r.drug,structure_key=r.structure_key,cell_line=r.cell_line,depmap_id=r.depmap_id,
                 row_name=r.row_name,source_screen=r.source_screen,source_plate=plate,**feat)
        output.append(out)
        raw.append(dict(structure_key=r.structure_key,depmap_id=r.depmap_id,source_doses=dose.tolist(),source_replicates={str(k):v.tolist() for k,v in reps.items()}))
        if (i+1)%500==0:
            print('Source progress',i+1,len(selected),'refit',refit,'reuse',reused,flush=True)
            write(ART/'source-progress.json',{'at':now(),'processed':i+1,'total':len(selected),'refits':refit,'reused':reused,'fit_failures':len(failures)})
            status('source_feature_derivation',['plan frozen','old development rederived',f'{i+1}/{len(selected)} source rows'],['complete source features','fit models','freeze scores','external evaluation','review'],[str(ART/'source-progress.json')])
    out=pd.DataFrame(output);out.to_csv(ART/'external-source-features.csv.gz',index=False)
    write(ART/'external-source-curves.json',raw)
    write(ART/'source-fit-failures.json',failures)
    result={'at':now(),'development_rows':len(dev),'external_source_rows':len(out),'external_structures':out.structure_key.nunique(),
            'external_models':out.depmap_id.nunique(),'old_fit_reuses':reused,'new_fixed_fits':refit,'fit_failures':len(failures),
            'new_target_responses_read':False,'files':{n:sha256_file(ART/n) for n in ['development-features.csv.gz','external-source-features.csv.gz','external-source-curves.json','source-fit-failures.json']}}
    write(ART/'source-preparation-complete.json',result)
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
