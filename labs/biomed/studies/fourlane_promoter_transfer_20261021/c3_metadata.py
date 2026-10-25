"""C3 metadata-only feasibility; never output or use P_resp magnitudes."""
from common import *
import csv, collections, math

def table(name):
    with (ART/'payload'/name).open() as f:
        return list(csv.DictReader((l for l in f if l.strip() and not l.startswith('#')),delimiter='\t'))

def rc(s): return s.translate(str.maketrans('ACGT','TGCA'))[::-1]
def canonical(s): return min(s,rc(s))

if __name__=='__main__':
    source=table('bergman_MOESM2.txt'); target=table('tan_500P_annotations.txt')
    other=table('tan_78P_annotations.txt'); idx={r['seq'].upper():r for r in source}
    # Outcome magnitudes are not inspected. Missingness and published TSS QC are metadata.
    records=[]; excluded=[]
    for r in target:
        s=r['seq'].upper(); o=idx.get(s)
        reason=[]
        if o is None:reason.append('no_exact_same_orientation_source')
        if o and o['neg_control'].lower() in ('true','1'):reason.append('source_negative_control')
        if r['clean_TSS'].lower() not in ('true','1'):reason.append('author_TSS_QC_fail')
        for c in ('P_resp','P_basal (log2)','fraction_of_reads_in_promoter','n_negctrl_E','n_for_P_resp'):
            try: finite=math.isfinite(float(r[c]))
            except ValueError:finite=False
            if not finite:reason.append('missing_'+c)
        if not reason and (float(r['n_negctrl_E'])<2 or float(r['n_for_P_resp'])<5):reason.append('insufficient_enhancer_controls_or_pairs')
        if reason:excluded.append(dict(sample_id=r['promoter'],reasons=reason));continue
        records.append(dict(sample_id=r['promoter'],source_id=o['fragment'],source_class=o['promoter_exp_class'],gene=r['gene'],chrom=r['chr'],start=int(r['start']),end=int(r['end']),sequence=s,sequence_sha256=hashlib.sha256(s.encode()).hexdigest()))
    # Group overlaps, genes, nearby genomic blocks and substantial shared canonical 21mers.
    parent=list(range(len(records)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):parent[root(a)]=root(b)
    km=[{canonical(r['sequence'][j:j+21]) for j in range(len(r['sequence'])-20)} for r in records]
    for i,a in enumerate(records):
        for j in range(i):
            b=records[j]
            same_gene=a['gene'] not in ('','NA') and a['gene']==b['gene']
            same_block=a['chrom']==b['chrom'] and a['start']//1000000==b['start']//1000000
            overlap=a['chrom']==b['chrom'] and max(a['start'],b['start'])<min(a['end'],b['end'])
            homology=len(km[i]&km[j])>=0.2*min(len(km[i]),len(km[j]))
            if same_gene or same_block or overlap or homology:union(i,j)
    components=collections.defaultdict(list)
    for i,r in enumerate(records):components[root(i)].append(i)
    exposed_sequences={r['seq'].upper() for r in target[:13]}
    exposed_genes={r['gene'] for r in target[:13] if r['gene'] not in ('','NA')}
    # Conservatively reserve any promoter in the smaller Tan panels for development as well.
    earlier_sequences={r['seq'].upper() for r in other+table('tan_26P_annotations.txt')}
    for ids in components.values():
        key='|'.join(sorted(records[i]['sample_id'] for i in ids))
        digest=hashlib.sha256(('C3-20261021|'+key).encode()).hexdigest()
        u=int(digest[:8],16)/2**32
        split='train' if u<0.4 else 'validation' if u<0.6 else 'test'
        if any(records[i]['sequence'] in exposed_sequences|earlier_sequences or records[i]['gene'] in exposed_genes for i in ids):split='train'
        for i in ids:records[i].update(group_id=digest[:16],split=split)
    with (DATA/'c3-samples.csv').open('w') as f:
        fields=[k for k in records[0] if k!='sequence'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r[k] for k in fields} for r in records)
    counts={s:dict(rows=sum(r['split']==s for r in records),groups=len({r['group_id'] for r in records if r['split']==s}),source_classes=dict(collections.Counter(r['source_class'] for r in records if r['split']==s))) for s in ('train','validation','test')}
    out=dict(time=now(),eligible=len(records),counts=counts,excluded=excluded,source_neg_control_values=dict(collections.Counter(r['neg_control'] for r in source)),target_TSS_QC_values=dict(collections.Counter(r['clean_TSS'] for r in target)),exposure_handling='first 13 target rows, their genes/groups and all 78P/26P shared sequences assigned training; no label magnitudes accessed',independence='Distinct GSE184426 and GSE334082 experiments, same K562 and overlapping investigators. One target reporter system, not independent laboratories or a third validation study.',precision={'test_groups':counts['test']['groups'],'approx_80pct_power_standardized_paired_loss_effect':2.8/math.sqrt(counts['test']['groups']),'interpretation':'Normal approximation in SD of group-level paired losses, no outcome-based variance estimate. Cannot promise detection of 5% MSE improvement.'},input_hashes={n:sha(ART/'payload'/n) for n in ('bergman_MOESM2.txt','tan_500P_annotations.txt','tan_78P_annotations.txt','tan_26P_annotations.txt')})
    write(DATA/'c3-metadata-feasibility.json',out);print(json.dumps({k:v for k,v in out.items() if k not in ('excluded','input_hashes')},indent=2))
