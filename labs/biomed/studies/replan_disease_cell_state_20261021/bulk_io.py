"""Strict source parsing and frozen programme scoring; no old scripts imported."""
from common import *
import csv,gzip,re
import numpy as np,pandas as pd
from scipy.stats import rankdata
PLAN=json.loads((DATA/'plan_frozen_v1.json').read_text())
assert sha(DATA/'plan_frozen_v1.json')==json.loads((DATA/'plan_frozen_v1.sha256.json').read_text())['sha256']
FILES={'GSE184316':'GSE184316_fHP_Txome_FPKM_RNAseq.csv.gz','GSE199949':'GSE199949_raw.counts.txt.gz','GSE150910':'GSE150910_gene-level_count_file.csv.gz'}
SCORE_NAMES=['abundance_ECM','abundance_alveolar','abundance_balance','singscore_ECM','singscore_alveolar','singscore_bidirectional']

def annotation():
 ref=json.loads((DATA/'annotation_readonly_reference.json').read_text());assert sha(ref['path'])==ref['sha256']
 a=pd.read_csv(ref['path'],sep='\t',dtype={'ensembl':str,'GeneName':str})
 a=a[a.ensembl.notna()&a.GeneName.notna()&a.ExonLength.gt(0)].copy()
 assert a.ensembl.is_unique
 # A duplicate symbol is not treated as an exact one-to-one identifier.
 a=a[~a.GeneName.duplicated(keep=False)]
 return a.set_index('ensembl')

def resolve_id(x,a):
 x=str(x).strip();key=re.sub(r'\.\d+$','',x) if x.startswith('ENSG') else x
 if key in a.index:return key
 bysymbol=dict(zip(a.GeneName,a.index))
 return bysymbol.get(key)

def verify_payload(acc):
 p=ART/'payload'/FILES[acc];assert p.exists(),str(p)
 records=[json.loads(x) for x in (ART/'manifest.jsonl').read_text().splitlines()]
 r=[x for x in records if x.get('name')==FILES[acc] and x.get('status')=='complete']
 assert len(r)==1 and sha(p)==r[0]['sha256'] and p.stat().st_size==r[0]['bytes']
 return p,r[0]

def inspect_identifiers(acc):
 """Only labels and shape are extracted; numeric cells not interpreted/output."""
 p,rec=verify_payload(acc);a=annotation();bysymbol=dict(zip(a.GeneName,a.index));ids=[];widths=set()
 with gzip.open(p,'rt') as f:
  first=f.readline();sep='\t' if first.count('\t')>first.count(',') else ','
  header=next(csv.reader([first],delimiter=sep))
  for row in csv.reader(f,delimiter=sep):
   if not row:continue
   widths.add(len(row));ids.append(row[0])
 mapped=[]
 for x in ids:
  key=re.sub(r'\.\d+$','',x) if x.startswith('ENSG') else x
  mapped.append(key if key in a.index else bysymbol.get(key))
 meta=pd.read_csv(DATA/f'{acc}_samples_frozen.csv',dtype={'subject':str})
 labels=header[1:];sample_map={}
 for _,r in meta.iterrows():
  matches=[x for x in labels if x in [r['title'],r['sample_id']]]
  if len(matches)==1:sample_map[r['sample_id']]=matches[0]
  else:sample_map[r['sample_id']]=None
 record=dict(at=now(),accession=acc,payload_sha256=rec['sha256'],delimiter=sep,header=header,rows=len(ids),widths=sorted(widths),mapped_rows=sum(x is not None for x in mapped),mapped_genes=len(set(x for x in mapped if x)),unmapped_examples=[x for x,y in zip(ids,mapped) if y is None][:20],sample_map=sample_map,matched_samples=sum(x is not None for x in sample_map.values()),samples=len(meta),duplicate_source_ids=pd.Series(ids).duplicated().sum().item(),target_mapping={g:a[a.GeneName.eq(g)].index.tolist() for gs in PLAN['programs'].values() for g in gs},expression_values_inspected=False)
 atomic(DATA/f'{acc}_format_audit.json',record)
 pd.DataFrame({'source_id':ids,'ensembl':mapped}).to_csv(DATA/f'{acc}_gene_mapping.csv',index=False)
 print(acc,'rows',len(ids),'mapped',record['mapped_genes'],'samples',record['matched_samples'],'/',len(meta),'header',header[:5], 'unmapped',record['unmapped_examples'][:5])
 return record

def freeze_universe():
 assert not (DATA/'gene_universe_frozen.json').exists()
 a=annotation();sets=[]
 for acc in FILES:
  r=json.loads((DATA/f'{acc}_format_audit.json').read_text());assert r['matched_samples']==r['samples'],acc
  assert r['widths']==[len(r['header'])],(acc,r['widths'],len(r['header']))
  m=pd.read_csv(DATA/f'{acc}_gene_mapping.csv');sets.append(set(m.ensembl.dropna()))
 shared=sorted(set.intersection(*sets));symbols=a.GeneName.reindex(shared).tolist()
 for gs in PLAN['programs'].values():assert set(gs)<=set(symbols),set(gs)-set(symbols)
 pd.DataFrame({'ensembl':shared,'symbol':symbols,'ExonLength':a.ExonLength.reindex(shared).values}).to_csv(DATA/'gene_universe_frozen.csv',index=False)
 atomic(DATA/'gene_universe_frozen.json',dict(at=now(),n=len(shared),sha256=sha(DATA/'gene_universe_frozen.csv'),derived_from='Identifier intersection only; no expression-based selection',expression_values_inspected=False,programs=PLAN['programs']))

def load_abundance(acc):
 assert sha(DATA/f'{acc}_samples_frozen.csv')==PLAN['sample_tables'][acc]['sha256']
 p,_=verify_payload(acc);r=json.loads((DATA/f'{acc}_format_audit.json').read_text());a=annotation()
 m=pd.read_csv(DATA/f'{acc}_gene_mapping.csv',dtype=str)
 # Integer usecols handles author CSVs with an unnamed first gene column.
 selected=[0]+[r['header'].index(label) for label in r['sample_map'].values()]
 assert len(selected)==len(set(selected))
 x=pd.read_csv(p,sep=r['delimiter'],index_col=0,usecols=selected).astype(float)
 assert list(x.index.astype(str))==m.source_id.tolist()
 assert np.isfinite(x.to_numpy(float)).all() and (x.to_numpy(float)>=0).all()
 if acc=='GSE199949':assert np.allclose(x.to_numpy(float),np.rint(x.to_numpy(float)),atol=1e-8,rtol=0),'STAR raw count file unexpectedly fractional'
 x.index=m.ensembl.values;x=x[x.index.notna()].groupby(level=0,sort=True).sum()
 if acc!='GSE184316':x=x.div(a.ExonLength.reindex(x.index),axis=0)
 assert (x.sum(axis=0)>0).all()
 abundance=x.div(x.sum(axis=0),axis=1)*1e6
 # Convert matrix columns to GEO sample IDs using audited one-to-one map.
 mapping={v:k for k,v in r['sample_map'].items()};assert len(mapping)==len(r['sample_map'])
 abundance=abundance.rename(columns=mapping)
 return abundance,a

def singscore(v,indices):
 """Published directed formula; ranks precomputed for common universe."""
 n=v.shape[0];k=len(indices)
 return (v[indices].mean(axis=0)-(k+1)/2)/(n-k)-.5

def score(acc):
 assert (DATA/'gene_universe_frozen.json').exists()
 assert not (ART/f'{acc}_scores.csv').exists(),'Scores cannot be overwritten'
 if acc=='GSE199949':
  assert (DATA/'confirmation_open.json').exists(),'Must explicitly audit and open confirmation once'
 abundance,a=load_abundance(acc)
 common=pd.read_csv(DATA/'gene_universe_frozen.csv');assert sha(DATA/'gene_universe_frozen.csv')==json.loads((DATA/'gene_universe_frozen.json').read_text())['sha256']
 vals=abundance.reindex(common.ensembl).to_numpy(float);assert np.isfinite(vals).all()
 ranks=rankdata(vals,axis=0,method='min');labels=common.symbol.to_numpy()
 meta=pd.read_csv(DATA/f'{acc}_samples_frozen.csv');meta=meta.set_index('sample_id').loc[abundance.columns].rename_axis('sample_id').reset_index()
 scores={};floors={};targets={}
 for key,genes in PLAN['programs'].items():
  ens=a.index[a.GeneName.isin(genes)];assert len(ens)==len(genes)
  z=abundance.loc[ens].to_numpy(float)
  scores['abundance_'+key]=np.log2(z+1).mean(axis=0)
  inds=np.where(np.isin(labels,genes))[0];assert len(inds)==len(genes)
  scores['singscore_'+key]=singscore(ranks,inds)
  floors[key]=(z<1).mean(axis=0)
  for en in ens:targets[a.loc[en,'GeneName']]=abundance.loc[en].values
 scores['abundance_balance']=scores['abundance_ECM']-scores['abundance_alveolar']
 scores['singscore_bidirectional']=scores['singscore_ECM']-scores['singscore_alveolar']
 for key,v in scores.items():meta[key]=v
 for key,v in floors.items():meta['floor_fraction_'+key]=v
 meta.to_csv(ART/f'{acc}_scores.csv',index=False)
 pd.DataFrame(targets,index=abundance.columns).rename_axis('sample_id').to_csv(ART/f'{acc}_programme_abundance.csv')
 atomic(ART/f'{acc}_score_record.json',dict(at=now(),accession=acc,plan_sha256=sha(DATA/'plan_frozen_v1.json'),code_sha256=sha(Path(__file__)),payload_sha256=sha(ART/'payload'/FILES[acc]),score_sha256=sha(ART/f'{acc}_scores.csv'),abundance_genes=len(abundance),rank_genes=len(common),score_definitions=PLAN['preprocessing'],maximum_memory_design_mib=450,paper_candidate=False))
 return meta

if __name__=='__main__':
 mode=sys.argv[1]
 if mode=='inspect':
  for acc in sys.argv[2:]:inspect_identifiers(acc)
 elif mode=='freeze':freeze_universe()
 elif mode=='score':
  for acc in sys.argv[2:]:score(acc)
 else:raise ValueError(mode)
