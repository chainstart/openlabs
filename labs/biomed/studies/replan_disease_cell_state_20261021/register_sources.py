from common import *
entries=[]
for acc,filename,doi,release in [
 ('GSE184316','GSE184316_fHP_Txome_FPKM_RNAseq.csv.gz','10.1164/rccm.202103-0569OC','2023-08-24'),
 ('GSE199949','GSE199949_raw.counts.txt.gz','10.1136/bmjresp-2022-001391','2025-02-03'),
 ('GSE150910','GSE150910_gene-level_count_file.csv.gz','10.1164/rccm.202001-0134OC','2022-05-18')]:
 entries.append(dict(source_id=acc,provider='NCBI GEO',official_record='https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc='+acc,source_url=f'https://ftp.ncbi.nlm.nih.gov/geo/series/{acc[:-3]}nnn/{acc}/suppl/{filename}',series_last_update_date=release,release_evidence_sha256=sha(ART/'payload'/f'{acc}_series_matrix.txt.gz'),terms_url='https://www.ncbi.nlm.nih.gov/home/about/policies/',reuse_basis='Public deidentified author-deposited processed data for attributed internal research; no redistribution or blanket ethics-exemption claim; no specific accession restriction stated in inspected record',citation=doi,independent_unit='lung donor',allowed_hosts=['ftp.ncbi.nlm.nih.gov','www.ncbi.nlm.nih.gov'],manifest=str(ART/'manifest.jsonl'),metadata_corrections=str(DATA/'intake_citation_correction.json') if acc=='GSE199949' else None))
atomic(DATA/'source_registry_local.json',dict(at=now(),scope='This study only; shared registry not edited',sources=entries,dependency_annotation=json.loads((DATA/'annotation_readonly_reference.json').read_text()),source_design_audit=str(DATA/'source_design_review.json'),independence_audit=str(DATA/'split_and_independence_audit.json')))
print('Registered3officialbulk sources locally')
