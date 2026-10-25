from common import *
queries=['(idiopathic pulmonary fibrosis) AND (transcriptomic OR deconvolution) AND (age OR cross-study OR pseudobulk) AND 2024:2026[dp]','(Habermann) AND (pulmonary fibrosis)']
for i,q in enumerate(queries):
 p=fetch('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&retmax=30&term='+urllib.parse.quote(q),f'pubmed_search_{i}.json')
 if p:
  ids=json.loads(p.read_text()).get('esearchresult',{}).get('idlist',[])
  if ids:fetch('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id='+','.join(ids),f'pubmed_records_{i}.xml')
for doi in ['10.1093/bib/bbac430','10.1038/s41467-025-56623-1','10.1186/s13059-025-03776-3','10.1038/s41467-025-62579-z','10.1038/s41592-026-03007-y','10.1038/s41588-025-02080-x']:
 fetch('https://api.crossref.org/works/'+urllib.parse.quote(doi,safe=''),doi.split('/')[-1]+'_crossref_refresh.json',timeout=60)
fetch('https://api.github.com/repos/KropskiLab/SingleCellIPF/contents','Habermann_repo_contents.json',timeout=60)
