from common import *
import itertools,collections
m=json.loads((PROJECT/'design-metadata.json').read_text());p=json.loads((PROJECT/'paired-identifiers.json').read_text())
p={('original' if '-cnpl-tre202-mre-' in k else 'MYC' if '-pmyc-' in k else 'GAPDH' if '-pgapdh-' in k else 'APOBEC3F'):set(v) for k,v in p.items()}
for a,b in itertools.combinations(p,2):
 ids=sorted(p[a]&p[b]&m['sequences'].keys()&m['coordinates'].keys()&m['classes'].keys());prox=[x for x in ids if m['classes'][x]['proximity']=='Proximal'];blocks={m['coordinates'][x][0]+':'+str(m['coordinates'][x][1]//1000000) for x in prox}
 print(a,b,'allannotated',len(ids),'proximal',len(prox),'blocks',len(blocks))
