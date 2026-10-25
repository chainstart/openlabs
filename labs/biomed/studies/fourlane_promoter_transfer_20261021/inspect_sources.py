from common import *
import xml.etree.ElementTree as ET,re
for name in ['parm','tan','zhang','quasarr','agarwal','roberts']:
    p=ART/'payload'/f'{name}.xml'
    if not p.exists():continue
    root=ET.parse(p).getroot()
    out=[]
    for el in root.iter():
        if el.tag in ('p','title'):
            s=' '.join(el.itertext())
            if re.search(r'GSE|github|zenodo|orientation|reverse|[Ll]ibrary|[Dd]ata availability|[Ss]equences were|[Ss]equence length',s):out.append(s)
    (ART/f'{name}-methods-extract.txt').write_text('\n\n'.join(out))
for acc in ('GSE301246','GSE334082'):
    fetch(f'{acc}.txt',f'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={acc}&targ=self&form=text&view=full',accession=acc)
for repo in ('vansteensellab/PARM','yj-tan/ExP-MPRA'):
    n=repo.split('/')[-1]
    p=fetch(n+'_repo.json','https://api.github.com/repos/'+repo)
    if p:
        branch=json.loads(p.read_text()).get('default_branch','main')
        q=fetch(n+'_tree.json',f'https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1')
        if q:
            d=json.loads(q.read_text()); print(n,d.get('sha'),[(x['path'],x.get('size')) for x in d.get('tree',[]) if x['type']=='blob'],flush=True)
fetch('tan.xml','https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13320843/fullTextXML')
fetch('klein.xml','https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7727316/fullTextXML')
