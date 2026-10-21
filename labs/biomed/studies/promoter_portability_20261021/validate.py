from common import *
from xlsx import sheets
import sys,csv,gzip,re,collections
import numpy as np,pandas as pd
sys.path.insert(0,str(CODE.parents[1]))
from tools.dataset_intake import validate_manifest
from tools.split_audit import audit
from run import boot,metrics
status('validation','Frozen primary completed; proximal subset inconclusive; identity outperforms learned selection','Independent payload/workbook arithmetic checks and report')
checks={};manifests=[]
for p in sorted((ART/'intakes').glob('*/manifest.json')):
 m=json.loads(p.read_text());errors=validate_manifest(m,verify_payload=True);assert not errors,(p,errors);manifests.append(dict(path=str(p),sha256=sha(p),payload_sha256=m['sha256'],bytes=m['bytes']))
checks['payload_manifests']=manifests
s=pd.read_csv(PROJECT/'samples.csv');a=audit(PROJECT/'samples.csv',independent_unit='molecule',group_columns=['molecule_id','locus_id','block_id','homology_group','canonical_sequence_sha256'],strategy='group',project_root=PROJECT);assert a['valid'];checks['split_recomputed']=a
w=sheets(ART/'intakes/quasarr-moesm6/source.xlsx');parity=[]
for p in (ART/'intakes').glob('gse310760*/data.tsv.gz'):
 context='pMYC' if '-pmyc-' in p.parent.name else 'pGAPDH' if '-pgapdh-' in p.parent.name else 'pAPOBEC3F' if '-papobec3f-' in p.parent.name else None
 name=f'QUASARR_{context}_paBC_logFC' if context else 'QUASARR_paBC_logFC';table={}
 for row in w[name]:
  rr={re.sub('[0-9]','',k):v for k,v in row.items()}
  if rr.get('A','').endswith(('.fwd','.rev')):table[rr['A']]=rr
 n=0;diff=0
 with gzip.open(p,'rt') as f:
  for r in csv.DictReader(f,delimiter='\t'):
   if r['Element'] not in table:raise AssertionError('workbook missing element')
   for k,col in [('DNA1','B'),('DNA2','C'),('RNA1','D'),('RNA2','E')]:
    x,y=float(r[k]),float(table[r['Element']][col]);diff=max(diff,abs(x-y)/(1+abs(x)))
   n+=1
 assert diff<1e-10
 parity.append(dict(context=context or 'original',rows=n,max_relative_count_discrepancy=diff))
checks['publisher_GEO_count_parity']=parity
pred=pd.read_csv(ART/'test-predictions.csv');r=json.loads((PROJECT/'results.json').read_text());allmetrics={}
for label in ['primary_context_transfer','same_mapping']:
 y=pred[label+'_observed'].to_numpy();allmetrics[label]={}
 for n in json.loads((PROJECT/'plan.json').read_text())['baselines']:
  mse=float(np.mean((y-pred[label+'_'+n])**2));assert abs(mse-r['metrics'][label]['metrics'][n]['mse'])<1e-12
  allmetrics[label][n]=mse
checks['prediction_arithmetic_verified']=allmetrics
# Post-outcome diagnostic comparisons; no new models, exclusions or labels.
y=pred.primary_context_transfer_observed.to_numpy();learned=pred.primary_context_transfer_full_hgb.to_numpy();ident=pred.primary_context_transfer_identity_delta.to_numpy();nu=pred.primary_context_transfer_nuisance_ridge.to_numpy();groups=pred.homology_group.to_numpy()
diag=dict(status='post-outcome descriptive diagnostic; no model selection or new configurations',learned_vs_direct_source=dict(relative_improvement=1-np.mean((y-learned)**2)/np.mean((y-ident)**2),bootstrap=boot(y,ident,learned,groups)),learned_vs_test_best_nuisance=dict(relative_improvement=1-np.mean((y-learned)**2)/np.mean((y-nu)**2),bootstrap=boot(y,nu,learned,groups)),no_new_training=True)
atomic(PROJECT/'post-outcome-diagnostics.json',diag)
old=Path('/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-functional-genomics-day1-20261021')
oldhash={n:sha(old/n) for n in ['plan.json','confirmation.started.json','confirmation.completed.json','results.json','frozen-selection.json']}
for n,h in json.loads((old/'freeze-hashes.json').read_text()).items():assert sha(old/n)==h
checks['old_frozen_inputs_unchanged_against_old_freeze']=True;checks['old_protected_files_current_sha256']=oldhash
for n,h in json.loads((PROJECT/'code-freeze.json').read_text()).items():assert sha(CODE/n)==h
checks['original_code_freeze_intact']=True
cg=Path('/proc/self/cgroup').read_text().strip().split('::')[1];base=Path('/sys/fs/cgroup')/cg.lstrip('/')
checks['resource_cgroup']=dict(path=cg,files={n:(base/n).read_text().strip() for n in ['memory.peak','memory.max','memory.high','cpu.max','pids.max','memory.events'] if (base/n).exists()})
checks['all_verified_at']=now();checks['paper_candidate']=False
atomic(PROJECT/'validation.json',checks)
atomic(PROJECT/'intake-manifests.json',manifests)
print(json.dumps(dict(parity=parity,diagnostics=diag,resource=checks['resource_cgroup']),indent=2))
