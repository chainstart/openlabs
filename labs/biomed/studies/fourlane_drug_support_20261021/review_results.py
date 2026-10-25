"""Reconstruct persisted results without training or selecting models."""
from common import *
import csv
import gzip
import math
import collections
import numpy as np
import pandas as pd

def integrate_segments(dose,ys,lo,hi,clip):
    # Independent segment-by-segment implementation, no curve_math import.
    x=[math.log10(d) for d in dose]
    y=[min(1,max(0,v)) if clip else v for v in ys]
    area=0.
    assert lo>=x[0]-1e-9 and hi<=x[-1]+1e-9
    for j in range(len(x)-1):
        left=max(x[j],lo);right=min(x[j+1],hi)
        if right<=left:continue
        slope=(y[j+1]-y[j])/(x[j+1]-x[j])
        area+=(right-left)*(y[j]+slope*((left+right)/2-x[j]))
    return area/(hi-lo)

df=pd.read_csv(ART/'sealed/test-curves.csv.gz')
raw=json.loads((ART/'sealed/test-curves-raw.json').read_text())
byid={r['sample_id']:r for r in raw}
errors=[];fitq=[]
for r in df.itertuples(index=False):
    q=byid[r.sample_id];lo,hi=r.common_lo,r.common_hi
    target=integrate_segments(q['target_doses'],q['target_replicates']['3'],lo,hi,True)
    unclipped=integrate_segments(q['target_doses'],q['target_replicates']['3'],lo,hi,False)
    source=sum(integrate_segments(q['source_doses'],y,lo,hi,True) for y in q['source_replicates'].values())/len(q['source_replicates'])
    errors.extend([abs(target-r.target_raw_auc),abs(unclipped-r.target_raw_unclipped_auc),abs(source-r.source_raw_auc)])
    sv=np.var(list(q['source_replicates'].values()));tv=np.var([q['target_replicates'][k] for k in ['1','2']])
    fitq.append({'sample_id':r.sample_id,'structure_key':r.structure_key,'source_r2':1-r.source_rmse**2/sv if sv>0 else None,'target_r2':1-r.target_fit_rmse**2/tv if tv>0 else None,'source_boundary':r.source_fit_boundary,'target_boundary':r.target_fit_boundary})
assert max(errors)<1e-10
pd.DataFrame(fitq).to_csv(ART/'curve-fit-descriptives.csv.gz',index=False)
# Reconstruct main estimand using stdlib CSV and explicitly equal drug weighting.
with gzip.open(ART/'confirmation-predictions.csv.gz','rt') as f:pred={r['sample_id']:r for r in csv.DictReader(f)}
g=collections.defaultdict(list)
with gzip.open(ART/'sealed/test-curves.csv.gz','rt') as f:
    for r in csv.DictReader(f):
        p=pred[r['sample_id']];a,b=float(p['identity_fit']),float(p['hgb_full']);fit,raw=float(r['target_fit_auc']),float(r['target_raw_auc'])
        fg=abs(a-fit)-abs(b-fit);mg=abs(a-raw)-abs(b-raw)
        g[r['structure_key']].append((fg,mg,fg-mg))
means=[sum(sum(t[j] for t in rows)/len(rows) for rows in g.values())/len(g) for j in range(3)]
r=json.loads((ART/'confirmation-results.json').read_text())
for j,key in enumerate(['fit_gain','measured_gain','misalignment']):assert abs(means[j]-r['primary'][key])<1e-12
# No new inference opening: paired comparisons derived from the same saved bootstrap.
boot=pd.read_csv(ART/'bootstrap-primary.csv.gz');comparisons={}
for base in ['identity_raw','affine_fit','rf_leaf20']:
    comparisons[base]={}
    for end in ['target_fit_auc','target_raw_auc','target_raw_unclipped_auc']:
        delta=boot[base+'::'+end]-boot['hgb_full::'+end]
        comparisons[base][end]={'hgb_improvement':r['all_baselines'][base][end]['macro_drug_mae']-r['all_baselines']['hgb_full'][end]['macro_drug_mae'],'paired_two_way_ci95':np.quantile(delta,[.025,.975]).tolist(),'role':'secondary comparison, not primary replacement'}
write(ART/'strong-baseline-comparisons.json',comparisons)
# Actual retained sample audit, without rewriting frozen sample table.
allframes=[]
for split,folder in [('train','development'),('validation','development'),('test','sealed')]:
    a=pd.read_csv(ART/folder/(split+'-curves.csv.gz'),usecols=['sample_id','structure_key','depmap_id','split'])
    a['molecule_id']=a.structure_key;a['cell_line_id']=a.depmap_id;allframes.append(a)
retained=pd.concat(allframes,ignore_index=True);retained.to_csv(DATA/'samples-retained.csv',index=False)
sys_path=ROOT/'openlabs/labs/biomed'
import sys
sys.path.insert(0,str(sys_path))
from tools.split_audit import audit
split=audit(DATA/'samples-retained.csv',independent_unit='molecule',group_columns=['molecule_id','cell_line_id'],strategy='group',project_root=DATA)
assert split['valid'];write(DATA/'split-audit-retained.json',split)
ex=pd.read_csv(ART/'curve-exclusions.csv.gz')
qc=pd.DataFrame(fitq)
frozen=json.loads((DATA/'freeze-ledger.json').read_text())
freeze_ok={k:hashlib.sha256((DATA/k).read_bytes()).hexdigest()==v for k,v in frozen['files'].items()}
assert all(freeze_ok.values())
report={'at':now(),'reviewer':'same agent, independently implemented arithmetic; no claim of independent human/laboratory review','test_rows_reconstructed':len(df),'empirical_integration_max_abs_error':max(errors),'primary_stdlib_reconstruction':dict(zip(['fit_gain','measured_gain','misalignment'],means)),'retained_split_audit_valid':True,'freeze_unchanged':freeze_ok,'exclusion_counts_by_split':ex.groupby(['split','reason']).size().to_dict() if False else [{'split':s,'reason':why,'n':int(n)} for (s,why),n in ex.groupby(['split','reason']).size().items()],'fit_descriptives':{'source_r2_quantiles':qc.source_r2.quantile([.05,.5,.95]).to_dict(),'target_r2_quantiles':qc.target_r2.quantile([.05,.5,.95]).to_dict(),'source_negative_r2_fraction':float((qc.source_r2<0).mean()),'target_negative_r2_fraction':float((qc.target_r2<0).mean()),'source_boundary_fraction':float(qc.source_boundary.mean()),'target_boundary_fraction':float(qc.target_boundary.mean())},'model_training_repeated':False,'confirmation_reopened_for_selection':False,'strong_baseline_comparisons':'strong-baseline-comparisons.json'}
write(ART/'result-review.json',report);write(DATA/'result-review.json',report)
print(json.dumps(report,indent=2))
