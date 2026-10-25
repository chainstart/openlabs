"""Execute frozen per-plate QC and separately fitted replicate labels.

Confirmation outputs are written to sealed/ and never summarized by effect here.
"""
from common import *
from curve_math import empirical_auc,fit_curve,self_check
import re
import warnings
import numpy as np
import pandas as pd

assert not (ART/'confirmation-opened.json').exists(), 'Completed confirmation exists; use review_results.py for arithmetic audit, not a new confirmation.'

warnings.filterwarnings('ignore',message='All-NaN slice encountered')
warnings.filterwarnings('ignore',message='Mean of empty slice')
freeze=json.loads((DATA/'freeze-ledger.json').read_text())
for f,h in freeze['files'].items():assert hashlib.sha256((DATA/f).read_bytes()).hexdigest()==h,f
plan=json.loads((DATA/'plan-frozen.json').read_text())
write(ART/'math-self-check.json',self_check())
samples=pd.read_csv(DATA/'samples-frozen.csv')
meta=pd.read_csv(DATA/'paired-compound-support.csv').set_index('structure_key')
tm=pd.read_csv(DATA/'treatment-metadata.csv')
cells=pd.read_csv(DATA/'cell-identity.csv').set_index('row_name')
pool=pd.read_csv(ART/'intake/prism19-secondary-screen-pooling-info.csv')
target_pool=pool[pool.screen_id=='MTS010'].dropna(subset=['depmap_id']).groupby('depmap_id').pool_id.agg(lambda x:'|'.join(sorted(set(x))))
tm['replicate']=tm.detection_plate.str.extract(r'_X([123])(?:[_.]|$)',expand=False)
ex=tm[(tm.perturbation_type=='experimental_treatment')&tm.structure_key.isin(meta.index)].copy()
ex=ex.merge(meta[['source_screen']],left_on='structure_key',right_index=True)
ex=ex[(ex.screen_id=='MTS010')|(ex.screen_id==ex.source_screen)]
assert ex.replicate.notna().all(),'Cannot identify original replicate'
ex['replicate']=ex.replicate.astype(int)
required_plates=set(ex.detection_plate)
control=tm[(tm.detection_plate.isin(required_plates))&(tm.perturbation_type.isin(['vehicle_control','positive_control']))]
columns=set(ex.column_name)|set(control.column_name)
if (ART/'normalized-selected-mfi.pkl').exists() and (ART/'selected-well-metadata.csv').exists():
    # Recovery: reuse completed per-plate preprocessing; original raw payload verified separately.
    normalized=pd.read_pickle(ART/'normalized-selected-mfi.pkl')
    old_ex=pd.read_csv(ART/'selected-well-metadata.csv')
    assert set(normalized.columns)==set(ex.column_name)
    assert set(old_ex.column_name)==set(ex.column_name)
    print('Recovery: reusing persisted normalized matrix',normalized.shape,flush=True)
    write(ART/'normalization-recovery.json',{'at':now(),'sha256':hashlib.sha256((ART/'normalized-selected-mfi.pkl').read_bytes()).hexdigest(),'shape':list(normalized.shape),'reason':'Completed normalization survived crash; curve records existed only in RAM and must be recomputed with identical frozen math.'})
else:
    print('Loading selected MFI columns',len(columns),flush=True)
    mfi=pd.read_csv(ART/'intake/prism19-secondary-screen-mfi.csv',index_col=0,usecols=lambda x:x in columns or x=='Unnamed: 0')
    assert set(ex.column_name).issubset(mfi.columns)
    mfi=mfi.astype(float)
    logmfi=np.log2(mfi.where(mfi>0))
    normalized=pd.DataFrame(np.nan,index=mfi.index,columns=ex.column_name,dtype=float)
    qcs=[]
    for plate,info in control.groupby('detection_plate'):
        negcols=info[info.perturbation_type=='vehicle_control'].column_name.tolist()
        poscols=info[info.perturbation_type=='positive_control'].column_name.tolist()
        neg=logmfi[negcols].to_numpy();pos=logmfi[poscols].to_numpy()
        nmed=np.nanmedian(neg,axis=1);pmed=np.nanmedian(pos,axis=1)
        nmad=1.4826*np.nanmedian(abs(neg-nmed[:,None]),axis=1)
        pmad=1.4826*np.nanmedian(abs(pos-pmed[:,None]),axis=1)
        with np.errstate(divide='ignore',invalid='ignore'):
            ssmd=(nmed-pmed)/np.sqrt(nmad**2+pmad**2)
        nn=np.isfinite(neg).sum(axis=1);np_=np.isfinite(pos).sum(axis=1)
        good=np.isfinite(ssmd)&(ssmd>=2)&(nn>=3)&(np_>=3)
        denom=np.nanmedian(mfi[negcols].where(mfi[negcols]>0).to_numpy(),axis=1)
        ec=ex[ex.detection_plate==plate].column_name.tolist()
        if ec:
            vals=mfi[ec].where(mfi[ec]>0).to_numpy()/denom[:,None]
            vals[~good]=np.nan
            normalized.loc[:,ec]=vals
        qcs.extend({'row_name':r,'detection_plate':plate,'ssmd':float(s),'n_negative':int(n),'n_positive':int(p),'passed':bool(ok)} for r,s,n,p,ok in zip(mfi.index,ssmd,nn,np_,good))
    qc=pd.DataFrame(qcs);qc.to_csv(ART/'plate-control-qc.csv.gz',index=False)
    del mfi,logmfi
    normalized.to_pickle(ART/'normalized-selected-mfi.pkl')
    ex.to_csv(ART/'selected-well-metadata.csv',index=False)
print('QC complete; fitting source and target X1/X2, never target X3.',flush=True)

groups={}
for (key,screen),g in ex.groupby(['structure_key','screen_id']):
    dosevals=sorted(g.dose.unique());clusters=[]
    for d in dosevals:
        if not clusters or abs(np.log10(d/clusters[-1][0]))>.001:clusters.append([d])
        else:clusters[-1].append(d)
    dose=np.array([np.median(cl) for cl in clusters])
    dmap={d:i for i,cl in enumerate(clusters) for d in cl}
    g=g.copy();g['dose_index']=g.dose.map(dmap)
    reps={}
    for rep,h in g.groupby('replicate'):
        cs=[h[h.dose_index==i].column_name.tolist() for i in range(len(dose))]
        if any(not x for x in cs):continue
        reps[int(rep)]=np.column_stack([np.nanmedian(normalized[x].to_numpy(),axis=1) for x in cs])
    groups[(key,screen)]=(dose,reps,'|'.join(sorted(set(g.compound_plate))))

rowindex={r:i for i,r in enumerate(normalized.index)}
def get_repeats(row,key,screen):
    dose,repcols,plates=groups[(key,screen)]
    complete={}
    for rep,mat in repcols.items():
        vals=mat[rowindex[row]]
        if np.isfinite(vals).all():complete[rep]=vals
    return dose,complete,plates

rowmap=cells.reset_index().set_index('depmap_id').row_name.to_dict()
output=[];excluded=[];rawcurve=[]
start=time.monotonic()
for i,s in enumerate(samples.itertuples(index=False)):
    key=s.structure_key;model=s.depmap_id;row=rowmap.get(model)
    common={'sample_id':s.sample_id,'structure_key':key,'depmap_id':model,'split':s.split,'row_name':row}
    if row not in normalized.index:
        excluded.append(dict(common,reason='model absent from raw MFI'));continue
    drug=meta.loc[key]
    sd,sreps,sp=get_repeats(row,key,drug.source_screen)
    td,treps,tp=get_repeats(row,key,'MTS010')
    if len(sreps)<2 or not {1,2,3}.issubset(treps):
        excluded.append(dict(common,reason='incomplete or control-failed original replicate',source_complete='|'.join(map(str,sreps)),target_complete='|'.join(map(str,treps))));continue
    # Actual representative dose points may differ slightly from metadata minima.
    # Use conservative common endpoints within both source/target raw supports.
    lo=float(np.log10(max(drug.common_min,sd.min(),td.min())))
    hi=float(np.log10(min(drug.common_max,sd.max(),td.max())))
    source=fit_curve(sd,list(sreps.values()),lo,hi)
    target=fit_curve(td,[treps[1],treps[2]],lo,hi)
    if not source['success'] or not target['success']:
        excluded.append(dict(common,reason='predeclared fixed 3PL optimization failure',source_fit=source,target_fit=target));continue
    source_aut=np.array([empirical_auc(sd,y,lo,hi) for y in sreps.values()])
    target_aut={r:empirical_auc(td,y,lo,hi) for r,y in treps.items()}
    target_unclipped=empirical_auc(td,treps[3],lo,hi,clip=False)
    srcpoints=np.mean([np.interp(np.linspace(lo,hi,5),np.log10(sd),y) for y in sreps.values()],axis=0)
    rec=dict(common,source_screen=drug.source_screen,source_plate=sp,target_plate=tp,target_pool=target_pool.get(model,'unknown'),common_lo=lo,common_hi=hi,log_source_min=float(np.log10(sd.min())),log_source_max=float(np.log10(sd.max())),log_target_min=float(np.log10(td.min())),log_target_max=float(np.log10(td.max())),support_width=hi-lo,source_fit_auc=source['auc'],source_raw_auc=float(source_aut.mean()),source_rep_auc_sd=float(source_aut.std(ddof=1)),source_nrep=len(sreps),target_fit_auc=target['auc'],target_raw_auc=target_aut[3],target_raw_unclipped_auc=target_unclipped,target_fit_rep1_aut=target_aut[1],target_fit_rep2_aut=target_aut[2],source_bottom=source['bottom'],source_logec50=source['logec50'],source_slope=source['slope'],source_rmse=source['rmse'],source_fit_boundary=source['boundary'],target_fit_boundary=target['boundary'],target_fit_rmse=target['rmse'],source_nfev=source['nfev'],target_nfev=target['nfev'])
    rec.update({f'source_point{j}':float(v) for j,v in enumerate(srcpoints)})
    rec.update({f'source_rep{r}_aut':empirical_auc(sd,y,lo,hi) for r,y in sreps.items()})
    output.append(rec)
    rawcurve.append(dict(common,source_doses=sd.tolist(),target_doses=td.tolist(),source_replicates={r:y.tolist() for r,y in sreps.items()},target_replicates={r:y.tolist() for r,y in treps.items()}))
    if (i+1)%500==0:
        write(ART/'curve-processing-progress.json',{'at_utc':now(),'processed_candidate_pairs':i+1,'total':len(samples),'eligible':len(output),'excluded':len(excluded),'elapsed_seconds':time.monotonic()-start})
        print('processed',i+1,'/',len(samples),'eligible',len(output),'excluded',len(excluded),flush=True)
        status('frozen_curve_processing',['Plan frozen before numeric target outcomes','Per-plate controls normalized independently; no shared ComBat','Processing source curves and target X1/X2; X3 remains evaluation-only'],['Finish bounded curve fitting','Development baseline comparison','Single confirmation opening','Independent result review/report'],['plan-frozen.json','curve-processing-progress.json','plate-control-qc.csv.gz'])

out=pd.DataFrame(output)
for split in ['train','validation','test']:
    dest=ART/('sealed' if split=='test' else 'development');dest.mkdir(exist_ok=True)
    out[out.split==split].to_csv(dest/(split+'-curves.csv.gz'),index=False)
    write(dest/(split+'-curves-raw.json'),[r for r in rawcurve if r['split']==split])
pd.DataFrame(excluded).to_csv(ART/'curve-exclusions.csv.gz',index=False)
summary={'at_utc':now(),'stage':'curve_processing_complete','numerical_target_values_processed_but_not_evaluated':True,'counts':out.groupby('split').agg(pairs=('sample_id','size'),drugs=('structure_key','nunique'),models=('depmap_id','nunique')).to_dict('index'),'exclusions':pd.DataFrame(excluded).reason.value_counts().to_dict() if excluded else {},'elapsed_seconds':time.monotonic()-start,'no_performance_metrics_calculated':True}
write(ART/'curve-preparation-summary.json',summary)
print(json.dumps(summary,indent=2),flush=True)
