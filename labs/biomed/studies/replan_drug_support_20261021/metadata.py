"""Metadata-only CTRP/PRISM linkage. Never parses new CTRP response values."""
from common import *
import numpy as np
import pandas as pd
from rdkit import Chem, RDLogger

OLD_ART = ROOT/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/drug_support'
OLD_DATA = ROOT/'openlabs-data/workspaces/biology/projects/biomed-fourlane-drug-support-20261021'

def verify_old():
    inventory=json.loads((OLD_ART/'reproducibility-inventory.json').read_text())
    hashes={x['path']:x['sha256'] for x in inventory['files']}
    hashes[str(OLD_ART/'normalized-selected-mfi.pkl')]=json.loads((OLD_ART/'normalization-recovery.json').read_text())['sha256']
    wanted=[OLD_ART/'normalized-selected-mfi.pkl',OLD_ART/'selected-well-metadata.csv',
            OLD_DATA/'paired-compound-support.csv',OLD_DATA/'cell-identity.csv']
    wanted += [OLD_ART/s for s in ['development/train-curves-raw.json','development/validation-curves-raw.json','sealed/test-curves-raw.json']]
    out=[]
    for p in wanted:
        actual=sha256_file(p); expected=hashes.get(str(p))
        assert expected == actual, (str(p),expected,actual)
        out.append({'path':str(p),'sha256':actual,'matches_prior_inventory':True,'role':'read-only; all old target outcomes development only'})
    write(DATA/'old-payload-reuse.json',out)

def main():
    verify_old()
    RDLogger.DisableLog('rdApp.error')
    m=pd.read_csv(ART/'intake/harmonization-drug-map.csv',dtype=str)
    names=set(pd.read_csv(DATA/'ctrp-drug-names.csv').drug)
    rows=[]
    for d in sorted(names):
        a=m[m.name==d].dropna(subset=['ctrp2_smiles'])
        canon=set()
        invalid=False
        for s in a.ctrp2_smiles.unique():
            mol=Chem.MolFromSmiles(s)
            if mol is None:invalid=True
            else:canon.add(Chem.MolToSmiles(mol,isomericSmiles=True))
        good=len(canon)==1 and not invalid
        rows.append({'drug':d,'canonical_smiles':next(iter(canon)) if good else None,
                     'structure_key':hashlib.sha256(next(iter(canon)).encode()).hexdigest()[:24] if good else None,
                     'n_structures':len(canon),'invalid_smiles':invalid,
                     'ctrp_original_names':'|'.join(sorted(a.ctrp2_name.dropna().unique())),
                     'ctrp_broad_ids':'|'.join(sorted(a.ctrp2_broad_cpd_id.dropna().unique())),
                     'ctrp_master_cpd_ids':'|'.join(sorted(a.ctrp2_master_cpd_id.dropna().unique()))})
    compounds=pd.DataFrame(rows)
    # Alias compounds mapping to the same exact structure are conservatively excluded,
    # rather than pooled without an original experiment/batch audit.
    compounds['duplicate_structure']=compounds.structure_key.notna() & compounds.structure_key.duplicated(keep=False)
    compounds.to_csv(DATA/'ctrp-compound-identity.csv',index=False)
    old=pd.read_csv(OLD_DATA/'paired-compound-support.csv')
    ex=pd.read_csv(OLD_ART/'selected-well-metadata.csv')
    exact_endpoints={}
    for (key,screen),h in ex.groupby(['structure_key','screen_id']):
        clusters=[]
        for dose in sorted(h.dose.unique()):
            if not clusters or abs(np.log10(dose/clusters[-1][0]))>.001:clusters.append([dose])
            else:clusters[-1].append(dose)
        exact_endpoints[(key,screen)]=(np.median(clusters[0]),np.median(clusters[-1]))
    matched=compounds[~compounds.duplicate_structure].dropna(subset=['structure_key']).merge(old,on='structure_key',suffixes=('_ctrp','_prism'))
    cells=pd.read_csv(OLD_DATA/'cell-identity.csv')
    cells['cell_line']=cells.ccle_name.str.split('_').str[0]
    cells['ambiguous']=cells.cell_line.duplicated(keep=False)|cells.depmap_id.duplicated(keep=False)
    cells=cells[~cells.ambiguous & cells.passed_str_profiling.astype(bool)]
    target_cells=pd.read_csv(DATA/'ctrp-cell-names.csv')
    cells=cells.merge(target_cells,on='cell_line')
    cells.to_csv(DATA/'cell-linkage.csv',index=False)
    g=pd.read_csv(ART/'ctrp-metadata-groups.csv.gz')
    g=g[g.drug.isin(matched.drug)&g.cell_line.isin(cells.cell_line)].copy()
    # Freeze a common interval for each drug using modal design endpoints, then
    # require actual source/target coverage. No outcome-dependent window selection.
    intervals=[]
    for d,h in g.groupby('drug',sort=True):
        a=matched[matched.drug==d].iloc[0]
        ctrp_min=float(h.dose_min.round(6).mode().iloc[0])
        ctrp_max=float(h.dose_max.round(6).mode().iloc[0])
        smin,smax=exact_endpoints[(a.structure_key,a.source_screen)]
        tmin,tmax=exact_endpoints[(a.structure_key,'MTS010')]
        lo=max(np.log10(smin),np.log10(tmin),ctrp_min)+2e-6
        hi=min(np.log10(smax),np.log10(tmax),ctrp_max)-2e-6
        intervals.append({'drug':d,'structure_key':a.structure_key,'source_screen':a.source_screen,
                          'common_lo':lo,'common_hi':hi,'width':hi-lo,
                          'ctrp_modal_min':ctrp_min,'ctrp_modal_max':ctrp_max,
                          'source_doses':a.source_doses,'old_target_doses':a.target_doses})
    intervals=pd.DataFrame(intervals)
    intervals['usable']=intervals.width>=1.2
    intervals.to_csv(DATA/'common-support-metadata.csv',index=False)
    z=g.merge(intervals,on='drug').merge(cells[['cell_line','depmap_id','row_name']],on='cell_line')
    z=z[z.usable & (z.dose_min<=z.common_lo+1e-6)&(z.dose_max>=z.common_hi-1e-6)&(z.n_rows>=4)]
    pairs=z.groupby(['drug','structure_key','cell_line','depmap_id','row_name','source_screen','common_lo','common_hi']).agg(n_target_replicate_labels=('replicate','nunique')).reset_index()
    # Source availability can be audited now: it is old development evidence,
    # not the external target response. No new target effect is computed.
    source=pd.read_pickle(OLD_ART/'normalized-selected-mfi.pkl')
    source_complete={}
    for (key,screen),h in ex.groupby(['structure_key','screen_id']):
        if screen=='MTS010':continue
        n=np.zeros(len(source),dtype=int)
        for rep,k in h.groupby('replicate'):
            vals=source[k.column_name].to_numpy()
            n+=np.isfinite(vals).all(axis=1)
        for row,count in zip(source.index,n):source_complete[(key,screen,row)]=int(count)
    pairs['source_complete_replicates']=[source_complete.get((a.structure_key,a.source_screen,a.row_name),0) for a in pairs.itertuples()]
    pairs['source_eligible']=pairs.source_complete_replicates>=2
    pairs.to_csv(DATA/'metadata-qualified-pairs.csv',index=False)
    eligible=pairs[pairs.source_eligible]
    counts=eligible.groupby('structure_key').size()
    counts.to_csv(DATA/'eligible-counts-by-structure.csv')
    result={'at_utc':now(),'target_response_exposure':'not parsed; metadata only',
            'exact_identity_policy':'Full isomeric canonical SMILES; no salt stripping, stereochemistry removal, tautomer merging, or name-only pairing. Master-name link from author DrugNameMap to original CTRP SMILES; compare exact canonical structures with verified official PRISM metadata.',
            'cell_identity_policy':'Exact CTRP standardized cell name equals unique original PRISM official CCLE name prefix; require passed STR and unique ModelID; no fuzzy aliases.',
            'n_name_records':len(compounds),'n_exact_structures_linked':len(matched),
            'n_unique_cell_links':len(cells),'metadata_pairs':len(pairs),
            'source_eligible_pairs':len(eligible),'source_eligible_structures':eligible.structure_key.nunique(),
            'source_eligible_models':eligible.depmap_id.nunique(),
            'min_median_max_cells_per_drug':[int(counts.min()),float(counts.median()),int(counts.max())],
            'replicate_warning':'CTRP author replicate labels do not retain original experiment/plate IDs. They are measurement repeats, not biological donors or proven separate runs. Target primary will aggregate measurements within dose and evaluate screen-level response, not replicate-level independence.',
            'independence':'CTRP2015 vs PRISM2019 are different upstream screening experiments and different readouts; both Broad. Same cell line identities permit paired screen transfer; not new patients or independent laboratory validation.',
            'precision_scenarios':[{'n_drugs':len(counts),'between_drug_sd':sd,'normal95_halfwidth':1.96*sd/np.sqrt(len(counts)),'normal80_mde':2.8*sd/np.sqrt(len(counts))} for sd in [.03,.05,.1]],
            'paper_candidate':False}
    write(DATA/'identity-and-support-feasibility.json',result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
