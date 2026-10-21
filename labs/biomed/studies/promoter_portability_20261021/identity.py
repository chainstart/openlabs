from common import *
from xlsx import sheets
import csv,collections,re
w=sheets(ART/'intakes/quasarr-moesm6/source.xlsx')
def vals(r):return [v for k,v in sorted(r.items(),key=lambda kv:(len(re.sub('[0-9]','',kv[0])),re.sub('[0-9]','',kv[0])))]
seq={};coords={};classes={}
for r in w['Elements_Sequences']:
 v=vals(r)
 if len(v)>=2 and re.fullmatch('[ACGTacgt]+',v[1]) and len(v[1])>50:seq[v[0]]=v[1].upper()
for r in w['Element_Coordinates']:
 v=vals(r)
 if len(v)>=4 and v[1].startswith('chr') and v[2].isdigit():
  coords[v[0]]=(v[1],int(v[2]),int(v[3]))
for k in ['GENCODE_Transcribed','GENCODE_Untranscribed']:
 for r in w[k]:
  v=vals(r)
  if len(v)>=2 and v[1] in ['Proximal','Distal']:classes[v[0]]=dict(proximity=v[1],transcribed=k=='GENCODE_Transcribed')
pairs=json.loads((PROJECT/'paired-identifiers.json').read_text());common=set.intersection(*(set(v) for v in pairs.values()))
print('seq',len(seq),'coords',len(coords),'classes',len(classes),'4contexts',len(common))
print('example genomic',[(x,coords.get(x),len(seq.get(x,'')),classes.get(x)) for x in sorted(common) if x in classes][:5])
old=Path('/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-functional-genomics-20261021/design/ENCFF631LHA.csv')
oldc=[]
for r in csv.DictReader(old.open()):
 if r['name'].startswith('ENSG') and 'Reversed' not in r['name'] and not r['name'].endswith('_R'):oldc.append((r['chrom'],int(r['start']),int(r['end'])))
exact=[x for x,c in coords.items() if c in set(oldc)]
overlap=[x for x,c in coords.items() if any(c[0]==o[0] and max(c[1],o[1])<min(c[2],o[2]) for o in oldc)]
rc=lambda s:s.translate(str.maketrans('ACGT','TGCA'))[::-1]
canonical=collections.defaultdict(list)
for x,s in seq.items():canonical[min(s,rc(s))].append(x)
atomic(PROJECT/'design-metadata.json',dict(sequences=seq,coordinates=coords,classes=classes))
a=dict(time=now(),seq_count=len(seq),coordinate_count=len(coords),class_count=len(classes),four_context_paired=len(common),four_context_proximal=sum(classes.get(x,{}).get('proximity')=='Proximal' for x in common),old_exact_coordinate_count=len(exact),old_exact_coordinate_ids=exact,old_any_overlap_count=len(overlap),old_any_overlap_ids=overlap,canonical_duplicate_groups=[v for v in canonical.values() if len(v)>1],orientation_translation='fwd/rev author construct labels only; genomic reference orientation not yet established',exact_insert_identity='Not inferred from coordinate overlap. No old insert sequence comparison yet.',molecule_compatibility='DNA locus, not small molecule')
atomic(PROJECT/'identity-feasibility.json',a);print(json.dumps({k:v for k,v in a.items() if not isinstance(v,list)},indent=2))
