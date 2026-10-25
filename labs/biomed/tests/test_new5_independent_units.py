import csv
import pytest
from tools.split_audit import audit


@pytest.mark.parametrize('unit,column', [('patient','donor_id'),('protein_position','protein_position')])
def test_repeated_measurements_cannot_cross_partition(tmp_path,unit,column):
    path=tmp_path/'samples.csv'
    rows=[['one','train','group-a'],['two','validation','group-b'],['three','test','group-c'],['four','test','group-a']]
    with path.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['sample_id','split',column]);w.writerows(rows)
    result=audit(path,independent_unit=unit,strategy='group',group_columns=[column])
    assert not result['valid']
    assert any('cross-split' in error for error in result['errors'])
    rows[-1][-1]='group-d'
    with path.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['sample_id','split',column]);w.writerows(rows)
    assert audit(path,independent_unit=unit,strategy='group',group_columns=[column])['valid']
