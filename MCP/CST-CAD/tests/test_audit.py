from __future__ import annotations

import base64
import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "MCP" / "CST-CAD" / "src"))

from cst_cad import audit, drc, ir  # noqa: E402
from cst_cad.dsl import ModelBuilder  # noqa: E402


def coupon(*, gap: float = 0.5, fail_spacing: bool = False) -> dict:
    model = ModelBuilder(model_id="neutral-two-net-coupon", title="Neutral two-net microstrip coupon")
    model.units(length="mm", frequency="GHz")
    h = model.param(
        "h",
        1.0,
        provenance="paper_explicit",
        source="fixture://neutral-coupon",
        description="substrate height",
    )
    t = model.param(
        "t_cu",
        0.035,
        provenance="assumption",
        source="fixture://neutral-coupon",
        description="copper thickness chosen for the fixture",
    )
    width = model.param(
        "trace_w",
        0.4,
        provenance="strong_inference",
        source="fixture://neutral-coupon",
        description="trace width under review",
        tunable=True,
        minimum=0.2,
        maximum=0.8,
    )
    model.material("Sub", kind="normal", epsilon=4.4, mu=1.0, tan_delta=0.02)
    model.material("PEC", kind="pec")
    model.layer("sub", 0.0, h, "Sub", role="substrate")
    model.layer("top", h, h + t, "PEC", role="signal")
    board = model.net("BOARD", "sub", net_class="reference")
    board.box(-2.0, -2.0, 8.0, 14.0)
    left = model.net("LEFT", "top")
    left.rect(0.0, 0.0, width, 10.0, solid_id="trace")
    right = model.net("RIGHT", "top")
    right.rect(0.4 + gap, 0.0, width, 10.0, solid_id="trace")
    model.port("P1", 1, "LEFT", "ymin", 0.0, 0.4, 0.0, 0.0, 0.0, 1.035)
    model.rule(
        "spacing",
        "min_spacing",
        "layer:top",
        severity="error",
        min_spacing=0.75 if fail_spacing else 0.25,
    )
    model.rule("connected", "net_connectivity", "*", severity="error", max_components=1)
    return model.build()


def test_audit_is_self_contained_and_embeds_binding_metadata(tmp_path: Path) -> None:
    document = coupon()
    output = tmp_path / "audit.html"
    result = audit.write(document, output)
    text = output.read_text(encoding="utf-8")

    assert result["self_contained"] is True
    assert result["sha256"] == audit.sha256_file(output)
    assert "<!doctype html>" in text
    # Bundled Three.js contains namespace/documentation URLs, not asset requests.
    from html.parser import HTMLParser
    class Assets(HTMLParser):
        refs = []
        def handle_starttag(self, tag, attrs):
            self.refs.extend(v for k,v in attrs if k in {'src','href'} and v)
    assets = Assets(); assets.feed(text)
    assert all(ref.startswith(('data:', '#', 'blob:')) for ref in assets.refs)
    assert 'connect-src' in text
    assert "2D source/IR overlay" in text
    assert "Orthographic 3D" in text
    assert "Parameter provenance" in text
    assert "DRC results" in text
    assert 'lang="zh-CN"' in text
    assert 'id="language-toggle"' in text
    assert 'id="toggle-inspector"' in text
    assert 'id="audit-model"' in text
    assert 'data-select-net="LEFT"' in text

    metadata = audit.read_metadata(output)
    assert metadata["model_intent_id"] == document["model_intent_id"]
    assert metadata["topology_hash"] == ir.topology_hash(document)
    assert metadata["drc_status"] == "pass"


def test_reviewable_parameters_are_sorted_before_explicit_parameters(tmp_path: Path) -> None:
    output = tmp_path / "audit.html"
    audit.write(coupon(), output)
    text = output.read_text(encoding="utf-8")
    assert text.index("t_cu") < text.index(">h<")
    assert text.index("trace_w") < text.index(">h<")
    assert 'class="review-required"' in text


def test_source_image_is_embedded_as_data_not_linked(tmp_path: Path) -> None:
    # A valid 1x1 transparent PNG; image decoding belongs to the browser, while
    # this test proves the package has no external file dependency.
    png = tmp_path / "source.png"
    png.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
            "AScY42YAAAAASUVORK5CYII="
        )
    )
    output = tmp_path / "audit.html"
    audit.write(coupon(), output, source_image=png)
    text = output.read_text(encoding="utf-8")
    assert "data:image/png;base64," in text
    assert str(png) not in text
    assert audit.read_metadata(output)["source_image_embedded"] is True


def test_drc_violation_is_highlighted_and_reported(tmp_path: Path) -> None:
    document = coupon(gap=0.5, fail_spacing=True)
    report = drc.run(document)
    assert report["status"] == "fail"
    output = tmp_path / "audit.html"
    audit.write(document, output, drc_report=report)
    text = output.read_text(encoding="utf-8")
    assert 'class="shape violation"' in text
    model_json = text.split('<script id="audit-model" type="application/json">', 1)[1].split('</script>', 1)[0]
    assert any(shape['violation'] for shape in json.loads(model_json)['shapes'])
    assert 'class="drc-fail"' in text
    assert audit.read_metadata(output)["drc_status"] == "fail"


def test_a_drc_report_for_another_ir_is_refused(tmp_path: Path) -> None:
    document = coupon()
    report = drc.run(document)
    report["model_intent_id"] = "0" * 64
    with pytest.raises(audit.AuditError, match="does not match"):
        audit.write(document, tmp_path / "audit.html", drc_report=report)


def test_invalid_or_tampered_ir_is_refused(tmp_path: Path) -> None:
    document = copy.deepcopy(coupon())
    document["model_intent_id"] = "0" * 64
    with pytest.raises(audit.AuditError, match="invalid geometry IR"):
        audit.write(document, tmp_path / "audit.html")


def test_audit_output_is_deterministic(tmp_path: Path) -> None:
    document = coupon()
    left = tmp_path / "left.html"
    right = tmp_path / "right.html"
    audit.write(document, left)
    audit.write(json.loads(json.dumps(document)), right)
    assert left.read_bytes() == right.read_bytes()
    assert audit.sha256_file(left) == audit.sha256_file(right)


def test_only_html_outputs_are_accepted(tmp_path: Path) -> None:
    with pytest.raises(audit.AuditError, match=r"\.html"):
        audit.write(coupon(), tmp_path / "audit.txt")


def test_registration_preserves_aspect_and_is_bound_to_image_bytes(tmp_path):
    import struct
    # Header-only fixture: mapping tested here, actual decoding in browser QA.
    png=tmp_path/'source.png';png.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0'*8+struct.pack('>II',400,200))
    reg=dict(x=-2.,y=12.,physical_width=8.,rotation_deg=0.,calibrated=True,
             method='8 mm full image width; top-left origin (-2,12)',citation='fixture://independent-drawing')
    output=tmp_path/'audit.html';audit.write(coupon(),output,source_image=png,registration=reg)
    text=output.read_text(encoding='utf-8');meta=audit.read_metadata(output)
    assert 'preserveAspectRatio="none"' not in text
    assert 'width="8" height="4"' in text
    assert meta['source_registration']['sha256']==audit.sha256_file(png)
    assert meta['source_registration']['calibrated'] is True
    changed=tmp_path/'changed.html';reg['x']=1.
    audit.write(coupon(),changed,source_image=png,registration=reg)
    assert audit.sha256_file(output)!=audit.sha256_file(changed)


def test_drc_claim_cannot_replace_actual_failed_checks(tmp_path):
    document=coupon(fail_spacing=True);report=drc.run(document);report['status']='pass'
    with pytest.raises(audit.AuditError,match='recomputed'):
        audit.write(document,tmp_path/'audit.html',drc_report=report)


def test_ports_and_approval_request_controls_are_in_the_offline_artifact(tmp_path):
    out=tmp_path/'audit.html';audit.write(coupon(),out)
    text=out.read_text(encoding='utf-8')
    model_json = text.split('<script id="audit-model" type="application/json">',1)[1].split('</script>',1)[0]
    assert json.loads(model_json)['ports'] == coupon()['ports']
    assert 'id="cad-renderer"' in text
    assert '<svg id="three-view"' not in text
    assert 'id="export-approval"' in text and 'id="save-registration"' in text
    assert 'data-range-name="trace_w"' in text
    assert 'data-range-name="h"' not in text


def test_embedded_image_provenance_is_verified(tmp_path):
    import struct
    png=tmp_path/'source.png';png.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0'*8+struct.pack('>II',40,20))
    out=tmp_path/'audit.html';audit.write(coupon(),out,source_image=png)
    meta=audit.read_metadata(out);audit.verify_embedded_source(out,meta)
    meta['source_registration']['sha256']='0'*64
    with pytest.raises(audit.AuditError,match='hash differs'):audit.verify_embedded_source(out,meta)
