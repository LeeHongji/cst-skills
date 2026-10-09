"""Public pure verification helpers; historical drivers and data are excluded."""
import math

def analytic(length):
    # Schneider effective permittivity, Qucs technical note eq. 11.14.
    # Use its simple static approximation explicitly; do not fit CST results.
    er=3.55;h=.813;w=1.8332;u=w/h
    ee=(er+1)/2+(er-1)/2/math.sqrt(1+10/u)
    # Hammerstad open extension, Qucs eq. 11.191 (not a patch's two open ends).
    extension=h*.102*(u+.106)/(u+.264)*(1.166+(er+1)/er*(.9+math.log(u+2.475)))
    return dict(length_mm=length,epsilon_effective=ee,open_extension_mm=extension,
        ideal_quarter_wave_ghz=299.792458/(4*math.sqrt(ee)*length),
        corrected_quarter_wave_ghz=299.792458/(4*math.sqrt(ee)*(length+extension)))
