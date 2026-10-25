from intake import *
import pandas as pd,re,zipfile
from xlsx_read import rows
def norm(t):
    m=re.fullmatch('(VUHD|VUILD|THD|TILD)0*([0-9]+)',str(t));return m[1]+str(int(m[2])) if m else t
r=list(rows(ART/'payload/41588_2025_2080_MOESM5_ESM.xlsx',0))
x=pd.DataFrame([v[:12] for v in r[2:]],columns=r[1][:12]);x=x[x.Donor_ID.str.len()>0]
y=pd.read_csv(ART/'payload/aba1972_Table_S2.csv').dropna(subset=['Sample_Name']).drop_duplicates('Sample_Name')
x['canonical_id']=x.Donor_ID.map(norm);y['canonical_id']=y.Sample_Name.map(norm)
x['overlaps_development']=x.canonical_id.isin(y.canonical_id)
x.to_csv(DATA/'spatial_donor_overlap_audit.csv',index=False)
y.to_csv(DATA/'development_donor_metadata.csv',index=False)
print(x[['Donor_ID','Clinical_Diagnosis','overlaps_development']].to_string(index=False))
print(x.groupby(['Clinical_Diagnosis','overlaps_development']).size().to_string())
print(y[['Sample_Name','Age','Diagnosis','Processing_site']].to_string(index=False))
with zipfile.ZipFile(ART/'payload/Sivakumar_supplements.zip') as z:
    print([(i.filename,i.file_size) for i in z.infolist()])
    for i in z.infolist():
        if i.filename.endswith('.pdf'):(ART/'payload'/Path(i.filename).name).write_bytes(z.read(i))
atomic(DATA/'exposure_log.json',dict(at_utc=now(),observed=['all published article texts','development cell metadata including counts','bulk design only','spatial supplement table1 demographics','first 6 rows spatial cell counts table2','first 6 rows spatial gene/pathology association supplement data1 (MMP7 etc)'],unopened=['all scRNA and bulk raw expression','spatial corrected RDS expression','remaining spatial cell-count outcomes'],implication='Spatial published summaries are partially exposed and cannot be represented as fully blinded confirmation. No hypothesis selected on these observed association results.'))
status('metadata_feasibility',['8 primary papers retrieved','bulk adult and repeat audit','development donor metadata retrieved','spatial overlap audit recorded'],['verify scRNA holdout demographics','freeze specific hypothesis and precision','acquire bounded expression matrices'])
