"""Frozen, sparse-row T-cell transfer experiment; explicit one-time confirmation."""
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.sparse import load_npz
from intake import ART, DATA, atomic, now, status, fetch
from calibration import fit, evaluate, potency, source_for, ratio

DEV=['CE0008162','CE0010866']
TEST=['CE0008678','CE0006864']
PANEL=['ATP2A2','CYB5R4','ELOB','GATA3','KDM1A','MED24','MEN1','NFKB2','SGF29']

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def axes():return pd.read_csv(ART/'pseudobulk_obs.csv',index_col=0),pd.read_csv(ART/'pseudobulk_var.csv',index_col=0)
def readrow(pos,label):
    p=ART/'extracted'/label/f'{pos}.npz';m=json.loads(p.with_suffix('.json').read_text())
    if sha(p)!=m['sha256']:raise ValueError('row hash mismatch')
    x=load_npz(p).toarray()[0].astype(float)
    if not np.isfinite(x).all() or (x<0).any():raise ValueError('invalid row')
    if not m['sum_matches_metadata']:raise ValueError('row sum does not match original metadata')
    return x

def controls(obs,label,donors):
    ids=json.loads((DATA/'development_access_plan.json').read_text())['control_ids'];out={}
    for donor in donors:
        for condition in sorted(obs.culture_condition.unique()):
            for half,gg in [('A',ids[:8]),('B',ids[8:])]:
                mask=obs.donor_id.eq(donor)&obs.culture_condition.eq(condition)&obs.guide_id.isin(gg)
                ix=np.flatnonzero(mask);assert len(ix)==8
                out[(donor,condition,half)]=np.sum([readrow(i,label) for i in ix],axis=0)
    return out

def select():
    if (DATA/'screen_selection_frozen.json').exists():raise RuntimeError('selection already frozen')
    obs,var=axes();c=controls(obs,'development_controls',DEV)
    eligible=np.ones(len(var),bool)
    for d in DEV:
        for cond in sorted(obs.culture_condition.unique()):
            x=c[d,cond,'A']+c[d,cond,'B'];eligible &= x/x.sum()*1e6>=10
    available=set(var.index[eligible]);groups={}
    for target,g in obs[obs.guide_type.eq('targeting')].groupby('perturbed_gene_name'):
        guides=sorted(g.guide_id.unique())
        # Complete original metadata support, never author response significance filters.
        if len(guides)!=2 or len(g)!=24 or g.n_cells.min()<25:continue
        if g.groupby(['donor_id','culture_condition','guide_id']).size().max()!=1:continue
        tids=g.perturbed_gene_id.unique()
        if len(tids)!=1 or tids[0] not in available:continue
        groups[target]=guides
    ranked=sorted(groups,key=lambda x:hashlib.sha256(('perturbation-context-v1:'+x).encode()).hexdigest())
    random=ranked[:64];diagnostic=[x for x in PANEL if x in groups and x not in random]
    if len(random)<64:raise RuntimeError('fewer than 64 prespecified eligible targets; do not replace design silently')
    selected=random+diagnostic
    features=var.index[eligible & ~var.gene_name.isin(selected).to_numpy()].tolist()
    rows=obs[obs.perturbed_gene_name.isin(selected)].copy()
    rows['guide_partition']=[groups[t].index(g)+1 for t,g in zip(rows.perturbed_gene_name,rows.guide_id)]
    rows['panel']=np.where(rows.perturbed_gene_name.isin(random),'random','author_selected')
    rows['split']=np.where(rows.donor_id.isin(DEV),'train','test')
    rows['position']=obs.index.get_indexer(rows.index)
    dev=rows[(rows.split=='train')&(rows.guide_partition==1)]
    test=rows[rows.split=='test']
    ids=json.loads((DATA/'development_access_plan.json').read_text())['control_ids']
    ntc=obs[obs.donor_id.isin(TEST)&obs.guide_id.isin(ids)].copy()
    dev.to_csv(DATA/'screen_development_rows.csv');test.to_csv(DATA/'screen_confirmation_rows.csv')
    ntc.to_csv(DATA/'screen_confirmation_controls.csv')
    atomic(DATA/'screen_features_frozen.json',features)
    atomic(DATA/'screen_transport_budget.json',{'at_utc':now(),'planned_target_rows':len(dev)+len(test),'confirmation_control_rows':len(ntc),'conservative_data_chunk_bytes':(len(dev)+len(test)+len(ntc))*4*339712,'metadata_allowance_bytes':512*1024**2,'global_enforced_bytes':6*1024**3,'memory_estimate_mib':800,'dense_scope':'only selected response vectors, never complete atlas','http_concurrency':2,'row_shards':'transport only; no scientific split modification'})
    atomic(DATA/'screen_selection_frozen.json',{'at_utc':now(),'eligible_targets':len(groups),'random_targets':random,'diagnostic_targets':diagnostic,'unavailable_author_targets':[x for x in PANEL if x not in selected],'guides':{k:groups[k] for k in selected},'n_features':len(features),'n_dev_rows':len(dev),'n_test_rows':len(test),'n_test_controls':len(ntc),'target_selection_uses':'metadata and development NTC only; no guide efficacy/DE filter','files':{str(p):sha(p) for p in [DATA/'screen_development_rows.csv',DATA/'screen_confirmation_rows.csv',DATA/'screen_confirmation_controls.csv',DATA/'screen_features_frozen.json']}})
    print('SELECTED',len(random),len(diagnostic),'features',len(features),'rows',len(dev),len(test),flush=True)

def prepare(stage):
    obs,var=axes();features=json.loads((DATA/'screen_features_frozen.json').read_text());indices=var.index.get_indexer(features);assert (indices>=0).all()
    dev=stage=='development';table=pd.read_csv(DATA/f'screen_{stage}_rows.csv',index_col=0)
    ctr=controls(obs,'development_controls' if dev else 'screen_confirmation_controls',DEV if dev else TEST)
    rows=[];effects=[]
    for sid,row in table.iterrows():
        x=readrow(int(row.position),'screen_'+stage);c=ctr[row.donor_id,row.culture_condition,'A' if row.guide_partition==1 else 'B']
        ti=var.index.get_loc(row.perturbed_gene_id)
        r=row.to_dict();r.update(sample_id=sid,target=row.perturbed_gene_name,target_count=x[ti],control_target_count=c[ti],library_size=x.sum(),control_library_size=c.sum())
        rows.append(r);effects.append(np.log2(x[indices]/x.sum()*1e6+1)-np.log2(c[indices]/c.sum()*1e6+1))
    return pd.DataFrame(rows).reset_index(drop=True),np.stack(effects)

def develop():
    if (DATA/'screen_final_model_frozen.json').exists():raise RuntimeError('already fitted; explicit audit needed for replay')
    # Runs after both extraction workers have exited: at most one HTTP transfer.
    # Identity checks never change or replace the frozen target panel.
    library=fetch('sgrna_library_metadata.suppl_table.csv','https://genome-scale-tcell-perturb-seq.s3.amazonaws.com/marson2025_data/suppl_tables/sgrna_library_metadata.suppl_table.csv',accession='GSE314342',unit='sgRNA sequence and genomic target metadata',terms='Author-linked public research data, internal attributed analysis; no redistribution; see terms_resolution_audit.json',terms_url='https://github.com/emdann/GWT_perturbseq_analysis_2025/blob/master/metadata/data_sharing_readme.md',citation='Zhu et al Cell 2026 DOI10.1016/j.cell.2026.08.002',max_bytes=16*1024**2)
    if library is None:raise RuntimeError('guide sequence metadata unavailable; inspect official alternate before confirmation')
    annotation=pd.read_csv(library,dtype=str)
    selected=json.loads((DATA/'screen_selection_frozen.json').read_text());checks=[]
    for target,guides in selected['guides'].items():
        seqs=[]
        for guide in guides:
            seq=annotation.loc[annotation.sgRNA.eq(guide),'seq'].dropna().str.upper().unique()
            if len(seq)!=1:raise ValueError('missing/ambiguous guide sequence '+guide)
            seqs.append(seq[0])
        checks.append({'target':target,'guides':guides,'sequences':seqs,'full_sequences_distinct':seqs[0]!=seqs[1],'terminal19_distinct':seqs[0][-19:]!=seqs[1][-19:]})
    valid=all(x['full_sequences_distinct'] and x['terminal19_distinct'] for x in checks)
    atomic(DATA/'screen_guide_sequence_audit.json',{'at_utc':now(),'source_sha256':sha(library),'checks':checks,'sequence_isolation_valid':valid,'panel_replaced':False,'limitations':'distinct sequences do not guarantee absence of shared off-target binding or prove independent biological replication'})
    if not valid:raise ValueError('frozen panel contains nonindependent guide sequences; scientific review required')
    old=ART/'payload/stabl_constructs.csv'
    if old.exists() and old.stat().st_size==0:
        old.rename(ART/'recovery/integrity_quarantine/stabl_constructs.original_zero_bytes.csv')
    fetch('stabl_constructs.csv','https://genome-scale-tcell-perturb-seq.s3.amazonaws.com/marson2025_data/suppl_tables/stabl_constructs.csv',accession='GSE314342',unit='validation plasmid constructs',terms='Author-linked supplementary sequence table; internal attributed analysis only',terms_url='https://github.com/emdann/GWT_perturbseq_analysis_2025/blob/master/metadata/data_sharing_readme.md',max_bytes=1024**2)
    meta,Y=prepare('development');mask=meta.panel.eq('random').to_numpy()
    model=fit(meta[mask].reset_index(drop=True),Y[mask],True)
    atomic(DATA/'screen_final_model_frozen.json',model)
    atomic(ART/'models/screen_final_model_frozen.json',model)
    atomic(DATA/'screen_quality_thresholds_frozen.json',{'at_utc':now(),'derived_from':'random panel development donors guide1 only','library_size_median':float(meta.loc[mask,'library_size'].median()),'n_cells_median':float(meta.loc[mask,'n_cells'].median()),'target_count_median':float(meta.loc[mask,'target_count'].median()),'purpose':'descriptive quality strata, never confirmation filtering or model selection'})
    # Descriptive leave-one-development-donor check. Calibration uses both donors;
    # explicitly not an independent validation or model-selection score.
    meta.to_csv(ART/'screen_development_samples.csv',index=False);np.savez_compressed(ART/'screen_development_effects.npz',Y=Y)
    frozen=[DATA/'frozen_plan_v1.json',DATA/'screen_selection_frozen.json',DATA/'screen_features_frozen.json',DATA/'screen_final_model_frozen.json',ART/'models/screen_final_model_frozen.json',ART/'screen_development_samples.csv',ART/'screen_development_effects.npz',DATA/'screen_guide_sequence_audit.json',DATA/'screen_quality_thresholds_frozen.json',DATA/'screen_implementation_conventions.json',DATA/'screen_residual_sensitivity_frozen.json',DATA/'screen_offtarget_diagnostics_frozen.json',Path(__file__),Path(__file__).with_name('calibration.py')]
    atomic(DATA/'screen_freeze_manifest.json',{'at_utc':now(),'files':{str(p):sha(p) for p in frozen},'n_random_dev_rows':int(mask.sum()),'n_features':Y.shape[1],'no_tuning':True})
    print('FITTED',model,flush=True)

def open_confirmation():
    marker=DATA/'screen_confirmation_opened.json'
    if marker.exists():raise RuntimeError('already opened')
    freeze=json.loads((DATA/'screen_freeze_manifest.json').read_text())
    for p,h in freeze['files'].items():
        if sha(p)!=h:raise RuntimeError('frozen file changed '+p)
    atomic(marker,{'at_utc':now(),'status':'opened for one-time extraction and evaluation','freeze_sha256':sha(DATA/'screen_freeze_manifest.json')})

def residuals(meta,Y,source,sy,model):
    source=source.copy();meta=meta.copy();source['q'],source['qs'],_,_,_=potency(source,model['prior']);meta['q'],meta['qs'],_,_,_=potency(meta,model['prior'])
    residual=[];independent_residual=[]
    for _,r in meta.iterrows():
        s=source_for(source,sy,r.target,r.culture_condition)
        residual.append(Y[len(residual)]-ratio(r.qs,s['qs'])*s['Y'])
        # Distinct development donors for the two held guides avoid a shared
        # estimated response vector inducing residual cross-guide covariance.
        donor=DEV[int(r.guide_partition)-1]
        sm=source.donor_id.eq(donor).to_numpy()
        separate=source_for(source[sm].reset_index(drop=True),sy[sm],r.target,r.culture_condition)
        independent_residual.append(Y[len(independent_residual)]-ratio(r.qs,separate['qs'])*separate['Y'])
    R=np.stack(residual)
    # Center across three time contexts within donor/guide/target to isolate temporal component.
    for _,ids in meta.groupby(['donor_id','guide_id','target']).groups.items():
        ii=np.array(list(ids));R[ii]-=R[ii].mean(axis=0)
    records=[]
    for (donor,target),g in meta.groupby(['donor_id','target']):
        aa=g[g.guide_partition==1].sort_values('culture_condition').index.to_numpy();bb=g[g.guide_partition==2].sort_values('culture_condition').index.to_numpy()
        if len(aa)!=3 or len(bb)!=3:continue
        a,b=R[aa].ravel(),R[bb].ravel();den=np.linalg.norm(a)*np.linalg.norm(b)
        records.append({'donor_id':donor,'target':target,'panel':g.panel.iloc[0],'temporal_residual_crossguide_product':float(np.mean(a*b)),'cosine':float(a@b/den) if den else None})
    pd.DataFrame(records).to_csv(ART/'screen_temporal_residual_audit.csv',index=False)
    cross=[]
    for target,g in meta.groupby('target'):
        vectors=[]
        for donor in TEST:
            # Opposite guides across donors avoid identical-guide artifacts, but study/batch remain shared.
            part=1 if donor==TEST[0] else 2
            ix=g[(g.donor_id==donor)&(g.guide_partition==part)].sort_values('culture_condition').index.to_numpy()
            vectors.append(R[ix].ravel())
        a,b=vectors;den=np.linalg.norm(a)*np.linalg.norm(b)
        cross.append({'target':target,'panel':g.panel.iloc[0],'cross_donor_guide_product':float(np.mean(a*b)),'cosine':float(a@b/den) if den else None})
    pd.DataFrame(cross).to_csv(ART/'screen_temporal_crossdonor_audit.csv',index=False)
    for label,Q in [('independent_reference',np.stack(independent_residual)),('raw_response',Y.copy())]:
        for _,ids in meta.groupby(['donor_id','guide_id','target']).groups.items():
            ii=np.array(list(ids));Q[ii]-=Q[ii].mean(axis=0)
        records=[]
        for (donor,target),g in meta.groupby(['donor_id','target']):
            aa=g[g.guide_partition==1].sort_values('culture_condition').index.to_numpy();bb=g[g.guide_partition==2].sort_values('culture_condition').index.to_numpy()
            a,b=Q[aa].ravel(),Q[bb].ravel();den=np.linalg.norm(a)*np.linalg.norm(b)
            records.append({'donor_id':donor,'target':target,'panel':g.panel.iloc[0],'temporal_crossguide_product':float(np.mean(a*b)),'cosine':float(a@b/den) if den else None})
        pd.DataFrame(records).to_csv(ART/f'screen_temporal_{label}_audit.csv',index=False)
        cross=[]
        for target,g in meta.groupby('target'):
            vectors=[]
            for donor,part in zip(TEST,[1,2]):
                ix=g[(g.donor_id==donor)&(g.guide_partition==part)].sort_values('culture_condition').index.to_numpy();vectors.append(Q[ix].ravel())
            a,b=vectors;den=np.linalg.norm(a)*np.linalg.norm(b)
            cross.append({'target':target,'panel':g.panel.iloc[0],'cross_donor_guide_product':float(np.mean(a*b)),'cosine':float(a@b/den) if den else None})
        pd.DataFrame(cross).to_csv(ART/f'screen_temporal_{label}_crossdonor.csv',index=False)

def confirm():
    marker=DATA/'screen_confirmation_opened.json';m=json.loads(marker.read_text())
    if m.get('status')!='opened for one-time extraction and evaluation':raise RuntimeError('confirmation already started; no silent replay')
    for p,h in json.loads((DATA/'screen_freeze_manifest.json').read_text())['files'].items():
        if sha(p)!=h:raise RuntimeError('frozen file changed '+p)
    m.update(status='evaluation started',evaluation_started_at_utc=now());atomic(marker,m)
    source=pd.read_csv(ART/'screen_development_samples.csv');sy=np.load(ART/'screen_development_effects.npz')['Y']
    model=json.loads((DATA/'screen_final_model_frozen.json').read_text());meta,Y=prepare('confirmation')
    meta.to_csv(ART/'screen_confirmation_samples.csv',index=False);np.savez_compressed(ART/'screen_confirmation_effects.npz',Y=Y)
    for panel,prefix in [('random','screen_confirmation'),('author_selected','screen_diagnostic')]:
        # Primary transfer must isolate BOTH donors and guides. Held donor guide1
        # is accessed only for the prespecified residual cross-guide audit.
        mask=(meta.panel.eq(panel)&meta.guide_partition.eq(2)).to_numpy();sm=source.panel.eq(panel).to_numpy()
        if mask.any():evaluate(source[sm].reset_index(drop=True),sy[sm],meta[mask].reset_index(drop=True),Y[mask],model,prefix,screen=True)
    residuals(meta,Y,source,sy,model)
    thresholds=json.loads((DATA/'screen_quality_thresholds_frozen.json').read_text())
    metrics=pd.read_csv(ART/'screen_confirmation_row_metrics.csv')
    metrics=metrics.merge(meta[['sample_id','target_count']],on='sample_id',how='left',validate='many_to_one')
    for col in ['library_size','n_cells','target_count']:
        metrics[col+'_development_median_stratum']=np.where(metrics[col]>=thresholds[col+'_median'],'high','low')
        metrics.groupby(['model','donor_id',col+'_development_median_stratum']).mse.agg(['mean','count']).to_csv(ART/f'screen_{col}_quality_diagnostics.csv')
    off=pd.read_csv(ART/'payload/guide_offtarget_analysis_results.csv')
    hits=off[off.distal_offtarget.astype(str).str.lower().isin(['true','1'])]
    pairs=set(zip(hits.guide_id,hits.culture_condition))
    metrics['author_distal_offtarget_flag']=['flagged' if (g,c) in pairs else 'not_flagged_or_not_screened' for g,c in zip(metrics.guide_id,metrics.culture_condition)]
    proximal=pd.read_csv(ART/'payload/DE_stats.suppl_table.csv',usecols=['target_contrast_gene_name','culture_condition','neighboring_gene_KD'])
    prox=proximal[proximal.neighboring_gene_KD.astype(str).str.lower().isin(['true','1'])]
    pairs=set(zip(prox.target_contrast_gene_name,prox.culture_condition))
    metrics['author_proximal_offtarget_flag']=['flagged' if (g,c) in pairs else 'not_flagged_or_not_screened' for g,c in zip(metrics.target,metrics.culture_condition)]
    for flag in ['author_distal_offtarget_flag','author_proximal_offtarget_flag']:
        metrics.groupby(['model','donor_id',flag]).mse.agg(['mean','count']).to_csv(ART/f'screen_{flag}_diagnostics.csv')
    m.update(status='evaluated once',completed_at_utc=now(),results_sha256=sha(ART/'screen_confirmation_results.json'));atomic(marker,m)
    print(json.dumps(json.loads((ART/'screen_confirmation_results.json').read_text())['primary_M5_vs_M2']),flush=True)

if __name__=='__main__':
    {'select':select,'develop':develop,'open':open_confirmation,'confirm':confirm}[sys.argv[1]]()
