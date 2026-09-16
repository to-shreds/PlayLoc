from pathlib import Path

p=Path('browser_service/server.js')
s=p.read_text()

old=r'''async function prepareReservation(page, payload) {
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
'''
new=r'''async function navigateReservation(page, payload) {
  const response = await page.goto(payload.reservationUrl, {
    waitUntil: 'domcontentloaded', timeout: 30000,
    referer: 'https://www.playlocal.com/facilities',
  });
  const path = (() => { try { return new URL(page.url()).pathname; } catch { return ''; } })();
  if (path === '/sign_in') throw new Error('PlayLocal did not accept the transferred authenticated session. Please retry.');
  console.log(`PlayLocal reservation navigation status=${response?.status?.() || 0} url=${page.url()}`);
}

async function tryPrepareReservation(page, payload) {
  return page.evaluate(({ courtId, courtName }) => {
    const controls = [...document.querySelectorAll('select[name*="reservable_id"], input[name*="reservable_id"]')];
    if (!controls.length) return { ready: false };
    let exact = controls.find(el => String(el.value || '') === String(courtId));
    if (!exact && courtName) {
      const needle = String(courtName).trim().toLowerCase();
      exact = controls.find(el => {
        const label = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
        const text = (label?.innerText || el.closest('label,li,article,div')?.innerText || '').trim().toLowerCase();
        return text === needle || text.includes(needle);
      });
    }
    if (!exact) return { ready: false, fatal: true, message: 'PlayLocal no longer offers the selected court for this time.' };
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
    return { ready: true };
  }, { courtId: payload.slot.courtId, courtName: payload.slot.courtName || '' });
}
'''
if old not in s: raise SystemExit('prepareReservation block not found')
s=s.replace(old,new,1)

old=r'''    const lower = info.body.toLowerCase();
    if (/not available|already (reserved|booked)|unable to reserve|reservation failed/.test(lower)) {
      session.state = 'failed';
      session.statusText = 'PlayLocal rejected the reservation or the slot is no longer available.';
      return;
    }
    const waiting = /please wait for verification to complete|complete verification|verify you are human|verification required/.test(lower);
    const verificationReady = info.challengePresent ? !!info.challengeToken : (!waiting && Date.now() - session.preparedAt > 3500);
'''
new=r'''    const lower = info.body.toLowerCase();
    if (/not available|already (reserved|booked)|unable to reserve|reservation failed/.test(lower)) {
      session.state = 'failed';
      session.statusText = 'PlayLocal rejected the reservation or the slot is no longer available.';
      return;
    }
    const waiting = /please wait for verification to complete|complete verification|verify you are human|verification required|checking your browser|performing security verification/.test(lower);
    if (!session.prepared) {
      const prep = await tryPrepareReservation(page, session.payload);
      if (prep?.fatal) {
        session.state = 'failed';
        session.statusText = prep.message || 'The selected court is no longer available.';
        return;
      }
      if (prep?.ready) {
        session.prepared = true;
        session.preparedAt = Date.now();
        session.state = waiting || info.challengePresent ? 'verification' : 'ready';
        session.statusText = waiting || info.challengePresent
          ? 'Complete PlayLocal verification in the window below.'
          : 'Reservation form is ready. CourtFlow is waiting for PlayLocal verification.';
        return;
      }
      session.state = waiting || info.challengePresent ? 'verification' : 'loading';
      session.statusText = waiting || info.challengePresent
        ? 'Complete PlayLocal verification in the window below.'
        : 'PlayLocal is loading the reservation form. If a verification control appears, complete it below.';
      return;
    }
    const verificationReady = info.challengePresent ? !!info.challengeToken : (!waiting && Date.now() - session.preparedAt > 3500);
'''
if old not in s: raise SystemExit('inspect marker not found')
s=s.replace(old,new,1)

old=r'''    await applySessionMaterial(page, material);
    await prepareReservation(page, payload);
    if (new URL(page.url()).pathname === '/sign_in') {
      throw new Error('PlayLocal did not accept the transferred authenticated session. Please retry.');
    }

    const id = crypto.randomBytes(18).toString('base64url');
'''
new=r'''    await applySessionMaterial(page, material);
    await navigateReservation(page, payload);

    const id = crypto.randomBytes(18).toString('base64url');
'''
if old not in s: raise SystemExit('session navigation marker not found')
s=s.replace(old,new,1)

s=s.replace("      preparedAt: Date.now(),\n", "      prepared: false,\n      preparedAt: 0,\n",1)
p.write_text(s)
