from common import *
import csv,collections,re
rc=lambda s:s.translate(str.maketrans('ACGT','TGCA'))[::-1]
def read(p):
    with p.open() as f:return list(csv.DictReader((l for l in f if l.strip() and not l.startswith('#')),delimiter='\t'))
source=read(ART/'payload/bergman_MOESM2.txt')
target=read(ART/'payload/tan_500P_annotations.txt')
idx=collections.defaultdict(list)
for r in source:idx[r['seq'].upper()].append(r)
matches=[]
for r in target:
    s=r['seq'].upper()
    for o in idx.get(s,[]):
        matches.append(dict(target_id=r['promoter'],source_id=o['fragment'],gene=r['gene'],chrom=r['chr'],start=r['start'],end=r['end'],source_class=o['promoter_exp_class'],same_orientation=True))
    for o in idx.get(rc(s),[]):
        matches.append(dict(target_id=r['promoter'],source_id=o['fragment'],gene=r['gene'],chrom=r['chr'],start=r['start'],end=r['end'],source_class=o['promoter_exp_class'],same_orientation=False))
write(DATA/'response-metadata.json',dict(time=now(),source_records=len(source),source_classes=dict(collections.Counter(r['promoter_exp_class'] for r in source)),target_records=len(target),exact_matches=len(matches),forward_exact=sum(r['same_orientation'] for r in matches),matches=matches,preexposed_target_ids=[r['promoter'] for r in target[:13]],note='Only sequence/identity/class fields used; no target outcomes read for feasibility. Source promoter_exp_class semantics require author definition.'))
print('source',len(source),collections.Counter(r['promoter_exp_class'] for r in source),'target',len(target),'exact',len(matches),'forward',sum(r['same_orientation'] for r in matches))
