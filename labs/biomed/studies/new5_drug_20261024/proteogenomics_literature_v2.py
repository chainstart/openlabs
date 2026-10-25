from pathlib import Path
import requests,json,urllib.parse,xml.etree.ElementTree as ET,hashlib,datetime
O=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-root-20261024/proteogenomics-repair-v2/literature');O.mkdir()
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
records=[]
for doi in ['10.1101/gr.276378.121','10.1038/s44320-025-00122-4','10.1038/s44320-026-00187-9']:
 slug=doi.split('/')[-1];urls=[('crossref','https://api.crossref.org/works/'+urllib.parse.quote(doi,safe='')),('europepmc','https://www.ebi.ac.uk/europepmc/webservices/rest/search?query='+urllib.parse.quote('DOI:'+doi)+'&format=json&resultType=core')]
 for kind,url in urls:
  try:
   r=requests.get(url,timeout=45);f=O/(slug+'-'+kind+'.json');f.write_bytes(r.content);records.append({'doi':doi,'database':kind,'url':url,'status_code':r.status_code,'path':str(f),'sha256':hashlib.sha256(r.content).hexdigest()});r.raise_for_status()
   if kind=='europepmc':
    hits=r.json()['resultList']['result'];print(doi,[(h.get('title'),h.get('pmcid')) for h in hits],flush=True)
    for h in hits[:1]:
     if h.get('pmcid'):
      u='https://www.ebi.ac.uk/europepmc/webservices/rest/'+h['pmcid']+'/fullTextXML';rr=requests.get(u,timeout=45);ff=O/(slug+'-article.xml');ff.write_bytes(rr.content);records.append({'doi':doi,'database':'EuropePMC_fullTextXML','url':u,'status_code':rr.status_code,'path':str(ff),'sha256':hashlib.sha256(rr.content).hexdigest()})
  except Exception as e:records.append({'doi':doi,'database':kind,'url':url,'error':str(e)})
(O/'LOOKUP_MANIFEST.json').write_text(json.dumps({'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'requests':records},indent=2)+'\n')
