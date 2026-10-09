"""Verify the exported review uses the forward, complex-valued S21 column."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_offline_plot_keeps_port_order_units_and_provenance(tmp_path):
    source=tmp_path/'nonreciprocal.s2p'
    source.write_text('# GHz S RI R 50\n1 .1 0 .5 0 .9 0 .2 0\n2 .1 0 .25 0 .8 0 .2 0\n')
    output=tmp_path/'review'
    command=[sys.executable,str(ROOT/'scripts/plot-review.py'),'--source',str(source),'--output',str(output)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    rows=list(csv.DictReader((output/'curves.csv').open()))
    assert [float(r['frequency_ghz']) for r in rows]==[1.,2.]
    assert [float(r['S21_db']) for r in rows]==pytest.approx([-6.020599913,-12.041199826])
    assert [float(r['S21_deg']) for r in rows]==[0.,0.]
    receipt=json.loads((output/'provenance.json').read_text())
    assert receipt['source_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
    assert receipt['samples']==2 and (output/'response.png').read_bytes().startswith(b'\x89PNG')
    saved=(output/'curves.csv').read_bytes()
    assert subprocess.run(command,capture_output=True).returncode!=0
    assert (output/'curves.csv').read_bytes()==saved
