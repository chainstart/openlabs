"""Official bounded solubility intake. Register one scoped source under shared lock."""
import fcntl,json,sys
from pathlib import Path
from audit import OUT,save,sha,status
LAB=Path('/home/biostar/work/openlabs/labs/biomed')
sys.path.insert(0,str(LAB))
from tools.dataset_intake import download

def main():
    commit=json.loads((OUT/'access/ulrich_commit.json').read_text())[0]['sha']
    src=dict(source_id='day1_solubility_curation_audit',phase=1,access='public',name='Author-deposited solubility curation paired tables and independent OChem candidate',documentation_url='https://link.springer.com/article/10.1186/s13321-025-01000-9',terms_url=f'https://raw.githubusercontent.com/nadinulrich/log_Sw_prediction/{commit}/LICENSE',reuse_basis='Repository MIT LICENSE; original journal CC BY 4.0; Dataverse etalab 2.0. Preserve original AqSolDB/OChem experiment provenance; public access is not independent data.',allowed_hosts=['raw.githubusercontent.com','entrepot.recherche.data.gouv.fr'],independence_risks=['AqSolDB derivatives share measurements','OChem is a compilation; exact chemical and original reference overlap must be audited before confirmation'],citation_policy='Ulrich et al. DOI10.1186/s13321-025-01000-9; Llompart et al. DOI10.1038/s41597-024-03105-6; dataset DOI10.57745/CZVZIA; AqSolDB original sources')
    registry=LAB/'registries/data_sources.json'
    with open('/tmp/openlabs-biomed-source-registry.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        j=json.loads(registry.read_text());matches=[x for x in j['sources'] if x['source_id']==src['source_id']]
        if not matches: j['sources'].append(src);save(registry,j)
        else: assert matches==[src]
    items=[('ulrich-license',f'https://raw.githubusercontent.com/nadinulrich/log_Sw_prediction/{commit}/LICENSE','LICENSE.txt','MIT license snapshot'),('ulrich-dataset',f'https://raw.githubusercontent.com/nadinulrich/log_Sw_prediction/{commit}/dataset.xlsx','dataset.xlsx',f'author commit {commit}'),('ochem-unseen','https://entrepot.recherche.data.gouv.fr/api/access/datafile/156689','OChemUnseen.tab','Dataverse DOI10.57745/CZVZIA version2.0 file156689'),('ochem-curated','https://entrepot.recherche.data.gouv.fr/api/access/datafile/156688','OChemCurated.tab','Dataverse DOI10.57745/CZVZIA version2.0 file156688'),('ochem-readme','https://entrepot.recherche.data.gouv.fr/api/access/datafile/569042','OChemREADME.txt','Dataverse DOI10.57745/CZVZIA version2.0 file569042')]
    # The official Dataverse text endpoint redirects to its institutional S3 host.
    # Register a unique scoped entry, retaining the first failed attempt directory.
    storage_src={**src,'source_id':'day1_solubility_dataverse_storage','name':'Recherche Data Gouv official institutional storage redirect','allowed_hosts':['entrepot.recherche.data.gouv.fr','prod-univ-strasbourg.opens3r-tls.stockage.inrae.fr'],'documentation_url':'https://entrepot.recherche.data.gouv.fr/dataset.xhtml?persistentId=doi:10.57745/CZVZIA','terms_url':'https://spdx.org/licenses/etalab-2.0.html'}
    with open('/tmp/openlabs-biomed-source-registry.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        j=json.loads(registry.read_text());matches=[x for x in j['sources'] if x['source_id']==storage_src['source_id']]
        if not matches:j['sources'].append(storage_src);save(registry,j)
        else:assert matches==[storage_src]
    items[-1]=('ochem-readme-v2',items[-1][1],items[-1][2],items[-1][3])
    items.append(('ochem-clean','https://entrepot.recherche.data.gouv.fr/api/access/datafile/569048','OChem_Clean.tab','Dataverse DOI10.57745/CZVZIA version2.0 file569048'))
    records=[]
    for key,url,name,release in items:
        p=OUT/key/'manifest.json'
        if p.exists(): m=json.loads(p.read_text())
        else:
            m=download(source_id=storage_src['source_id'] if key.startswith('ochem-readme') else src['source_id'],url=url,staging_root=OUT,dataset_id=key,release_or_accession=release,independent_unit='molecule_and_original_experimental_reference',terms_url=src['terms_url'] if key.startswith('ulrich') else 'https://spdx.org/licenses/etalab-2.0.html',reuse_basis=src['reuse_basis'],citation=src['citation_policy'],upstream_study_ids=['AqSolDB nine-source compilation and literature additions' if key.startswith('ulrich') else 'OChem compilation; per-reference independence not yet established'],filename=name,max_bytes=16*1024**2,retries=1)
        records.append(m)
        save(OUT/'solubility-intake-index.json',records)
    save(OUT/'solubility-intake-index.json',records)
    status('strongest_candidate_data_acquired','Audit paired-label availability, outcome-independent external identity/reference exclusions; freeze only if feasible.',[str(OUT/'solubility-intake-index.json')])
    print(json.dumps([dict(dataset_id=m['dataset_id'],bytes=m['bytes'],sha256=m['sha256']) for m in records],indent=2))
if __name__=='__main__':main()
