"""Embedded offline review controls. No network or filesystem write privilege."""

SCRIPT = r'''
const metadataNode=document.getElementById('audit-metadata');
const metadata=JSON.parse(metadataNode.textContent);
let registrationDirty=false;
function sourceTransform(){
  if(!source)return;
  const reg=metadata.source_registration;
  const x=Number(document.getElementById('source-x').value),y=Number(document.getElementById('source-y').value);
  const width=Number(document.getElementById('source-width').value),angle=Number(document.getElementById('source-angle').value);
  const sx=x-Number(svg.dataset.x0),sy=Number(svg.dataset.y1)-y;
  source.setAttribute('x',sx);source.setAttribute('y',sy);
  source.setAttribute('width',width);source.setAttribute('height',width*reg.pixel_height/reg.pixel_width);
  source.setAttribute('transform',`rotate(${-angle} ${sx} ${sy})`);
  source.style.opacity=String(Number(document.getElementById('source-opacity').value)/100);
}
function download(text,name,type){
  const a=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type}));
  a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function status(text){document.getElementById('approval-status').textContent=text;}
document.querySelectorAll('[data-registration-control]').forEach(e=>e.addEventListener('input',()=>{
  if(e.id!=='source-calibrated')document.getElementById('source-calibrated').checked=false;
  registrationDirty=true;sourceTransform();status('Registration changed. Recheck calibration, then save and reopen the audit before requesting approval.');
}));
const saved=metadata.review_state||{};
if(saved.dimensions){document.getElementById('toggle-dimensions').checked=true;document.body.classList.add('show-dimensions');}
for(const box of document.querySelectorAll('[data-net-toggle]')){
  if((saved.hidden_nets||[]).includes(box.dataset.netToggle)){box.checked=false;box.dispatchEvent(new Event('change'));}
}
document.getElementById('save-registration').addEventListener('click',()=>{
  const updated=JSON.parse(JSON.stringify(metadata));
  if(source){
    const reg=updated.source_registration;
    for(const [field,id] of [['x','source-x'],['y','source-y'],['physical_width','source-width'],['rotation_deg','source-angle']])reg[field]=Number(document.getElementById(id).value);
    reg.citation=document.getElementById('source-citation').value.trim();
    reg.method=document.getElementById('source-method').value.trim();
    reg.calibrated=document.getElementById('source-calibrated').checked;
    if(![reg.x,reg.y,reg.physical_width,reg.rotation_deg].every(Number.isFinite)||reg.physical_width<=0||!reg.citation||!reg.method){status('Enter finite registration, positive width, source citation and calibration method.');return;}
  }
  updated.review_state={dimensions:document.getElementById('toggle-dimensions').checked,
    hidden_nets:[...document.querySelectorAll('[data-net-toggle]')].filter(e=>!e.checked).map(e=>e.dataset.netToggle)};
  const clone=document.documentElement.cloneNode(true);
  clone.querySelectorAll('.modal-backdrop,.toast').forEach(e=>e.hidden=true);
  clone.querySelector('#audit-metadata').textContent=JSON.stringify(updated).replace(/<\//g,'<\\/');
  for(const input of clone.querySelectorAll('input')){
    const live=input.id?document.getElementById(input.id):null;
    if(!live||input.type==='file')continue;
    input.setAttribute('value',live.value);
    if(live.checked)input.setAttribute('checked','');else input.removeAttribute('checked');
  }
  clone.querySelector('#approval-status').textContent='Reopened artifact required; this file contains the saved registration.';
  download('<!doctype html>\n'+clone.outerHTML,'audit-calibrated.html','text/html');
  status('Saved audit-calibrated.html. Open that file and review it before exporting a request.');
});
document.getElementById('export-approval').addEventListener('click',async()=>{
  try{
    if(registrationDirty)throw Error('Save and reopen the changed audit first.');
    if(metadata.drc_status!=='pass')throw Error('DRC must pass.');
    if(source&&!metadata.source_registration.calibrated)throw Error('Calibrate the source and save/reopen first.');
    const file=document.getElementById('audit-file').files[0];
    if(!file)throw Error('Choose this opened HTML file to bind its exact bytes.');
    const bytes=await file.arrayBuffer(),text=new TextDecoder().decode(bytes);
    const parsed=new DOMParser().parseFromString(text,'text/html');
    const fileMetadata=JSON.parse(parsed.querySelector('#audit-metadata').textContent);
    if(JSON.stringify(fileMetadata)!==JSON.stringify(metadata))throw Error('Selected file is not the opened audit metadata.');
    const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
    const ranges={};
    for(const row of document.querySelectorAll('[data-range-name]')){
      if(!row.querySelector('input[type=checkbox]').checked)continue;
      const inputs=[...row.querySelectorAll('input[type=number]')];
      if(inputs.some(e=>e.value.trim()===''))throw Error('Enter explicit bounds: '+row.dataset.rangeName);
      const v=inputs.map(e=>Number(e.value));
      if(v.length!==2||!v.every(Number.isFinite)||v[0]>v[1])throw Error('Invalid range: '+row.dataset.rangeName);
      ranges[row.dataset.rangeName]=v;
    }
    const request={schema_version:1,kind:'cst-approval-request',artifact_id:metadata.artifact_id,
      audit_sha256:hash,topology_hash:metadata.topology_hash,model_intent_id:metadata.model_intent_id,ranges};
    document.getElementById('approval-request-preview').textContent=JSON.stringify(request,null,2);
    download(JSON.stringify(request,null,2)+'\n','approval-request.json','application/json');
    status('Request exported. Approval is not granted; cst_approve requires authenticated human confirmation.');
  }catch(error){status(error.message);}
});
sourceTransform();
'''
