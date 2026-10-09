"""Public pure verification helpers; historical drivers and data are excluded."""
import csv, math
from pathlib import Path

def notch(path,band=(2.3,3.6)):
    with Path(path).open(encoding='utf-8') as handle: rows=list(csv.DictReader(handle))
    points=[]
    for row in rows:
        f=float(row['frequency_ghz']);s=complex(float(row['s2_1_real']),float(row['s2_1_imag']))
        if not all(math.isfinite(v) for v in (f,s.real,s.imag)) or abs(s)==0:
            raise ValueError('non-finite or exact-zero exported sample')
        points.append((f,20*math.log10(abs(s))))
    if not points or any(b[0]<=a[0] for a,b in zip(points,points[1:])):
        raise ValueError('frequency samples must be strictly increasing')
    if points[0][0]>band[0] or points[-1][0]<band[1]:raise ValueError('notch search window is not covered')
    inside=[p for p in points if band[0]<=p[0]<=band[1]]
    if len(inside)<100:raise ValueError('notch window is undersampled')
    i=min(range(len(inside)),key=lambda j:inside[j][1])
    if i<2 or i>len(inside)-3:raise ValueError('edge minimum is not a resolved resonance')
    f,depth=inside[i]
    if depth>=-20 or min(inside[0][1],inside[-1][1])-depth<10:
        raise ValueError('no deep, interior transmission notch with 10 dB endpoint prominence')
    step=max(inside[i][0]-inside[i-1][0],inside[i+1][0]-inside[i][0])
    return dict(frequency_ghz=f,depth_db=depth,samples=len(points),window_samples=len(inside),
        local_grid_step_ghz=step,frequency_estimator='interior sampled S21 minimum; no sub-grid accuracy claimed')

def compare(measured,oracle):
    if len(measured)!=2 or len(oracle['points'])!=2:raise ValueError('T2 requires two length points')
    expected=oracle['points'];checks=[]
    for actual,predicted in zip(measured,expected):
        error=abs(actual['frequency_ghz']/predicted['corrected_quarter_wave_ghz']-1)
        checks.append(dict(**actual,**predicted,relative_frequency_error=error,
            frequency_gate=error<=oracle['max_relative_frequency_error']))
    ratio=measured[1]['frequency_ghz']/measured[0]['frequency_ghz']
    prediction=expected[1]['corrected_quarter_wave_ghz']/expected[0]['corrected_quarter_wave_ghz']
    ratio_error=abs(ratio/prediction-1)
    down=expected[1]['length_mm']>expected[0]['length_mm'] and measured[1]['frequency_ghz']<measured[0]['frequency_ghz']
    passed=down and all(r['frequency_gate'] for r in checks) and ratio_error<=oracle['max_relative_ratio_error']
    return dict(status='passed' if passed else 'failed',points=checks,length_increase_frequency_decrease=down,
        measured_frequency_ratio=ratio,analytic_frequency_ratio=prediction,relative_ratio_error=ratio_error,
        ratio_gate=ratio_error<=oracle['max_relative_ratio_error'])
