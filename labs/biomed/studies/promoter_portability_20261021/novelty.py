from common import *
import xml.etree.ElementTree as E,re,concurrent.futures
old=Path('/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-functional-genomics-20261021/metadata')
root=E.parse(old/'PMC12632999-xml-accept.xml').getroot()
for s in root.iter('sec'):
 title=s.find('title');title=''.join(title.itertext()) if title is not None else ''
 if re.search('library|direction|orient|reporter|data availability',title,re.I):
  print(title, ' '.join(s.itertext())[:1400])
b=json.loads((ART/'metadata/bose-commit.json').read_text());commit=b[0]['sha'] if isinstance(b,list) else b['sha']
jobs=[(f'https://api.github.com/repos/boseHere/TSS_MPRA_2025/git/trees/{commit}?recursive=1','bose-tree.json')]
with concurrent.futures.ThreadPoolExecutor(2) as ex:
 for (u,n),b in zip(jobs,ex.map(lambda x:fetch(*x),jobs)):print(n,len(b))
# Deduplicate multi-source literature on normalized DOI. Preserve source records.
merged={}
e=json.loads((ART/'metadata/literature-europepmc.json').read_text())
c=json.loads((ART/'metadata/literature-crossref.json').read_text())
for source,rows in [('EuropePMC',e['resultList']['result']),('Crossref',c['message']['items'])]:
 for r in rows:
  doi=r.get('doi',r.get('DOI','')).lower().removeprefix('https://doi.org/').strip()
  key=doi or str(r.get('title'))
  merged.setdefault(key,dict(doi=doi,records=[]))['records'].append(dict(source=source,record=r))
atomic(PROJECT/'literature-search.json',dict(time=now(),queries=['promoter directionality reporter assay'],mcp_status='academic-search MCP unavailable: no callable tools; used T1 Crossref API and EuropePMC API',deduplication='normalized DOI; no uncertain title merges',records=list(merged.values())))
