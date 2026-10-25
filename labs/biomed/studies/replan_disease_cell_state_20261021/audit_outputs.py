"""Semantic reconciliation of units, exclusions, pairs and exposure records."""
from common import *
import numpy as np,pandas as pd

plan=json.loads((DATA/'plan_frozen_v1.json').read_text());opening=json.loads((DATA/'confirmation_open.json').read_text())
for name in ['bulk_io.py','analyse_bulk.py']:
 assert sha(CODE/name)==opening['code_hashes'][name], 'Scientific implementation changed after confirmation opening'
cohorts={};score_names=[c['name'] for c in plan['configurations'][:6]]
for acc in ['GSE184316','GSE199949','GSE150910']:
 meta=pd.read_csv(DATA/f'{acc}_samples_frozen.csv').set_index('sample_id')
 scores=pd.read_csv(ART/f'{acc}_scores.csv').set_index('sample_id')
 assert scores.index.is_unique and set(scores.index)==set(meta.index)
 for col in ['donor_id','diagnosis','eligible_adult','eligible_primary','split','region']:
  assert scores[col].equals(meta.loc[scores.index,col]),(acc,col)
 assert np.isfinite(scores[score_names].to_numpy()).all()
 assert np.allclose(scores.abundance_balance,scores.abundance_ECM-scores.abundance_alveolar)
 assert np.allclose(scores.singscore_bidirectional,scores.singscore_ECM-scores.singscore_alveolar)
 donors=pd.read_csv(ART/f'{acc}_donor_scores.csv').set_index('donor_id')
 expected=scores[scores.eligible_primary].groupby('donor_id')[score_names].mean().sort_index()
 assert set(donors.index)==set(expected.index)
 assert np.allclose(donors.loc[expected.index,score_names],expected,atol=1e-12)
 analysis=json.loads((ART/f'{acc}_analysis.json').read_text())
 assert analysis['primary_adult_donors']==len(expected)
 exclusions=meta[~meta.eligible_adult].reset_index()[['sample_id','donor_id','diagnosis','age']].where(pd.notna(meta[~meta.eligible_adult].reset_index()[['sample_id','donor_id','diagnosis','age']]),None)
 pairfile=ART/f'{acc}_regional_pairs.csv';n_pairs=0
 if pairfile.exists():
  pairs=pd.read_csv(pairfile);n_pairs=len(pairs)
  assert not pairs[['score','sample_a','sample_b']].duplicated().any()
  for name,g in pairs.groupby('score'):
   left=scores.loc[g.sample_a];right=scores.loc[g.sample_b]
   assert np.all(left.donor_id.to_numpy()==right.donor_id.to_numpy())
   assert np.all(left.eligible_adult.to_numpy()&right.eligible_adult.to_numpy())
   delta=np.abs(left[name].to_numpy()-right[name].to_numpy());margin=analysis['by_score'][name]['regional_threshold']
   assert np.allclose(delta,g.abs_difference,atol=1e-12)
   assert np.array_equal(delta>=margin,g.exceeds_margin.to_numpy())
   for dx,gg in g.groupby('diagnosis'):
    per=gg.groupby('donor_id').exceeds_margin.mean()
    regional=analysis['by_score'][name]['regional'][dx]
    assert len(per)==regional['donors']
    assert np.isclose(per.mean(),regional['mean_pair_event_frequency']['mean'])
    if acc=='GSE199949':assert len(gg)==len(per) and int(gg.exceeds_margin.sum())==regional['exact_pair_event']['k']
  expected_pairs=sum(int(n*(n-1)/2) for n in scores[scores.eligible_adult].groupby('donor_id').size())*6
  assert n_pairs==expected_pairs
 if acc=='GSE150910':
  assert scores.index.size==scores.donor_id.nunique()
  assert all(np.isclose(e['disease_effect']['unadjusted']['donor_to_naive_se_ratio'],1) for e in analysis['by_score'].values())
 cohorts[acc]=dict(scored_samples=len(scores),scored_donors=scores.donor_id.nunique(),adult_primary_samples=int(scores.eligible_primary.sum()),adult_primary_donors=len(expected),adult_excluded_sample_ids=exclusions.sample_id.tolist(),adult_excluded_donors=exclusions.donor_id.unique().tolist(),pair_rows_across6scores=n_pairs,unit_and_mapping_checks=True,score_sha256=sha(ART/f'{acc}_scores.csv'))
events=[json.loads(s) for s in (ART/'executions.jsonl').read_text().splitlines()]
success=[e for e in events if e['returncode']==0]
countscore=sum(e['command'][-2:]==['score','GSE199949'] for e in success)
countanalysis=sum(e['command'][-2:]==[str(CODE/'analyse_bulk.py'),'GSE199949'] for e in success)
countopen=sum(e['command'][-1]==str(CODE/'open_confirmation.py') for e in success)
assert (countscore,countanalysis,countopen)==(1,1,1)
record=dict(at=now(),cohorts=cohorts,one_confirmation_open_and_analysis=True,scientific_code_unchanged_since_open=True,new_scientific_configurations=False,all_pass=True,script_sha256=sha(Path(__file__)),scope='Accounting and deterministic consistency checks only; does not establish biological validity or remove library confounding')
atomic(ART/'output_semantic_audit.json',record);print(json.dumps(record))
