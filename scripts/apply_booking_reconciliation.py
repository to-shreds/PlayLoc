from pathlib import Path

p = Path('playlocal_server.py')
s = p.read_text()

# Extend ApiError so booking failures can return a handoff URL without packing it into prose.
old = """class ApiError(Exception):
    def __init__(self, code, message, status=400, definitive=False):
        self.code = code
        self.message = message
        self.status = status
        self.definitive = definitive
        super().__init__(message)
"""
new = """class ApiError(Exception):
    def __init__(self, code, message, status=400, definitive=False, data=None):
        self.code = code
        self.message = message
        self.status = status
        self.definitive = definitive
        self.data = data or {}
        super().__init__(message)
"""
if old not in s:
    raise SystemExit('ApiError block not found')
s = s.replace(old, new, 1)

# Reuse Activity parsing for both the public history action and post-book reconciliation.
old = """def history(req):
    s = get_session(req['sessionToken'], req['accountId'])
    r = browser_get(s, BASE + '/user/reservations', referer=BASE + '/', retry_403=True)
    if urlparse(r.url).path == '/sign_in':
        raise ApiError('AUTH_REJECTED', 'PlayLocal session expired.', 401, True)
    if r.status_code == 403:
        raise ApiError('PLAYLOCAL_FORBIDDEN', 'PlayLocal refused the Activity request from the hosted connector (HTTP 403).', 502)
    r.raise_for_status()
    rows = parse_reservations(r.text)
    return {
        'asOf': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': '/user/reservations',
        'count': len(rows),
        'reservations': rows,
    }
"""
new = """def _history_for_session(s):
    r = browser_get(s, BASE + '/user/reservations', referer=BASE + '/', retry_403=True)
    if urlparse(r.url).path == '/sign_in':
        raise ApiError('AUTH_REJECTED', 'PlayLocal session expired.', 401, True)
    if r.status_code == 403:
        raise ApiError('PLAYLOCAL_FORBIDDEN', 'PlayLocal refused the Activity request from the hosted connector (HTTP 403).', 502)
    r.raise_for_status()
    return parse_reservations(r.text)


def history(req):
    s = get_session(req['sessionToken'], req['accountId'])
    rows = _history_for_session(s)
    return {
        'asOf': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': '/user/reservations',
        'count': len(rows),
        'reservations': rows,
    }
"""
if old not in s:
    raise SystemExit('history block not found')
s = s.replace(old, new, 1)

marker = "\ndef book(req):\n"
if marker not in s:
    raise SystemExit('book marker not found')
helpers = r'''
def _verification_gate(d, form=None):
    text = clean(d.get_text(' ', strip=True))
    if re.search(r'please\s+wait\s+for\s+verification\s+to\s+complete|complete\s+verification|verify\s+you\s+are\s+human', text, re.I):
        return True
    scope = form or d
    for el in scope.find_all(['input', 'textarea', 'div']):
        hay = clean(' '.join(str(el.get(k) or '') for k in ('name', 'id', 'class', 'data-sitekey', 'data-callback')))
        if re.search(r'turnstile|captcha|cf[-_ ]?challenge|challenge[-_ ]?response', hay, re.I):
            return True
    return False


def _slot_start_label(slot):
    h = int(slot['start']) // 60
    return f'{h % 12 or 12}:00 {"PM" if h >= 12 else "AM"}'


def _reservation_row_matches_slot(row, slot):
    if row.get('date') and row.get('date') != slot.get('date'):
        return False
    expected = _slot_start_label(slot).upper()
    if row.get('start') and str(row.get('start')).upper() != expected:
        return False
    text = clean((row.get('title') or '') + ' ' + (row.get('text') or '')).lower()
    wanted = clean(slot.get('courtName') or '').lower()
    if wanted and re.search(r'court\s*\d+', wanted, re.I):
        # History usually contains the court name. If it does, require the exact court;
        # if it omits court text entirely, date/time is still a useful unique match.
        has_any_court = bool(re.search(r'court\s*\d+', text, re.I))
        if has_any_court and wanted not in text:
            return False
    return bool(row.get('date') or row.get('start'))


def _reconcile_created_reservation(s, slot):
    rows = _history_for_session(s)
    return next((row for row in rows if _reservation_row_matches_slot(row, slot)), None)

'''
s = s.replace(marker, helpers + marker, 1)

old = """    r = submit(s, p, form, set_fields(form, slot))
    body = clean(soup(r.text).get_text(' ', strip=True))
    if re.search(r'error|unable|failed|not available|already (?:reserved|booked)', body, re.I):
        raise ApiError('BOOKING_REJECTED', body[:300], 409, True)
    m = re.search(r'/reservations/(\\d+)', urlparse(r.url).path)
    if not (m or re.search(r'reservation (?:confirmed|created|booked)|successfully reserved|confirmation', body, re.I)):
        raise ApiError('UNKNOWN_OUTCOME', 'PlayLocal responded, but CourtFlow could not prove that the reservation was created.', 502)
    result = {'id': m.group(1) if m else 'playlocal-' + key[:12], **slot, 'accountId': req['accountId'], 'status': 'confirmed', 'idempotencyKey': key}
"""
new = """    # PlayLocal currently gates the final reservation submission with browser-side
    # verification. A raw HTTP POST cannot legitimately manufacture that token.
    if _verification_gate(d, form):
        raise ApiError(
            'VERIFICATION_REQUIRED',
            'PlayLocal requires browser verification before it will create this reservation.',
            409,
            True,
            {'reservationUrl': booking_url},
        )

    r = submit(s, p, form, set_fields(form, slot))
    rd = soup(r.text)
    body = clean(rd.get_text(' ', strip=True))
    m = re.search(r'/reservations/(\\d+)', urlparse(r.url).path)
    confirmed = bool(m or re.search(r'reservation (?:confirmed|created|booked)|successfully reserved|confirmation', body, re.I))

    reconciled = None
    if not confirmed:
        # The Activity endpoint is authoritative for this account. Check it before
        # ever reporting an ambiguous result.
        reconciled = _reconcile_created_reservation(s, slot)
        confirmed = reconciled is not None

    if not confirmed:
        if _verification_gate(rd):
            raise ApiError(
                'VERIFICATION_REQUIRED',
                'PlayLocal did not create the reservation because browser verification is required.',
                409,
                True,
                {'reservationUrl': booking_url},
            )
        if re.search(r'error|unable|failed|not available|already (?:reserved|booked)', body, re.I):
            raise ApiError('BOOKING_REJECTED', body[:300], 409, True)
        raise ApiError('BOOKING_REJECTED', 'PlayLocal did not create this reservation.', 409, True)

    resolved_id = m.group(1) if m else (reconciled.get('id') if reconciled else 'playlocal-' + key[:12])
    result = {'id': resolved_id, **slot, 'accountId': req['accountId'], 'status': 'confirmed', 'idempotencyKey': key, 'reconciled': bool(reconciled and not m)}
"""
if old not in s:
    raise SystemExit('booking confirmation block not found')
s = s.replace(old, new, 1)

# Include ApiError.data in the adapter response.
old = """            payload = {'version': 1, 'ok': False, 'error': {'code': e.code, 'message': e.message, 'definitive': e.definitive}}
            status = e.status
"""
new = """            err = {'code': e.code, 'message': e.message, 'definitive': e.definitive}
            if e.data:
                err['data'] = e.data
            payload = {'version': 1, 'ok': False, 'error': err}
            status = e.status
"""
if old not in s:
    raise SystemExit('error payload block not found')
s = s.replace(old, new, 1)

p.write_text(s)

# Frontend: preserve structured adapter errors, carry the exact reservation URL,
# and give the user a direct continuation button if PlayLocal asks for verification.
p = Path('index.html')
h = p.read_text()

old = """<div class=\"card\"><h2>Plan</h2><div id=\"plan\" class=\"muted\">No plan yet.</div><button class=\"btn primary hidden\" id=\"bookPlan\">Book planned slots</button></div>"""
new = """<div class=\"card\"><h2>Plan</h2><div id=\"plan\" class=\"muted\">No plan yet.</div><button class=\"btn primary hidden\" id=\"bookPlan\">Book planned slots</button><div id=\"bookingHelp\" class=\"small\" style=\"margin-top:10px\"></div></div>"""
if old not in h:
    raise SystemExit('plan card block not found')
h = h.replace(old, new, 1)

old = """async function rpc(action,payload={}){if(!state.adapter)throw Error('Set the backend adapter URL in Settings.');let r=await fetch(state.adapter,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({version:1,action,...payload})});let b=await r.json().catch(()=>null);if(!r.ok||!b?.ok)throw Error(b?.error?.message||'Adapter request failed');return b.data}"""
new = """async function rpc(action,payload={}){if(!state.adapter)throw Error('Set the backend adapter URL in Settings.');let r=await fetch(state.adapter,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({version:1,action,...payload})});let b=await r.json().catch(()=>null);if(!r.ok||!b?.ok){let e=Error(b?.error?.message||'Adapter request failed');e.code=b?.error?.code||'ADAPTER_ERROR';e.data=b?.error?.data||{};e.definitive=!!b?.error?.definitive;throw e}return b.data}"""
if old not in h:
    raise SystemExit('rpc block not found')
h = h.replace(old, new, 1)

old = """        reservationHref:exact?.reservationHref||f?.reservationHref||base.reservationHref||'',
        reservationReferer:exact?.reservationReferer||f?.reservationReferer||base.reservationReferer||''
"""
new = """        reservationHref:exact?.reservationHref||f?.reservationHref||base.reservationHref||'',
        reservationReferer:exact?.reservationReferer||f?.reservationReferer||base.reservationReferer||'',
        reservationUrl:exact?.reservationUrl||''
"""
if old not in h:
    raise SystemExit('slot reservation metadata block not found')
h = h.replace(old, new, 1)

old = """$('bookPlan').onclick=async()=>{for(let r of state.plan.filter(x=>x.status==='planned')){try{await doBook(r.slot,r.account);log(`Booked ${t(r.start)} with ${r.account.name}`)}catch(e){log(`Stopped at ${t(r.start)}: ${e.message}`);break}}renderBookings()};"""
new = """$('bookPlan').onclick=async()=>{let help=$('bookingHelp');help.innerHTML='';for(let r of state.plan.filter(x=>x.status==='planned')){try{let result=await doBook(r.slot,r.account);log(`Booked ${t(r.start)} with ${r.account.name}${result?.reconciled?' (confirmed in PlayLocal Activity)':''}`)}catch(e){if(e.code==='VERIFICATION_REQUIRED'){let u=e.data?.reservationUrl||r.slot.reservationUrl||'';log(`Stopped at ${t(r.start)}: PlayLocal requires browser verification before booking.`);if(u)help.innerHTML=`<a class=\"btn primary\" href=\"${esc(u)}\" target=\"_blank\" rel=\"noopener\">Verify and book ${t(r.start)} on PlayLocal</a>`}else{log(`Stopped at ${t(r.start)}: ${e.message}`)}break}}await refreshCurrentBookings();renderBookings()};"""
if old not in h:
    raise SystemExit('bookPlan block not found')
h = h.replace(old, new, 1)

p.write_text(h)
