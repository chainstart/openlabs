from intake import *
from urllib.parse import quote,urlencode
sources=json.loads((OD/'nearest-work-audit.json').read_text())['sources']
out=[]
for s in sources:
    doi=s['doi']; url='https://api.crossref.org/works/'+quote(doi,safe='')
    p=fetch(s['name']+'_crossref_refresh.json',url)
    out.append(dict(name=s['name'],doi=doi,endpoint=url,payload=str(p)))
    if s['publication_status']=='preprint':
        u='https://api.biorxiv.org/details/biorxiv/'+doi+'/na/json'
        q=fetch(s['name']+'_biorxiv_refresh.json',u);out.append(dict(name=s['name'],endpoint=u,payload=str(q)))
for i,query in enumerate(['massively parallel reporter assay measurement reliability promoter responsiveness','reporter assay position context promoter calibration','promoter saturation mutagenesis background dependence']):
    url='https://api.crossref.org/works?'+urlencode({'query':query,'filter':'from-pub-date:2024-01-01','rows':15})
    p=fetch('search_'+str(i)+'.json',url);out.append(dict(query=query,endpoint=url,payload=str(p)))
write(DATA/'literature-refresh-index.json',out)
print('saved',len(out),'queries')
