"""Official file-level intake, bounded sequential HTTP, no outcome analysis."""
import fcntl,json,sys,hashlib
from urllib.parse import urlparse
from common import *
sys.path.insert(0,str(CODE.parents[1]))
from tools.dataset_intake import download

SOURCE='encode_mpra_agarwal_2025'
TERMS='https://www.encodeproject.org/help/citing-encode/'

def register():
    # Official experiment JSON explicitly names the public object-store hostname.
    d=json.loads((ART/'metadata/ENCSR405QCT.json').read_text())
    hosts={urlparse(x.get('cloud_metadata',{}).get('url','')).hostname for x in d['files']}
    assert 'encode-public.s3.amazonaws.com' in hosts
    assert (ART/'metadata/encode-terms-current.html').exists()
    entry=dict(source_id=SOURCE,phase=1,access='public',
        name='ENCODE Agarwal et al. 2025 paired-orientation lentiMPRA',
        documentation_url='https://www.nature.com/articles/s41586-024-08430-9',
        terms_url=TERMS,reuse_basis='Released ENCODE MPRA processed tables; official ENCODE external-user policy permits download and analysis with accession, producer and Consortium attribution. Article CC BY 4.0. No restricted raw data used.',
        allowed_hosts=['www.encodeproject.org','encode-public.s3.amazonaws.com'],
        citation_policy='Agarwal et al. Nature 639:411–420 (2025), DOI10.1038/s41586-024-08430-9; ENCODE Consortium and exact experiment/file accessions.',
        independence_risks=['Cell contexts share synthetic library and upstream study; not independent laboratories','Biological replicates are cultures, not independent donors','Shared genomic loci and sequences require grouped validation'],
        checked_at='2026-10-21')
    registry=CODE.parents[1]/'registries/data_sources.json'
    with open('/tmp/openlabs-biomed-source-registry.lock','w') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        old=json.loads(registry.read_text())
        existing=[x for x in old['sources'] if x['source_id']==SOURCE]
        if existing:
            assert existing==[entry]
        else:
            before={x['source_id']:x for x in old['sources']}
            old['sources'].append(entry)
            atomic(registry,old)
            after=json.loads(registry.read_text())
            assert all(next(x for x in after['sources'] if x['source_id']==k)==v for k,v in before.items())
    atomic(PROJECT/'source-entry.json',entry)

def intake(accession, fileid):
    meta=json.loads((ART/f'metadata/{accession}.json').read_text())
    item=next(x for x in meta['files'] if x['accession']==fileid)
    assert item['status']=='released' and not item.get('restricted',False)
    assert item['file_size']<=128*1024**2
    dest=ART/'intakes'/fileid.lower()
    filename='data.bed.gz' if item['href'].endswith('.bed.gz') else 'data.tsv'
    if (dest/'manifest.json').exists(): return dest/filename
    status('data_intake','Cross-cell conservation of signed orientation dependence',
           f'intake.py {accession} {fileid}',[ART/f'metadata/{accession}.json'])
    m=download(source_id=SOURCE,url='https://www.encodeproject.org'+item['href'],
        staging_root=ART/'intakes',dataset_id=fileid.lower(),release_or_accession=accession+':'+fileid+':status=released:created='+item['date_created']+':experiment_release='+str(meta.get('date_released','not_reported')),
        independent_unit='genomic_locus_paired_reporter_orientation',terms_url=TERMS,
        reuse_basis=json.loads((PROJECT/'source-entry.json').read_text())['reuse_basis'],
        citation='Agarwal et al. Nature (2025) DOI10.1038/s41586-024-08430-9; ENCODE Consortium; '+accession+' '+fileid,
        upstream_study_ids=['DOI:10.1038/s41586-024-08430-9',accession],filename=filename,max_bytes=128*1024**2,retries=1)
    assert m['bytes']==item['file_size']
    md5=hashlib.md5((dest/filename).read_bytes()).hexdigest()
    assert md5==item['md5sum']
    atomic(dest/'official-md5-check.json',dict(expected=item['md5sum'],observed=md5,valid=True))
    return dest/filename

if __name__=='__main__':
    register()
    p=intake(*sys.argv[1:3])
    print(p)
    if '--schema' in sys.argv:
        # Explicitly excluded preview rows before any outcome comparison.
        with p.open() as f:
            rows=[next(f) for _ in range(4)]
        (PROJECT/'schema-preview.txt').write_text(''.join(rows))
        print(''.join(rows))
