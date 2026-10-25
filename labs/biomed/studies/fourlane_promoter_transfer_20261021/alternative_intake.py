from common import *
for suffix in ('Synthetic_Promoter_Libraries_Small_and_Large_Data.txt.gz','Saturated_Mutagenesis_Validation_Library_Data.txt.gz','Motif_Insertion_Validation_Library_Data.txt.gz'):
    name='GSE301246_'+suffix
    fetch(name,'https://ftp.ncbi.nlm.nih.gov/geo/series/GSE301nnn/GSE301246/suppl/'+name,limit=16*1024**2,terms={'terms_url':'https://www.ncbi.nlm.nih.gov/geo/info/disclaimer.html','reuse_basis':'Official PARM processed validation sequence/count tables; internal attributed analysis, no redistribution'},accession='GSE301246',study='10.1038/s41586-025-10093-z')
for repo in ['broadinstitute/ExP-model-fit']:
    p=fetch('bergman_repo.json','https://api.github.com/repos/'+repo)
    if p:
        branch=json.loads(p.read_text())['default_branch']
        q=fetch('bergman_tree.json',f'https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1')
        if q:print([(x['path'],x.get('size')) for x in json.loads(q.read_text()).get('tree',[])],flush=True)
fetch('bergman_crossref.json','https://api.crossref.org/works/10.1038%2Fs41586-022-04877-w')
fetch('klein_crossref.json','https://api.crossref.org/works/10.1038%2Fs41592-020-0965-y')
