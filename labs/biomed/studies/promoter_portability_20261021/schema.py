from common import *
from xlsx import sheets
import gzip,csv
out={}
for p in sorted((ART/'intakes').glob('*/source.xlsx')):
 out[str(p)]={k:dict(nrows=len(v),first3=v[:3]) for k,v in sheets(p).items()}
for p in sorted((ART/'intakes').glob('*/data.tsv.gz')):
 with gzip.open(p,'rt') as f:
  reader=csv.reader(f,delimiter='\t');header=next(reader);names=[];n=0
  for r in reader:
   n+=1
   if len(names)<6:names.append(r[0])
 out[str(p)]=dict(header=header,nrows=n,first_identifier_values=names)
atomic(PROJECT/'schema-audit.json',out)
print(json.dumps(out,indent=2))
