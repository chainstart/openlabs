from common import *
import csv,collections,re,xml.etree.ElementTree as ET
rc=lambda s:s.translate(str.maketrans('ACGT','TGCA'))[::-1]
out={}
for p in sorted((ART/'payload').glob('tan_*.fasta')):
    seqs={};name=None
    for line in p.read_text().splitlines():
        if line.startswith('>'):name=line[1:];seqs[name]=''
        elif name:seqs[name]+=line.strip().upper()
    idx=collections.defaultdict(list)
    for n,s in seqs.items():idx[s].append(n)
    pairs=sorted(set(tuple(sorted((a,b))) for a,s in seqs.items() for b in idx.get(rc(s),[]) if a!=b and s!=rc(s)))
    out[p.name]=dict(records=len(seqs),unique_sequences=len(idx),lengths=dict(collections.Counter(map(len,seqs.values()))),nonpalindromic_rc_pairs=pairs,exact_duplicate_groups=[v for v in idx.values() if len(v)>1],sha256=sha(p))
write(DATA/'tan-exact-orientation-audit.json',out)
print(json.dumps(out,indent=2))
for name in ('agarwal','parm','quasarr','tan','zhang','klein'):
    p=ART/'payload'/f'{name}.xml'
    if not p.exists():continue
    root=ET.parse(p).getroot()
    links=[]
    for el in root.iter():
        if el.tag in ('supplementary-material','ext-link','media'):
            href=el.attrib.get('{http://www.w3.org/1999/xlink}href','')
            if href:links.append(dict(href=href,text=' '.join(el.itertext())[:120]))
    write(DATA/f'{name}-all-links.json',links)
    print(name,links[:20])
write(DATA/'exposure-log.json',dict(time=now(),events=[{'file':'tan_500P_annotations.txt','exposed':'First 13 data rows and associated published P_resp/P_basal visible during metadata header inspection; sorted high P_resp. No model fit. Must not be called unseen confirmation.','handling':'If using this panel, record development exposure and exclude exposed loci/linked groups from any prospectively held-out evaluation; do not infer untouched full panel.'},{'file':'PARM v1 raw partial','exposed':'Header and first row first 7 fields, including one HAP1 count; no confirmation boundary exists yet.'}],old_confirmations='All old Agarwal and QUASARR outcomes considered exposed; no old experiments rerun.'))
