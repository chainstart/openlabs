from common import *
for pmc in ['PMC8865586','PMC6948862','PMC7667907']:
 fetch('https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/'+pmc+'/unicode',pmc+'_bioc.json',timeout=45)
q='TITLE_ABS:("pulmonary fibrosis") AND TITLE_ABS:("transcriptomic" OR "gene expression") AND TITLE_ABS:("sampling" OR "regional" OR "heterogeneity")'
fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&pageSize=100&resultType=core&query='+urllib.parse.quote(q),'programme_sampling_targeted.json')
