"""Interaction layer for the offline CAD workspace (camera changes only)."""
SCRIPT = r'''
const model=JSON.parse(document.getElementById('audit-model').textContent);
let language='zh', selectedNet=null, view='3d', mode='select';
const stage=document.getElementById('cad-stage');
let cad=null,explode=false;
const planBase=svg.getAttribute('viewBox').split(' ').map(Number);
let planBox=[...planBase];
const tr=(zh,en)=>language==='zh'?zh:en;
const terms={assumption:'建模假设',strong_inference:'依据推断',paper_explicit:'来源明确',synthesized:'综合计算',optimized:'优化结果',derived:'公式推导',
 'copper thickness chosen for the fixture':'为验证模型选定的铜厚，需人工确认',
 'trace width under review':'待审阅的走线宽度', 'substrate height':'基板厚度',
 'Neutral two-net microstrip coupon':'双走线微带验证模型'};
document.querySelectorAll('.badge,.review-note,td,.project-title').forEach(e=>{
 if(!e.children.length&&terms[e.textContent.trim()]){e.dataset.en=e.textContent.trim();e.dataset.zh=terms[e.dataset.en];}
});
document.querySelectorAll('.review-note').forEach(e=>{for(const n of [...e.childNodes]){if(n.nodeType===3&&terms[n.textContent.trim()]){const s=document.createElement('span');s.dataset.en=n.textContent.trim();s.dataset.zh=terms[s.dataset.en];e.replaceChild(s,n);}}});
function label(id,zh,en){const e=document.getElementById(id);e.textContent=tr(zh,en);}
function translate(){
 document.documentElement.lang=language==='zh'?'zh-CN':'en';
 document.querySelectorAll('[data-zh]').forEach(e=>e.textContent=language==='zh'?e.dataset.zh:e.dataset.en);
 document.getElementById('language-toggle').textContent=language==='zh'?'中文 / EN':'EN / 中文';
 updateViewLabels();inspect(selectedNet);
}
function updateViewLabels(){
 label('view-name',view==='3d'?'正交立体视图':'平面与来源叠图',view==='3d'?'Orthographic 3D':'2D source/IR overlay');
 label('canvas-hint',view==='3d'?(mode==='pan'?'左键平移 · 滚轮缩放':'左键旋转 · 右键平移 · 滚轮缩放'):mode==='measure'?'点击两点量测距离':'拖动平移 · 滚轮缩放',view==='3d'?(mode==='pan'?'Left: pan · Wheel: zoom':'Left: rotate · Right: pan · Wheel: zoom'):mode==='measure'?'Click two points to measure':'Drag to pan · Scroll to zoom');
 document.getElementById('view-badge').textContent=(view==='3d'?(explode?'EXPLODED':'ORTHO'):'TOP')+' · '+unit;
}
function switchView(next){view=next;document.body.dataset.view=view;document.getElementById('view-2d').hidden=view!=='2d';document.getElementById('view-3d').hidden=view!=='3d';document.querySelectorAll('button[data-view]').forEach(e=>e.classList.toggle('active',e.dataset.view===view));updateViewLabels();if(view==='3d')render3d();if(cad)cad.setActive(view==='3d');}
function setMode(next){mode=next;document.body.dataset.mode=next;stage.classList.toggle('mode-measure',next==='measure');document.querySelectorAll('button[data-mode]').forEach(e=>e.classList.toggle('active',e.dataset.mode===next));if(next==='measure')switchView('2d');if(cad)cad.setPan(next==='pan');updateViewLabels();}
function visible(name){return [...document.querySelectorAll('[data-net-toggle]')].find(e=>e.dataset.netToggle===name)?.checked!==false;}
function property(name,value){const row=document.createElement('div');row.className='property-row';const a=document.createElement('span'),b=document.createElement('span');a.textContent=name;b.textContent=value;row.append(a,b);return row;}
function inspect(name){
 selectedNet=name;
 document.querySelectorAll('[data-net-row]').forEach(e=>e.classList.toggle('selected',e.dataset.netRow===name));
 document.querySelectorAll('.shape').forEach(e=>e.classList.toggle('selected',e.dataset.key.startsWith(name+':')));
 const shapes=model.shapes.filter(s=>!name||s.net===name),props=document.getElementById('selection-properties');props.replaceChildren();
 document.getElementById('selection-title').textContent=name||tr('模型概览','Model overview');
 document.getElementById('inspector-eyebrow').textContent=name?'SELECTED NET':'MODEL OVERVIEW';
 document.getElementById('selection-caption').textContent=name?tr('网络及其所属实体','Net and associated bodies'):tr('先核对结构，再确认建模假设','Check structure before confirming assumptions');
 if(shapes.length){const xs=shapes.flatMap(s=>s.ring.map(p=>p[0])),ys=shapes.flatMap(s=>s.ring.map(p=>p[1])),zs=shapes.flatMap(s=>[s.z0,s.z1]);
  for(const [n,v] of [[tr('宽度 X','Width X'),Math.max(...xs)-Math.min(...xs)],[tr('长度 Y','Length Y'),Math.max(...ys)-Math.min(...ys)],[tr('高度 Z','Height Z'),Math.max(...zs)-Math.min(...zs)]])props.append(property(n,v.toFixed(4)+' '+unit));
  if(name)props.append(property(tr('Z 范围','Z range'),Math.min(...zs).toFixed(4)+' … '+Math.max(...zs).toFixed(4)+' '+unit));
 }
 const net=model.nets.find(n=>n.name===name),layer=model.stackup.find(l=>l.name===net?.layer);
 if(net){props.append(property(tr('所属层','Layer'),net.layer));props.append(property(tr('材料','Material'),net.material||layer?.material||'—'));props.append(property(tr('实体数量','Bodies'),String(shapes.length)));}
 else props.append(property(tr('层叠','Stackup'),String(model.stackup.length)+' '+tr('层','layers')));
 render3d();
}
function render3d(){
 if(!cad){try{cad=CAD3D.createViewer(document.getElementById('three-view'),model,inspect);}catch(error){document.getElementById('three-view').textContent='3D 渲染不可用 / 3D renderer unavailable: '+error.message;throw error;}}
 cad.sync(visible,selectedNet,explode);
}
let start=null,dragged=false;
for(const canvas of [svg]){
 canvas.addEventListener('pointerdown',e=>{if(mode==='measure'&&canvas===svg)return;start={x:e.clientX,y:e.clientY,box:[...planBox],net:e.target.dataset.net||e.target.dataset.key?.split(':')[0]};dragged=false;canvas.setPointerCapture(e.pointerId);});
 canvas.addEventListener('pointermove',e=>{if(canvas===svg){const p=localPoint(e);document.getElementById('cursor-position').textContent=`X ${(p.x+Number(svg.dataset.x0)).toFixed(3)}   Y ${(Number(svg.dataset.y1)-p.y).toFixed(3)}`;}if(!start)return;const dx=e.clientX-start.x,dy=e.clientY-start.y;if(Math.abs(dx)+Math.abs(dy)>3)dragged=true;
  const rect=svg.getBoundingClientRect(),scale=Math.min(rect.width/start.box[2],rect.height/start.box[3]);planBox=[start.box[0]-dx/scale,start.box[1]-dy/scale,start.box[2],start.box[3]];svg.setAttribute('viewBox',planBox.join(' '));
 });
 canvas.addEventListener('pointerup',()=>{const net=start?.net;start=null;if(!dragged&&net&&mode==='select')inspect(net);});canvas.addEventListener('pointercancel',()=>{start=null;});
 canvas.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY<0?1.12:1/1.12);},{passive:false});
}
function zoom(factor){if(view==='3d'){cad.zoom(factor);}else{const w=planBox[2]/factor,h=planBox[3]/factor;if(w<planBase[2]/20||w>planBase[2]*5)return;planBox=[planBox[0]+(planBox[2]-w)/2,planBox[1]+(planBox[3]-h)/2,w,h];svg.setAttribute('viewBox',planBox.join(' '));}}
function reset(){explode=false;planBox=[...planBase];svg.setAttribute('viewBox',planBox.join(' '));render3d();cad.standard('iso');updateViewLabels();}

document.querySelectorAll('button[data-view]').forEach(e=>e.addEventListener('click',()=>switchView(e.dataset.view)));
document.querySelectorAll('button[data-mode]').forEach(e=>e.addEventListener('click',()=>setMode(e.dataset.mode)));
document.querySelectorAll('[data-select-net]').forEach(e=>e.addEventListener('click',()=>inspect(e.dataset.selectNet)));
document.querySelectorAll('.shape').forEach(e=>e.addEventListener('click',()=>{if(mode==='select'&&!dragged)inspect(e.dataset.key.split(':')[0]);}));
document.querySelectorAll('[data-net-toggle]').forEach(e=>e.addEventListener('change',render3d));
document.getElementById('zoom-in').addEventListener('click',()=>zoom(1.2));document.getElementById('zoom-out').addEventListener('click',()=>zoom(1/1.2));
document.getElementById('fit-view').addEventListener('click',()=>view==='3d'?cad.fit():reset());document.getElementById('reset-all').addEventListener('click',reset);
document.getElementById('explode-view').addEventListener('click',()=>{explode=!explode;switchView('3d');updateViewLabels();});
document.getElementById('dimensions-tool').addEventListener('click',()=>{const b=document.getElementById('toggle-dimensions');b.checked=!b.checked;b.dispatchEvent(new Event('change'));switchView('2d');});
document.getElementById('language-toggle').addEventListener('click',()=>{language=language==='zh'?'en':'zh';translate();});
document.querySelectorAll('button[data-panel]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('button[data-panel]').forEach(e=>e.classList.toggle('active',e===b));document.querySelectorAll('.dock-panel').forEach(e=>e.hidden=e.dataset.panel!==b.dataset.panel);}));
document.getElementById('toggle-evidence').addEventListener('click',()=>document.body.classList.toggle('no-evidence'));
document.getElementById('toggle-inspector').addEventListener('click',()=>document.body.classList.toggle('inspector-open'));
function openModal(id){document.getElementById(id).hidden=false;document.getElementById(id).querySelector('button').focus();}
function closeModals(){document.querySelectorAll('.modal-backdrop').forEach(e=>e.hidden=true);}
document.getElementById('open-source').addEventListener('click',()=>{switchView('2d');openModal('source-modal');});document.getElementById('open-approval').addEventListener('click',()=>openModal('approval-modal'));
document.querySelectorAll('[data-close-modal]').forEach(e=>e.addEventListener('click',closeModals));document.querySelectorAll('.modal-backdrop').forEach(e=>e.addEventListener('click',event=>{if(event.target===e)closeModals();}));
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModals();if(e.target.matches('input,textarea'))return;if(e.key.toLowerCase()==='m')setMode('measure');if(e.key.toLowerCase()==='f')reset();});
const messages={
 'Save and reopen the changed audit first.':'请先保存并重新打开已修改的审计文件。',
 'DRC must pass.':'设计规则检查必须通过。',
 'Calibrate the source and save/reopen first.':'请完成来源标定，保存并重新打开审计文件。',
 'Choose this opened HTML file to bind its exact bytes.':'请选择当前审阅的 HTML 文件，以绑定其准确内容。',
 'Selected file is not the opened audit metadata.':'选择的文件与当前审计内容不匹配。',
 'Request exported. Approval is not granted; cst_approve requires authenticated human confirmation.':'批准请求已生成，尚未批准。请通过人工确认入口完成审阅批准。',
 'Registration changed. Recheck calibration, then save and reopen the audit before requesting approval.':'配准已修改。请重新核对标定，保存并重开后再请求批准。',
 'Saved audit-calibrated.html. Open that file and review it before exporting a request.':'已保存审计版本。请打开新文件并审阅，再导出批准请求。',
 'Enter finite registration, positive width, source citation and calibration method.':'请填写有效坐标、正数宽度、来源引用及标定依据。'
};
status=function(text){document.getElementById('approval-status').textContent=language==='zh'?(messages[text]||text):text;const t=document.getElementById('workbench-toast');t.textContent=language==='zh'?(messages[text]||text):text;t.hidden=false;setTimeout(()=>t.hidden=true,5000);};
document.getElementById('cad-standard-view').addEventListener('change',e=>{switchView('3d');cad.standard(e.target.value);});
translate();setMode('select');switchView('3d');
'''
