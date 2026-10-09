"""Model-first, bilingual CAD review workspace; rendered into one offline file."""
import html
import json
from .workbench_style import STYLE
from importlib.resources import files


def bi(zh,en):
    return f'<span data-zh="{html.escape(zh)}" data-en="{html.escape(en)}">{html.escape(zh)}</span>'


PATHS={
 'cube':'M9 2 2 6v9l7 4 7-4V6L9 2ZM2 6l7 4 7-4M9 10v9',
 'layers':'m2 6 7-4 7 4-7 4-7-4Zm0 5 7 4 7-4M2 15l7 4 7-4',
 'plan':'M3 3h12v12H3zM3 7h12M7 3v12',
 'measure':'m2 13 11-11 4 4L6 17l-4-4Zm4-4 2 2m1-5 2 2m1-5 2 2',
 'fit':'M2 7V2h5m5 0h5v5m0 5v5h-5m-5 0H2v-5M6 6h7v7H6z',
 'plus':'M9 3v12M3 9h12', 'minus':'M3 9h12',
 'check':'m3 9 4 4 8-8', 'chevron':'m7 4 5 5-5 5',
 'download':'M9 2v10m-4-4 4 4 4-4M3 13v4h12v-4',
 'cross':'m4 4 10 10M14 4 4 14', 'sliders':'M2 5h5m4 0h5M2 13h9m4 0h1M7 2v6m4 2v6',
 'eye':'M1 9s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5Zm10 0a2 2 0 1 1-4 0 2 2 0 0 1 4 0',
 'cursor':'M3 2v13l4-4 3 6 3-2-3-5 6-1L3 2Z',
 'rotate':'M15 6A6 6 0 1 0 15 12M15 2v4h-4',
 'file':'M4 2h7l4 4v11H4V2Zm7 0v5h4M7 10h5m-5 3h5',
}


def icon(name):
    return f'<svg viewBox="0 0 19 20" aria-hidden="true" class="icon"><path d="{PATHS[name]}"/></svg>'


def render(*,doc,report,shapes,colours,metadata,metadata_json,title,plan_svg,three_svg,parameter_rows,drc_rows,range_rows,script):
    net_rows=''.join(f'<div class="net-row" data-net-row="{html.escape(name)}"><button class="net-select" data-select-net="{html.escape(name)}">'
                     f'<span class="swatch" style="--color:{color}"></span><span>{html.escape(name)}</span></button>'
                     f'<span class="count">{sum(s["net"]==name for s in shapes)}</span>'
                     f'<input type="checkbox" checked data-net-toggle="{html.escape(name)}" aria-label="{html.escape(name)} visibility / 显隐"></div>' for name,color in colours.items())
    ports=''.join(f'<div class="port-row"><span class="port-dot">P{p["number"]}</span><span>{html.escape(p["net"])}</span><span class="grow"></span><span class="subtle">{html.escape(p["orientation"])}</span></div>' for p in doc.get('ports',[]))
    parameters=doc.get('parameters',[])
    concerns=[p for p in parameters if p.get('provenance') in ('assumption','strong_inference')]
    notes=''.join(f'<div class="review-note"><strong>{html.escape(p["name"])} · {p["value"]} {html.escape(p.get("unit", ""))}</strong>{html.escape(p.get("description") or p.get("source") or p["provenance"])}</div>' for p in concerns[:4])
    if doc.get('notes'): notes='<div class="review-note">'+html.escape(doc['notes'])+'</div>'+notes
    reg=metadata.get('source_registration')
    source_fields='<div class="empty">'+bi('此模型暂无来源图，可直接检查模型及参数依据。','No source image. Review the model and parameter provenance directly.')+'</div>'
    if reg:
        source_fields='<div class="field-grid">'
        for id,key,zh,en in [('source-x','x','左上原点 X','Origin X'),('source-y','y','左上原点 Y','Origin Y'),('source-width','physical_width','图像物理宽度','Physical width'),('source-angle','rotation_deg','旋转角度 °','Rotation °')]:
            source_fields+=f'<label class="field">{bi(zh,en)}<input id="{id}" data-registration-control type="number" step="any" value="{reg[key]}"></label>'
        source_fields+='</div>'
        for id,key,zh,en in [('source-citation','citation','来源引用','Source citation'),('source-method','method','标定依据','Calibration basis')]:
            source_fields+=f'<label class="field">{bi(zh,en)}<input id="{id}" data-registration-control value="{html.escape(reg[key])}"></label>'
        source_fields+=f'<label class="field"><input id="source-calibrated" data-registration-control type="checkbox" {"checked" if reg["calibrated"] else ""}> {bi("已依据尺寸完成等比例标定","Calibrated against the stated dimension")}</label>'
    model_data=json.dumps(dict(shapes=shapes,nets=doc.get('nets',[]),ports=doc.get('ports',[]),stackup=doc.get('stackup',[]),colours=colours,parameters=parameters,unit=doc.get('units',{}).get('length','mm')),ensure_ascii=False).replace('</','<\\/')
    headers=lambda pairs:''.join('<th>'+bi(zh,en)+'</th>' for zh,en in pairs)
    license_text=files('cst_cad').joinpath('assets/THREE-LICENSE.txt').read_text(encoding='utf-8')
    renderer_script=('/*\n'+license_text.replace('*/','* /')+'\n*/\n'+files('cst_cad').joinpath('assets/viewer.js').read_text(encoding='utf-8')).replace('</script', '<\\/script')
    check_class='' if report['status']=='pass' else ' fail'
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; font-src data:; base-uri 'none'; form-action 'none'"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · CAD Review</title><style>{STYLE}</style></head>
<body data-unit="{html.escape(doc.get('units',{}).get('length','mm'))}" data-mode="select" data-view="3d">
<header class="topbar"><div class="brand"><span class="brandmark">{icon('cube')}</span>CST <span style="font-weight:400;color:#9aa7b8">/</span> REVIEW</div><span class="divider"></span>
<div><div class="project-title">{html.escape(doc.get('title') or doc['model_id'])}</div><div class="subtle">{bi('几何理解与建模审查','Geometry interpretation workspace')}</div></div><span class="grow"></span>
<span class="status-pill">{bi('待人工审阅','Awaiting review')}</span><button class="language" id="language-toggle">中文 / EN</button><button class="primary" id="open-approval">{icon('check')}{bi('审阅与确认','Review & confirm')}</button></header>
<nav class="toolbar"><div class="tool-group"><button class="tool" data-view="2d">{icon('plan')}{bi('平面','Plan')}</button><button class="tool active" data-view="3d">{icon('cube')}{bi('立体','3D')}</button></div><span class="divider"></span>
<div class="tool-group"><button class="tool active" data-mode="select">{icon('cursor')}{bi('选择','Select')}</button><button class="tool" data-mode="measure">{icon('measure')}{bi('量测','Measure')}<span class="keyboard">M</span></button><button class="tool" data-mode="pan">{icon("fit")}{bi("平移","Pan")}</button><button class="tool" id="dimensions-tool">{icon('layers')}{bi('尺寸','Dimensions')}</button></div>
<span class="divider"></span><button class="tool" id="open-source">{icon('sliders')}{bi('来源配准','Source alignment')}</button><span class="grow"></span><button class="tool inspector-toggle" id="toggle-inspector">{icon("sliders")}{bi("检查器","Inspector")}</button><button class="tool" id="reset-all">{icon('rotate')}{bi('重置视图','Reset view')}</button></nav>
<main class="workspace"><aside class="sidebar tree"><div class="panel-heading"><h2>{bi('模型结构','MODEL TREE')}</h2><span class="count">{len(shapes)}</span></div>
<div class="tree-root">{icon('cube')} {bi('几何模型','Geometry model')}</div><div class="tree-subtitle">{bi('实体与网络','BODIES & NETS')}</div>{net_rows}
<div class="tree-subtitle" style="margin-top:18px">{bi('端口与激励','PORTS & EXCITATION')}</div>{ports or '<div class="empty">'+bi('未定义端口','No ports defined')+'</div>'}
<div class="tree-note">{icon('eye')}<p>{bi('选择网络以检查尺寸与层叠。显隐与视角操作仅影响审阅视图。','Select a net to inspect dimensions and stackup. Visibility and camera controls affect this review only.')}</p></div></aside>
<section class="stage" id="cad-stage"><div class="stage-corner"><span>GEOMETRY INSPECTION</span><strong id="view-name">{bi('正交立体视图','Orthographic 3D')}</strong></div><div class="view-badge" id="view-badge">ISO · mm</div>
<div class="canvas-view" id="view-2d" hidden>{plan_svg}</div><div class="canvas-view" id="view-3d">{three_svg}</div>
<div class="canvas-hint" id="canvas-hint">{bi('拖动旋转 · 滚轮缩放','Drag to orbit · Scroll to zoom')}</div><div class="canvas-tools"><button class="icon-button" id="zoom-out" aria-label="缩小 / Zoom out">{icon('minus')}</button><button class="icon-button" id="fit-view" aria-label="适应视图 / Fit view">{icon('fit')}</button><button class="icon-button" id="zoom-in" aria-label="放大 / Zoom in">{icon('plus')}</button><span class="tool-separator"></span><button class="icon-button" id="explode-view" aria-label="分层展开 / Explode layers">{icon('layers')}</button></div><div id="cad-navigation"><select id="cad-standard-view" aria-label="标准视图 / Standard view"><option value="custom" data-zh="自定义视角" data-en="Custom view">自定义视角</option><option value="iso" data-zh="等轴测" data-en="Isometric">等轴测</option><option value="top" data-zh="俯视 +Z" data-en="Top +Z">俯视 +Z</option><option value="bottom" data-zh="仰视 −Z" data-en="Bottom −Z">仰视 −Z</option><option value="front" data-zh="前视 −Y" data-en="Front −Y">前视 −Y</option><option value="back" data-zh="后视 +Y" data-en="Back +Y">后视 +Y</option><option value="right" data-zh="右视 +X" data-en="Right +X">右视 +X</option><option value="left" data-zh="左视 −X" data-en="Left −X">左视 −X</option></select></div><canvas id="cad-triad" aria-label="同步世界坐标轴 / Synchronized world axes"></canvas><span id="cad-scale"></span></section>
<aside class="sidebar inspector"><div class="panel-heading"><h2>{bi('检查器','INSPECTOR')}</h2>{icon('sliders')}</div><div class="eyebrow" id="inspector-eyebrow">MODEL OVERVIEW</div><div class="inspector-title" id="selection-title">{bi('模型概览','Model overview')}</div><div class="inspector-caption" id="selection-caption">{bi('先核对结构，再确认建模假设','Check structure before confirming assumptions')}</div>
<div id="selection-properties"></div><div class="inspector-section"><div class="metric-grid"><div class="metric"><strong>{len(shapes)}</strong><span>{bi('几何实体','Bodies')}</span></div><div class="metric"><strong>{len(doc.get('ports',[]))}</strong><span>{bi('端口','Ports')}</span></div></div></div>
<div class="check-status{check_class}">{icon('check')}<div><strong>{bi('设计规则','Design rules')} · {html.escape(report['status'].upper())}</strong><div class="subtle">{report['summary']['passed']} / {report['summary']['checks']} {bi('检查通过','checks passed')}</div></div></div>
<div class="inspector-section"><div class="section-title">{bi('需要你确认的理解','INTERPRETATIONS TO REVIEW')} · {len(concerns)}</div>{notes or '<div class="review-note">'+bi('参数出处见下方依据表。','See the provenance table for parameter sources.')+'</div>'}</div>
<div class="inspector-section"><label class="field">{bi('来源图透明度','Source opacity')}<input id="source-opacity" data-source-control type="range" min="0" max="100" value="45" {'' if reg else 'disabled'}></label><label class="field"><input id="toggle-dimensions" type="checkbox"> {bi('显示尺寸标注','Dimension labels')}</label><button class="ghost" id="clear-measure">{bi('清除量测','Clear measure')}</button></div>
</aside><section class="evidence"><div class="dock-tabs"><button class="dock-tab active" data-panel="parameters">{bi('参数与依据','Parameter provenance')} <span class="count">{len(parameters)}</span></button><button class="dock-tab" data-panel="drc">{bi('设计规则检查','DRC results')} <span class="count">{report['summary']['checks']}</span></button><button class="dock-tab" data-panel="identity">{bi('模型身份','Model identity')}</button><span class="grow"></span><button class="icon-button" id="toggle-evidence" aria-label="折叠证据面板 / Collapse evidence">{icon('minus')}</button></div>
<div class="dock-panel" data-panel="parameters"><table><thead><tr>{headers([('参数','Parameter'),('数值','Value'),('单位','Unit'),('出处级别','Provenance'),('来源','Source'),('建模解释','Interpretation')])}</tr></thead><tbody>{parameter_rows}</tbody></table></div>
<div class="dock-panel" data-panel="drc" hidden><table><thead><tr>{headers([('检查项','Check'),('规则','Rule'),('范围','Scope'),('状态','Status'),('测量值','Measured'),('门槛','Threshold'),('定位','Details')])}</tr></thead><tbody>{drc_rows}</tbody></table></div>
<div class="dock-panel" data-panel="identity" hidden><div class="identity" style="margin:15px">MODEL · {html.escape(doc['model_id'])}<br>INTENT · {doc['model_intent_id']}<br>TOPOLOGY · {metadata['topology_hash']}<br>ARTIFACT · {metadata['artifact_id']}</div></div></section></main>
<footer class="footer"><span class="dot"></span>{bi('本地审查 · 未运行求解器','Local review · No solver run')}<span class="grow"></span><span id="cursor-position">X — &nbsp; Y —</span><span>mm</span><span>CAD REVIEW / 01</span></footer>
<div class="modal-backdrop" id="source-modal" hidden><section class="modal"><div class="modal-head"><div><div class="step-label">SOURCE ALIGNMENT</div><h2>{bi('核对来源与模型','Align source and model')}</h2></div><button class="icon-button" data-close-modal aria-label="关闭 / Close">{icon('cross')}</button></div><div class="modal-content"><p>{bi('使用已知尺寸进行等比例标定。保存后的新文件会保留配准状态，供重新审阅。','Use a known dimension for uniform calibration. A newly saved audit preserves the registration for review.')}</p>{source_fields}</div><div class="modal-actions"><button class="ghost" data-close-modal>{bi('返回模型','Back to model')}</button><button class="primary" id="save-registration">{icon('download')}{bi('保存审计版本','Save audit version')}</button></div></section></div>
<div class="modal-backdrop" id="approval-modal" hidden><section class="modal"><div class="modal-head"><div><div class="step-label">REVIEW & CONFIRM</div><h2>{bi('确认你的建模理解','Confirm the modeling interpretation')}</h2></div><button class="icon-button" data-close-modal aria-label="关闭 / Close">{icon('cross')}</button></div><div class="modal-content"><p>{bi('选择允许调整的参数和范围。未选参数保持固定；建议区间不等于批准。','Choose the parameters and ranges that may change. Unselected parameters stay fixed; suggestions are not approval.')}</p><table class="range-table"><thead><tr>{headers([('允许调整','Allow change'),('最小值','Minimum'),('最大值','Maximum')])}</tr></thead><tbody>{''.join(range_rows)}</tbody></table>
<label class="field">{bi('选择当前审阅的 HTML 文件','Choose the HTML file being reviewed')}<input id="audit-file" type="file" accept=".html"></label><div class="approval-message" id="approval-status">{bi('尚未批准。导出的请求需要通过人工确认入口完成批准。','Not approved. Exported requests require human confirmation through the approval tool.')}</div><details style="margin-top:16px"><summary class="subtle">{bi('查看批准请求','Inspect approval request')}</summary><pre class="request-preview" id="approval-request-preview">{bi('尚未生成请求','No request generated')}</pre></details></div><div class="modal-actions"><button class="ghost" data-close-modal>{bi('继续检查','Continue inspection')}</button><button class="primary" id="export-approval">{icon('download')}{bi('导出批准请求','Export approval request')}</button></div></section></div>
<div class="toast" id="workbench-toast" hidden></div><script id="audit-metadata" type="application/json">{metadata_json}</script><script id="audit-model" type="application/json">{model_data}</script><script id="cad-renderer">{renderer_script}</script><script>{script}</script></body></html>'''
