from common import *
from xlsx_stream import Workbook
import itertools,gzip
for p in sorted((ART/'payload').glob('*lib design*.xlsx')):
    w=Workbook(p);print(p.name,list(w.sheets),flush=True)
    for s in w.sheets:print(s,list(itertools.islice(w.rows(s),1)),flush=True)
    w.close()
w=Workbook(ART/'payload/tan-supplement-tables.xlsx')
for s in ['Table S6','Table S7']:
    print(s,list(itertools.islice(w.rows(s),11)),flush=True)
w.close()
p=ART/'payload/GSE142696_ForwardReverse_sequences_coordinates.tsv.gz'
with gzip.open(p,'rt') as f:print('Klein',f.readline(),f.readline()[:500])
