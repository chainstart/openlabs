"""Prospective experiment lock; refuses to replace an existing freeze."""
from common import *
import pandas as pd
import numpy as np

if (DATA/'plan-frozen.json').exists():
    raise SystemExit('Existing scientific freeze must not be overwritten')
meta=pd.read_csv(DATA/'paired-compound-support.csv')
ids=pd.read_csv(DATA/'candidate-pairs-identifiers.csv')
def assign(values,salt):
    values=sorted(set(values),key=lambda x:hashlib.sha256((salt+'|'+x).encode()).hexdigest())
    n=len(values);ntr=int(n*.4);nv=int(n*.2)
    return {x:('train' if i<ntr else 'validation' if i<ntr+nv else 'test') for i,x in enumerate(values)}
drug=assign(ids.structure_key,'drug-support-20261021-structure')
cell=assign(ids.depmap_id,'drug-support-20261021-model')
ids['drug_split']=ids.structure_key.map(drug);ids['cell_split']=ids.depmap_id.map(cell)
ids['split']=np.where(ids.drug_split==ids.cell_split,ids.drug_split,'unused_cross_quadrant')
ids['sample_id']=ids.structure_key+'|'+ids.depmap_id
ids['molecule_id']=ids.structure_key;ids['cell_line_id']=ids.depmap_id
ids.to_csv(DATA/'all-pair-assignments-frozen.csv',index=False)
ids[ids.split!='unused_cross_quadrant'].to_csv(DATA/'samples-frozen.csv',index=False)
plan={
 'created_at_utc':now(),'stage':'exploratory_pilot','candidate_id':'C2_PRISM_independent_redo_replicate',
 'research_question':'For same-compound/same-cell assay translation, does a fixed simple tree model improve a fitted common-support viability-AUC label without improving an independently measured third-repeat common-support response?',
 'use_case':'Prioritize cell models by sensitivity within a drug when an earlier screen is available; not prediction for an unmeasured drug/cell pair, not a clinical model.',
 'hypothesis':'The improvement against fitted summaries can differ materially from improvement against an independent supported measurement. A sign reversal is a stronger secondary claim, not assumed.',
 'independent_unit':['exact chemical structure','official DepMap cell model','screening run','experimental/detection plate replicate'],
 'upstream_independence':'HTS002/MTS006 initial screens versus MTS010 technical redo from the same Broad PRISM program. Different assay runs, not independent laboratories or patient cohorts. Released repackaging is not a new experiment.',
 'identity':'All comma-separated SMILES annotations must parse and give exactly one full isomeric canonical SMILES. No name-only matching or salt/stereochemistry merging. Cell identity uses official depmap_id and passing STR metadata.',
 'split_strategy':{'type':'crossed group','structure':'40% train /20% validation /40% test, stable salted SHA256 ordering','cell_model':'40% train /20% validation /40% test, independently ordered','cross_quadrants':'unused for model fitting/selection/confirmation','structure_generalization':'exact structures held out from target-label training, not scaffold/mechanism cold-start. Source measurements for every test pair are available by design.'},
 'confirmatory_holdout':{'status':'unopened','boundary':'Test drug AND test cell; MTS010 repeat X3 independent of X1/X2 target curve fitting. Target outcome values never used to select split or design. Pre-freeze response files read only for schema and identifiers.','opens':1},
 'raw_preprocessing':{
   'input':'Official PRISM19Q4 v4 secondary-screen-mfi.csv; fresh per-plate normalization, not globally ComBat-corrected responses for primary analysis.',
   'calibration':'For each row_name and detection_plate, retain positive finite MFI; log2 MFI. Require >=3 negative and >=3 positive control wells. Compute robust SSMD=(median(negative)-median(positive))/sqrt((1.4826*MAD_negative)^2+(1.4826*MAD_positive)^2); require finite SSMD>=2, the published control-separation criterion. Divide each experimental MFI by the median same-cell/same-plate vehicle MFI. No normalization pooled across cell models or train/test, no experimental-response outlier deletion.',
   'replicates':'Parse X1/X2/X3 from official detection_plate. Require unique assignment within drug/screen/batch. Source uses all available X1/X2/X3; target fitted label uses only X1 and X2; target measured endpoint only X3. Do not treat X labels as biological donors.',
   'multiple_batches':'Retain provenance; median within identical nominal dose and replicate after exact compound matching. Conflicting identity excluded before outcomes.',
   'dose_units':'micromolar; interpolate/integrate linearly in log10 concentration only within observed support.',
   'support':'For each structure common interval [max(source minimum,target minimum),min(source maximum,target maximum)], fixed by metadata. >=1.2 log10 width and >=4 distinct nominal concentrations per screen within/near this interval. All146 metadata-qualified compounds retained, including22 changed-dose-grid compounds. Never compare full-range AUCs across different ranges.',
   'complete_curves':'For a replicate, require finite normalized responses at every metadata-defined nominal dose (8 expected); source >=2 complete replicates, target X1/X2/X3 all complete. All exclusions logged, never based on responsiveness, fit R2 or whether IC50 is inside tested support.',
   'dose_rounding':'Collapse metadata concentration differences <0.001 log10 within a screen/compound; use actual representative median concentration. No response-dependent dose matching.',
   'curve_fit':'Same fixed top=1 three-parameter decreasing logistic as Chen et al 2026 family: bottom[0,1], log10EC50[-6,6], slope[0,4]. Fit raw normalized source replicates and target X1/X2 separately with scipy least_squares, start(min(max(min(y),0),1),median(logdose),1), max_nfev=300; no hyperparameter tuning. Unsuccessful fits recorded; no R2 exclusions. Fit to all measured positive doses; integrate only common support. This is established curve processing, not a novel method.',
   'fitted_auc':'64-point Gauss-Legendre integral of fitted viability over common log10 interval, divided by interval width.',
   'measured_aut':'Piecewise-linear trapezoid integral of X3 measured viability, clipped to [0,1] to measure bounded growth inhibition, over the same common log10 interval with endpoint interpolation. Also report predeclared unclipped measurement sensitivity. Neither endpoint is an IC50 confidence interval or true noiseless biological response.'},
 'features':['source common-support fitted AUC','source common-support measured AUT averaged over complete replicates','source fitted bottom,log10EC50,slope,RMSE','source measured viability at 5 equally-spaced common-log-support positions','source replicate AUT standard deviation and count','log10 source min/max, target min/max, common min/max; support width'],
 'feature_learning':'No target input features, fitted-label stratification or molecular/omics pretrained features. Missing feature medians/imputation fitted on train only. Fixed feature list, no feature selection.',
 'baselines':[
   {'name':'identity_fit','definition':'Source fixed3PL common-support AUC; also the established adjusted-AUC harmonization comparator'},
   {'name':'affine_fit','definition':'Training ordinary least squares target fitted AUC ~ source fitted AUC'},
   {'name':'drug_mean','definition':'Training target mean per exact structure; global train mean for unseen structures'},
   {'name':'cell_mean','definition':'Training target mean per ModelID; global train mean for unseen models'},
   {'name':'additive_mean','definition':'Global train mean plus train drug and cell deviations; unseen effects zero'},
   {'name':'hgb_full','definition':'HistGradientBoostingRegressor squared_error, max_iter200, max_leaf_nodes31, min_samples_leaf30,l2_regularization5,learning_rate0.05,early_stoppingFalse,random_state20261021'},
   {'name':'hgb_dose_only','definition':'Exactly same capacity/training budget; only source/target/common dose design features'},
   {'name':'rf_leaf5','definition':'RandomForestRegressor 200 trees,min_samples_leaf5,max_features1.0,n_jobs2,seed20261021'},
   {'name':'rf_leaf20','definition':'Same RF budget,min_samples_leaf20'},
   {'name':'identity_raw','definition':'Mean source complete-repeat measured bounded common-support AUT'},
   {'name':'affine_raw','definition':'Training OLS target fitted AUC ~ source measured AUT'}],
 'max_trials':12,'registered_prediction_configurations':11,'curve_processing_configurations':1,'additional_budget':'No adaptive model configurations. Primary fixed HGB; both RF configs reported. Optional seed repeats of same stochastic RF configs with20261022/20261023 logged separately, never select best seed.',
 'primary_comparison':{'model':'hgb_full','comparator':'identity_fit','metric':'Macro-average over drug structures of per-drug MAE; identical paired test rows for both endpoints','fit_gain':'MAE(identity_fit,target_fit)-MAE(hgb_full,target_fit)','measured_gain':'MAE(identity_fit,target_X3_AUT)-MAE(hgb_full,target_X3_AUT)','primary_estimand':'fit_gain - measured_gain (positive means fitted-label improvement overstates measured-response improvement)','minimum_practical_effect':0.02,'units':'normalized viability AUC units','interpretation':'Material misalignment requires 95% interval lower bound above0.02 AND fitted gain positive. Sign reversal additionally requires measured_gain interval upper bound below0. A null interval spanning0 is not equivalence. Lack of precision reported as inconclusive.'},
 'secondary_endpoints':['Within-drug cell-ranking pairwise error, 0.5 for ties, same rows. Report all methods, do not replace primary.','Within-cell drug-ranking only on matched/common-dose eligible comparisons; no global cross-drug rank over nonidentical support.','Rank abstention: source AUT sign consistent across all complete source repeats vs same-coverage largest absolute source fitted-AUC difference, threshold chosen only by source repeat evidence. No retrospective target-fit support gate.','Unclipped X3 AUT errors, each replicate-specific X3 error, between-plate sensitivity and fitted R2 descriptive summaries.','Nearest published3PL/common-support comparator is identity_fit itself; global means and trees cover DrEval-supported strong baseline classes. No claim to reproduce DrEval omics benchmark.'],
 'uncertainty':{'primary':'2000 paired two-way bootstrap resamples of test drug identities and test cell ModelIDs, preserving all endpoint/model differences within rows. RNG20261021. Percentile95 intervals, finite population interpretation conditional on chosen screening program.','sensitivity':'Bootstrap drug and target cell pool clusters; leave-one-target-compound-plate-out estimates; shared experimental plate dependence explicitly limits generality. Do not count dose points, cell pairs, seeds or replicate wells as independent donors.','model_selection':'Primary fixed before data; report validation-selected best tree as secondary, and complete range across both RF configurations and HGB. No choosing an improved confirmation metric.'},
 'precision_plan':json.loads((DATA/'feasibility-final.json').read_text())['precision_scenarios'],
 'stop_conditions':['Absolute campaign deadline','Resource/data budget violation','Cannot establish exact identities/independent assay-repeat labels','Primary complete-case sample or variance insufficient: report actual uncertainty without upgrading claim','Code/data failure requiring target exposure: mark confirmation compromised, retain outputs and do not silently retune'],
 'resource_budget':{'threads':2,'memory_mib':5120,'download_bytes':6*1024**3,'scratch_bytes':12*1024**3,'http_concurrency':1,'gpu':False},
 'limitations_predeclared':['Technical repeat validation within Broad, not independent laboratory validation','Frozen cross-screen calibration requires source measurements, not de novo drug response prediction','One held-out repeat is noisy evidence, not a noiseless truth','Source/target pools and drug plates induce dependencies beyond drug/cell identity','No statement of novelty based on failure to find a paper','Research target does not select a journal or alter global policy'],
 'paper_candidate':False}
write(DATA/'plan-frozen.json',plan)
files=['plan-frozen.json','samples-frozen.csv','all-pair-assignments-frozen.csv','paired-compound-support.csv','compound-identity.csv','environment.json','feasibility-final.json']
freeze={'at_utc':now(),'files':{f:hashlib.sha256((DATA/f).read_bytes()).hexdigest() for f in files},'code_at_freeze':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in CODE.glob('*.py')},'input_manifests':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ART/'intake').glob('prism19*.manifest.json')},'target_outcomes_inspected':False}
write(DATA/'freeze-ledger.json',freeze)
print('Frozen',freeze['at_utc']);print(ids.groupby('split').agg(pairs=('sample_id','size'),drugs=('structure_key','nunique'),models=('depmap_id','nunique')).to_string())
