/* Runs only in PlayLocal's top document. Never modifies CAPTCHA response fields. */
(function (root) {
  'use strict';
  function minutes(value) {
    const m = String(value || '').trim().match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/i);
    if (!m) return null;
    let h = Number(m[1]); const n = Number(m[2] || 0);
    if (n > 59 || h > (m[3] ? 12 : 23) || (m[3] && h < 1)) return null;
    if (m[3]) h = h % 12 + (/pm/i.test(m[3]) ? 12 : 0);
    return h * 60 + n;
  }
  function day(value) {
    const raw = String(value || '').trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
    const m = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    return m ? m[3] + '-' + m[1].padStart(2, '0') + '-' + m[2].padStart(2, '0') : '';
  }
  function info(status, message, extra) { return Object.assign({ status, message }, extra || {}); }
  function pending(slot) {
    const controls = [...document.querySelectorAll('button,a,input[type=button],input[type=submit]')];
    const text = el => String(el.innerText || el.value || '').replace(/\s+/g, ' ').trim();
    const next = controls.find(el => /^continue reservation$/i.test(text(el)));
    const fresh = controls.find(el => /^new reservation$/i.test(text(el)));
    if (!next || !fresh) return false;
    const box = fresh.closest('[role=dialog],.modal,.modal-dialog,.modal-content,.dialog,.popup') || next.parentElement?.parentElement;
    const body = String(box?.innerText || document.body?.innerText || '');
    if (!/another reservation is in progress/i.test(body)) return false;
    const normalize = s => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    const date = new Date(slot.date + 'T12:00:00Z');
    const dateLabel = new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', timeZone: 'UTC' }).format(date);
    const matches = normalize(body).includes(normalize(slot.facilityName)) && normalize(body).includes(normalize(dateLabel)) && [...body.matchAll(/\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b/ig)].some(m => minutes(m[0]) === slot.start);
    const target = matches ? next : fresh;
    if (!target.disabled) target.click();
    return true;
  }
  function binding(request, form) {
    const slot = request.slot;
    const url = new URL(location.href);
    if (!['www.playlocal.com', 'playlocal.com'].includes(url.hostname) || url.protocol !== 'https:' || url.pathname !== new URL(request.reservationUrl).pathname) return 'PlayLocal moved away from the requested reservation.';
    if (day(url.searchParams.get('date')) !== slot.date || minutes(url.searchParams.get('time')) !== slot.start) return 'The reservation date or start time changed.';
    const action = new URL(form.action || location.href, location.href);
    if (!['www.playlocal.com', 'playlocal.com'].includes(action.hostname) || action.protocol !== 'https:' || !(action.pathname === new URL(request.reservationUrl).pathname.replace(/\/new$/, '') || action.pathname === '/reservations' || action.pathname === '/reservations/')) return 'The reservation form has an unexpected destination.';
    if (String(new FormData(form).get('reservation[reservable_id]') || '') !== String(slot.courtId)) return 'The selected court changed.';
    if ([...String(form.innerText || '').matchAll(/\$\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)/g)].some(m => Number(m[1].replace(/,/g, '')) > 0)) return 'The reservation price changed. CourtFlow only books free courts.';
    let hasEnd = false;
    for (const el of form.elements) {
      if (!el.name || el.disabled || /checkbox|radio/.test(el.type || '')) continue;
      const key = (el.name.match(/\[([^\]]+)\]$/)?.[1] || el.name).toLowerCase();
      const value = String(el.value || '').trim();
      if (/^(?:price|price_cents|total|total_price|amount|amount_cents|cost)$/.test(key) && Number(value.replace(/[$,]/g, '')) > 0) return 'The reservation price changed. CourtFlow only books free courts.';
      if (/^(?:date|reservation_date|reserved_date|day)$/.test(key) && day(value) !== slot.date) return 'The reservation form contains a different date.';
      if (/^(?:start|start_time|time|reserved_time|reservation_time)$/.test(key) && minutes(value) !== slot.start) return 'The reservation form contains a different start time.';
      if (/^(?:end|end_time)$/.test(key)) { hasEnd = true; if (minutes(value) !== slot.end) return 'The reservation form contains a different end time.'; }
      if (/^(?:duration|duration_minutes)$/.test(key)) { hasEnd = true; if (Number(value) !== slot.end - slot.start) return 'The reservation duration changed.'; }
    }
    if (!hasEnd && slot.end - slot.start !== 60) return 'PlayLocal does not expose the requested reservation duration.';
    return '';
  }
  function challengeReady(form) {
    const responses = [...form.querySelectorAll('[name="cf-turnstile-response"],[name="g-recaptcha-response"],[name="h-captcha-response"]')];
    const widget = document.querySelector('.cf-turnstile,.g-recaptcha,.h-captcha,iframe[src*="challenges.cloudflare.com"],iframe[src*="recaptcha"],iframe[src*="hcaptcha.com"]');
    if (responses.length) return responses.every(el => String(el.value || '').trim());
    return !widget && !/please wait for verification to complete|complete verification|verify you are human/i.test(document.body?.innerText || '');
  }
  function signal(request) {
    if (root.CourtFlowReservationSignal) root.CourtFlowReservationSignal.postMessage(JSON.stringify({ requestId: request.requestId, status: 'submitting' }));
  }
  function inspect(request) {
    if (request.submissionAttempted) {
      if (!document.__courtflowSubmissionLocked) { document.__courtflowSubmissionLocked = true; document.addEventListener('submit', event => { event.preventDefault(); event.stopImmediatePropagation(); }, true); }
      document.querySelectorAll('button[type=submit],input[type=submit]').forEach(el => { el.disabled = true; });
      return info('submitted', 'Reservation submitted once. Checking Activity.', { submissionAttempted: true });
    }
    if (pending(request.slot)) return info('waiting', 'Opening the requested reservation.');
    const slot = request.slot;
    const controls = [...document.querySelectorAll('select[name="reservation[reservable_id]"],input[name="reservation[reservable_id]"]')];
    if (!controls.length) return info('waiting', 'Complete PlayLocal verification if it asks.');
    const exact = controls.find(el => !el.disabled && (el.tagName === 'SELECT' ? [...el.options].some(o => o.value === String(slot.courtId) && !o.disabled) : String(el.value) === String(slot.courtId)));
    if (!exact || !exact.form) return info('failed', 'PlayLocal no longer offers the exact requested court.');
    const form = exact.form;
    if (exact.tagName === 'SELECT') { if (exact.value !== String(slot.courtId)) { exact.value = String(slot.courtId); exact.dispatchEvent(new Event('input', { bubbles: true })); exact.dispatchEvent(new Event('change', { bubbles: true })); } }
    else if (exact.type === 'radio') { if (!exact.checked) { exact.click(); exact.checked = true; exact.dispatchEvent(new Event('change', { bubbles: true })); } }
    else if (exact.type !== 'hidden') return info('failed', 'PlayLocal uses an unsupported court selection.');
    const problem = binding(request, form);
    if (problem) return info('failed', problem);
    form.dataset.courtflowReservation = request.requestId;
    for (const box of form.querySelectorAll('input[type=checkbox]')) {
      if (/term|policy|agree|accept/i.test([box.name, box.id, box.getAttribute('aria-label')].join(' ')) && !box.disabled && !box.checked) box.click();
    }
    let guard = root.__courtflowReservationGuard;
    if (!guard || guard.requestId !== request.requestId) guard = root.__courtflowReservationGuard = { requestId: request.requestId, attempted: false, lastCourt: '', stableAt: Date.now() };
    if (!form.__courtflowGuard) {
      form.__courtflowGuard = true;
      form.addEventListener('submit', function (event) {
        const state = root.__courtflowReservationGuard;
        const error = binding(request, form);
        if (!state || state.requestId !== request.requestId || state.attempted || error || !challengeReady(form) || !form.checkValidity()) { event.preventDefault(); event.stopImmediatePropagation(); return; }
        state.attempted = true;
        signal(request);
      }, true);
    }
    if (guard.attempted) return info('submitted', 'Reservation submitted once. Checking Activity.', { submissionAttempted: true });
    const selected = String(new FormData(form).get('reservation[reservable_id]') || '');
    if (guard.lastCourt !== selected) { guard.lastCourt = selected; guard.stableAt = Date.now(); }
    const errors = [...document.querySelectorAll('[role=alert],.alert-danger,#error_explanation,.validation-error')].some(el => String(el.innerText || '').trim());
    if (errors) return info('failed', 'PlayLocal rejected the reservation form. Check Activity before retrying.');
    const submit = form.querySelector('button[type=submit],input[type=submit]');
    if (!challengeReady(form)) return info('waiting', 'Court ' + String(slot.courtName || slot.courtId).replace(/^.*?([123])$/, '$1') + ' selected. Complete PlayLocal verification.', { prepared: true });
    if (!form.checkValidity()) return info('waiting', 'Complete the required fields on the reservation form.', { prepared: true });
    if (!submit || submit.disabled || submit.getAttribute('aria-disabled') === 'true' || Date.now() - guard.stableAt < 900) return info('waiting', 'Waiting for the reservation form.', { prepared: true });
    return info('ready', 'Verification complete. Submitting the requested reservation once.', { prepared: true });
  }
  function submit(request) {
    const state = inspect(Object.assign({}, request, { submissionAttempted: false }));
    if (state.status !== 'ready') return state;
    const form = document.querySelector('form[data-courtflow-reservation="' + request.requestId + '"]');
    const button = form && form.querySelector('button[type=submit],input[type=submit]');
    if (!button || binding(request, form)) return info('failed', 'The exact reservation is no longer ready.');
    // The native latch is already set before this single click. No timers retry it.
    button.click();
    return info('submitted', 'Reservation submitted once. Checking Activity.', { submissionAttempted: true });
  }
  root.CourtFlowReservation = { inspect, submit };
})(window);
