from common import *
import zipfile,itertools
from xlsx_stream import Workbook
for name in ['quasarr-source.xlsx','parm-synthetic.xlsx']:
    p=ART/'payload'/name
    w=Workbook(p)
    print(name,list(w.sheets))
    for s in w.sheets:
        # Header only: source workbook may embed phenotype columns.
        print(s,list(itertools.islice(w.rows(s),1)))
    w.close()
with zipfile.ZipFile(ART/'payload/tan-supplements.zip') as z:
    p=ART/'payload/tan-supplement-tables.xlsx';p.write_bytes(z.read('media-1.xlsx'))
    w=Workbook(p)
    print('Tan sheet inventory only',list(w.sheets));w.close()
fetch('GSE142696_ForwardReverse_sequences_coordinates.tsv.gz','https://ftp.ncbi.nlm.nih.gov/geo/series/GSE142nnn/GSE142696/suppl/GSE142696_ForwardReverse_sequences_coordinates.tsv.gz',terms={'terms_url':'https://www.ncbi.nlm.nih.gov/geo/info/disclaimer.html','reuse_basis':'Official author processed sequence annotations, internal analysis'},study='10.1038/s41592-020-0965-y',accession='GSE142696')
