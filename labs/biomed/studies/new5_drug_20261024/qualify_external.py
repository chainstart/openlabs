from pathlib import Path
import sys,json,hashlib,re,urllib.parse,requests,pandas as pd
R=Path('/home/biostar/work/projects/openlabs/openlabs');P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
sys.path.insert(0,str(R/'labs/biomed'));from tools import dataset_intake
from read_tables import xlsx_rows
from rdkit import Chem
from rdkit.Chem.MolStandardize import rdMolStandardize
def normalized_name(s):return re.sub('[^a-z0-9]','',str(s).lower())
def active_smiles(s):
 m=Chem.MolFromSmiles(s)
 if m is None:return None
 m=rdMolStandardize.Cleanup(m);m=rdMolStandardize.FragmentParent(m);m=rdMolStandardize.Uncharger().uncharge(m)
 return Chem.MolToSmiles(m,isomericSmiles=True)
f=next((A/'melanoma2026-media-supp5').glob('*.xlsx'));rr=list(xlsx_rows(f));target=pd.DataFrame(rr[1:],columns=rr[0]);target=target[target.NAME.str.strip().ne('')].copy()
aliases={'Venetoclax':'Venetoclax','MK-2206':'MK-2206','Olaparib (AZD2281)':'Olaparib','Trametinib/Mekinist':'Trametinib','Lapatinib':'Lapatinib'}
source=pd.read_csv(P/'compound-metadata.csv');lookup={normalized_name(n):n for n in source.name}
records=[]
for _,row in target.iterrows():
 candidate=aliases.get(row.NAME,row.NAME)
 if normalized_name(candidate) not in lookup:continue
 name=lookup[normalized_name(candidate)];did='pubchem-source-'+normalized_name(name);manifest=A/did/'manifest.json'
 if manifest.exists():m=json.loads(manifest.read_text());assert not dataset_intake.validate_manifest(m,verify_payload=True)
 else:m=dataset_intake.download(source_id='pubchem',url='https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/'+urllib.parse.quote(name)+'/property/IsomericSMILES,InChIKey/JSON',staging_root=A,dataset_id=did,release_or_accession='PubChemPUG20261024:name='+name,independent_unit='molecule',terms_url='https://pubchem.ncbi.nlm.nih.gov/docs/usage-policies',reuse_basis='NCBI PubChem public facts with source attribution. Name-to-structure qualification only; does not chemically authenticate source-screen vials or salts.',citation='PubChem PUG REST retrieved20261024 and original GDSC/Oslo drug tables.',upstream_study_ids=['PubChem', 'Bashi2024', 'AyudaDuran2026'],filename='properties.json',max_bytes=1024**2)
 payload=json.loads(Path(m['artifact_uri'].removeprefix('file://')).read_text());pr=payload['PropertyTable']['Properties'][0];sm=pr.get('SMILES',pr.get('IsomericSMILES'));a=active_smiles(sm);b=active_smiles(row.PUBCHEM_ISOMERIC_SMILES)
 records.append({'target_name':row.NAME,'source_name':name,'pubchem_resolved_cid':pr['CID'],'target_cited_cid':row.PUBCHEM_ID,'same_parent_isomeric_structure':a==b,'parent_isomeric_smiles':a,'manifest':str(manifest),'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()})
out={'compound_matches':records,'no_external_combination_outcomes_read':True,'notes':['Nominal source compound names resolved to PubChem structures; source screen vial identity not independently authenticated.','Salts/charge standardized only for active-parent comparison; does not prove dose equivalence.']}
(P/'EXTERNAL_CHEMICAL_QUALIFICATION.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
