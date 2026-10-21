"""Second and final HTTP slot, opaque WTC11 intake; no outcome parsing."""
import json
from common import *
from intake import intake,register
assert (PROJECT/'plan.json').exists()
register()
a='ENCSR244FWB'
meta=json.loads((ART/f'metadata/{a}.json').read_text())
selected=[x for x in meta['files'] if x.get('file_format')=='tsv' and x.get('status')=='released' and len(x.get('biological_replicates',[]))==1]
assert len(selected)==3
for item in selected:
    print('starting confirmation opaque file',item['accession'],item['file_size'],flush=True)
    print('completed',intake(a,item['accession']),flush=True)
print('Confirmation files received but numeric outcomes remain analytically unopened.',flush=True)
