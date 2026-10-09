from __future__ import annotations

from html import escape
from typing import Any

from .svg_linechart import _SVG_MARGIN, _SVG_W, _SVG_H


_HEATMAP_STYLE = """
.heatmap-bg{fill:var(--hm-bg,#fff)}
.heatmap-text{fill:var(--hm-text,#18181b);font-family:system-ui,-apple-system,sans-serif}
.heatmap-label{fill:var(--hm-label,#52525b);font-family:system-ui,-apple-system,sans-serif;font-size:10px}
.heatmap-title{fill:var(--hm-text,#18181b);font-family:system-ui,-apple-system,sans-serif;font-size:14px;font-weight:600}
.heatmap-axis-title{fill:var(--hm-text,#18181b);font-family:system-ui,-apple-system,sans-serif;font-size:12px;font-weight:500}
.heatmap-cb-border{fill:none;stroke:var(--hm-border,#d4d4d8);stroke-width:1;rx:2}
"""


def svg_heatmap(x: list[float], y: list[float], z: list[list[float]], title: str, xlabel: str, ylabel: str, zlabel: str) -> str:
    if not x or not y or not z:
        return f'<svg viewBox="0 0 {_SVG_W} {_SVG_H}" width="{_SVG_W}" height="{_SVG_H}"><text x="20" y="40" class="heatmap-label">无数据</text></svg>'
    nx, ny = len(x), len(y)
    m = _SVG_MARGIN
    pw = _SVG_W - m["l"] - m["r"] - 60
    ph = _SVG_H - m["t"] - m["b"]
    cw, ch = pw / nx, ph / ny

    all_z = [v for row in z for v in row if v is not None]
    if not all_z:
        return f'<svg viewBox="0 0 {_SVG_W} {_SVG_H}" width="{_SVG_W}" height="{_SVG_H}"><text x="20" y="40" class="heatmap-label">无数据</text></svg>'
    z_min, z_max = min(all_z), max(all_z)
    z_rng = z_max - z_min or 1

    def _color(v):
        if v is None:
            return "#e4e4e7"
        t = (v - z_min) / z_rng
        r = int(13 + (217 - 13) * t)
        g = int(148 + (119 - 148) * t)
        b = int(136 + (6 - 136) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    parts = [
        f'<svg viewBox="0 0 {_SVG_W} {_SVG_H}" width="{_SVG_W}" height="{_SVG_H}" xmlns="http://www.w3.org/2000/svg">',
        f'<style>{_HEATMAP_STYLE}</style>',
        f'<rect x="0" y="0" width="{_SVG_W}" height="{_SVG_H}" class="heatmap-bg" rx="6"/>',
        f'<text x="{_SVG_W/2}" y="24" text-anchor="middle" class="heatmap-title">{escape(title)}</text>',
    ]

    for i in range(ny):
        for j in range(nx):
            v = z[i][j] if i < len(z) and j < len(z[i]) else None
            xx = m["l"] + j * cw
            yy = m["t"] + i * ch
            parts.append(f'<rect x="{xx}" y="{yy}" width="{cw}" height="{ch}" fill="{_color(v)}" stroke="none"><title>{xlabel}: {x[j]:.2f}, {ylabel}: {y[i]:.2f}, {zlabel}: {v if v is not None else "N/A"}</title></rect>')

    # Colorbar
    cb_x = m["l"] + pw + 12
    cb_h = ph
    cb_w = 18
    cb_steps = 24
    for i in range(cb_steps):
        t = i / cb_steps
        v = z_min + t * z_rng
        yy = m["t"] + cb_h - (cb_h * t)
        ch_step = cb_h / cb_steps + 1
        parts.append(f'<rect x="{cb_x}" y="{yy}" width="{cb_w}" height="{ch_step}" fill="{_color(v)}" stroke="none"/>')
    parts.append(f'<rect x="{cb_x}" y="{m["t"]}" width="{cb_w}" height="{cb_h}" class="heatmap-cb-border"/>')
    parts.append(f'<text x="{cb_x+cb_w+6}" y="{m["t"]+12}" class="heatmap-label" font-weight="500">{z_max:.2f}</text>')
    parts.append(f'<text x="{cb_x+cb_w+6}" y="{m["t"]+cb_h+4}" class="heatmap-label" font-weight="500">{z_min:.2f}</text>')
    parts.append(f'<text x="{cb_x+cb_w+6}" y="{m["t"]+cb_h/2+4}" class="heatmap-label" transform="rotate(-90,{cb_x+cb_w+6},{m["t"]+cb_h/2+4})">{escape(zlabel)}</text>')

    # Axis labels
    x_step = max(1, nx // 8)
    for j in range(0, nx, x_step):
        parts.append(f'<text x="{m["l"]+j*cw+cw/2}" y="{m["t"]+ph+14}" text-anchor="middle" class="heatmap-label">{x[j]:.1f}</text>')
    y_step = max(1, ny // 6)
    for i in range(0, ny, y_step):
        parts.append(f'<text x="{m["l"]-8}" y="{m["t"]+i*ch+ch/2+3}" text-anchor="end" class="heatmap-label">{y[i]:.1f}</text>')
    parts.append(f'<text x="{m["l"]+pw/2}" y="{_SVG_H-4}" text-anchor="middle" class="heatmap-axis-title">{escape(xlabel)}</text>')
    parts.append(f'<text x="16" y="{m["t"]+ph/2}" text-anchor="middle" class="heatmap-axis-title" transform="rotate(-90,16,{m["t"]+ph/2})">{escape(ylabel)}</text>')

    parts.append("</svg>")
    return "\n".join(parts)
