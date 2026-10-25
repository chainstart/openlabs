from common import *
DOIS={'roberts':'10.1101/gr.270751.120','agarwal':'10.1038/s41586-024-08430-9','zhang':'10.1186/s13059-025-03828-8','quasarr':'10.1038/s41467-026-68780-y','parm':'10.1038/s41586-025-10093-z','tan':'10.64898/2026.06.25.734173','regtrust':'10.64898/2026.08.20.745945'}
records=[]
for name,doi in DOIS.items():
    p=fetch(f'{name}_crossref.json','https://api.crossref.org/works/'+urllib.parse.quote(doi,safe=''),study=doi)
    q=fetch(f'{name}_epmc.json','https://www.ebi.ac.uk/europepmc/webservices/rest/search?query='+urllib.parse.quote('DOI:'+doi)+'&format=json',study=doi)
    rec=dict(name=name,doi=doi,crossref=str(p),europepmc=str(q))
    if q:
        hits=json.loads(q.read_text()).get('resultList',{}).get('result',[])
        rec['hits']=hits
        if hits and hits[0].get('pmcid'):
            pmc=hits[0]['pmcid'];rec['fulltext']=str(fetch(f'{name}.xml',f'https://www.ebi.ac.uk/europepmc/webservices/rest/{pmc}/fullTextXML',study=doi))
    if name in ('tan','regtrust'):
        rec['biorxiv']=str(fetch(f'{name}_biorxiv.json',f'https://api.biorxiv.org/details/biorxiv/{doi}/na/json',study=doi))
    records.append(rec);write(DATA/'literature-index.json',records)
    print(name,rec.get('hits',[]),flush=True)
status('literature_and_data_gate',['7 DOI metadata queries and available fulltexts archived'],['read nearest methods','audit new library sequence files'])
