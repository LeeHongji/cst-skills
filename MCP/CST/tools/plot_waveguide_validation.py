"""Offline native-modal WR-90 curves, analytic phase and cutoff estimate."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'MCP/CST-Lab/src'),str(ROOT/'MCP/CST-CAD/src')]
from cst_lab.contracts import read_touchstone
from verification_waveguide import C0,WIDTH_MM,cutoff_ghz


def main():
    ap=argparse.ArgumentParser();ap.add_argument('run',type=Path);args=ap.parse_args();run=args.run
    report=json.loads((run/'verification-report.json').read_text(encoding='utf-8'))
    fig,axes=plt.subplots(2,2,figsize=(12,8));supplement=[]
    for index,t in enumerate(report['trials']):
        data=read_touchstone(t['touchstone']);f=np.asarray(data.frequencies_hz);s=np.asarray(data.s[(2,1)]);length=t['length_mm']*.001
        label=f"{t['length_mm']:g} mm"+(' independent' if index==2 else '')
        beta=np.sqrt((2*np.pi*f/C0)**2-(np.pi/(WIDTH_MM*.001))**2);theory=-beta*length
        measured=np.unwrap(np.angle(s));measured+=2*np.pi*round((theory[0]-measured[0])/(2*np.pi))
        # Integer 2pi unwrapping only affects plotting; acceptance uses the raw complex ratio.
        err=np.rad2deg(np.angle(s/np.exp(1j*theory)))
        axes[0,0].plot(f/1e9,20*np.log10(np.maximum(np.abs(data.s[(1,1)]),1e-15)),label=label)
        axes[0,1].plot(f/1e9,20*np.log10(abs(s)),label=label)
        axes[1,0].plot(f/1e9,np.rad2deg(measured),label=label)
        if index<2:axes[1,0].plot(f/1e9,np.rad2deg(theory),'k--',alpha=.5,label=f'Theory {length*1000:g} mm')
        axes[1,1].plot(f/1e9,err,label=label)
        # Local linear phase slope at 10 GHz: independent of integer phase branch.
        mask=abs(f-10e9)<=.05e9;slope=np.polyfit(f[mask]-10e9,measured[mask],1)[0];delay=-slope/(2*np.pi)
        inferred=10e9*np.sqrt(1-(length/(C0*delay))**2)
        supplement.append(dict(trial=index,length_mm=length*1000,group_delay_10ghz_ps=delay*1e12,cutoff_inferred_ghz=inferred/1e9,cutoff_theory_ghz=cutoff_ghz(),relative_cutoff_error=abs(inferred/1e9/cutoff_ghz()-1),method='Linear phase slope in 9.95-10.05 GHz; supplemental, not a tuned acceptance threshold'))
    for ax,title,ylabel in zip(axes.flat,['Input reflection','Modal transmission amplitude','Transmission phase vs. analytic TE10','Phase error from raw complex ratio'],['S11 (dB)','S21 (dB)','Phase (deg)','Error (deg)']):
        ax.set(title=title,xlabel='Frequency (GHz)',ylabel=ylabel);ax.grid(alpha=.25);ax.legend(fontsize=8)
    axes[0,1].axhline(0,color='k',ls='--',lw=1)
    fig.suptitle('Classic WR-90 PEC/vacuum waveguide — CST vs. analytic TE10',fontsize=15);fig.tight_layout()
    fig.savefig(run/'waveguide-theory-comparison.png',dpi=160);plt.close(fig)
    (run/'dispersion-estimate.json').write_text(json.dumps(supplement,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(supplement))


if __name__=='__main__':main()
