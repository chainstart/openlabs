"""Separate loop implementation of revised donor-before-square estimand and paired CI."""
from pathlib import Path
import csv,json,collections,argparse,hashlib
import numpy as np
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args()
r=json.loads((A/'revision-v2/RESULTS_V2.json').read_text());names=['B2_family_mean','B3_family_global_activity','B4_activity_knn'];groups=collections.defaultdict(list)
for x in csv.DictReader((A/'crossnull-matrix-predictions.csv').open()):groups[(x['donor_id'],x['family_pair'],int(x['fold']))].append(x)
means={k:{n:sum(float(x[n]) for x in v)/len(v) for n in names+['coupled_label','disjoint_label']} for k,v in groups.items()};units={}
for d,f,fold in means:
 if (d,f) in units:continue
 units[d,f]={mode+'_'+n:sum((means[d,f,h][n]-means[d,f,h][mode+'_label'])**2 for h in [0,1])/2 for mode in ['coupled','disjoint'] for n in names}
ds=sorted({d for d,f in units});fs=sorted({f for d,f in units});cols=list(next(iter(units.values())));rng=np.random.default_rng(20261024)
def calc(dw,fw):
 mm={k:[] for k in cols};weights=[]
 for i,f in enumerate(fs):
  ix=[(d,f) for d in ds if (d,f) in units and dw[ds.index(d)]>0];ww=[dw[ds.index(d)] for d,f in ix]
  if not ix or fw[i]==0:continue
  weights.append(fw[i])
  for k in cols:mm[k].append(sum(w*units[t][k] for t,w in zip(ix,ww))/sum(ww))
 mm={k:float(np.average(v,weights=weights)) for k,v in mm.items()};gain={mode+'_vs_'+b:100*(mm[mode+'_'+b]-mm[mode+'_'+names[2]])/mm[mode+'_'+b] for mode in ['coupled','disjoint'] for b in names[:2]}
 for b in names[:2]:gain['disjoint_minus_coupled_vs_'+b+'_pp']=gain['disjoint_vs_'+b]-gain['coupled_vs_'+b]
 return mm,gain
mm,gain=calc(np.ones(len(ds)),np.ones(len(fs)));draw=[]
for _ in range(1000):
 dw=rng.multinomial(len(ds),np.ones(len(ds))/len(ds));fw=rng.multinomial(len(fs),np.ones(len(fs))/len(fs));draw.append(calc(dw,fw)[1])
errors=[abs(mm[k]-v) for k,v in r['crossnull_metrics']['mse'].items()]+[abs(gain[k]-v) for k,v in r['crossnull_metrics'].items() if k!='mse'];cierr=max(float(np.max(abs(np.quantile([d[k] for d in draw],[.025,.975])-v))) for k,v in r['paired_crossed_bootstrap_95'].items());assert max(errors)<1e-12 and cierr<1e-10
idx=json.loads((P/'REVIEW_INPUT_INDEX.json').read_text());print(type(idx).__name__)
out={'passed':True,'independent_implementation':'stdlib CSV groups and explicit loops; no import of revision analysis','aligned_mse_and_gain_max_absolute_error':max(errors),'paired_bootstrap_ci_max_absolute_error':cierr,'donor_family_units':len(units),'new_model_fits':0,'not_new_confirmation':True}
Path(args.output).write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
