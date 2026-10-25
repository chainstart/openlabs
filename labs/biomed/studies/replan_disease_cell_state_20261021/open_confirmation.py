"""Once-only opening of the preregistered new bulk holdout; old holdout untouched."""
from bulk_io import *
assert not (DATA/'confirmation_open.json').exists()
assert not (ART/'GSE199949_scores.csv').exists()
for acc in ['GSE184316','GSE150910']:
 assert (ART/f'{acc}_analysis.json').exists(), 'Finish fixed development/context first'
 assert sha(DATA/f'{acc}_samples_frozen.csv')==PLAN['sample_tables'][acc]['sha256']
verify=json.loads((DATA/'software_verification.json').read_text());assert verify['all_pass']
for name,h in verify['code_hashes'].items():assert sha(CODE/name)==h,(name,'code changed after tests')
fmt=json.loads((DATA/'GSE199949_format_audit.json').read_text())
assert fmt['matched_samples']==42 and fmt['samples']==42
assert sha(DATA/'GSE199949_samples_frozen.csv')==PLAN['sample_tables']['GSE199949']['sha256']
verify_payload('GSE199949')
audit=json.loads((DATA/'split_and_independence_audit.json').read_text())
assert (DATA/'source_design_review.json').exists()
record=dict(at=now(),accession='GSE199949',scope='All fixed6score formulas and fixed3age/sex contrasts; one frozen primary adultIPF paired balance endpoint; no tuning',plan_sha256=sha(DATA/'plan_frozen_v1.json'),code_hashes={p.name:sha(p) for p in CODE.glob('*.py')},payload_sha256=sha(ART/'payload'/FILES['GSE199949']),gene_universe_sha256=sha(DATA/'gene_universe_frozen.csv'),sample_table_sha256=sha(DATA/'GSE199949_samples_frozen.csv'),source_audit_sha256=sha(DATA/'source_design_review.json'),independence_audit_sha256=sha(DATA/'split_and_independence_audit.json'),development_results_sha256={acc:sha(ART/f'{acc}_analysis.json') for acc in ['GSE184316','GSE150910']},source_gate='Official raw integer count file with audit; distinct original experimental tissue procurement supported; not read-level revalidation',limitations=['Two library batches with missing sample allocation: no purely biological regional attribution','Different systematic region selection across studies','Only9knownadultIPFdonors; lack of support not equivalence','Same-gene published literature and overall source findings already known; holdout is prospective analyst score access, not blinded primary data collection'],old_confirmation_opened=False,paper_candidate=False)
atomic(DATA/'confirmation_open.json',record);atomic(ART/'confirmation_open.json',record)
print(json.dumps(record))
