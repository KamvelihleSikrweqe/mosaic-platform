const $=s=>document.querySelector(s);
const state={org:null,orgs:[],auth:null,accessToken:null,refreshToken:null,idToken:null,expiresAt:0,authMode:false};
const tokenStore='mosaic.oidc.session';
function b64url(bytes){return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
function randomText(size=32){const bytes=crypto.getRandomValues(new Uint8Array(size));return b64url(bytes);}
async function pkceChallenge(verifier){return b64url(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier)));}
function decodeJwt(token){const part=token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/');const padded=part+'='.repeat((4-part.length%4)%4);return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(padded),c=>c.charCodeAt(0))));}
function decodeBase64Url(value){const raw=value.replace(/-/g,'+').replace(/_/g,'/');return Uint8Array.from(atob(raw+'='.repeat((4-raw.length%4)%4)),c=>c.charCodeAt(0));}
async function validateIdToken(token,expectedNonce){
  const parts=token.split('.');
  if(parts.length!==3)throw new Error('Malformed identity token.');
  const header=JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[0])));
  const claims=JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[1])));
  if(header.alg!=='RS256'||!header.kid)throw new Error('Unsupported identity token signing algorithm.');
  const response=await fetch(state.auth.issuer+'/protocol/openid-connect/certs');
  if(!response.ok)throw new Error('Could not retrieve identity provider signing keys.');
  const jwks=await response.json(),jwk=jwks.keys.find(key=>key.kid===header.kid&&key.use==='sig'&&key.kty==='RSA');
  if(!jwk)throw new Error('Identity token signing key was not found.');
  const key=await crypto.subtle.importKey('jwk',jwk,{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
  const valid=await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,decodeBase64Url(parts[2]),new TextEncoder().encode(parts[0]+'.'+parts[1]));
  const audience=Array.isArray(claims.aud)?claims.aud:[claims.aud];
  if(!valid||claims.iss!==state.auth.issuer||!audience.includes(state.auth.client_id)||Number(claims.exp)*1000<=Date.now()||claims.nonce!==expectedNonce)
    throw new Error('Identity token validation failed.');
  return claims;
}
function saveSession(){sessionStorage.setItem(tokenStore,JSON.stringify({accessToken:state.accessToken,refreshToken:state.refreshToken,idToken:state.idToken,expiresAt:state.expiresAt}));}
function clearSession(){state.accessToken=null;state.refreshToken=null;state.idToken=null;state.expiresAt=0;sessionStorage.removeItem(tokenStore);}
function setSession(tokens){
  state.accessToken=tokens.access_token;state.refreshToken=tokens.refresh_token||state.refreshToken;
  state.idToken=tokens.id_token||state.idToken;state.expiresAt=Date.now()+Number(tokens.expires_in||300)*1000;
  saveSession();
}
async function tokenRequest(params){
  const response=await fetch(state.auth.issuer+'/protocol/openid-connect/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({...params,client_id:state.auth.client_id})});
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(data.error_description||data.error||'Identity provider token exchange failed');
  return data;
}
async function refreshSession(){
  if(!state.refreshToken)throw new Error('Your session has expired. Sign in again.');
  try{setSession(await tokenRequest({grant_type:'refresh_token',refresh_token:state.refreshToken}));}
  catch(error){clearSession();throw new Error('Your session has expired. Please sign in again.');}
}
async function ensureAccessToken(){
  if(state.accessToken&&Date.now()<state.expiresAt-30000)return;
  if(state.refreshToken){await refreshSession();return;}
  throw new Error('Sign in to continue.');
}
async function startLogin(){
  const verifier=randomText(48),stateValue=randomText(24),nonce=randomText(24);
  sessionStorage.setItem('mosaic.oidc.transaction',JSON.stringify({verifier,state:stateValue,nonce}));
  const challenge=await pkceChallenge(verifier);
  const url=new URL(state.auth.issuer+'/protocol/openid-connect/auth');
  url.search=new URLSearchParams({client_id:state.auth.client_id,redirect_uri:state.auth.redirect_uri,response_type:'code',scope:state.auth.scopes.join(' '),state:stateValue,nonce,code_challenge:challenge,code_challenge_method:'S256'});
  location.assign(url);
}
async function handleOidcCallback(){
  const params=new URLSearchParams(location.search),code=params.get('code'),returnedState=params.get('state'),error=params.get('error');
  if(!code&&!error)return false;
  history.replaceState({},document.title,location.pathname+location.hash);
  if(error)throw new Error(params.get('error_description')||error);
  const transaction=JSON.parse(sessionStorage.getItem('mosaic.oidc.transaction')||'null');
  sessionStorage.removeItem('mosaic.oidc.transaction');
  if(!transaction||!returnedState||returnedState!==transaction.state)throw new Error('Login state validation failed. Start sign-in again.');
  const tokens=await tokenRequest({grant_type:'authorization_code',code,redirect_uri:state.auth.redirect_uri,code_verifier:transaction.verifier});
  if(!tokens.id_token)throw new Error('Identity provider did not return an identity token.');
  await validateIdToken(tokens.id_token,transaction.nonce);
  setSession(tokens);
  return true;
}
async function endLogin(){
  const idToken=state.idToken;clearSession();
  const url=new URL(state.auth.issuer+'/protocol/openid-connect/logout');
  url.search=new URLSearchParams({post_logout_redirect_uri:state.auth.redirect_uri,client_id:state.auth.client_id,...(idToken?{id_token_hint:idToken}:{})});
  location.assign(url);
}
function renderAuth(){
  const action=$('#authAction'),status=$('#authStatus');
  if(!state.authMode){action.hidden=true;status.hidden=true;return;}
  action.hidden=false;status.hidden=false;
  const signedIn=Boolean(state.accessToken);
  action.textContent=signedIn?'Sign out':'Sign in';
  status.textContent=signedIn?'Signed in':'Authentication required';
  $('#loadDemo').hidden=true;$('#newOrg').hidden=!signedIn;const demoLink=document.querySelector('nav a[href="/demo/suppliers"]');if(demoLink)demoLink.hidden=true;
  action.onclick=()=>signedIn?endLogin():startLogin().catch(e=>toast(e.message));
}
async function initAuth(){
  const response=await fetch('/api/v1/auth/config');
  const config=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(config.detail||'Could not load authentication settings');
  if(!config.enabled)return;
  state.auth=config;state.authMode=true;
  const stored=JSON.parse(sessionStorage.getItem(tokenStore)||'null');
  if(stored){state.accessToken=stored.accessToken;state.refreshToken=stored.refreshToken;state.idToken=stored.idToken;state.expiresAt=stored.expiresAt||0;}
  const callback=await handleOidcCallback();
  if(!callback&&state.accessToken&&Date.now()>=state.expiresAt-30000){if(state.refreshToken)await refreshSession();else clearSession();}
  renderAuth();
  if(!state.accessToken){document.querySelector('main').classList.add('auth-locked');return false;}
  document.querySelector('main').classList.remove('auth-locked');
  renderAuth();
  return true;
}
async function api(path,opts={}){
  const headers={'Content-Type':'application/json',...(opts.headers||{})};
  if(state.authMode){await ensureAccessToken();headers.Authorization='Bearer '+state.accessToken;}
  if(state.org) headers['X-Organisation-ID']=state.org;
  let response=await fetch('/api/v1'+path,{...opts,credentials:'same-origin',headers});
  if(response.status===401&&state.authMode&&state.refreshToken){await refreshSession();headers.Authorization='Bearer '+state.accessToken;response=await fetch('/api/v1'+path,{...opts,credentials:'same-origin',headers});}
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
  $('#workflowRuns').replaceChildren();
  const [objects,apps,workflows,audit]=await Promise.all([
    api('/objects'),api('/apps'),api('/workflows'),api('/audit')
  ]);
  $('#objectCount').textContent=objects.length;$('#appCount').textContent=apps.length;
  $('#workflowCount').textContent=workflows.length;
  $('#publishedCount').textContent=apps.filter(a=>a.status==='published').length;
  $('#objectList').innerHTML=objects.slice(0,5).map(o=>'<div class="item"><b>'+esc(o.label)+'</b><span class="tag">'+esc(o.key)+'</span></div>').join('')||'<small class="muted">No data models yet.</small>';
  $('#appList').innerHTML=apps.slice(0,5).map(a=>'<div class="item"><span><b>'+esc(a.name)+'</b><small class="tag"> '+esc(a.status)+' · v'+esc(a.version)+'</small></span>'+(a.status==='published'?'':'<button type="button" class="mini-action" data-publish="'+esc(a.id)+'">Publish metadata</button>')+'</div>').join('')||'<small class="muted">No applications yet.</small>';
  $('#workflowList').innerHTML=workflows.slice(0,5).map(w=>'<div class="item workflow-item"><span><b>'+esc(w.name)+'</b><small class="tag"> '+(w.enabled?'ENABLED':'DRAFT')+' · '+(w.definition?.steps?.length||0)+' steps</small></span><span class="workflow-actions">'+(w.enabled?'<button type="button" class="mini-action" data-run="'+esc(w.id)+'">Run</button>':'<button type="button" class="mini-action" data-enable="'+esc(w.id)+'">Enable</button>')+'<button type="button" class="mini-action" data-history="'+esc(w.id)+'">Runs</button></span></div>').join('')||'<small class="muted">No workflows yet.</small>';
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
async function showWorkflowRuns(workflowId){
  const panel=$('#workflowRuns');panel.dataset.workflowId=workflowId;panel.innerHTML='<div class="item"><small class="muted">Loading workflow runs…</small></div>';
  try{
    const runs=await api('/workflows/'+encodeURIComponent(workflowId)+'/runs');
    if(!runs.length){panel.innerHTML='<div class="item"><small class="muted">No runs yet for this workflow.</small></div>';return;}
    panel.innerHTML='<div class="workflow-run-heading">RECENT EXECUTIONS</div>'+runs.map(run=>{
      const steps=(run.step_results||[]).map(step=>'<div class="workflow-step"><span>'+esc(step.type.replaceAll('_',' '))+' · '+esc(step.status)+'</span>'+(step.label?'<small>'+esc(step.label)+'</small>':'')+(step.message?'<small>'+esc(step.message)+'</small>':'')+(step.comment?'<small>Comment: '+esc(step.comment)+'</small>':'')+'</div>').join('');
      const actions=run.status==='waiting_approval'?'<div class="workflow-actions"><button class="mini-action" data-approval="approve" data-run-id="'+esc(run.id)+'">Approve</button><button class="mini-action" data-approval="reject" data-run-id="'+esc(run.id)+'">Reject</button></div>':'';
      return '<article class="workflow-run"><div class="workflow-run-top"><b>'+esc(run.id.slice(0,8))+'</b><span class="tag">'+esc(run.status.replaceAll('_',' ').toUpperCase())+'</span></div><small class="muted">'+new Date(run.created_at).toLocaleString()+'</small>'+steps+ (run.error?'<p class="workflow-error">'+esc(run.error)+'</p>':'')+actions+'</article>';
    }).join('');
  }catch(error){panel.textContent=error.message;}
}
async function startWorkflowRun(workflowId){
  let input={};
  const raw=window.prompt('Workflow input as JSON', '{}');
  if(raw===null)return;
  try{input=JSON.parse(raw);if(!input||Array.isArray(input)||typeof input!=='object')throw Error('Input must be a JSON object.');}
  catch(error){toast('Invalid workflow input: '+error.message);return;}
  const run=await api('/workflows/'+encodeURIComponent(workflowId)+'/runs',{method:'POST',body:JSON.stringify({input,idempotency_key:crypto.randomUUID()})});
  toast('Workflow run '+run.status.replaceAll('_',' ')+'.');
  await showWorkflowRuns(workflowId);
}
async function decideApproval(runId,approved){
  const comment=window.prompt(approved?'Approval comment (optional)':'Reason for rejection (optional)','');
  if(comment===null)return;
  const result=await api('/workflow-runs/'+encodeURIComponent(runId)+'/approval',{method:'POST',body:JSON.stringify({approved,comment})});
  toast(approved?'Approval recorded; workflow resumed.':'Approval rejected; workflow stopped.');
  return result.workflow_id;
}
function field(label,name,placeholder='',value=''){return '<label>'+label+'<input name="'+name+'" placeholder="'+esc(placeholder)+'" value="'+esc(value)+'" required></label>';}
function openModal(kind){
  if(kind!=='org'&&!state.org){toast('Create or select an organisation first.');return;}
  const configs={
    org:{title:'Create organisation',fields:field('Organisation name','name','e.g. Acme Financial')+field('Unique workspace slug','slug','acme-financial'),save:'Create organisation'},
    object:{title:'Create data model',fields:field('Display name','label','Supplier')+field('Object key','key','supplier')+'<label>JSON Schema <span class="hint">Define fields for this business object.</span><textarea name="schema" required>{"type":"object","properties":{"name":{"type":"string"},"email":{"type":"string","format":"email"}}}</textarea></label>',save:'Create data model'},
    app:{title:'Create application',fields:field('Application name','name','Supplier Portal')+'<label>Description<textarea name="description" placeholder="What will this application do?"></textarea></label><label>Application configuration <span class="hint">JSON metadata; this preview does not render or deploy an app.</span><textarea name="config" required>{"navigation":[],"pages":[]}</textarea></label>',save:'Create application'},
    workflow:{title:'Create workflow',fields:field('Workflow name','name','Supplier approval')+'<label>Workflow definition <span class="hint">Supported steps: log and manual_approval. Runs pause for a human decision and continue after approval.</span><textarea name="definition" required>{"steps":[{"type":"manual_approval","label":"Review request"},{"type":"log","message":"Approved"}]}</textarea></label>',save:'Create workflow'}
  };
  const config=configs[kind];$('#modalTitle').textContent=config.title;$('#fields').innerHTML=config.fields;
  $('#save').textContent=config.save;$('#modalForm').dataset.kind=kind;$('#modalForm').dataset.saveLabel=config.save;
  if(kind==='org'){
    const name=$('#fields input[name="name"]'),slug=$('#fields input[name="slug"]');
    slug.pattern='[a-z0-9][a-z0-9-]{0,79}';slug.title='Use lowercase letters, numbers and hyphens; start with a letter or number.';
    name.addEventListener('input',()=>{if(!slug.dataset.edited)slug.value=name.value.trim().toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,80);});
    slug.addEventListener('input',()=>{slug.dataset.edited='true';});
  }
  $('#modal').showModal();
}
let savingModal=false;
async function saveModal(){
  const form=$('#modalForm'),kind=form.dataset.kind,save=$('#save');
  if(savingModal||!form.reportValidity())return;
  const values=Object.fromEntries(new FormData(form).entries());
  savingModal=true;save.disabled=true;save.textContent='Creating…';
  try{
    if(kind==='org'){
      const created=await api('/organisations',{method:'POST',body:JSON.stringify(values)});
      state.org=created.id;
      await loadOrgs();
      $('#orgSelect').value=created.id;
    }else if(kind==='object'){
      values.schema=JSON.parse(values.schema);await api('/objects',{method:'POST',body:JSON.stringify(values)});
    }else if(kind==='app'){
      values.config=JSON.parse(values.config);await api('/apps',{method:'POST',body:JSON.stringify(values)});
    }else{
      values.definition=JSON.parse(values.definition);await api('/workflows',{method:'POST',body:JSON.stringify(values)});
    }
    $('#modal').close();await refresh();toast(kind==='org'?'Organisation created successfully.':'Created successfully.');
  }catch(error){toast(error.message);}
  finally{savingModal=false;save.disabled=false;save.textContent=form.dataset.saveLabel||'Create';}
}
$('#modalForm').addEventListener('submit',event=>{event.preventDefault();saveModal();});
$('#save').addEventListener('click',event=>{event.preventDefault();saveModal();});
$('#modalClose').addEventListener('click',()=>$('#modal').close());
document.querySelectorAll('[data-modal-cancel]').forEach(button=>button.addEventListener('click',()=>$('#modal').close()));
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
  const publish=event.target.closest('[data-publish]'),enable=event.target.closest('[data-enable]'),run=event.target.closest('[data-run]'),history=event.target.closest('[data-history]'),approval=event.target.closest('[data-approval]');
  if(!publish&&!enable&&!run&&!history&&!approval)return;
  const button=publish||enable||run||history||approval;if(button)button.disabled=true;
  try{
    if(publish){await api('/apps/'+encodeURIComponent(publish.dataset.publish)+'/publish',{method:'POST'});toast('Application metadata published.');}
    if(enable){await api('/workflows/'+encodeURIComponent(enable.dataset.enable)+'/enable',{method:'POST'});toast('Workflow enabled and ready to run.');}
    if(run)await startWorkflowRun(run.dataset.run);
    if(history)await showWorkflowRuns(history.dataset.history);
    if(approval){const runId=approval.dataset.runId;const workflowId=await decideApproval(runId,approval.dataset.approval==='approve');if(workflowId){await refresh();await showWorkflowRuns(workflowId);}}
    if(publish||enable)await refresh();
  }catch(error){toast(error.message);}
  finally{if(button)button.disabled=false;}
});
(async()=>{
  try{
    const authenticated=await initAuth();
    if(state.authMode&&!authenticated){toast('Sign in to access your MOSAIC workspaces.');return;}
    renderAuth();
    await loadOrgs();await refresh();
  }catch(error){renderAuth();toast('Authentication/workspace error: '+error.message);}
})();
