"""Frozen 8-policy promoter contrast pilot. Confirmation refuses a second opening."""
import argparse,csv,json,sys,os,collections,platform
for _thread_var in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS',
                    'NUMEXPR_NUM_THREADS','NUMEXPR_MAX_THREADS','BLIS_NUM_THREADS','VECLIB_MAXIMUM_THREADS']:
    os.environ[_thread_var]='2'
import numpy as np
import pandas as pd
from scipy.stats import pearsonr,spearmanr
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
import joblib
from threadpoolctl import threadpool_info
from common import *

SEED=20261021
CELLS={'HepG2':'ENCSR022GQD','K562':'ENCSR382BVV','WTC11':'ENCSR244FWB'}

def check_freeze():
    assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
    if PROJECT==PROJECT_BASE:
        assert dt.datetime.now(dt.timezone.utc)<dt.datetime.fromisoformat('2026-10-22T00:10:00+00:00')
    else:
        replay=json.loads((PROJECT/'replay-provenance.json').read_text())
        assert replay['replay'] is True and replay['new_independent_validation'] is False
        assert replay['original_results_sha256']==sha(PROJECT_BASE/'results.json')
    for n,h in json.loads((PROJECT/'freeze-hashes.json').read_text()).items():
        assert sha(PROJECT/n)==h, 'Frozen input changed: '+n

def load_cell(cell, samples, phase):
    """Parse numeric values only for phase-permitted identifiers; no WTC11 outside test."""
    if cell=='WTC11': assert phase=='confirm' and set(samples.split)=={'test'}
    if cell=='K562': assert set(samples.split).issubset({'train','validation'})
    meta=json.loads((ART/f'metadata/{CELLS[cell]}.json').read_text())
    files=sorted([x for x in meta['files'] if x.get('file_format')=='tsv' and x.get('status')=='released' and len(x.get('biological_replicates',[]))==1],key=lambda x:x['biological_replicates'][0])
    assert len(files)==3
    wanted={}
    for i,row in enumerate(samples.to_dict('records')):
        for o,orient in enumerate(['sense','antisense']):
            name=row[f'{cell}_{orient}_name']
            assert name not in wanted
            wanted[name]=(i,o)
    scores=np.full((len(samples),3,2),np.nan);barcodes=np.zeros_like(scores)
    audit=[]
    for rep,x in enumerate(files):
        p=ART/'intakes'/x['accession'].lower()/'data.tsv'
        m=json.loads((p.parent/'manifest.json').read_text())
        assert sha(p)==m['sha256'] and p.stat().st_size==m['bytes']
        found=set();bad=0
        with p.open() as f:
            for row in csv.reader(f,delimiter='\t'):
                if len(row)<3 or row[2] not in wanted:continue
                name=row[2];assert name not in found,'duplicate score identifier'
                found.add(name);i,o=wanted[name]
                assert row[0]==cell and int(row[1])==rep+1 and len(row)==8
                try:scores[i,rep,o]=float(row[6]);barcodes[i,rep,o]=float(row[7])
                except ValueError:bad+=1
        audit.append(dict(file=x['accession'],replicate=rep+1,requested=len(wanted),found=len(found),invalid_numeric=bad,
                          payload_sha256=m['sha256'],parsed_label_scope=phase+' requested loci only'))
    quality=np.isfinite(scores).all(axis=(1,2)) & (barcodes>=10).all(axis=(1,2))
    return scores,barcodes,quality,audit

def source_features(scores,barcodes):
    contrasts=scores[:,:,0]-scores[:,:,1]
    delta=contrasts.mean(axis=1)
    avg=scores.mean(axis=(1,2))
    sd=contrasts.std(axis=1,ddof=1)
    activity=np.column_stack([avg,avg**2,sd,np.log1p(barcodes.min(axis=(1,2)))])
    full=np.column_stack([activity,delta,delta*avg])
    reliable=(np.abs(delta)>=.5)&((contrasts>0).all(axis=1)|(contrasts<0).all(axis=1))
    return dict(activity=activity,full=full,delta=delta[:,None],reliable=reliable,contrasts=contrasts)

def fit_models(features,y):
    params=dict(max_iter=100,max_leaf_nodes=7,max_depth=3,min_samples_leaf=20,
                l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=SEED)
    models={'zero':0.,'median':float(np.median(y)),'identity_delta':None}
    for name,key,kind in [('activity_ridge','activity','ridge'),('activity_hgb','activity','hgb'),
                          ('delta_ridge','delta','ridge'),('full_ridge','full','ridge'),('full_hgb','full','hgb')]:
        model=make_pipeline(StandardScaler(),Ridge(alpha=1)) if kind=='ridge' else HistGradientBoostingRegressor(**params)
        models[name]=model.fit(features[key],y)
    return models

def predict(models,features):
    n=len(features['delta']);out={}
    for name,model in models.items():
        if name=='identity_delta':out[name]=features['delta'][:,0].copy()
        elif isinstance(model,float):out[name]=np.full(n,model)
        else:
            key='activity' if name.startswith('activity') else 'delta' if name=='delta_ridge' else 'full'
            out[name]=model.predict(features[key])
    return out

def metrics(y,p):
    return dict(mse=float(np.mean((y-p)**2)),mae=float(np.mean(abs(y-p))),
                pearson=float(pearsonr(y,p).statistic) if np.std(p)>1e-12 and np.std(y)>1e-12 else None,
                spearman=float(spearmanr(y,p).statistic) if np.std(p)>1e-12 and np.std(y)>1e-12 else None,
                sign_concordance=float(np.mean(np.sign(y)==np.sign(p))))

def select():
    check_freeze();assert not (PROJECT/'frozen-selection.json').exists(),'Model selection is already frozen'
    pools=threadpool_info()
    assert all(x['num_threads']<=2 for x in pools),'Native computational thread cap exceeded'
    atomic(PROJECT/'native-thread-pools.json',dict(time_utc=now(),pools=pools,cap=2))
    status('training_validation','Frozen promoter-specific contrast transfer', 'run.py select',[PROJECT/'plan.json'])
    samples=pd.read_csv(PROJECT/'samples.csv')
    source,sbc,sq,sa=load_cell('HepG2',samples,'source')
    trainval=samples[samples.split!='test'].copy().reset_index(drop=True)
    target,tbc,tq,ta=load_cell('K562',trainval,'train_validation')
    sf=source_features(source,sbc)
    tv_positions=np.flatnonzero(samples.split!='test')
    good=sq[tv_positions]&tq
    # Do not evaluate a target outcome before applying the fixed input quality rule.
    train=(trainval.split.to_numpy()=='train')&good
    val=(trainval.split.to_numpy()=='validation')&good
    assert train.sum()>=200 and val.sum()>=100
    y=(target[:,:,0]-target[:,:,1]).mean(axis=1)
    ftrain={k:v[tv_positions[train]] for k,v in sf.items()}
    fval={k:v[tv_positions[val]] for k,v in sf.items()}
    models=fit_models(ftrain,y[train]);pred=predict(models,fval)
    vm={k:metrics(y[val],p) for k,p in pred.items()}
    bnames=['zero','median','activity_ridge','activity_hgb']
    onames=['identity_delta','delta_ridge','full_ridge','full_hgb']
    baseline=min(bnames,key=lambda k:vm[k]['mse']);orientation=min(onames,key=lambda k:vm[k]['mse'])
    out=ART/'models.joblib';joblib.dump(models,out)
    np.savez_compressed(ART/'source-features.npz',**sf,source_scores=source,source_barcodes=sbc,source_quality=sq)
    pv=trainval[val].copy()
    pv['K562_delta']=y[val]
    for k,p in pred.items():pv[k]=p
    pv.to_csv(ART/'validation-predictions.csv',index=False)
    ledger=[]
    for i,name in enumerate(json.loads((PROJECT/'plan.json').read_text())['baselines'],1):
        ledger.append(dict(trial=i,configuration=name,seed=SEED,training_unit='genomic promoter locus',
             n_train=int(train.sum()),n_validation=int(val.sum()),validation=vm[name],
             status='completed',holdout_used=False,model_sha256=sha(out),time_utc=now()))
    atomic(PROJECT/'trial-ledger.json',ledger)
    # Residual activity-only model is trained here, before any confirmation labels.
    residual_target=make_pipeline(StandardScaler(),Ridge(alpha=1)).fit(ftrain['activity'],y[train])
    residual_source=make_pipeline(StandardScaler(),Ridge(alpha=1)).fit(ftrain['activity'],ftrain['delta'][:,0])
    joblib.dump((residual_target,residual_source),ART/'residual-models.joblib')
    selection=dict(frozen_at_utc=now(),baseline=baseline,orientation=orientation,validation=vm,
       n_train=int(train.sum()),n_validation=int(val.sum()),
       qc=dict(source_total=int(sq.sum()),trainval_total=int(good.sum()),trainval_excluded=int((~good).sum())),
       data_audit=sa+ta,plan_sha256=sha(PROJECT/'plan.json'),sample_sha256=sha(PROJECT/'samples.csv'),
       model_sha256=sha(out),feature_sha256=sha(ART/'source-features.npz'),
       residual_models_sha256=sha(ART/'residual-models.joblib'),analysis_code_sha256=sha(Path(__file__)))
    atomic(PROJECT/'frozen-selection.json',selection)
    status('selection_frozen','Frozen selected contrast policy awaits once-only WTC11 confirmation',
           'run.py select completed',[PROJECT/'frozen-selection.json',PROJECT/'trial-ledger.json'])
    print(json.dumps(dict(n_train=int(train.sum()),n_validation=int(val.sum()),selected_baseline=baseline,selected_orientation=orientation,validation=vm),indent=2))

def bootstrap(blocks,yrep,pbase,pmodel,reps=2000):
    codes,uniques=pd.factorize(blocks);nblocks=len(uniques)
    assert nblocks>=50
    count=np.bincount(codes,minlength=nblocks)
    y=yrep.mean(axis=1)
    diff=(y-pbase)**2-(y-pmodel)**2
    summed=np.bincount(codes,weights=diff,minlength=nblocks)
    rng=np.random.default_rng(SEED);blockonly=[];both=[]
    for _ in range(reps):
        inds=rng.integers(0,nblocks,nblocks)
        blockonly.append(float(summed[inds].sum()/count[inds].sum()))
        culture=rng.integers(0,3,3)
        yr=yrep[:,culture].mean(axis=1)
        dc=(yr-pbase)**2-(yr-pmodel)**2
        ds=np.bincount(codes,weights=dc,minlength=nblocks)
        both.append(float(ds[inds].sum()/count[inds].sum()))
    return dict(n_blocks=nblocks,replicates=reps,seed=SEED,
         mse_improvement=float(diff.mean()),
         block_95ci=list(map(float,np.quantile(blockonly,[.025,.975]))),
         block_and_target_culture_95ci=list(map(float,np.quantile(both,[.025,.975]))),
         scope='Conditional on source measurements, fitted policies, four test chromosomes, one WTC11 context and one original study. Three target cultures are globally resampled, not treated as new cell types.'),np.array([blockonly,both])

def confirm():
    check_freeze()
    selection=json.loads((PROJECT/'frozen-selection.json').read_text())
    assert selection['analysis_code_sha256']==sha(Path(__file__)),'Analysis changed after selection'
    for path,key in [('models.joblib','model_sha256'),('source-features.npz','feature_sha256'),('residual-models.joblib','residual_models_sha256')]:
        assert sha(ART/path)==selection[key]
    # Exclusive marker before numeric WTC11 access; no retry/reopening after a failure.
    marker=PROJECT/'confirmation.started.json'
    with marker.open('x') as f:
        json.dump(dict(time_utc=now(),selection_sha256=sha(PROJECT/'frozen-selection.json'),code_sha256=sha(Path(__file__))),f,indent=2)
    status('single_confirmation_evaluation','Held-out WTC11 orientation contrasts at held-out loci',
           'run.py confirm',[marker,PROJECT/'frozen-selection.json'])
    samples=pd.read_csv(PROJECT/'samples.csv')
    test=samples[samples.split=='test'].copy().reset_index(drop=True)
    indices=np.flatnonzero(samples.split=='test')
    source=np.load(ART/'source-features.npz')
    ftest={k:source[k][indices] for k in ['activity','full','delta','reliable','contrasts']}
    scores,bc,tq,audit=load_cell('WTC11',test,'confirm')
    good=tq&source['source_quality'][indices]
    assert good.sum()>=200,'Confirmation QC sample size failed: stop, no retuning'
    test=test[good].copy();ftest={k:v[good] for k,v in ftest.items()}
    yrep=(scores[:,:,0]-scores[:,:,1])[good];y=yrep.mean(axis=1)
    models=joblib.load(ART/'models.joblib');pred=predict(models,ftest)
    allmetrics={k:metrics(y,p) for k,p in pred.items()}
    base=selection['baseline'];model=selection['orientation']
    boot,draws=bootstrap(test.block_id,yrep,pred[base],pred[model])
    np.savez_compressed(ART/'bootstrap-draws.npz',draws=draws)
    target_reg,source_reg=joblib.load(ART/'residual-models.joblib')
    rt=y-target_reg.predict(ftest['activity']);rs=ftest['delta'][:,0]-source_reg.predict(ftest['activity'])
    residual_corr=float(pearsonr(rt,rs).statistic)
    subset=ftest['reliable'];secondary={}
    if subset.sum()>0:
        secondary['source_reliable_subset']=dict(n=int(subset.sum()),baseline=metrics(y[subset],pred[base][subset]),orientation=metrics(y[subset],pred[model][subset]),
             sign_concordance_source_target=float(np.mean(np.sign(y[subset])==np.sign(ftest['delta'][subset,0]))))
    secondary['per_chromosome']={c:dict(n=int((test.chrom==c).sum()),baseline=metrics(y[test.chrom==c],pred[base][test.chrom==c]),orientation=metrics(y[test.chrom==c],pred[model][test.chrom==c])) for c in sorted(test.chrom.unique())}
    secondary['culture_replicate_contrast_correlations']={str(i+1)+'_'+str(j+1):float(pearsonr(yrep[:,i],yrep[:,j]).statistic) for i in range(3) for j in range(i+1,3)}
    secondary['source_replicate_contrast_correlations']={str(i+1)+'_'+str(j+1):float(pearsonr(ftest['contrasts'][:,i],ftest['contrasts'][:,j]).statistic) for i in range(3) for j in range(i+1,3)}
    secondary['train_fit_activity_residual_pearson']=residual_corr
    secondary['per_culture_selected_policy']={str(i+1):dict(baseline=metrics(yrep[:,i],pred[base]),orientation=metrics(yrep[:,i],pred[model])) for i in range(3)}
    for i,label in enumerate(['low','middle','high']):
        # Tertile boundaries are learned on source training identities only.
        trainmask=(samples.split.to_numpy()=='train')&source['source_quality']
        cuts=np.quantile(source['activity'][trainmask,0],[1/3,2/3])
        mask=np.digitize(ftest['activity'][:,0],cuts)==i
        secondary['source_activity_'+label]=dict(n=int(mask.sum()),cuts=list(map(float,cuts)),baseline=metrics(y[mask],pred[base][mask]),orientation=metrics(y[mask],pred[model][mask]))
    relative=boot['mse_improvement']/allmetrics[base]['mse']
    support=relative>=.1 and boot['block_95ci'][0]>0
    test['WTC11_delta']=y;test['HepG2_delta']=ftest['delta'][:,0];test['source_mean_activity']=ftest['activity'][:,0]
    test['source_reliable']=subset
    for i in range(3):test[f'WTC11_replicate_{i+1}_delta']=yrep[:,i]
    for k,p in pred.items():test[k]=p
    test.to_csv(ART/'confirmation-predictions.csv',index=False)
    results=dict(schema_version='openlabs.functional_genomics_results.v1',stage='exploratory_pilot',independent_unit='molecule',
       completed_at_utc=now(),metrics=dict(primary_mse_improvement=boot['mse_improvement'],primary_relative_mse_reduction=float(relative),
          baseline_mse=allmetrics[base]['mse'],orientation_mse=allmetrics[model]['mse'],n_confirmation=int(good.sum())),
       selected_baseline=base,selected_orientation_policy=model,uncertainty=boot,
       baselines={k:{m:v for m,v in vals.items() if v is not None} for k,vals in allmetrics.items()},secondary=secondary,
       trials_run=8,primary_pilot_support=bool(support),paper_candidate=False,
       confirmation_openings=1,qc=dict(identity_eligible=len(good),source_and_target_pass=int(good.sum()),excluded=int((~good).sum())),data_audit=audit,
       limitations=['The exact source study and Roberts2021 already establish generic cross-cell strand asymmetry; this is only a conditional contrast-transfer extension.',
                    'Three cell contexts from one study, with WTC11 as the sole held-out context; genomic loci are not independent donors, cell types or studies.',
                    'LentiMPRA reports reporter activity, not endogenous promoter regulation, enhancer causality, mechanism, efficacy or clinical truth.',
                    'Shared fixed 200nt promoter design and common vector/protocol can preserve assay-specific artifacts across cultures. Independent barcode/library construction does not remove all shared platform bias.',
                    '1Mb block intervals assume limited dependence beyond blocks. Four confirmation chromosomes and three target cultures do not establish across-cell population coverage.',
                    'Source measurements and upstream MPRAflow library-wide normalization are explicitly available. Signed contrasts cancel common log-scale offsets; overall-activity features remain assay-relative.',
                    'Complete-case >=10-barcode QC and subset-selected WTC11 promoters limit population generalization. Sequence identity follows exact coordinates/reference design, not independent construct resequencing.',
                    'The study tests portability of observed assay contrasts; it does not disentangle all biochemical sources of directionality. No new sequence model or superiority to genome foundation models is claimed.'],
       run=dict(command='bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/functional_genomics_day1_20261021/run.py confirm',
          code_sha256=sha(Path(__file__)),code_revision='sha256:'+sha(Path(__file__)),seed=SEED,environment_sha256=sha(PROJECT/'environment.json'),plan_sha256=sha(PROJECT/'plan.json'),selection_sha256=sha(PROJECT/'frozen-selection.json')))
    atomic(PROJECT/'results.json',results)
    ledger=json.loads((PROJECT/'trial-ledger.json').read_text())
    for record in ledger:
        name=record['configuration'];record.update(confirmation_descriptive=allmetrics[name],
           selected_for_primary=name in [base,model],confirmation_used_for_selection=False)
    atomic(PROJECT/'complete-trial-ledger.json',ledger)
    atomic(PROJECT/'confirmation.completed.json',dict(time_utc=now(),results_sha256=sha(PROJECT/'results.json'),predictions_sha256=sha(ART/'confirmation-predictions.csv')))
    status('computation_completed','Conditional promoter contrast transfer result; no paper promotion',
           'run.py confirm completed',[PROJECT/'results.json',PROJECT/'complete-trial-ledger.json',ART/'confirmation-predictions.csv'],state='completed')
    print(json.dumps(dict(primary=results['metrics'],uncertainty=boot,selected=[base,model],pilot_support=support,paper_candidate=False),indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['select','confirm']);args=parser.parse_args()
    if args.phase=='select':select()
    else:confirm()
