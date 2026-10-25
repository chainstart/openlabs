"""Check delivery consistency without recomputing or modifying model results."""
from common import *
import re
import numpy as np
import pandas as pd

def main():
    r=json.loads((ART/'RESULTS.json').read_text());c=json.loads((ART/'confirmation-results.json').read_text());report=(ART/'FINAL_REPORT.md').read_text()
    assert r['primary']==c['primary'] and r['all_baselines']==c['all_baselines']
    assert r['paper_candidate'] is False and r['scientific_disposition']=='negative_registered_external_test'
    assert r['ancestry_audit']['donor_parent_components']==439
    assert r['counts']=={'drug_structures':50,'cell_models':444,'drug_cell_pairs':15674,'cell_comparisons':2600017,'source_compound_plates':26}
    for name,v in c['all_baselines'].items():
        assert f'`{name}`' in report and f"{100*v['error_at_50pct']:.3f}" in report
    assert abs(c['primary']['benefit']-(c['all_baselines']['gap_raw']['error_at_50pct']-c['all_baselines']['hgb_full']['error_at_50pct']))<1e-15
    ledger=json.loads((DATA/'all-trials-ledger.json').read_text());assert len(ledger['current_campaign']['registered_configurations'])==12
    assert sum(t['type']=='single_external_confirmation' for t in ledger['current_campaign']['trials'])==1
    assert json.loads((ART/'independent-statistical-review.json').read_text())['all_passed']
    assert json.loads((ART/'identity-and-model-audit.json').read_text())['all_checks_passed']
    missing=[]
    for dest in re.findall(r'\]\(([^)]+)\)',report):
        if not dest.startswith('https://'):
            p=Path(dest) if dest.startswith('/') else ART/dest
            if not p.exists():missing.append(str(p))
    assert not missing,missing
    for fn in ['FINAL_REPORT.md','RESULTS.json','research_status.json']:assert (ART/fn).read_bytes()==(DATA/fn).read_bytes(),fn
    # Full secondary tables must be retained, with no additional model fits.
    strata=pd.read_csv(ART/'descriptive-strata-summary.csv');assert set(strata.dimension)=={'training_drug','training_cells','source_pool','tissue'}
    assert set(strata.method)=={'gap_raw','hgb_full'}
    out={'at':now(),'all_passed':True,'final_primary_and_baselines_identical_to_single_confirmation':True,'report_links_exist':True,'all_11_methods_in_report':True,'budget_12_configurations':True,'one_confirmation':True,'artifact_data_deliveries_match':True,'prespecified_descriptive_tables_retained':True,'report_sha256':sha256_file(ART/'FINAL_REPORT.md'),'results_sha256':sha256_file(ART/'RESULTS.json'),'code_sha256':sha256_file(__file__)}
    write(ART/'delivery-validation.json',out);print(json.dumps(out,indent=2))
if __name__=='__main__':main()
