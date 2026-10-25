"""Bounded read-only public NCI GraphQL queries; no authentication or mutations."""
from common import *
import argparse

def query(name,q):
    assert q.lstrip().startswith(('{','query')) and 'mutation' not in q
    with (ART/'intake.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        u='https://studycatalog.cancer.gov/v1/graphql/'
        r=requests.post(u,json={'query':q,'variables':{}},timeout=(15,45),stream=True)
        data=bytearray()
        for chunk in r.iter_content(65536):
            data.extend(chunk)
            if len(data)>8*1024**2:raise ValueError('8MiB metadata cap')
        p=ART/'intake'/name
        assert not p.exists()
        p.write_bytes(data)
        write(p.with_name(p.name+'.manifest.json'),{'source_url':u,'method':'POST read-only GraphQL','query':q,'variables':{},'status':r.status_code,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'at':now(),'terms':'Public NCI metadata only; not file reuse authorization'})
        ledger=json.loads((ART/'download-ledger.json').read_text());ledger['actual_bytes']+=len(data)
        ledger['requests'].append({'name':p.name,'bytes':len(data),'at':now()});write(ART/'download-ledger.json',ledger)
        print(r.status_code,len(data),bytes(data[:1500]).decode())

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('name');a.add_argument('query');x=a.parse_args();query(x.name,x.query)
