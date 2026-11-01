const $=s=>document.querySelector(s);
const state={org:null,orgs:[]};
async function api(path,opts={}){
  const headers={'Content-Type':'application/json',...(opts.headers||{})};
  if(state.org) headers['X-Organisation-ID']=state.org;
  const response=await fetch('/api/v1'+path,{...opts,credentials:'same-origin',headers});
  const data=response.status===204?null:await response.json().catch(()=>({detail:response.statusText}));
  if(!response.ok) throw new Error(data?.detail||'Request failed ('+response.status+')');
  return data;
}
function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');window.setTimeout(()=>el.classList.remove('show'),3200);}
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function clearWorkspace(){
  ['objectCount','appCount','workflowCount','publishedCount'].forEach(id=>$('#'+id).textContent='0');
  ['objectList','appList','workflowList'].forEach(id=>$('#'+id).replaceChildren());
  $('#recordCount').textContent='0 RECORDS';$('#recordList').textContent='Select an organisation or load the supplier demo to view records.';
  $('#auditList').textContent='No activity yet.';
}
async function loadOrgs(){
  state.orgs=await api('/organisations');
  const select=$('#orgSelect'),previous=state.org;
  select.innerHTML='<option value="">Select organisation</option>'+state.orgs.map(o=>'<option value="'+esc(o.id)+'">'+esc(o.name)+'</option>').join('');
  if(previous&&state.orgs.some(o=>o.id===previous)){select.value=previous;}
  else if(state.orgs.length){state.org=state.orgs[0].id;select.value=state.org;}
  else{state.org=null;select.value='';clearWorkspace();}
}
async function refresh(){
  if(!state.org){clearWorkspace();return;}
  const [objects,apps,workflows,audit]=await Promise.all([
    api('/objects'),api('/apps'),api('/workflows'),api('/audit')
  ]);
  $('#objectCount').textContent=objects.length;$('#appCount').textContent=apps.length;
  $('#workflowCount').textContent=workflows.length;
  $('#publishedCount').textContent=apps.filter(a=>a.status==='published').length;
  $('#objectList').innerHTML=objects.slice(0,5).map(o=>'<div class="item"><b>'+esc(o.label)+'</b><span class="tag">'+esc(o.key)+'</span></div>').join('')||'<small class="muted">No data models yet.</small>';
  $('#appList').innerHTML=apps.slice(0,5).map(a=>'<div class="item"><span><b>'+esc(a.name)+'</b><small class="tag"> '+esc(a.status)+' · v'+esc(a.version)+'</small></span>'+(a.status==='published'?'':'<button type="button" class="mini-action" data-publish="'+esc(a.id)+'">Publish metadata</button>')+'</div>').join('')||'<small class="muted">No applications yet.</small>';
  $('#workflowList').innerHTML=workflows.slice(0,5).map(w=>'<div class="item"><span><b>'+esc(w.name)+'</b><small class="tag"> '+(w.enabled?'ENABLED':'DRAFT')+'</small></span>'+(w.enabled?'':'<button type="button" class="mini-action" data-enable="'+esc(w.id)+'">Enable definition</button>')+'</div>').join('')||'<small class="muted">No workflows yet.</small>';
  const groups=await Promise.all(objects.map(async object=>({object,records:await api('/objects/'+encodeURIComponent(object.id)+'/records')})));
  const rows=groups.flatMap(({object,records})=>records.map(record=>({object,record})));
  $('#recordCount').textContent=rows.length+' RECORD'+(rows.length===1?'':'S');
  $('#recordList').innerHTML=rows.length?'<div class="record-table-wrap"><table class="record-table"><thead><tr><th>Data model</th><th>Business record</th><th>Key details</th><th>Created</th></tr></thead><tbody>'+rows.map(({object,record})=>{
    const data=record.data||{},primary=data.company_name||data.name||data.title||record.id;
    const details=Object.entries(data).filter(([key])=>key!==('company_name' in data?'company_name':'name')).slice(0,3).map(([k,v])=>'<span><b>'+esc(k.replaceAll('_',' '))+':</b> '+esc(v)+'</span>').join('<br>');
    return '<tr><td>'+esc(object.label)+'</td><td><b>'+esc(primary)+'</b></td><td>'+details+'</td><td>'+new Date(record.created_at).toLocaleDateString()+'</td></tr>';
  }).join('')+'</tbody></table></div>':'<div class="empty-state">No business records in this workspace yet. Select <b>Load supplier demo</b> to create a working sample dataset.</div>';
  $('#auditList').innerHTML=audit.length?audit.slice(0,10).map(event=>'<div class="audit-row"><span><b>'+esc(event.action)+'</b> · '+esc(event.resource_type)+'</span><time>'+new Date(event.created_at).toLocaleString()+'</time></div>').join(''):'No activity yet.';
}
function field(label,name,placeholder='',value=''){return '<label>'+label+'<input name="'+name+'" placeholder="'+esc(placeholder)+'" value="'+esc(value)+'" required></label>';}
function openModal(kind){
  if(kind!=='org'&&!state.org){toast('Create or select an organisation first.');return;}
  const configs={
    org:{title:'Create organisation',fields:field('Organisation name','name','e.g. Acme Financial')+field('Unique workspace slug','slug','acme-financial'),save:'Create organisation'},
    object:{title:'Create data model',fields:field('Display name','label','Supplier')+field('Object key','key','supplier')+'<label>JSON Schema <span class="hint">Define fields for this business object.</span><textarea name="schema" required>{"type":"object","properties":{"name":{"type":"string"},"email":{"type":"string","format":"email"}}}</textarea></label>',save:'Create data model'},
    app:{title:'Create application',fields:field('Application name','name','Supplier Portal')+'<label>Description<textarea name="description" placeholder="What will this application do?"></textarea></label><label>Application configuration <span class="hint">JSON metadata; this preview does not render or deploy an app.</span><textarea name="config" required>{"navigation":[],"pages":[]}</textarea></label>',save:'Create application'},
    workflow:{title:'Create workflow',fields:field('Workflow name','name','Supplier approval')+'<label>Workflow definition <span class="hint">Definitions are stored, not executed, in this preview.</span><textarea name="definition" required>{"steps":[{"type":"manual_approval","label":"Review request"},{"type":"log","message":"Approved"}]}</textarea></label>',save:'Create workflow'}
  };
  const config=configs[kind];$('#modalTitle').textContent=config.title;$('#fields').innerHTML=config.fields;
  $('#save').textContent=config.save;$('#modalForm').dataset.kind=kind;$('#modal').showModal();
}
$('#modalForm').addEventListener('submit',async event=>{
  if(event.submitter?.value==='cancel')return;
  event.preventDefault();const kind=event.currentTarget.dataset.kind;
  const values=Object.fromEntries(new FormData(event.currentTarget).entries());
  const save=$('#save');save.disabled=true;
  try{
    if(kind==='org'){
      const created=await api('/organisations',{method:'POST',body:JSON.stringify(values)});
      state.org=created.id;await loadOrgs();
    }else if(kind==='object'){
      values.schema=JSON.parse(values.schema);await api('/objects',{method:'POST',body:JSON.stringify(values)});
    }else if(kind==='app'){
      values.config=JSON.parse(values.config);await api('/apps',{method:'POST',body:JSON.stringify(values)});
    }else{
      values.definition=JSON.parse(values.definition);await api('/workflows',{method:'POST',body:JSON.stringify(values)});
    }
    $('#modal').close();await refresh();toast('Created successfully.');
  }catch(error){toast(error.message);}
  finally{save.disabled=false;}
});
$('#newOrg').addEventListener('click',()=>openModal('org'));
$('#quickApp').addEventListener('click',()=>openModal('app'));
document.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>openModal(button.dataset.action)));
$('#orgSelect').addEventListener('change',async event=>{state.org=event.target.value||null;try{await refresh();}catch(error){toast(error.message);}});
$('#refresh').addEventListener('click',()=>refresh().then(()=>toast('Workspace refreshed.')).catch(error=>toast(error.message)));
$('#loadDemo').addEventListener('click',async()=>{
  const button=$('#loadDemo');button.disabled=true;button.textContent='Loading demo…';
  try{
    const result=await api('/demo/supplier-onboarding',{method:'POST'});
    state.org=result.organisation.id;await loadOrgs();$('#orgSelect').value=state.org;
    await refresh();$('#pageTitle').textContent='MOSAIC Demo Workspace';
    toast('Supplier demo ready. '+result.records_created+' new sample records created.');
    $('#records').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(error){toast('Could not load demo: '+error.message);}
  finally{button.disabled=false;button.textContent='Load supplier demo';}
});
document.addEventListener('click',async event=>{
  const publish=event.target.closest('[data-publish]'),enable=event.target.closest('[data-enable]');
  if(!publish&&!enable)return;
  const button=publish||enable;button.disabled=true;
  try{
    if(publish){await api('/apps/'+encodeURIComponent(publish.dataset.publish)+'/publish',{method:'POST'});toast('Application metadata published.');}
    if(enable){await api('/workflows/'+encodeURIComponent(enable.dataset.enable)+'/enable',{method:'POST'});toast('Workflow definition enabled. It is not yet executing.');}
    await refresh();
  }catch(error){toast(error.message);}
  finally{button.disabled=false;}
});
loadOrgs().then(refresh).catch(error=>toast('Workspace could not load: '+error.message));
