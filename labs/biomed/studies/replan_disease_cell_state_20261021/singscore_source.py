from common import *
j=json.loads((ART/'payload/singscore_tree.json').read_text());commit=j['sha']
for path in ['R/rankAndScoring.R','R/rankGenesGeneric.R','R/simpleScoreGeneric.R','DESCRIPTION']:
 fetch('https://raw.githubusercontent.com/DavisLaboratory/singscore/'+commit+'/'+path,'singscore_'+path.split('/')[-1],timeout=60)
