from common import *
import sys,fcntl
sys.path.insert(0,str(CODE.parents[1]))
from tools.dataset_intake import download
SOURCE='quasarr_2026_source_data'
entry=dict(source_id=SOURCE,phase=1,access='public',name='QUASARR-seq 2026 publisher source data',documentation_url='https://www.nature.com/articles/s41467-026-68780-y',terms_url='https://creativecommons.org/licenses/by/4.0/',reuse_basis='Article CC BY 4.0, including supplementary source material unless a credit line indicates otherwise; internal attributed research. Inspect workbook credits. Author code has no explicit repository license; inspect as provenance, do not redistribute.',allowed_hosts=['media.springernature.com','static-content.springer-cdn.com','www.nature.com'],citation_policy='Paramo et al. Nature Communications 17:2177 (2026), DOI10.1038/s41467-026-68780-y; GSE310760.',independence_risks=['ENCSR382BVV is Agarwal old source, not independent','Minimal promoter variants are contexts of one study','Variable-length inserts require sequence audit'],checked_at='2026-10-21')
with open('/tmp/openlabs-biomed-source-registry.lock','w') as f:
 fcntl.flock(f,fcntl.LOCK_EX);p=CODE.parents[1]/'registries/data_sources.json';d=json.loads(p.read_text())
 if not any(x['source_id']==SOURCE for x in d['sources']):d['sources'].append(entry);atomic(p,d)
atomic(PROJECT/'source-entry.json',entry)
for i in [3,6]:
 dest=ART/f'intakes/quasarr-moesm{i}'
 if (dest/'manifest.json').exists():continue
 try:
  m=download(source_id=SOURCE,url=f'https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-026-68780-y/MediaObjects/41467_2026_68780_MOESM{i}_ESM.xlsx',staging_root=ART/'intakes',dataset_id=f'quasarr-moesm{i}',release_or_accession='DOI10.1038/s41467-026-68780-y:published2026-01-30:MOESM'+str(i),independent_unit='DNA locus, not small molecule; paired reporter orientations',terms_url=entry['terms_url'],reuse_basis=entry['reuse_basis'],citation=entry['citation_policy'],upstream_study_ids=['GSE310760','DOI10.1038/s41467-026-68780-y'],filename='source.xlsx',max_bytes=128*1024**2,retries=1)
  print(i,m['bytes'],flush=True)
 except Exception as e:print(i,str(e),flush=True)
