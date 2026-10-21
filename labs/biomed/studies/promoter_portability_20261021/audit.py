from common import *
import re,concurrent.futures,xml.etree.ElementTree as ET
status('primary_source_metadata','Read plans, skills, registry and contract; inherited cgroup verified','QUASARR pairing, independent routes, prospective freeze')
jobs=[('https://www.nature.com/articles/s41467-026-68780-y','quasarr.html'),('https://api.github.com/repos/haiyuan-yu-lab/quasarr-seq-manuscript/commits/main','quasarr-commit.json'),('https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE310760&targ=self&form=text&view=full','GSE310760.txt'),('https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE279057&targ=self&form=text&view=full','GSE279057.txt'),('https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE156857&targ=self&form=text&view=full','GSE156857.txt'),('https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=promoter%20directionality%20reporter%20assay&format=json&pageSize=30','literature-europepmc.json'),('https://api.crossref.org/works?query=promoter%20directionality%20reporter%20assay&rows=15','literature-crossref.json'),('https://api.github.com/repos/boseHere/TSS_MPRA_2025/commits/main','bose-commit.json')]
with concurrent.futures.ThreadPoolExecutor(2) as ex:
 for (u,n),b in zip(jobs,ex.map(lambda x:fetch(*x),jobs)):
  print(n,len(b))
p=ART/'metadata/quasarr.html'
if p.exists():
 links=re.findall(r'https[^\s"<>]+',p.read_text())
 atomic(PROJECT/'quasarr-supp-links.json',sorted(set(x for x in links if 'MOESM' in x)))
for n in ['GSE310760','GSE279057','GSE156857']:
 t=(ART/f'metadata/{n}.txt').read_text()
 print(n,'\n'.join(x for x in t.splitlines() if re.search('supplementary|relation|summary|overall_design',x,re.I)))
old=Path('/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-functional-genomics-20261021/metadata')
for n in ['PMC8092006-xml-accept.xml','PMC12632999-xml-accept.xml']:
 root=ET.parse(old/n).getroot();out=[]
 for sec in root.iter('sec'):
  t=' '.join(sec.itertext())
  if re.search('data access|data availability',t,re.I):out.append(t)
 atomic(PROJECT/(n+'.accessions.json'),dict(source=str(old/n),sha256=sha(old/n),accessions=sorted(set(re.findall(r'GSE\d+|SRP\d+', ' '.join(root.itertext())))),sections=out))
print((PROJECT/'quasarr-supp-links.json').read_text())
