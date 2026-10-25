from common import *
import gzip,io,re
def probe(name,url,n=262144):
    rec=dict(time=now(),source_url=url,requested_range=f'bytes=0-{n-1}',purpose='schema only; incomplete payload not eligible for numerical inference',attempts=[])
    for attempt in range(2):
        raw=b''
        try:
            req=urllib.request.Request(url,headers={'Range':f'bytes=0-{n-1}','User-Agent':'OpenLabs-promoter-research/1.0'})
            with urllib.request.urlopen(req,timeout=30) as r:
                rec.update(http_status=r.status,headers=dict(r.headers),final_url=r.url)
                cr=r.headers.get('Content-Range','')
                if r.status!=206 or not re.match(rf'bytes 0-{n-1}/\d+',cr):raise ValueError('Range unsupported or invalid; no full payload consumed')
                raw=r.read(n+1)
                if len(raw)!=n:raise ValueError('Wrong range length')
            p=ART/'payload'/name;p.write_bytes(raw)
            rec.update(actual_bytes=n,sha256=sha(p),payload=str(p),status='partial_schema_only')
            f=gzip.GzipFile(fileobj=io.BytesIO(raw));header=f.readline().decode();row=f.readline().decode().split('\t')
            rec['header']=header
            rec['first_row_metadata']=row[:4]
            print(name,header,row[:4],flush=True)
            break
        except Exception as e:rec['attempts'].append(dict(error=str(e),actual_bytes=len(raw)));time.sleep(1)
    write(ART/'manifests'/f'{name}.json',rec)
if __name__=='__main__':
    partial=ART/'payload/GSE301246_PARM_Training_Library_v1_pHY3_raw_counts.txt.gz.part'
    write(ART/'manifests/parm-aborted-download.json',dict(time=now(),reason='Slow full download replaced with official Range schema and smaller processed alternatives before committing substantial budget',actual_bytes=partial.stat().st_size,sha256=sha(partial),status='incomplete',payload=str(partial)))
    for suffix in ['PARM_Training_Library_v1_pHY3_normalized_fold0.bed.gz','PARM_Training_Library_v2_MH4_raw_counts.txt.gz']:
        name='GSE301246_'+suffix
        probe(name+'.prefix','https://ftp.ncbi.nlm.nih.gov/geo/series/GSE301nnn/GSE301246/suppl/'+name)
    fetch('GSE142696.txt','https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE142696&targ=self&form=text&view=full')
    fetch('GSE142696_inventory.html','https://ftp.ncbi.nlm.nih.gov/geo/series/GSE142nnn/GSE142696/suppl/')
    fetch('bergman.xml','https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9262863/fullTextXML')
    fetch('GSE184426.txt','https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE184426&targ=self&form=text&view=full')
    fetch('GSE184426_inventory.html','https://ftp.ncbi.nlm.nih.gov/geo/series/GSE184nnn/GSE184426/suppl/')
