"""Checks source score bookkeeping and math without reading new target outcomes."""
from common import *
from prepare_source import check_freeze
from pair_math import METHODS, selected, software_check
from evaluate import software_check as bootstrap_check
import numpy as np
import pandas as pd

check_freeze()
assert not (ART/'confirmation-opened.json').exists()
frozen=json.loads((ART/'models-frozen.json').read_text())
for f,h in frozen['code'].items():assert sha256_file(CODE/f)==h,f
assert sha256_file(ART/'models.joblib')==frozen['model_sha256']
eligible=pd.read_csv(DATA/'external-eligible-identifiers.csv')
selections=[]
for entry in frozen['scores']:
    assert sha256_file(entry['path'])==entry['sha256']
    z=np.load(entry['path'],allow_pickle=False);n=len(z['models']);i=z['i'];j=z['j']
    assert len(i)==n*(n-1)//2 and np.all(i<j)
    assert np.isfinite(z['risks']).all() and np.min(z['risks'])>=0 and np.max(z['risks'])<=1
    assert np.allclose(z['scores'][:,METHODS.index('gap_raw')],abs(z['raw_direction']))
    assert np.allclose(z['scores'][:,METHODS.index('gap_fit')],abs(z['fit_direction']))
    assert np.allclose(z['scores'][:,METHODS.index('additive_mean')],abs(z['mean_direction']))
    assert set(z['models'])==set(eligible[eligible.structure_key==entry['structure_key']].depmap_id)
    for mi,name in enumerate(METHODS):
        for coverage in [.25,.5,.75]:
            ix=selected(z['scores'][:,mi],z['tie'],coverage)
            assert len(ix)==int(len(i)*coverage) and len(set(ix))==len(ix)
            selections.append({'structure_key':entry['structure_key'],'method':name,'coverage':coverage,'n':len(ix),'index_sha256':hashlib.sha256(ix.astype('<i8').tobytes()).hexdigest()})
idx=pd.MultiIndex.from_tuples([('drug','cell1'),('drug','cell2')],names=['structure_key','depmap_id'])
toy=pd.DataFrame({'target_auc':[.1,.8]},index=idx);models=np.array(['cell2','cell1'])
assert toy.loc[('drug',models),'target_auc'].tolist()==[.8,.1]
write(ART/'preopening-selection-hashes.json',selections)
write(ART/'preopening-audit.json',{'at':now(),'new_target_values_read':False,'math':software_check(),'bootstrap_math':bootstrap_check(),
                                'all_source_score_hashes_pass':True,'all_frozen_code_hashes_pass':True,'equal_coverage_pass':True,
                                'target_alignment_toy_pass':True,'n_drugs':len(frozen['scores']),'n_selection_sets':len(selections),
                                'expected_target_rows':len(eligible),'evaluator_sha256':sha256_file(CODE/'evaluate.py'),
                                'known_limitations':['NRFE baseline is curve-level3PL adaptation, not full plateQC.','Training outcome labels historically exposed.','Development field brier is squared probability error to tie-coded labels; external report will explicitly retain this and also show expected binary Brier.','Bootstrap uses fixed selection sets and excludes same-original-cell self-comparisons.']})
print('Preopening audit passed',len(selections),'source-only selection sets')
