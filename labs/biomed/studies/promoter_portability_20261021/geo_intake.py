from common import *
import sys,re,concurrent.futures
sys.path.insert(0,str(CODE.parents[1]))
from tools.dataset_intake import download
jobs=[]
for g in ['GSE310760','GSE279057','GSE156857']:
 t=(ART/f'metadata/{g}-ftp.html').read_text()
 for name in re.findall(r'href="([^"]+)"',t):
  if not name.startswith(g):continue
  if g=='GSE310760' and 'paBC' not in name:continue
  if g=='GSE279057' and 'annotations' not in name:continue
  if g=='GSE156857' and not name.endswith('.tsv.gz'):continue
  jobs.append((g,name))
def one(item):
 g,n=item;did=n.lower().replace('_','-').replace('.','-');dest=ART/'intakes'/did
 if (dest/'manifest.json').exists():return n,'cached'
 try:
  m=download(source_id='geo',url=f'https://ftp.ncbi.nlm.nih.gov/geo/series/{g[:-3]}nnn/{g}/suppl/{n}',staging_root=ART/'intakes',dataset_id=did,release_or_accession=g+':official supplementary file:'+n,independent_unit='DNA locus, not small molecule; reporter element',terms_url='https://www.ncbi.nlm.nih.gov/home/about/policies/',reuse_basis='Public GEO submitter data for attributed internal secondary research; retain original study terms. GEO availability is not an unrestricted file license or ethics exemption. No redistribution.',citation={'GSE310760':'Paramo et al. DOI10.1038/s41467-026-68780-y','GSE279057':'Bose et al. DOI10.1101/2025.10.13.659964','GSE156857':'Roberts et al. DOI10.1101/gr.270751.120'}[g],upstream_study_ids=[g],filename='data.tsv.gz',max_bytes=128*1024**2,retries=1)
  return n,m['bytes']
 except Exception as e:return n,str(e)
with concurrent.futures.ThreadPoolExecutor(2) as ex:
 for v in ex.map(one,jobs):print(v,flush=True)
