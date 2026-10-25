from common import *
import csv,gzip,collections,re
guard_check()
path=ART/'payload/GSE279057_kyono_library_annotations.txt.gz'
with gzip.open(path,'rt') as f:raw=list(csv.DictReader(f,delimiter='\t'))
records=[];counts=collections.Counter();bad=[]
for r in raw:
    s=r['fullseq'].upper();la=r['lanch'].upper();ra=r['ranch'].upper()
    assert s.startswith(la) and s.endswith(ra),(r['name'],'adapter inconsistency')
    seq=s[len(la):-len(ra)];ref=r['noflankseq'].upper()
    counts['n_total']+=1;counts['insert_length_'+str(len(seq))]+=1
    counts['reference_field_disagrees_'+r['is_ref_alt']]+=int(seq!=ref)
    if len(seq)!=198 or set(seq)-set('ACGT'):
        bad.append(dict(sample_id=r['name'],reason='not_author_198nt_ACGT_design',length=len(seq)));continue
    records.append(dict(sample_id=r['name'],sequence=seq,chrom=r['chr'],start=int(r['start']),end=int(r['end']),library_class=r['subset'],target_id=r['subset']+':'+r['target_id'],index_signal=r['chr']+':'+r['index_rsid'],proxy_variant=r['proxy_rsid'],allele=r['is_ref_alt'],window=r['snp_location'],trait=r['trait']))
result=dict(time=now(),study='Tovar et al 2026, DOI10.1016/j.xhgg.2026.100606; GSE279057; rat INS-1 832/13',author_paper_sha256=sha(ART/'payload/bose_related_41952336.xml'),annotation_sha256=sha(path),counts=dict(counts),records=records,exclusions=bad,sequence_method='Use fullseq, verify and remove each row explicit lanch/ranch. noflankseq is a reference-sequence field, unchanged between all ref/alt pairs; it is not the alternate insert sequence.',independent_unit='linked genomic signal/locus component; never barcode, allele, fragment offset or clone',conditions=['ins_up','ins_down','scp1_up','scp1_down'],replicate_structure='Three independent electroporations of pooled four-vector library; three RNA columns and a single shared plasmid input DNA column. Shared DNA error is not identifiable from between-RNA-replicate spread.',outcome_magnitudes_accessed=False)
bulk=ART/'derived/tovar-metadata.json';write(bulk,result)
summary={k:v for k,v in result.items() if k!='records'};summary.update(records_path=str(bulk),records_sha256=sha(bulk));write(DATA/'tovar-metadata.json',summary)
print('metadata eligible',len(records),'excluded',len(bad),'audit',dict(counts))
