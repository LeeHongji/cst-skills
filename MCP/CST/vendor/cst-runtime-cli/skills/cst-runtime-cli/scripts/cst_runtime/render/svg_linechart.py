from __future__ import annotations

import math
from html import escape
from typing import Any

from ..core.utils import safe_log_db

# ── SVG Constants ──

_SVG_W = 960
_SVG_H = 540
_SVG_MARGIN: dict[str, int] = dict(t=50, r=30, b=60, l=70)
_COLORS = ["#0d9488", "#d97706", "#7c3aed", "#dc2626", "#059669", "#0891b2", "#be185d", "#65a30d"]
_DARK_BG = "#18181b"
_DARK_TEXT = "#f4f4f5"
_LIGHT_BG = "#ffffff"
_LIGHT_TEXT = "#18181b"

# ── SVG inline style for chart elements ──

_CHART_STYLE = """
.chart-bg{fill:var(--chart-bg,#fff)}
.chart-grid-line{stroke:var(--chart-grid,#e4e4e7);stroke-width:.5;stroke-dasharray:3,3}
.chart-label{fill:var(--chart-label,#71717a);font-family:system-ui,-apple-system,sans-serif;font-size:11px}
.chart-axis-title{fill:var(--chart-title,#18181b);font-family:system-ui,-apple-system,sans-serif;font-size:13px;font-weight:500}
.chart-plot-title{fill:var(--chart-title,#18181b);font-family:system-ui,-apple-system,sans-serif;font-size:15px;font-weight:600}
.chart-legend-text{fill:var(--chart-legend,#18181b);font-family:system-ui,-apple-system,sans-serif;font-size:12px;font-weight:500}
.chart-line{stroke-width:2.2;stroke-linejoin:round;stroke-linecap:round;fill:none}
.chart-min-marker{cursor:pointer;transition:r .2s cubic-bezier(.16,1,.3,1)}
.chart-min-marker:hover{r:6}
@keyframes chartDraw{0%{stroke-dashoffset:10000;opacity:0}1%{opacity:1}to{stroke-dashoffset:0;opacity:1}}
.chart-anim-line{stroke-dasharray:10000;stroke-dashoffset:10000;animation:chartDraw 1.5s cubic-bezier(.16,1,.3,1) forwards}
"""


# ── SVG axes ──

def _svg_axes(x_min: float, x_max: float, y_min: float, y_max: float, xlabel: str, ylabel: str, dark: bool) -> str:
    m = _SVG_MARGIN
    pw = _SVG_W - m["l"] - m["r"]
    ph = _SVG_H - m["t"] - m["b"]
    bg = _DARK_BG if dark else _LIGHT_BG
    tc = _DARK_TEXT if dark else _LIGHT_TEXT
    gc = "#3f3f46" if dark else "#e4e4e7"
    ac = "#71717a" if dark else "#a1a1aa"

    x_pad = (x_max - x_min) * 0.03 or 1
    y_pad = (y_max - y_min) * 0.05 or 1
    x_min -= x_pad
    x_max += x_pad
    y_min -= y_pad
    y_max += y_pad

    def sx(v: float) -> float: return m["l"] + (v - x_min) / (x_max - x_min) * pw
    def sy(v: float) -> float: return m["t"] + ph - (v - y_min) / (y_max - y_min) * ph

    lines = [f'<rect x="0" y="0" width="{_SVG_W}" height="{_SVG_H}" fill="{bg}" rx="6"/>']
    lines.append(f'<text x="{_SVG_W/2}" y="24" text-anchor="middle" class="chart-plot-title">{escape(xlabel)} vs {escape(ylabel)}</text>')

    # Grid + Y axis labels
    y_steps = 5
    for i in range(y_steps + 1):
        v = y_min + (y_max - y_min) * i / y_steps
        yy = sy(v)
        lines.append(f'<line x1="{m["l"]}" y1="{yy}" x2="{m["l"]+pw}" y2="{yy}" class="chart-grid-line"/>')
        lines.append(f'<text x="{m["l"]-8}" y="{yy+4}" text-anchor="end" class="chart-label">{v:.2f}</text>')
    # Grid + X axis labels
    x_steps = 8
    for i in range(x_steps + 1):
        v = x_min + (x_max - x_min) * i / x_steps
        xx = sx(v)
        lines.append(f'<line x1="{xx}" y1="{m["t"]}" x2="{xx}" y2="{m["t"]+ph}" class="chart-grid-line"/>')
        lines.append(f'<text x="{xx}" y="{m["t"]+ph+16}" text-anchor="middle" class="chart-label">{v:.2f}</text>')
    # Axis labels
    lines.append(f'<text x="{m["l"]+pw/2}" y="{_SVG_H-6}" text-anchor="middle" class="chart-axis-title">{escape(xlabel)}</text>')
    lines.append(f'<text x="18" y="{m["t"]+ph/2}" text-anchor="middle" class="chart-axis-title" transform="rotate(-90,18,{m["t"]+ph/2})">{escape(ylabel)}</text>')

    return "\n".join(lines), x_min, x_max, y_min, y_max


# ── SVG line chart ──

def svg_linechart(traces: list[dict[str, Any]], xlabel: str = "Frequency (GHz)", ylabel: str = "S11 (dB)", dark: bool = False, stagger_ms: int = 0) -> str:
    all_x = [v for t in traces for v in t.get("x", [])]
    all_y = [v for t in traces for v in t.get("y", [])]
    if not all_x or not all_y:
        return f'<svg viewBox="0 0 {_SVG_W} {_SVG_H}" width="{_SVG_W}" height="{_SVG_H}"><text x="20" y="40" class="chart-label">无数据</text></svg>'

    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    m = _SVG_MARGIN
    pw = _SVG_W - m["l"] - m["r"]
    ph = _SVG_H - m["t"] - m["b"]
    x_pad = (x_max - x_min) * 0.03 or 1
    y_pad = (y_max - y_min) * 0.05 or 1
    x_min -= x_pad; x_max += x_pad
    y_min -= y_pad; y_max += y_pad

    def sx(v): return m["l"] + (v - x_min) / (x_max - x_min) * pw
    def sy(v): return m["t"] + ph - (v - y_min) / (y_max - y_min) * ph

    axes_svg, _, _, _, _ = _svg_axes(all_x[0], all_x[-1] if len(all_x) > 1 else all_x[0] + 1, y_min + y_pad, y_max - y_pad, xlabel, ylabel, dark)

    defs_parts = []
    for idx in range(len(traces)):
        color = _COLORS[idx % len(_COLORS)]
        grad_id = f"areaGrad{idx}"
        defs_parts.append(
            f'<linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity=".12"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity=".02"/>'
            f'</linearGradient>'
        )

    parts = [
        f'<svg viewBox="0 0 {_SVG_W} {_SVG_H}" width="{_SVG_W}" height="{_SVG_H}" xmlns="http://www.w3.org/2000/svg">',
        f'<style>{_CHART_STYLE}</style>',
        f'<defs>{"".join(defs_parts)}</defs>',
        axes_svg,
    ]
    tc = _DARK_TEXT if dark else _LIGHT_TEXT

    for idx, trace in enumerate(traces):
        xs = trace.get("x", [])
        ys = trace.get("y", [])
        if not xs or not ys:
            continue
        color = _COLORS[idx % len(_COLORS)]
        label = trace.get("name", f"Trace {idx+1}")
        grad_id = f"areaGrad{idx}"

        # Area fill (gradient)
        pts_fill = " ".join(f"{sx(x)},{sy(y)}" for x, y in zip(xs, ys) if not (math.isnan(y) or math.isinf(y)))
        first_x, last_x = sx(xs[0]), sx(xs[-1])
        baseline_y = sy(y_min + y_pad)
        parts.append(
            f'<polygon points="{pts_fill} {last_x},{baseline_y} {first_x},{baseline_y}" '
            f'fill="url(#{grad_id})" stroke="none"/>'
        )

        # Line (with draw animation, optional stagger per trace)
        pts = " ".join(f"{sx(x)},{sy(y)}" for x, y in zip(xs, ys) if not (math.isnan(y) or math.isinf(y)))
        anim_class = "chart-line chart-anim-line"
        if stagger_ms > 0:
            delay = f' style="animation-delay:{idx * stagger_ms}ms;opacity:0"'
        else:
            delay = ""
        parts.append(f'<polyline points="{pts}" class="{anim_class}" stroke="{color}"{delay}/>')

        # Min point marker
        valid_pairs = [(x, y) for x, y in zip(xs, ys) if not (math.isnan(y) or math.isinf(y))]
        if valid_pairs:
            min_pair = min(valid_pairs, key=lambda p: p[1])
            mx, my = sx(min_pair[0]), sy(min_pair[1])
            parts.append(
                f'<circle cx="{mx}" cy="{my}" r="4.5" fill="{color}" stroke="{tc}" stroke-width="1.5" class="chart-min-marker">'
                f'<title>{label} min: {min_pair[1]:.2f} dB at {min_pair[0]:.3f} GHz</title>'
                f'</circle>'
            )
            # Value annotation next to min point
            parts.append(
                f'<text x="{mx+10}" y="{my+4}" fill="{color}" font-family="system-ui,-apple-system,sans-serif" font-size="10" font-weight="600">'
                f'{min_pair[1]:.1f} dB</text>'
            )

        # Legend
        ly = m["t"] + 20 + idx * 24
        parts.append(f'<line x1="{m["l"]+pw-130}" y1="{ly}" x2="{m["l"]+pw-106}" y2="{ly}" stroke="{color}" stroke-width="2.2" stroke-linecap="round"/>')
        parts.append(f'<circle cx="{m["l"]+pw-118}" cy="{ly}" r="3.5" fill="{color}"/>')
        parts.append(f'<text x="{m["l"]+pw-100}" y="{ly+4}" class="chart-legend-text">{escape(label)}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


# ── Utilities ──

def complex_components(value: Any) -> tuple[float, float]:
    if isinstance(value, dict):
        return float(value.get("real", 0.0)), float(value.get("imag", 0.0))
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return float(value[0]), float(value[1])
    if isinstance(value, (int, float)):
        return float(value), 0.0
    return 0.0, 0.0


def scalar_series(values: list[Any]) -> tuple[list[float], str]:
    if not values:
        return [], "value"
    if any(isinstance(value, dict) and "real" in value and "imag" in value for value in values):
        return [safe_log_db(math.hypot(*complex_components(value))) for value in values], "magnitude_db"
    return [float(value) for value in values], "value"


# ── Mini SVG trend chart ──

def svg_mini_trend(points: list[float], width: int = 320, height: int = 100, label: str = "", show_axes: bool = False) -> str:
    if not points:
        return ""
    n = len(points)
    pad = 8
    if show_axes:
        pad = 36  # more margin for axes labels
    pw = width - pad * 2
    ph = height - pad * 2
    y_min = min(points)
    y_max = max(points)
    y_rng = y_max - y_min or 1
    y_min -= y_rng * 0.1
    y_max += y_rng * 0.1

    def sx(i): return pad + i / max(n - 1, 1) * pw
    def sy(v): return pad + ph - (v - y_min) / (y_max - y_min) * ph

    pts = " ".join(f"{sx(i)},{sy(v)}" for i, v in enumerate(points) if not (math.isnan(v) or math.isinf(v)))
    fill_pts = f"{pts} {sx(n-1)},{height - pad} {sx(0)},{height - pad}"

    svg = f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" class="mini-trend">'

    if show_axes:
        # Background
        svg += f'<rect x="0" y="0" width="{width}" height="{height}" fill="transparent" rx="4"/>'
        # Grid lines Y
        y_steps = 4
        for i in range(y_steps + 1):
            v = y_min + (y_max - y_min) * i / y_steps
            yy = sy(v)
            svg += f'<line x1="{pad}" y1="{yy}" x2="{width-pad}" y2="{yy}" stroke="#e4e4e7" stroke-width=".5" stroke-dasharray="2,2"/>'
            svg += f'<text x="{pad-4}" y="{yy+3}" text-anchor="end" fill="#a1a1aa" font-family="system-ui,sans-serif" font-size="8">{v:.1f}</text>'
        # Grid lines X (iteration ticks)
        x_steps = min(n - 1, 6)
        for i in range(x_steps + 1):
            xi = int(round(i * (n - 1) / x_steps))
            xx = sx(xi)
            svg += f'<text x="{xx}" y="{height-2}" text-anchor="middle" fill="#a1a1aa" font-family="system-ui,sans-serif" font-size="8">{xi+1}</text>'
        # Axis labels
        svg += f'<text x="10" y="{pad + ph//2}" text-anchor="middle" fill="#71717a" font-family="system-ui,sans-serif" font-size="8" transform="rotate(-90,10,{pad + ph//2})">S11 dB</text>'
        svg += f'<text x="{pad + pw//2}" y="{height-14}" text-anchor="middle" fill="#71717a" font-family="system-ui,sans-serif" font-size="8">Run</text>'
    else:
        svg += f'<rect x="0" y="0" width="{width}" height="{height}" fill="none"/>'

    svg += f'<polygon points="{fill_pts}" fill="#0d9488" fill-opacity="0.08"/>'
    svg += f'<polyline points="{pts}" fill="none" stroke="#0d9488" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    if n > 0 and points:
        last_val = points[-1]
        svg += f'<circle cx="{sx(n-1)}" cy="{sy(last_val)}" r="3" fill="#0d9488"/>'
    if label:
        svg += f'<text x="{width-pad}" y="{pad+8}" text-anchor="end" fill="#a1a1aa" font-family="system-ui,sans-serif" font-size="9">{escape(label)}</text>'
    svg += "</svg>"
    return svg
