from common import *
import gzip,csv,collections
import pandas as pd
out={}
for acc in ['GSE150910','GSE124685','GSE184316']:
 rows=list(csv.reader(gzip.open(ART/'payload'/f'{acc}_series_matrix.txt.gz','rt'),delimiter='\t'))
 d={}; desc=[]
 for r in rows:
  if not r:continue
  if r[0] in ['!Sample_geo_accession','!Sample_title','!Sample_source_name_ch1']:d[r[0][8:]]=r[1:]
  if r[0]=='!Sample_characteristics_ch1':
   keys=[v.split(': ',1)[0] for v in r[1:]]
   for key in set(keys):d[key]=[v.split(': ',1)[1] if v.startswith(key+': ') else '' for v in r[1:]]
  if r[0].startswith('!Series_') or r[0]=='!Sample_data_processing':desc.append(r[:2])
 df=pd.DataFrame(d);df.to_csv(DATA/f'{acc}_metadata.csv',index=False)
 summary={c:dict(collections.Counter(df[c])) for c in df if c not in ['title','geo_accession']}
 out[acc]=dict(n=len(df),columns=list(df),summary=summary,series=desc)
 print(acc,len(df));print(json.dumps(summary,ensure_ascii=False)[:6500]);print(desc[:12])
atomic(DATA/'new_metadata_feasibility.json',out)
