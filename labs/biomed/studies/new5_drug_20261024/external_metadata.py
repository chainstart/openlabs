from pathlib import Path
import json,zipfile,hashlib,re,sys,pandas as pd
from read_tables import xlsx_rows
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-drug-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-drug-20261024')
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
source_map={'Venetoclax':'BCL2','Capivasertib':'AKT','MK-2206':'AKT','Selumetinib':'MEK','Trametinib':'MEK','Lapatinib':'ERBB','Gefitinib':'ERBB','Olaparib':'PARP','Palbociclib':'CDK46','SRA737':'CHK1','Prexasertib':'CHK1'}
target_map={'Venetoclax':'BCL2','MK-2206':'AKT','Olaparib (AZD2281)':'PARP','Trametinib/Mekinist':'MEK','Lapatinib':'ERBB','Abemaciclib mesylate (LY2835219)':'CDK46','LY2603618':'CHK1'}
source=pd.read_csv(A/'metadata-only.csv');source['t1']=source.lib1_name.map(source_map);source['t2']=source.lib2_name.map(source_map);source=source.dropna(subset=['t1','t2']);source=source[source.t1!=source.t2];source['family_pair']=source.apply(lambda x:'|'.join(sorted([x.t1,x.t2])),axis=1);sourcepairs=sorted(source.family_pair.unique())
z=zipfile.ZipFile(next((A/'melanoma2026-media-supp15').glob('*.zip')));parts=[]
for d in pd.read_csv(z.open('data.csv'),usecols=['Sample','Destination Plate Barcode','Combination ID','Drug','Drug Concentration','Unit','Destination Well'],chunksize=100000):parts.append(d)
d=pd.concat(parts,ignore_index=True);cols=['Sample','Destination Plate Barcode','Destination Well','Combination ID'];d['Drug']=d.Drug.astype(str).str.strip();d['candidate_family']=d.Drug.map(target_map)
counts=d.groupby(cols,dropna=False).size().rename('n_treatments');total=counts.value_counts().to_dict()
selected=d[d.candidate_family.notna()].copy();selected=selected.merge(counts,on=cols,how='left');selcount=selected.groupby(cols,dropna=False).size().rename('n_selected');selected=selected.merge(selcount,on=cols,how='left');sel=selected[(selected.n_selected==selected.n_treatments)&selected.n_treatments.isin([1,2])].copy();sel.to_csv(A/'external-selected-treatment-metadata.csv',index=False)
pairrecords=[]
for keys,g in sel[sel.n_treatments==2].groupby(cols,dropna=False,sort=False):
 family='|'.join(sorted(g.candidate_family));
 if family not in sourcepairs:continue
 gs=g.sort_values('candidate_family');rows=gs.to_dict('records');pairrecords.append({'Sample':keys[0],'plate':keys[1],'well':keys[2],'combination_id':keys[3],'family_pair':family,'drug1':rows[0]['Drug'],'drug2':rows[1]['Drug'],'conc1':rows[0]['Drug Concentration'],'conc2':rows[1]['Drug Concentration'],'unit1':rows[0]['Unit'],'unit2':rows[1]['Unit']})
pd.DataFrame(pairrecords).to_csv(A/'external-frozen-points-metadata.csv',index=False)
def norm(s):return re.sub('[^A-Z0-9]','',str(s).upper())
source_all=pd.read_csv(A/'metadata-only.csv',usecols=['CELL_LINE_NAME','SIDM']);source_names={norm(n) for n in source_all.CELL_LINE_NAME}
meta=list(xlsx_rows(next((A/'melanoma2026-media-supp4').glob('*.xlsx'))));mcols=meta[0];cells=[]
for row in meta[1:]:
 if len(row)<3 or not row[2].strip():continue
 name=row[2].strip().strip('*');aliases=[name]+row[3].split(';');overlap=any(norm(n) in source_names for n in aliases)
 if norm(name) in ['WM115','WM239A','WM2664']:donor='WM115_WM239_WM2664_same_source_individual'
 elif norm(name) in ['FEMX1','FEMXV']:donor='FEMX_same_source_individual'
 else:donor=row[1] or norm(name)
 rawaliases={'WM239A':'WM239','WM1341B':'WM1341','Hermes 3C':'Hermes 3','Hermes 4C':'Hermes 4'};rawname=rawaliases.get(name,name)
 cells.append({'source_name':row[2],'raw_name':rawname,'cellosaurus_id':row[1],'donor_id':donor,'disease':row[4],'is_melanoma':row[4].strip()!='Healthy skin','source_name_or_alias_overlap':overlap,'aliases':aliases})
pd.DataFrame(cells).drop(columns=['aliases']).to_csv(P/'external-cell-identities-frozen.csv',index=False)
out={'no_target_response_columns_read':True,'source_family_mapping':source_map,'target_family_mapping':target_map,'source_family_pairs':sourcepairs,'same_family_does_not_establish_identical_target_profiles':True,'raw_long_rows':len(d),'raw_samples':sorted(d.Sample.unique()),'treatment_count_per_well_distribution':{str(k):int(v) for k,v in total.items()},'selected_candidate_wells':len(pairrecords),'selected_candidate_family_pairs':len(set(r['family_pair'] for r in pairrecords)),'selected_candidate_samples':len(set(r['Sample'] for r in pairrecords)),'selected_units':sorted(set(d.Unit.dropna().astype(str))),'cell_identities':cells,'points_metadata_sha256':hashlib.sha256((A/'external-frozen-points-metadata.csv').read_bytes()).hexdigest()}
(P/'EXTERNAL_METADATA_QUALIFICATION.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='cell_identities'},indent=2))
