from pathlib import Path
import json,sys
R=Path('/home/biostar/work/projects/openlabs/openlabs');P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
sys.path.insert(0,str(R/'labs/biomed'));from tools import dataset_intake
s=json.loads((P/'source-registry-local.json').read_text());old=dataset_intake.source_record;dataset_intake.source_record=lambda k:s if k==s['source_id'] else old(k)
m=json.loads((A/'figshare-25266697.json').read_text());f=m['files'][0];did='gdsc-combination-raw-25266697';loc=A/did/'manifest.json'
if loc.exists():rec=json.loads(loc.read_text());assert not dataset_intake.validate_manifest(rec,verify_payload=True)
else:rec=dataset_intake.download(source_id=s['source_id'],url=f['download_url'],staging_root=A,dataset_id=did,release_or_accession=m['doi'],independent_unit='cell_line_and_drug_pair_matrix_well',terms_url=m['license']['url'],reuse_basis=s['reuse_basis'],citation='Bashi,Coker,Bulusu et al.2024 Cancer Discovery DOI10.1158/2159-8290.CD-23-0388; '+m['doi'],upstream_study_ids=['CancerDiscovery2024_CD-23-0388','GDSC007-010_Sandpiper1'],filename=f['name'],max_bytes=256*1024**2)
(P/'sanger-raw-intake.json').write_text(json.dumps(rec,indent=2)+'\n');print(json.dumps({'bytes':rec['bytes'],'release':rec['release_or_accession']},indent=2))
