from common import *
from xlsx_stream import Workbook
import re,csv,gzip,collections
rc=lambda s:s.translate(str.maketrans('ACGT','TGCA'))[::-1]
canonical=lambda s:min(s,rc(s))
def fasta(p):
    out={};n=None
    for line in p.read_text().splitlines():
        if line.startswith('>'):n=line[1:];out[n]=''
        elif n:out[n]+=line.strip().upper()
    return out
def dna(s):return isinstance(s,str) and len(s)>=50 and re.fullmatch('[ACGTacgt]+',s)
libs={};metadata={}
for p in sorted((ART/'payload').glob('*lib design*.xlsx')):
    w=Workbook(p)
    for sheet in w.sheets:
        seqs={};cats={};header=None
        for r in w.rows(sheet):
            if any('230nt sequence' in str(x) for x in r):header=r;continue
            if header is None:continue
            seqcol=next((i for i,x in enumerate(header) if '230nt sequence' in str(x)),None)
            if seqcol is None or len(r)<=seqcol or not dna(r[seqcol]):continue
            s=r[seqcol].upper();assert len(s)==230
            n=r[0];seqs[n]=s[15:-15]
            cats[n]=r[1] if len(r)>1 else ''
        key='Agarwal_'+sheet;libs[key]=seqs
        metadata[key]=dict(source_file=p.name,genome_note='hg19 for HepG2 design with hg38 perfect maps; hg38 for K562/WTC11',sequence_derivation='Header explicitly 15nt adaptor + 200nt element + 15nt adaptor; strip exactly 15 each end',categories=dict(collections.Counter(cats.values())),header=header)
        print(key,len(seqs),metadata[key]['categories'],flush=True)
        # Only explicitly annotated promoter entries, not all regulatory fragments.
        promoter={n:s for n,s in seqs.items() if 'promoter' in cats.get(n,'').lower()}
        libs[key+'_promoter']=promoter
    w.close()
w=Workbook(ART/'payload/quasarr-source.xlsx')
libs['QUASARR_all']={r[0]:r[1].upper() for r in w.rows('Elements_Sequences') if len(r)>1 and dna(r[1])};w.close()
w=Workbook(ART/'payload/parm-synthetic.xlsx')
rows=w.rows('NK20240522_Count_table_super_pr');header=next(rows);idx=header.index('gdna')
libs['PARM_synthetic']={r[0]:r[idx].upper() for r in rows if len(r)>idx and dna(r[idx])};w.close()
for p in (ART/'payload').glob('tan_*.fasta'):libs[p.stem]=fasta(p)
p=ART/'payload/GSE142696_ForwardReverse_sequences_coordinates.tsv.gz'
seqs={}
with gzip.open(p,'rt') as f:
    for r in csv.reader(f,delimiter='\t'):
        ds=[s.upper() for s in r if dna(s)]
        if ds:seqs[r[0]]=ds[0]
libs['Klein_192']=seqs
summary={}
for name,d in libs.items():
    byseq=collections.defaultdict(list)
    for n,s in d.items():byseq[s].append(n)
    pairs=set(canonical(s) for s in byseq if s!=rc(s) and rc(s) in byseq)
    summary[name]=dict(rows=len(d),unique_sequences=len(byseq),canonical_sequences=len({canonical(s) for s in byseq}),nonpalindromic_rc_pairs=len(pairs),lengths=dict(collections.Counter(map(len,d.values()))))
    p=ART/'sequences'/f'{name.replace(" ","_")}.csv';p.parent.mkdir(exist_ok=True)
    with p.open('w') as f:
        wr=csv.writer(f);wr.writerow(['id','sequence','canonical_sha256'])
        for n,s in d.items():wr.writerow([n,s,hashlib.sha256(canonical(s).encode()).hexdigest()])
    summary[name]['sequence_table_sha256']=sha(p)
oldkeys=[n for n in libs if n.startswith('Agarwal') and 'large-scale' in n and not n.endswith('_promoter')]
old={canonical(s) for n in oldkeys for s in libs[n].values()}
oldprom={canonical(s) for n in oldkeys for s in libs.get(n+'_promoter',{}).values()}
comparisons={}
for n,d in libs.items():
    if n.startswith('Agarwal'):continue
    exact=[dict(id=i,length=len(s),matches_old_promoter=canonical(s) in oldprom) for i,s in d.items() if canonical(s) in old]
    comparisons[n]=dict(old_core_exact_matches=len(exact),old_promoter_core_exact_matches=sum(x['matches_old_promoter'] for x in exact),matches=exact)
    print(n,summary[n],comparisons[n],flush=True)
write(DATA/'exact-library-audit.json',dict(time=now(),method='Literal DNA or full reverse-complement equality only; no coordinate-overlap substitution; no trimming of target sequences',metadata=metadata,libraries=summary,comparisons=comparisons,limitations=['Design sequence equality is not physical clone resequencing','Old assays remain exposed; exact identity does not create new confirmation','Klein forward/reverse entries represented by single design sequence; assay pairing must use original orientation data','PARM synthetic table is one validation subset, not full fragmented libraries','No claims about unaudited files']))
status('exact_sequence_gate',['full original Agarwal design extracted via verified Range ZIP; no outcome table fetched','exact sequence intersection and reverse-complement counts completed'],['review genuine matched records','evaluate alternative designs and precision'],evidence_paths=[str(DATA/'exact-library-audit.json')])
