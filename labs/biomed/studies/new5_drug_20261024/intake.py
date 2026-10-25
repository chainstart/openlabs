from pathlib import Path
import sys,json,hashlib,datetime,requests
R=Path('/home/biostar/work/projects/openlabs/openlabs');P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
sys.path.insert(0,str(R/'labs/biomed'))
from tools import dataset_intake
source={'source_id':'gdsc_combinations_figshare','name':'Sanger GDSC combination matrix screens linked by Cancer Discovery 2024 original article','allowed_hosts':['api.figshare.com','ndownloader.figshare.com','figshare.com','s3-eu-west-1.amazonaws.com'],'documentation_url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC11061612/','terms_url':'https://creativecommons.org/licenses/by/4.0/','reuse_basis':'Each selected exact Figshare record declares CC BY4.0. Preserve attribution, exact version/file IDs and original study; these are cell line in vitro screens, not patients.'}
(P/'source-registry-local.json').write_text(json.dumps(source,indent=2)+'\n')
original=dataset_intake.source_record
dataset_intake.source_record=lambda s:source if s==source['source_id'] else original(s)
manifest=[]
for i in [22362769,22362793,22362802,22362808,22362760]:
 m=json.loads((A/f'figshare-{i}.json').read_text());f=m['files'][0];did='gdsc-combination-'+str(i);loc=A/did/'manifest.json'
 if loc.exists():
  rec=json.loads(loc.read_text());assert not dataset_intake.validate_manifest(rec,verify_payload=True)
 else:
  rec=dataset_intake.download(source_id=source['source_id'],url=f['download_url'],staging_root=A,dataset_id=did,release_or_accession=m['doi'],independent_unit='cell_line_and_drug_pair',terms_url=m['license']['url'],reuse_basis=source['reuse_basis'],citation='Garcia-Alonso et al. 2024 Cancer Discovery DOI10.1158/2159-8290.CD-23-0388; '+m['doi'],upstream_study_ids=['CancerDiscovery2024_CD-23-0388',m['title']],filename=f['name'],max_bytes=32*1024**2)
 manifest.append({'path':str(loc),'sha256':hashlib.sha256(loc.read_bytes()).hexdigest(),'dataset':rec})
(P/'intake-index.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps([{'record':x['dataset']['release_or_accession'],'bytes':x['dataset']['bytes']} for x in manifest],indent=2))
