from pathlib import Path
import re

# Patch browser service so /session/start responds immediately and browser init happens in background.
p = Path('browser_service/server.js')
s = p.read_text()

start_pat = re.compile(r"app\.post\('/session/start', async \(req, res\) => \{.*?\n\}\);\n\napp\.get\('/session/:id/status'", re.S)
new_start = r'''async function initializeSession(session) {
  let browser = null;
  try {
    session.state = 'starting';
    session.statusText = 'Starting the private PlayLocal browser…';
    const material = await fetchSessionMaterial(session.payload.bridgeId, session.payload.accountId);
    browser = await launchBrowser();
    session.browser = browser;
    const page = await browser.newPage();
    session.page = page;
    await page.setViewport(VIEWPORT);
    await page.setJavaScriptEnabled(true);
    await applySessionMaterial(page, material);
    session.state = 'loading';
    session.statusText = 'Opening the PlayLocal reservation…';
    await navigateReservation(page, session.payload);
    await inspect(session);
    session.monitor = setInterval(() => inspect(session), 650);
    console.log(`Remote session ${session.id} initialized state=${session.state} url=${page.url()}`);
  } catch (err) {
    session.state = 'failed';
    session.statusText = err.message || String(err);
    console.error(`Remote session ${session.id} failed:`, err?.stack || err);
    try { await browser?.close(); } catch {}
    session.browser = null;
    session.page = null;
  }
}

app.post('/session/start', async (req, res) => {
  try {
    const payload = verifyTicket(req.body?.ticket);
    if (!payload.bridgeId) throw new Error('Browser ticket is missing its authenticated session bridge.');
    const id = crypto.randomBytes(18).toString('base64url');
    const key = crypto.randomBytes(24).toString('base64url');
    const session = {
      id, key, page: null, browser: null, payload,
      state: 'starting',
      statusText: 'Starting the private PlayLocal browser…',
      createdAt: Date.now(),
      lastActivity: Date.now(),
      prepared: false,
      preparedAt: 0,
      submitting: false,
      closed: false,
      busyInspect: false,
      monitor: null,
    };
    sessions.set(id, session);
    res.json({ ok: true, sessionId: id, sessionKey: key, state: session.state, statusText: session.statusText, viewport: VIEWPORT });
    initializeSession(session);
  } catch (err) {
    console.error('start session failed:', err?.stack || err);
    res.status(err.status || 500).json({ ok: false, message: err.message || String(err) });
  }
});

app.get('/session/:id/status' '''
if not start_pat.search(s):
    raise SystemExit('session start block not found')
s = start_pat.sub(new_start, s)

# Fix accidental spacing from replacement function boundary.
s = s.replace("app.get('/session/:id/status' , requireSession", "app.get('/session/:id/status', requireSession")

old_status = "res.json({ ok: true, state: s.state, statusText: s.statusText, viewport: VIEWPORT, ageSeconds: Math.round((Date.now() - s.createdAt) / 1000) });"
new_status = "res.json({ ok: true, state: s.state, statusText: s.statusText, viewport: VIEWPORT, frameReady: !!s.page && !s.page.isClosed(), ageSeconds: Math.round((Date.now() - s.createdAt) / 1000) });"
if old_status not in s:
    raise SystemExit('status response not found')
s = s.replace(old_status, new_status, 1)

old_frame = """app.get('/session/:id/frame', requireSession, async (req, res) => {\n  try {\n    const png = await req.remoteSession.page.screenshot({ type: 'png', fullPage: false, captureBeyondViewport: false });"""
new_frame = """app.get('/session/:id/frame', requireSession, async (req, res) => {\n  try {\n    if (!req.remoteSession.page || req.remoteSession.page.isClosed()) return res.status(425).json({ ok: false, message: 'Remote browser is still starting.' });\n    const png = await req.remoteSession.page.screenshot({ type: 'png', fullPage: false, captureBeyondViewport: false });"""
if old_frame not in s:
    raise SystemExit('frame block not found')
s = s.replace(old_frame, new_frame, 1)

# Remove stale browserPromise reference in SIGTERM.
s = s.replace("  try { const b = await browserPromise; await b?.close(); } catch {}\n", "")
p.write_text(s)

# Patch frontend UX and frame polling.
p = Path('index.html')
h = p.read_text()

# Add loading placeholder in browser view.
h = h.replace('<div class="browser-view" id="browserView"><img id="browserFrame" alt="Interactive PlayLocal verification browser"></div>',
              '<div class="browser-view" id="browserView"><div id="browserLoading" style="color:#dbe7e1;text-align:center;padding:24px"><div class="spinner"></div><div style="margin-top:10px">Starting PlayLocal…</div></div><img id="browserFrame" class="hidden" alt="Interactive PlayLocal verification browser"></div>')

# Replace server-vault verification help with automatic status only.
old_help = """    help.innerHTML=`<div class=\"notice\"><b>Interactive verification required</b><div style=\"margin-top:6px\">CourtFlow will open PlayLocal in a temporary remote browser already signed into <b>${esc(a.name)}</b>. Complete only the verification PlayLocal presents. Credentials stay on Render.</div><div style=\"margin-top:10px\"><button class=\"btn primary\" id=\"openRemoteBrowser\">Open verification browser</button> <button class=\"btn\" id=\"checkPending\">Check & continue</button></div></div>`;\n    $('openRemoteBrowser').onclick=()=>startRemoteBrowser(row);\n    $('checkPending').onclick=()=>checkPendingBooking(true);\n    startRemoteBrowser(row);\n    return;"""
new_help = """    help.innerHTML=`<div class=\"notice\"><b>Verification needed for ${esc(a.name)}</b><div style=\"margin-top:6px\">Opening PlayLocal verification now. Complete the verification when it appears. CourtFlow will submit and continue automatically.</div></div>`;\n    startRemoteBrowser(row);\n    return;"""
if old_help not in h:
    raise SystemExit('verification help block not found')
h = h.replace(old_help, new_help, 1)

# Replace poll function body wholesale.
poll_pat = re.compile(r"async function pollRemoteBrowser\(\)\{.*?\n\}\nasync function startRemoteBrowser", re.S)
new_poll = r'''async function pollRemoteBrowser(){
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
    if(s.state==='failed'){
      $('browserRetry').classList.remove('hidden');
      $('browserLoading').classList.add('hidden');
      log('Verification browser stopped: '+(s.statusText||'Unknown error'));
      return;
    }
    if(s.frameReady){
      const fr=await browserRequest(`/session/${encodeURIComponent(rb.id)}/frame?ts=${Date.now()}`);
      if(fr.ok){
        const blob=await fr.blob();
        if(state.remoteBrowser===rb){
          if(rb.objectUrl)URL.revokeObjectURL(rb.objectUrl);
          rb.objectUrl=URL.createObjectURL(blob);
          $('browserFrame').src=rb.objectUrl;
          $('browserFrame').classList.remove('hidden');
          $('browserLoading').classList.add('hidden');
        }
      }
    }
  }catch(e){
    $('browserStatus').textContent=e.message||String(e);
    $('browserRetry').classList.remove('hidden');
    log('Verification display failed: '+(e.message||String(e)));
  }
  if(state.remoteBrowser===rb)state.browserPoll=setTimeout(pollRemoteBrowser,850);
}
async function startRemoteBrowser'''
if not poll_pat.search(h):
    raise SystemExit('poll function not found')
h = poll_pat.sub(new_poll, h)

# Enhance start initialization visuals and failure recovery.
h = h.replace("$('browserModal').classList.remove('hidden');$('browserStatus').textContent='Preparing a private PlayLocal browser…';$('browserFrame').removeAttribute('src');",
              "$('browserModal').classList.remove('hidden');$('browserStatus').textContent='Starting the private PlayLocal browser…';$('browserRetry').classList.add('hidden');$('browserFrame').removeAttribute('src');$('browserFrame').classList.add('hidden');$('browserLoading').classList.remove('hidden');")
h = h.replace("}catch(e){$('browserStatus').textContent='Could not open verification browser: '+e.message;log('Verification browser failed: '+e.message)}",
              "}catch(e){state.remoteBrowser=null;$('browserStatus').textContent='Could not open verification browser: '+e.message;$('browserRetry').classList.remove('hidden');$('browserLoading').classList.add('hidden');log('Verification browser failed: '+e.message)}")

# Retry should close any stale session then restart current pending row.
old_retry = "$('browserRetry').onclick=()=>{const p=state.pendingVerification;closeRemoteBrowser().then(()=>{if(p)startRemoteBrowser(p.row)})};"
if old_retry in h:
    h = h.replace(old_retry, "$('browserRetry').onclick=async()=>{const p=state.pendingVerification;await closeRemoteBrowser();if(p)startRemoteBrowser(p.row)};", 1)
else:
    anchor = "$('browserClose').onclick=closeRemoteBrowser;"
    h = h.replace(anchor, "$('browserRetry').onclick=async()=>{const p=state.pendingVerification;await closeRemoteBrowser();if(p)startRemoteBrowser(p.row)};\n"+anchor, 1)

p.write_text(h)
