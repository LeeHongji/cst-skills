"""Public pure verification helpers; historical drivers and data are excluded."""
import csv, math
from pathlib import Path

def crosscheck_csv(path, data):
    with Path(path).open(encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != len(data) or data.ports != 4 or len(data.s) != 16:
        raise ValueError('T3 requires all 16 matrix columns and equal sample counts')
    maximum = 0.
    for i, row in enumerate(rows):
        frequency = float(row['frequency_ghz'])
        if not math.isfinite(frequency) or abs(frequency-data.frequencies_hz[i]/1e9) > 1e-10:
            raise ValueError('CSV and S4P frequency grids differ')
        for (out, inp), values in data.s.items():
            value = complex(float(row[f's{out}_{inp}_real']), float(row[f's{out}_{inp}_imag']))
            if not math.isfinite(abs(value)):
                raise ValueError('Non-finite complex matrix evidence')
            maximum = max(maximum, abs(value-values[i]))
    if maximum > 1e-9:
        raise ValueError('CSV and S4P complex matrix evidence differs')
    return dict(status='pass', matrix_columns=16, samples=len(rows), max_complex_abs_error=maximum, tolerance=1e-9)
