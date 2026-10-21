from common import *
from xlsx import sheets
w=sheets(ART/'intakes/quasarr-moesm6/source.xlsx')
out={k:dict(nrows=len(v),headers=[{c:x for c,x in row.items() if x and not x.replace('.','',1).replace('-','',1).isdigit() and not any(a in x for a in ['e-','E-'])} for row in v[:1]]) for k,v in w.items()}
atomic(PROJECT/'source-workbook-schema.json',out);print(json.dumps(out,indent=2))
