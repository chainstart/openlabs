"""Summarize frozen descriptive diagnostics without adding tests or model fits."""
import json
import pandas as pd
from intake import ART, DATA, atomic, now


def main():
    marker = json.loads((DATA / 'screen_confirmation_opened.json').read_text())
    if marker['status'] != 'evaluated once':
        raise RuntimeError('wait for complete one-time evaluation')
    result = {'at_utc': now(), 'scope': 'post-evaluation descriptive summary only; no new hypothesis tests',
              'independent_donors': 2, 'temporal': {}, 'quality': {}}
    for label, stem in [('shared_reference', 'screen_temporal_residual_audit'),
                        ('independent_reference', 'screen_temporal_independent_reference_audit'),
                        ('raw_response', 'screen_temporal_raw_response_audit')]:
        frame = pd.read_csv(ART / (stem + '.csv'))
        product = next(c for c in frame if c.endswith('product'))
        result['temporal'][label] = {'within_donor': {
            d: {'targets': len(g), 'mean_product': float(g[product].mean()),
                'median_cosine': float(g.cosine.median()), 'positive_products': int((g[product] > 0).sum())}
            for d, g in frame.groupby('donor_id')}}
        name = 'screen_temporal_crossdonor_audit.csv' if label == 'shared_reference' else f'screen_temporal_{label}_crossdonor.csv'
        cross = pd.read_csv(ART / name)
        result['temporal'][label]['cross_donor'] = {
            'targets': len(cross), 'mean_product': float(cross.cross_donor_guide_product.mean()),
            'median_cosine': float(cross.cosine.median()),
            'positive_products': int((cross.cross_donor_guide_product > 0).sum()),
            'limitation': 'one crossed pair of donors/guides; targets are not additional donors'}
    for path in sorted(ART.glob('screen_*_diagnostics.csv')):
        frame = pd.read_csv(path)
        strata = next(c for c in frame if c not in ['model', 'donor_id', 'mean', 'count'])
        result['quality'][path.name] = {
            'stratum': strata,
            'fixed_primary_pair': frame[frame.model.isin(['M2_linear', 'M5_shrunk_potency_ratio'])].to_dict('records'),
            'limitation': 'descriptive, no confirmation exclusions or subgroup significance selection'}
    atomic(DATA / 'screen_descriptive_diagnostics.json', result)
    print(json.dumps(result['temporal'], indent=2))


if __name__ == '__main__':
    main()
