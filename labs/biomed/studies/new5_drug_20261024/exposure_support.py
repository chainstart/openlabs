from pathlib import Path
import json,pandas as pd,numpy as np
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
p=pd.read_csv(A/'external-point-predictions.csv');s=pd.read_csv(A/'metadata-only.csv');chem=json.loads((P/'EXTERNAL_CHEMICAL_QUALIFICATION.json').read_text());names={r['target_name']:r['source_name'] for r in chem['compound_matches'] if r['same_parent_isomeric_structure']};rows=[]
for (d1,d2),g in p[p.same_parent_chemical_pair].groupby(['drug1','drug2']):
 pair='|'.join(sorted([names[d1].lower(),names[d2].lower()]));raw=s[s.pair.eq(pair)].copy();ranges={}
 for tname in [d1,d2]:
  sn=names[tname];vals=[]
  for k in [1,2]:
   rr=raw[raw[f'lib{k}_name'].eq(sn)];vals.extend(zip(rr[f'lib{k}_minc'],rr[f'lib{k}_maxc']))
  vals=sorted(set(vals));ranges[tname]={'source_nominal_ranges_uM':[[float(a),float(b)] for a,b in vals],'source_union_min_uM':float(min(a for a,b in vals)),'source_union_max_uM':float(max(b for a,b in vals))}
 inside=np.ones(len(g),dtype=bool)
 for i,tname in enumerate([d1,d2],1):
  rg=ranges[tname];inside&=g[f'conc{i}'].between(rg['source_union_min_uM']*.99,rg['source_union_max_uM']*1.01).to_numpy();rg['target_min_uM']=float(g[f'conc{i}'].min());rg['target_max_uM']=float(g[f'conc{i}'].max())
 rows.append({'chemical_pair':pair,'target_points':len(g),'inside_both_source_nominal_dose_ranges':int(inside.sum()),'inside_fraction':float(inside.mean()),'ranges':ranges})
out={'type':'prespecified descriptive exposure audit; no model refit or new independent confirmation','exact_parent_chemical_pairs':rows,'units':'reported micromolar; saltmolarity and targetoccupancy not independently measured','tolerance':'1% endpoint tolerance around source nominal support; findings insensitive for30xgap','interpretation':'Common monotherapy activity does not establish common absolute exposure or common target engagement. Outside-source dose support is not proof of an off-target mechanism.'}
(P/'EXPOSURE_SUPPORT_AUDIT.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
