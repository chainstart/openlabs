"""Bounded official metadata/HEAD probes; records failures without bypass."""
import json, urllib.request
from audit import OUT,save,status
URLS={
 'drugcomb_summary':'https://drugcomb.fimm.fi/jing/summary_v_1_5.csv',
 'drugcomb_api':'https://api.drugcomb.org/',
 'drugcomb_terms':'https://drugcomb.org/download/',
 'prism_figshare':'https://api.figshare.com/v2/articles/11791698',
 'almanac_official':'https://dtp.cancer.gov/discovery_development/nci-60/almanac.htm',
 'solubility_data':'https://api.github.com/repos/datamol-io/solubility-prediction/contents',
 'chembl_status':'https://www.ebi.ac.uk/chembl/api/data/status.json',
}
def main():
    records=[]
    for key,url in URLS.items():
        method='HEAD' if key=='drugcomb_summary' else 'GET'
        try:
            req=urllib.request.Request(url,method=method,headers={'User-Agent':'OpenLabs-biomed/0.1 public research','Accept':'application/json' if 'api.' in url else '*/*'})
            with urllib.request.urlopen(req,timeout=25) as r:
                b=r.read(3*1024**2+1) if method=='GET' else b''
                if len(b)>3*1024**2: raise ValueError('metadata exceeds 3MiB ceiling')
                p=OUT/'access'/f'{key}.payload'; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b)
                records.append(dict(key=key,url=url,method=method,status=r.status,headers=dict(r.headers),payload=str(p),bytes=len(b)))
        except Exception as e: records.append(dict(key=key,url=url,method=method,error=str(e)))
        save(OUT/'access-probes.json',records)
    status('bounded_candidate_access_probed','Choose strongest distinct question after direct-neighbor audit; freeze before outcome analysis.',[str(OUT/'access-probes.json')])
    print(json.dumps([{k:v for k,v in x.items() if k not in ['headers']} for x in records],indent=2))
if __name__=='__main__':main()
