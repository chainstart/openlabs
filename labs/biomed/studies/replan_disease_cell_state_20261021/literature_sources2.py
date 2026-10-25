from common import *
acc='GSE199949'
fetch(f'https://ftp.ncbi.nlm.nih.gov/geo/series/{acc[:-3]}nnn/{acc}/matrix/{acc}_series_matrix.txt.gz',acc+'_series_matrix.txt.gz')
fetch(f'https://ftp.ncbi.nlm.nih.gov/geo/series/{acc[:-3]}nnn/{acc}/suppl/',acc+'_files.html')
q='EXT_ID:31600171 OR EXT_ID:36725082 OR EXT_ID:32602730 OR EXT_ID:34724391'
p=fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=core&query='+urllib.parse.quote(q),'original_bulk_papers.json')
if p:
 for x in json.loads(p.read_text())['resultList']['result']:
  if x.get('pmcid'):fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/'+x['pmcid']+'/fullTextXML',x['pmcid']+'.xml')
fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13605140/fullTextXML','PMC13605140.xml')
q='("pulmonary fibrosis") AND ("repeatability" OR "intraclass" OR "regional heterogeneity" OR "sampling variability")'
fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&pageSize=30&resultType=core&query='+urllib.parse.quote(q),'programme_sampling_literature.json')
