from common import *
for i in [2,3,15,16]:
    name=f'bergman_MOESM{i}.txt'
    p=fetch(name,f'https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41586-022-04877-w/MediaObjects/41586_2022_4877_MOESM{i}_ESM.txt',limit=32*1024**2,terms={'terms_url':'https://www.nature.com/articles/s41586-022-04877-w#rightslink','reuse_basis':'Official publicly supplied supplementary data; internal noncommercial attributed research, no redistribution'},accession=f'DOI10.1038/s41586-022-04877-w:MOESM{i}',study='GSE184426')
    if p:
        with p.open() as f:print(name,next(f)[:5000],flush=True)
