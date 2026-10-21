"""Optional frozen replay for auditors; never new biological confirmation.

Requires FG_PROJECT_ROOT and FG_ARTIFACT_ROOT set to NEW subdirectories of this
campaign's assigned roots. Reuses immutable intakes; performs no network access.
Does not run automatically during the original experiment.
"""
import shutil,json,importlib.metadata,platform
from common import *
assert PROJECT!=PROJECT_BASE and ART!=ART_BASE,'Explicit NEW replay subdirectories required'
assert not PROJECT.exists() and not ART.exists(),'Never overwrite a replay or original confirmation'
expected=json.loads((PROJECT_BASE/'environment.json').read_text())
installed=sorted([(d.metadata['Name'],d.version) for d in importlib.metadata.distributions()])
assert [list(x) for x in installed]==expected['distributions'] and platform.python_version()==expected['python'],'Pinned installed environment mismatch'
PROJECT.mkdir(parents=True);ART.mkdir(parents=True)
for name in ['plan.json','samples.csv','split-audit.json','identity-audit.json','environment.json','environment.uv.lock','freeze-hashes.json']:
    shutil.copyfile(PROJECT_BASE/name,PROJECT/name)
for name in ['metadata','intakes','design']:
    (ART/name).symlink_to(ART_BASE/name,target_is_directory=True)
atomic(PROJECT/'replay-provenance.json',dict(time_utc=now(),replay=True,new_independent_validation=False,
      original_results_sha256=sha(PROJECT_BASE/'results.json'),note='Exact frozen-policy replay on the same consumed labels; never use as a new experiment, model search or confirmation cohort.'))
from run import select,confirm
select();confirm()
original=json.loads((PROJECT_BASE/'results.json').read_text())
replayed=json.loads((PROJECT/'results.json').read_text())
import numpy as np
for key,value in original['metrics'].items():
    np.testing.assert_allclose(value,replayed['metrics'][key],rtol=1e-10,atol=1e-12)
for key in ['mse_improvement','block_95ci','block_and_target_culture_95ci']:
    np.testing.assert_allclose(original['uncertainty'][key],replayed['uncertainty'][key],rtol=1e-10,atol=1e-12)
print('Frozen numerical replay agrees within 1e-10 relative / 1e-12 absolute tolerance; this is not independent evidence.')
