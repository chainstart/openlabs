"""Development and once-opened held-guide/held-donor bulk confirmation."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from intake import ART, DATA, atomic, now, status
from calibration import fit, evaluate

TARGETS=['ATP2A2','CYB5R4','ELOB','GATA3','KDM1A','MED24','MEN1','NFKB2','SGF29']

def prepare(splits,features=None):
    samples=pd.read_csv(DATA/'bulk_samples.csv');samples=samples[samples.split.isin(splits)].copy()
    matrices={};libraries={};geneinfo=None
    for fn in sorted(samples.file.unique()):
        raw=pd.read_csv(ART/'payload'/fn,index_col='gene_id')
        exclusions=json.loads((DATA/'bulk_count_exclusions_frozen.json').read_text())['excluded_genes']
        raw=raw[raw.index.str.startswith('ENSG') & ~raw.index.isin(exclusions)]
        if raw.index.duplicated().any():raise ValueError('duplicate gene IDs')
        info=raw[['gene_name','gene_biotype']]
        if geneinfo is None:geneinfo=info
        elif not set(geneinfo.index).issubset(info.index):raise ValueError('reference genes missing; do not silently impute')
        cols=samples[samples.file==fn].sample_id.tolist()
        counts=raw.loc[geneinfo.index,cols].to_numpy(float).T
        if not np.isfinite(counts).all() or (counts<0).any():raise ValueError('invalid bulk counts')
        for col,x in zip(cols,counts):
            matrices[col]=x
            libraries[col]=float(raw[col].sum())
    geneinfo=geneinfo.copy();ids=geneinfo.index.to_numpy(str)
    if features is None:
        eligible=geneinfo.gene_biotype.eq('protein_coding').to_numpy() & ~geneinfo.gene_name.isin(TARGETS).to_numpy()
        for donor,g in samples[(samples.split=='train')&(samples.target=='NTC')].groupby('donor_id'):
            c=np.sum([matrices[x] for x in g.sample_id],axis=0);eligible &= (c/sum(libraries[x] for x in g.sample_id)*1e6>=10)
        features=ids[eligible].tolist()
    indices=geneinfo.index.get_indexer(features)
    if (indices<0).any():raise ValueError('frozen features missing in this split')
    target_idx={}
    for target in TARGETS:
        ii=np.flatnonzero(geneinfo.gene_name.eq(target).to_numpy())
        if len(ii)!=1:raise ValueError('target symbol ambiguous/missing '+target)
        target_idx[target]=int(ii[0])
    rows=[];effects=[]
    for _,row in samples[samples.target!='NTC'].iterrows():
        nt=samples[(samples.original_donor_label==row.original_donor_label)&(samples.target=='NTC')]
        if len(nt)==0:raise ValueError('no matched controls')
        y=matrices[row.sample_id];c=np.sum([matrices[x] for x in nt.sample_id],axis=0)
        yl=libraries[row.sample_id];cl=sum(libraries[x] for x in nt.sample_id)
        Y=np.log2(y[indices]/yl*1e6+1)-np.log2(c[indices]/cl*1e6+1)
        r=row.to_dict();r.update(target_count=float(y[target_idx[row.target]]),control_target_count=float(c[target_idx[row.target]]),library_size=yl,control_library_size=cl,n_cells=1.,counts_integer=bool(np.allclose(y,np.round(y))),n_control_wells=len(nt))
        rows.append(r);effects.append(Y)
    return pd.DataFrame(rows).reset_index(drop=True),np.stack(effects),features

def develop():
    meta,Y,features=prepare(['train','validation'])
    atomic(DATA/'bulk_features_frozen.json',features)
    atomic(DATA/'bulk_development_measurement_audit.json',{'at_utc':now(),'n_features':len(features),'n_rows':len(meta),'n_donors':meta.donor_id.nunique(),'integer_counts':bool(meta.counts_integer.all()),'library_count_range':[float(meta.library_size.min()),float(meta.library_size.max())],'responses_opened':'numeric development donors only'})
    train=meta.split.eq('train').to_numpy();val=meta.split.eq('validation').to_numpy()
    model=fit(meta[train].reset_index(drop=True),Y[train],has_cells=False)
    atomic(DATA/'bulk_training_model.json',model)
    result=evaluate(meta[train].reset_index(drop=True),Y[train],meta[val].reset_index(drop=True),Y[val],model,'bulk_validation')
    finalmodel=fit(meta,Y,has_cells=False);atomic(DATA/'bulk_final_model_frozen.json',finalmodel)
    meta.to_csv(ART/'bulk_development_samples.csv',index=False);np.savez_compressed(ART/'bulk_development_effects.npz',Y=Y)
    atomic(DATA/'bulk_freeze_manifest.json',{'frozen_at_utc':now(),'files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [DATA/'frozen_plan_v1.json',DATA/'plan_clarification_v1_1.json',DATA/'bulk_count_exclusions_frozen.json',DATA/'bulk_features_frozen.json',DATA/'bulk_final_model_frozen.json',Path(__file__),Path(__file__).with_name('calibration.py')]},'model_selection':'none; no validation-dependent parameter/endpoint/feature changes','confirmation_opened':False})
    print(json.dumps(result['primary_M5_vs_M2'],indent=2))

def confirm():
    marker=DATA/'bulk_confirmation_opened.json'
    if marker.exists():raise RuntimeError('Confirmation already opened; any error/replay requires explicit audit, not a new independent test')
    manifest=json.loads((DATA/'bulk_freeze_manifest.json').read_text())
    for file,sha in manifest['files'].items():
        if hashlib.sha256(Path(file).read_bytes()).hexdigest()!=sha:raise RuntimeError('frozen file changed: '+file)
    atomic(marker,{'opened_at_utc':now(),'freeze_manifest_sha256':hashlib.sha256((DATA/'bulk_freeze_manifest.json').read_bytes()).hexdigest(),'status':'opening once'})
    features=json.loads((DATA/'bulk_features_frozen.json').read_text());model=json.loads((DATA/'bulk_final_model_frozen.json').read_text())
    source=pd.read_csv(ART/'bulk_development_samples.csv');sy=np.load(ART/'bulk_development_effects.npz')['Y']
    meta,Y,_=prepare(['test'],features)
    meta.to_csv(ART/'bulk_confirmation_samples.csv',index=False);np.savez_compressed(ART/'bulk_confirmation_effects.npz',Y=Y)
    result=evaluate(source,sy,meta,Y,model,'bulk_confirmation')
    atomic(marker,{'opened_at_utc':json.loads(marker.read_text())['opened_at_utc'],'completed_at_utc':now(),'freeze_manifest_sha256':hashlib.sha256((DATA/'bulk_freeze_manifest.json').read_bytes()).hexdigest(),'status':'evaluated once','results_sha256':hashlib.sha256((ART/'bulk_confirmation_results.json').read_bytes()).hexdigest()})
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    if sys.argv[1]=='develop':develop()
    elif sys.argv[1]=='confirm':confirm()
    else:raise ValueError('develop or confirm required')
