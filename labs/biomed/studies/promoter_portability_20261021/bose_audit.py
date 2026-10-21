from common import *
import gzip,csv,re
pin=json.loads((ART/'metadata/bose-tree.json').read_text())['sha']
for n in ['MPRAnalyze.R','elastic-net.R','glm.R','LICENSE']:
 b=fetch(f'https://raw.githubusercontent.com/boseHere/TSS_MPRA_2025/{pin}/{n}','bose-'+n)
 print(n,len(b))
 for line in b.decode(errors='replace').splitlines():
  if re.search('read.|[Oo]rient|[Pp]osition|forward|reverse|promoter|enhancer',line):print(line[:250])
p=list((ART/'intakes').glob('gse279057*/data.tsv.gz'))
if p:
 with gzip.open(p[0],'rt') as f:
  reader=csv.reader(f,delimiter='\t');h=next(reader);print('HEADER',h)
  for i,r in enumerate(reader):
   if i<3:print('ANNOTATION',r)
 atomic(PROJECT/'bose-schema.json',dict(header=h,nrows=i+1,code_commit=pin))
