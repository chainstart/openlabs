"""Design arithmetic only; no expression input or new scoring configuration."""
from common import *
from scipy.stats import binom
assert not (DATA/'confirmation_open.json').exists()
current={str(p):float(binom.sf(5,9,p)) for p in [.25,.5,.75]}
table=[]
for n in range(9,101):
 critical=next(k for k in range(1,n+1) if binom.sf(k-1,n,.25)<.025)
 table.append(dict(n=n,critical_events=critical,power_if_true_frequency_half=float(binom.sf(critical-1,n,.5))))
minimum=next(r for r in table if r['power_if_true_frequency_half']>=.8)
atomic(DATA/'precision_design_review.json',dict(at=now(),before_expression=not (ART/'GSE184316_scores.csv').exists(),n9_power=current,future_design_example=minimum,assumptions='Independent donor Bernoulli events under a common unchanged sampling protocol; true frequency0.5 is a planning scenario, not an estimated result. Exact interval test is discrete; power may not increase monotonically at every n.',not_a_new_model_or_trial=True,no_threshold_or_sample_changes=True,code_sha256=sha(Path(__file__))))
