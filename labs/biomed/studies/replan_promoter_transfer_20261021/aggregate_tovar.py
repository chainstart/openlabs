"""Count-column provenance audit; source estimates only, never target association."""
from common import *
import gzip,csv,collections
import numpy as np
from scipy.stats import spearmanr
from xlsx_stream import Workbook
guard_check()
meta=json.loads((ART/'derived/tovar-metadata.json').read_text())['records']
ids={r['sample_id']:i for i,r in enumerate(meta)}
cfg={'ins_up':0,'ins_dwn':1,'scp_up':2,'scp_dwn':3}
bc={};qc=collections.Counter()
with gzip.open(ART/'payload/GSE279057_kyono_library_barcode_pairing.txt.gz','rt') as f:
    for r in csv.DictReader(f,delimiter='\t'):
        qc['pair_rows']+=1
        if r['refname'] not in ids:continue
        v=ids[r['refname']]*4+cfg[r['config']];b=r['barcode']
        if b in bc and bc[b]!=v:bc[b]=-1;qc['ambiguous_pair_records']+=1
        else:bc[b]=v
print('barcode map complete',len(bc),flush=True)
tot=np.zeros((len(meta),4,4),dtype=np.int64)
nb=np.zeros((len(meta),4),dtype=np.int32)
filtered=np.zeros((4,len(meta),4,4),dtype=np.int64)
fnb=np.zeros((4,len(meta),4),dtype=np.int32)
seen=set()
with gzip.open(ART/'payload/GSE279057_kyono_library_counts.txt.gz','rt') as f:
    for line in f:
        z=[v.strip() for v in line.rstrip('\r\n').split('\t')];assert len(z)==5
        b=z[0];qc['count_rows']+=1
        assert b not in seen,'duplicated count barcode';seen.add(b)
        v=bc.get(b,-1)
        if v<0:qc['unmapped_or_ambiguous_counts']+=1;continue
        x=np.array([int(q) for q in z[1:]],dtype=np.int64);assert (x>=0).all()
        i,c=divmod(v,4);tot[i,c]+=x;nb[i,c]+=1
        for d in range(4):
            if x[d]>=10:filtered[d,i,c]+=x;fnb[d,i,c]+=1
del bc,seen
author=np.full((len(meta),4),np.nan);name_to_ids=collections.defaultdict(list)
with gzip.open(ART/'payload/GSE279057_kyono_library_annotations.txt.gz','rt') as f:
    for r in csv.DictReader(f,delimiter='\t'):
        if r['name'] in ids:
            name='_'.join(r[k] for k in ('proxy_rsid','chr','start','end','proxyref','proxyalt','snp_location','is_ref_alt'))
            name_to_ids[name].append(ids[r['name']])
for fn,sheet,c in [('tovar_mmc5.xlsx','Table_S4',0),('tovar_mmc7.xlsx','Table_S6',2)]:
    w=Workbook(ART/'payload'/fn)
    for j,r in enumerate(w.rows(sheet)):
        if j<2 or not r:continue
        for i in name_to_ids.get(r[0],[]):author[i,c]=float(r[7])
    w.close()
audit=[]
for d in range(4):
    rr=[k for k in range(4) if k!=d]
    for mode in ['total_DNA10','barcode_DNA10']:
        t=tot if mode=='total_DNA10' else filtered[d];n=nb if mode=='total_DNA10' else fnb[d]
        eligible=(n>2).all(axis=1)&(t[:,:,d]>=10).all(axis=1)
        row=dict(denominator_numeric_column_1based=d+1,filter=mode,n_common=int(eligible.sum()),source_checks={})
        for c in [0,2]:
            ok=eligible&np.isfinite(author[:,c]);est=np.log2((t[:,c,rr].sum(axis=1)+.5)/(3*(t[:,c,d]+.5)))
            row['source_checks'][str(c)]=dict(n=int(ok.sum()),spearman=float(spearmanr(est[ok],author[ok,c]).statistic) if ok.sum()>2 else None)
        audit.append(row)
np.savez_compressed(ART/'derived/tovar-count-audit.npz',ids=np.array(list(ids)),total=tot,nbarcode=nb,filtered=filtered,filtered_nbarcode=fnb,author=author)
write(DATA/'count-column-audit.json',dict(time=now(),qc=dict(qc),audit=audit,author_units='Alpha_corrected, log2; source-only official MPRAnalyze tables',target_values_analyzed=False,payload_sha256=sha(ART/'payload/GSE279057_kyono_library_counts.txt.gz')))
print(json.dumps(audit,indent=2),flush=True)
