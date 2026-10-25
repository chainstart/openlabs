"""Train only on exposed PRISM development; freeze scores before external effects."""
from common import *
from prepare_source import check_freeze
from pair_math import *
import joblib
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.isotonic import IsotonicRegression
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

def summarize(frame,models,mean_model):
    rows=[]
    for key,g in frame.groupby('structure_key',sort=True):
        if len(g)<20:continue
        df,i,j,x,tie=make_pairs(g)
        scores,risks,directions=get_scores(df,i,j,x,models,mean_model)
        y=df.target_auc.to_numpy();diff=y[i]-y[j]
        for method in METHODS:
            err=method_error(method,directions,diff)
            rec={'structure_key':key,'method':method,'n_cells':len(df),'n_pairs':len(i),'all_pair_error':float(err.mean())}
            for c in [.25,.5,.75]:rec['error_'+str(c)]=float(err[selected(scores[method],tie,c)].mean())
            if method in risks:rec['brier']=float(np.mean((risks[method]-method_error('gap_raw',directions,diff))**2))
            rows.append(rec)
    return pd.DataFrame(rows)

def main():
    check_freeze()
    assert not (ART/'models-frozen.json').exists()
    assert not (ART/'confirmation-opened.json').exists()
    assert json.loads((DATA/'plan-frozen.json').read_text())['features']==FEATURES
    write(ART/'pair-software-checks.json',software_check())
    preparation=json.loads((ART/'source-preparation-complete.json').read_text())
    for f,h in preparation['files'].items():assert sha256_file(ART/f)==h,f
    data=pd.read_csv(ART/'development-features.csv.gz')
    train=data[data.role=='train'];validation=data[data.role=='validation']
    assert set(train.structure_key).isdisjoint(validation.structure_key)
    assert set(train.depmap_id).isdisjoint(validation.depmap_id)
    blocks=[];targets=[];weights=[];audit=[]
    for key,g in train.groupby('structure_key',sort=True):
        if len(g)<20:continue
        df,i,j,x,tie=make_pairs(g,cap=2000)
        a=df.raw_auc.to_numpy();b=df.target_auc.to_numpy()
        y=ranking_error(a[i]-a[j],b[i]-b[j])
        blocks.append(x);targets.append(y);weights.append(np.full(len(y),1/len(y)))
        audit.append({'structure_key':key,'n_cells':len(df),'sampled_pairs':len(y),'available_pairs':len(df)*(len(df)-1)//2})
    X=pd.concat(blocks,ignore_index=True);y=np.concatenate(targets);w=np.concatenate(weights);w*=len(w)/w.sum()
    params=dict(loss='squared_error',max_iter=200,max_leaf_nodes=15,min_samples_leaf=50,l2_regularization=5,learning_rate=.05,early_stopping=False,random_state=20261021)
    models={
     'isotonic_gap':IsotonicRegression(increasing=False,out_of_bounds='clip'),
     'ridge_full':Pipeline([('imputer',SimpleImputer(strategy='median')),('scaler',StandardScaler()),('ridge',Ridge(alpha=10))]),
     'hgb_gap':Pipeline([('imputer',SimpleImputer(strategy='median')),('hgb',HistGradientBoostingRegressor(**params))]),
     'hgb_full':Pipeline([('imputer',SimpleImputer(strategy='median')),('hgb',HistGradientBoostingRegressor(**params))]),
     'hgb_dose':Pipeline([('imputer',SimpleImputer(strategy='median')),('hgb',HistGradientBoostingRegressor(**params))])}
    started=now()
    for name,model in models.items():
        print('Fit',name,'rows',len(y),flush=True)
        if name=='isotonic_gap':model.fit(X.raw_gap.to_numpy(),y,sample_weight=w)
        elif name=='ridge_full':model.fit(X[FEATURES],y,ridge__sample_weight=w)
        else:
            columns=['raw_gap'] if name=='hgb_gap' else DOSE_FEATURES if name=='hgb_dose' else FEATURES
            model.fit(X[columns],y,hgb__sample_weight=w)
    base=float(train.target_auc.mean())
    cell=(train.groupby('depmap_id').target_auc.mean()-base).to_dict()
    drug=(train.groupby('structure_key').target_auc.mean()-base).to_dict()
    mean_model=(base,cell,drug)
    joblib.dump({'models':models,'mean_model':mean_model},ART/'models.joblib')
    v=summarize(validation,models,mean_model)
    v.to_csv(ART/'development-validation-by-drug.csv',index=False)
    summary=v.groupby('method')[['error_0.25','error_0.5','error_0.75','all_pair_error','brier']].mean()
    selected_secondary=summary.loc[LEARNED,'error_0.5'].idxmin()
    write(DATA/'development-results.json',{'at':now(),'exposure':'All PRISM outcomes historical development; not independent scientific confirmation','train_curves':len(train),'validation_curves':len(validation),'training_drugs':len(audit),'training_pairs':len(y),'seed':20261021,'models':summary.to_dict(orient='index'),'primary':'hgb_full','validation_selected_secondary':selected_secondary,'sampling':audit})
    # Only target eligibility identifiers may be read here, not target values.
    target_metadata=pd.read_csv(DATA/'external-eligible-identifiers.csv')
    source=pd.read_csv(ART/'external-source-features.csv.gz')
    source=source.merge(target_metadata[['structure_key','depmap_id']],on=['structure_key','depmap_id'],validate='one_to_one')
    outdir=ART/'frozen-source-scores';outdir.mkdir(exist_ok=True)
    inventory=[];npairs=0
    for key,g in source.groupby('structure_key',sort=True):
        assert len(g)>=20
        df,i,j,x,tie=make_pairs(g)
        scores,risks,directions=get_scores(df,i,j,x,models,mean_model)
        path=outdir/(key+'.npz')
        # Source-only indices and predictions. No new target outcomes saved here.
        np.savez_compressed(path,models=df.depmap_id.astype(str).to_numpy(dtype=str),i=i.astype(np.int32),j=j.astype(np.int32),tie=tie,
                            scores=np.column_stack([scores[m] for m in METHODS]),
                            risks=np.column_stack([risks[m] for m in LEARNED]),
                            raw_direction=directions['raw'],fit_direction=directions['fit'],mean_direction=directions['mean'])
        n=len(i);npairs+=n
        inventory.append({'structure_key':key,'drug':df.drug.iloc[0],'n_cells':len(df),'n_comparisons':n,'path':str(path),'sha256':sha256_file(path),'source_plate':df.source_plate.iloc[0]})
        print('Frozen source scores',df.drug.iloc[0],len(df),n,flush=True)
    frozen={'started_utc':started,'finished_utc':now(),'new_target_effects_seen':False,'model_sha256':sha256_file(ART/'models.joblib'),
            'plan_sha256':sha256_file(DATA/'plan-frozen.json'),'target_eligibility_sha256':sha256_file(DATA/'external-eligible-identifiers.csv'),
            'source_features_sha256':sha256_file(ART/'external-source-features.csv.gz'),
            'code':{f:sha256_file(CODE/f) for f in ['models.py','pair_math.py','curve_math.py','prepare_source.py','prepare_target.py']},
            'primary':'hgb_full','validation_selected_secondary':selected_secondary,'methods':METHODS,'learned':LEARNED,
            'n_predictor_configurations':11,'n_curve_configurations':1,'seed':20261021,'n_external_comparisons':npairs,'scores':inventory}
    write(ART/'models-frozen.json',frozen)
    ledger=json.loads((DATA/'all-trials-ledger.json').read_text())
    ledger['current_campaign']['trials'].append({'at':now(),'type':'development_fit_and_source_prediction','configurations_run':12,'seed':20261021,'models':METHODS,'training_pairs':len(y),'external_scores_only':npairs,'validation_selected_secondary':selected_secondary,'failures':[]})
    write(DATA/'all-trials-ledger.json',ledger)
    status('models_and_source_scores_frozen',['source preprocessing','sealed target preprocessing','all12 configurations','development validation','external scores frozen without target effects'],['pre-opening implementation review','one external evaluation','result review','Chinese report'],[str(ART/'models-frozen.json'),str(DATA/'development-results.json')])
    print(summary.to_string(),flush=True)

if __name__=='__main__':main()
