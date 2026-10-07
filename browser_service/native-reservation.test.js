'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const runtime = require('./server');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const asset = fs.readFileSync(path.join(__dirname, '..', 'android', 'app', 'src', 'main', 'assets', 'reservation.js'), 'utf8');
const reservationUrl = 'https://www.playlocal.com/facilities/22/reservations/new?date=2026-10-10&time=7%3A00%20AM';
const request = { requestId: 'native-fixture-request', reservationUrl, submissionAttempted: false,
  slot: { facilityId: '22', facilityName: 'West Roxbury High School', courtId: '54', courtName: 'Court 2',
    date: '2026-10-10', start: 420, end: 480, priceCents: 0 } };

function fixture(options = {}) {
  const court = options.court || `<select name="reservation[reservable_id]">
    <option value="53">Court 1</option><option value="54">Court 2</option><option value="55">Court 3</option></select>`;
  return `<!doctype html><meta name="viewport" content="width=device-width"><title>Native reservation fixture</title>
    <form id="search" onsubmit="event.preventDefault();window.searchPosts++"><input name="search[location]" value="West Roxbury"><button type="submit">Search</button></form>
    <form id="reservation" action="${options.action || 'https://www.playlocal.com/facilities/22/reservations'}" method="post"
      onsubmit="event.preventDefault();window.bookingPosts++">
      <h1>Your Reservation</h1><p>Tell your friends and get your reservation receipt.</p>
      ${court}
      <input type="hidden" name="reservation[date]" value="${options.date || '2026-10-10'}">
      <input type="hidden" name="reservation[start_time]" value="${options.start || '7:00 AM'}">
      <input type="hidden" name="reservation[end_time]" value="${options.end || '8:00 AM'}">
      <input id="price" type="hidden" name="reservation[price_cents]" value="0">
      <input id="response" type="hidden" name="cf-turnstile-response" value="">
      <button id="fixture-human-step" type="button" onclick="document.getElementById('response').value='LOCAL_FIXTURE_CHALLENGE_COMPLETE'">Complete local fixture verification</button>
      ${options.extra || ''}<button id="book" type="submit">Reserve court</button>
    </form>
    <script>window.bookingPosts=0;window.searchPosts=0;window.signals=[];
      window.CourtFlowReservationSignal={postMessage:message=>window.signals.push(JSON.parse(message))};</script>`;
}

test('native reservation asset regression suite', { timeout: 120000 }, async t => {
  const browser = await runtime.getBrowser();
  t.after(() => runtime.shutdownBrowser());
  async function pageFor(html = fixture(), url = reservationUrl) {
    const page = await browser.newPage();
    await page.setRequestInterception(true);
    page.on('request', req => {
      if (req.isNavigationRequest() && req.frame() === page.mainFrame()) {
        req.respond({ status: 200, contentType: 'text/html', body: html }).catch(() => {});
      } else req.abort().catch(() => {});
    });
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.addScriptTag({ content: asset });
    return page;
  }
  const inspect = (page, payload = request) => page.evaluate(r => window.CourtFlowReservation.inspect(r), payload);
  const submit = (page, payload = request) => page.evaluate(r => window.CourtFlowReservation.submit(r), payload);
  async function completeFixture(page) {
    await page.click('#fixture-human-step');
    await inspect(page);
    await pause(950);
    return inspect(page);
  }
  const counts = page => page.evaluate(() => ({ booking: window.bookingPosts, search: window.searchPosts,
    signals: window.signals.map(s => ({ requestId: s.requestId, status: s.status })) }));

  await t.test('nondefault court is selected while empty verification response stays untouched', async () => {
    const page = await pageFor();
    try {
      assert.equal(await page.$eval('select', el => el.value), '53');
      assert.equal((await inspect(page)).status, 'waiting');
      assert.equal(await page.$eval('select', el => el.value), '54');
      assert.equal(await page.$eval('#response', el => Boolean(el.value)), false);
      await pause(950);
      assert.equal((await submit(page)).status, 'waiting');
      assert.deepEqual(await counts(page), { booking: 0, search: 0, signals: [] });
    } finally { await page.close(); }
  });

  await t.test('completed local verification submits the exact form once after court stability delay', async () => {
    const page = await pageFor();
    try {
      await inspect(page);
      await page.click('#fixture-human-step');
      assert.equal((await inspect(page)).status, 'waiting');
      await pause(950);
      assert.equal((await inspect(page)).status, 'ready');
      assert.equal((await submit(page)).status, 'submitted');
      assert.equal((await submit(page)).status, 'submitted');
      assert.equal((await inspect(page)).status, 'submitted');
      assert.deepEqual(await counts(page), { booking: 1, search: 0,
        signals: [{ requestId: request.requestId, status: 'submitting' }] });
    } finally { await page.close(); }
  });

  await t.test('manual reservation submit latches and prevents a second automatic or manual POST', async () => {
    const page = await pageFor();
    try {
      await inspect(page);
      assert.equal((await completeFixture(page)).status, 'ready');
      await page.click('#book');
      assert.equal((await inspect(page)).status, 'submitted');
      assert.equal((await submit(page)).status, 'submitted');
      await page.click('#book');
      assert.deepEqual(await counts(page), { booking: 1, search: 0,
        signals: [{ requestId: request.requestId, status: 'submitting' }] });
    } finally { await page.close(); }
  });

  await t.test('receipt wording on a new form cannot imply success', async () => {
    const page = await pageFor();
    try {
      assert.match(await page.$eval('#reservation', el => el.innerText), /reservation receipt/);
      const state = await inspect(page);
      assert.equal(state.status, 'waiting');
      assert.notEqual(state.submissionAttempted, true);
      assert.deepEqual(await counts(page), { booking: 0, search: 0, signals: [] });
    } finally { await page.close(); }
  });

  await t.test('iframe verification before the form remains waiting without a submission', async () => {
    const page = await pageFor('<h1>Verify you are human</h1><iframe src="https://challenges.cloudflare.com/turnstile/local-fixture"></iframe>');
    try {
      assert.equal((await inspect(page)).status, 'waiting');
      assert.equal((await submit(page)).status, 'waiting');
      assert.equal(await page.$$eval('form', forms => forms.length), 0);
    } finally { await page.close(); }
  });

  const bindings = [
    ['wrong facility URL', fixture(), reservationUrl.replace('/22/', '/23/')],
    ['wrong URL date', fixture(), reservationUrl.replace('2026-10-10', '2026-10-11')],
    ['wrong URL start', fixture(), reservationUrl.replace('7%3A00', '8%3A00')],
    ['wrong form destination', fixture({ action: 'https://www.playlocal.com/facilities/23/reservations' })],
    ['external form destination', fixture({ action: 'https://example.invalid/reservations' })],
    ['wrong form date', fixture({ date: '2026-10-11' })],
    ['wrong form start', fixture({ start: '8:00 AM' })],
    ['wrong form end', fixture({ end: '9:00 AM' })],
    ['missing requested court', fixture({ court: '<input type="hidden" name="reservation[reservable_id]" value="53">' })],
    ['conflicting court fields', fixture({ court: '<input type="hidden" name="reservation[reservable_id]" value="53"><select name="reservation[reservable_id]"><option value="54">Court 2</option></select>' })],
  ];
  for (const [name, html, url] of bindings) {
    await t.test(name + ' cannot submit', async () => {
      const page = await pageFor(html, url || reservationUrl);
      try {
        await page.click('#fixture-human-step');
        assert.equal((await inspect(page)).status, 'failed');
        assert.equal((await submit(page)).status, 'failed');
        assert.deepEqual(await counts(page), { booking: 0, search: 0, signals: [] });
      } finally { await page.close(); }
    });
  }

  await t.test('changed price after readiness blocks the submission', async () => {
    const page = await pageFor();
    try {
      await inspect(page);
      assert.equal((await completeFixture(page)).status, 'ready');
      await page.$eval('#price', el => { el.value = '500'; });
      const result = await submit(page);
      assert.equal(result.status, 'failed');
      assert.match(result.message, /price|free/i);
      assert.deepEqual(await counts(page), { booking: 0, search: 0, signals: [] });
    } finally { await page.close(); }
  });

  await t.test('visible nonzero charge is refused even with a free hidden price', async () => {
    const page = await pageFor(fixture({ extra: '<p>Total price: $5.00</p>' }));
    try {
      const result = await inspect(page);
      assert.equal(result.status, 'failed');
      assert.match(result.message, /price|free/i);
      assert.deepEqual(await counts(page), { booking: 0, search: 0, signals: [] });
    } finally { await page.close(); }
  });

  await t.test('required field validation blocks readiness and manual form submission', async () => {
    const page = await pageFor(fixture({ extra: '<label>Player name<input required name="reservation[player_name]"></label>' }));
    try {
      await inspect(page);
      assert.equal((await completeFixture(page)).status, 'waiting');
      assert.equal((await submit(page)).status, 'waiting');
      await page.click('#book');
      assert.deepEqual(await counts(page), { booking: 0, search: 0, signals: [] });
    } finally { await page.close(); }
  });
});
