from common import *
from xlsx import sheets
import csv,gzip,re,collections
w=sheets(ART/'intakes/quasarr-moesm6/source.xlsx')
for k in ['Element_Coordinates','Elements_Sequences','GENCODE_Transcribed','GENCODE_Untranscribed']:
 print(k,w[k][:5])
for p in (ART/'intakes').glob('gse156857*/data.tsv.gz'):
 with gzip.open(p,'rt') as f:print(p.parent.name,f.readline().strip())
for p in (ART/'intakes').glob('gse279057*/data.tsv.gz'):
 with gzip.open(p,'rt') as f:print(p.parent.name,f.readline().strip())
# Read ONLY element identifiers in reporter tables, no activities.
pairs={}
for p in (ART/'intakes').glob('gse310760*/data.tsv.gz'):
 ids=collections.defaultdict(set)
 with gzip.open(p,'rt') as f:
  reader=csv.DictReader(f,delimiter='\t')
  for row in reader:
   m=re.fullmatch(r'(.+)\.(fwd|rev)',row['Element'])
   if m:ids[m[1]].add(m[2])
 pairs[p.parent.name]=sorted(x for x,v in ids.items() if v=={'fwd','rev'})
atomic(PROJECT/'paired-identifiers.json',pairs)
print('PAIR COUNTS', {k:len(v) for k,v in pairs.items()})
