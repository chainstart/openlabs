import json
from common import *

status('candidate_metadata_access', 'Can cross-cell orientation dependence reveal transferable cis-regulatory grammar?',
       'guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/functional_genomics_day1_20261021/probe.py')
for accession in ['ENCSR405QCT','ENCSR203UFY','ENCSR336MKI','ENCSR022GQD']:
    try:
        d=json.loads(fetch(f'https://www.encodeproject.org/experiments/{accession}/?format=json',accession+'.json'))
        print(accession,[(x['accession'],x.get('output_type'),x.get('file_size'),x.get('file_format'),x.get('href')) for x in d.get('files',[])])
    except Exception as e: print(accession,str(e))
for name,url in [('allostery-tree.json','https://api.github.com/repos/lehner-lab/allostery_pathogenicity/git/trees/main?recursive=1'),
                 ('encode-terms.html','https://www.encodeproject.org/help/data-use-policy/')]:
    try:
        b=fetch(url,name)
        if name.endswith('.json'):
            d=json.loads(b)
            print(name,[(x['path'],x.get('size')) for x in d.get('tree',[])][:120])
        else: print(name,len(b))
    except Exception as e: print(name,str(e))
status('candidate_metadata_access_complete','Cross-cell orientation hypothesis feasibility',
       'probe.py completed',list((ART/'metadata').glob('*access.json')))
