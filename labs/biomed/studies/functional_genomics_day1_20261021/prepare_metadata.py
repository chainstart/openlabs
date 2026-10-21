import json,gzip,csv,collections
from common import *
from intake import intake,register
register()
for a,f in [('ENCSR382BVV','ENCFF631LHA'),('ENCSR244FWB','ENCFF971UBA')]:
    p=intake(a,f)
    print('download complete',f,flush=True)
for f in ['ENCFF774DYO','ENCFF631LHA','ENCFF971UBA']:
    p=ART/'intakes'/f.lower()/'data.bed.gz'
    if not p.exists(): continue
    with gzip.open(p,'rt') as h:
        rows=[next(h) for _ in range(2)]
    # Design fields only, even though BED embeds outcomes; no score fields inspected.
    print(f,'design preview',[x.split('\t')[:4]+[x.split('\t')[5]] for x in rows],flush=True)
    out=ART/'design'/f'{f}.csv'
    out.parent.mkdir(exist_ok=True)
    names=[]
    with gzip.open(p,'rt') as h,out.open('w') as w:
        wr=csv.writer(w);wr.writerow(['chrom','start','end','name','strand'])
        for row in csv.reader(h,delimiter='\t'):
            if row[0].startswith('#'):continue
            wr.writerow(row[:4]+[row[5]])
            names.append(row[3])
    print(f,'n',len(names),'names',names[:8],flush=True)
status('design_metadata_ready','Assess paired-orientation independent loci before freezing outcomes',
       'prepare_metadata.py completed',list((ART/'design').glob('*.csv')))
