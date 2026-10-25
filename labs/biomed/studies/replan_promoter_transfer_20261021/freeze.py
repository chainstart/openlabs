"""Seal protocol, metadata partitions and runnable analysis before any real fit."""
from common import *
from models import POINT,RISK,CONTEXTS,SEED
import csv,collections
guard_check()
assert not (DATA/'freeze.json').exists()
assert not (DATA/'training-completed.json').exists()
parts=json.loads((DATA/'partition-summary.json').read_text())
members=json.loads((ART/'derived/partition-membership.json').read_text())
by=collections.defaultdict(set)
for r in members:by[r['group']].add(r['split'])
assert all(len(v)==1 for v in by.values())
with (DATA/'samples.csv').open('w') as f:
    w=csv.DictWriter(f,fieldnames=['sample_id','dataset','group','split']);w.writeheader();w.writerows(members)
split_audit=dict(time=now(),independent_unit='linked genomic locus component',split_strategy='global component SHA256 salted 40/20/40',group_columns=['group'],samples_path=str(DATA/'samples.csv'),samples_sha256=sha(DATA/'samples.csv'),group_overlap=0,summary=parts['summary'])
write(DATA/'split-audit.json',split_audit)
code=pathlib.Path(__file__).parent
plan=dict(stage='exploratory_pilot_with_prospective_holdout',candidate='R2',
    question='Does measured source replicate dispersion improve cross-reporter-position risk ranking beyond source activity, source read support, sequence composition and class?',
    use_case='Select low-risk genomic locus groups before collecting their target-design activity; observed-source calibration, not sequence-only or causal inference.',
    independent_unit='linked genomic locus component',
    primary_outcomes=['Within each study, affine target prediction squared error averaged equally across locus components; compare mean error in lowest-risk half under precision_hgb versus base_hgb.'],
    minimum_relevant_effect=dict(relative=.10,absolute_log2_squared=.01,paired_bootstrap_CI95_lower_above_zero=True),
    success_rule='All three criteria must hold separately in Klein WT and independent Tovar INS held-out components. SCP1 secondary only. Practical usefulness also compared with all simpler risk baselines and validation-selected baseline.',
    contexts=CONTEXTS,point_configurations=POINT,risk_configurations=RISK,
    max_trials=dict(new_candidates=3,model_configurations=12,contexts_per_configuration=3,seeds=[SEED],historical_candidates=3,historical_configurations=8),
    trial_accounting='12 algorithm configurations each executed in three predeclared contexts; 36 context-config evaluations. Five internal affine OOF folds per context are nuisance fits, reported separately. No validation tuning, retraining, seed search or added configurations.',
    split_strategy=split_audit['split_strategy'],group_columns=['group'],
    grouping=parts['grouping'],partitions=parts,
    preprocessing=dict(klein='Training-only per-replicate median offsets centered at mean median.',tovar='Barcode DNA>=10 and >2 retained barcodes in all four configurations if source schema decision selects that filter; source/target totals independently normalized using training rows only; log2((RNA+.5)/(DNA+.5)). Exact choice bound in count-column-decision.',
      target_qc='DNA/barcode availability across designs is cohort eligibility only. Target RNA values and target precision never enter predictors or risk selection; no RNA activity threshold.',
      author_estimate='Published source-only log2 mean for Klein. Tovar uses both reported Alpha_corrected and log2(Alpha_original=Alpha_corrected*ln2), because workbook legend and author plotting code differ in scale interpretation. Both are provided to the same author affine comparator and both matched HGB/ridge feature sets, never selected using target outcomes. Author preprocessing uses whole source libraries; this is transductive source measurement, not target leakage.',
      feature_filling='Training median for missing author source estimate plus explicit missing flag; class list learned from training.'),
    models=dict(point='Identity; weighted affine OLS; weighted standardized ridge alpha10; training class mean; affine on published source estimate + missing flag; paired HGB with/without log1p(source SEM²).',
      risk='5-fold group-hashed OOF affine squared errors, all normalization inside each OOF fold. HGB regresses log1p(error); same fixed settings and source features, SEM² added only to precision model.',
      HGB=dict(max_iter=100,max_leaf_nodes=4,learning_rate=.05,min_samples_leaf=30,l2_regularization=10,early_stopping=False,random_state=SEED),
      weights='Each locus component has equal total fit weight; equal-component evaluation; source SEM² is variance across three log-activity repeats /3.',
      ties='Ascending frozen group ID is the deterministic tie break, including constant-risk control.'),
    inference=dict(bootstrap=10000,seed=SEED,unit='whole component',pairing='same resampled group multiset for all models',selection='sort risk then group ID; retain floor(n_groups/2), reselect within every bootstrap',
       multiplicity='Joint primary conclusion requires success in both predeclared primary contexts; all remaining comparisons descriptive, no selective significance claims.',
       uncertainty='Conditional on frozen models and sampled loci; does not estimate population-of-studies uncertainty or refit-training variability. Present all configurations and validation selection uncertainty.'),
    diagnostic='Mean squared affine residual minus estimated RNA replicate-mean noise; Klein sums source/target marginal variances (independent assay replicates); Tovar uses paired electroporation residual variance. Retain negative corrections. Shared DNA error persists in Tovar; Poisson DNA subtraction is assumption-only sensitivity, not identified biological variance. Also report this diagnostic among held-out groups with mean source SEM² no larger than the training-group 25th percentile; threshold learned from training only, no subgroup hypothesis significance claim.',
    baselines=POINT+RISK,leakage_controls=['All old exposed outcomes development only','No old labels included','No target-feature use','No group overlap','Source schema audit before freezing','No holdout fitting or adaptation'],
    confirmatory_holdout='Single opening after fixed training/validation outputs and model hashes; all three context predictions saved before summary. Mechanical pre-freeze count aggregation and partition copying disclosed.',
    stop_conditions=['No verified count schema','Inadequate linked groups makes confirmation exploratory','Deadline 2026-10-21T19:51:45.199167Z','No re-opening or replacing confirmation on poor results'],
    resource_budget=dict(cpu_threads=2,memory_high_MiB=4096,memory_max_MiB=5120,swap_MiB=512,tasks=96,download_GiB=6,scratch_GiB=12,GPU=False),
    closest_work='Tovar2026 establishes reporter-position/promoter bias and motif LASSO; Klein2020 compares assay designs; PARM2026 sequence modeling; Yang2601.14969v3 sequence-only uncertainty/error coverage. This narrower source-replicate incremental-risk question is a candidate, not proven novel.',
    limitations=['Only two upstream experiments, different cellular settings and protocols','Tovar same pooled library and shared DNA among RNA replicates','Three repeats give noisy variance estimates','No claim about promoter directionality or endogenous causality','Filtered cohort is not all designed elements; our16094 fragments do not reproduce author11656 cohort, detailed intermediate filtering unavailable','Published author-estimator preprocessing not independently recomputed with original MPRAnalyze; source-scale ambiguity explicitly handled with two fixed representations','Per-configuration training-total normalization measures within-library relative activity; not an estimate of absolute global design-induced expression shifts.'],paper_candidate=False)
write(DATA/'plan.json',plan)
freeze=dict(time=now(),plan_path=str(DATA/'plan.json'),plan_sha256=sha(DATA/'plan.json'),
  code_sha256={str(p):sha(p) for p in code.glob('*.py')},partitions=parts,
  decision_sha256=sha(DATA/'count-column-decision.json'),split_audit_sha256=sha(DATA/'split-audit.json'),
  environment_sha256=sha(DATA/'environment.json'),test_opened=False,real_models_fitted=False)
write(DATA/'freeze.json',freeze);write(ART/'freeze.json',freeze)
ledger=json.loads((DATA/'complete-trial-ledger.json').read_text())
ledger['current_trials']=[dict(configuration_id=f'P{i+1}',kind='point',name=name,status='registered',contexts=list(CONTEXTS)) for i,name in enumerate(POINT)]+[dict(configuration_id=f'R{i+1}',kind='risk',name=name,status='registered',contexts=list(CONTEXTS)) for i,name in enumerate(RISK)]
ledger['time']=now();ledger['freeze_sha256']=sha(DATA/'freeze.json');write(DATA/'complete-trial-ledger.json',ledger)
status('frozen','来源重复精度的跨报告位置风险排序增量', ['来源核验','metadata分组','12配置及代码冻结'],['训练验证','一次确认','结果复核与中文报告'],'guard --task-type cpu -- python freeze.py')
print('frozen',freeze['time'],sha(DATA/'freeze.json'))
