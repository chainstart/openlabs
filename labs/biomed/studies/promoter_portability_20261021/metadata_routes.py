from common import *
import concurrent.futures,re
commit=json.loads((ART/'metadata/quasarr-commit.json').read_text())['sha']
jobs=[(f'https://api.github.com/repos/haiyuan-yu-lab/quasarr-seq-manuscript/git/trees/{commit}?recursive=1','quasarr-tree.json')]
for i in [1,3,6]:jobs.append((f'https://raw.githubusercontent.com/haiyuan-yu-lab/quasarr-seq-manuscript/{commit}/Fig.%20{i}.Rmd',f'quasarr-fig{i}.Rmd'))
for g in ['GSE310760','GSE279057','GSE156857','GSE128325']:
 jobs.append((f'https://ftp.ncbi.nlm.nih.gov/geo/series/{g[:-3]}nnn/{g}/suppl/',f'{g}-ftp.html'))
 jobs.append((f'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={g}&targ=self&form=text&view=full&tool=OpenLabs',f'{g}-alternate.txt'))
with concurrent.futures.ThreadPoolExecutor(2) as ex:
 for (u,n),b in zip(jobs,ex.map(lambda x:fetch(*x),jobs)):
  print(n,len(b),flush=True)
  if n.endswith('.html'):print(re.findall(r'href="([^"]+)"',b.decode(errors='replace')),flush=True)
atomic(PROJECT/'author-code-pin.json',dict(repository='https://github.com/haiyuan-yu-lab/quasarr-seq-manuscript',commit=commit))
