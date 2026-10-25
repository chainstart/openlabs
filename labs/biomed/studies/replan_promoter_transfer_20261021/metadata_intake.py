from intake import *
from urllib.parse import quote
write(DATA/'source-registry.json',dict(time=now(),allowed_hosts=sorted(ALLOWED),sources=[dict(id='geo_klein',accession='GSE142696',provider='NCBI GEO',release='public processed files; Last-Modified recorded at retrieval',terms_url='https://www.ncbi.nlm.nih.gov/home/about/policies/',reuse_basis='Public author-deposited processed data for attributed internal research; no redistribution. Klein et al Nature Methods 2020 author manuscript in PMC.',independent_unit='genomic locus; same HepG2 study, technical/biological replicate metadata audited separately'),dict(id='author_github',reuse_basis='Read source repository metadata; inspect individual LICENSE before numerical use')]))
for name in ['9MPRA.ActivityRatios.IndividualReps.tsv.gz','9MPRA.ActivityRatios.tsv.gz','ShortMedLong.ActivityRatios.IndividualReps.tsv.gz']:
    fname='GSE142696_'+name
    fetch(fname,'https://ftp.ncbi.nlm.nih.gov/geo/series/GSE142nnn/GSE142696/suppl/'+fname,kind='processed_measurements_sealed',terms='https://www.ncbi.nlm.nih.gov/home/about/policies/',study='Klein2020 GSE142696')
for name,doi in [('longrange','10.1101/2025.04.21.649048'),('extra','10.1101/2024.12.08.627402'),('mprabc','10.1093/nar/gkag554')]:
    fetch(name+'_crossref.json','https://api.crossref.org/works/'+quote(doi,safe=''))
    if '10.1101' in doi:fetch(name+'_biorxiv.json','https://api.biorxiv.org/details/biorxiv/'+doi+'/na/json')
for name,repo in [('longrange','yaweiwu233/long-range-MPRA'),('tan','yj-tan/ExP-MPRA')]:
    p=fetch(name+'_repo.json','https://api.github.com/repos/'+repo)
    if p:
        d=json.loads(p.read_text());q=fetch(name+'_tree.json','https://api.github.com/repos/'+repo+'/git/trees/'+d['default_branch']+'?recursive=1')
        if q:
            tree=json.loads(q.read_text())
            for f in tree['tree']:
                if f['path'] in ('README.md','LICENSE','code/README.md'):
                    fetch(name+'_'+f['path'].replace('/','_'),'https://raw.githubusercontent.com/'+repo+'/'+tree['sha']+'/'+f['path'])
print('intake finished')
