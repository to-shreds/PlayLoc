from pathlib import Path
import hashlib
import re


def blob_sha(text):
    data = text.encode()
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit('Expected exactly one patch anchor: ' + old[:110])
    return text.replace(old, new, 1)


p = Path('browser_service/server.js')
s = p.read_text()
hp = Path('index.html')
h = hp.read_text()
if "require('./verification-flow')" in s:
    raise SystemExit('Lifecycle repair is already applied; do not reapply.')
assert blob_sha(s) == 'a7720de7179aa4658c2d8f3ac93f12762939687e', 'Server changed; inspect before patching'
assert blob_sha(h) == 'a510f3e01f3411626325da4bc37c3580489fda84', 'Frontend changed; inspect before patching'

s = once(s, "const chromium = require('@sparticuz/chromium');", "const chromium = require('@sparticuz/chromium');\nconst { inspectSession, prepareReservationDOM, confirmationLike } = require('./verification-flow');\nconst BUILD = 'verification-lifecycle-2';")
a = s.index('async function tryPrepareReservation(')
b = s.index('function requireSession(', a)
s = s[:a] + '''async function tryPrepareReservation(page, payload) {
  return page.evaluate(prepareReservationDOM, payload.slot);
}

async function inspect(session) { return inspectSession(session); }

''' + s[b:]

a = s.index('async function closeSession(')
b = s.index("app.get('/health'", a)
s = s[:a] + '''async function closeSession(session) {
  if (!session || session.closed) return;
  session.closed = true;
  if (session.monitor) clearInterval(session.monitor);
  try { await session.page?.close(); } catch {}
  if (session.initPromise) { try { await session.initPromise; } catch {} }
  session.page = null;
  sessions.delete(session.id);
  if (activeSessionId === session.id) activeSessionId = null;
}

''' + s[b:]
s = once(s, "res.json({ ok: true, service: 'courtflow-browser' })", "res.json({ ok: true, service: 'courtflow-browser', build: BUILD })")
s = once(s, "app.get('/health/deep', async (req, res) => {\n  let page = null;", "app.get('/health/deep', async (req, res) => {\n  if (activeSessionId) return res.status(409).json({ ok: false, message: 'A verification is active.' });\n  let page = null;")

a = s.index('async function initializeSession(')
b = s.index("app.post('/session/start'", a)
s = s[:a] + '''async function initializeSession(session, dependencies = {}) {
  session.initializing = true;
  try {
    session.state = 'starting';
    session.statusText = 'Starting the private PlayLocal browser...';
    const material = await (dependencies.fetchSessionMaterial || fetchSessionMaterial)(session.payload.bridgeId, session.payload.accountId);
    if (session.closed) return;
    const browser = await (dependencies.getBrowser || getBrowser)();
    if (session.closed) return;
    session.browser = browser;
    const page = await browser.newPage();
    if (session.closed) { await page.close(); return; }
    session.page = page;
    await page.setViewport(VIEWPORT);
    await page.setJavaScriptEnabled(true);
    if (session.readOnly) {
      // Diagnostics can observe a real authenticated page but cannot submit it.
      await page.setRequestInterception(true);
      page.on('request', request => {
        if (request.isInterceptResolutionHandled()) return;
        if (!['GET', 'HEAD'].includes(request.method())) {
          session.blockedMutations = (session.blockedMutations || 0) + 1;
          request.abort().catch(() => {});
        } else request.continue().catch(() => {});
      });
    } else {
      page.on('request', request => {
        try {
          const u = new URL(request.url());
          if (request.method() === 'POST' && ['playlocal.com', 'www.playlocal.com'].includes(u.hostname)
              && u.pathname === `/facilities/${session.payload.slot.facilityId}/reservations`) {
            session.submissionAttempted = true;
          }
        } catch {}
      });
    }
    await (dependencies.applySessionMaterial || applySessionMaterial)(page, material);
    if (session.closed) return;
    session.state = 'loading';
    session.statusText = 'Opening the PlayLocal reservation...';
    await (dependencies.navigateReservation || navigateReservation)(page, session.payload);
    if (session.closed) return;
    session.frameReady = true;
    session.initializing = false;
    await inspect(session);
    if (!session.closed) session.monitor = setInterval(() => inspect(session), 900);
    console.log(`Remote session initialized state=${session.state} frameReady=${session.frameReady} readOnly=${!!session.readOnly}`);
  } catch (err) {
    if (!session.closed) {
      session.state = 'failed';
      session.statusText = err.message || String(err);
      console.error(`Remote session initialization failed: ${session.statusText}`);
    }
    try { await session.page?.close(); } catch {}
    session.browser = null;
    session.page = null;
    session.frameReady = false;
  } finally {
    session.initializing = false;
    if (session.closed) {
      try { await session.page?.close(); } catch {}
      session.page = null;
    }
  }
}

''' + s[b:]
s = once(s, '''    if (activeSessionId) {
      const prior = sessions.get(activeSessionId);
      if (prior) await closeSession(prior);
      activeSessionId = null;
    }''', '''    if (activeSessionId) {
      return res.status(409).json({ ok: false, code: 'BROWSER_BUSY', message: 'Another verification is open. Close it before starting another one.' });
    }''')
s = once(s, '      id, key, page: null, browser: null, payload,', '''      id, key, page: null, browser: null, payload,
      initializing: true, frameReady: false, submissionAttempted: false,
      readOnly: req.body?.readOnly === true,''')
s = once(s, '    initializeSession(session);', '    session.initPromise = initializeSession(session);')
s = once(s, 'frameReady: !!s.page && !s.page.isClosed(),', "build: BUILD, readOnly: !!s.readOnly, selectedCourtId: s.selectedCourtId || '', challengePresent: !!s.challengePresent, submissionAttempted: !!s.submissionAttempted, frameReady: !!s.frameReady && !s.initializing && !!s.page && !s.page.isClosed() && s.state !== 'failed',")
s = once(s, "if (!req.remoteSession.page || req.remoteSession.page.isClosed()) return res.status(425)", "if (!req.remoteSession.frameReady || req.remoteSession.initializing || !req.remoteSession.page || req.remoteSession.page.isClosed()) return res.status(425)")
s = once(s, "res.type('jpeg').send(image);", "res.type('jpeg').send(Buffer.from(image));")
s = once(s, "  const s = req.remoteSession;\n  try {\n    const body = req.body || {};", "  const s = req.remoteSession;\n  if (s.readOnly || s.initializing || !s.frameReady || !s.page || s.page.isClosed() || s.state === 'failed') return res.status(409).json({ ok: false, message: s.readOnly ? 'Input is disabled during a read-only display test.' : 'Wait for the verification page to load.' });\n  try {\n    const body = req.body || {};")
s = once(s, "app.listen(PORT, '0.0.0.0', () => {\n  console.log(`CourtFlow browser service listening on ${PORT}`);\n  warmBrowserRuntime();\n});", '''if (require.main === module) {
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`CourtFlow browser service listening on ${PORT} build=${BUILD}`);
    warmBrowserRuntime().then(async () => {
      if (process.env.COURTFLOW_RUN_READONLY_PROBE === '1') {
        await require('./readonly-probe').run({ port: PORT, mainAPI: MAIN_API });
      }
    });
  });
}

async function shutdownBrowser() {
  for (const session of sessions.values()) await closeSession(session);
  const browser = await sharedBrowserPromise;
  sharedBrowserPromise = null;
  try { await browser?.close(); } catch {}
}
module.exports = { app, sessions, inspect, initializeSession, closeSession, getBrowser, shutdownBrowser, confirmationLike, tryPrepareReservation, VIEWPORT };
''')

# Frontend: keep one visible step, preserve pending verification, and decode frames
# before replacing the last valid image. Never hide the modal based on page text.
a = h.index('async function browserRequest(')
b = h.index("$('browserUp').onclick", a)
h = h[:a] + r'''let browserGeneration = 0;
async function browserRequest(path, opts={}, rb=state.remoteBrowser){
  const headers={...(opts.headers||{})};
  if(rb?.key)headers['X-CourtFlow-Session']=rb.key;
  return fetch(BROWSER_SERVICE+path,{...opts,headers,signal:opts.signal||AbortSignal.timeout(30000)});
}
function verificationPaused(){
  const row=state.pendingVerification?.row;
  if(!row)return;
  $('bookingHelp').innerHTML=`<div class="notice"><b>Booking paused for verification</b><div>${esc(row.slot.courtName)} at ${timeLabel(row.start)} using ${esc(row.account.name)} has not been confirmed.</div><button id="resumeVerification" class="btn primary">Resume verification</button></div>`;
  $('resumeVerification').onclick=()=>startRemoteBrowser(row);
  renderPlan();
}
async function closeRemoteBrowser(quiet=false){
  ++browserGeneration;
  if(state.browserPoll){clearTimeout(state.browserPoll);state.browserPoll=null}
  const rb=state.remoteBrowser;state.remoteBrowser=null;
  $('browserModal').classList.add('hidden');document.body.style.overflow='';
  if(rb?.objectUrl)URL.revokeObjectURL(rb.objectUrl);
  if(rb?.id&&rb?.key){try{await browserRequest(`/session/${encodeURIComponent(rb.id)}`,{method:'DELETE'},rb)}catch{}}
  if(!quiet)verificationPaused();
}
async function sendBrowserInput(payload){
  const rb=state.remoteBrowser;if(!rb)return;
  try{
    const response=await browserRequest(`/session/${encodeURIComponent(rb.id)}/input`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)},rb);
    if(!response.ok){const d=await response.json();throw Error(d.message||'Input failed.')}
  }catch(e){$('browserStatus').textContent='Verification: '+e.message}
}
async function pollRemoteBrowser(){
  const rb=state.remoteBrowser;if(!rb)return;
  try{
    const sr=await browserRequest(`/session/${encodeURIComponent(rb.id)}/status`,{},rb);
    const s=await sr.json();
    if(state.remoteBrowser!==rb)return;
    if(!sr.ok||!s.ok)throw Error(s.message||'Remote browser session failed.');
    $('browserStatus').textContent=s.statusText||'Loading PlayLocal...';
    if(s.state==='confirmed'||s.state==='submitting'){
      if(!rb.lastCheck||Date.now()-rb.lastCheck>5000){
        rb.lastCheck=Date.now();
        if(await checkPendingBooking(false))return;
      }
    }
    if(s.state==='failed'){
      $('browserRetry').classList.remove('hidden');$('browserLoading').classList.add('hidden');
      log('Verification stopped: '+s.statusText);return;
    }
    if(s.frameReady){
      const fr=await browserRequest(`/session/${encodeURIComponent(rb.id)}/frame`,{},rb);
      if(fr.status!==425){
        if(!fr.ok)throw Error((await fr.json()).message||'Could not read the verification image.');
        const blob=await fr.blob();
        if(!blob.type.startsWith('image/'))throw Error('The server did not return an image.');
        const nextUrl=URL.createObjectURL(blob);
        const decoded=new Image();decoded.src=nextUrl;
        try{await decoded.decode()}catch{URL.revokeObjectURL(nextUrl);throw Error('The verification image could not be decoded.')}
        if(state.remoteBrowser!==rb){URL.revokeObjectURL(nextUrl);return}
        const previous=rb.objectUrl;rb.objectUrl=nextUrl;
        $('browserFrame').src=nextUrl;$('browserFrame').classList.remove('hidden');
        $('browserLoading').classList.add('hidden');$('browserRetry').classList.add('hidden');
        if(previous)URL.revokeObjectURL(previous);
      }
    }
  }catch(e){
    if(state.remoteBrowser!==rb)return;
    $('browserStatus').textContent=e.message||String(e);
    $('browserRetry').classList.remove('hidden');log('Verification display: '+e.message);
  }
  if(state.remoteBrowser===rb)state.browserPoll=setTimeout(pollRemoteBrowser,1200);
}
async function startRemoteBrowser(row){
  if(!state.serverVault||state.remoteBrowserStarting)return;
  if(state.remoteBrowser){$('browserModal').classList.remove('hidden');return}
  state.remoteBrowserStarting=true;
  const generation=++browserGeneration;
  $('browserModal').classList.remove('hidden');document.body.style.overflow='hidden';
  $('browserRetry').classList.add('hidden');$('browserLoading').classList.remove('hidden');
  $('browserStatus').textContent=`Opening ${row.slot.courtName}, ${timeLabel(row.start)}, using ${row.account.name}...`;
  $('browserFrame').removeAttribute('src');$('browserFrame').classList.add('hidden');
  try{
    const ss=await auth(row.account);
    const ticket=await rpc('browser_ticket',{accountId:row.account.id,sessionToken:ss.sessionToken,slot:row.slot});
    if(generation!==browserGeneration)return;
    const r=await fetch(BROWSER_SERVICE+'/session/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({ticket:ticket.ticket}),signal:AbortSignal.timeout(60000)});
    const b=await r.json().catch(()=>null);
    if(!r.ok||!b?.ok)throw Error(b?.message||'Could not start verification.');
    const rb={id:b.sessionId,key:b.sessionKey,viewport:b.viewport||{width:430,height:760},objectUrl:null};
    if(generation!==browserGeneration){try{await browserRequest(`/session/${encodeURIComponent(rb.id)}`,{method:'DELETE'},rb)}catch{}return}
    state.remoteBrowser=rb;$('browserStatus').textContent=b.statusText||'Loading PlayLocal...';
    pollRemoteBrowser();
  }catch(e){
    if(generation!==browserGeneration)return;
    $('browserStatus').textContent='Could not open verification: '+e.message;
    $('browserRetry').classList.remove('hidden');$('browserLoading').classList.add('hidden');
    log('Verification browser: '+e.message);
  }finally{state.remoteBrowserStarting=false}
}
$('browserRetry').onclick=async()=>{const row=state.pendingVerification?.row;await closeRemoteBrowser(true);if(row)startRemoteBrowser(row)};
$('browserClose').onclick=()=>closeRemoteBrowser();
''' + h[b:]
# Do not permit a second Book action to skip the pending verification row.
h = once(h, "$('bookPlan').onclick=async()=>{setNextStep", "$('bookPlan').onclick=async()=>{if(state.pendingVerification){startRemoteBrowser(state.pendingVerification.row);return}if(state.bookingRunning)return;state.bookingRunning=true;try{setNextStep")
h = once(h, "await continuePlanBooking()};\nwindow.addEventListener", "await continuePlanBooking()}finally{state.bookingRunning=false;renderPlan()}};\nwindow.addEventListener")
h = once(h, "if(v.confirmed){p.row.status='booked';", "if(v.confirmed){await closeRemoteBrowser(true);p.row.status='booked';")
h = once(h, "if(planned)setNextStep(4,`Plan ready. Next: book ${planned} slot${planned===1?'':'s'}.`)}", "if(planned)setNextStep(4,`Plan ready. Next: book ${planned} slot${planned===1?'':'s'}.`);if(state.pendingVerification||state.bookingRunning){$('bookPlan').classList.add('hidden');$('buildPlan').classList.add('hidden');setNextStep(4,state.pendingVerification?'Booking paused: complete the PlayLocal verification.':'Booking in progress. Please wait.')}}")
h = once(h, '<title>CourtFlow</title>', '<title>CourtFlow</title>\n<meta name="courtflow-build" content="verification-lifecycle-2">')
h = once(h, '.browser-view img{width:100%;height:auto;max-height:none;object-fit:contain}', '.browser-view img{width:auto;height:auto;max-width:100%;max-height:100%;object-fit:contain}')
# All anchors have been checked before either file is changed.
p.write_text(s)
hp.write_text(h)
print('Applied verification lifecycle repair to server.js and index.html')
