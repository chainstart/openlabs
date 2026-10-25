"""Freeze a new prospective external-screen test; never re-open an old holdout."""
from common import *

assert not (DATA/'plan-frozen.json').exists(), 'Immutable freeze already exists'
feas=json.loads((DATA/'identity-and-support-feasibility.json').read_text())
configs=[
 {'id':'gap_raw','definition':'Identity source mean replicate empirical AUT; retain largest absolute source AUT separation.'},
 {'id':'gap_fit','definition':'Established common-support 3PL source AUC (Pozdeyev/Chen family); retain largest fitted separation; failed fit falls back to raw AUT, no fit-quality exclusion.'},
 {'id':'additive_mean','definition':'Training old-target overall mean + cell mean deviation + drug mean deviation; unseen effects zero. Rank by these predictions, select largest separation.'},
 {'id':'repeat_agreement','definition':'Fraction of all cross-repeat cell comparisons agreeing with source-mean order; ties half. Select greatest agreement, deterministic hash tie-break.'},
 {'id':'standardized_gap','definition':'raw_gap / sqrt(sd_i^2/n_i + sd_j^2/n_j + 0.02^2). Fixed 0.02 floor, no tuning.'},
 {'id':'nrfe_curve','definition':'Select lowest max curve NRFE of the two source curves. NRFE=mean(100*abs(y-fit)*(1+4*fit*(1-fit))) over source repeats/doses. Same fixed 3PL fit across methods. Published NRFE formula adapted to curve level, not a reproduction of full 4PL plateQC/plate exclusion.'},
 {'id':'isotonic_gap','definition':'Training drug-balanced IsotonicRegression(increasing=False,out_of_bounds=clip), predicts observed pair ranking error from raw_gap.'},
 {'id':'ridge_full','definition':'Training median imputation and StandardScaler, Ridge(alpha=10), drug-balanced weights, full frozen pair features; clip predicted error to [0,1].'},
 {'id':'hgb_gap','definition':'HistGradientBoostingRegressor(squared_error,max_iter=200,max_leaf_nodes=15,min_samples_leaf=50,l2_regularization=5,learning_rate=.05,early_stopping=False,random_state=20261021); raw_gap only.'},
 {'id':'hgb_full','definition':'Same HGB capacity, iterations, weights and seed; full frozen pair features; fixed primary, not validation-selected.'},
 {'id':'hgb_dose','definition':'Same HGB capacity and budget; common_lo,common_hi,support_width,source_log_min,source_log_max,source_n_doses only. Ties use hash, not response gap.'},
 {'id':'curve_processing','definition':'One fixed source 3PL fit with top1,bottom[0,1],logEC50[-6,6],slope[0,4], scipy least_squares max_nfev300; original known parameters reused where identical source measurements. Empirical log-dose piecewise-linear integration. No adaptive fits.'}
]
plan={
 'created_at_utc':now(),'stage':'exploratory_pilot_with_prospective_external_screen_confirmation',
 'candidate_id':'C1_source_reliability_transport','paper_candidate':False,
 'research_question':'At fixed 50% comparison coverage, can source-only measurement precision, curve quality, saturation and dose-design information learned from technical-repeat development predict which within-drug cell rankings replicate in the independently generated CTRPv2 screen, better than simply taking large source response gaps?',
 'use_case':'Prioritize relative sensitivity of two existing cell models to the same drug when source PRISM measurements and target planned dose range are available. Same-drug/same-cell screen transfer; not unseen-drug response prediction, clinical efficacy or a mechanism test.',
 'hypothesis':'Additional source reliability information may or may not transport. No direction of fitted-label inflation is assumed.',
 'nearest_work':{
  '2016_10.18632/oncotarget.10010':'Established common-support AUC; not our invention.',
  '2025_10.1016/j.isci.2025.113470':'NRFE plate QC and cross-GDSC two-sided quality filtering already established. We test frozen one-sided deployment at matched coverage; curve-level NRFE comparator is explicitly adapted, not full plateQC reproduction.',
  '2026_10.1093/bioinformatics/btag382':'Truncation, raw curves, cross-screen correlations and top20 ranking overlap already covered; no new metric claim.',
  '2026_10.64898/2026.04.29.721574':'Preprint iDRR/DRS covers pooled consensus SEE and reliability across 15 screens. Its consensus uses target measurements and is not a prospective source-only risk predictor; do not feed target-informed consensus as feature.',
  '2026_10.1038/s41467-026-72903-w':'DrEval strong baselines and assay/ex-vivo transfer; not reproducing its omics benchmark.'},
 'data':{'source':'PRISM19Q4 v4 HTS002/MTS006 source normalized using original per-cell/detection-plate controls and fixed SSMD>=2. Read-only verified previous payload and normalization.',
         'development_target':'Previously exposed MTS010 X3. Original train + original test become development training; original validation remains development validation. No old test is confirmation.',
         'external_target':'CTRPv2 raw repeat input in author Zenodo17981848 (823603861 bytes, exact SHA in manifest), author DrugNameMap commit144210bb1860089c82d038c9accbee4e6ec45c5e for original CTRP SMILES. Different upstream experiments, same Broad institution; matched cell identities, not new donors.',
         'identity':feas['exact_identity_policy'],'cell_linkage':feas['cell_identity_policy'],
         'replicate_caveat':feas['replicate_warning'],
         'unit':'micromolar dose; author dose field log10(uM); response relative viability; endpoint normalized common-log-support AUT, not IC50/Ki/Kd'},
 'independent_unit':['chemical structure','cell model','upstream screen'],
 'metadata_counts':{'external_pairs':feas['source_eligible_pairs'],'external_structures':feas['source_eligible_structures'],'external_models':feas['source_eligible_models']},
 'preprocessing':{
  'support':'Per structure modal CTRP metadata min/max intersect actual representative PRISM source and MTS010 dose endpoints; shave 2e-6 log units from each endpoint for rounding safety; width>=1.2. Frozen common-support-metadata.csv. Non-CTRP development drugs use original full common support.',
  'source':'At least 2 complete original technical repeats, all expected nominal dose points finite; use all complete repeats; compute per-repeat bounded empirical AUT and their mean, SD. Source input mapping comes from old selected-well metadata. Different-source identity conflicts excluded.',
  'target':'Stream CTRP in chunks; retain frozen exact matches; aggregate all finite response measurements at identical actual log dose by median, clip median to [0,1] for primary; >=4 distinct dose points and coverage of entire frozen support, no extrapolation. Exclusions by missingness/support only; never by magnitude, fit R2 or cross-screen agreement.',
  'target_replicates':'Do not treat CTRP replicate number as a biological/independent experimental unit; primary target is per-screen median response at each dose.',
  'curve_fit_failures':'Do not discard primary raw-response rows. Fitted-AUC baseline falls back to raw; NRFE-only missing score worst; learned missing-feature imputation trained on development only, failure indicator included.',
  'drug_eligibility':'At least 20 eligible matched cells after predefined completeness requirements. Every eligible drug equally weighted, regardless of number of comparisons.',
  'source_saturation':'Fraction of source raw measurements <=0.05 or >=0.95; computed without target responses.',
  'no_target_features':True},
 'features':['raw_gap','fit_gap','mean_auc','min_auc','max_auc','pooled_se','mean_rep_sd','max_rep_sd','min_nrep','standardized_gap','repeat_agreement','mean_nrfe','max_nrfe','mean_rmse','max_rmse','mean_saturation_low','mean_saturation_high','mean_dynamic_range','difference_dynamic_range','fit_failed','common_lo','common_hi','support_width','source_log_min','source_log_max','source_n_doses'],
 'training':{'pair_target':'0 if source raw-AUT ranking agrees with exposed MTS010 X3 empirical AUT ranking; 1 for opposite ranking; 0.5 if either is tied.',
             'sampling':'At most 2000 uniformly sampled distinct cell pairs per training drug; seed20261021; exact same rows/weights for all learned methods. Exhaustive development validation and external evaluation.',
             'weights':'Each training drug has equal total weight; scale weights to sum to number of training rows.',
             'selection':'Primary HGB full fixed. Validation-best learned selector is secondary only; all configurations reported. No tuning or new seeds after external results.',
             'source_endpoint':'All reliability selectors keep raw mean AUT direction; gap_fit/additive_mean have their own predeclared directions.'},
 'configurations':configs,'max_trials':12,'prediction_configurations':11,'curve_processing_configurations':1,
 'primary':{'model':'hgb_full','baseline':'gap_raw','coverage':0.5,
            'selection':'Within each drug retain floor(0.5*N) pairs ranked by source-only reliability score. Ties broken by stable SHA256 pair ID, never target outcome; same count for every method.',
            'metric':'Drug-equal macro mean observed CTRP ranking disagreement (ties 0.5).',
            'estimand':'error(gap_raw)-error(hgb_full), positive favors additional reliability features.',
            'minimum_practical_effect':0.02,'units':'absolute ranking-error probability (2 percentage points)',
            'decision':'Material improvement requires lower95CI>0.02. Novel information claim additionally requires positive lower95CI vs same-capacity hgb_gap and vs isotonic_gap. No method superiority claim over full plateQC/DRS implementations.'},
 'secondary':['All baseline errors at 50% coverage and all-pair ordering error.','25% and 75% coverage curves, never replace 50% primary.','Brier error and 5 fixed probability bins for learned predictors, without recalibration on external data.','Primary contrast with unclipped target empirical AUT.','Per-drug and tissue/pool descriptive results, no new hypothesis confirmation.','Validation-selected predictor and range over all learned models.','Stratify external drugs/cells by development-training identity presence; not cold-start claims.'],
 'uncertainty':{'primary':'1000 paired bootstrap resamples of chemical structures and global cell ModelIDs, independently with replacement, seed20261021. Pair weight product of its two cell counts; drug weight multinomial count. Fixed chosen comparison sets and fitted models; intervals conditional on development and source panel, not full retraining uncertainty.',
                'sensitivity':'Drug-only bootstrap; leave-one-source-compound-plate-out primary contrasts. Shared screening campaign, pools and unobserved CTRP plates constrain generality; comparison pairs are not independent biological samples.',
                'null':'CI containing zero is not equivalence; upper95CI below0.02 only excludes the registered material benefit in this conditional population.'},
 'precision':feas['precision_scenarios'],
 'confirmation':{'status':'unopened','max_opens':1,'boundary':'No CTRP numeric response was parsed before this freeze. Metadata/source eligibility inspected. Target aggregation may subsequently be computed into sealed artifacts without effect evaluation; fitted models, source scores and selection decisions must be frozen before opening paired effects.',
                 'old_holdouts':'All old PRISM/GDSC outcomes development only; no unopened old target subset accessed for confirmation.'},
 'resource_budget':{'cpu_threads':2,'memory_high_mib':4096,'memory_max_mib':5120,'swap_mib':512,'tasks':96,'download_gib':6,'scratch_gib':12,'http_concurrency':1,'gpu':False},
 'deadline_utc':'2026-10-21T19:51:45.199167+00:00',
 'stop_conditions':['Absolute campaign deadline; reserve final 30min for review/report.','Identity, units or upstream provenance invalidated: stop dependent confirmation and record failure.','Target processing error exposing outcomes before frozen scores: mark compromised, never silently restart confirmation.','No material gain or insufficient precision: retain null/negative result, do not change thresholds or endpoints.']}
write(DATA/'plan-frozen.json',plan)
files=['plan-frozen.json','common-support-metadata.csv','metadata-qualified-pairs.csv','ctrp-compound-identity.csv','cell-linkage.csv','environment.json','old-payload-reuse.json']
write(DATA/'freeze-ledger.json',{'at_utc':now(),'files':{f:sha256_file(DATA/f) for f in files}})
ledger=json.loads((DATA/'all-trials-ledger.json').read_text())
ledger['current_campaign']['registered_configurations']=configs
ledger['current_campaign']['trials'].append({'at':now(),'type':'registration','n_configurations':12,'n_predictors':11,'n_curve_processing':1,'external_outcomes_exposed':False})
ledger['current_campaign']['software_events']=[
 {'event':'metadata initial integrity check stopped because normalized matrix hash resides in normalization-recovery.json rather than inventory; corrected provenance lookup, actual hash matches','science_outcomes_used':False},
 {'event':'ad hoc plate-count probe duplicated source_screen column during merge; corrected to use existing column','science_outcomes_used':False}]
write(DATA/'all-trials-ledger.json',ledger)
write(DATA/'candidate-ledger.json',{'at':now(),'candidates_used':3,'max_candidates':3,'candidates':[
 {'id':'C1','disposition':'selected_and_frozen','evidence':'identity-and-support-feasibility.json; 50 structures/444 models/15675 source-qualified pairs','question':plan['research_question']},
 {'id':'C2','disposition':'not_advanced','reason':'Fixed-truncation versus ranking preservation is directly close to Chen2026 top20-sensitive overlap and full/truncated comparisons; no demonstrated distinct question stronger than C1. No outcome experiments run.'},
 {'id':'C3','disposition':'not_advanced','reason':'Author PRISM MTS021-026 release concerns only AZ-628,nutlin-3a,imatinib control drugs; same Broad program and already compared by Chen2026. Three compounds cannot provide general drug-level reliability calibration evidence. No outcomes downloaded or evaluated.'}]})
status('plan_frozen',['prior audit','recent literature and direct near-neighbors','actual source and identity feasibility','12 configurations registered before CTRP response parsing'],['derive source features','fit development models','seal external scores','one external evaluation','independent implementation review and Chinese report'],[str(DATA/'plan-frozen.json'),str(DATA/'freeze-ledger.json')])
print('Frozen',sha256_file(DATA/'plan-frozen.json'))
