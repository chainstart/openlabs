from intake import *
import pandas as pd,numpy as np,re
def devkey(s,keys):
    s=str(s).removesuffix('_haberman')
    if s in keys:return s
    a=s.rsplit('_',1)
    return a[1]+'_'+a[0] if len(a)==2 else s
def compartment_dev(t,p):
    if t=='AT1':return 'AT1'
    if t in ['AT2','Transitional AT2']:return 'AT2'
    if t=='KRT5-/KRT17+':return 'disease_epithelial'
    if p=='Epithelial':return 'other_epithelial'
    if 'Fibroblast' in t or t=='Myofibroblasts':return 'fibroblast'
    if t in ['Smooth Muscle Cells','Mesothelial Cells']:return 'other_mesenchymal'
    if 'Endothelial' in t:return 'endothelial'
    return 'immune'
def compartment_con(t,cat):
    if t.startswith('Multiplet') or t.startswith('Assorted_'):return 'exclude'
    if t=='ATI':return 'AT1'
    if t.startswith('ATII'):return 'AT2'
    if t=='Mystery_Disease_Epithelial':return 'disease_epithelial'
    if cat=='Epithelial':return 'other_epithelial'
    if t in ['Fibroblast','Myofibroblast']:return 'fibroblast'
    if t in ['Mesothelial','Pericyte'] or t.startswith('Smooth-Muscle'):return 'other_mesenchymal'
    if 'Endothelial' in t:return 'endothelial'
    if cat in ['Immune','Myeloid','Lymphoid']:return 'immune'
    return 'exclude'
if __name__=='__main__':
    report={}
    for tag,study in [('development','Banovich_Kropski_2020'),('confirmation','Kaminski_2020')]:
        a=pd.read_csv(ART/f'{study}_metadata.csv.gz')
        if tag=='development':
            b=pd.read_csv(ART/'payload/GSE135893_IPF_metadata.csv.gz').rename(columns={'Unnamed: 0':'cell_id','Sample_Name':'donor_id','Diagnosis':'disease'})
            keys=set(b.cell_id);a['cell_id']=a._index.map(lambda s:devkey(s,keys))
            b['compartment']=[compartment_dev(t,p) for t,p in zip(b.celltype,b.population)]
            ages=pd.read_csv(DATA/'development_donor_metadata.csv').rename(columns={'Sample_Name':'donor_id','Age':'age'})[['donor_id','age']]
        else:
            b=pd.read_csv(ART/'payload/GSE136831_AllCells.Samples.CellType.MetadataTable.txt.gz',sep='\t').rename(columns={'CellBarcode_Identity':'cell_id','Subject_Identity':'donor_id','Disease_Identity':'disease'})
            a['cell_id']=a._index.str.removesuffix('_adams')
            b['compartment']=[compartment_con(t,p) for t,p in zip(b.Subclass_Cell_Identity,b.CellType_Category)]
            ages=pd.read_csv(DATA/'confirmation_donor_demographics.csv')[['donor_id','age']]
        b=b.merge(ages,on='donor_id',how='left',validate='many_to_one');b.age=pd.to_numeric(b.age,errors='coerce')
        eligible=b[(b.age>=18)&b.disease.isin(['IPF','Control'])&(b.compartment!='exclude')]
        assert a.cell_id.is_unique and b.cell_id.is_unique
        merged=eligible.merge(a[['row','cell_id']],on='cell_id',how='inner',validate='one_to_one')
        merged['study_id']='GSE135893' if tag=='development' else 'GSE136831'
        merged['split']='train' if tag=='development' else 'test'
        merged.to_csv(ART/f'{tag}_eligible_cells.csv.gz',index=False)
        report[tag]=dict(original_cells=len(b),original_eligible=len(eligible),transport_intersection=len(merged),eligible_donors=eligible.donor_id.nunique(),transport_donors=merged.donor_id.nunique(),missing_donors=sorted(set(eligible.donor_id)-set(merged.donor_id)),original_per_donor=eligible.groupby('donor_id').size().to_dict(),intersection_per_donor=merged.groupby('donor_id').size().to_dict())
        selected=[]
        for (donor,comp),group in merged.groupby(['donor_id','compartment']):
            group=group.copy();group['selection_hash']=group.cell_id.map(lambda c:hashlib.sha256(('20261021'+c).encode()).hexdigest())
            sample=group.sort_values('selection_hash').head(32).copy();sample['population_cells']=len(group);sample['sampled_cells']=len(sample);sample['weight']=len(group)/len(sample);selected.append(sample)
        selected=pd.concat(selected).sort_values('row');selected.to_csv(DATA/f'{tag}_sample_frozen.csv',index=False)
        print(tag,'sampled',len(selected),'donors',selected.donor_id.nunique(),'match',len(merged),'/',len(eligible),'missing',report[tag]['missing_donors'])
    atomic(DATA/'barcode_reconciliation.json',report)
    atomic(DATA/'sample_freeze_hashes.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.glob('*sample_frozen.csv')})
