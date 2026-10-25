"""Single-use selection and heldout evaluation for frozen C3 calibration pilot."""
from common import *
from c3_metadata import table
import csv, numpy as np, joblib
from sklearn.linear_model import Ridge, LinearRegression
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.dummy import DummyRegressor

MODELS=['equal_response_1','train_mean','basal_affine','nuisance_ridge','nuisance_hgb','class_only','full_ridge','full_hgb']

def check_freeze():
    for p,h in json.loads((DATA/'c3-freeze-hashes.json').read_text()).items():assert sha(p)==h,p
    for p,h in json.loads((DATA/'c3-code-freeze.json').read_text()).items():assert sha(p)==h,p

def load(split):
    with (DATA/'c3-samples.csv').open() as f:samples=[r for r in csv.DictReader(f) if r['split']==split]
    ids={r['sample_id'] for r in samples}
    # Parse strings for lookup, convert label magnitudes only for explicitly requested split.
    raw={r['promoter']:r for r in table('tan_500P_annotations.txt') if r['promoter'] in ids}
    X=[];C=[];Y=[]
    for s in samples:
        r=raw[s['sample_id']];seq=r['seq'].upper()
        assert hashlib.sha256(seq.encode()).hexdigest()==s['sequence_sha256']
        X.append([float(r['P_basal (log2)']),float(r['n_negctrl_E']),float(r['n_for_P_resp']),float(r['fraction_of_reads_in_promoter']),(seq.count('G')+seq.count('C'))/len(seq),sum(seq[i:i+2]=='CG' for i in range(len(seq)-1))/(len(seq)-1)])
        C.append([float(s['source_class']==str(i)) for i in range(3)])
        Y.append(float(r['P_resp']))
    X=np.array(X);C=np.array(C);Y=np.array(Y)
    assert np.isfinite(X).all() and np.isfinite(Y).all()
    return samples,X,C,Y

def features(name,X,C):
    if name=='basal_affine':return X[:,:1]
    if name=='class_only':return C
    if name.startswith('full_'):return np.column_stack([X,C])
    return X

def model(name,plan):
    if name=='equal_response_1':return DummyRegressor(strategy='constant',constant=1)
    if name=='train_mean':return DummyRegressor(strategy='mean')
    if name=='basal_affine':return make_pipeline(StandardScaler(),LinearRegression())
    if name.endswith('_hgb'):return HistGradientBoostingRegressor(**plan['configurations'][name],random_state=plan['seed'])
    return make_pipeline(StandardScaler(),Ridge(alpha=1))

def prediction_file(path,samples,y,preds):
    with path.open('w') as f:
        w=csv.writer(f);w.writerow(['sample_id','group_id','source_class','observed']+MODELS)
        for i,s in enumerate(samples):w.writerow([s['sample_id'],s['group_id'],s['source_class'],y[i]]+[preds[n][i] for n in MODELS])

def main(mode):
    check_freeze();plan=json.loads((DATA/'c3-plan.frozen.json').read_text())
    out=ART/'c3';out.mkdir(exist_ok=True)
    if mode=='select':
        assert not (DATA/'c3-selection.json').exists()
        assert not (out/'selection.started.json').exists(), 'Interrupted selections need explicit recovery audit'
        write(out/'selection.started.json',dict(time=now(),command=' '.join(sys.argv)))
        a,X,C,y=load('train');b,V,D,z=load('validation')
        models={};preds={};ledger=[]
        for n in MODELS:
            m=model(n,plan);m.fit(features(n,X,C),y);p=m.predict(features(n,V,D))
            assert np.isfinite(p).all();models[n]=m;preds[n]=p
            ledger.append(dict(configuration=n,parameters=plan['configurations'][n],seed=plan['seed'],status='success',train_rows=len(a),validation_rows=len(b),validation_MSE=float(np.mean((z-p)**2))))
        control=min(MODELS[:5],key=lambda n:float(np.mean((z-preds[n])**2)))
        selected=min(['full_ridge','full_hgb'],key=lambda n:float(np.mean((z-preds[n])**2)))
        prediction_file(out/'validation_predictions.csv',b,z,preds)
        joblib.dump(models,out/'models.joblib')
        write(DATA/'c3-trial-ledger.json',ledger)
        write(DATA/'c3-selection.json',dict(time=now(),control=control,selected=selected,models_sha256=sha(out/'models.joblib'),validation_predictions_sha256=sha(out/'validation_predictions.csv'),trial_ledger_sha256=sha(DATA/'c3-trial-ledger.json'),refit=False))
        status('C3_selection_completed',['8 fixed configurations fitted on 135 training loci','selection uses 39 validation loci only'],['open exploratory test once','independent metric verification','report'],candidate_budget_used=3,model_configurations_used=8,evidence_paths=[str(DATA/'c3-selection.json')])
        print(json.dumps(ledger,indent=2));print(control,selected)
    elif mode=='evaluate':
        assert not (out/'test.started.json').exists(), 'Test already exposed; no re-opening'
        sel=json.loads((DATA/'c3-selection.json').read_text())
        assert sha(out/'models.joblib')==sel['models_sha256']
        assert sha(DATA/'c3-trial-ledger.json')==sel['trial_ledger_sha256']
        write(out/'test.started.json',dict(time=now(),command=' '.join(sys.argv),purpose='single exploratory holdout; not independent scientific confirmation'))
        a,X,C,y=load('test');models=joblib.load(out/'models.joblib')
        preds={n:models[n].predict(features(n,X,C)) for n in MODELS}
        prediction_file(out/'test_predictions.csv',a,y,preds)
        losses={n:(y-p)**2 for n,p in preds.items()}
        groups=sorted({s['group_id'] for s in a});sizes=np.array([sum(s['group_id']==g for s in a) for g in groups])
        sums=np.array([[sum(losses[n][i] for i,s in enumerate(a) if s['group_id']==g) for g in groups] for n in MODELS])
        rng=np.random.default_rng(plan['seed']);boot=np.empty((10000,len(MODELS)))
        for i in range(10000):
            ix=rng.integers(len(groups),size=len(groups));boot[i]=sums[:,ix].sum(axis=1)/sizes[ix].sum()
        np.save(out/'bootstrap_MSE.npy',boot)
        means={n:float(losses[n].mean()) for n in MODELS}
        c=MODELS.index(sel['control']);m=MODELS.index(sel['selected'])
        delta=means[sel['control']]-means[sel['selected']];relative=delta/means[sel['control']]
        ci=np.quantile(boot[:,c]-boot[:,m],[.025,.975]).tolist()
        relci=np.quantile((boot[:,c]-boot[:,m])/boot[:,c],[.025,.975]).tolist()
        strata={}
        for cls in ('0','1','2'):
            ix=[i for i,s in enumerate(a) if s['source_class']==cls]
            strata[cls]=dict(n=len(ix),MSE={n:float(losses[n][ix].mean()) for n in MODELS}) if ix else dict(n=0)
        success=delta>=.01 and relative>=.05 and ci[0]>0 and means[sel['selected']]<means['class_only']
        res=dict(time=now(),stage='exploratory_pilot',independent_unit='genomic locus component',n_test=len(a),test_components=len(groups),selected=sel,metrics={n:dict(MSE=means[n],MSE_CI95=np.quantile(boot[:,i],[.025,.975]).tolist()) for i,n in enumerate(MODELS)},primary=dict(absolute_MSE_reduction=delta,relative_MSE_reduction=relative,absolute_CI95=ci,relative_CI95=relci,criterion_passed=bool(success)),source_class_strata=strata,model_selection_uncertainty=dict(candidate_test_MSE_range=[min(means[n] for n in ('full_ridge','full_hgb')),max(means[n] for n in ('full_ridge','full_hgb'))],no_class_control_test_MSE_range=[min(means[n] for n in MODELS[:5]),max(means[n] for n in MODELS[:5])]),trials_run=8,paper_candidate=False,limitations=plan['leakage_controls']+['No source continuous activity/precision included: this does not settle the original observed-source directionality transfer question.','Published class annotations are features, not a proposed new biological mechanism.','Target quality n_for_P_resp itself requires enhancer assays: full feature set is retrospective calibration, not a demonstrated low-cost prospective triage tool.','Measurement-replicate covariance and source-class uncertainty unavailable in this processed table; intervals condition on them.'],run=dict(command=' '.join(sys.argv),seed=plan['seed'],environment_sha256=sha(ROOT/'labs/biomed/uv.lock'),code_freeze_sha256=sha(DATA/'c3-code-freeze.json'),plan_sha256=sha(DATA/'c3-plan.frozen.json'),predictions_sha256=sha(out/'test_predictions.csv')))
        write(DATA/'c3-results.json',res);write(out/'results.json',res)
        write(out/'test.completed.json',dict(time=now(),result_sha256=sha(out/'results.json')))
        status('C3_test_evaluated',['single exploratory holdout completed','all 8 models reported'],['independent metric/hash review','Chinese report and scientific disposition'],candidate_budget_used=3,model_configurations_used=8,evidence_paths=[str(DATA/'c3-results.json')])
        print(json.dumps(res,indent=2))
    else:raise ValueError(mode)

if __name__=='__main__':main(sys.argv[1])
