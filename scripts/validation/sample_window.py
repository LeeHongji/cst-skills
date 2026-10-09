"""Retained float32 band-edge verification helper; no live CST reader."""
import numpy as np

def sample_window(
    frequencies: np.ndarray,
    values_db: np.ndarray,
    lower: float,
    upper: float,
) -> tuple[np.ndarray, np.ndarray]:
    # Match cst_metrics' default 1 ppm endpoint tolerance: CST stores some
    # frequency grids as float32. A nominal 12.4 GHz may read as 12.3999996.
    tolerance = 1e-6 * max(1.0, abs(lower), abs(upper), abs(upper-lower))
    if frequencies[0] > lower+tolerance or frequencies[-1] < upper-tolerance:
        raise ValueError(
            f"Result coverage {frequencies[0]:g}-{frequencies[-1]:g} GHz does not "
            f"contain {lower:g}-{upper:g} GHz"
        )
    mask = (frequencies >= lower) & (frequencies <= upper)
    interior_f = frequencies[mask]
    interior_v = values_db[mask]
    edge_f = np.asarray([lower, upper], dtype=float)
    edge_v = np.interp(edge_f, frequencies, values_db)
    combined_f = np.concatenate((edge_f[:1], interior_f, edge_f[1:]))
    combined_v = np.concatenate((edge_v[:1], interior_v, edge_v[1:]))
    unique_f, indices = np.unique(combined_f, return_index=True)
    return unique_f, combined_v[indices]
