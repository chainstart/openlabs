from common import *
files=list((ART/'payload').glob('*.part'))
progress={p.name:p.stat().st_size for p in files}
status('frozen_plan_intake_and_implementation',['Frozen scientific question and12fixedconfigurations before score inspection','Official donor mapping and cross-study overlap audit completed','Estimator algebra and donor/pair accounting checks passed','Bounded official bulk payload transfers in progress'],['Verify complete payload SHA/gzip/schema','Freeze gene identifier intersection without expression selection','Run development and once-only independent confirmation','Review source/estimators/results and Chinese final report'],['Original single-cell source-count gate remains unmet','GSE199949 four missing-ageIPFdonors excluded','Metadata sex conflicts excluded from adjustment','Initial software JSON boolean serialization error fixed before any expression score'])
obj=json.loads((ART/'research_status.json').read_text());obj['download_progress_bytes']=progress;obj['transfer_accounted_bytes']=json.loads((ART/'transfer_bytes.json').read_text())['bytes'];obj['code_paths']=str(CODE)
for root in [ART,DATA]:atomic(root/'research_status.json',obj)
print(json.dumps(progress))
