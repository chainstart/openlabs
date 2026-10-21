"""One bounded sequential intake queue; no outcomes parsed."""
import json
from common import *
from intake import intake,register
assert (PROJECT/'plan.json').exists()
register()
for accession in ['ENCSR022GQD','ENCSR382BVV','ENCSR244FWB']:
    meta=json.loads((ART/f'metadata/{accession}.json').read_text())
    selected=[x for x in meta['files'] if x.get('file_format')=='tsv' and x.get('status')=='released' and len(x.get('biological_replicates',[]))==1]
    assert len(selected)==3
    for item in selected:
        print('starting',accession,item['accession'],item['file_size'],flush=True)
        print('completed',intake(accession,item['accession']),flush=True)
status('replicate_intake_complete','Frozen promoter-specific orientation transfer',
       'download_replicates.py completed',list((ART/'intakes').glob('*/manifest.json')))
