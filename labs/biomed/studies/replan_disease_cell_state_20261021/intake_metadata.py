from common import *
# Serial audited official metadata; expression files not opened here.
fetch('https://raw.githubusercontent.com/LungCellAtlas/HLCA_reproducibility/318d17d4277baddb202f903cf7b6680caf0230d8/scripts/LCA_file_reading.py','HLCA_file_reading.py')
for path in ['README.md','Fig1_BC.R','Fig5_DE_TableS8.R']:
 fetch('https://raw.githubusercontent.com/tgen/banovichlab/31704e559e9b098a82508d6bd04bb81aa799a263/pulmonary_fibrosis/10x_scRNA-Seq_2019/'+path,'banovich_'+path)
for path in ['README.md','combined_metadata.csv','ipf_sensitivity_analysis.R','study_imbalance_analysis.py']:
 fetch('https://raw.githubusercontent.com/gmiaslab/IPF_Analysis/24683aabb81c748c97de3f13e2150971a6c38778/'+path,'mias_'+path)
for acc in ['GSE150910','GSE124685','GSE184316']:
 fetch(f'https://ftp.ncbi.nlm.nih.gov/geo/series/{acc[:-3]}nnn/{acc}/matrix/{acc}_series_matrix.txt.gz',acc+'_series_matrix.txt.gz',timeout=120)
q='(idiopathic pulmonary fibrosis) AND (transcriptomic OR deconvolution) AND (age OR cross-study OR pseudobulk) AND FIRST_PDATE:[2024-01-01 TO 2026-10-21]'
fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&pageSize=50&resultType=core&query='+urllib.parse.quote(q),'europepmc_recent.json')
fetch('https://api.crossref.org/works/'+urllib.parse.quote('10.64898/2026.06.24.734263',safe=''),'mias_preprint_crossref.json')
