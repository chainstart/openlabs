from common import *
url='https://ftp.ncbi.nlm.nih.gov/geo/series/GSE135nnn/GSE135893/suppl/GSE135893_matrix.mtx.gz'
start=time.monotonic();n=0;rec=dict(at=now(),url=url,purpose='New nonoverlapping range transfer feasibility, original prior prefix reused read-only',range='bytes=65536-1114111')
try:
 def alarm(*_):raise TimeoutError('60-second source feasibility probe')
 signal.signal(signal.SIGALRM,alarm);signal.alarm(60)
 with urllib.request.urlopen(urllib.request.Request(url,headers={'Range':rec['range']}),timeout=25) as r:
  rec.update(http_status=r.status,content_range=r.headers.get('Content-Range'))
  assert r.status==206 and r.headers.get('Content-Range','').startswith('bytes 65536-1114111/'),rec
  with (ART/'original_range_65536_1114111.part').open('wb') as f:
   while n<1048576:
    b=r.read1(min(65536,1048576-n))
    if not b:break
    f.write(b);n+=len(b)
 rec['complete']=n==1048576
except Exception as e:rec['error']=repr(e)
finally:signal.alarm(0)
rec.update(bytes=n,seconds=time.monotonic()-start,bytes_per_second=n/(time.monotonic()-start))
p=ART/'original_range_65536_1114111.part'
if p.exists():rec['sha256']=sha(p)
atomic(DATA/'original_source_probe.json',rec);print(json.dumps(rec))
