from pathlib import Path

# Backend changes
p = Path('playlocal_server.py')
s = p.read_text()

if 'SITE_TOKENS = {}' not in s:
    s = s.replace("LOCK = threading.RLock()\n", "LOCK = threading.RLock()\nSITE_TOKENS = {}\nSITE_TOKEN_TTL = 12 * 60 * 60\n", 1)

marker = "\ndef login(account_id, username, password):\n"
if 'def configured_server_accounts():' not in s:
    helper = r'''
def configured_server_accounts():
    out = {}
    for i in range(1, 4):
        username = os.environ.get(f'PLAYLOCAL_ACCOUNT_{i}_USERNAME', '').strip()
        password = os.environ.get(f'PLAYLOCAL_ACCOUNT_{i}_PASSWORD', '')
        if not username or not password:
            continue
        account_id = f'server-{i}'
        out[account_id] = {
            'id': account_id,
            'name': os.environ.get(f'PLAYLOCAL_ACCOUNT_{i}_NAME', f'Account {i}').strip() or f'Account {i}',
            'username': username,
            'password': password,
        }
    return out


def site_auth_required():
    return bool(os.environ.get('COURTFLOW_SITE_PASSWORD', ''))


def public_server_accounts():
    return [{'id': a['id'], 'name': a['name']} for a in configured_server_accounts().values()]


def issue_site_token(password):
    expected = os.environ.get('COURTFLOW_SITE_PASSWORD', '')
    if not expected:
        return {'siteToken': '', 'accounts': public_server_accounts(), 'expiresInSeconds': 0}
    supplied = str(password or '')
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise ApiError('SITE_AUTH_REJECTED', 'Incorrect site password.', 401, True)
    token = secrets.token_urlsafe(32)
    with LOCK:
        SITE_TOKENS[token] = time.time() + SITE_TOKEN_TTL
    return {'siteToken': token, 'accounts': public_server_accounts(), 'expiresInSeconds': SITE_TOKEN_TTL}


def require_site_token(req):
    if not site_auth_required():
        return
    token = str(req.get('siteToken') or '')
    now = time.time()
    with LOCK:
        expired = [k for k, exp in SITE_TOKENS.items() if exp <= now]
        for k in expired:
            SITE_TOKENS.pop(k, None)
        exp = SITE_TOKENS.get(token)
    if not exp or exp <= now:
        raise ApiError('SITE_AUTH_REQUIRED', 'Enter the CourtFlow site password to continue.', 401, True)


def login_server_account(account_id):
    account = configured_server_accounts().get(str(account_id or ''))
    if not account:
        raise ApiError('ACCOUNT_NOT_FOUND', 'That server account is not configured.', 404, True)
    return login(account['id'], account['username'], account['password'])

'''
    s = s.replace(marker, helper + marker, 1)

old_dispatch = '''def dispatch(req):
    if req.get('version') != 1:
        raise ApiError('VERSION', 'CourtFlow protocol version 1 is required.')
    action = req.get('action')
    if action == 'capabilities':
        return {'vendor': 'playlocal', 'idempotency': True, 'reservationHistory': True, 'completeDailyHistory': False, 'slotMinutes': 60}
    if action == 'authenticate':
        return login(req['accountId'], req['username'], req['password'])
    if action == 'availability':
        sess = None
        if req.get('sessionToken') and req.get('accountId'):
            sess = get_session(req['sessionToken'], req['accountId'])
        return availability(req.get('query') or {}, sess=sess)
    if action == 'history':
        return history(req)
    if action == 'court_options':
        return court_options(req)
    if action == 'verify_booking':
        return verify_booking(req)
    if action == 'book':
        return book(req)
    raise ApiError('ACTION', 'Unknown adapter action.')
'''
new_dispatch = '''def dispatch(req):
    if req.get('version') != 1:
        raise ApiError('VERSION', 'CourtFlow protocol version 1 is required.')
    action = req.get('action')
    if action == 'capabilities':
        return {
            'vendor': 'playlocal', 'idempotency': True, 'reservationHistory': True,
            'completeDailyHistory': False, 'slotMinutes': 60,
            'siteAuthRequired': site_auth_required(),
            'serverAccountCount': len(configured_server_accounts()),
        }
    if action == 'site_login':
        return issue_site_token(req.get('sitePassword'))

    require_site_token(req)

    if action == 'accounts':
        return {'accounts': public_server_accounts()}
    if action == 'authenticate':
        if configured_server_accounts():
            return login_server_account(req.get('accountId'))
        return login(req['accountId'], req['username'], req['password'])
    if action == 'availability':
        sess = None
        if req.get('sessionToken') and req.get('accountId'):
            sess = get_session(req['sessionToken'], req['accountId'])
        return availability(req.get('query') or {}, sess=sess)
    if action == 'history':
        return history(req)
    if action == 'court_options':
        return court_options(req)
    if action == 'verify_booking':
        return verify_booking(req)
    if action == 'book':
        return book(req)
    raise ApiError('ACTION', 'Unknown adapter action.')
'''
if old_dispatch in s:
    s = s.replace(old_dispatch, new_dispatch, 1)
elif "if action == 'site_login':" not in s:
    raise SystemExit('dispatch block not found')

p.write_text(s)

# Frontend changes
p = Path('index.html')
h = p.read_text()

if '.site-gate{' not in h:
    h = h.replace('@media(max-width:820px)', '.site-gate{position:fixed;inset:0;background:#f3f6f4;z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px}.site-gate.hidden{display:none}.gate-card{width:min(420px,100%);background:#fff;border:1px solid var(--border);border-radius:18px;padding:22px;box-shadow:0 12px 40px #0002}.gate-card h1{margin:0 0 6px;font-size:25px}.gate-card input{width:100%;border:1px solid #cbd6cf;border-radius:9px;padding:11px;font:inherit;margin:12px 0}\n@media(max-width:820px)', 1)

if 'id="siteGate"' not in h:
    h = h.replace('<body>\n<div class="wrap">', '''<body>
<div id="siteGate" class="site-gate hidden">
  <div class="gate-card">
    <h1>CourtFlow</h1>
    <div class="small">Enter the site password to continue.</div>
    <input id="sitePassword" type="password" autocomplete="current-password" placeholder="Site password">
    <button class="btn primary" id="siteLogin">Unlock</button>
    <div id="siteLoginError" class="bad small" style="margin-top:10px"></div>
  </div>
</div>
<div class="wrap" id="appShell">''', 1)

old_state = "const state={accounts:loadAccounts(),sessions:new Map(),facilities:[],matrix:null,selected:new Set(),plan:[],remoteBookings:[],bookingQueue:[],bookingCursor:0,pendingVerification:null,pendingCheckRunning:false};"
new_state = "const state={accounts:loadAccounts(),sessions:new Map(),facilities:[],matrix:null,selected:new Set(),plan:[],remoteBookings:[],bookingQueue:[],bookingCursor:0,pendingVerification:null,pendingCheckRunning:false,siteToken:sessionStorage.getItem('cf_site_token')||'',serverVault:false};"
if old_state in h:
    h = h.replace(old_state, new_state, 1)

old_rpc = "async function rpc(action,payload={}){const r=await fetch(ADAPTER,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({version:1,action,...payload})});const b=await r.json().catch(()=>null);if(!r.ok||!b?.ok){const e=Error(b?.error?.message||'Adapter request failed');e.code=b?.error?.code||'ADAPTER_ERROR';e.data=b?.error?.data||{};e.definitive=!!b?.error?.definitive;throw e}return b.data}"
new_rpc = "async function rpc(action,payload={},includeSiteToken=true){const body={version:1,action,...payload};if(includeSiteToken&&state.siteToken)body.siteToken=state.siteToken;const r=await fetch(ADAPTER,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const b=await r.json().catch(()=>null);if(!r.ok||!b?.ok){const e=Error(b?.error?.message||'Adapter request failed');e.code=b?.error?.code||'ADAPTER_ERROR';e.data=b?.error?.data||{};e.definitive=!!b?.error?.definitive;if(e.code==='SITE_AUTH_REQUIRED'){state.siteToken='';sessionStorage.removeItem('cf_site_token');showSiteGate()}throw e}return b.data}"
if old_rpc in h:
    h = h.replace(old_rpc, new_rpc, 1)
elif 'includeSiteToken=true' not in h:
    raise SystemExit('rpc block not found')

old_auth = "async function auth(account){if(state.sessions.has(account.id))return state.sessions.get(account.id);const s=await rpc('authenticate',{accountId:account.id,username:account.email,password:account.password});state.sessions.set(account.id,s);return s}"
new_auth = "async function auth(account){if(state.sessions.has(account.id))return state.sessions.get(account.id);const payload=state.serverVault?{accountId:account.id}:{accountId:account.id,username:account.email,password:account.password};const s=await rpc('authenticate',payload);state.sessions.set(account.id,s);return s}"
if old_auth in h:
    h = h.replace(old_auth, new_auth, 1)

old_render = '''function renderAccounts(){
  $('accountList').innerHTML=state.accounts.length?state.accounts.map((a,i)=>`<div class="account-row"><div><b>${i+1}. ${esc(a.name)}</b><div class="small">${esc(a.email)}</div></div><button class="btn danger" data-remove="${esc(a.id)}">Remove</button></div>`).join(''):'<div class="small">No accounts saved yet.</div>';
  document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{state.accounts=state.accounts.filter(a=>a.id!==b.dataset.remove);state.sessions.delete(b.dataset.remove);saveAccounts();renderAccounts();log('Account removed.')});
}
'''
new_render = '''function renderAccounts(){
  if(state.serverVault){
    $('accountList').innerHTML=state.accounts.length?state.accounts.map((a,i)=>`<div class="account-row"><div><b>${i+1}. ${esc(a.name)}</b><div class="small">Credentials stored securely on the server</div></div></div>`).join(''):'<div class="small">No server accounts are configured.</div>';
    return;
  }
  $('accountList').innerHTML=state.accounts.length?state.accounts.map((a,i)=>`<div class="account-row"><div><b>${i+1}. ${esc(a.name)}</b><div class="small">${esc(a.email)}</div></div><button class="btn danger" data-remove="${esc(a.id)}">Remove</button></div>`).join(''):'<div class="small">No accounts saved yet.</div>';
  document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{state.accounts=state.accounts.filter(a=>a.id!==b.dataset.remove);state.sessions.delete(b.dataset.remove);saveAccounts();renderAccounts();log('Account removed.')});
}
'''
if old_render in h:
    h = h.replace(old_render, new_render, 1)
elif 'Credentials stored securely on the server' not in h:
    raise SystemExit('renderAccounts block not found')

old_add = "$('addAccount').onclick=()=>{const name=$('accountName').value.trim(),email=$('accountEmail').value.trim(),password=$('accountPassword').value;if(!name||!email||!password)return alert('Name, email, and password are required.');if(state.accounts.some(a=>a.email.toLowerCase()===email.toLowerCase()))return alert('That email is already saved.');state.accounts.push({id:crypto.randomUUID(),name,email,password});saveAccounts();$('accountName').value=$('accountEmail').value=$('accountPassword').value='';renderAccounts();log(`Saved account ${name}.`)};"
new_add = "$('addAccount').onclick=()=>{if(state.serverVault)return;const name=$('accountName').value.trim(),email=$('accountEmail').value.trim(),password=$('accountPassword').value;if(!name||!email||!password)return alert('Name, email, and password are required.');if(state.accounts.some(a=>a.email.toLowerCase()===email.toLowerCase()))return alert('That email is already saved.');state.accounts.push({id:crypto.randomUUID(),name,email,password});saveAccounts();$('accountName').value=$('accountEmail').value=$('accountPassword').value='';renderAccounts();log(`Saved account ${name}.`)};"
if old_add in h:
    h = h.replace(old_add, new_add, 1)

old_clear = "$('clearAccounts').onclick=()=>{if(!state.accounts.length||confirm('Clear all saved PlayLocal accounts from this browser?')){state.accounts=[];state.sessions.clear();saveAccounts();renderAccounts();log('Saved accounts cleared.')}};"
new_clear = "$('clearAccounts').onclick=()=>{if(state.serverVault)return;if(!state.accounts.length||confirm('Clear all saved PlayLocal accounts from this browser?')){state.accounts=[];state.sessions.clear();saveAccounts();renderAccounts();log('Saved accounts cleared.')}};"
if old_clear in h:
    h = h.replace(old_clear, new_clear, 1)

# Do not show a hidden username in verification help when server-vault mode is active.
h = h.replace("Use <b>${esc(a.name)}</b> (${esc(a.email)}) to book", "Use <b>${esc(a.name)}</b>${state.serverVault?'':' ('+esc(a.email)+')'} to book")
h = h.replace("<div class=\"small\">${esc(g.account.email)}</div>", "<div class=\"small\">${state.serverVault?'Server-managed account':esc(g.account.email)}</div>")

boot_old = "renderAccounts();renderSelectedSummary();renderPlan();\n(async()=>{try{const c=await rpc('capabilities');if(c.vendor!=='playlocal')throw Error('Unexpected backend');$('mode').textContent='Live PlayLocal';$('mode').className='pill ok';log('Live PlayLocal backend connected.')}catch(e){$('mode').textContent='Backend unavailable';$('mode').className='pill bad';log('Backend connection failed: '+e.message)}})();"
boot_new = r'''function showSiteGate(){ $('siteGate').classList.remove('hidden'); }
function hideSiteGate(){ $('siteGate').classList.add('hidden'); $('siteLoginError').textContent=''; }
function applyServerVault(accounts){
  state.serverVault=true;
  state.accounts=(accounts||[]).map(a=>({id:a.id,name:a.name,email:'',password:''}));
  state.sessions.clear();
  try{$('accountName').closest('.card').classList.add('hidden')}catch{}
  $('clearAccounts').classList.add('hidden');
  renderAccounts();
}
async function unlockWithPassword(){
  const btn=$('siteLogin'),password=$('sitePassword').value;
  btn.disabled=true;$('siteLoginError').textContent='';
  try{
    const d=await rpc('site_login',{sitePassword:password},false);
    state.siteToken=d.siteToken||'';
    if(state.siteToken)sessionStorage.setItem('cf_site_token',state.siteToken);
    applyServerVault(d.accounts||[]);
    hideSiteGate();$('sitePassword').value='';
    log('Site unlocked. Server-managed PlayLocal accounts loaded.');
  }catch(e){$('siteLoginError').textContent=e.message;showSiteGate()}
  finally{btn.disabled=false}
}
$('siteLogin').onclick=unlockWithPassword;
$('sitePassword').addEventListener('keydown',e=>{if(e.key==='Enter')unlockWithPassword()});

renderAccounts();renderSelectedSummary();renderPlan();
(async()=>{
  try{
    const c=await rpc('capabilities',{},false);
    if(c.vendor!=='playlocal')throw Error('Unexpected backend');
    $('mode').textContent='Live PlayLocal';$('mode').className='pill ok';
    if(c.siteAuthRequired){
      if(state.siteToken){
        try{const d=await rpc('accounts');applyServerVault(d.accounts||[]);hideSiteGate();log('Site session restored.')}catch{showSiteGate()}
      }else showSiteGate();
    }else{
      hideSiteGate();
      log('Live PlayLocal backend connected.');
    }
  }catch(e){$('mode').textContent='Backend unavailable';$('mode').className='pill bad';hideSiteGate();log('Backend connection failed: '+e.message)}
})();'''
if boot_old in h:
    h = h.replace(boot_old, boot_new, 1)
elif 'function unlockWithPassword()' not in h:
    raise SystemExit('boot block not found')

p.write_text(h)
