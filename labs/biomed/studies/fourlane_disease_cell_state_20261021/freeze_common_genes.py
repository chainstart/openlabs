from intake import *
import pandas as pd

def main():
    out=DATA/'common_genes_frozen.json'
    assert not out.exists(),'Refuse overwrite shared-feature freeze'
    paths=[ART/'payload/GSE135893_genes.tsv.gz',ART/'payload/GSE136831_AllCells.GeneIDs.txt.gz',ART/'atlas_genes.csv']
    dev=pd.read_csv(paths[0],sep='\t',header=None)[0].astype(str)
    con=pd.read_csv(paths[1],sep='\t')
    genes=pd.read_csv(paths[2])
    # Development release supplies symbols only. Require exact symbol match and
    # confirmation original Ensembl availability. No expression-based filtering.
    keep=genes.feature_name.isin(set(dev))&genes['_index'].isin(set(con.Ensembl_GeneID))
    common=genes[keep].copy()
    programs=json.loads((DATA/'plan_frozen_v1.json').read_text())['programs']
    coverage={name:{g:int(common.feature_name.eq(g).sum()) for g in values} for name,values in programs.items()}
    assert all(v==1 for p in coverage.values() for v in p.values()),coverage
    common.to_csv(DATA/'common_genes_frozen.csv',index=False)
    record=dict(at=now(),timing='Metadata-only feature availability, before any completed extracted expression/model result',rule='Exact development released gene-symbol match to atlas feature_name and original confirmation Ensembl-ID presence. Conservative exclusion of changed aliases; no confirmation expression used.',atlas_gene_ids=common['_index'].tolist(),original_development_gene_rows=len(dev),original_confirmation_gene_rows=len(con),atlas_gene_rows=len(genes),common_gene_rows=len(common),endpoint_coverage=coverage,source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},normalization='All model and endpoint summaries use the same common feature set; extraction raw-total audit uses original full raw layer before filtering')
    atomic(out,record);print({k:v for k,v in record.items() if k!='atlas_gene_ids'})

if __name__=='__main__':main()
