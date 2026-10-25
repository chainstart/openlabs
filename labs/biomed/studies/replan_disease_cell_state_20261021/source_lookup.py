from common import *
for repo,branch,label in [('tgen/banovichlab','master','banovich'),('gmiaslab/IPF_Analysis','main','mias')]:
 fetch(f'https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1',label+'_tree.json')
for acc in ['GSE150910','GSE124685','GSE184316']:
 fetch(f'https://ftp.ncbi.nlm.nih.gov/geo/series/{acc[:-3]}nnn/{acc}/suppl/',acc+'_files.html',timeout=60)
 fetch(f'https://ftp.ncbi.nlm.nih.gov/geo/series/{acc[:-3]}nnn/{acc}/matrix/',acc+'_matrix_listing.html',timeout=60)
