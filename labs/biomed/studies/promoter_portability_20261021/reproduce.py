"""Deterministic local replay. Never a new independent validation."""
from common import *
import argparse,shutil
import run
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();dest=args.output.resolve()
assert dest.is_relative_to(ART/'replays');dest.mkdir(parents=True,exist_ok=False)
project=dest/'project';art=dest/'artifacts';project.mkdir();art.mkdir()
for n in ['plan.json','samples.csv','split-audit.json','sequence-locus-audit.json','environment.json','design-metadata.json','freeze-hashes.json','code-freeze.json']:shutil.copyfile(PROJECT/n,project/n)
(art/'intakes').symlink_to(ART/'intakes',target_is_directory=True)
run.PROJECT=project;run.ART=art;run.status=lambda *a,**kw:None
run.select();run.confirm()
original=json.loads((PROJECT/'results.json').read_text());replay=json.loads((project/'results.json').read_text());assert original['metrics']==replay['metrics'];assert sha(ART/'test-predictions.csv')==sha(art/'test-predictions.csv')
atomic(dest/'replay-validation.json',dict(time=now(),identical_metrics=True,identical_prediction_bytes=True,original_results_sha256=sha(PROJECT/'results.json'),replay_results_sha256=sha(project/'results.json'),new_validation=False,paper_candidate=False))
print('REPLAY VERIFIED: identical metrics and prediction bytes; not new evidence')
