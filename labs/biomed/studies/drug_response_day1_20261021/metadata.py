"""Fetch small official source metadata, not experimental outcomes."""
import urllib.request,json
from audit import OUT,save,status
URLS={
 'ulrich_repo':'https://api.github.com/repos/nadinulrich/log_Sw_prediction/contents',
 'ulrich_commit':'https://api.github.com/repos/nadinulrich/log_Sw_prediction/commits?per_page=1',
 'dataverse':'https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/?persistentId=doi:10.57745/CZVZIA',
 'almanac_wiki':'https://wiki.nci.nih.gov/spaces/NCIDTPdata/pages/338237347/NCI-ALMANAC',
}
def main():
    rec=[]
    for key,url in URLS.items():
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'OpenLabs-public-research/0.1'}),timeout=25) as r:
                b=r.read(4*1024**2+1)
                if len(b)>4*1024**2: raise ValueError('metadata ceiling')
                p=OUT/'access'/f'{key}.json';p.write_bytes(b)
                rec.append(dict(key=key,url=url,status=r.status,path=str(p),bytes=len(b)))
                if key=='ulrich_repo': print(key,[(x['name'],x['size']) for x in json.loads(b)])
                if key=='dataverse':
                    j=json.loads(b)['data']['latestVersion'];print('dataverse',j.get('license'),j.get('termsOfUse'),[(x['dataFile']['id'],x['dataFile']['filename'],x['dataFile']['filesize']) for x in j['files']])
        except Exception as e: rec.append(dict(key=key,url=url,error=str(e)))
        save(OUT/'metadata-probes.json',rec)
    status('candidate_metadata_review','Review exact payload provenance and file reuse terms before any model plan.',[str(OUT/'metadata-probes.json')])
    print(json.dumps(rec))
if __name__=='__main__': main()
