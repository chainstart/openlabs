from common import *
fetch('https://api.github.com/repos/DavisLaboratory/singscore/git/trees/master?recursive=1','singscore_tree.json',timeout=60)
for pmc in ['PMC6219008','PMC3199230','PMC11531500']:
 fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/'+pmc+'/fullTextXML',pmc+'.xml',timeout=60)
