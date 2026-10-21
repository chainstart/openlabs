from common import *
import sys,shutil,re,html
sys.path.insert(0,str(CODE.parents[1]))
from protocols.public_data_pilot import validate
from tools.split_audit import audit
r=json.loads((PROJECT/'results.json').read_text());sel=json.loads((PROJECT/'frozen-selection.json').read_text());v=json.loads((PROJECT/'validation.json').read_text());diag=json.loads((PROJECT/'post-outcome-diagnostics.json').read_text());plan=json.loads((PROJECT/'plan.json').read_text());metrics=r['metrics'];primary=metrics['primary_context_transfer'];same=metrics['same_mapping'];b=r['selected_baseline'];o=r['selected_orientation']
for u,n in [('https://www.ncbi.nlm.nih.gov/home/about/policies/','ncbi-policies.html'),('https://creativecommons.org/licenses/by/4.0/','ccby4.html')]:fetch(u,n)
# Clarify unresolved genome-build identity rather than treating literal coordinates as biological sequence identity.
alt=json.loads((PROJECT/'design-alternatives.json').read_text());alt['routes'][0]['decision']='Exact insert and strand translation to the old panel was not established: zero literal coordinate-tuple matches, unharmonized genome build, variable insert lengths. This does not prove absence of matching biological sequences. No cross-system effect estimate was attempted. Within-system context stress test completed.'
alt['routes'][0]['limitations'].append('Literal overlap counts are annotation-level only because genome build remains unverified; no inference of biological disjointness.')
atomic(PROJECT/'design-alternatives.json',alt)
trials=json.loads((PROJECT/'trial-ledger.json').read_text())
for t in trials:t['test_descriptive']=primary['metrics'][t['configuration']];t['primary_selected']=t['configuration'] in [b,o]
atomic(PROJECT/'complete-trial-ledger.json',dict(model_trials=trials,control_trials=dict(path=str(ART/'control-trials.json'),sha256=sha(ART/'control-trials.json'),n_signflip=1000,n_permutation=1000,refits=0),failed_attempts=[dict(stage='schema inspection',error="ModuleNotFoundError: openpyxl",resolution='No package installed; implemented bounded standard-library XLSX ZIP/XML reader before freeze; no outcomes inspected'),dict(stage='coordinate metadata parsing',error="ValueError int('start')",resolution='Header guard corrected before freeze; initial failed run did not compare outcomes'),dict(stage='GEO landing metadata',error='Browser challenge HTML returned with HTTP200',resolution='Archived challenged response and used official FTP HTTPS file index'),dict(stage='skill workflow path',error='Initial guessed multi-source-search.md path absent',resolution='Used manifest-mapped wf1-multi-source-search.md')],download_failures=[str(p) for p in (ART/'metadata').glob('*.failure.json')]))
# Source intake copies remain small in data project; payloads stay in artifacts.
ledger=json.loads((PROJECT/'complete-trial-ledger.json').read_text())
if (PROJECT/'protocol-validation-attempt1.json').exists():
 ledger['failed_attempts'].append(dict(stage='protocol packaging',error=json.loads((PROJECT/'protocol-validation-attempt1.json').read_text())['errors'],resolution='Retained original frozen enriched split audit; added separate native protocol audit and code-revision compatibility field. Scientific outputs unchanged.'))
 atomic(PROJECT/'complete-trial-ledger.json',ledger)
manifests=[]
for p in sorted((ART/'intakes').glob('*/manifest.json')):
 dest=PROJECT/'intake-manifests'/f'{p.parent.name}.json';dest.parent.mkdir(exist_ok=True);shutil.copyfile(p,dest);manifests.append(dict(path=str(dest.relative_to(PROJECT)),sha256=sha(dest)))
rows='\n'.join(f"| {n} | {sel['validation_metrics'][n]['mse']:.6f} | {primary['metrics'][n]['mse']:.6f} |" for n in plan['baselines'])
ci=primary['bootstrap']['relative_improvement_ci95'];prox=metrics['strata']['proximal'];pc=prox['bootstrap']['relative_improvement_ci95'];dist=metrics['strata']['distal']
report=f'''# Promoter directionality portability: bounded research report

Completed {now()}. **Independent reporter-system transfer remains untested; paper_candidate=false.** A prospectively frozen fallback analysis provides new, limited evidence about promoter-activity directionality across minimal-promoter contexts within QUASARR-seq. It is not independent replication of the old Agarwal/WTC11 result, a new algorithm, or a causal mechanism.

## Scientific result

Across **{primary['n']} held-out genomic elements / {primary['groups']} locus-homology groups**, a model trained on MYC→GAPDH promoter activity and selected without test labels predicted GAPDH→APOBEC3F forward-minus-reverse promoter activity with MSE **{primary['metrics'][o]['mse']:.6f}**, versus **{primary['metrics'][b]['mse']:.6f}** for the validation-selected strongest activity/nuisance baseline. Relative improvement was **{100*primary['relative_mse_improvement']:.2f}%**, with paired component-bootstrap 95% interval **{100*ci[0]:.2f}% to {100*ci[1]:.2f}%** (2,000 resamples). The frozen criterion required a point improvement ≥5% and absolute-improvement interval above zero; it passed. The interval does not establish that the true improvement exceeds 5%.

The primary endpoint is **promoter paBC log2(RNA/DNA), forward minus reverse**, averaged across two replicate columns. Every analyzed row measures local promoter activity. Including distal elements does not replace the endpoint with enhancer activity, but it limits the claim: the main panel mixes proximal and distal regulatory elements. **Only {prox['n']} test elements are annotated proximal promoters.** Their estimated improvement was {100*(1-prox['orientation']['mse']/prox['baseline']['mse']):.2f}%, interval **{100*pc[0]:.2f}% to {100*pc[1]:.2f}%**; promoter-only portability is inconclusive. The 95 distal elements showed {100*(1-dist['orientation']['mse']/dist['baseline']['mse']):.2f}% improvement. These predefined strata are descriptive, not separate confirmations.

## What failed or weakened

* Directly copying source directionality had MSE **{primary['metrics']['identity_delta']['mse']:.6f}**, better than the selected learned model. The latter was **11.04% worse** than direct copying (post-outcome descriptive comparison; interval includes either ordering). There is no evidence here that the learned method improves on the simplest direction-preserving translation.
* The predefined reverse-complement antisymmetric sequence model had MSE **{primary['metrics']['antisym_seq']['mse']:.6f}**, worse than the selected activity baseline. This small k-mer model supplies no positive sequence-only portability result.
* The same-mapping MYC→GAPDH test improvement was **{100*same['relative_mse_improvement']:.2f}%**, compared with {100*primary['relative_mse_improvement']:.2f}% after changing the source/target contexts. Different target variances preclude reading their raw MSE difference as a pure context causal effect.
* Both precision strata and the low-activity stratum had improvement intervals crossing zero. The high-activity stratum contains only 15 loci; it cannot establish a reliable general failure/success boundary. Proximal-promoter insufficiency is the clearest limitation.

The test-best nuisance model, selected after outcomes only as a diagnostic, had MSE {primary['metrics']['nuisance_ridge']['mse']:.6f}; the frozen selected model still improved by {100*diag['learned_vs_test_best_nuisance']['relative_improvement']:.2f}% against it. This comparison does not replace the primary selection or add a new configuration.

## Controls and measurement limits

Target replicate directionality correlation was **{metrics['target_replicate_delta_pearson']:.3f}**. Source/target residual directionality correlation after training-only nuisance regressions was **{metrics['activity_conditioned_residual_pearson']:.3f}**. Both target replicate contrasts separately favored the selected source-informed model over the selected baseline. None establishes mechanism or independent-laboratory reproducibility.

There were 1,000 component-wise source sign-flip controls and 1,000 source-direction permutations within source-activity tertiles, applied to frozen models with nuisance features unchanged. No control MSE was at or below observed selected-model MSE (empirical fraction 0/1,000; finite simulation resolution, not p=0). Exact antisymmetry of the sequence model was checked computationally. These are conditional model controls, not independent biological experiments.

## Independent-source feasibility: three routes

1. **QUASARR-seq, Paramo et al. 2026, DOI 10.1038/s41467-026-68780-y, GSE310760.** Official publisher source workbook (4.62 MB) contains element coordinates, sequences and GENCODE classifications; four small processed paBC tables contain explicit `.fwd`/`.rev` pairs. The author repository was pinned at `{json.loads((PROJECT/'author-code-pin.json').read_text())['commit']}`. There are 716 paired elements in the original library and 1,093 / 1,439 / 1,195 in MYC / GAPDH / APOBEC3F contexts before genomic eligibility. Original measurements are a different laboratory/vector from Agarwal. However, **ENCSR382BVV is exactly the old K562 source** and is not independent evidence. Literal coordinate comparisons found zero exact old-promoter tuples and 215 overlaps across all supplied coordinates. Genome-build harmonization and old/new insert sequence/strand identity were not established; the tuple result cannot prove biological disjointness or exact matches. Elements vary 65–703 bp. The fallback therefore evaluates contexts only. Cross-system generalization remains open.
2. **Roberts2021, DOI 10.1101/gr.270751.120.** Cached original XML identifies GSE156857, reused SuRE GSE128325, and Johnson SRP144640. Downloaded official processed HTT/SORT1 stranded tables are 290-bp bin summaries of heterogeneous-fragment STARR assays, not matched exact forward/reverse promoter inserts. SuRE's official file inventory was inspected: stranded genome-wide tracks likewise aggregate fragments. No promoter endpoint was fabricated from these bins, and the 12-GB raw archive was not downloaded. A different bin-level STARR/SuRE comparison would substantially repeat Roberts and would need a separately justified question.
3. **Bose2025, DOI 10.1101/2025.10.13.659964, GSE279057.** Original XML, pinned author analysis code and the 9.15-MB annotation file were inspected. The annotation table has **79,380 records, 39,653 unique sequences, and zero exact non-palindromic reverse-complement sequence entries**. Four plasmid configurations mean INS/SCP1 promoter × upstream/downstream position; CAGE strand annotation is not a reverse-cloned insert measurement. No valid paired-directionality panel was established. Barcode/count payloads were not fetched after this design-level failure.

These findings support a scoped feasibility no-go for the requested exact-insert independent transfer analysis with the audited files, not a claim that no useful independent data exist anywhere. A sequence-only cross-study design would need its own orientation/sequence audit and novelty justification; sequence prediction alone is already prior art.

## Prospective validation boundary

Before numerical outcomes, the sample table, grouping, endpoint, MSE metric, ≥5% criterion, 11 configurations, bootstrap unit and source/target mapping were frozen. The eligible autosomal panel had **358 elements: 159 train, 49 validation, 150 test**, including 124 proximal elements total. The 150 test rows occupy 123 1-Mb blocks. Hash-assigned connected components grouped coordinate overlap, 1-Mb blocks, exact/reverse-complement identity, and ≥20% canonical 21-mer containment. The 40% test allocation was selected before labels to retain ≥100 loci and ≥30 blocks. All 150 test loci passed positive finite RNA/DNA QC; no target-label trimming or imputation occurred.

The source measurements at test loci are explicitly available: this is measured-source transfer. Scaling, imputation-free features and model fitting used training loci only. Validation selected `{b}` and `{o}`. No refit followed. Confirmation has one start and one completion marker. The old WTC11 confirmation was never used for selection; all old frozen-input hashes still match. Molecular compatibility fields explicitly mean **DNA locus, not small molecule**.

The split tool passed its supported identifier-overlap audit. It does **not** establish independent studies/donors, genome-build harmonization, exhaustive distant homology, full genome alignment, construct resequencing, or genomic-reference strand identity. Those unsupported audits are explicitly recorded, not marked passed. Author forward/reverse labels are used within contexts; sequence-table orientation is not asserted to be genomic strand. The main selected model uses composition and measured source directionality, not a genomic strand claim.

| Frozen configuration | Validation MSE | Context test MSE (descriptive except selected primary) |
|---|---:|---:|
{rows}

## Novelty and disposition

Roberts2021 already studies cross-assay strand asymmetry and sequence predictors. Agarwal2025 (DOI 10.1038/s41586-024-08430-9) supplies the old shared-study/vector panel. Bose2025 studies promoter/position biases and sequence/strand associations. Paramo2026 already demonstrates minimal-promoter effects on overall promoter activity. This analysis adds only an incremental, prospectively evaluated **activity-conditioned directionality stress test** with explicit failure/uncertainty findings. It does not establish a new biological mechanism, and no RNA-stability association is given a causal interpretation.

**Paper development no-go pending independent scientific review and a valid independent reporter-system panel.** No claim of Zone 2 quality or publishability is made. No journal recommendation, submission, payment, global scientific database write, external message or public release occurred.

## Verification and reproducibility

All nine scientific payload manifests were revalidated by actual size and SHA-256. Publisher and GEO DNA1/DNA2/RNA1/RNA2 counts agree across all four promoter tables to floating-point precision (maximum relative discrepancy <1.7e-16). Every saved prediction MSE was independently recomputed. The original code freeze and all old frozen-plan hashes passed. A deterministic replay reproduced every metric and the exact prediction CSV bytes; it is labeled replay, not new validation.

Current cgroup peak memory was {int(v['resource_cgroup']['files']['memory.peak'])/1024**2:.1f} MiB, below the 2-GiB supervisor limit; OOM events were zero. All runtimes inherited the verified worker cgroup, with two-thread limits. Replay explicitly invoked the CPU resource guard. No GPU, package installation or raw sequencing download was used. HTTP concurrency never exceeded two.

See `result_bundle/README.md` for exact replay command, hashes and artifact paths. Primary records: `plan.json`, `samples.csv`, `freeze-hashes.json`, `code-freeze.json`, `complete-trial-ledger.json`, `results.json`, `validation.json`, `design-alternatives.json`, `sequence-locus-audit.json`, `post-outcome-diagnostics.json` and `intake-manifests/`. Failed attempts are preserved in the complete ledger and metadata failure records.
'''
for p in [PROJECT/'FINAL_REPORT.md',WORKER/'FINAL_REPORT.md']:p.write_text(report)
# Compatibility view does not alter the original once-only scientific result.
protocol_results=dict(stage='exploratory_pilot',independent_unit='molecule',unit_description='DNA locus, not small molecule',metrics=dict(n_test=primary['n'],baseline_mse=primary['metrics'][b]['mse'],orientation_mse=primary['metrics'][o]['mse'],relative_improvement=primary['relative_mse_improvement']),baselines={n:dict(mse=primary['metrics'][n]['mse']) for n in plan['baselines']},trials_run=11,limitations=r['limitations'],run=r['run'],scientific_results_sha256=sha(PROJECT/'results.json'))
protocol_results['run']={**r['run'],'code_revision':'sha256:'+sha(CODE/'run.py')}
atomic(PROJECT/'protocol-results.json',protocol_results)
atomic(PROJECT/'protocol-split-audit.json',audit(PROJECT/'samples.csv',independent_unit='molecule',group_columns=plan['group_columns'],strategy='group',project_root=PROJECT))
def rec(n):return dict(path=n,sha256=sha(PROJECT/n))
atomic(PROJECT/'project.json',dict(schema_version='openlabs.project.v1',project_id=PROJECT.name,domain='biology',lab_id='biomed',status='active',objective=plan['research_question'],protocol=dict(id='biomed-public-data-pilot',primary_skill='biomed-research-loop'),workstreams=[dict(workstream_id='promoter-portability',state_path='research_state.json',startup='paused',agent_role='researcher',session_mode='fresh',objective=plan['research_question'],resources=dict(cpu_threads=2,memory_mib=1536,scratch_mib=2048))]))
atomic(PROJECT/'research_state.json',dict(schema_version='openlabs.biomed_pilot_state.v1',project_id=PROJECT.name,workstream_id='promoter-portability',status='completed',paper_candidate=False,research_question=plan['research_question'],independent_unit='molecule',unit_description='DNA locus, not small molecule',next_experiment='Independent scientific review and valid paired promoter cross-system data; preserve consumed holdout and do not tune on it.',plan=rec('plan.json'),environment=rec('environment.json'),datasets=manifests,split_audit=rec('protocol-split-audit.json'),results=rec('protocol-results.json'),evidence=[rec(n) for n in ['results.json','validation.json','design-alternatives.json','FINAL_REPORT.md','complete-trial-ledger.json']],claims=[dict(status='provisional',text='Conditional within-study context transfer improves on activity baseline; proximal-only and independent-system generalization remain unestablished.')],live_worker=False))
errors=validate(PROJECT/'project.json',PROJECT/'research_state.json',mode='commit');atomic(PROJECT/'protocol-validation.json',dict(valid=not errors,errors=errors,scope='bookkeeping/provenance only, not biological adequacy, novelty, independent replication or publication readiness'));assert not errors,errors
# Final locks include added reproduction/validation/package code; prospective lock remains immutable.
atomic(PROJECT/'code-lock.json',{p.name:sha(p) for p in sorted(CODE.glob('*.py'))})
artifacts=[]
for p in sorted(ART.rglob('*')):
 if not p.is_file() or p.is_symlink() or '/replays/' in str(p) or '.download-' in p.name:continue
 artifacts.append(dict(path=str(p.relative_to(ART)),bytes=p.stat().st_size,sha256=sha(p)))
assert sum(x['bytes'] for x in artifacts)<2*1024**3
atomic(PROJECT/'artifact-index.json',dict(root=str(ART),files=artifacts,bytes=sum(x['bytes'] for x in artifacts),replay_verification=str(ART/'replays/verification-1/replay-validation.json')))
command='bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/promoter_portability_20261021/reproduce.py --output '+str(ART/'replays/reproduction-2')
important=['FINAL_REPORT.md','plan.json','samples.csv','freeze-hashes.json','code-freeze.json','code-lock.json','environment.json','results.json','validation.json','protocol-validation.json','complete-trial-ledger.json','artifact-index.json','design-alternatives.json']
bundle=dict(schema_version='openlabs.result_bundle.v1',task_id='promoter-portability-20261021',lab_id='biomed',domain='biology',status='needs_replan',paper_candidate=False,independent_study_validation=False,summary='Completed frozen within-QUASARR context directionality stress test; 150 loci123groups,20.74% MSE improvement vs selected activity baseline. Proximal-only CI crosses zero; direct source identity beats learned model. Independent reporter-system portability remains open.',artifacts=[dict(artifact_id=n,uri=(PROJECT/n).as_uri(),sha256=sha(PROJECT/n),kind='evidence') for n in important],reproduction_command=command)
atomic(PROJECT/'result-bundle.json',bundle)
for root in [PROJECT/'result_bundle',ART/'result_bundle']:
 root.mkdir(exist_ok=True)
 (root/'README.md').write_text('# Frozen promoter portability result bundle\n\n'+bundle['summary']+'\n\nNot independent replication. paper_candidate=false. No external release.\n\nRun from /home/biostar/work/openlabs; use a new --output directory for each replay. This reuses consumed labels and supplies no new evidence.\n\n```bash\n'+command+'\n```\n\nEnvironment: labs/biomed/uv.lock SHA256 '+sha(CODE.parents[1]/'uv.lock')+'; exact installed versions in environment.json. Payloads stay in '+str(ART)+'/intakes.\n\nEvidence hashes (SHA-256):\n\n'+''.join(f'* `{n}`: `{sha(PROJECT/n)}`\n' for n in important)+'\nBundle JSON: '+str(PROJECT/'result-bundle.json')+'\n')
(CODE/'README.md').write_text('# Promoter portability study\n\nProspective fallback context-transfer study. See '+str(PROJECT/'FINAL_REPORT.md')+'.\n\nOriginal order: audit.py, metadata_routes.py, intake.py, geo_intake.py, workbook_schema.py, design.py, identity.py, novelty.py, bose_audit.py, context_feasibility.py, freeze.py; write code-freeze.json before run.py select; run.py confirm once; routes_summary.py; validate.py; reproduce.py; package.py. All code ran in the verified worker cgroup with two-thread limits. Frozen originals cannot be rerun in place.\n\nExact safe numerical replay:\n\n```bash\n'+command+'\n```\n')
status('completed',dict(primary_relative_mse_improvement=primary['relative_mse_improvement'],n_test=150,groups=123,independent_study_validation=False,proximal_only='inconclusive',protocol_valid=True,replay='exact_metrics_and_prediction_bytes',report=str(WORKER/'FINAL_REPORT.md')),'No active work. Independent cross-system study needs new auditable data and scientific review.',live=False)
print(json.dumps(dict(report=str(WORKER/'FINAL_REPORT.md'),protocol_valid=True,bundle=str(PROJECT/'result-bundle.json'),live_worker=False),indent=2))
