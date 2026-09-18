'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
process.env.COURTFLOW_BROWSER_SECRET = 'local-fixture-secret-not-a-production-secret';
const runtime = require('./server');
const flow = require('./verification-flow');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const fixture = `<!doctype html><meta name="viewport" content="width=device-width"><title>Verification fixture</title>
<style>body{font:16px sans-serif;margin:20px}label,button{display:block;padding:12px}</style>
<form id="search" onsubmit="event.preventDefault();window.searchPosts=(window.searchPosts||0)+1"><input name="search[location]" value="West Roxbury"><button type="submit">Search</button></form>
<form id="reservation" action="https://www.playlocal.com/facilities/22/reservations" method="post" onsubmit="event.preventDefault();window.bookingPosts=(window.bookingPosts||0)+1">
<h1>Your Reservation</h1><p>Next, tell your friends about the reservation and get your reservation receipt.</p>
<label><input type="radio" name="reservation[reservable_id]" value="53" checked>Court 1</label>
<label><input type="radio" name="reservation[reservable_id]" value="54">Court 2</label>
<input id="response" type="hidden" name="cf-turnstile-response" value="">
<p id="waiting">Please wait for verification to complete</p>
<button id="fixture-step" type="button" onclick="document.getElementById('response').value='LOCAL_FIXTURE_ONLY';document.getElementById('book').disabled=false;document.getElementById('waiting').hidden=true">Local fixture human step</button>
<button id="book" type="submit" disabled>Reserve court</button></form>`;
const slot = { facilityId: '22', courtId: '54', courtName: 'Court 2', facilityName: 'West Roxbury High School', date: '2026-09-25', start: 420, end: 480 };
let serial = 0;
function makeSession(extra = {}) {
  const s = { id: 'fixture-' + (++serial), key: 'fixture-key-' + serial, state: 'starting', statusText: 'Starting',
    createdAt: Date.now(), lastActivity: Date.now(), initializing: true, frameReady: false, prepared: false,
    preparedAt: 0, submissionAttempted: false, closed: false, busyInspect: false, monitor: null, page: null,
    payload: { slot, accountId: 'fixture', bridgeId: 'fixture', reservationUrl: 'https://www.playlocal.com/facilities/22/reservations/new?date=2026-09-25&time=7am' }, ...extra };
  runtime.sessions.set(s.id, s); return s;
}
function initialize(s, wait = 0) {
  s.initPromise = runtime.initializeSession(s, {
    fetchSessionMaterial: async () => { await delay(wait); return {}; },
    applySessionMaterial: async () => {},
    navigateReservation: async page => page.goto('data:text/html,' + encodeURIComponent(fixture)),
  });
  return s.initPromise;
}

test('full verification lifecycle regression suite', { timeout: 180000 }, async t => {
  const listener = runtime.app.listen(0, '127.0.0.1');
  await new Promise(resolve => listener.once('listening', resolve));
  const local = 'http://127.0.0.1:' + listener.address().port;
  t.after(async () => { await runtime.shutdownBrowser(); await new Promise(resolve => listener.close(resolve)); });
  const request = (s, suffix, method='GET') => fetch(local + '/session/' + s.id + suffix, { method, headers: { 'X-CourtFlow-Session': s.key } });

  await t.test('first status polls during delayed startup are not failures', async () => {
    const s = makeSession(); initialize(s, 1200);
    for (let i = 0; i < 3; i++) {
      const r = await request(s, '/status'), state = await r.json();
      assert.equal(r.status, 200); assert.equal(state.state, 'starting'); assert.equal(state.frameReady, false);
      await delay(100);
    }
    assert.equal((await request(s, '/frame')).status, 425);
    await s.initPromise;
    assert.equal(s.state, 'loading'); assert.equal(s.frameReady, false); assert.equal(s.selectedCourtId, '54');
    await delay(1000); await runtime.inspect(s);
    assert.equal(s.state, 'verification'); assert.equal(s.frameReady, true); assert.equal(s.selectedCourtId, '54');
    await runtime.closeSession(s);
  });
  await t.test('failed initialization retains its actual error on subsequent polls', async () => {
    const s = makeSession();
    await runtime.initializeSession(s, { fetchSessionMaterial: async () => { throw new Error('Fixture session-transfer failure'); } });
    await runtime.inspect(s);
    const state = await (await request(s, '/status')).json();
    assert.equal(state.state, 'failed'); assert.equal(state.statusText, 'Fixture session-transfer failure');
    await runtime.closeSession(s);
  });
  await t.test('closing during initialization cannot resurrect a page', async () => {
    const s = makeSession(); let pageCreated = false;
    s.initPromise = runtime.initializeSession(s, {
      fetchSessionMaterial: async () => { await delay(150); return {}; },
      getBrowser: async () => { pageCreated = true; throw new Error('Must not be called'); },
    });
    await runtime.closeSession(s);
    assert.equal(pageCreated, false); assert.equal(s.closed, true); assert.equal(s.page, null);
  });
  await t.test('new booking page containing receipt language never confirms', async () => {
    for (const submitted of [false, true]) assert.equal(flow.confirmationLike('https://www.playlocal.com/facilities/22/reservations/new', 'get your reservation receipt; reservation confirmed', submitted), false);
    assert.equal(flow.confirmationLike('https://www.playlocal.com/reservations/123', '', false), false);
    assert.equal(flow.confirmationLike('https://www.playlocal.com/reservations/123', '', true), true);
    assert.equal(flow.confirmationLike('https://www.playlocal.com/reservations/123/edit', '', true), false);
  });
  await t.test('stale PlayLocal pending reservation chooses New Reservation', async () => {
    const browser = await runtime.getBrowser(), page = await browser.newPage();
    await page.setContent(`<div role="dialog"><h2>Another reservation is in progress</h2>
      <p>You have already initiated a reservation for West Roxbury High School for Friday, September 25, 09:00 AM.</p>
      <button id="continue" onclick="window.choice='continue'">CONTINUE RESERVATION</button>
      <button id="new" onclick="window.choice='new'">NEW RESERVATION</button></div>`);
    const result = await page.evaluate(flow.handlePendingReservationDOM, slot);
    assert.equal(result.present, true);
    assert.equal(result.matchesRequestedSlot, false);
    assert.equal(result.action, 'new');
    assert.equal(await page.evaluate(() => window.choice), 'new');
    await page.close();
  });

  await t.test('matching PlayLocal pending reservation chooses Continue Reservation', async () => {
    const browser = await runtime.getBrowser(), page = await browser.newPage();
    await page.setContent(`<div role="dialog"><h2>Another reservation is in progress</h2>
      <p>You have already initiated a reservation for West Roxbury High School for Friday, September 25, 07:00 AM.</p>
      <button id="continue" onclick="window.choice='continue'">CONTINUE RESERVATION</button>
      <button id="new" onclick="window.choice='new'">NEW RESERVATION</button></div>`);
    const result = await page.evaluate(flow.handlePendingReservationDOM, slot);
    assert.equal(result.present, true);
    assert.equal(result.matchesRequestedSlot, true);
    assert.equal(result.action, 'continue');
    assert.equal(await page.evaluate(() => window.choice), 'continue');
    await page.close();
  });

  await t.test('selected court is prepared but challenge stays untouched', async () => {
    const s = makeSession(); await initialize(s); clearInterval(s.monitor); await delay(1000); await runtime.inspect(s);
    const values = await s.page.evaluate(() => ({ court: new FormData(document.getElementById('reservation')).get('reservation[reservable_id]'), token: document.getElementById('response').value, posts: window.bookingPosts || 0 }));
    assert.deepEqual(values, { court: '54', token: '', posts: 0 }); assert.equal(s.state, 'verification');
    await runtime.closeSession(s);
  });
  await t.test('only the exact reservation form submits once, never the search form', async () => {
    const s = makeSession(); await initialize(s); clearInterval(s.monitor); await delay(1000); await runtime.inspect(s);
    await s.page.click('#fixture-step');
    await runtime.inspect(s); await runtime.inspect(s); await runtime.inspect(s);
    const counts = await s.page.evaluate(() => ({ booking: window.bookingPosts || 0, search: window.searchPosts || 0 }));
    assert.deepEqual(counts, { booking: 1, search: 0 }); assert.equal(s.submissionAttempted, true);
    await runtime.closeSession(s);
  });
  await t.test('court drift hides the frame and restores the requested ID before display', async () => {
    const s = makeSession(); await initialize(s); clearInterval(s.monitor); await delay(1000); await runtime.inspect(s);
    assert.equal(s.frameReady, true); assert.equal(s.selectedCourtId, '54');
    await s.page.evaluate(() => {
      const court1 = document.querySelector('input[name="reservation[reservable_id]"][value="53"]');
      court1.click();
    });
    await runtime.inspect(s);
    assert.equal(s.frameReady, false); assert.equal(s.prepared, false); assert.equal(s.selectedCourtId, '');
    await runtime.inspect(s);
    assert.equal(s.selectedCourtId, '54'); assert.equal(s.frameReady, false);
    await delay(1000); await runtime.inspect(s);
    assert.equal(s.selectedCourtId, '54'); assert.equal(s.frameReady, true);
    assert.equal(await s.page.$eval('input[name="reservation[reservable_id]"][value="54"]', el => el.checked), true);
    await runtime.closeSession(s);
  });

  await t.test('select control chooses a nondefault exact ID', async () => {
    const browser = await runtime.getBrowser(), page = await browser.newPage();
    await page.setContent('<form><select name="reservation[reservable_id]"><option value="53">Court 1</option><option value="54">Court 2</option></select></form>');
    const prep = await page.evaluate(flow.prepareReservationDOM, slot);
    assert.equal(prep.ready, true); assert.equal(await page.$eval('select', el => el.value), '54'); await page.close();
  });
  await t.test('missing exact ID fails without a name-based substitution', async () => {
    const browser = await runtime.getBrowser(), page = await browser.newPage();
    await page.setContent('<form><input name="reservation[reservable_id]" type="radio" value="53" checked><label>Court 2</label></form>');
    const prep = await page.evaluate(flow.prepareReservationDOM, slot);
    assert.equal(prep.fatal, true); await page.close();
  });
  await t.test('frame HTTP response is an actual decodable 430 by 760 JPEG', async () => {
    const s = makeSession(); await initialize(s); clearInterval(s.monitor); await delay(1000); await runtime.inspect(s);
    const response = await request(s, '/frame');
    assert.equal(response.status, 200); assert.match(response.headers.get('content-type'), /^image\/jpeg/);
    const image = Buffer.from(await response.arrayBuffer()); assert.equal(image[0], 255); assert.equal(image[1], 216);
    const dimensions = await s.page.evaluate(base64 => new Promise((resolve, reject) => {
      const image = new Image(); image.onload = () => resolve([image.naturalWidth, image.naturalHeight]); image.onerror = reject;
      image.src = 'data:image/jpeg;base64,' + base64;
    }), image.toString('base64'));
    assert.deepEqual(dimensions, [430, 760]); await runtime.closeSession(s);
  });
  await t.test('read-only probe cannot submit or accept browser input', async () => {
    const s = makeSession({ readOnly: true }); await initialize(s); clearInterval(s.monitor);
    await s.page.click('#fixture-step'); await runtime.inspect(s);
    assert.equal(await s.page.evaluate(() => window.bookingPosts || 0), 0);
    assert.equal(s.submissionAttempted, false);
    const input = await fetch(local + '/session/' + s.id + '/input', { method: 'POST', headers: { 'content-type': 'application/json', 'X-CourtFlow-Session': s.key }, body: JSON.stringify({ type: 'click', x: 1, y: 1 }) });
    assert.equal(input.status, 409); await runtime.closeSession(s);
  });
  await t.test('invalid tickets and wrong frame keys are rejected', async () => {
    const r = await fetch(local + '/session/start', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ticket: 'invalid' }) });
    assert.equal(r.status, 401);
    const s = makeSession(); assert.equal((await fetch(local + '/session/' + s.id + '/frame')).status, 401); await runtime.closeSession(s);
  });
  await t.test('mobile frontend displays a real frame after delayed initialization and keeps booking paused', async () => {
    const browser = await runtime.getBrowser(), ui = await browser.newPage();
    await ui.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
    const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
    let fixtureSession;
    await ui.setRequestInterception(true);
    ui.on('request', async req => {
      try {
        const u = new URL(req.url());
        if (req.method() === 'OPTIONS') return req.respond({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET,POST,DELETE,OPTIONS', 'access-control-allow-headers': 'content-type,x-courtflow-session' } });
        if (u.hostname === 'to-shreds.github.io') return req.respond({ status: 200, contentType: 'text/html', body: html });
        if (u.hostname === 'courtflow-playlocal.onrender.com') {
          const b = JSON.parse(req.postData() || '{}'); let data;
          if (b.action === 'capabilities') data = { vendor: 'playlocal', siteAuthRequired: true };
          else if (b.action === 'authenticate') data = { sessionToken: 'fixture-login' };
          else if (b.action === 'browser_ticket') data = { ticket: 'fixture-ticket' };
          else data = { accounts: [], reservations: [] };
          return req.respond({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ ok: true, data }) });
        }
        if (u.hostname === 'courtflow-browser-playlocal.onrender.com') {
          if (u.pathname === '/session/start') {
            fixtureSession = makeSession(); initialize(fixtureSession, 2000);
            return req.respond({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ ok: true, sessionId: fixtureSession.id, sessionKey: fixtureSession.key, state: 'starting', viewport: runtime.VIEWPORT }) });
          }
          const r = await fetch(local + u.pathname, { method: req.method(), headers: { 'X-CourtFlow-Session': fixtureSession.key }, ...(req.method() === 'POST' ? { body: req.postData() } : {}) });
          return req.respond({ status: r.status, headers: { 'access-control-allow-origin': '*', 'content-type': r.headers.get('content-type') }, body: Buffer.from(await r.arrayBuffer()) });
        }
        if (u.protocol === 'data:' || u.protocol === 'blob:') return req.continue();
        return req.abort();
      } catch (err) { console.error('UI fixture request failed:', err.message); try { await req.abort(); } catch {} }
    });
    await ui.goto('https://to-shreds.github.io/PlayLoc/'); await delay(100);
    await ui.evaluate(slot => {
      hideSiteGate(); applyServerVault([{ id: 'fixture', name: 'Fixture' }]);
      const row = { start: 420, slot, status: 'verification', account: state.accounts[0] };
      state.plan = [row]; state.pendingVerification = { row }; renderPlan(); startRemoteBrowser(row);
    }, slot);
    await ui.waitForFunction(() => !document.getElementById('browserModal').classList.contains('hidden'));
    assert.equal(await ui.$eval('#bookPlan', el => getComputedStyle(el).display), 'none');
    await ui.waitForFunction(() => document.getElementById('browserFrame').naturalWidth === 430, { timeout: 30000 });
    assert.equal(await ui.$eval('#browserModal', el => getComputedStyle(el).display), 'flex');
    assert.equal(await ui.$eval('#browserRetry', el => getComputedStyle(el).display), 'none');
    fs.mkdirSync(path.join(__dirname, 'test-output'), { recursive: true });
    await ui.screenshot({ path: path.join(__dirname, 'test-output', 'mobile-verification-fixture.png') });
    await ui.evaluate(() => closeRemoteBrowser(true)); await ui.close();
  });
});
