from common import *
import csv,gzip,re,collections,math
guard_check()
with gzip.open(OLD/'payload/GSE142696_ForwardReverse_sequences_coordinates.tsv.gz','rt') as f:
    while True:
        line=f.readline()
        if line.startswith('name\t'):break
        assert line
    seqrows=list(csv.DictReader(f,fieldnames=line.rstrip('\r\n').split('\t'),delimiter='\t'))
intervals=collections.defaultdict(list)
for r in seqrows:
    if r['type']=='test':intervals[r['chr']].append((int(r['start']),int(r['stop']),r['sequence (192nt)']))
rows=[]; excluded=[]
with gzip.open(ART/'payload/GSE142696_9MPRA.ActivityRatios.IndividualReps.tsv.gz','rt') as f:
    rd=csv.DictReader(f,delimiter='\t');header=rd.fieldnames
    for r in rd:
        name=r['name'];m=re.search(r'\[(chr[^:]+):(\d+)-(\d+)\]',name or '')
        if not m:excluded.append(dict(sample_id=name,reason='non_genomic_control_or_blank'));continue
        c,s,e=m[1],int(m[2]),int(m[3]);hits=[]
        for a,b,seq in intervals[c]:
            if a<=s and b>=e and len(seq)==b-a: hits.append(seq[s-a:e-a])
        if len(set(hits))!=1:excluded.append(dict(sample_id=name,reason='no_unique_reference_interval_sequence',n_hits=len(hits)));continue
        # Access only identifier and missingness, not numerical response magnitudes.
        valid={}
        for assay in ["5'/3' WT","3'/3' WT","5'/3' MT","3'/3' MT",'pGL4','ORI']:
            valid[assay]=sum(r.get(f'{assay} replicate {i}, log2 RNA/DNA ratio','') not in ('','NA','NaN','nan') for i in [1,2,3])
        rows.append(dict(sample_id=name,chrom=c,start=s,end=e,sequence=hits[0],library_class=name.split('_')[0],replicate_availability=valid))
write(DATA/'klein-metadata.json',dict(time=now(),n_rows=len(rows),exclusions=excluded,records=rows,sequence_method='Genomic-coordinate containment in author-supplied hg19 192nt reference design. Slice at declared 171nt interval; not inferred equality to 192nt constructs, not physical clone resequencing. Nine designs use same 171nt subcloned library per original Methods.',source_sequence_sha256=sha(OLD/'payload/GSE142696_ForwardReverse_sequences_coordinates.tsv.gz'),activity_file_sha256=sha(ART/'payload/GSE142696_9MPRA.ActivityRatios.IndividualReps.tsv.gz'),outcome_magnitudes_accessed=False,header=header))
print('Klein metadata eligible',len(rows),'excluded',len(excluded),'availability',collections.Counter(tuple(r['replicate_availability'].values()) for r in rows))
