'use strict';
const crypto = require('crypto');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function run({ port, mainAPI }) {
  const password = process.env.COURTFLOW_PROBE_SITE_PASSWORD;
  if (!password) { console.log('READONLY_PROBE skipped: no diagnostic site credential'); return; }
  const local = `http://127.0.0.1:${port}`;
  let token = '', remote = null;
  async function rpc(action, data = {}) {
    const r = await fetch(mainAPI + '/adapter', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ version: 1, action, ...data, ...(token ? { siteToken: token } : {}) }),
      signal: AbortSignal.timeout(45000),
    });
    const b = await r.json();
    if (!r.ok || !b.ok) throw new Error(`${action}: ${b.error?.code || r.status}`);
    return b.data;
  }
  async function sessionRequest(path, options = {}) {
    return fetch(local + `/session/${encodeURIComponent(remote.sessionId)}` + path, {
      ...options, headers: { ...(options.headers || {}), 'X-CourtFlow-Session': remote.sessionKey },
      signal: AbortSignal.timeout(20000),
    });
  }
  const historyHash = value => crypto.createHash('sha256').update(JSON.stringify(value.reservations || [])).digest('hex');
  try {
    const gate = await rpc('site_login', { sitePassword: password });
    token = gate.siteToken;
    const accountId = 'server-1';
    const auth = await rpc('authenticate', { accountId });
    const fields = { accountId, sessionToken: auth.sessionToken };
    const before = await rpc('history', fields);
    const slot = {
      facilityId: '22', facilityName: 'West Roxbury High School', courtId: '54', courtName: 'Court 2',
      date: process.env.COURTFLOW_PROBE_DATE || new Date(Date.now() + 86400000).toISOString().slice(0, 10),
      start: 420, end: 480, priceCents: 0, searchLocation: 'West Roxbury',
    };
    const ticket = await rpc('browser_ticket', { ...fields, slot });
    const start = await fetch(local + '/session/start', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ticket: ticket.ticket, readOnly: true }), signal: AbortSignal.timeout(15000),
    });
    remote = await start.json();
    if (!start.ok || !remote.ok) throw new Error(`start: ${remote.code || start.status}`);
    let startupPolls = 0, imageCount = 0, firstState = '', lastState = null, dimensions = null, bytes = 0;
    const deadline = Date.now() + 75000;
    while (Date.now() < deadline && imageCount < 5) {
      const response = await sessionRequest('/status');
      const state = await response.json();
      if (!response.ok || !state.ok) throw new Error(`status: ${response.status}`);
      if (!firstState) firstState = state.state;
      if (state.state === 'failed' || state.state === 'confirmed' || state.submissionAttempted) throw new Error(`Unexpected read-only state: ${state.state}`);
      if (!state.frameReady) { startupPolls++; await pause(350); continue; }
      if (state.selectedCourtId !== slot.courtId) throw new Error('Expected court was not selected');
      const frame = await sessionRequest('/frame');
      const image = Buffer.from(await frame.arrayBuffer());
      if (frame.status !== 200 || !frame.headers.get('content-type')?.startsWith('image/jpeg')
          || image[0] !== 255 || image[1] !== 216 || image.length < 100) throw new Error('Frame is not a binary JPEG');
      const live = require('./server').sessions.get(remote.sessionId);
      dimensions = await live.page.evaluate(base64 => new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
        img.onerror = () => reject(new Error('Live browser could not decode frame'));
        img.src = 'data:image/jpeg;base64,' + base64;
      }), image.toString('base64'));
      if (dimensions.width !== 430 || dimensions.height !== 760) throw new Error('Unexpected decoded viewport');
      bytes += image.length; imageCount++; lastState = state;
      await pause(1200);
    }
    if (imageCount !== 5) throw new Error('Timed out before five decoded frames');
    const denied = await sessionRequest('/input', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ type: 'click', x: 1, y: 1 }) });
    if (denied.status !== 409) throw new Error('Read-only input guard did not reject input');
    await sessionRequest('', { method: 'DELETE' }); remote = null;
    const after = await rpc('history', fields);
    const unchanged = historyHash(before) === historyHash(after);
    console.log('READONLY_PROBE ' + JSON.stringify({ ok: unchanged, firstState, startupPolls, imageCount, bytes, dimensions,
      finalState: lastState.state, selectedCourtId: lastState.selectedCourtId, challengePresent: lastState.challengePresent,
      submissionAttempted: lastState.submissionAttempted, browserInputBlocked: true, historyUnchanged: unchanged }));
  } catch (err) {
    console.error('READONLY_PROBE ' + JSON.stringify({ ok: false, message: err.message }));
  } finally {
    if (remote?.sessionId && remote?.sessionKey) { try { await sessionRequest('', { method: 'DELETE' }); } catch {} }
    token = '';
  }
}
module.exports = { run };
