"""Review exact identities, learned preprocessing and model budgets without retuning."""
from common import *
from metadata import OLD_ART, OLD_DATA
from pair_math import make_pairs, FEATURES, DOSE_FEATURES
import numpy as np
import pandas as pd
import joblib
from rdkit import Chem, RDLogger

def main():
    RDLogger.DisableLog('rdApp.error')
    ids=pd.read_csv(DATA/'external-eligible-identifiers.csv')
    linkage=pd.read_csv(DATA/'ctrp-compound-identity.csv').set_index('structure_key')
    old=pd.read_csv(OLD_DATA/'paired-compound-support.csv').set_index('structure_key')
    records=[]
    for key in sorted(ids.structure_key.unique()):
        a=linkage.loc[key];b=old.loc[key]
        mol1=Chem.MolFromSmiles(a.canonical_smiles);mol2=Chem.MolFromSmiles(b.canonical_smiles)
        assert Chem.MolToSmiles(mol1,isomericSmiles=True)==Chem.MolToSmiles(mol2,isomericSmiles=True)
        ik1=Chem.MolToInchiKey(mol1);ik2=Chem.MolToInchiKey(mol2);assert ik1==ik2
        records.append({'structure_key':key,'master_name':a.drug,'original_ctrp_name':a.ctrp_original_names,'original_ctrp_broad_id':a.ctrp_broad_ids,'full_inchikey':ik1})
    pd.DataFrame(records).to_csv(DATA/'independent-chemical-key-audit.csv',index=False)
    cells=pd.read_csv(DATA/'cell-linkage.csv')
    actual=cells[cells.depmap_id.isin(ids.depmap_id)]
    assert not actual.depmap_id.duplicated().any() and not actual.cell_line.duplicated().any()
    assert actual.passed_str_profiling.all()
    assert (actual.ccle_name.str.split('_').str[0]==actual.cell_line).all()
    dev=pd.read_csv(ART/'development-features.csv.gz')
    train=dev[dev.role=='train'];val=dev[dev.role=='validation']
    assert set(train.structure_key).isdisjoint(val.structure_key)
    assert set(train.depmap_id).isdisjoint(val.depmap_id)
    blocks=[];n=[]
    for key,g in train.groupby('structure_key',sort=True):
        if len(g)<20:continue
        _,_,_,x,_=make_pairs(g,cap=2000);blocks.append(x);n.append(len(x))
    X=pd.concat(blocks,ignore_index=True)
    bundle=joblib.load(ART/'models.joblib');models=bundle['models']
    model_audits={}
    for name in ['ridge_full','hgb_full','hgb_gap','hgb_dose']:
        columns=['raw_gap'] if name=='hgb_gap' else DOSE_FEATURES if name=='hgb_dose' else FEATURES
        imputer=models[name].named_steps['imputer']
        median=np.nanmedian(X[columns].to_numpy(),axis=0)
        assert np.allclose(imputer.statistics_,median,rtol=0,atol=1e-12,equal_nan=True)
        a={'imputation_train_only_verified':True,'n_features':len(columns),'columns':columns}
        if name.startswith('hgb'):
            hgb=models[name].named_steps['hgb']
            a['hyperparameters']={k:hgb.get_params()[k] for k in ['max_iter','max_leaf_nodes','min_samples_leaf','l2_regularization','learning_rate','early_stopping','random_state']}
            a['n_iter']=hgb.n_iter_;assert hgb.n_iter_==200
        else:a['alpha']=models[name].named_steps['ridge'].alpha
        model_audits[name]=a
    assert model_audits['hgb_full']['hyperparameters']==model_audits['hgb_gap']['hyperparameters']==model_audits['hgb_dose']['hyperparameters']
    overlap={'external_drugs_seen_in_development_training':len(set(ids.structure_key)&set(train.structure_key)),
             'external_drugs_only_in_development_validation':len(set(ids.structure_key)&set(val.structure_key)),
             'external_models_seen_in_development_training':len(set(ids.depmap_id)&set(train.depmap_id)),
             'external_models_not_in_development_training':len(set(ids.depmap_id)-set(train.depmap_id)),
             'external_exact_pairs_seen_in_development_training':len(set(zip(ids.structure_key,ids.depmap_id))&set(zip(train.structure_key,train.depmap_id)))}
    source=pd.read_csv(ART/'external-source-features.csv.gz').merge(ids[['structure_key','depmap_id']],on=['structure_key','depmap_id'],validate='one_to_one')
    result={'at':now(),'chemical_keys_verified':len(records),'unique_cell_model_links_verified':len(actual),
            'cell_limit':'Source has official DepMap ModelID; target author table has standardized names, not original CTRP master_ccl_id. Exact unique name mapping is verified, not an independent STR reauthentication of target cells.',
            'upstream_limit':'Two screening experiments, same institution and source cell identities; not independent laboratory/patient cohorts.',
            'development_training_curves':len(train),'development_validation_curves':len(val),'development_training_drugs':len(n),'sampled_training_comparisons':len(X),
            'overlap':overlap,'models':model_audits,'source_fit_failures_retained_in_external':int(source.fit_failed.sum()),
            'source_fit_failures_in_historical_development_training':int(train.fit_failed.sum()),
            'population_shift':'Historical old fit-complete development excluded failed curves; new raw-endpoint external retains failures. This limits broad negative-method claims; no post-hoc removal or model refit performed.',
            'budget':{'predictors':11,'curve_configuration':1,'max':12,'seed':20261021,'new_configurations_in_this_review':0},
            'all_checks_passed':True,'code_sha256':sha256_file(__file__)}
    write(ART/'identity-and-model-audit.json',result)
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
