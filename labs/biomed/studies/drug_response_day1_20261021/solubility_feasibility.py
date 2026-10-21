"""Outcome-independent identity/reference feasibility; no models or external errors."""
import json,zipfile,xml.etree.ElementTree as ET
import pandas as pd
from rdkit import Chem,RDLogger
from rdkit.Chem.MolStandardize import rdMolStandardize
from rdkit.Chem.Scaffolds import MurckoScaffold
from audit import OUT,PROJECT,save,sha,status
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
RDLogger.DisableLog('rdApp.*')
def sheet(p,member):
    with zipfile.ZipFile(p) as z:
        strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
        rows=[]
        with z.open(member) as f:
            for _,e in ET.iterparse(f,events=['end']):
                if e.tag.endswith('}row'):
                    d={}
                    for c in e:
                        v=c.find('m:v',NS);value=None if v is None else v.text
                        if c.attrib.get('t')=='s':value=strings[int(value)]
                        col=''.join(a for a in c.attrib['r'] if a.isalpha());d[col]=value
                    rows.append(d);e.clear()
        header=rows[0]
        return pd.DataFrame([{header[k]:v for k,v in row.items() if k in header} for row in rows[1:]])
def identity(smiles):
    try:
        m=Chem.MolFromSmiles(str(smiles))
        if m is None: return None,None
        m=rdMolStandardize.Cleanup(m);m=rdMolStandardize.FragmentParent(m)
        m=rdMolStandardize.Uncharger().uncharge(m)
        m=rdMolStandardize.TautomerEnumerator().Canonicalize(m)
        Chem.RemoveStereochemistry(m) # Conservative exclusion, not identity assertion.
        key=Chem.MolToSmiles(m,canonical=True)
        scaffold=Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(m)) or 'ALL_ACYCLIC'
        return key,scaffold
    except Exception: return None,None
def main():
    status('strongest_candidate_identity_audit_running','Count standardized chemical/scaffold overlap and original-reference recovery; do not fit if provenance gate fails.',[str(PROJECT/'feasibility-plan.json')])
    train=sheet(OUT/'ulrich-dataset/dataset.xlsx','xl/worksheets/sheet2.xml')
    external=pd.read_csv(OUT/'ochem-unseen/OChemUnseen.tab',sep='\t')
    refs=pd.read_csv(OUT/'ochem-curated/OChemCurated.tab',sep='\t')
    cache={}
    for s in set(train.SMILES.dropna())|set(external.SMILES.dropna())|set(refs.SMILES.dropna()):cache[s]=identity(s)
    for df in [train,external,refs]:
        df['molecule_key']=df.SMILES.map(lambda s:cache.get(s,(None,None))[0])
        df['scaffold_key']=df.SMILES.map(lambda s:cache.get(s,(None,None))[1])
    old=pd.to_numeric(train['log Sw original dataset'],errors='coerce');new=pd.to_numeric(train['log Sw dataset used'],errors='coerce')
    paired=old.notna()&new.notna()&train.molecule_key.notna()
    t=train[paired].copy()
    refcol=train.get('reference',pd.Series(index=train.index,dtype=object)).fillna('').astype(str).str.strip()
    trainkeys=set(train.molecule_key.dropna());trainscaffolds=set(train.scaffold_key.dropna())
    # Exclude ALL train structures, including new-data rows without original labels.
    external['structure_disjoint']=external.molecule_key.notna()&~external.molecule_key.isin(trainkeys)
    external['scaffold_disjoint']=external.structure_disjoint&~external.scaffold_key.isin(trainscaffolds)
    refmap=refs[refs.molecule_key.notna()].groupby('molecule_key').agg(reference_count=('ARTICLEID','nunique'),article_ids=('ARTICLEID',lambda x:'|'.join(sorted(set(map(str,x))))))
    external=external.merge(refmap,on='molecule_key',how='left',validate='many_to_one')
    external['provenance_ambiguous']=external.reference_count.fillna(0)!=1
    # Never inspect external LogS values or choose based on any model error.
    sample=external.drop(columns=['LogS']).copy();sample.to_csv(OUT/'external-identity-audit.csv',index=False)
    duplicatekeys=int(train.molecule_key.dropna().duplicated(keep=False).sum())
    result=dict(candidate='solubility_model_assisted_curation_external_portability',stage='actual_data_feasibility_validation',models_fitted=0,confirmatory_tests=0,paper_candidate=False,counts=dict(published_training_rows=len(train),paired_original_curated_rows=int(paired.sum()),changed_paired_labels=int(((old-new).abs()>1e-8)[paired].sum()),training_rows_missing_original_reference=int((refcol=='').sum()),paired_rows_missing_original_reference=int((refcol[paired]=='').sum()),training_rows_with_duplicated_conservative_structure=duplicatekeys,external_rows=len(external),external_unique_structures=int(external.molecule_key.nunique()),external_structure_disjoint_rows=int(external.structure_disjoint.sum()),external_scaffold_disjoint_rows=int(external.scaffold_disjoint.sum()),external_structure_disjoint_unique=int(external.loc[external.structure_disjoint,'molecule_key'].nunique()),external_scaffold_disjoint_unique=int(external.loc[external.scaffold_disjoint,'molecule_key'].nunique()),external_scaffold_disjoint_with_single_reference=int((external.scaffold_disjoint&~external.provenance_ambiguous).sum()),external_reference_table_rows=len(refs),external_reference_table_unique_articles=int(refs.ARTICLEID.nunique())),decision='NO_GO_FOR_PREPLANNED_INDEPENDENT_STUDY_COMPARISON',reason='The paired-label training collection lacks original measurement references for many molecules; the separate external values are aggregated per structure, with multiple possible upstream reference records. Structure exclusion alone does not recover measurement-level provenance or establish a new independent-study confirmation. Do not train to obtain a favorable result after this gate fails.',exposure_record='Initial schema script inadvertently printed the first data row from each workbook sheet while intending headers only. These rows and the existing author test predictions are exposed exploratory information. No original author holdout is claimed blinded or evaluated here. External table schema and missingness were inspected, but external numeric values were never summarized or used for selection.',limitations=['Conservative neutralized tautomer and stereochemistry-stripped keys used only for overlap exclusion; these do not assert equal physical solubility.','Scaffold absence is chemical separation, not proof of original-study independence.','No assessment of correction validity or accusation of misconduct.','Even a future improvement would need nearest-method, fixed-budget model and independent uncertainty analyses.','Repository software MIT licence does not by itself establish a separate unrestricted experimental-data licence; retain original paper/data-source terms.'])
    save(OUT/'solubility-feasibility-results.json',result)
    save(PROJECT/'solubility-feasibility-results.json',result)
    save(OUT/'solubility-feasibility-hashes.json',{str(p):sha(p) for p in [Path for Path in [OUT/'ulrich-dataset/dataset.xlsx',OUT/'ochem-unseen/OChemUnseen.tab',OUT/'ochem-curated/OChemCurated.tab',PROJECT/'feasibility-plan.json',__import__('pathlib').Path(__file__)]]})
    status('strongest_candidate_no_go_provenance_gate','Finalize six-candidate ledger, reproducible no-go report and hashes; stop further candidate search.',[str(OUT/'solubility-feasibility-results.json'),str(OUT/'external-identity-audit.csv')])
    print(json.dumps(result,indent=2))
if __name__=='__main__': main()
