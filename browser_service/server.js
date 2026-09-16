const express = require('express');
const crypto = require('crypto');
const puppeteer = require('puppeteer-core');
const chromium = require('@sparticuz/chromium');

const PORT = Number(process.env.PORT || 10000);
const MAIN_API = process.env.COURTFLOW_MAIN_API || 'https://courtflow-playlocal.onrender.com';
const SHARED_SECRET = process.env.COURTFLOW_BROWSER_SECRET || '';
const ALLOWED_ORIGIN = process.env.COURTFLOW_ALLOWED_ORIGIN || 'https://to-shreds.github.io';
const VIEWPORT = { width: 430, height: 760, deviceScaleFactor: 1, isMobile: true, hasTouch: true };
const SESSION_TTL_MS = 12 * 60 * 1000;
const sessions = new Map();
const usedNonces = new Map();

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

async function launchBrowser() {
  return puppeteer.launch({
    args: [...chromium.args, '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check'],
    defaultViewport: VIEWPORT,
    executablePath: await chromium.executablePath(),
    headless: 'shell',
  });
}

async function fetchCredentials(accountId) {
  const r = await fetch(MAIN_API + '/browser-credentials', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'authorization': 'Bearer ' + SHARED_SECRET,
    },
    body: JSON.stringify({ accountId }),
  });
  const b = await r.json().catch(() => null);
  if (!r.ok || !b?.ok || !b?.username || !b?.password) {
    throw new Error(b?.message || 'Could not retrieve the assigned PlayLocal account from CourtFlow.');
  }
  return b;
}

async function loginToPlayLocal(page, username, password) {
  await page.goto('https://www.playlocal.com/sign_in', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForSelector('input[type="password"]', { timeout: 15000 });
  const found = await page.evaluate(({ username, password }) => {
    const email = document.querySelector('input[type="email"], input[name*="email" i], input[name*="user" i]');
    const pass = document.querySelector('input[type="password"]');
    if (!email || !pass) return false;
    const set = (el, value) => {
      el.focus();
      el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    set(email, username);
    set(pass, password);
    const form = pass.form || email.form || document.querySelector('form');
    if (!form) return false;
    if (form.requestSubmit) form.requestSubmit(); else form.submit();
    return true;
  }, { username, password });
  if (!found) throw new Error('PlayLocal sign-in fields were not recognized.');
  await page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => null);
  if (new URL(page.url()).pathname === '/sign_in') {
    const stillHasPassword = await page.$('input[type="password"]');
    if (stillHasPassword) throw new Error('PlayLocal rejected the assigned account or returned to sign-in.');
  }
}

async function prepareReservation(page, payload) {
  await page.goto(payload.reservationUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForSelector('form', { timeout: 15000 });
  const result = await page.evaluate(({ courtId, courtName }) => {
    const controls = [...document.querySelectorAll('select[name*="reservable_id"], input[name*="reservable_id"]')];
    let exact = controls.find(el => String(el.value || '') === String(courtId));
    if (!exact && courtName) {
      const needle = String(courtName).trim().toLowerCase();
      exact = controls.find(el => {
        const label = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
        const text = (label?.innerText || el.closest('label,li,article,div')?.innerText || '').trim().toLowerCase();
        return text === needle || text.includes(needle);
      });
    }
    if (!exact) return { ok: false, message: 'PlayLocal no longer offers the selected court for this time.' };
    if (exact.tagName === 'SELECT') {
      exact.value = exact.value;
      exact.dispatchEvent(new Event('change', { bubbles: true }));
    } else if ((exact.type || '').toLowerCase() === 'radio') {
      exact.click();
      exact.checked = true;
      exact.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      exact.click();
    }
    for (const box of document.querySelectorAll('input[type="checkbox"]')) {
      const hay = `${box.name || ''} ${box.id || ''} ${box.getAttribute('aria-label') || ''}`.toLowerCase();
      if ((box.required || /term|policy|agree|accept/.test(hay)) && !box.checked) box.click();
    }
    const form = exact.form || exact.closest('form') || document.querySelector('form');
    if (form) form.scrollIntoView({ block: 'center' });
    return { ok: true };
  }, { courtId: payload.slot.courtId, courtName: payload.slot.courtName || '' });
  if (!result.ok) throw new Error(result.message);
}

function confirmationLike(url, body) {
  const path = (() => { try { return new URL(url).pathname; } catch { return ''; } })();
  if (/\/reservations\/\d+/.test(path) && !/\/new$/.test(path)) return true;
  return /reservation (confirmed|created|booked)|successfully reserved|reservation receipt|reservation confirmation/i.test(body || '');
}

async function inspect(session) {
  if (!session || session.closed || session.busyInspect) return;
  session.busyInspect = true;
  try {
    const page = session.page;
    if (!page || page.isClosed()) throw new Error('Remote browser closed unexpectedly.');
    const info = await page.evaluate(() => {
      const body = document.body?.innerText || '';
      const challenge = document.querySelector('input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"], input[name*="captcha" i], textarea[name*="captcha" i], input[name*="challenge" i], textarea[name*="challenge" i]');
      const submit = document.querySelector('button[type="submit"], input[type="submit"]');
      return {
        body,
        challengePresent: !!challenge,
        challengeToken: challenge ? String(challenge.value || '').trim() : '',
        submitPresent: !!submit,
        submitDisabled: !!submit?.disabled,
      };
    });
    session.lastActivity = Date.now();
    if (confirmationLike(page.url(), info.body)) {
      session.state = 'confirmed';
      session.statusText = 'PlayLocal reports the reservation was submitted. CourtFlow is confirming it in Activity.';
      return;
    }
    const lower = info.body.toLowerCase();
    if (/not available|already (reserved|booked)|unable to reserve|reservation failed/.test(lower)) {
      session.state = 'failed';
      session.statusText = 'PlayLocal rejected the reservation or the slot is no longer available.';
      return;
    }
    const waiting = /please wait for verification to complete|complete verification|verify you are human|verification required/.test(lower);
    const verificationReady = info.challengePresent ? !!info.challengeToken : (!waiting && Date.now() - session.preparedAt > 3500);
    if (!session.submitting && info.submitPresent && !info.submitDisabled && verificationReady) {
      session.submitting = true;
      session.state = 'submitting';
      session.statusText = 'Verification complete. Submitting the reservation…';
      await page.evaluate(() => {
        const submit = document.querySelector('button[type="submit"], input[type="submit"]');
        if (submit) submit.click();
      });
      setTimeout(() => { if (session && !session.closed) session.submitting = false; }, 5000);
      return;
    }
    session.state = waiting || info.challengePresent ? 'verification' : 'ready';
    session.statusText = waiting || info.challengePresent
      ? 'Complete PlayLocal verification in the window below.'
      : 'PlayLocal reservation is ready. CourtFlow is waiting for the final control to become available.';
  } catch (err) {
    session.state = 'failed';
    session.statusText = err.message || String(err);
  } finally {
    session.busyInspect = false;
  }
}

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
  sessions.delete(session.id);
  try { await session.browser?.close(); } catch {}
}

app.get('/health', (req, res) => res.json({ ok: true, service: 'courtflow-browser' }));

app.post('/session/start', async (req, res) => {
  let browser = null;
  try {
    const payload = verifyTicket(req.body?.ticket);
    const credentials = await fetchCredentials(payload.accountId);
    browser = await launchBrowser();
    const page = await browser.newPage();
    await page.setViewport(VIEWPORT);
    await page.setJavaScriptEnabled(true);
    await loginToPlayLocal(page, credentials.username, credentials.password);
    await prepareReservation(page, payload);

    const id = crypto.randomBytes(18).toString('base64url');
    const key = crypto.randomBytes(24).toString('base64url');
    const session = {
      id, key, page, browser, payload,
      state: 'verification',
      statusText: 'Opening PlayLocal verification…',
      createdAt: Date.now(),
      lastActivity: Date.now(),
      preparedAt: Date.now(),
      submitting: false,
      closed: false,
      busyInspect: false,
      monitor: null,
    };
    sessions.set(id, session);
    await inspect(session);
    session.monitor = setInterval(() => inspect(session), 650);
    res.json({ ok: true, sessionId: id, sessionKey: key, state: session.state, statusText: session.statusText, viewport: VIEWPORT });
  } catch (err) {
    try { await browser?.close(); } catch {}
    console.error('start session failed:', err?.stack || err);
    res.status(err.status || 500).json({ ok: false, message: err.message || String(err) });
  }
});

app.get('/session/:id/status', requireSession, async (req, res) => {
  const s = req.remoteSession;
  await inspect(s);
  res.json({ ok: true, state: s.state, statusText: s.statusText, viewport: VIEWPORT, ageSeconds: Math.round((Date.now() - s.createdAt) / 1000) });
});

app.get('/session/:id/frame', requireSession, async (req, res) => {
  try {
    const png = await req.remoteSession.page.screenshot({ type: 'png', fullPage: false, captureBeyondViewport: false });
    res.type('png').send(png);
  } catch (err) {
    res.status(500).json({ ok: false, message: err.message || String(err) });
  }
});

app.post('/session/:id/input', requireSession, async (req, res) => {
  const s = req.remoteSession;
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
  try { const b = await browserPromise; await b?.close(); } catch {}
  process.exit(0);
});

app.listen(PORT, '0.0.0.0', () => console.log(`CourtFlow browser service listening on ${PORT}`));
