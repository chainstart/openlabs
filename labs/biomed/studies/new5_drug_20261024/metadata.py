from pathlib import Path
import json,hashlib,pandas as pd
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
cols=['BARCODE','DRUGSET_ID','cmatrix','CELL_LINE_NAME','MASTER_CELL_ID','COSMIC_ID','SIDM','TISSUE','CANCER_TYPE','lib1_ID','lib1_name','lib1_minc','lib1_maxc','lib1_target','lib1_pathway','lib2_ID','lib2_name','lib2_minc','lib2_maxc','lib2_target','lib2_pathway']
frames=[]
for r in json.loads((P/'intake-index.json').read_text()):
 f=Path(r['dataset']['artifact_uri'].removeprefix('file://'));d=pd.read_csv(f,usecols=cols);d['screen']=f.name.split('_matrix')[0];frames.append(d)
d=pd.concat(frames,ignore_index=True);d['pair']=d.apply(lambda x:'|'.join(sorted([str(x.lib1_name).lower(),str(x.lib2_name).lower()])),axis=1)
d.to_csv(P/'metadata-only.csv',index=False)
rows=[]
for screen,g in d.groupby('screen'):rows.append({'screen':screen,'rows':len(g),'cell_lines':g.SIDM.nunique(),'pairs':g.pair.nunique(),'tissues':g.TISSUE.nunique()})
pairsets={s:set(g.pair) for s,g in d.groupby('screen')};pair_overlaps={f'{a}::{b}':len(pairsets[a]&pairsets[b]) for a in pairsets for b in pairsets if a<b}
drug=pd.concat([d[['lib1_ID','lib1_name','lib1_target','lib1_pathway']].rename(columns=lambda s:s.replace('lib1_','')),d[['lib2_ID','lib2_name','lib2_target','lib2_pathway']].rename(columns=lambda s:s.replace('lib2_',''))]).drop_duplicates();drug.to_csv(P/'compound-metadata.csv',index=False)
out={'no_outcome_columns_loaded':True,'screens':rows,'total_cells':d.SIDM.nunique(),'unique_pairs':d.pair.nunique(),'unique_compounds':drug.name.nunique(),'pair_overlaps':pair_overlaps,'duplicate_pair_cells':int(d.duplicated(['pair','SIDM']).sum()),'drug_metadata_conflicts':int(drug.groupby('name').size().gt(1).sum())}
(P/'METADATA_FEASIBILITY.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
