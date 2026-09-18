const express = require('express');
const crypto = require('crypto');
const puppeteer = require('puppeteer-core');
const chromium = require('@sparticuz/chromium');
const { inspectSession, prepareReservationDOM, confirmationLike } = require('./verification-flow');
const BUILD = 'verification-lifecycle-2';

const PORT = Number(process.env.PORT || 10000);
const MAIN_API = process.env.COURTFLOW_MAIN_API || 'https://courtflow-playlocal.onrender.com';
const SHARED_SECRET = process.env.COURTFLOW_BROWSER_SECRET || '';
const ALLOWED_ORIGIN = process.env.COURTFLOW_ALLOWED_ORIGIN || 'https://to-shreds.github.io';
const VIEWPORT = { width: 430, height: 760, deviceScaleFactor: 1, isMobile: true, hasTouch: true };
const SESSION_TTL_MS = 12 * 60 * 1000;
const sessions = new Map();
const usedNonces = new Map();
let chromiumPathPromise = null;
let sharedBrowserPromise = null;
let activeSessionId = null;

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

async function chromiumPath() {
  if (!chromiumPathPromise) {
    chromiumPathPromise = chromium.executablePath().catch(err => {
      chromiumPathPromise = null;
      throw err;
    });
  }
  return chromiumPathPromise;
}

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '256kb' }));
app.use((req, res, next) => {
  const origin = req.headers.origin || '';
  if (origin === ALLOWED_ORIGIN) res.setHeader('Access-Control-Allow-Origin', origin);
  res.setHeader('Vary', 'Origin');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-CourtFlow-Session');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,DELETE,OPTIONS');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method === 'OPTIONS') return res.sendStatus(204);
  next();
});

function b64urlDecode(value) {
  const pad = value.length % 4 ? '='.repeat(4 - value.length % 4) : '';
  return Buffer.from(value.replace(/-/g, '+').replace(/_/g, '/') + pad, 'base64');
}

function safeEqual(a, b) {
  const aa = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return aa.length === bb.length && crypto.timingSafeEqual(aa, bb);
}

function verifyTicket(ticket) {
  if (!SHARED_SECRET) throw Object.assign(new Error('Browser service is not configured.'), { status: 503 });
  const parts = String(ticket || '').split('.');
  if (parts.length !== 2) throw Object.assign(new Error('Invalid browser ticket.'), { status: 401 });
  const [body, sig] = parts;
  const expected = crypto.createHmac('sha256', SHARED_SECRET).update(body).digest('base64url');
  if (!safeEqual(sig, expected)) throw Object.assign(new Error('Invalid browser ticket.'), { status: 401 });
  let payload;
  try { payload = JSON.parse(b64urlDecode(body).toString('utf8')); }
  catch { throw Object.assign(new Error('Invalid browser ticket.'), { status: 401 }); }
  if (!payload.exp || Date.now() / 1000 > Number(payload.exp)) throw Object.assign(new Error('Browser ticket expired.'), { status: 401 });
  if (!payload.nonce || usedNonces.has(payload.nonce)) throw Object.assign(new Error('Browser ticket has already been used.'), { status: 409 });
  const u = new URL(payload.reservationUrl || 'https://invalid.invalid/');
  if (!['www.playlocal.com', 'playlocal.com'].includes(u.hostname) || !u.pathname.includes('/reservations/new')) {
    throw Object.assign(new Error('Browser ticket contains an invalid PlayLocal URL.'), { status: 400 });
  }
  if (!payload.accountId || !payload.slot || !payload.slot.courtId) throw Object.assign(new Error('Browser ticket is incomplete.'), { status: 400 });
  usedNonces.set(payload.nonce, Date.now() + SESSION_TTL_MS);
  return payload;
}

async function getBrowser() {
  if (sharedBrowserPromise) return sharedBrowserPromise;
  sharedBrowserPromise = (async () => {
    const executablePath = await chromiumPath();
    let lastError = null;
    for (let attempt = 1; attempt <= 4; attempt++) {
      try {
        const browser = await puppeteer.launch({
          args: [...chromium.args, '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check'],
          defaultViewport: VIEWPORT,
          executablePath,
          headless: 'shell',
          dumpio: true,
        });
        browser.on('disconnected', () => {
          console.error('Shared Chromium disconnected.');
          sharedBrowserPromise = null;
          for (const session of sessions.values()) {
            if (!session.closed && session.browser === browser && session.state !== 'confirmed') {
              session.state = 'failed';
              session.statusText = 'The verification browser restarted unexpectedly. Tap Retry.';
              session.page = null;
              session.context = null;
            }
          }
        });
        console.log('Shared Chromium started.');
        return browser;
      } catch (err) {
        lastError = err;
        const busy = /ETXTBSY|text file busy/i.test(String(err?.message || err));
        if (!busy || attempt === 4) throw err;
        console.warn(`Chromium executable busy; retrying launch attempt ${attempt + 1}.`);
        await sleep(600 * attempt);
      }
    }
    throw lastError || new Error('Could not start Chromium.');
  })().catch(err => {
    sharedBrowserPromise = null;
    throw err;
  });
  return sharedBrowserPromise;
}

async function fetchSessionMaterial(bridgeId, accountId) {
  const r = await fetch(MAIN_API + '/browser-session', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'authorization': 'Bearer ' + SHARED_SECRET,
    },
    body: JSON.stringify({ bridgeId, accountId }),
  });
  const data = await r.json().catch(() => null);
  if (!r.ok || !data?.ok || !Array.isArray(data.cookies) || !data.cookies.length) {
    throw new Error(data?.message || 'Could not transfer the authenticated PlayLocal session.');
  }
  return data;
}

async function clearBrowserCookies(page) {
  const client = await page.createCDPSession();
  try {
    await client.send('Network.clearBrowserCookies');
  } finally {
    try { await client.detach(); } catch {}
  }
}

async function applySessionMaterial(page, material) {
  await clearBrowserCookies(page);
  await page.setUserAgent(material.userAgent || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36');
  await page.setExtraHTTPHeaders({ 'Accept-Language': 'en-US,en;q=0.9' });
  const cookies = (material.cookies || []).map(c => ({
    name: String(c.name || ''),
    value: String(c.value || ''),
    domain: String(c.domain || '.playlocal.com'),
    path: String(c.path || '/'),
    secure: !!c.secure,
  })).filter(c => c.name);
  if (!cookies.length) throw new Error('Authenticated PlayLocal session contained no cookies.');
  await page.setCookie(...cookies);
}

async function navigateReservation(page, payload) {
  const response = await page.goto(payload.reservationUrl, {
    waitUntil: 'domcontentloaded', timeout: 30000,
    referer: 'https://www.playlocal.com/facilities',
  });
  const path = (() => { try { return new URL(page.url()).pathname; } catch { return ''; } })();
  if (path === '/sign_in') throw new Error('PlayLocal did not accept the transferred authenticated session. Please retry.');
  console.log(`PlayLocal reservation navigation status=${response?.status?.() || 0} url=${page.url()}`);
}

async function tryPrepareReservation(page, payload) {
  return page.evaluate(prepareReservationDOM, payload.slot);
}

async function inspect(session) { return inspectSession(session); }

function requireSession(req, res, next) {
  const session = sessions.get(req.params.id);
  const key = req.get('X-CourtFlow-Session') || '';
  if (!session || session.closed || !safeEqual(key, session.key)) return res.status(401).json({ ok: false, message: 'Remote browser session expired.' });
  session.lastActivity = Date.now();
  req.remoteSession = session;
  next();
}

async function closeSession(session) {
  if (!session || session.closed) return;
  session.closed = true;
  if (session.monitor) clearInterval(session.monitor);
  try { await session.page?.close(); } catch {}
  if (session.initPromise) { try { await session.initPromise; } catch {} }
  session.page = null;
  sessions.delete(session.id);
  if (activeSessionId === session.id) activeSessionId = null;
}

app.get('/health', (req, res) => res.json({ ok: true, service: 'courtflow-browser', build: BUILD }));

app.get('/health/deep', async (req, res) => {
  if (activeSessionId) return res.status(409).json({ ok: false, message: 'A verification is active.' });
  let page = null;
  try {
    const browser = await getBrowser();
    page = await browser.newPage();
    await page.setViewport(VIEWPORT);
    await page.goto('data:text/html,<title>CourtFlow Deep Health</title><h1>ok</h1>', { waitUntil: 'domcontentloaded', timeout: 15000 });
    const title = await page.title();
    const image = await page.screenshot({ type: 'jpeg', quality: 68, fullPage: false, captureBeyondViewport: false });
    if (title !== 'CourtFlow Deep Health' || !image || image.length < 100) throw new Error('Chromium deep health check returned an invalid result.');
    res.json({ ok: true, service: 'courtflow-browser', chromium: 'ready', singleActivePage: true, frameBytes: image.length });
  } catch (err) {
    console.error('Deep health failed:', err?.stack || err);
    res.status(500).json({ ok: false, service: 'courtflow-browser', message: err.message || String(err) });
  } finally {
    try { await page?.close(); } catch {}
  }
});

async function initializeSession(session, dependencies = {}) {
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

app.post('/session/start', async (req, res) => {
  try {
    const payload = verifyTicket(req.body?.ticket);
    if (!payload.bridgeId) throw new Error('Browser ticket is missing its authenticated session bridge.');
    if (activeSessionId) {
      return res.status(409).json({ ok: false, code: 'BROWSER_BUSY', message: 'Another verification is open. Close it before starting another one.' });
    }
    const id = crypto.randomBytes(18).toString('base64url');
    const key = crypto.randomBytes(24).toString('base64url');
    const session = {
      id, key, page: null, browser: null, payload,
      initializing: true, frameReady: false, submissionAttempted: false,
      readOnly: req.body?.readOnly === true,
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
    activeSessionId = id;
    res.json({ ok: true, sessionId: id, sessionKey: key, state: session.state, statusText: session.statusText, viewport: VIEWPORT });
    session.initPromise = initializeSession(session);
  } catch (err) {
    console.error('start session failed:', err?.stack || err);
    res.status(err.status || 500).json({ ok: false, message: err.message || String(err) });
  }
});

app.get('/session/:id/status', requireSession, async (req, res) => {
  const s = req.remoteSession;
  await inspect(s);
  res.json({ ok: true, state: s.state, statusText: s.statusText, viewport: VIEWPORT, build: BUILD, readOnly: !!s.readOnly, selectedCourtId: s.selectedCourtId || '', challengePresent: !!s.challengePresent, submissionAttempted: !!s.submissionAttempted, frameReady: !!s.frameReady && !s.initializing && !!s.page && !s.page.isClosed() && s.state !== 'failed', ageSeconds: Math.round((Date.now() - s.createdAt) / 1000) });
});

app.get('/session/:id/frame', requireSession, async (req, res) => {
  try {
    if (!req.remoteSession.frameReady || req.remoteSession.initializing || !req.remoteSession.page || req.remoteSession.page.isClosed()) return res.status(425).json({ ok: false, message: 'Remote browser is still starting.' });
    const image = await req.remoteSession.page.screenshot({ type: 'jpeg', quality: 68, fullPage: false, captureBeyondViewport: false });
    res.type('jpeg').send(Buffer.from(image));
  } catch (err) {
    res.status(500).json({ ok: false, message: err.message || String(err) });
  }
});

app.post('/session/:id/input', requireSession, async (req, res) => {
  const s = req.remoteSession;
  if (s.readOnly || s.initializing || !s.frameReady || !s.page || s.page.isClosed() || s.state === 'failed') return res.status(409).json({ ok: false, message: s.readOnly ? 'Input is disabled during a read-only display test.' : 'Wait for the verification page to load.' });
  try {
    const body = req.body || {};
    if (body.type === 'click') {
      const x = Math.max(0, Math.min(VIEWPORT.width - 1, Number(body.x) || 0));
      const y = Math.max(0, Math.min(VIEWPORT.height - 1, Number(body.y) || 0));
      await s.page.mouse.click(x, y);
    } else if (body.type === 'wheel') {
      await s.page.mouse.wheel({ deltaY: Math.max(-1200, Math.min(1200, Number(body.deltaY) || 0)) });
    } else if (body.type === 'text') {
      const text = String(body.text || '').slice(0, 200);
      if (text) await s.page.keyboard.type(text, { delay: 20 });
    } else if (body.type === 'key') {
      const allowed = new Set(['Enter','Tab','Escape','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Backspace','Space']);
      if (allowed.has(body.key)) await s.page.keyboard.press(body.key);
    } else {
      return res.status(400).json({ ok: false, message: 'Unsupported input type.' });
    }
    s.lastActivity = Date.now();
    setTimeout(() => inspect(s), 150);
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ ok: false, message: err.message || String(err) });
  }
});

app.delete('/session/:id', requireSession, async (req, res) => {
  await closeSession(req.remoteSession);
  res.json({ ok: true });
});

setInterval(() => {
  const now = Date.now();
  for (const [nonce, exp] of usedNonces) if (exp < now) usedNonces.delete(nonce);
  for (const s of sessions.values()) if (now - s.lastActivity > SESSION_TTL_MS) closeSession(s);
}, 30000).unref();

process.on('SIGTERM', async () => {
  for (const s of sessions.values()) await closeSession(s);
  process.exit(0);
});

async function warmBrowserRuntime() {
  for (let attempt = 1; attempt <= 3; attempt++) {
    let page = null;
    try {
      const browser = await getBrowser();
      page = await browser.newPage();
      await page.setViewport(VIEWPORT);
      await page.goto('data:text/html,<title>CourtFlow Runtime Warmup</title><h1>ok</h1>', { waitUntil: 'domcontentloaded', timeout: 15000 });
      const image = await page.screenshot({ type: 'jpeg', quality: 68, fullPage: false, captureBeyondViewport: false });
      if (!image || image.length < 100) throw new Error('Runtime warmup frame was invalid.');
      await page.close();
      console.log(`CourtFlow runtime Chromium warmup passed on attempt ${attempt}.`);
      return;
    } catch (err) {
      try { await page?.close(); } catch {}
      console.error(`CourtFlow runtime Chromium warmup attempt ${attempt} failed:`, err?.stack || err);
      sharedBrowserPromise = null;
      if (attempt < 3) await sleep(900 * attempt);
    }
  }
  console.error('CourtFlow runtime Chromium warmup failed after 3 attempts.');
}

if (require.main === module) {
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

