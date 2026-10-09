"""The T3 independent export checker must catch transposition and bad grids."""
import csv
from pathlib import Path
import runpy
import pytest

ROOT=Path(__file__).resolve().parents[3]
CHECK=runpy.run_path(str(ROOT/'scripts/validation/verify_fourport_results.py'))['crosscheck_csv']
from cst_lab.contracts.touchstone import Touchstone

def fixture(tmp_path, change=None):
    data=Touchstone(tmp_path/'matrix.s4p',4,(2.4e9,3e9,4.3e9),
        {(o,i):tuple(complex(o/10+k/100,i/10) for k in range(3)) for o in range(1,5) for i in range(1,5)})
    rows=[]
    for k,f in enumerate(data.frequencies_hz):
        row={'frequency_ghz':f/1e9}
        for (o,i),s in data.s.items():
            row[f's{o}_{i}_real']=s[k].real
            row[f's{o}_{i}_imag']=s[k].imag
        rows.append(row)
    if change:change(rows)
    path=tmp_path/'curves.csv'
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    return path,data

def test_all_sixteen_distinct_complex_columns(tmp_path):
    report=CHECK(*fixture(tmp_path))
    assert report['matrix_columns']==16 and report['max_complex_abs_error']==0

def test_rejects_transposed_off_diagonal(tmp_path):
    def change(rows):
        rows[1]['s4_3_real'],rows[1]['s3_4_real']=rows[1]['s3_4_real'],rows[1]['s4_3_real']
    with pytest.raises(ValueError,match='complex matrix evidence differs'):
        CHECK(*fixture(tmp_path,change))

@pytest.mark.parametrize('frequency',[float('nan'),3.01])
def test_rejects_invalid_frequency_grid(tmp_path,frequency):
    with pytest.raises(ValueError,match='frequency grids differ'):
        CHECK(*fixture(tmp_path,lambda rows:rows[1].update(frequency_ghz=frequency)))
