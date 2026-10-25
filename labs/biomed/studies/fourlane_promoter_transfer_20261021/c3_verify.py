"""Independent arithmetic and provenance review of saved results, no test reopening."""
from common import *
import csv, math, zipfile, gzip, collections
import numpy as np
from xlsx_stream import Workbook
from c3_metadata import table

def mse(rows,name):return math.fsum((float(r['observed'])-float(r[name]))**2 for r in rows)/len(rows)
out=ART/'c3';res=json.loads((DATA/'c3-results.json').read_text())
with (out/'test_predictions.csv').open() as f:rows=list(csv.DictReader(f))
with (out/'validation_predictions.csv').open() as f:val=list(csv.DictReader(f))
ledger=json.loads((DATA/'c3-trial-ledger.json').read_text())
checks={};models=list(res['metrics'])
for n in models:checks['test_MSE_'+n]=abs(mse(rows,n)-res['metrics'][n]['MSE'])<1e-12
for trial in ledger:checks['validation_MSE_'+trial['configuration']]=abs(mse(val,trial['configuration'])-trial['validation_MSE'])<1e-12
for p,h in json.loads((DATA/'c3-freeze-hashes.json').read_text()).items():checks['freeze_'+p]=sha(p)==h
for p,h in json.loads((DATA/'c3-code-freeze.json').read_text()).items():checks['code_'+p]=sha(p)==h
checks['single_test_completed']=(out/'test.started.json').exists() and (out/'test.completed.json').exists()
boot=np.load(out/'bootstrap_MSE.npy');sel=res['selected']['selected'];ctrl=res['selected']['control']
ci=np.quantile(boot[:,models.index(ctrl)]-boot[:,models.index(sel)],[.025,.975])
checks['primary_CI_saved_bootstrap']=np.allclose(ci,res['primary']['absolute_CI95'],rtol=0,atol=1e-12)
simple_delta=mse(rows,'class_only')-mse(rows,sel)
simple_ci=np.quantile(boot[:,models.index('class_only')]-boot[:,models.index(sel)],[.025,.975]).tolist()

# Secondary arithmetic check using a different implementation of group sampling.
groups=sorted({r['group_id'] for r in rows});bygroup={g:[r for r in rows if r['group_id']==g] for g in groups}
rng=np.random.default_rng(20261021);first=[]
for j in range(100):
    sampled=[r for ix in rng.integers(len(groups),size=len(groups)) for r in bygroup[groups[ix]]]
    first.append([mse(sampled,n) for n in models])
checks['bootstrap_100_explicit_row_resamples']=np.allclose(first,boot[:100],atol=1e-12,rtol=0)

# Compare published supplement Table S4 with saved author-repository endpoint table.
# This is a post-evaluation provenance check, never a second model fit or test evaluation.
w=Workbook(ART/'payload/tan-supplement-tables.xlsx');pub={};header=None
for row in w.rows('Table S4'):
    if row and row[0]=='promoter':header=row;continue
    if header and row and row[0] and not str(row[0]).startswith('#'):pub[row[0]]=dict(zip(header,row))
w.close()
repo={r['promoter']:r for r in table('tan_500P_annotations.txt')}
numeric=[];seq_errors=[];missing=[]
for name,r in repo.items():
    if name not in pub:missing.append(name);continue
    if r['seq'].upper()!=str(pub[name].get('seq','')).upper():seq_errors.append(name)
    for col in ('P_resp','P_basal (log2)'):
        try:a=float(r[col]);b=float(pub[name][col])
        except (ValueError,TypeError,KeyError):continue
        if math.isfinite(a) and math.isfinite(b):numeric.append(abs(a-b))
checks['supplement_sequences_match']=not missing and not seq_errors
comparison=dict(published_rows=len(pub),repo_rows=len(repo),missing=missing,sequence_mismatch=seq_errors,finite_numeric_comparisons=len(numeric),max_absolute_numeric_difference=max(numeric) if numeric else None)
checks['supplement_numeric_match_roundoff']=bool(numeric) and max(numeric)<1e-6

structures=[]
for p in (ART/'payload').iterdir():
    if p.suffix=='.zip':structures.append(dict(file=p.name,valid_zip=zipfile.is_zipfile(p),scientific_use='none' if not zipfile.is_zipfile(p) else 'archive'))
    elif p.suffix=='.gz':
        try:
            with gzip.open(p,'rb') as f:
                while f.read(1048576):pass
            valid=True
        except Exception:valid=False
        structures.append(dict(file=p.name,valid_gzip=valid))
review=dict(time=now(),passed=bool(all(checks.values())),checks={k:bool(v) for k,v in checks.items()},supplement_comparison=comparison,archive_structural_audit=structures,
 strongest_simple_comparison=dict(comparator='class_only',selected=sel,absolute_MSE_reduction=simple_delta,relative_MSE_reduction=simple_delta/mse(rows,'class_only'),absolute_CI95=simple_ci,interpretation='Post-outcome descriptive uncertainty for frozen required comparator; not new confirmation or endpoint selection.'),
 limitations=['Supplement verification does not establish independence: it is the same original data in two releases.','Current campaign files were verified; unsynced earlier Agarwal and QUASARR experimental payloads were not rerun.'])
write(DATA/'c3-independent-review.json',review)
print(json.dumps(review,indent=2))
assert review['passed'], 'Review mismatch; retain results but investigate before reporting'
