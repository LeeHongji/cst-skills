"""Self-contained visual audit packages for geometry IR.

The audit closes the gap that numeric reconstruction checks cannot: generated
geometry may faithfully reproduce an IR while the IR itself misinterprets a
source drawing.  The output is one HTML file with no network dependencies, so
the exact artifact a reviewer saw can be hashed into ``attempt.json``.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import mimetypes
import math
import struct
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import drc, ir
from .audit_ui import SCRIPT as REVIEW_SCRIPT

PALETTE = (
    "#507e7a",
    "#e0b36b",
    "#b5ade5",
    "#22c55e",
    "#f43f5e",
    "#eab308",
    "#14b8a6",
    "#ec4899",
)


class AuditError(ValueError):
    """Raised when an audit package cannot faithfully describe its inputs."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_data_uri(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def source_registration(path: Path, bounds, registration=None, citation=None):
    """Uniform pixel-to-model mapping; uncalibrated fit is never approval-ready.

    The image top-left is (x, y) in model units. Image pixels point downward;
    model y points upward. A known physical image width provides the scale.
    PNG is deliberately supported without an optional imaging dependency.
    """
    raw = path.read_bytes()
    if raw[:8] != b'\x89PNG\r\n\x1a\n' or len(raw) < 24:
        raise AuditError('source image must be PNG with a readable pixel size')
    width, height = struct.unpack('>II', raw[16:24])
    if not width or not height:
        raise AuditError('source image has zero dimensions')
    x0, y0, x1, y1, *_ = bounds
    fit = min((x1-x0)/width, (y1-y0)/height)
    value = dict(x=x0, y=y1, physical_width=width*fit, rotation_deg=0.,
                 calibrated=False, method='uncalibrated aspect-preserving fit',
                 citation=citation or 'missing source citation')
    if registration is not None:
        allowed = set(value)
        if set(registration)-allowed:
            raise AuditError('unknown source registration fields')
        value.update(registration)
    for key in ('x', 'y', 'physical_width', 'rotation_deg'):
        if isinstance(value[key], bool) or not math.isfinite(float(value[key])):
            raise AuditError('source registration must be finite')
        value[key] = float(value[key])
    if value['physical_width'] <= 0:
        raise AuditError('physical_width must be positive')
    if value['calibrated'] and (not value['citation'] or value['citation']=='missing source citation'
                               or value['method']=='uncalibrated aspect-preserving fit'):
        raise AuditError('calibration requires a source citation and calibration method')
    value.update(pixel_width=width, pixel_height=height, sha256=sha256_file(path))
    return value


def _shapes(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for net in document.get("nets", []):
        for solid in net.get("solids", []):
            ring = ir.footprint(solid)
            z_range = ir.z_range(solid)
            if ring is None or z_range is None:
                raise AuditError(f"unsupported audit solid: {net['name']}:{solid['id']} ({solid['kind']})")
            result.append(
                {
                    "key": f"{net['name']}:{solid['id']}",
                    "net": net["name"],
                    "solid": solid["id"],
                    "ring": list(ring),
                    "z0": float(z_range[0]),
                    "z1": float(z_range[1]),
                }
            )
    if not result:
        raise AuditError("geometry IR has no 2D-auditable solids")
    return result


def _bounds(shapes: Sequence[Mapping[str, Any]]) -> tuple[float, float, float, float, float, float]:
    xs = [float(x) for shape in shapes for x, _ in shape["ring"]]
    ys = [float(y) for shape in shapes for _, y in shape["ring"]]
    zs = [float(shape[key]) for shape in shapes for key in ("z0", "z1")]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    z0, z1 = min(zs), max(zs)
    span = max(x1 - x0, y1 - y0, 1.0)
    margin = span * 0.04
    return x0 - margin, y0 - margin, x1 + margin, y1 + margin, z0, z1


def _net_colours(document: Mapping[str, Any]) -> dict[str, str]:
    colours: dict[str, str] = {}
    for index, net in enumerate(sorted(document.get("nets", []), key=lambda item: item["name"])):
        rgb = net.get("color")
        colours[net["name"]] = (
            f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"
            if isinstance(rgb, list) and len(rgb) == 3
            else PALETTE[index % len(PALETTE)]
        )
    return colours


def _violation_keys(report: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for check in report.get("checks", []):
        for violation in check.get("violations", []):
            for field in ("a", "b", "solid", "conductor"):
                value = violation.get(field)
                if isinstance(value, str) and ":" in value:
                    keys.add(value)
            for field in ("net", "net_a", "net_b"):
                value = violation.get(field)
                if isinstance(value, str):
                    keys.add(value + ":")
    return keys


def _is_violating(key: str, violations: set[str]) -> bool:
    return key in violations or any(marker.endswith(":") and key.startswith(marker) for marker in violations)


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_2d(
    shapes: Sequence[Mapping[str, Any]],
    bounds: tuple[float, float, float, float, float, float],
    colours: Mapping[str, str],
    violations: set[str],
    source_uri: str | None,
    registration=None,
) -> str:
    x0, y0, x1, y1, _, _ = bounds
    width, height = x1 - x0, y1 - y0

    def point(value: Sequence[float]) -> str:
        return f"{float(value[0]) - x0:.9g},{y1 - float(value[1]):.9g}"

    pieces = [
        f'<svg id="plan-view" viewBox="0 0 {width:.9g} {height:.9g}" '
        f'data-x0="{x0:.17g}" data-y1="{y1:.17g}" role="img" '
        'aria-label="Interactive top-view geometry audit">'
    ]
    if source_uri:
        reg = registration
        image_width = reg['physical_width']
        image_height = image_width * reg['pixel_height'] / reg['pixel_width']
        pieces.append(
            f'<image id="source-image" href="{source_uri}" x="{reg["x"]-x0:.9g}" y="{y1-reg["y"]:.9g}" '
            f'width="{image_width:.9g}" height="{image_height:.9g}" preserveAspectRatio="xMinYMin meet"/>'
        )
    for shape in sorted(shapes, key=lambda item: (item['z0'], item['z1'], item['key'])):
        key = str(shape["key"])
        net = str(shape["net"])
        cls = "shape violation" if _is_violating(key, violations) else "shape"
        points = " ".join(point(item) for item in shape["ring"])
        xs = [float(item[0]) for item in shape["ring"]]
        ys = [float(item[1]) for item in shape["ring"]]
        cx = (min(xs) + max(xs)) / 2.0 - x0
        cy = y1 - (min(ys) + max(ys)) / 2.0
        label = f"{shape['net']}:{shape['solid']} {max(xs)-min(xs):.4g}×{max(ys)-min(ys):.4g}"
        rotation = f' transform="rotate(-90 {cx:.9g} {cy:.9g})"' if max(ys)-min(ys)>2*(max(xs)-min(xs)) else ''
        pieces.append(
            f'<g class="net-layer" data-net="{html.escape(net)}">'
            f'<polygon class="{cls}" points="{points}" fill="{colours[net]}" '
            f'data-key="{html.escape(key)}"><title>{html.escape(key)}</title></polygon>'
            f'<text class="dimension-label" x="{cx:.9g}" y="{cy:.9g}"{rotation}>'
            f'{html.escape(label)}</text></g>'
        )
    pieces.append(
        '<g id="measurement-layer">'
        '<line id="measure-line" x1="0" y1="0" x2="0" y2="0"/>'
        '<circle id="measure-a" r="0"/><circle id="measure-b" r="0"/>'
        '<text id="measure-label" x="0" y="0"></text></g></svg>'
    )
    return "".join(pieces)


def _parameter_rows(document: Mapping[str, Any]) -> str:
    priority = {"assumption": 0, "strong_inference": 1, "paper_explicit": 2, "synthesized": 3, "optimized": 4}
    rows = []
    for parameter in sorted(
        document.get("parameters", []),
        key=lambda item: (priority.get(item.get("provenance"), 99), item.get("name", "")),
    ):
        provenance = str(parameter.get("provenance", ""))
        review = provenance in {"assumption", "strong_inference"}
        rows.append(
            f'<tr class="{"review-required" if review else ""}">'
            f'<td>{html.escape(str(parameter.get("name", "")))}</td>'
            f'<td>{html.escape(_fmt(parameter.get("value")))}</td>'
            f'<td>{html.escape(str(parameter.get("unit") or ""))}</td>'
            f'<td><span class="badge {html.escape(provenance)}">{html.escape(provenance)}</span></td>'
            f'<td>{html.escape(str(parameter.get("source") or "missing source"))}</td>'
            f'<td>{html.escape(str(parameter.get("description") or ""))}</td></tr>'
        )
    return "".join(rows)


def _drc_rows(report: Mapping[str, Any]) -> str:
    rows = []
    for check in report.get("checks", []):
        status = str(check.get("status", "error"))
        rows.append(
            f'<tr class="drc-{html.escape(status)}">'
            f'<td>{html.escape(str(check.get("id", "")))}</td>'
            f'<td>{html.escape(str(check.get("rule", "")))}</td>'
            f'<td>{html.escape(str(check.get("scope", "")))}</td>'
            f'<td>{html.escape(status)}</td>'
            f'<td>{html.escape(_fmt(check.get("measured")))}</td>'
            f'<td>{html.escape(_fmt(check.get("threshold")))}</td>'
            f'<td><details><summary>{len(check.get("violations", []))}</summary>'
            f'<pre>{html.escape(json.dumps(check.get("violations", []),ensure_ascii=False,indent=2))}</pre>'
            '</details></td></tr>'
        )
    return "".join(rows)


_SCRIPT = """
const svg=document.getElementById('plan-view');
const source=document.getElementById('source-image');
const unit=document.body.dataset.unit;
document.querySelectorAll('[data-source-control]').forEach(e=>e.addEventListener('input',sourceTransform));
document.querySelectorAll('[data-net-toggle]').forEach(box=>box.addEventListener('change',()=>{
  document.querySelectorAll(`.net-layer[data-net="${CSS.escape(box.dataset.netToggle)}"]`).forEach(e=>e.style.display=box.checked?'':'none');
}));
document.getElementById('toggle-dimensions').addEventListener('change',e=>document.body.classList.toggle('show-dimensions',e.target.checked));
let measure=[];
function localPoint(event){const p=svg.createSVGPoint();p.x=event.clientX;p.y=event.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());}
svg.addEventListener('click',event=>{
  if(document.body.dataset.mode!=='measure')return;
  const p=localPoint(event);measure.push(p);if(measure.length>2)measure=[p];
  const a=document.getElementById('measure-a'),b=document.getElementById('measure-b'),line=document.getElementById('measure-line'),label=document.getElementById('measure-label');
  a.setAttribute('cx',p.x);a.setAttribute('cy',p.y);a.setAttribute('r',svg.viewBox.baseVal.width/180);
  if(measure.length===1){b.setAttribute('r',0);line.style.display='none';label.textContent='';return}
  const [p1,p2]=measure;const distance=Math.hypot(p2.x-p1.x,p2.y-p1.y);
  b.setAttribute('cx',p2.x);b.setAttribute('cy',p2.y);b.setAttribute('r',svg.viewBox.baseVal.width/180);
  for(const [name,v] of [['x1',p1.x],['y1',p1.y],['x2',p2.x],['y2',p2.y]])line.setAttribute(name,v);
  line.style.display='';label.setAttribute('x',(p1.x+p2.x)/2);label.setAttribute('y',(p1.y+p2.y)/2);
  label.textContent=`${distance.toFixed(4)} ${unit}`;
});
document.getElementById('clear-measure').addEventListener('click',()=>{measure=[];document.getElementById('measure-a').setAttribute('r',0);document.getElementById('measure-b').setAttribute('r',0);document.getElementById('measure-line').style.display='none';document.getElementById('measure-label').textContent='';});
"""


def render(
    document: Mapping[str, Any],
    *,
    drc_report: Mapping[str, Any] | None = None,
    source_image: str | Path | None = None,
    title: str | None = None,
    registration: Mapping[str, Any] | None = None,
    source_citation: str | None = None,
) -> str:
    """Render a deterministic, self-contained HTML audit package."""
    doc = dict(document)
    problems = ir.validate(doc)
    if problems:
        raise AuditError("invalid geometry IR: " + "; ".join(problems[:5]))
    actual_report = drc.run(doc)
    report = dict(drc_report or actual_report)
    if report.get("model_intent_id") != doc.get("model_intent_id"):
        raise AuditError("DRC report model_intent_id does not match the geometry IR")
    if report != actual_report:
        raise AuditError('DRC report differs from recomputed checks; regenerate it')

    shapes = _shapes(doc)
    bounds = _bounds(shapes)
    colours = _net_colours(doc)
    violations = _violation_keys(report)
    for shape in shapes:
        shape['violation'] = _is_violating(shape['key'], violations)
    source_uri = _image_data_uri(Path(source_image)) if source_image else None
    reg = source_registration(Path(source_image), bounds, registration, source_citation) if source_image else None
    topology = ir.topology_hash(doc)
    metadata = {
        "schema_version": 1,
        "model_id": doc["model_id"],
        "model_intent_id": doc["model_intent_id"],
        "topology_hash": topology,
        "drc_status": report["status"],
        "source_image_embedded": source_uri is not None,
        "units": doc.get("units", {}),
        "source_registration": reg,
        "baseline_parameters": {p['name']: p['value'] for p in doc.get('parameters', [])},
        "drc_sha256": hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
    }
    metadata['artifact_id'] = hashlib.sha256(json.dumps(metadata,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    page_title = title or f"Geometry audit — {doc.get('title') or doc['model_id']}"
    range_rows = []
    for p in doc.get('parameters', []):
        if not p.get('tunable', False):
            continue
        value = float(p['value']); span = abs(value)*.2
        low = _fmt(value-span) if value else ''; high = _fmt(value+span) if value else ''
        range_rows.append(f'<tr data-range-name="{html.escape(p["name"])}"><td><input type="checkbox"> {html.escape(p["name"])}</td>'
                          f'<td><input type="number" step="any" value="{low}" aria-label="{html.escape(p["name"])} low"></td>'
                          f'<td><input type="number" step="any" value="{high}" aria-label="{html.escape(p["name"])} high"></td></tr>')
    from . import workbench
    from .workbench_ui import SCRIPT as WORKBENCH_SCRIPT
    return workbench.render(
        doc=doc, report=report, shapes=shapes, colours=colours,
        metadata=metadata, metadata_json=metadata_json, title=page_title,
        plan_svg=_render_2d(shapes, bounds, colours, violations, source_uri, reg),
        three_svg='<div id="three-view" role="img" aria-label="3D CAD geometry"></div>',
        parameter_rows=_parameter_rows(doc), drc_rows=_drc_rows(report),
        range_rows=range_rows, script=_SCRIPT + REVIEW_SCRIPT + WORKBENCH_SCRIPT,
    )



def write(
    document: Mapping[str, Any],
    output: str | Path,
    *,
    drc_report: Mapping[str, Any] | None = None,
    source_image: str | Path | None = None,
    title: str | None = None,
    registration: Mapping[str, Any] | None = None,
    source_citation: str | None = None,
) -> dict[str, Any]:
    target = Path(output)
    if target.suffix.lower() != ".html":
        raise AuditError(f"audit output must be an .html file, got {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render(document, drc_report=drc_report, source_image=source_image, title=title,
               registration=registration, source_citation=source_citation),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "status": "ok",
        "output": str(target.resolve()),
        "sha256": sha256_file(target),
        "model_intent_id": document["model_intent_id"],
        "topology_hash": ir.topology_hash(dict(document)),
        "drc_status": (drc_report or drc.run(dict(document)))["status"],
        "self_contained": True,
    }


def read_metadata(path: str | Path) -> dict[str, Any]:
    """Read the immutable binding metadata embedded in an audit HTML file."""
    text = Path(path).read_text(encoding="utf-8")
    marker = '<script id="audit-metadata" type="application/json">'
    if text.count(marker) != 1:
        raise AuditError('audit HTML must have exactly one metadata record')
    start = text.find(marker)
    if start < 0:
        raise AuditError("audit HTML has no embedded audit-metadata record")
    start += len(marker)
    end = text.find("</script>", start)
    if end < 0:
        raise AuditError("audit HTML metadata script is not closed")
    try:
        return json.loads(text[start:end].replace("<\\/", "</"))
    except json.JSONDecodeError as exc:
        raise AuditError(f"audit HTML metadata is invalid JSON: {exc}") from exc


def verify_embedded_source(path, metadata):
    """Match provenance to actual embedded PNG, independent of metadata claims."""
    class Images(HTMLParser):
        def __init__(self):super().__init__();self.sources=[]
        def handle_starttag(self, tag, attrs):
            values=dict(attrs)
            if tag=='image' and values.get('id')=='source-image':self.sources.append(values.get('href',''))
    parser=Images();parser.feed(Path(path).read_text(encoding='utf-8'))
    reg=metadata.get('source_registration')
    if not metadata.get('source_image_embedded'):
        if parser.sources or reg:raise AuditError('unreported source image')
        return
    if len(parser.sources)!=1 or not reg:raise AuditError('source image registration missing or ambiguous')
    prefix='data:image/png;base64,'
    if not parser.sources[0].startswith(prefix):raise AuditError('source must be an embedded PNG')
    try:raw=base64.b64decode(parser.sources[0][len(prefix):],validate=True)
    except ValueError as exc:raise AuditError('invalid embedded source') from exc
    if len(raw)<24 or raw[:8]!=b'\x89PNG\r\n\x1a\n':raise AuditError('invalid PNG header')
    if hashlib.sha256(raw).hexdigest()!=reg.get('sha256'):raise AuditError('embedded image hash differs from provenance')
    width,height=struct.unpack('>II',raw[16:24])
    if (width,height)!=(reg.get('pixel_width'),reg.get('pixel_height')):raise AuditError('embedded image dimensions differ from provenance')
