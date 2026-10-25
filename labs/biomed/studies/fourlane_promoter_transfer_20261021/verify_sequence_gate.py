from common import *
import csv,zipfile,xml.etree.ElementTree as ET,re,collections,gzip
from xlsx_stream import Workbook
rc=lambda s:s.translate(str.maketrans('ACGT','TGCA'))[::-1]
canon=lambda s:min(s,rc(s))
old=next((ART/'payload').glob('*Table S3*design*.xlsx'))
# Independent reconstruction bypasses the worksheet header/name parser entirely.
all230=set();ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
with zipfile.ZipFile(old) as z,z.open('xl/sharedStrings.xml') as f:
    for _,el in ET.iterparse(f,events=('end',)):
        if el.tag==ns+'si':
            s=''.join(el.itertext()).upper()
            if len(s)==230 and re.fullmatch('[ACGT]+',s):all230.add(s)
            el.clear()
cores={canon(s[15:-15]) for s in all230}
with (ART/'sequences/QUASARR_all.csv').open() as f:
    target=list(csv.DictReader(f))
matches=[r['id'] for r in target if canon(r['sequence']) in cores]
assert not matches
assert rc(rc('ACGTTGCA'))=='ACGTTGCA'
audit=json.loads((DATA/'exact-library-audit.json').read_text())
assert audit['comparisons']['QUASARR_all']['old_core_exact_matches']==len(matches)
# Audit PARM's full synthetic sequence design table, only sequence/library columns.
p=ART/'payload/GSE301246_Synthetic_Promoter_Libraries_Small_and_Large_Data.txt.gz'
counts=collections.Counter();seqs=set();bylib=collections.defaultdict(set);records=0
with gzip.open(p,'rt') as f:
    reader=csv.DictReader(f,delimiter='\t')
    for r in reader:
        s=r['query.seq'].upper();assert re.fullmatch('[ACGT]+',s)
        records+=1;seqs.add(s);bylib[r['library']].add(s)
parmd=dict(barcode_rows=records,unique_query_sequences=len(seqs),lengths=dict(collections.Counter(map(len,seqs))),nonpalindromic_rc_pairs=len({canon(s) for s in seqs if s!=rc(s) and rc(s) in seqs}),old_core_exact_matches=len({canon(s) for s in seqs}&cores),libraries={k:len(v) for k,v in bylib.items()})
write(DATA/'sequence-gate-independent-verification.json',dict(time=now(),method='Direct sharedStrings XML sequence extraction, independent of worksheet row/header logic',old230_unique=len(all230),old200_canonical=len(cores),quasarr_records=len(target),quasarr_200nt=sum(len(r['sequence'])==200 for r in target),exact_match_count=len(matches),matches=matches,passed=True,parm_full_synthetic=parmd,input_hashes={str(old):sha(old),str(p):sha(p)}))
print('Independent sequence audit',len(all230),len(cores),'QUASARR matches',len(matches),'PARM',parmd,flush=True)
# All pairwise sequence-set intersections among new processed libraries.
sets={}
for p in (ART/'sequences').glob('*.csv'):
    if p.name.startswith('Agarwal'):continue
    with p.open() as f:sets[p.stem]={canon(r['sequence']) for r in csv.DictReader(f)}
sets['PARM_full_synthetic']={canon(s) for s in seqs}
cross=[]
for i,(a,sa) in enumerate(sets.items()):
    for b,sb in list(sets.items())[i+1:]:
        if a.startswith('tan_') and b.startswith('tan_'):continue
        cross.append(dict(a=a,b=b,canonical_exact_overlap=len(sa&sb)))
write(DATA/'new-library-cross-intersections.json',cross)
