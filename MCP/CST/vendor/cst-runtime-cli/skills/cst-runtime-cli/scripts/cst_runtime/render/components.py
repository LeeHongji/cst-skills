"""components.py — reusable HTML component library for CST report rendering."""

from __future__ import annotations

import json
from html import escape
from typing import Any


def section_header(label: str, count: int | None = None, badge: str | None = None) -> str:
    parts = [f'<div class="section-header"><h2>{escape(label)}</h2>']
    if count is not None:
        parts.append(f'<span class="section-count">{count}</span>')
    if badge:
        parts.append(f'<span class="section-badge">{escape(badge)}</span>')
    parts.append("</div>")
    return "".join(parts)


def foldable_panel(
    title: str,
    meta: str = "",
    body: str = "",
    tag: str | None = None,
    tag_class: str = "",
    open: bool = False,
    nested: bool = False,
    title_html: str = "",
) -> str:
    """Create a foldable panel. If title_html is provided, use it raw (no escaping)."""
    cls = "foldable-nested" if nested else "foldable"
    tag_html = f'<span class="foldable-tag {tag_class}">{escape(tag)}</span>' if tag else ""
    open_attr = " open" if open else ""
    title_content = title_html if title_html else escape(title)
    return (
        f'<details class="{cls}"{open_attr}>'
        f'<summary>'
        f'{tag_html}'
        f'<span class="foldable-header">'
        f'<span class="foldable-title">{title_content}</span>'
        f'{f'<span class="foldable-meta">{escape(meta)}</span>' if meta else ""}'
        f'</span>'
        f'</summary>'
        f'<div class="foldable-body">{body}</div>'
        f'</details>'
    )


def iteration_header_html(
    run_id: int,
    summary: str,
    s11_value: str | None = None,
    freq: str | None = None,
    is_best: bool = False,
) -> tuple[str, str, str]:
    tag = "最优" if is_best else f"Run {run_id}"
    tag_class = "success" if is_best else ""
    s11_part = f" · S11={s11_value} dB" if s11_value else ""
    freq_part = f" @ {freq} GHz" if freq else ""
    title = f"{summary}{s11_part}{freq_part}"
    return tag, tag_class, title


def step_card_html(step_idx: int, record: dict[str, Any], s11_data: dict[int, dict[str, Any]] | None = None) -> str:
    from .dashboard import _categorize_step, _step_summary, _rationale_from_step  # avoid circular

    tool = record["tool"]
    category = _categorize_step(record)
    summary = _step_summary(record)
    rationale = _rationale_from_step(record)
    ts = record.get("timestamp", "")
    status = record.get("status", "unknown")
    args = record.get("args", {})
    result = record.get("result", {})

    detail_json = json.dumps({"tool": tool, "args": args, "result": result}, indent=2, ensure_ascii=False)

    card_class = "step-card"
    if category == "param_change":
        card_class += " step-param"
    elif category == "simulation":
        card_class += " step-sim"
    elif category == "result":
        card_class += " step-result"
    elif category == "probe":
        card_class += " step-probe"
    elif category == "optimization":
        card_class += " step-optim"

    parts = [
        f'<div class="{card_class}">',
        f'<div class="step-header">',
        f'<span class="step-idx">#{step_idx}</span>',
        f'<span class="step-tool {category}">{category}</span>',
        f'<span class="step-ts">{ts}</span>',
        f'</div>',
        f'<div class="step-body">',
        f'<div class="step-summary"><strong>{escape(summary)}</strong></div>',
    ]
    if rationale:
        parts.append(f'<div class="step-rationale">{escape(rationale)}</div>')

    # ── Probe phase details ──
    if tool == "run-probe-phase":
        parts.append(_probe_details(result))

    # ── Optimization step details ──
    if tool == "run-optimization-step":
        parts.append(_optimization_details(result))

    parts.append("</div></div>")
    return "\n".join(parts)


def _probe_details(result: dict[str, Any]) -> str:
    """Build structured HTML for probe phase results."""
    html = '<div class="step-details" style="margin-top:8px;font-size:12px">'
    n_probes = result.get("n_probes") or result.get("n_simulated", "?")
    mean_val = result.get("mean_value")
    html += f'<div style="margin-bottom:6px;color:var(--text-secondary)">探针数: {n_probes}'
    if mean_val is not None:
        html += f' · 均值 S11: {mean_val:.2f} dB'
    html += '</div>'

    # Main effects
    main_effects = result.get("main_effects", {})
    main_effects_norm = result.get("main_effects_normalized", {})
    if main_effects:
        html += '<div style="font-weight:500;margin:6px 0 4px;color:var(--text)">主效应</div>'
        html += '<table style="width:100%;border-collapse:collapse;font-size:11px">'
        html += '<tr><th style="text-align:left;padding:2px 6px;border-bottom:1px solid var(--border)">参数</th><th style="text-align:right;padding:2px 6px;border-bottom:1px solid var(--border)">效应 (dB)</th><th style="text-align:right;padding:2px 6px;border-bottom:1px solid var(--border)">归一化</th></tr>'
        for param, effect in sorted(main_effects.items(), key=lambda x: abs(x[1]), reverse=True):
            norm = main_effects_norm.get(param, 0)
            html += f'<tr><td style="padding:2px 6px;border-bottom:1px solid var(--border)">{escape(param)}</td><td style="text-align:right;padding:2px 6px;border-bottom:1px solid var(--border);color:{"#0d9488" if effect < 0 else "#dc2626" if effect > 0 else "var(--text)"}">{effect:+.2f}</td><td style="text-align:right;padding:2px 6px;border-bottom:1px solid var(--border)">{norm:.3f}</td></tr>'
        html += '</table>'

    # Top params
    top_params = result.get("top_params", [])
    if top_params:
        html += f'<div style="margin-top:6px;color:var(--text-secondary)">贡献排序: {", ".join(escape(p) for p in top_params)}</div>'

    # Interactions (top 5 by absolute value)
    interactions = result.get("interactions", {})
    if interactions:
        sorted_ints = sorted(interactions.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
        html += '<div style="font-weight:500;margin:6px 0 4px;color:var(--text)">交互效应 (Top 5)</div>'
        html += '<div style="display:flex;flex-wrap:wrap;gap:4px">'
        for pair, val in sorted_ints:
            cls = "green" if val < 0 else "red" if val > 0 else ""
            html += f'<span style="padding:2px 6px;border-radius:4px;border:1px solid var(--border);font-size:10px;white-space:nowrap">{escape(pair)}: <span style="color:{"#0d9488" if val < 0 else "#dc2626" if val > 0 else "var(--text)"}">{val:+.1f}</span></span>'
        html += '</div>'

    html += '</div>'
    return html


def _optimization_details(result: dict[str, Any]) -> str:
    """Build structured HTML for optimization step results."""
    html = '<div class="step-details" style="margin-top:8px;font-size:12px">'
    trial_id = result.get("trial_id", "?")
    html += f'<div style="margin-bottom:6px;color:var(--text-secondary)">Trial #{trial_id}</div>'

    # Params used
    params_used = result.get("params_used", {})
    if params_used:
        html += '<div style="font-weight:500;margin:6px 0 4px;color:var(--text)">本步参数</div>'
        html += '<table style="width:100%;border-collapse:collapse;font-size:11px">'
        html += '<tr><th style="text-align:left;padding:2px 6px;border-bottom:1px solid var(--border)">参数</th><th style="text-align:right;padding:2px 6px;border-bottom:1px solid var(--border)">值</th></tr>'
        for param, val in sorted(params_used.items()):
            html += f'<tr><td style="padding:2px 6px;border-bottom:1px solid var(--border)">{escape(param)}</td><td style="text-align:right;padding:2px 6px;border-bottom:1px solid var(--border)">{val:.4g}</td></tr>'
        html += '</table>'

    # S11 metric
    s11_metric = result.get("s11_metric", {})
    if s11_metric:
        db = s11_metric.get("min_db", "?")
        freq = s11_metric.get("best_freq", "?")
        run_id = s11_metric.get("run_id", "?")
        if isinstance(db, float):
            db = f"{db:.2f}"
        if isinstance(freq, float):
            freq = f"{freq:.3f}"
        html += f'<div style="margin-top:6px;color:var(--text-secondary)">S11: <span style="color:{"#0d9488" if isinstance(s11_metric.get("min_db"), float) and s11_metric["min_db"] < -20 else "var(--text)"}">{db} dB</span> @ {freq} GHz (run {run_id})</div>'

    # Study best
    study_best = result.get("study_best", {})
    if study_best:
        best_val = study_best.get("value")
        best_params = study_best.get("params", {})
        if best_val is not None:
            html += f'<div style="font-weight:500;margin:6px 0 4px;color:var(--text)">阶段最优: {best_val:.2f} dB</div>'
        if best_params:
            html += '<table style="width:100%;border-collapse:collapse;font-size:11px">'
            html += '<tr><th style="text-align:left;padding:2px 6px;border-bottom:1px solid var(--border)">最优参数</th><th style="text-align:right;padding:2px 6px;border-bottom:1px solid var(--border)">值</th></tr>'
            for param, val in sorted(best_params.items()):
                html += f'<tr><td style="padding:2px 6px;border-bottom:1px solid var(--border)">{escape(param)}</td><td style="text-align:right;padding:2px 6px;border-bottom:1px solid var(--border)">{val:.4g}</td></tr>'
            html += '</table>'

    html += '</div>'
    return html


def data_table(headers: list[str], rows: list[list[str]], class_name: str = "") -> str:
    if not rows:
        return ""
    hdr = "".join(f"<th>{escape(h)}</th>" for h in headers)
    row_htmls = []
    for row in rows:
        is_best = class_name and row and "best" in class_name
        row_cls = f' class="{class_name}"' if is_best else ""
        cells = "".join(f"<td>{c}</td>" for c in row)
        row_htmls.append(f"<tr{row_cls}>{cells}</tr>")
    return (
        f'<div class="data-section">'
        f'<table><thead><tr>{hdr}</tr></thead><tbody>{"".join(row_htmls)}</tbody></table>'
        f"</div>"
    )


def badge(text: str, variant: str = "accent") -> str:
    return f'<span class="badge badge-{variant}">{escape(text)}</span>'


def empty_state(text: str = "无可用数据") -> str:
    return f'<div class="empty-state"><p>{escape(text)}</p></div>'


def s11_snippet(min_db: float, best_freq: float) -> str:
    return f'<div class="s11-snippet"><span class="s11-min">S11={min_db:.2f} dB</span> <span class="s11-freq">@ {best_freq:.3f} GHz</span></div>'


def audit_foldable(record: dict[str, Any]) -> str:
    detail_json = json.dumps(record, indent=2, ensure_ascii=False)
    return (
        f'<details class="foldable-nested">'
        f'<summary>审计明细</summary>'
        f'<div class="foldable-body"><pre>{escape(detail_json)}</pre></div>'
        f'</details>'
    )
