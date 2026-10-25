"""Check report/ledger consistency without re-reading raw confirmation arrays."""
from common import *
import re,math
guard_check();final='--final' in sys.argv
rp=ART/('FINAL_REPORT.md' if final else 'REPORT_DRAFT.md')
jp=ART/('RESULTS.json' if final else 'RESULTS.draft.json')
report=rp.read_text();res=json.loads(jp.read_text());ledger=json.loads((DATA/'complete-trial-ledger.json').read_text())
assert len(res['baselines'])==12 and res['trials_run']==12
assert len(ledger['current_trials'])==12 and all(t['status']=='evaluated' for t in ledger['current_trials'])
assert all(not c['primary']['passes'] for c in res['contexts'].values())
assert res['paper_candidate'] is False and 'paper_candidate=false' in report
assert res['run']['environment_SHA256']==sha(DATA/'environment.lock')
assert len(res['run']['code_sha256'])==len(list(pathlib.Path(__file__).parent.glob('*.py')))
for n,h in res['run']['code_sha256'].items():assert sha(pathlib.Path(__file__).parent/n)==h
for ctx,c in res['contexts'].items():
    for kind in ['point','risk50']:
        metric='MSE' if kind=='point' else 'affine_MSE'
        for k,v in c[kind].items():
            assert f'{v[metric]:.6f}' in report
            assert f'{v["CI95"][0]:.6f}' in report and f'{v["CI95"][1]:.6f}' in report
    for trial in ledger['current_trials']:
        kind='point' if trial['kind']=='point' else 'risk50'
        assert trial['confirmation'][ctx]==c[kind][trial['name']]
links=re.findall(r'\]\((/[^)]+)\)',report)
for link in links:assert pathlib.Path(link).exists(),link
assert '915' in report and '确认后的数值纠错' in report and 'HTTP' in report and '11656' in report
assert res['run']['freeze_sha256']==sha(DATA/'freeze.json')
result=dict(time=now(),stage='final' if final else 'draft',local_links_checked=len(links),all_12_baselines_and_CI_strings_present=True,
    ledger_matches_results=True,code_and_lock_hashes_match=True,material_caveats_present=True,raw_holdout_reopened=False,
    report_sha256=sha(rp),results_sha256=sha(jp))
write(DATA/('delivery-check.json' if final else 'delivery-check-draft.json'),result)
print(result)
