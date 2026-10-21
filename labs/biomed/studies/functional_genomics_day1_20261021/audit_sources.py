import json,re,urllib.parse
from common import *

status('literature_and_terms_audit','Is signed orientation dependence portable across three cell contexts?',
       'guard --task-type cpu -- labs/biomed/.venv/bin/python labs/biomed/studies/functional_genomics_day1_20261021/audit_sources.py')
urls={
 'encode-terms-current.html':'https://www.encodeproject.org/help/citing-encode/',
 'encode-policy-current.html':'https://www.encodeproject.org/about/data-use-policy/',
 'agarwal2025.html':'https://www.nature.com/articles/s41586-024-08430-9',
 'siddiq2024.html':'https://www.nature.com/articles/s41559-024-02582-7',
 'liao2026.html':'https://www.nature.com/articles/s41467-026-74517-8',
}
for name,url in urls.items():
    try:
        b=fetch(url,name)
        links=sorted(set(re.findall(r'https?[^"<> ]+MOESM[^"<> ]+',b.decode())))
        print(name,'bytes',len(b),'supplement links',links[:12])
    except Exception as e: print(name,str(e))
queries=['(lentiMPRA AND orientation)','(MPRA AND directionality AND cell)','(yeast AND TDH3 AND fitness AND expression)']
for i,q in enumerate(queries):
    url='https://www.ebi.ac.uk/europepmc/webservices/rest/search?'+urllib.parse.urlencode(dict(query=q,format='json',pageSize=12,sort_date='y'))
    try:
        d=json.loads(fetch(url,f'europepmc-search-{i}.json'))
        print(q,d.get('hitCount'),[(x.get('title'),x.get('firstPublicationDate'),x.get('doi')) for x in d.get('resultList',{}).get('result',[])][:8])
    except Exception as e: print(q,str(e))
status('literature_and_terms_audit_complete','Signed orientation dependence across cells: novelty remains provisional',
       'audit_sources.py completed',list((ART/'metadata').glob('*access.json')))
