from common import *

DOIS=['10.1186/s13321-025-00972-y','10.18632/oncotarget.10010','10.1038/s42004-026-01916-9','10.1093/bioinformatics/btag382','10.1038/s41467-026-72903-w','10.1371/journal.pcbi.1013232']
for i,doi in enumerate(DOIS):
    fetch(f'paper-{i}-crossref.json','https://api.crossref.org/works/'+urllib.parse.quote(doi,safe=''),provenance={'database':'Crossref','doi':doi})
fetch('pmc-ids.json','https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?format=json&ids='+','.join(DOIS))
for repo in ['preprocess_drp_data','drevalpy']:
    p=fetch(repo+'-commit.json',f'https://api.github.com/repos/daisybio/{repo}/commits/HEAD')
    if p:
        sha=json.loads(p.read_text())['sha']
        fetch(repo+'-tree.json',f'https://api.github.com/repos/daisybio/{repo}/git/trees/{sha}?recursive=1')
        fetch(repo+'-README.md',f'https://raw.githubusercontent.com/daisybio/{repo}/{sha}/README.md')
        fetch(repo+'-LICENSE',f'https://raw.githubusercontent.com/daisybio/{repo}/{sha}/LICENSE')
fetch('zenodo-12633909.json','https://zenodo.org/api/records/12633909')
