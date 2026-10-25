from pathlib import Path
import sys,json,hashlib
R=Path('/home/biostar/work/projects/openlabs/openlabs');P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
sys.path.insert(0,str(R/'labs/biomed'));from tools import dataset_intake
terms='https://creativecommons.org/licenses/by-nc-nd/4.0/'
basis='Publisher article XML explicitly licenses article/material under CC BY-NC-ND4.0 unless separately credited. Exact files are linked publisher supplementary data1,2,14. Bounded private noncommercial research use with attribution only; no redistribution of raw/adapted supplements. Separate Zenodo record lacks explicit license; do not infer CC BY. Scope and current terms preserved in melanoma2026.xml.'
rows=[]
for number,ext in [(4,'xlsx'),(5,'xlsx'),(17,'ods'),(15,'zip'),(13,'zip'),(14,'zip')]:
 name=f'43856_2026_1583_MOESM{number}_ESM.{ext}';did=f'melanoma2026-media-supp{number}';loc=A/did/'manifest.json'
 if loc.exists():rec=json.loads(loc.read_text());assert not dataset_intake.validate_manifest(rec,verify_payload=True)
 else:rec=dataset_intake.download(source_id='publisher_supplementary_tables',url='https://media.springernature.com/full/springer-static/esm/art%3A10.1038%2Fs43856-026-01583-w/MediaObjects/'+name,staging_root=A,dataset_id=did,release_or_accession='10.1038/s43856-026-01583-w:MOESM'+str(number),independent_unit='donor_cell_line_and_drug_pair',terms_url=terms,reuse_basis=basis,citation='Ayuda-Duran et al. Communications Medicine2026 DOI10.1038/s43856-026-01583-w; exact supplementary file'+name,upstream_study_ids=['Ayuda-Duran2026_melanoma','zenodo.18962045'],filename=name,max_bytes=40*1024**2)
 rows.append(rec)
(P/'melanoma-intake-index.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps([{'release':r['release_or_accession'],'bytes':r['bytes']} for r in rows],indent=2))
