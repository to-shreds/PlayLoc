'use strict';

// These DOM functions run in PlayLocal's page. They never alter verification tokens.
function prepareReservationDOM({ courtId }) {
  const id = String(courtId);
  const controls = [...document.querySelectorAll('select[name="reservation[reservable_id]"], input[name="reservation[reservable_id]"]')];
  if (!controls.length) return { ready: false };
  const exact = controls.find(el => !el.disabled && (el.tagName === 'SELECT'
    ? [...el.options].some(o => o.value === id && !o.disabled)
    : el.value === id));
  if (!exact) return { fatal: true, message: 'PlayLocal no longer offers the selected court for this time.' };
  const form = exact.form;
  if (!form) return { fatal: true, message: 'The selected court is not inside a reservation form.' };
  if (exact.tagName === 'SELECT') {
    exact.value = id;
    exact.dispatchEvent(new Event('input', { bubbles: true }));
    exact.dispatchEvent(new Event('change', { bubbles: true }));
  } else if (exact.type === 'radio') {
    exact.click();
    exact.checked = true;
    exact.dispatchEvent(new Event('change', { bubbles: true }));
  } else if (exact.type !== 'hidden') {
    return { fatal: true, message: 'The selected court uses an unsupported reservation control.' };
  }
  if (String(new FormData(form).get('reservation[reservable_id]') || '') !== id) {
    return { fatal: true, message: 'PlayLocal did not retain the exact selected court.' };
  }
  form.setAttribute('data-courtflow-reservation', 'true');
  for (const box of form.querySelectorAll('input[type="checkbox"]')) {
    const label = `${box.name || ''} ${box.id || ''} ${box.getAttribute('aria-label') || ''}`;
    if (/term|policy|agree|accept/i.test(label) && !box.checked && !box.disabled) box.click();
  }
  const focus = form.querySelector('.cf-turnstile, .g-recaptcha, .h-captcha, iframe, button[type="submit"], input[type="submit"]') || exact;
  focus.scrollIntoView({ block: 'center' });
  return { ready: true, selectedCourtId: id };
}

function handlePendingReservationDOM(slot) {
  const controls = [...document.querySelectorAll('button, a, input[type="button"], input[type="submit"]')];
  const label = el => String(el.innerText || el.value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const continueButton = controls.find(el => label(el) === 'continue reservation');
  const newButton = controls.find(el => label(el) === 'new reservation');
  if (!continueButton || !newButton) return { present: false };

  const container = newButton.closest('[role="dialog"], .modal, .modal-dialog, .modal-content, .dialog, .popup') || continueButton.parentElement?.parentElement || document.body;
  const text = String(container?.innerText || document.body?.innerText || '').replace(/\s+/g, ' ').trim();
  if (!/another reservation is in progress/i.test(text)) return { present: false };

  const normalize = value => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  const facilityMatch = !slot.facilityName || normalize(text).includes(normalize(slot.facilityName));

  const [y, m, d] = String(slot.date || '').split('-').map(Number);
  let dateMatch = false;
  if (y && m && d) {
    const dt = new Date(Date.UTC(y, m - 1, d));
    const monthDay = new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', timeZone: 'UTC' }).format(dt);
    const weekdayMonthDay = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric', timeZone: 'UTC' }).format(dt);
    const hay = normalize(text);
    dateMatch = hay.includes(normalize(monthDay)) || hay.includes(normalize(weekdayMonthDay));
  }

  const timeValues = [];
  for (const match of text.matchAll(/\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/ig)) {
    let hour = Number(match[1]) % 12;
    const minute = Number(match[2] || 0);
    if (match[3].toLowerCase() === 'pm') hour += 12;
    timeValues.push(hour * 60 + minute);
  }
  const timeMatch = timeValues.includes(Number(slot.start));

  const matchesRequestedSlot = facilityMatch && dateMatch && timeMatch;
  const target = matchesRequestedSlot ? continueButton : newButton;
  const disabled = target.disabled || target.getAttribute('aria-disabled') === 'true';
  if (!disabled) target.click();

  return {
    present: true,
    clicked: !disabled,
    action: matchesRequestedSlot ? 'continue' : 'new',
    matchesRequestedSlot,
    facilityMatch,
    dateMatch,
    timeMatch,
  };
}

function reservationInfoDOM() {
  const form = document.querySelector('form[data-courtflow-reservation="true"]');
  const root = form || document;
  const challenge = root.querySelector('[name="cf-turnstile-response"], [name="g-recaptcha-response"], [name="h-captcha-response"]');
  const submit = form?.querySelector('button[type="submit"], input[type="submit"]');
  return {
    text: document.body?.innerText || '',
    formPresent: !!form,
    selectedCourtId: form ? String(new FormData(form).get('reservation[reservable_id]') || '') : '',
    challengePresent: !!challenge,
    challengeReady: !!String(challenge?.value || '').trim(),
    submitPresent: !!submit,
    submitDisabled: !submit || submit.disabled || submit.getAttribute('aria-disabled') === 'true',
  };
}

function submitReservationDOM({ courtId }) {
  const form = document.querySelector('form[data-courtflow-reservation="true"]');
  if (!form || String(new FormData(form).get('reservation[reservable_id]') || '') !== String(courtId)) return false;
  const submit = form.querySelector('button[type="submit"], input[type="submit"]');
  if (!submit || submit.disabled || submit.getAttribute('aria-disabled') === 'true') return false;
  submit.click();
  return true;
}

function confirmationLike(url, _body, submitted = false) {
  // The NEW form says "get your reservation receipt" before anything is booked.
  // Neither that text nor an HTTP 200 is evidence of a completed reservation.
  if (!submitted) return false;
  try {
    const u = new URL(url);
    return ['www.playlocal.com', 'playlocal.com'].includes(u.hostname)
      && /^\/(?:facilities\/\d+\/)?reservations\/\d+(?:\/(?:confirmation|receipt))?\/?$/.test(u.pathname);
  } catch { return false; }
}

async function inspectSession(session) {
  // A null page is NORMAL during asynchronous startup. Do not turn the first
  // status poll into a terminal failure, and do not overwrite a real failure.
  if (!session || session.closed || session.initializing || session.busyInspect
      || ['failed', 'confirmed'].includes(session.state)) return;
  session.busyInspect = true;
  try {
    const page = session.page;
    if (!page || page.isClosed()) throw new Error('The verification page closed. Retry this verification.');
    if (confirmationLike(page.url(), '', session.submissionAttempted)) {
      session.state = 'confirmed';
      session.statusText = 'Reservation submitted. Checking the account\'s actual bookings.';
      return;
    }
    if (new URL(page.url()).pathname === '/sign_in') throw new Error('The PlayLocal login expired. Retry verification to sign in again.');

    // PlayLocal can retain an unfinished reservation in the authenticated account.
    // Resolve that modal before asking the user to verify the currently requested slot.
    const modal = await page.evaluate(handlePendingReservationDOM, session.payload.slot);
    if (session.closed) return;
    if (modal.present) {
      if (modal.clicked) {
        session.prepared = false;
        session.selectedCourtId = '';
        session.challengePresent = false;
        session.pendingDraftActionAt = Date.now();
        session.frameReady = false;
        session.courtStableSince = 0;
        console.log(`Resolved PlayLocal pending reservation modal action=${modal.action} match=${modal.matchesRequestedSlot} facility=${modal.facilityMatch} date=${modal.dateMatch} time=${modal.timeMatch}`);
      }
      session.state = 'loading';
      session.statusText = modal.action === 'continue'
        ? 'Continuing the matching PlayLocal reservation and restoring your exact court...'
        : 'Clearing an older PlayLocal reservation draft and reopening your selected slot...';
      return;
    }

    if (!session.prepared) {
      session.frameReady = false;
      const prep = await page.evaluate(prepareReservationDOM, session.payload.slot);
      if (session.closed) return;
      if (prep.fatal) throw new Error(prep.message);
      if (prep.ready) {
        session.prepared = true;
        session.preparedAt = Date.now();
        session.selectedCourtId = prep.selectedCourtId;
        session.courtStableSince = Date.now();
      }
    }
    const info = await page.evaluate(reservationInfoDOM);
    if (session.closed) return;
    session.challengePresent = info.challengePresent;
    const waiting = /please wait for verification to complete|complete verification|verify you are human|verification required|checking your browser|performing security verification/i.test(info.text);
    if (!session.prepared || !info.formPresent) {
      session.frameReady = !!info.challengePresent;
      session.state = 'verification';
      session.statusText = info.challengePresent
        ? 'Complete the PlayLocal security check shown below. CourtFlow will lock the exact court afterward.'
        : 'Loading the exact requested court...';
      return;
    }
    if (info.selectedCourtId !== String(session.payload.slot.courtId)) {
      session.prepared = false;
      session.selectedCourtId = '';
      session.frameReady = false;
      session.courtStableSince = 0;
      session.state = 'loading';
      session.statusText = `PlayLocal changed the court. Restoring ${session.payload.slot.courtName} before continuing...`;
      return;
    }
    if (!session.courtStableSince) session.courtStableSince = Date.now();
    if (Date.now() - session.courtStableSince < 900) {
      session.frameReady = false;
      session.state = 'loading';
      session.statusText = `Locking ${session.payload.slot.courtName} before showing the verification page...`;
      return;
    }
    session.frameReady = true;
    if (session.readOnly) {
      session.state = 'verification';
      session.statusText = 'Read-only display test. Booking and browser input are disabled.';
      return;
    }
    if (session.submissionAttempted) {
      session.state = 'submitting';
      session.statusText = 'Submitted once. Checking PlayLocal for confirmation; do not book again.';
      return;
    }
    const ready = info.challengePresent ? info.challengeReady : !waiting && Date.now() - session.preparedAt > 3500;
    if (ready && info.submitPresent && !info.submitDisabled) {
      session.submissionAttempted = true;
      session.submitting = true;
      session.state = 'submitting';
      session.statusText = 'Verification complete. Submitting your selected court.';
      // Do not retry an uncertain submission. The Activity check reconciles it.
      if (!await page.evaluate(submitReservationDOM, session.payload.slot)) {
        session.submissionAttempted = false;
        session.submitting = false;
        session.state = 'verification';
        session.statusText = 'Waiting for PlayLocal to enable the reservation button.';
      }
      return;
    }
    session.state = 'verification';
    session.statusText = 'Complete the PlayLocal verification below. CourtFlow will book and continue automatically.';
  } catch (err) {
    if (session.closed) return;
    // Navigation can replace the execution context between two status polls.
    if (/execution context was destroyed|cannot find context|context with specified id/i.test(err.message || '')
        && session.page && !session.page.isClosed()) return;
    session.state = 'failed';
    session.statusText = err.message || String(err);
    console.error(`Remote session ${session.id} inspect failed: ${session.statusText}`);
  } finally { session.busyInspect = false; }
}

module.exports = { prepareReservationDOM, handlePendingReservationDOM, reservationInfoDOM, submitReservationDOM, confirmationLike, inspectSession };
