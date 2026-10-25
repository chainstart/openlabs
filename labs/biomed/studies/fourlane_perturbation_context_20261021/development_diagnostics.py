"""Descriptive development-only signal support; no alternative model fitting."""
import json
import numpy as np
import pandas as pd
from intake import ART, DATA, atomic, now


def main():
    meta = pd.read_csv(ART / 'screen_development_samples.csv')
    effects = np.load(ART / 'screen_development_effects.npz')['Y']
    rows = []
    for (target, condition), g in meta.groupby(['target', 'culture_condition']):
        if len(g) != 2 or g.donor_id.nunique() != 2:
            raise ValueError('unexpected development pair')
        a, b = effects[g.index.to_numpy()]
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        rows.append({'target': target, 'condition': condition,
                     'cross_product': float(np.mean(a * b)),
                     'mean_squared_response': float(np.mean((a*a + b*b)/2)),
                     'cosine': float(a @ b / denom) if denom else None})
    frame = pd.DataFrame(rows)
    frame.to_csv(ART / 'screen_development_signal_support.csv', index=False)
    summary = {'at_utc': now(), 'scope': 'development-only descriptive diagnostic after model freeze; no tuning',
               'n_donors': 2, 'by_condition': {},
               'limitations': 'one donor pair, same guide, no independent validation; low concordance cannot separate donor biology, batch, control noise and sampling noise'}
    for c, g in frame.groupby('condition'):
        summary['by_condition'][c] = {
            'n_targets': len(g), 'mean_cross_product': float(g.cross_product.mean()),
            'mean_squared_response': float(g.mean_squared_response.mean()),
            'median_cosine': float(g.cosine.median()),
            'positive_cross_products': int((g.cross_product > 0).sum())}
    atomic(DATA / 'screen_development_signal_support.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
