from __future__ import annotations

import json
import math
from typing import Any


def render_3d_farfield(data: dict[str, Any], container_id: str = "ff3d") -> str:
    xpos = data.get("xpositions", [])
    ypos = data.get("ypositions", [])
    gain = data.get("data", [])
    if not xpos or not ypos or not gain:
        return '<div class="chart-panel"><p>\u65e0\u53ef\u7528\u7684\u8fdc\u573a\u6570\u636e\uff0c\u65e0\u6cd5\u6e32\u67d3 3D \u89c6\u56fe</p></div>'

    ny = len(xpos)
    nx = len(ypos)

    raw_vals: list[float | None] = []
    for i in range(ny):
        for j in range(nx):
            g = gain[j][i] if j < len(gain) and i < len(gain[j]) else None
            raw_vals.append(float(g) if g is not None else None)
    valid_vals = [v for v in raw_vals if v is not None]
    val_min = min(valid_vals) if valid_vals else -40
    val_max = max(valid_vals) if valid_vals else 14
    val_rng = max(val_max - val_min, 1)

    vertices: list[list[float]] = []
    values: list[float | None] = []
    max_radius = 0.0
    for i in range(ny):
        for j in range(nx):
            g = raw_vals[i * nx + j]
            if g is None:
                r = 0.1
                v = None
            else:
                r = (g - val_min) / val_rng * 4.5 + 0.3
                v = g
                max_radius = max(max_radius, r)
            th = math.radians(float(xpos[i]))
            ph = math.radians(float(ypos[j]))
            x = r * math.sin(th) * math.cos(ph)
            y = r * math.sin(th) * math.sin(ph)
            z = r * math.cos(th)
            vertices.append([x, y, z])
            values.append(v)

    faces: list[list[int]] = []
    for i in range(ny - 1):
        for j in range(nx - 1):
            a = i * nx + j
            b = a + 1
            c = a + nx
            d = c + 1
            va, vb, vc, vd = values[a], values[b], values[c], values[d]
            if va is not None and vb is not None and vc is not None:
                faces.append([a, b, c, (va + vb + vc) / 3])
            if vb is not None and vd is not None and vc is not None:
                faces.append([b, d, c, (vb + vd + vc) / 3])

    if nx >= 3:
        for i in range(ny - 1):
            a = i * nx + (nx - 1)
            b = i * nx
            c = (i + 1) * nx + (nx - 1)
            d = (i + 1) * nx
            va, vb, vc, vd = values[a], values[b], values[c], values[d]
            if va is not None and vb is not None and vc is not None:
                faces.append([a, b, c, (va + vb + vc) / 3])
            if vb is not None and vd is not None and vc is not None:
                faces.append([b, d, c, (vb + vd + vc) / 3])

    if not faces:
        return '<div class="chart-panel"><p>\u65e0\u6709\u6548\u7684\u8fdc\u573a\u7f51\u683c\u6570\u636e</p></div>'

    camera_dist = max(max_radius * 2.5, 6)
    initial_zoom = 1.0

    vdata: list[float] = []
    for f in faces:
        a, b, c, fv = f
        for idx in (a, b, c):
            v = vertices[idx]
            vdata.extend([v[0], v[1], v[2], fv])

    vdata_json = json.dumps(vdata, separators=(",", ":"))
    face_count = len(faces)

    js = f'''<div class="ff3d-controls" style="display:flex;gap:8px;margin-bottom:8px;">
<button onclick="document.getElementById('{container_id}').resetView()" style="padding:4px 12px;font-size:11px;border:1px solid var(--border);border-radius:6px;background:var(--bg-raised);color:var(--text);cursor:pointer;transition:var(--transition);font-family:var(--font-sans);">重置</button>
<button onclick="document.getElementById('{container_id}').startAuto()" style="padding:4px 12px;font-size:11px;border:1px solid var(--border);border-radius:6px;background:var(--bg-raised);color:var(--text);cursor:pointer;transition:var(--transition);font-family:var(--font-sans);">旋转</button>
<button onclick="document.getElementById('{container_id}').stopAuto()" style="padding:4px 12px;font-size:11px;border:1px solid var(--border);border-radius:6px;background:var(--bg-raised);color:var(--text);cursor:pointer;transition:var(--transition);font-family:var(--font-sans);">停止</button>
</div>
<canvas id="{container_id}" style="width:100%;min-height:460px;display:block;border-radius:9px;background:var(--bg-card,#18181b);"></canvas>
<script>
(function(){{
var cnv=document.getElementById("{container_id}");
if(!cnv)return;
var gl=cnv.getContext("webgl2")||cnv.getContext("webgl")||cnv.getContext("experimental-webgl");
if(!gl)return;

var vertexData=new Float32Array({vdata_json});
var triCount={face_count};

// ── Shaders ──
var vs=gl.createShader(gl.VERTEX_SHADER);
gl.shaderSource(vs,'attribute vec3 aPos;attribute float aVal;uniform mat4 uMVP;varying float vVal;void main(){{gl_Position=uMVP*vec4(aPos,1.0);vVal=aVal;}}');
gl.compileShader(vs);
if(!gl.getShaderParameter(vs,gl.COMPILE_STATUS)){{return;}}

var fs=gl.createShader(gl.FRAGMENT_SHADER);
gl.shaderSource(fs,'precision mediump float;varying float vVal;uniform float uVmin;uniform float uVrng;void main(){{float t=clamp((vVal-uVmin)/uVrng,0.0,1.0);vec3 c;if(t<0.16){{float s=t/0.16;c=mix(vec3(.0196,.0196,.1176),vec3(0.,.3922,.7843),s);}}else if(t<0.33){{float s=(t-0.16)/0.17;c=mix(vec3(0.,.3922,.7843),vec3(0.,.7843,1.),s);}}else if(t<0.5){{float s=(t-0.33)/0.17;c=mix(vec3(0.,.7843,1.),vec3(0.,1.,0.),s);}}else if(t<0.66){{float s=(t-0.5)/0.16;c=mix(vec3(0.,1.,0.),vec3(1.,.8627,0.),s);}}else if(t<0.83){{float s=(t-0.66)/0.17;c=mix(vec3(1.,.8627,0.),vec3(1.,.4706,0.),s);}}else{{float s=(t-0.83)/0.17;c=mix(vec3(1.,.4706,0.),vec3(1.,1.,1.),s);}}gl_FragColor=vec4(c,1.0);}}');
gl.compileShader(fs);
if(!gl.getShaderParameter(fs,gl.COMPILE_STATUS)){{return;}}

var prog=gl.createProgram();
gl.attachShader(prog,vs);
gl.attachShader(prog,fs);
gl.linkProgram(prog);
gl.useProgram(prog);

// ── Buffers ──
var vbo=gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER,vbo);
gl.bufferData(gl.ARRAY_BUFFER,vertexData,gl.STATIC_DRAW);

var stride=16;
var aPos=gl.getAttribLocation(prog,"aPos");
gl.enableVertexAttribArray(aPos);
gl.vertexAttribPointer(aPos,3,gl.FLOAT,false,stride,0);
var aVal=gl.getAttribLocation(prog,"aVal");
gl.enableVertexAttribArray(aVal);
gl.vertexAttribPointer(aVal,1,gl.FLOAT,false,stride,12);

// ── Uniforms ──
var uMVP=gl.getUniformLocation(prog,"uMVP");
var uVmin=gl.getUniformLocation(prog,"uVmin");
var uVrng=gl.getUniformLocation(prog,"uVrng");
gl.uniform1f(uVmin,{val_min});
gl.uniform1f(uVrng,{val_rng});

// ── Matrix helpers ──
function matMul(a,b){{
var r=new Array(16);
for(var i=0;i<4;i++)for(var j=0;j<4;j++){{var s=0;for(var k=0;k<4;k++)s+=a[i+k*4]*b[k+j*4];r[i+j*4]=s;}}
return r;}}

function axisAngle(ax,ay,az,angle){{
var c=Math.cos(angle),s=Math.sin(angle),t=1-c;
return[t*ax*ax+c,t*ax*ay+s*az,t*ax*az-s*ay,0,
       t*ax*ay-s*az,t*ay*ay+c,t*ay*az+s*ax,0,
       t*ax*az+s*ay,t*ay*az-s*ax,t*az*az+c,0,
       0,0,0,1];}}

function perspective(fov,aspect,near,far){{
var f=1.0/Math.tan(fov/2);
return[f/aspect,0,0,0,
       0,f,0,0,
       0,0,(far+near)/(near-far),-1,
       0,0,(2*far*near)/(near-far),0];}}

// ── State ──
var maxR={max_radius:.4f};
var camDist={camera_dist:.1f};
var zoom={initial_zoom:.1f};
var M=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
var M0=M.slice();
var dragging=false,lastSx=0,lastSy=0;
var autoRAF=0;

function startAuto(){{if(!autoRAF)autoRAF=requestAnimationFrame(autoFrame);}}
function stopAuto(){{if(autoRAF){{cancelAnimationFrame(autoRAF);autoRAF=0;}}}}
function autoFrame(){{M=matMul(axisAngle(0,0,1,0.008),M);draw();autoRAF=requestAnimationFrame(autoFrame);}}
function resetView(){{stopAuto();M=M0.slice();zoom={initial_zoom:.1f};draw();}}

var W,H,projMat;
function resize(){{
var w=Math.max(cnv.clientWidth||800,400);
var h=Math.max(w*0.75,350);
cnv.width=w;cnv.height=h;
gl.viewport(0,0,w,h);
var fov=Math.atan(maxR/(camDist/zoom))*2;
projMat=perspective(fov,w/h,0.1,100);
W=w;H=h;
draw();
}}

function draw(){{
var d=camDist/zoom;
var viewMat=[1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,-d,1];
var mv=matMul(viewMat,M);
var mvp=matMul(projMat,mv);
gl.uniformMatrix4fv(uMVP,false,mvp);
var cs=getComputedStyle(document.documentElement);
var bg=cs.getPropertyValue('--bg-card').trim()||'#18181b';
var r=parseInt(bg.slice(1,3),16)/255,g=parseInt(bg.slice(3,5),16)/255,b=parseInt(bg.slice(5,7),16)/255;
gl.clearColor(r,g,b,1);
gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
gl.enable(gl.DEPTH_TEST);
gl.drawArrays(gl.TRIANGLES,0,triCount*3);
}}

function mapToSphere(x,y){{
var r=Math.min(W,H)*0.5;
var sx=(x-W/2)/r, sy=-(y-H/2)/r;
var len=Math.sqrt(sx*sx+sy*sy);
if(len>1){{sx/=len;sy/=len;len=1;}}
return[sx,sy,Math.sqrt(Math.max(0,1-len*len))];}}

// ── Events ──
cnv.addEventListener("mousedown",function(e){{stopAuto();dragging=true;var r=cnv.getBoundingClientRect();lastSx=e.clientX-r.left;lastSy=e.clientY-r.top;cnv.style.cursor="grabbing";}});
window.addEventListener("mouseup",function(){{dragging=false;cnv.style.cursor="grab";}});
window.addEventListener("mousemove",function(e){{
if(!dragging)return;
var r=cnv.getBoundingClientRect();
var sx=e.clientX-r.left,sy=e.clientY-r.top;
var p0=mapToSphere(lastSx,lastSy);
var p1=mapToSphere(sx,sy);
var ax=p0[1]*p1[2]-p0[2]*p1[1], ay=p0[2]*p1[0]-p0[0]*p1[2], az=p0[0]*p1[1]-p0[1]*p1[0];
var len=Math.sqrt(ax*ax+ay*ay+az*az);
if(len>1e-6){{ax/=len;ay/=len;az/=len;var dot=Math.max(-1,Math.min(1,p0[0]*p1[0]+p0[1]*p1[1]+p0[2]*p1[2]));M=matMul(axisAngle(ax,ay,az,Math.acos(dot)),M);}}
lastSx=sx;lastSy=sy;
draw();
}});
cnv.addEventListener("wheel",function(e){{e.preventDefault();zoom*=e.deltaY>0?0.9:1.1;zoom=Math.max(0.15,Math.min(8,zoom));resize();}});
cnv.addEventListener("touchstart",function(e){{stopAuto();if(e.touches.length==1){{dragging=true;var r=cnv.getBoundingClientRect();lastSx=e.touches[0].clientX-r.left;lastSy=e.touches[0].clientY-r.top;}}}});
cnv.addEventListener("touchmove",function(e){{
if(!dragging||e.touches.length!=1)return;
var r=cnv.getBoundingClientRect();
var sx=e.touches[0].clientX-r.left,sy=e.touches[0].clientY-r.top;
var p0=mapToSphere(lastSx,lastSy),p1=mapToSphere(sx,sy);
var ax=p0[1]*p1[2]-p0[2]*p1[1],ay=p0[2]*p1[0]-p0[0]*p1[2],az=p0[0]*p1[1]-p0[1]*p1[0];
var len=Math.sqrt(ax*ax+ay*ay+az*az);
if(len>1e-6){{ax/=len;ay/=len;az/=len;var dot=Math.max(-1,Math.min(1,p0[0]*p1[0]+p0[1]*p1[1]+p0[2]*p1[2]));M=matMul(axisAngle(ax,ay,az,Math.acos(dot)),M);}}
lastSx=sx;lastSy=sy;
draw();
}});
cnv.addEventListener("touchend",function(){{dragging=false;}});
window.addEventListener("resize",resize);

// ── Init ──
M=matMul(axisAngle(0,1,0,0.4),M);
M=matMul(axisAngle(1,0,0,-0.5),M);
M0=M.slice();
cnv.resetView=resetView;
cnv.startAuto=startAuto;
cnv.stopAuto=stopAuto;
cnv.style.cursor="grab";
resize();
}})();
</script>'''
    return js


def render_3d_farfield_lazy(data: dict[str, Any], container_id: str = "ff3d") -> str:
    """Render 3D farfield with raw data embedded as JSON. JS computes vertices on-demand (file:// safe)."""
    xpos = data.get("xpositions", [])
    ypos = data.get("ypositions", [])
    gain = data.get("data", [])
    if not xpos or not ypos or not gain:
        return '<div class="chart-panel"><p>\u65e0\u53ef\u7528\u7684\u8fdc\u573a\u6570\u636e\uff0c\u65e0\u6cd5\u6e32\u67d3 3D \u89c6\u56fe</p></div>'

    ny = len(xpos)
    nx = len(ypos)

    # Embed raw data only — JS will compute vertices on toggle
    xpos_json = json.dumps(xpos, separators=(",", ":"))
    ypos_json = json.dumps(ypos, separators=(",", ":"))
    gain_json = json.dumps(gain, separators=(",", ":"))

    js = f'''<div class="ff3d-controls" style="display:flex;gap:8px;margin-bottom:8px;">
<button onclick="FF3D_init('{container_id}')" style="padding:4px 12px;font-size:11px;border:1px solid var(--border);border-radius:6px;background:var(--bg-raised);color:var(--text);cursor:pointer;transition:var(--transition);font-family:var(--font-sans);">加载 3D</button>
<button id="{container_id}_btn_reset" onclick="document.getElementById('{container_id}').resetView()" style="display:none;padding:4px 12px;font-size:11px;border:1px solid var(--border);border-radius:6px;background:var(--bg-raised);color:var(--text);cursor:pointer;font-family:var(--font-sans);">重置</button>
<button id="{container_id}_btn_auto" onclick="document.getElementById('{container_id}').startAuto()" style="display:none;padding:4px 12px;font-size:11px;border:1px solid var(--border);border-radius:6px;background:var(--bg-raised);color:var(--text);cursor:pointer;font-family:var(--font-sans);">旋转</button>
<button id="{container_id}_btn_stop" onclick="document.getElementById('{container_id}').stopAuto()" style="display:none;padding:4px 12px;font-size:11px;border:1px solid var(--border);border-radius:6px;background:var(--bg-raised);color:var(--text);cursor:pointer;font-family:var(--font-sans);">停止</button>
</div>
<canvas id="{container_id}" style="width:100%;min-height:460px;display:block;border-radius:9px;background:var(--bg-card,#18181b);"></canvas>
<div id="{container_id}_status" style="text-align:center;padding:8px;color:var(--text-muted);font-size:11px;">点击"加载 3D"渲染方向图</div>
<script type="application/json" id="{container_id}_data">
{{"x":{xpos_json},"y":{ypos_json},"g":{gain_json}}}
</script>'''
    return js


# ── Shared JS: initializes any lazy 3D container on demand ──
FF3D_SHARED_JS = r'''
<script>
var FF3D_REGISTRY={};
function FF3D_init(cid){
    var cnv=document.getElementById(cid);
    var status=document.getElementById(cid+"_status");
    var btnReset=document.getElementById(cid+"_btn_reset");
    var btnAuto=document.getElementById(cid+"_btn_auto");
    var btnStop=document.getElementById(cid+"_btn_stop");
    if(!cnv||!status)return;
    if(FF3D_REGISTRY[cid]){status.textContent="已渲染";return;}

    var raw;
    try{raw=JSON.parse(document.getElementById(cid+"_data").textContent);}catch(e){status.textContent="数据解析失败";return;}
    var xpos=raw.x||[],ypos=raw.y||[],gain=raw.g||[];
    if(!xpos.length||!ypos.length||!gain.length){status.textContent="远场数据无效";return;}

    var ny=xpos.length,nx=ypos.length;
    var rawVals=[],validVals=[];
    for(var i=0;i<ny;i++){for(var j=0;j<nx;j++){
        var g=(j<gain.length&&i<gain[j].length)?gain[j][i]:null;
        if(g!==null){var v=parseFloat(g);rawVals.push(v);validVals.push(v);}else{rawVals.push(null);}
    }}
    if(!validVals.length){status.textContent="无有效增益值";return;}
    var valMin=Math.min.apply(null,validVals),valMax=Math.max.apply(null,validVals);
    var valRng=Math.max(valMax-valMin,1);

    var vertices=[],values=[];
    var maxR=0;
    var PI=Math.PI;
    for(var i=0;i<ny;i++){for(var j=0;j<nx;j++){
        var g=rawVals[i*nx+j];
        var r=g!==null?(g-valMin)/valRng*4.5+0.3:0.1;
        if(g!==null&&r>maxR)maxR=r;
        var th=xpos[i]*PI/180,ph=ypos[j]*PI/180;
        vertices.push([r*Math.sin(th)*Math.cos(ph),r*Math.sin(th)*Math.sin(ph),r*Math.cos(th)]);
        values.push(g);
    }}

    var faces=[];
    for(var i=0;i<ny-1;i++)for(var j=0;j<nx-1;j++){
        var a=i*nx+j,b=a+1,c=a+nx,d=c+1;
        var va=values[a],vb=values[b],vc=values[c],vd=values[d];
        if(va!==null&&vb!==null&&vc!==null)faces.push([a,b,c,(va+vb+vc)/3]);
        if(vb!==null&&vd!==null&&vc!==null)faces.push([b,d,c,(vb+vd+vc)/3]);
    }
    if(nx>=3)for(var i=0;i<ny-1;i++){
        var a=i*nx+(nx-1),b=i*nx,c=(i+1)*nx+(nx-1),d=(i+1)*nx;
        var va=values[a],vb=values[b],vc=values[c],vd=values[d];
        if(va!==null&&vb!==null&&vc!==null)faces.push([a,b,c,(va+vb+vc)/3]);
        if(vb!==null&&vd!==null&&vc!==null)faces.push([b,d,c,(vb+vd+vc)/3]);
    }
    if(!faces.length){status.textContent="无有效网格";return;}

    var vdata=[];
    for(var f=0;f<faces.length;f++){var tri=faces[f];for(var k=0;k<3;k++){var v=vertices[tri[k]];vdata.push(v[0],v[1],v[2],tri[3]);}}

    var gl=cnv.getContext("webgl2")||cnv.getContext("webgl")||cnv.getContext("experimental-webgl");
    if(!gl){status.textContent="WebGL 不可用";return;}
    status.style.display="none";

    var vertexData=new Float32Array(vdata);
    var triCount=faces.length;
    var camDist=Math.max(maxR*2.5,6);
    var zoom=1.0;

    var vs=gl.createShader(gl.VERTEX_SHADER);
    gl.shaderSource(vs,'attribute vec3 aPos;attribute float aVal;uniform mat4 uMVP;varying float vVal;void main(){gl_Position=uMVP*vec4(aPos,1.0);vVal=aVal;}');
    gl.compileShader(vs);
    var fs=gl.createShader(gl.FRAGMENT_SHADER);
    gl.shaderSource(fs,'precision mediump float;varying float vVal;uniform float uVmin;uniform float uVrng;void main(){float t=clamp((vVal-uVmin)/uVrng,0.0,1.0);vec3 c;if(t<0.16){float s=t/0.16;c=mix(vec3(.0196,.0196,.1176),vec3(0.,.3922,.7843),s);}else if(t<0.33){float s=(t-0.16)/0.17;c=mix(vec3(0.,.3922,.7843),vec3(0.,.7843,1.),s);}else if(t<0.5){float s=(t-0.33)/0.17;c=mix(vec3(0.,.7843,1.),vec3(0.,1.,0.),s);}else if(t<0.66){float s=(t-0.5)/0.16;c=mix(vec3(0.,1.,0.),vec3(1.,.8627,0.),s);}else if(t<0.83){float s=(t-0.66)/0.17;c=mix(vec3(1.,.8627,0.),vec3(1.,.4706,0.),s);}else{float s=(t-0.83)/0.17;c=mix(vec3(1.,.4706,0.),vec3(1.,1.,1.),s);}gl_FragColor=vec4(c,1.0);}');
    gl.compileShader(fs);
    var prog=gl.createProgram();
    gl.attachShader(prog,vs);gl.attachShader(prog,fs);gl.linkProgram(prog);gl.useProgram(prog);

    var vbo=gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER,vbo);
    gl.bufferData(gl.ARRAY_BUFFER,vertexData,gl.STATIC_DRAW);
    var stride=16;
    var aPos=gl.getAttribLocation(prog,"aPos");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos,3,gl.FLOAT,false,stride,0);
    var aVal=gl.getAttribLocation(prog,"aVal");
    gl.enableVertexAttribArray(aVal);
    gl.vertexAttribPointer(aVal,1,gl.FLOAT,false,stride,12);

    var uMVP=gl.getUniformLocation(prog,"uMVP");
    var uVmin=gl.getUniformLocation(prog,"uVmin");
    var uVrng=gl.getUniformLocation(prog,"uVrng");
    gl.uniform1f(uVmin,valMin);
    gl.uniform1f(uVrng,valRng);

    function matMul(a,b){var r=new Array(16);for(var i=0;i<4;i++)for(var j=0;j<4;j++){var s=0;for(var k=0;k<4;k++)s+=a[i+k*4]*b[k+j*4];r[i+j*4]=s;}return r;}
    function axisAngle(ax,ay,az,angle){var c=Math.cos(angle),s=Math.sin(angle),t=1-c;return[t*ax*ax+c,t*ax*ay+s*az,t*ax*az-s*ay,0,t*ax*ay-s*az,t*ay*ay+c,t*ay*az+s*ax,0,t*ax*az+s*ay,t*ay*az-s*ax,t*az*az+c,0,0,0,0,1];}
    function perspective(fov,aspect,near,far){var f=1.0/Math.tan(fov/2);return[f/aspect,0,0,0,0,f,0,0,0,0,(far+near)/(near-far),-1,0,0,(2*far*near)/(near-far),0];}

    var M=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
    var M0=M.slice();
    var dragging=false,lastSx=0,lastSy=0;
    var autoRAF=0;

    function startAuto(){if(!autoRAF)autoRAF=requestAnimationFrame(autoFrame);}
    function stopAuto(){if(autoRAF){cancelAnimationFrame(autoRAF);autoRAF=0;}}
    function autoFrame(){M=matMul(axisAngle(0,0,1,0.008),M);draw();autoRAF=requestAnimationFrame(autoFrame);}
    function resetView(){stopAuto();M=M0.slice();zoom=1.0;draw();}

    var W,H,projMat;
    function resize(){
        var w=Math.max(cnv.clientWidth||800,400);
        var h=Math.max(w*0.75,350);
        cnv.width=w;cnv.height=h;
        gl.viewport(0,0,w,h);
        var fov=Math.atan(maxR/(camDist/zoom))*2;
        projMat=perspective(fov,w/h,0.1,100);
        W=w;H=h;
        draw();
    }
    function draw(){
        var d=camDist/zoom;
        var viewMat=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,-d,1];
        var mv=matMul(viewMat,M);
        var mvp=matMul(projMat,mv);
        gl.uniformMatrix4fv(uMVP,false,mvp);
        var cs=getComputedStyle(document.documentElement);
        var bg=cs.getPropertyValue('--bg-card').trim()||'#18181b';
        var br=parseInt(bg.slice(1,3),16)/255,bg2=parseInt(bg.slice(3,5),16)/255,bb=parseInt(bg.slice(5,7),16)/255;
        gl.clearColor(br,bg2,bb,1);
        gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
        gl.enable(gl.DEPTH_TEST);
        gl.drawArrays(gl.TRIANGLES,0,triCount*3);
    }
    function mapToSphere(x,y){
        var r=Math.min(W,H)*0.5;
        var sx=(x-W/2)/r,sy=-(y-H/2)/r;
        var len=Math.sqrt(sx*sx+sy*sy);
        if(len>1){sx/=len;sy/=len;len=1;}
        return[sx,sy,Math.sqrt(Math.max(0,1-len*len))];
    }

    cnv.addEventListener("mousedown",function(e){stopAuto();dragging=true;var r=cnv.getBoundingClientRect();lastSx=e.clientX-r.left;lastSy=e.clientY-r.top;cnv.style.cursor="grabbing";});
    window.addEventListener("mouseup",function(){dragging=false;cnv.style.cursor="grab";});
    window.addEventListener("mousemove",function(e){
        if(!dragging)return;
        var r=cnv.getBoundingClientRect();
        var sx=e.clientX-r.left,sy=e.clientY-r.top;
        var p0=mapToSphere(lastSx,lastSy),p1=mapToSphere(sx,sy);
        var ax=p0[1]*p1[2]-p0[2]*p1[1],ay=p0[2]*p1[0]-p0[0]*p1[2],az=p0[0]*p1[1]-p0[1]*p1[0];
        var len=Math.sqrt(ax*ax+ay*ay+az*az);
        if(len>1e-6){ax/=len;ay/=len;az/=len;var dot=Math.max(-1,Math.min(1,p0[0]*p1[0]+p0[1]*p1[1]+p0[2]*p1[2]));M=matMul(axisAngle(ax,ay,az,Math.acos(dot)),M);}
        lastSx=sx;lastSy=sy;draw();
    });
    cnv.addEventListener("wheel",function(e){e.preventDefault();zoom*=e.deltaY>0?0.9:1.1;zoom=Math.max(0.15,Math.min(8,zoom));resize();});
    window.addEventListener("resize",resize);

    M=matMul(axisAngle(0,1,0,0.4),M);
    M=matMul(axisAngle(1,0,0,-0.5),M);
    M0=M.slice();
    cnv.resetView=resetView;
    cnv.startAuto=startAuto;
    cnv.stopAuto=stopAuto;
    cnv.style.cursor="grab";
    btnReset.style.display="";btnAuto.style.display="";btnStop.style.display="";
    FF3D_REGISTRY[cid]=true;
    resize();
}
</script>
'''
