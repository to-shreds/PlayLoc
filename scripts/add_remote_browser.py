from pathlib import Path

# ---------------- Backend ----------------
p = Path('playlocal_server.py')
s = p.read_text()

s = s.replace(
    'import hashlib, json, os, re, secrets, threading, time, requests',
    'import base64, hashlib, hmac, json, os, re, secrets, threading, time, requests',
    1,
)

marker = '\ndef login(account_id, username, password):\n'
if marker not in s:
    raise SystemExit('backend login marker not found')

if 'def issue_browser_ticket(req):' not in s:
    helper = r'''
def _b64url(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def issue_browser_ticket(req):
    secret = os.environ.get('COURTFLOW_BROWSER_SECRET', '')
    if not secret:
        raise ApiError('BROWSER_UNAVAILABLE', 'Interactive browser verification is not configured.', 503, True)
    account_id = str(req.get('accountId') or '')
    if account_id not in configured_server_accounts():
        raise ApiError('ACCOUNT_NOT_FOUND', 'That server account is not configured.', 404, True)
    session_token = str(req.get('sessionToken') or '')
    sess = get_session(session_token, account_id)
    slot = req.get('slot') or {}
    for key in ('facilityId', 'courtId', 'date', 'start', 'end'):
        if slot.get(key) is None or slot.get(key) == '':
            raise ApiError('BROWSER_TICKET', f'Missing slot field: {key}.', 400, True)
    booking_q = {
        'date': slot['date'],
        'location': slot.get('searchLocation', ''),
        'sport': 'tennis',
        'start': int(slot['start']),
        'end': int(slot['end']),
        'facilityId': str(slot['facilityId']),
    }
    page, doc, form, _, _, _, booking_url = _reservation_page_for_query(sess, booking_q, str(slot['facilityId']))
    if page is None:
        raise ApiError('SLOT_UNAVAILABLE', 'PlayLocal no longer shows that time as available.', 409, True)
    if not form:
        raise ApiError('UPSTREAM_CHANGED', 'PlayLocal reservation form was not found for interactive verification.', 502)
    set_fields(form, slot)  # validates that the selected exact court is still offered
    safe_slot = {k: slot.get(k) for k in (
        'slotId', 'facilityId', 'facilityName', 'courtId', 'courtName', 'date',
        'start', 'end', 'priceCents', 'searchLocation'
    )}
    payload = {
        'exp': int(time.time()) + 10 * 60,
        'nonce': secrets.token_urlsafe(18),
        'accountId': account_id,
        'slot': safe_slot,
        'reservationUrl': booking_url,
    }
    raw = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
    body = _b64url(raw)
    sig = _b64url(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return {'ticket': body + '.' + sig, 'expiresInSeconds': 10 * 60}


def browser_credentials(account_id):
    account = configured_server_accounts().get(str(account_id or ''))
    if not account:
        raise ApiError('ACCOUNT_NOT_FOUND', 'That server account is not configured.', 404, True)
    return {'username': account['username'], 'password': account['password']}

'''
    s = s.replace(marker, helper + marker, 1)

old_caps = """            'siteAuthRequired': site_auth_required(),
            'serverAccountCount': len(configured_server_accounts()),
"""
new_caps = """            'siteAuthRequired': site_auth_required(),
            'serverAccountCount': len(configured_server_accounts()),
            'remoteBrowserAvailable': bool(os.environ.get('COURTFLOW_BROWSER_SECRET', '')),
"""
if old_caps in s and 'remoteBrowserAvailable' not in s:
    s = s.replace(old_caps, new_caps, 1)

old_dispatch = """    if action == 'verify_booking':
        return verify_booking(req)
    if action == 'book':
        return book(req)
"""
new_dispatch = """    if action == 'verify_booking':
        return verify_booking(req)
    if action == 'browser_ticket':
        return issue_browser_ticket(req)
    if action == 'book':
        return book(req)
"""
if old_dispatch in s:
    s = s.replace(old_dispatch, new_dispatch, 1)
elif "if action == 'browser_ticket':" not in s:
    raise SystemExit('backend dispatch marker not found')

old_post = """    def do_POST(self):
        if self.path != '/adapter':
            return self.send_error(404)
        try:
"""
new_post = r'''    def do_POST(self):
        if self.path == '/browser-credentials':
            try:
                expected = os.environ.get('COURTFLOW_BROWSER_SECRET', '')
                supplied = self.headers.get('Authorization', '')
                if supplied.lower().startswith('bearer '):
                    supplied = supplied[7:]
                if not expected or not secrets.compare_digest(str(supplied), str(expected)):
                    payload = {'ok': False, 'message': 'Unauthorized.'}
                    status = 401
                else:
                    n = int(self.headers.get('Content-Length', '0'))
                    req = json.loads(self.rfile.read(n) or b'{}')
                    creds = browser_credentials(req.get('accountId'))
                    payload = {'ok': True, **creds}
                    status = 200
            except ApiError as e:
                payload = {'ok': False, 'message': e.message}
                status = e.status
            except Exception:
                payload = {'ok': False, 'message': 'Credential service error.'}
                status = 500
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path != '/adapter':
            return self.send_error(404)
        try:
'''
if old_post in s:
    s = s.replace(old_post, new_post, 1)
elif "self.path == '/browser-credentials'" not in s:
    raise SystemExit('backend do_POST marker not found')

p.write_text(s)

# ---------------- Frontend ----------------
p = Path('index.html')
h = p.read_text()

css_marker = '.site-gate{position:fixed;inset:0;background:#f3f6f4;z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px}'
if css_marker not in h:
    raise SystemExit('frontend CSS marker not found')
if '.browser-modal{' not in h:
    h = h.replace(css_marker,
        '.browser-modal{position:fixed;inset:0;background:#111c;z-index:900;display:flex;align-items:center;justify-content:center;padding:12px}.browser-modal.hidden{display:none}.browser-card{width:min(1040px,100%);height:min(860px,96vh);background:#fff;border-radius:16px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 18px 60px #0008}.browser-head{display:flex;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--border)}.browser-head .grow{flex:1}.browser-view{flex:1;min-height:0;background:#1b1f1d;display:flex;align-items:center;justify-content:center;overflow:auto;touch-action:none}.browser-view img{max-width:100%;max-height:100%;object-fit:contain;cursor:crosshair;user-select:none;-webkit-user-drag:none}.browser-tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:9px 12px;border-top:1px solid var(--border)}.browser-tools input{flex:1;min-width:160px;border:1px solid #cbd6cf;border-radius:8px;padding:8px}.browser-status{font-size:12px;color:var(--muted)}' + css_marker, 1)

body_marker = '<div class="wrap" id="appShell">'
if body_marker not in h:
    raise SystemExit('frontend body marker not found')
if 'id="browserModal"' not in h:
    modal = r'''<div id="browserModal" class="browser-modal hidden">
  <div class="browser-card">
    <div class="browser-head"><div class="grow"><b>PlayLocal verification</b><div id="browserStatus" class="browser-status">Opening remote browser…</div></div><button class="btn" id="browserClose">Close</button></div>
    <div class="browser-view" id="browserView"><img id="browserFrame" alt="Interactive PlayLocal verification browser"></div>
    <div class="browser-tools"><button class="btn" id="browserUp">Scroll up</button><button class="btn" id="browserDown">Scroll down</button><input id="browserText" placeholder="Type here only if PlayLocal asks for text"><button class="btn" id="browserSendText">Send text</button><button class="btn" id="browserEnter">Enter</button></div>
  </div>
</div>
'''
    h = h.replace(body_marker, modal + body_marker, 1)

h = h.replace(
    "const ADAPTER='https://courtflow-playlocal.onrender.com/adapter';",
    "const ADAPTER='https://courtflow-playlocal.onrender.com/adapter';\nconst BROWSER_SERVICE='https://courtflow-browser-playlocal.onrender.com';",
    1,
)

old_state = "const state={accounts:loadAccounts(),sessions:new Map(),facilities:[],matrix:null,selected:new Set(),plan:[],remoteBookings:[],bookingQueue:[],bookingCursor:0,pendingVerification:null,pendingCheckRunning:false,siteToken:sessionStorage.getItem('cf_site_token')||'',serverVault:false};"
new_state = "const state={accounts:loadAccounts(),sessions:new Map(),facilities:[],matrix:null,selected:new Set(),plan:[],remoteBookings:[],bookingQueue:[],bookingCursor:0,pendingVerification:null,pendingCheckRunning:false,siteToken:sessionStorage.getItem('cf_site_token')||'',serverVault:false,remoteBrowser:null,browserPoll:null};"
if old_state in h:
    h = h.replace(old_state, new_state, 1)
elif 'remoteBrowser:null' not in h:
    raise SystemExit('frontend state marker not found')

old_vh = "function verificationHelp(row,url){const help=$('bookingHelp'),a=row.account,court=row.slot.courtName;help.innerHTML=`<div class=\"notice\"><b>Finish this reservation in PlayLocal</b><div style=\"margin-top:6px\">Use <b>${esc(a.name)}</b>${state.serverVault?'':' ('+esc(a.email)+')'} to book <b>${esc(court)}</b> at <b>${timeLabel(row.start)}</b>. Complete PlayLocal's verification and submit. CourtFlow will check Activity when you return and continue the plan.</div><div style=\"margin-top:10px\"><a class=\"btn primary\" href=\"${esc(url)}\" target=\"_blank\" rel=\"noopener\">Open PlayLocal</a> <button class=\"btn\" id=\"checkPending\">Check & continue</button></div></div>`;$('checkPending').onclick=()=>checkPendingBooking(true)}"
new_vh = r'''function verificationHelp(row,url){
  const help=$('bookingHelp'),a=row.account,court=row.slot.courtName;
  if(state.serverVault){
    help.innerHTML=`<div class="notice"><b>Interactive verification required</b><div style="margin-top:6px">CourtFlow will open PlayLocal in a temporary remote browser already signed into <b>${esc(a.name)}</b>. Complete only the verification PlayLocal presents. Credentials stay on Render.</div><div style="margin-top:10px"><button class="btn primary" id="openRemoteBrowser">Open verification browser</button> <button class="btn" id="checkPending">Check & continue</button></div></div>`;
    $('openRemoteBrowser').onclick=()=>startRemoteBrowser(row);
    $('checkPending').onclick=()=>checkPendingBooking(true);
    startRemoteBrowser(row);
    return;
  }
  help.innerHTML=`<div class="notice"><b>Finish this reservation in PlayLocal</b><div style="margin-top:6px">Use <b>${esc(a.name)}</b> (${esc(a.email)}) to book <b>${esc(court)}</b> at <b>${timeLabel(row.start)}</b>. Complete PlayLocal's verification and submit. CourtFlow will check Activity when you return and continue the plan.</div><div style="margin-top:10px"><a class="btn primary" href="${esc(url)}" target="_blank" rel="noopener">Open PlayLocal</a> <button class="btn" id="checkPending">Check & continue</button></div></div>`;
  $('checkPending').onclick=()=>checkPendingBooking(true);
}'''
if old_vh in h:
    h = h.replace(old_vh, new_vh, 1)
elif 'function startRemoteBrowser(' not in h:
    raise SystemExit('verificationHelp marker not found')

insert_marker = 'async function verifyRow(row){'
if insert_marker not in h:
    raise SystemExit('verifyRow marker not found')
if 'async function startRemoteBrowser(row)' not in h:
    browser_js = r'''
async function browserRequest(path,opts={}){
  const headers={...(opts.headers||{})};
  if(state.remoteBrowser?.key)headers['X-CourtFlow-Session']=state.remoteBrowser.key;
  return fetch(BROWSER_SERVICE+path,{...opts,headers});
}
async function closeRemoteBrowser(){
  if(state.browserPoll){clearTimeout(state.browserPoll);state.browserPoll=null}
  const rb=state.remoteBrowser;state.remoteBrowser=null;$('browserModal').classList.add('hidden');
  if(rb?.id&&rb?.key){try{await fetch(BROWSER_SERVICE+`/session/${encodeURIComponent(rb.id)}`,{method:'DELETE',headers:{'X-CourtFlow-Session':rb.key}})}catch{}}
}
async function sendBrowserInput(payload){
  const rb=state.remoteBrowser;if(!rb)return;
  try{await browserRequest(`/session/${encodeURIComponent(rb.id)}/input`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)})}catch(e){$('browserStatus').textContent='Remote browser input failed: '+e.message}
}
async function pollRemoteBrowser(){
  const rb=state.remoteBrowser;if(!rb)return;
  try{
    const sr=await browserRequest(`/session/${encodeURIComponent(rb.id)}/status`);const s=await sr.json();
    if(!sr.ok||!s.ok)throw Error(s.message||'Remote browser session failed.');
    $('browserStatus').textContent=s.statusText||s.state||'Waiting for PlayLocal…';
    if(s.state==='confirmed'){
      await closeRemoteBrowser();
      if(state.pendingVerification)setTimeout(()=>checkPendingBooking(true),400);
      return;
    }
    if(s.state==='failed')return;
    const fr=await browserRequest(`/session/${encodeURIComponent(rb.id)}/frame?ts=${Date.now()}`);
    if(fr.ok){const blob=await fr.blob();if(state.remoteBrowser===rb){if(rb.objectUrl)URL.revokeObjectURL(rb.objectUrl);rb.objectUrl=URL.createObjectURL(blob);$('browserFrame').src=rb.objectUrl;}}
  }catch(e){$('browserStatus').textContent=e.message||String(e)}
  if(state.remoteBrowser===rb)state.browserPoll=setTimeout(pollRemoteBrowser,850);
}
async function startRemoteBrowser(row){
  if(!state.serverVault)return;
  if(state.remoteBrowser)return;
  $('browserModal').classList.remove('hidden');$('browserStatus').textContent='Preparing a private PlayLocal browser…';$('browserFrame').removeAttribute('src');
  try{
    const ss=await auth(row.account);
    const ticket=await rpc('browser_ticket',{accountId:row.account.id,sessionToken:ss.sessionToken,slot:row.slot});
    const r=await fetch(BROWSER_SERVICE+'/session/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({ticket:ticket.ticket})});
    const b=await r.json().catch(()=>null);if(!r.ok||!b?.ok)throw Error(b?.message||'Could not start the verification browser.');
    state.remoteBrowser={id:b.sessionId,key:b.sessionKey,viewport:b.viewport||{width:980,height:720},objectUrl:null};
    $('browserStatus').textContent=b.statusText||'Remote browser ready.';
    pollRemoteBrowser();
  }catch(e){$('browserStatus').textContent='Could not open verification browser: '+e.message;log('Verification browser failed: '+e.message)}
}
$('browserClose').onclick=closeRemoteBrowser;
$('browserUp').onclick=()=>sendBrowserInput({type:'wheel',deltaY:-560});
$('browserDown').onclick=()=>sendBrowserInput({type:'wheel',deltaY:560});
$('browserSendText').onclick=()=>{const v=$('browserText').value;if(v){sendBrowserInput({type:'text',text:v});$('browserText').value=''}};
$('browserEnter').onclick=()=>sendBrowserInput({type:'key',key:'Enter'});
$('browserFrame').addEventListener('click',e=>{const rb=state.remoteBrowser;if(!rb)return;const rect=e.currentTarget.getBoundingClientRect();const x=(e.clientX-rect.left)*rb.viewport.width/rect.width;const y=(e.clientY-rect.top)*rb.viewport.height/rect.height;sendBrowserInput({type:'click',x,y})});
$('browserView').addEventListener('wheel',e=>{if(!state.remoteBrowser)return;e.preventDefault();sendBrowserInput({type:'wheel',deltaY:e.deltaY})},{passive:false});
'''
    h = h.replace(insert_marker, browser_js + '\n' + insert_marker, 1)

p.write_text(h)
