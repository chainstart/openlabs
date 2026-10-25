"""Metadata-only identity and dose feasibility audit; never reads response matrices."""
from common import *
import pandas as pd
import numpy as np
from rdkit import Chem, rdBase, RDLogger
from rdkit.Chem.Scaffolds import MurckoScaffold

t=pd.read_csv(ART/'intake/prism19-secondary-screen-replicate-treatment-info.csv')
c=pd.read_csv(ART/'intake/prism19-secondary-screen-cell-line-info.csv')
p=pd.read_csv(ART/'intake/prism19-secondary-screen-pooling-info.csv')
RDLogger.DisableLog('rdApp.error')
struct=[]
for sm in sorted(t.smiles.dropna().unique()):
    # Official field can contain comma-separated repeated structures. Require all
    # nonempty entries to parse and agree exactly after atom-order canonicalization.
    parts=[x.strip() for x in sm.split(',') if x.strip()]
    mols=[Chem.MolFromSmiles(x) for x in parts]
    canon={Chem.MolToSmiles(m,isomericSmiles=True) for m in mols if m is not None}
    if not mols or any(m is None for m in mols) or len(canon)!=1:
        struct.append({'smiles':sm,'canonical_smiles':None,'structure_key':None,'scaffold_key':None,'annotation_count':len(parts),'identity_status':'invalid_or_conflicting'});continue
    canonical=next(iter(canon));mol=mols[0]
    key=hashlib.sha256(canonical.encode()).hexdigest()[:24]
    scaffold=MurckoScaffold.MurckoScaffoldSmiles(mol=mol,includeChirality=False)
    struct.append({'smiles':sm,'canonical_smiles':canonical,'structure_key':key,'scaffold_key':hashlib.sha256((scaffold or 'ACYCLIC').encode()).hexdigest()[:24],'annotation_count':len(parts),'identity_status':'unambiguous_exact_canonical'})
s=pd.DataFrame(struct)
t=t.merge(s,on='smiles',how='left')
t.to_csv(DATA/'treatment-metadata.csv',index=False)
s.to_csv(DATA/'compound-identity.csv',index=False)
t=t[t.perturbation_type=='experimental_treatment'].dropna(subset=['structure_key','dose'])
rows=[]
for key,g in t.groupby('structure_key'):
    target=g[g.screen_id=='MTS010']
    if target.empty:continue
    source=g[g.screen_id!='MTS010']
    screens=sorted(source.screen_id.unique(),key=lambda x:['HTS002','MTS006','MTS005'].index(x))
    if not screens:continue
    source=source[source.screen_id==screens[0]]
    td=np.array(sorted(target.dose.unique()));sd=np.array(sorted(source.dose.unique()))
    # Metadata rounding differs; collapse log10-dose differences below 0.001 (~0.23%).
    def cluster(a):
        out=[]
        for x in a:
            if not out or abs(np.log10(x/out[-1]))>0.001:out.append(x)
        return np.array(out)
    td,sd=cluster(td),cluster(sd)
    rows.append({'structure_key':key,'scaffold_key':g.scaffold_key.iloc[0],'canonical_smiles':g.canonical_smiles.iloc[0],'name':g['name'].iloc[0], 'source_screen':screens[0], 'source_batches':'|'.join(sorted(source.broad_id.unique())), 'target_batches':'|'.join(sorted(target.broad_id.unique())), 'source_doses':json.dumps(sd.tolist()), 'target_doses':json.dumps(td.tolist()),'matched_grid':bool(len(td)==len(sd) and np.allclose(td,sd,rtol=.01,atol=0)), 'source_n_doses':len(sd),'target_n_doses':len(td),'source_min':sd.min(),'source_max':sd.max(),'target_min':td.min(),'target_max':td.max(),'source_detection_plates':source.detection_plate.nunique(),'target_detection_plates':target.detection_plate.nunique(),'source_compound_plates':source.compound_plate.nunique(),'target_compound_plates':target.compound_plate.nunique()})
meta=pd.DataFrame(rows)
meta.to_csv(DATA/'paired-compound-metadata.csv',index=False)
cells=c[(c.passed_str_profiling==True)&c.depmap_id.notna()].copy()
cellcounts=cells.groupby('depmap_id').row_name.nunique()
cells['duplicate_model_rows']=cells.depmap_id.map(cellcounts)>1
cells.to_csv(DATA/'cell-identity.csv',index=False)
result={'created_at_utc':now(),'exposure':'metadata only; no numerical response labels inspected','rdkit':rdBase.rdkitVersion,'identity':'full isomeric canonical SMILES; no salt stripping/tautomer merge or name-only matches','matched_compounds':len(meta),'source_screens':meta.source_screen.value_counts().to_dict(),'matched_dose_grid_compounds':int(meta.matched_grid.sum()),'source_dose_counts':meta.source_n_doses.value_counts().to_dict(),'target_dose_counts':meta.target_n_doses.value_counts().to_dict(),'passing_cell_models':cells.depmap_id.nunique(),'duplicate_model_ids':int((cellcounts>1).sum()),'structures_total':len(s),'invalid_structures':int(s.structure_key.isna().sum()),'split_note':'not yet frozen; feasibility determines sample and precision before outcome inspection'}
write(DATA/'prism-metadata-feasibility.json',result)
print(json.dumps(result,indent=2));print(meta.groupby(['source_screen','matched_grid']).size());print('nonmatched grids',meta[~meta.matched_grid][['name','source_doses','target_doses']].to_string(index=False))
