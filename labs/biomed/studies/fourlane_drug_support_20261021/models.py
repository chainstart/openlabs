"""Frozen eleven configurations; development first, confirmation requires saved models."""
from common import *
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline

DOSE=['log_source_min','log_source_max','log_target_min','log_target_max','common_lo','common_hi','support_width']
FEATURES=['source_fit_auc','source_raw_auc','source_bottom','source_logec50','source_slope','source_rmse']+[f'source_point{i}' for i in range(5)]+['source_rep_auc_sd','source_nrep']+DOSE
NAMES=['identity_fit','affine_fit','drug_mean','cell_mean','additive_mean','hgb_full','hgb_dose_only','rf_leaf5','rf_leaf20','identity_raw','affine_raw']

def train(df):
    y=df.target_fit_auc
    models={'global':float(y.mean()),'drug':df.groupby('structure_key').target_fit_auc.mean().to_dict(),'cell':df.groupby('depmap_id').target_fit_auc.mean().to_dict()}
    for name,col in [('affine_fit','source_fit_auc'),('affine_raw','source_raw_auc')]:
        models[name]=LinearRegression().fit(df[[col]],y)
    for name in ['hgb_full','hgb_dose_only']:
        cols=DOSE if name=='hgb_dose_only' else FEATURES
        models[name]=make_pipeline(SimpleImputer(strategy='median'),HistGradientBoostingRegressor(max_iter=200,max_leaf_nodes=31,min_samples_leaf=30,l2_regularization=5,learning_rate=.05,early_stopping=False,random_state=20261021)).fit(df[cols],y)
    for leaf in [5,20]:
        models[f'rf_leaf{leaf}']=make_pipeline(SimpleImputer(strategy='median'),RandomForestRegressor(n_estimators=200,min_samples_leaf=leaf,max_features=1.,n_jobs=2,random_state=20261021)).fit(df[FEATURES],y)
    return models

def predict(df,models):
    p=pd.DataFrame({'sample_id':df.sample_id})
    p['identity_fit']=df.source_fit_auc;p['identity_raw']=df.source_raw_auc
    p['drug_mean']=df.structure_key.map(models['drug']).fillna(models['global'])
    p['cell_mean']=df.depmap_id.map(models['cell']).fillna(models['global'])
    p['additive_mean']=p.drug_mean+p.cell_mean-models['global']
    for name,col in [('affine_fit','source_fit_auc'),('affine_raw','source_raw_auc')]:p[name]=models[name].predict(df[[col]])
    for name in ['hgb_full','hgb_dose_only','rf_leaf5','rf_leaf20']:
        p[name]=models[name].predict(df[DOSE if name=='hgb_dose_only' else FEATURES])
    assert np.isfinite(p[NAMES].to_numpy()).all()
    return p

def develop():
    assert not (ART/'confirmation-opened.json').exists(),'Do not retrain after confirmation'
    assert not (ART/'models.joblib').exists(),'Already trained; inspect existing ledger'
    tr=pd.read_csv(ART/'development/train-curves.csv.gz');va=pd.read_csv(ART/'development/validation-curves.csv.gz')
    assert not set(tr.structure_key)&set(va.structure_key)
    assert not set(tr.depmap_id)&set(va.depmap_id)
    started=now();models=train(tr);joblib.dump(models,ART/'models.joblib')
    pred=predict(va,models);pred.to_csv(ART/'development/validation-predictions.csv.gz',index=False)
    results={}
    for name in NAMES:
        results[name]={}
        for endpoint in ['target_fit_auc','target_raw_auc','target_raw_unclipped_auc']:
            e=abs(pred[name]-va[endpoint]);results[name][endpoint]=float(e.groupby(va.structure_key).mean().mean())
    trees=['hgb_full','rf_leaf5','rf_leaf20']
    chosen=min(trees,key=lambda n:results[n]['target_fit_auc'])
    ledger={'started_utc':started,'finished_utc':now(),'configurations':NAMES,'n_prediction_configurations':11,'n_curve_processing_configurations':1,'max_configurations':12,'seed':20261021,'failures':[],'training_pairs':len(tr),'validation_pairs':len(va),'validation_selected_tree':chosen,'selection_endpoint':'macro_drug fitted_AUC MAE; primary remains hgb_full','metrics':results,'model_sha256':hashlib.sha256((ART/'models.joblib').read_bytes()).hexdigest(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write(DATA/'trial-ledger.json',ledger);write(ART/'development-results.json',ledger)
    print(json.dumps(ledger,indent=2),flush=True)

if __name__=='__main__':develop()
