from common import *
from initial_audit import DOIS
import xml.etree.ElementTree as ET

for i,doi in enumerate(DOIS):
    p=fetch(f'epmc-{i}.json','https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&query='+urllib.parse.quote('DOI:'+doi))
    if p:
        for r in json.loads(p.read_text()).get('resultList',{}).get('result',[]):
            if r.get('pmcid'):
                f=fetch(f'epmc-{i}.xml','https://www.ebi.ac.uk/europepmc/webservices/rest/'+r['pmcid']+'/fullTextXML')
                if f:
                    root=ET.parse(f)
                    (ART/'intake'/f'epmc-{i}-readable.txt').write_text('\n\n'.join(' '.join(s.itertext()) for s in root.findall('.//body/sec')))
queries=['drug response prediction fitted IC50 raw viability ranking replicate','drug sensitivity fit summary extrapolation independent measurement prediction','PRISM MTS010 repeat drug response prediction']
for i,q in enumerate(queries):
    fetch(f'crossref-search-{i}.json','https://api.crossref.org/works?rows=10&query='+urllib.parse.quote(q))
