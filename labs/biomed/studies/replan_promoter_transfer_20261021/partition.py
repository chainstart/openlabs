"""Mechanical ingestion and metadata-only split, no outcome summaries."""
from common import *
import numpy as np
import gzip,csv,collections
from grouping import groups,canonical
guard_check()
assert not (DATA/'freeze.json').exists(),'partitions already frozen'
audit=json.loads((DATA/'count-column-decision.json').read_text())
assert audit['denominator_numeric_column_1based']==4
z=np.load(ART/'derived/tovar-count-audit.npz',allow_pickle=False)
mode=audit['filter']
t=z['filtered'][3] if mode=='barcode_DNA10' else z['total']
b=z['filtered_nbarcode'][3] if mode=='barcode_DNA10' else z['nbarcode']
ok=(b>2).all(axis=1)&(t[:,:,3]>=10).all(axis=1)
tm=json.loads((ART/'derived/tovar-metadata.json').read_text())['records']
assert list(z['ids'])==[r['sample_id'] for r in tm]
tr=[dict(r,dataset='tovar') for r,v in zip(tm,ok) if v]
td=dict(dna=t[ok,:,3],rna=t[ok,:,:3],nbarcode=b[ok],author=z['author'][ok])
km=json.loads((DATA/'klein-metadata.json').read_text())['records']
km=[dict(r,dataset='klein') for r in km if all(r['replicate_availability'][a]==3 for a in ["5'/3' WT","3'/3' WT"])]
ki={r['sample_id']:i for i,r in enumerate(km)}
raw=np.full((len(km),2,3),np.nan);author=np.full((len(km),2),np.nan)
with gzip.open(ART/'payload/GSE142696_9MPRA.ActivityRatios.IndividualReps.tsv.gz','rt') as f:
    for r in csv.DictReader(f,delimiter='\t'):
        if r['name'] not in ki:continue
        i=ki[r['name']]
        for j,a in enumerate(["5'/3' WT","3'/3' WT"]):
            for k in range(3):raw[i,j,k]=float(r[f'{a} replicate {k+1}, log2 RNA/DNA ratio'])
with gzip.open(ART/'payload/GSE142696_9MPRA.ActivityRatios.tsv.gz','rt') as f:
    line=f.readline()
    while not line.startswith('name\t'):
        line=f.readline();assert line
    for r in csv.DictReader(f,fieldnames=line.rstrip('\r\n').split('\t'),delimiter='\t'):
        if r['name'] not in ki:continue
        for j,a in enumerate(["5'/3' WT","3'/3' WT"]):
            v=r[f'{a} mean log2 RNA/DNA ratio']
            author[ki[r['name']],j]=float(v) if v not in ('NA','','NaN') else np.nan
assert np.isfinite(raw).all()
kd=dict(raw=raw,author=author)
records=km+tr
print('building conservative groups',len(records),flush=True)
g=groups(records);out=ART/'analysis_inputs';out.mkdir(exist_ok=True)
summary={};manifest=[]
for dataset,rs,dd,offset in [('klein',km,kd,0),('tovar',tr,td,len(km))]:
    dd.update(ids=np.array([r['sample_id'] for r in rs]),classes=np.array([r['library_class'] for r in rs]),
      gc=np.array([(r['sequence'].count('G')+r['sequence'].count('C'))/len(r['sequence']) for r in rs]),
      cpg=np.array([r['sequence'].count('CG')/(len(r['sequence'])-1) for r in rs]),
      groups=np.array([g[i+offset][0] for i in range(len(rs))]))
    splits=np.array([g[i+offset][1] for i in range(len(rs))]);summary[dataset]={}
    for sp in ['train','validation','test']:
        take=splits==sp;path=out/f'{dataset}_{sp}.npz'
        np.savez_compressed(path,**{k:v[take] for k,v in dd.items()})
        sizes=collections.Counter(dd['groups'][take]);ng=len(sizes)
        summary[dataset][sp]=dict(n_rows=int(take.sum()),groups=ng,largest_group=max(sizes.values()),
          illustrative_standardized_mean_CI_halfwidth=1.96/np.sqrt(ng),
          illustrative_risk50_difference_SE_factor=2.8/np.sqrt(ng/2),path=str(path),sha256=sha(path))
    for i,r in enumerate(rs):manifest.append(dict(dataset=dataset,sample_id=r['sample_id'],group=g[i+offset][0],split=g[i+offset][1]))
write(DATA/'partition-summary.json',dict(time=now(),summary=summary,metadata_only_selection=True,
    precision_note='Reference normal approximation in units of unknown group SD; not claimed 10% power. Risk selection and unequal sizes require final bootstrap.',
    grouping='Connected components: hg19 1Mb blocks, Tovar reported index signal, exact canonical sequence, >=99% full-length same-length sequence identity either orientation, across both studies. Exhaustive block-pigeonhole candidate generation plus Hamming verification.',
    target_exposure='Mechanical parsing/copying only; no numerical target summaries or fitted models.',tovar_qc_excluded=int((~ok).sum())))
write(ART/'derived/partition-membership.json',manifest)
print(json.dumps(summary,indent=2))
