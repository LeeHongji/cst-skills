"""Offline review plots from retained Touchstone; never claims new acceptance."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'MCP/CST-Lab/src'))
from cst_lab.contracts.touchstone import read_touchstone,curve


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--label',default='Retained exported evidence');args=p.parse_args()
    if args.output.exists():raise FileExistsError('Use a new derived review directory')
    data=read_touchstone(args.source);args.output.mkdir(parents=True)
    frequency=[f/1e9 for f in data.frequencies_hz]
    keys=[(1,1),(2,1)] if data.ports>=2 else [(1,1)]
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    columns={'frequency_ghz':frequency}
    for key in keys:
        label=f'S{key[0]}{key[1]}'
        columns[label+'_db']=curve(data,*key,'db');columns[label+'_deg']=curve(data,*key,'deg')
        axes[0].plot(frequency,columns[label+'_db'],label=label,lw=1.6)
        axes[1].plot(frequency,columns[label+'_deg'],label=label,lw=1.6)
    for ax in axes:
        ax.set_xlabel('Frequency (GHz)');ax.grid(alpha=.2);ax.legend(frameon=False)
    axes[0].set_ylabel('Magnitude (dB)');axes[1].set_ylabel('Unwrapped phase (deg)')
    fig.suptitle(args.label);fig.savefig(args.output/'response.png',dpi=180);plt.close(fig)
    with (args.output/'curves.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.writer(handle);writer.writerow(columns);writer.writerows(zip(*columns.values()))
    (args.output/'provenance.json').write_text(json.dumps(dict(source_name=args.source.name,
        source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),samples=len(data),
        claim='Derived offline visualization; evaluate gates through cst_run, not visual inspection alone.'),indent=2)+'\n')


if __name__=='__main__':main()
