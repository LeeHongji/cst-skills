from __future__ import annotations

import time
from html import escape


def svg_page(
    title: str,
    body_svg: str,
    dark: bool = False,
    extra_html: str = "",
    metrics_html: str = "",
    subtitle: str = "",
) -> str:
    timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
:root{{
--bg:#f4f5f7;--bg-card:#fff;--bg-raised:#f0f1f3;--bg-code:#f8f9fb;
--text:#161618;--text-secondary:#52525b;--text-muted:#a1a1aa;
--border:#e4e4e7;--border-subtle:#f0f0f2;
--accent:#0d9488;--accent-hover:#0f766e;--accent-subtle:rgba(13,148,136,.08);
--accent-glass:rgba(13,148,136,.04);
--success:#059669;--success-subtle:rgba(5,150,105,.1);
--warning:#d97706;--warning-subtle:rgba(217,119,6,.1);
--danger:#dc2626;--danger-subtle:rgba(220,38,38,.1);
--purple:#7c3aed;--purple-subtle:rgba(124,58,237,.1);
--shadow-sm:0 1px 2px rgba(0,0,0,.04);
--shadow:0 1px 3px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.04);
--shadow-md:0 4px 12px rgba(0,0,0,.05),0 1px 3px rgba(0,0,0,.04);
--shadow-lg:0 8px 24px rgba(0,0,0,.06);
--radius:14px;--radius-sm:8px;--radius-xs:4px;
--transition:all .25s cubic-bezier(.16,1,.3,1);
--font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Oxygen,Ubuntu,Cantarell,"Helvetica Neue",system-ui,sans-serif;
--font-mono:"SF Mono","Fira Code","Cascadia Code","JetBrains Mono",Consolas,monospace;
--tracking-tight:-.02em;
--leading-snug:1.4;
}}
@media(prefers-color-scheme:dark){{
:root{{
--bg:#0c0c0e;--bg-card:#18181b;--bg-raised:#1f1f23;--bg-code:#141416;
--text:#f0f0f2;--text-secondary:#a1a1aa;--text-muted:#71717a;
--border:#27272a;--border-subtle:#1f1f23;
--accent:#2dd4bf;--accent-hover:#5eead4;--accent-subtle:rgba(45,212,191,.12);
--accent-glass:rgba(45,212,191,.06);
--success:#34d399;--success-subtle:rgba(52,211,153,.15);
--warning:#fbbf24;--warning-subtle:rgba(251,191,36,.15);
--danger:#f87171;--danger-subtle:rgba(248,113,113,.15);
--purple:#a78bfa;--purple-subtle:rgba(167,139,250,.15);
--shadow-sm:0 1px 2px rgba(0,0,0,.2);
--shadow:0 1px 3px rgba(0,0,0,.3);
--shadow-md:0 4px 12px rgba(0,0,0,.35);
--shadow-lg:0 8px 24px rgba(0,0,0,.4);
--glass-edge:inset 0 1px 0 rgba(255,255,255,.06);
}}
:root{{
--glass-edge:inset 0 1px 0 rgba(255,255,255,.5);
}}
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--font-sans);background:var(--bg);color:var(--text);line-height:var(--leading-snug);-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}}
.container{{max-width:1280px;margin:0 auto;padding:48px 32px}}
@media(max-width:640px){{.container{{padding:24px 16px}}}}

/* ── Page header (left-aligned, asymmetric) ── */
.page-header{{margin-bottom:48px}}
.page-header h1{{font-size:clamp(1.5rem,2.8vw,2.25rem);font-weight:700;letter-spacing:var(--tracking-tight);line-height:1.15;color:var(--text)}}
.page-header .subtitle{{font-size:15px;color:var(--text-secondary);margin-top:8px;font-weight:400;letter-spacing:-.01em}}
.page-header .timestamp{{font-size:11px;color:var(--text-muted);margin-top:12px;text-transform:uppercase;letter-spacing:.05em;font-family:var(--font-mono)}}

/* ── Metrics grid ── */
.metrics-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:44px}}
.metric-card{{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:20px 22px;transition:var(--transition);position:relative;overflow:hidden;cursor:default;box-shadow:var(--shadow-sm)}}
.metric-card:hover{{transform:translateY(-2px);box-shadow:var(--shadow-md);border-color:var(--accent)}}
.metric-card::after{{content:"";position:absolute;top:0;left:0;right:0;height:3px;background:var(--accent);opacity:0;transition:var(--transition);border-radius:var(--radius) var(--radius) 0 0}}
.metric-card:hover::after{{opacity:1}}
.metric-card:active{{transform:translateY(0);transition:all .1s}}
.metric-label{{font-size:10px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}}
.metric-value{{font-size:clamp(1.25rem,2vw,1.75rem);font-weight:700;color:var(--text);line-height:1.1;letter-spacing:var(--tracking-tight)}}
.metric-value.accent{{color:var(--accent)}}
.metric-value.success{{color:var(--success)}}
.metric-value.warning{{color:var(--warning)}}
.metric-unit{{font-size:13px;font-weight:400;color:var(--text-secondary);margin-left:4px}}

/* ── Liquid glass panels ── */
.chart-section{{margin-bottom:40px}}
.chart-panel{{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:28px;margin-bottom:28px;box-shadow:var(--shadow-sm);transition:var(--transition);box-shadow:var(--glass-edge),var(--shadow-sm)}}
.chart-panel:hover{{box-shadow:var(--glass-edge),var(--shadow)}}
.chart-panel svg{{max-width:100%;height:auto;display:block;margin:0 auto;border-radius:var(--radius-xs)}}
.chart-grid{{display:grid;grid-template-columns:1fr;gap:24px;margin-bottom:28px}}
@media(min-width:1060px){{.chart-grid.cols-2{{grid-template-columns:1fr 1fr}}}}
@media(min-width:1200px){{.chart-grid.cols-3{{grid-template-columns:1fr 1fr 1fr}}}}

/* ── Section titles ── */
.section-header{{display:flex;align-items:baseline;gap:12px;margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid var(--border-subtle)}}
.section-header h2{{font-size:clamp(1rem,1.6vw,1.25rem);font-weight:600;letter-spacing:var(--tracking-tight);color:var(--text);line-height:1.2}}
.section-header .section-count{{font-size:12px;color:var(--text-muted);font-family:var(--font-mono);font-weight:500}}
.section-header .section-badge{{margin-left:auto;font-size:10px;font-weight:600;padding:3px 10px;border-radius:99px;background:var(--accent-subtle);color:var(--accent);text-transform:uppercase;letter-spacing:.04em}}

/* ── Foldable panels ── */
.foldable{{border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-card);overflow:hidden;transition:var(--transition);margin-bottom:16px;box-shadow:var(--shadow-sm)}}
.foldable:hover{{box-shadow:var(--glass-edge),var(--shadow)}}
.foldable summary{{padding:16px 20px;cursor:pointer;user-select:none;display:flex;align-items:center;gap:12px;list-style:none;transition:var(--transition)}}
.foldable summary::-webkit-details-marker{{display:none}}
.foldable summary::before{{content:"▶";font-size:10px;color:var(--text-muted);transition:var(--transition);flex-shrink:0}}
.foldable[open] summary::before{{content:"▼"}}
.foldable summary:hover{{background:var(--accent-glass)}}
.foldable summary:active{{background:var(--accent-subtle)}}
.foldable .foldable-header{{flex:1;min-width:0}}
.foldable .foldable-title{{font-size:14px;font-weight:600;color:var(--text);letter-spacing:-.01em;line-height:1.3}}
.foldable .foldable-meta{{font-size:11px;color:var(--text-muted);margin-top:2px;font-family:var(--font-mono)}}
.foldable .foldable-body{{padding:0 20px 20px}}
.foldable .foldable-tag{{font-size:10px;font-weight:600;padding:2px 8px;border-radius:99px;background:var(--accent-subtle);color:var(--accent);text-transform:uppercase;letter-spacing:.03em;flex-shrink:0}}
.foldable .foldable-tag.success{{background:var(--success-subtle);color:var(--success)}}
.foldable .foldable-tag.warning{{background:var(--warning-subtle);color:var(--warning)}}

/* ── Nested foldable (audit sub-panel) ── */
.foldable-nested{{border:1px solid var(--border-subtle);border-radius:var(--radius-sm);background:var(--bg-raised);overflow:hidden;margin-top:16px}}
.foldable-nested summary{{padding:12px 16px;cursor:pointer;user-select:none;display:flex;align-items:center;gap:8px;font-size:12px;font-weight:500;color:var(--text-secondary);list-style:none;transition:var(--transition);font-family:var(--font-mono)}}
.foldable-nested summary::-webkit-details-marker{{display:none}}
.foldable-nested summary::before{{content:"▸";font-size:10px;color:var(--text-muted);transition:var(--transition)}}
.foldable-nested[open] summary::before{{content:"▾"}}
.foldable-nested summary:hover{{color:var(--text);background:var(--accent-glass)}}
.foldable-nested .foldable-body{{padding:12px 16px}}
.foldable-nested pre{{margin:0;font-size:11px;font-family:var(--font-mono);color:var(--text-secondary);overflow-x:auto;white-space:pre-wrap;max-height:300px;overflow-y:auto;line-height:1.5}}

/* ── Tables ── */
table{{width:100%;border-collapse:separate;border-spacing:0;font-size:13px;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden}}
thead th{{font-weight:600;color:var(--text-secondary);text-transform:uppercase;font-size:10px;letter-spacing:.06em;padding:12px 16px;text-align:left;background:var(--bg-raised);border-bottom:1px solid var(--border)}}
tbody td{{padding:10px 16px;border-bottom:1px solid var(--border-subtle);color:var(--text);transition:var(--transition)}}
tbody tr{{transition:var(--transition)}}
tbody tr:hover td{{background:var(--accent-subtle)}}
tbody tr:last-child td{{border-bottom:none}}
tr.best td{{background:var(--accent-subtle);font-weight:600}}
tr.best td:first-child{{border-left:3px solid var(--accent)}}

/* ── Badges ── */
.badge{{display:inline-flex;align-items:center;padding:2px 10px;border-radius:99px;font-size:10px;font-weight:600;letter-spacing:.02em;text-transform:uppercase}}
.badge-best{{background:var(--success-subtle);color:var(--success)}}
.badge-warn{{background:var(--warning-subtle);color:var(--warning)}}
.badge-accent{{background:var(--accent-subtle);color:var(--accent)}}
.badge-purple{{background:var(--purple-subtle);color:var(--purple)}}

/* ── Step cards (used in timeline and nested audit) ── */
.step-card{{border-left:3px solid var(--border);padding:12px 16px;margin-bottom:8px;background:var(--bg-card);border-radius:0 var(--radius-xs) var(--radius-xs) 0;transition:var(--transition)}}
.step-card:hover{{background:var(--accent-glass)}}
.step-card.step-param{{border-left-color:var(--accent)}}
.step-card.step-sim{{border-left-color:var(--purple)}}
.step-card.step-result{{border-left-color:var(--success)}}
.step-card.step-probe{{border-left-color:var(--warning)}}
.step-card.step-optim{{border-left-color:var(--accent)}}
.step-header{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px}}
.step-idx{{font-size:10px;font-weight:700;color:var(--accent);font-family:var(--font-mono)}}
.step-tool{{font-size:10px;font-weight:600;padding:1px 7px;border-radius:var(--radius-xs);text-transform:lowercase;letter-spacing:.02em}}
.step-tool.param_change,.step-tool.param_define{{background:var(--accent-subtle);color:var(--accent)}}
.step-tool.simulation{{background:var(--purple-subtle);color:var(--purple)}}
.step-tool.result{{background:var(--success-subtle);color:var(--success)}}
.step-tool.probe{{background:var(--warning-subtle);color:var(--warning)}}
.step-tool.optimization{{background:var(--accent-subtle);color:var(--accent)}}
.step-tool.geometry,.step-tool.boolean,.step-tool.entity{{background:var(--warning-subtle);color:var(--warning)}}
.step-ts{{font-size:10px;color:var(--text-muted);margin-left:auto;font-family:var(--font-mono)}}
.step-body{{font-size:13px;color:var(--text)}}
.step-summary{{margin-bottom:2px}}
.step-rationale{{font-size:12px;color:var(--text-secondary);font-style:italic}}
.s11-snippet{{margin-top:6px;padding:6px 10px;background:var(--bg-raised);border-radius:var(--radius-xs);display:inline-flex;gap:8px;align-items:baseline}}
.s11-min{{font-size:14px;font-weight:700;color:var(--success)}}
.s11-freq{{font-size:12px;color:var(--text-secondary)}}

/* ── Empty / error states ── */
.empty-state{{text-align:center;padding:48px 24px;color:var(--text-muted)}}
.empty-state p{{font-size:14px;margin-top:8px}}
.error-state{{padding:16px 20px;background:var(--danger-subtle);border:1px solid color-mix(in srgb,var(--danger) 20%,transparent);border-radius:var(--radius-sm);color:var(--danger);font-size:13px;margin-bottom:16px}}

/* ── Timeline container ── */
.timeline-container{{position:relative;padding-left:28px;margin:24px 0}}
.timeline-container::before{{content:"";position:absolute;left:11px;top:0;bottom:0;width:2px;background:var(--border);border-radius:1px}}
.timeline-item{{position:relative;margin-bottom:16px}}
.timeline-item::before{{content:"";position:absolute;left:-22px;top:20px;width:10px;height:10px;border-radius:50%;background:var(--bg-card);border:2px solid var(--accent);z-index:1}}
.timeline-item:first-child::before{{background:var(--accent);border-color:var(--accent)}}
.timeline-item:last-child::before{{background:var(--success);border-color:var(--success)}}

/* ── Footer ── */
footer{{margin-top:48px;padding-top:20px;border-top:1px solid var(--border);text-align:left}}
footer p{{color:var(--text-muted);font-size:11px;letter-spacing:.03em;font-family:var(--font-mono)}}

/* ── Canvas 3D ── */
.chart-panel canvas{{max-width:100%;height:auto;display:block;margin:0 auto;border-radius:var(--radius-xs)}}
.ff3d-controls button:hover{{background:var(--accent-subtle);border-color:var(--accent)}}
.ff3d-controls button:active{{transform:scale(0.96)}}
</style>
</head>
<body>
<div class="container">
<header class="page-header">
<h1>{escape(title)}</h1>
{f'<div class="subtitle">{escape(subtitle)}</div>' if subtitle else ''}
<div class="timestamp">{timestamp_str}</div>
</header>
{metrics_html}
<div class="chart-section">
{body_svg}
</div>
{extra_html}
<footer><p>CST Runtime CLI &mdash; &#30005;&#30913;&#20223;&#30495;&#20248;&#21270;&#25253;&#21578;</p></footer>
</div>
</body>
</html>"""


def metric_cards_html(metrics: list[dict[str, str]]) -> str:
    if not metrics:
        return ""
    cards = []
    for m in metrics:
        css_class = m.get("css_class", "")
        cards.append(
            f'<div class="metric-card">'
            f'<div class="metric-label">{escape(m["label"])}</div>'
            f'<div class="metric-value {css_class}">{escape(m["value"])}'
            f'{f'<span class="metric-unit">{escape(m["unit"])}</span>' if m.get("unit") else ""}'
            f'</div>'
            f'</div>'
        )
    return f'<div class="metrics-grid">{"".join(cards)}</div>'
