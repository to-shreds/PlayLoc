from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlparse, urlencode, parse_qsl
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import hashlib, json, os, re, secrets, threading, time, requests
from curl_cffi import requests as curl_requests

BASE = 'https://www.playlocal.com'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
SESSIONS = {}
IDEM = {}
LOCK = threading.RLock()
SITE_TOKENS = {}
SITE_TOKEN_TTL = 12 * 60 * 60

class ApiError(Exception):
    def __init__(self, code, message, status=400, definitive=False, data=None):
        self.code = code
        self.message = message
        self.status = status
        self.definitive = definitive
        self.data = data or {}
        super().__init__(message)

def soup(text):
    return BeautifulSoup(text, 'html.parser')

def clean(text):
    return re.sub(r'\s+', ' ', text or '').strip()

def browser_session():
    s = curl_requests.Session(impersonate='chrome')
    s.headers.update({
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    })
    return s

def browser_get(sess, url, *, params=None, referer=None, timeout=25, retry_403=True):
    headers = {}
    if referer:
        headers['Referer'] = referer
    r = sess.get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
    if r.status_code == 403 and retry_403:
        home = sess.get(BASE + '/', headers={'Referer': BASE + '/'}, timeout=timeout, allow_redirects=True)
        if home.status_code < 500:
            r = sess.get(url, params=params, headers={'Referer': BASE + '/'}, timeout=timeout, allow_redirects=True)
    return r

def form_data(form):
    out = []
    for el in form.find_all(['input', 'select', 'textarea']):
        name = el.get('name')
        typ = (el.get('type') or '').lower()
        if not name or el.has_attr('disabled') or typ in ('submit', 'button', 'image', 'reset', 'file'):
            continue
        if typ in ('checkbox', 'radio') and not el.has_attr('checked'):
            continue
        if el.name == 'select':
            selected = el.find_all('option', selected=True) or ([el.find('option')] if el.find('option') else [])
            out.extend((name, o.get('value', '')) for o in selected)
        else:
            out.append((name, el.get('value', '')))
    return out

def submit(sess, page, form, overrides=None):
    data = form_data(form)
    for k, v in (overrides or {}).items():
        data = [(a, b) for a, b in data if a != k] + [(k, str(v))]
    btn = form.find(['button', 'input'], attrs={'type': 'submit'})
    if btn and btn.get('name'):
        data.append((btn['name'], btn.get('value') or clean(btn.text)))
    method = (form.get('method') or 'post').lower()
    url = urljoin(page.url, form.get('action') or page.url)
    return sess.request(
        method,
        url,
        data=data if method != 'get' else None,
        params=data if method == 'get' else None,
        headers={'Referer': page.url},
        timeout=25,
        allow_redirects=True,
    )

def configured_server_accounts():
    out = {}
    for i in range(1, 4):
        username = os.environ.get(f'PLAYLOCAL_ACCOUNT_{i}_USERNAME', '').strip()
        password = os.environ.get(f'PLAYLOCAL_ACCOUNT_{i}_PASSWORD', '')
        if not username or not password:
            continue
        account_id = f'server-{i}'
        out[account_id] = {
            'id': account_id,
            'name': os.environ.get(f'PLAYLOCAL_ACCOUNT_{i}_NAME', f'Account {i}').strip() or f'Account {i}',
            'username': username,
            'password': password,
        }
    return out


def site_auth_required():
    return bool(os.environ.get('COURTFLOW_SITE_PASSWORD', ''))


def public_server_accounts():
    return [{'id': a['id'], 'name': a['name']} for a in configured_server_accounts().values()]


def issue_site_token(password):
    expected = os.environ.get('COURTFLOW_SITE_PASSWORD', '')
    if not expected:
        return {'siteToken': '', 'accounts': public_server_accounts(), 'expiresInSeconds': 0}
    supplied = str(password or '')
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise ApiError('SITE_AUTH_REJECTED', 'Incorrect site password.', 401, True)
    token = secrets.token_urlsafe(32)
    with LOCK:
        SITE_TOKENS[token] = time.time() + SITE_TOKEN_TTL
    return {'siteToken': token, 'accounts': public_server_accounts(), 'expiresInSeconds': SITE_TOKEN_TTL}


def require_site_token(req):
    if not site_auth_required():
        return
    token = str(req.get('siteToken') or '')
    now = time.time()
    with LOCK:
        expired = [k for k, exp in SITE_TOKENS.items() if exp <= now]
        for k in expired:
            SITE_TOKENS.pop(k, None)
        exp = SITE_TOKENS.get(token)
    if not exp or exp <= now:
        raise ApiError('SITE_AUTH_REQUIRED', 'Enter the CourtFlow site password to continue.', 401, True)


def login_server_account(account_id):
    account = configured_server_accounts().get(str(account_id or ''))
    if not account:
        raise ApiError('ACCOUNT_NOT_FOUND', 'That server account is not configured.', 404, True)
    return login(account['id'], account['username'], account['password'])


def login(account_id, username, password):
    s = browser_session()
    browser_get(s, BASE + '/', retry_403=False)
    p = browser_get(s, BASE + '/sign_in', referer=BASE + '/', retry_403=True)
    p.raise_for_status()
    d = soup(p.text)
    form = next((f for f in d.find_all('form') if f.find('input', {'type': 'password'})), None)
    if not form:
        raise ApiError('UPSTREAM_CHANGED', 'Could not find PlayLocal sign-in form.', 502)
    user = form.find('input', {'type': 'email'}) or form.find('input', attrs={'name': re.compile('email', re.I)})
    pw = form.find('input', {'type': 'password'})
    if not user or not pw:
        raise ApiError('UPSTREAM_CHANGED', 'Could not identify PlayLocal sign-in fields.', 502)
    r = submit(s, p, form, {user.get('name'): username, pw.get('name'): password})
    if urlparse(r.url).path == '/sign_in' and soup(r.text).find('input', {'type': 'password'}):
        raise ApiError('AUTH_REJECTED', 'PlayLocal rejected that email/password.', 401, True)
    token = secrets.token_urlsafe(32)
    identity = hashlib.sha256(username.strip().lower().encode()).hexdigest()[:32]
    with LOCK:
        SESSIONS[token] = {'accountId': account_id, 'identity': identity, 'session': s, 'created': time.time()}
    return {'sessionToken': token, 'identity': identity}

def get_session(token, account_id):
    with LOCK:
        item = SESSIONS.get(token)
    if not item or item['accountId'] != account_id:
        raise ApiError('AUTH_REJECTED', 'PlayLocal session expired. Sign in again.', 401, True)
    return item['session']

def search_parts(start, end):
    parts = []
    for name, a, b in [
        ('early_morning', 0, 480),
        ('morning', 480, 720),
        ('afternoon', 720, 960),
        ('evening', 960, 1200),
        ('night', 1200, 1440),
    ]:
        if start < b and end > a:
            parts.append(name)
    return parts or ['evening']

def search_pages(q, sess=None):
    start = int(q.get('start', 960))
    end = int(q.get('end', 1320))
    own_session = sess is None
    s = sess or browser_session()
    if own_session:
        browser_get(s, BASE + '/', retry_403=False)
    pages = []
    for part in search_parts(start, end):
        params = {
            'search[date]': q.get('date', ''),
            'search[location]': q.get('location', ''),
            'search[reservable_type]': 'TennisCourt',
            'search[sport]': q.get('sport', 'tennis'),
            'search[time]': part,
            'commit': 'Search Courts',
        }
        r = browser_get(s, BASE + '/facilities', params=params, referer=BASE + '/facilities', retry_403=True)
        if r.status_code == 403:
            raise ApiError('PLAYLOCAL_FORBIDDEN', 'PlayLocal refused the court-search request from the hosted connector (HTTP 403).', 502)
        r.raise_for_status()
        pages.append(r)
    return pages

def parse_facilities_page(page, q, wanted, start, end, facilities, slots):
    d = soup(page.text)
    for box in d.select('li[data-role="facility"]'):
        fid = str(box.get('data-id') or '')
        if not fid:
            link = box.find('a', href=re.compile(r'/facilities/[^/]+/reservations/new'))
            m = re.search(r'/facilities/([^/]+)/reservations/new', link.get('href', '') if link else '')
            fid = m.group(1) if m else ''
        if not fid or (wanted and fid != wanted):
            continue
        heading = box.find(['h4','h3','h2','h1'])
        name = clean(heading.get_text(' ', strip=True)) if heading else 'Facility ' + fid
        text = clean(box.get_text(' ', strip=True))
        price_node = box.select_one('[data-role="price"]')
        price_text = clean(price_node.get_text(' ', strip=True)) if price_node else text
        price_match = re.search(r'\$(\d+(?:\.\d{1,2})?)', price_text)
        price = int(round(float(price_match.group(1)) * 100)) if price_match else 0
        reservable = box.select_one('[data-role="reservable-number"]')
        reservable_count = int(clean(reservable.get_text(strip=True))) if reservable and clean(reservable.get_text(strip=True)).isdigit() else 1
        reserve_link = box.find('a', href=re.compile(r'/facilities/[^/]+/reservations/new'))
        reservation_href = reserve_link.get('href', '') if reserve_link else ''
        courts = [{'id': f'{fid}:any', 'name': 'Any available court'}]
        facilities[fid] = {
            'id': fid, 'name': name, 'courts': courts,
            'reservableCourtCount': reservable_count,
            'reservationHref': reservation_href,
            'reservationReferer': page.url,
        }
        selector = box.select_one('[data-role="reservation-selector"]')
        if not selector:
            continue
        for node in selector.find_all('li', recursive=False):
            txt = clean(node.get_text(' ', strip=True))
            mt = re.fullmatch(r'(\d{1,2})(?::00)?\s*(am|pm)', txt, re.I)
            if not mt:
                continue
            h = int(mt.group(1)) % 12 + (12 if mt.group(2).lower() == 'pm' else 0)
            st = h * 60
            if st < start or st >= end:
                continue
            classes = {str(x).lower() for x in node.get('class', [])}
            available = 'slot-available' in classes and 'slot-unavailable' not in classes
            c = courts[0]
            key = (fid, c['id'], st)
            slots[key] = {
                'slotId': f'{fid}:{c["id"]}:{q.get("date")}:{st}',
                'facilityId': fid, 'facilityName': name,
                'courtId': c['id'], 'courtName': c['name'],
                'date': q.get('date'), 'start': st, 'end': st + 60,
                'available': available, 'priceCents': price,
                'reservationHref': reservation_href,
                'reservationReferer': page.url,
                'searchLocation': q.get('location', ''),
            }

def availability(q, sess=None):
    wanted = str(q.get('facilityId') or '')
    start = int(q.get('start', 0))
    end = int(q.get('end', 1440))
    facilities = {}
    slots = {}
    for page in search_pages(q, sess=sess):
        parse_facilities_page(page, q, wanted, start, end, facilities, slots)
    return {
        'coverage': 'complete',
        'slotMinutes': 60,
        'asOf': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'facilities': list(facilities.values()),
        'slots': list(slots.values()),
    }

def parse_date(text):
    patterns = [
        (r'\b(\d{4}-\d{2}-\d{2})\b', None),
        (r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b', ('%m/%d/%Y', '%m/%d/%y')),
        (r'\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)\b', None),
    ]
    for pattern, fmts in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        raw = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', m.group(1), flags=re.I)
        if fmts:
            for fmt in fmts:
                try:
                    return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
                except ValueError:
                    pass
        elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
            return raw
        else:
            for fmt in ('%B %d, %Y', '%B %d %Y', '%b %d, %Y', '%b %d %Y'):
                try:
                    return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
                except ValueError:
                    pass
    return ''

def parse_times(text):
    times = re.findall(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', text, re.I)
    out = []
    for h, mm, ap in times[:2]:
        h = int(h) % 12 + (12 if ap.lower() == 'pm' else 0)
        out.append(f'{h % 12 or 12}:{int(mm or 0):02d} {"PM" if h >= 12 else "AM"}')
    return out

def reservation_id_from(node):
    for el in [node] + list(node.find_all(['a', 'form'])):
        target = (el.get('href') or '') + ' ' + (el.get('action') or '')
        m = re.search(r'/reservations/(\d+)', target)
        if m:
            return m.group(1)
    return ''

def parse_reservations(html):
    d = soup(html)
    candidates = []
    seen_nodes = set()
    for link in d.find_all('a', href=re.compile(r'/reservations/\d+')):
        box = link.find_parent(['li', 'article', 'section', 'tr']) or link.find_parent('div') or link.parent
        if box and id(box) not in seen_nodes:
            seen_nodes.add(id(box)); candidates.append(box)
    for form in d.find_all('form', action=re.compile(r'/reservations/\d+')):
        box = form.find_parent(['li', 'article', 'section', 'tr']) or form.find_parent('div') or form.parent
        if box and id(box) not in seen_nodes:
            seen_nodes.add(id(box)); candidates.append(box)
    for el in d.select('[class*=reservation], [id*=reservation]'):
        if el.name in ('html', 'body'):
            continue
        text = clean(el.get_text(' ', strip=True))
        if text and id(el) not in seen_nodes:
            seen_nodes.add(id(el)); candidates.append(el)

    rows = []
    seen = set()
    for i, box in enumerate(candidates):
        text = clean(box.get_text(' ', strip=True))
        if not text or len(text) < 6:
            continue
        rid = reservation_id_from(box) or f'activity-{i+1}'
        if rid in seen:
            continue
        seen.add(rid)
        heading = box.find(['h1', 'h2', 'h3', 'h4', 'h5', 'strong'])
        title = clean(heading.get_text(' ', strip=True)) if heading else ''
        if not title:
            link = box.find('a', href=re.compile(r'/reservations/\d+'))
            title = clean(link.get_text(' ', strip=True)) if link else ''
        if not title:
            title = 'PlayLocal reservation'
        date = parse_date(text)
        times = parse_times(text)
        status = 'current'
        if re.search(r'cancelled|canceled', text, re.I): status = 'cancelled'
        elif re.search(r'completed|past reservation|expired', text, re.I): status = 'past'
        elif re.search(r'upcoming|confirmed|reserved', text, re.I): status = 'confirmed'
        rows.append({'id': rid, 'title': title[:160], 'text': text[:500], 'date': date,
                     'start': times[0] if times else '', 'end': times[1] if len(times) > 1 else '', 'status': status})

    if not rows:
        for i, box in enumerate(d.find_all(['li', 'article', 'section'])):
            text = clean(box.get_text(' ', strip=True))
            if not text or not re.search(r'court|reservation|reserved|tennis|pickleball', text, re.I):
                continue
            date = parse_date(text); times = parse_times(text)
            if not (date or times):
                continue
            heading = box.find(['h1', 'h2', 'h3', 'h4', 'h5', 'strong'])
            title = clean(heading.get_text(' ', strip=True)) if heading else 'PlayLocal reservation'
            rows.append({'id': f'activity-{i+1}', 'title': title[:160], 'text': text[:500], 'date': date,
                         'start': times[0] if times else '', 'end': times[1] if len(times) > 1 else '',
                         'status': 'cancelled' if re.search(r'cancelled|canceled', text, re.I) else 'current'})
    return rows

def _history_for_session(s):
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

def _control_label(form, el):
    bits = [el.get('name'), el.get('id'), el.get('aria-label')]
    if el.get('id'):
        lab = form.find('label', attrs={'for': el.get('id')})
        if lab:
            bits.append(clean(lab.get_text(' ', strip=True)))
    parent = el.find_parent(['label', 'li', 'article', 'div', 'td'])
    if parent:
        bits.append(clean(parent.get_text(' ', strip=True))[:220])
    return clean(' '.join(x for x in bits if x))


def _court_name_from_text(text, value=''):
    text = clean(text)
    if not text:
        return ''

    # PlayLocal's current reservation cards can wrap a hidden reservable_id
    # inside the entire reservation summary. Prefer the explicit court-name
    # phrase and discard price/summary text around it.
    m = re.search(
        r'court\s*name\s*:\s*(?:\d+\s+)?(.+?)(?=\s+-\s*\$|\s+prefer\s+a\s+different\s+court|\s+total\b|$)',
        text,
        re.I,
    )
    if m:
        name = clean(m.group(1))
        if name:
            return name[:100]

    # Normal option labels are usually already short, e.g. "Court 2 - $0".
    if len(text) <= 100 and not re.search(
        r'your\s+reservation|total\s+price|terms\s+of\s+service|verification\s+to\s+complete',
        text,
        re.I,
    ):
        name = re.sub(r'\s+-\s*\$\s*\d+(?:\.\d{1,2})?.*$', '', text).strip()
        if name:
            return name[:100]

    # Defensive fallback for verbose reservation-card text.
    m = re.search(r'\bcourt\s*#?\s*\d+\b', text, re.I)
    if m:
        return clean(m.group(0)).replace('#', '').title()
    return ''


def _court_controls(form):
    controls = []
    seen = set()

    # PlayLocal's actual field is reservation[reservable_id]. Depending on
    # the page version it can be a select, radio, or hidden control inside a
    # court-selection card. Restrict discovery to those semantic controls so
    # unrelated reservation fields cannot become fake court choices.
    selectors = [
        'select#reservation_reservable_id',
        'select[name*="reservable_id"]',
        '[data-role="court-selection"] select',
        'input[type="radio"][name*="reservable_id"]',
        'input[type="hidden"][name*="reservable_id"]',
        '[data-role="court-selection"] input[type="radio"]',
        '[data-role="court-selection"] input[type="hidden"]',
    ]
    for selector in selectors:
        for el in form.select(selector):
            if el.has_attr('disabled') or id(el) in seen:
                continue
            seen.add(id(el))
            controls.append(el)

    if controls:
        return controls

    # Compatibility fallback for older forms that explicitly name court_id.
    for el in form.find_all(['select', 'input']):
        if el.has_attr('disabled'):
            continue
        typ = (el.get('type') or '').lower()
        if el.name == 'input' and typ not in ('radio', 'hidden'):
            continue
        field_name = clean((el.get('name') or '') + ' ' + (el.get('id') or ''))
        if re.search(r'court[_\- ]?id', field_name, re.I):
            controls.append(el)
    return controls


def _input_court_label(form, el):
    candidates = []
    if el.get('id'):
        lab = form.find('label', attrs={'for': el.get('id')})
        if lab:
            candidates.append(clean(lab.get_text(' ', strip=True)))
    parent_label = el.find_parent('label')
    if parent_label:
        candidates.append(clean(parent_label.get_text(' ', strip=True)))
    semantic = el.find_parent(attrs={'data-role': 'court-selection'})
    if semantic:
        candidates.append(clean(semantic.get_text(' ', strip=True)))
    parent = el.find_parent(['li', 'article', 'div', 'td'])
    if parent:
        candidates.append(clean(parent.get_text(' ', strip=True)))
    candidates.append(_control_label(form, el))

    for raw in candidates:
        name = _court_name_from_text(raw, el.get('value', ''))
        if name:
            return name
    return ''


def _extract_courts(form):
    courts = []
    seen_values = set()
    for el in _court_controls(form):
        if el.name == 'select':
            for opt in el.find_all('option'):
                val = str(opt.get('value') or '')
                if not val or opt.has_attr('disabled') or val in seen_values:
                    continue
                label = _court_name_from_text(opt.get_text(' ', strip=True), val)
                if not label:
                    continue
                if re.search(r'choose|select|please', label, re.I) and not re.search(r'court', label, re.I):
                    continue
                seen_values.add(val)
                courts.append({'id': val, 'name': label})
        else:
            val = str(el.get('value') or '')
            if not val or val in seen_values:
                continue
            label = _input_court_label(form, el)
            if not label:
                continue
            seen_values.add(val)
            courts.append({'id': val, 'name': label})
    return courts


def _find_reservation_form(d):
    forms = d.find_all('form')
    direct = next((f for f in forms if re.search(r'reservation|booking', (f.get('action') or '') + ' ' + clean(f.get_text(' ', strip=True)), re.I)), None)
    if direct:
        return direct
    for f in forms:
        action = (f.get('action') or '').lower()
        text = clean(f.get_text(' ', strip=True)).lower()
        controls = f.find_all(['select','input','textarea'])
        if not controls:
            continue
        if re.search(r'sign[_ -]?in|login|search', action + ' ' + text, re.I):
            continue
        if any(el.name == 'select' for el in controls) or any((el.get('type') or '').lower() == 'radio' for el in controls):
            return f
    return None


def _page_diagnostic(p, d):
    title = clean(d.title.get_text(' ', strip=True)) if d.title else ''
    forms = [clean((f.get('action') or '') + ' ' + f.get_text(' ', strip=True))[:180] for f in d.find_all('form')[:8]]
    links = []
    for a in d.find_all('a', href=True):
        href = a.get('href') or ''
        txt = clean(a.get_text(' ', strip=True))
        if re.search(r'reserv|court|facility|book|time', href + ' ' + txt, re.I):
            links.append((txt + ' -> ' + href)[:180])
        if len(links) >= 10:
            break
    body = clean(d.get_text(' ', strip=True))[:350]
    return f'url={p.url}; title={title}; forms={forms or ["none"]}; links={links or ["none"]}; text={body}'


def _slot_time_minutes(text):
    m = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', clean(text), re.I)
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'pm' else 0)
    return h * 60 + int(m.group(2) or 0)


def _reservation_click_url(href, selected_time, selected_date):
    """Mirror PlayLocal's facilities-page Reserve click handler exactly."""
    parsed = urlparse(urljoin(BASE, href))
    params = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
              if k not in ('time', 'date')]
    params.extend([('time', clean(selected_time)), ('date', str(selected_date or ''))])
    return parsed._replace(query=urlencode(params)).geturl()


def _reservation_page_for_query(s, q, facility_id):
    requested_start = int(q.get('start', 0) or 0)
    requested_end = int(q.get('end', requested_start + 60) or (requested_start + 60))
    found_href = ''
    found_referer = ''
    found_time = ''

    for sp in search_pages(q, sess=s):
        sd = soup(sp.text)
        for box in sd.select('li[data-role="facility"]'):
            if str(box.get('data-id') or '') != str(facility_id):
                continue
            link = box.find('a', href=re.compile(r'/facilities/[^/]+/reservations/new'))
            selector = box.select_one('[data-role="reservation-selector"]')
            if not link or not selector:
                continue

            choices = []
            for node in selector.find_all('li', recursive=False):
                classes = {str(x).lower() for x in node.get('class', [])}
                if 'reserve' in classes or 'disabled' in classes or 'slot-closed' in classes:
                    continue
                text = clean(node.get_text(' ', strip=True))
                minutes = _slot_time_minutes(text)
                if minutes is None or minutes < requested_start or minutes >= requested_end:
                    continue
                choices.append((0 if minutes == requested_start else 1, minutes, text))

            if not choices:
                continue
            choices.sort(key=lambda x: (x[0], x[1]))
            found_time = choices[0][2]
            found_href = link.get('href', '')
            found_referer = sp.url
            break
        if found_href:
            break

    if not found_href:
        return None, None, None, '', '', '', ''

    target = _reservation_click_url(found_href, found_time, q.get('date', ''))
    parsed = urlparse(target)
    if parsed.netloc not in ('www.playlocal.com', 'playlocal.com') or '/reservations/new' not in parsed.path:
        raise ApiError('COURT_OPTIONS', 'Invalid PlayLocal reservation link.', 400, True)

    p = browser_get(s, target, referer=found_referer, retry_403=True)
    if urlparse(p.url).path == '/sign_in':
        raise ApiError('AUTH_REJECTED', 'PlayLocal session expired.', 401, True)
    p.raise_for_status()
    d = soup(p.text)
    return p, d, _find_reservation_form(d), found_href, found_referer, found_time, target


def court_options(req):
    s = get_session(req['sessionToken'], req['accountId'])
    facility_id = str(req.get('facilityId') or '')
    if not facility_id:
        raise ApiError('COURT_OPTIONS', 'A facility is required.')

    requested_date = str(req.get('date') or '')
    requested_start = int(req.get('start', 0) or 0)
    requested_end = int(req.get('end', requested_start + 60) or (requested_start + 60))
    q = {
        'date': requested_date,
        'location': req.get('location', ''),
        'sport': 'tennis',
        'start': requested_start,
        'end': requested_end,
        'facilityId': facility_id,
    }

    p, d, form, href, referer, selected_time, target = _reservation_page_for_query(s, q, facility_id)
    if p is None:
        raise ApiError(
            'SLOT_UNAVAILABLE',
            'PlayLocal does not show the selected start time as available at this facility.',
            409,
            True,
        )
    if form is None:
        detail = _page_diagnostic(p, d)
        print(f'Court lookup page diagnostic: {detail}', flush=True)
        raise ApiError(
            'UPSTREAM_CHANGED',
            f'PlayLocal did not open its reservation form for {selected_time or "the selected time"}.',
            502,
        )

    courts = _extract_courts(form)
    print(f'Court options facility={facility_id} time={selected_time}: {courts}', flush=True)
    if not courts:
        controls = []
        for el in form.find_all(['select', 'input'])[:40]:
            controls.append(f"{el.name}:{el.get('type','')}:{el.get('name','')}:{el.get('id','')}")
        print('Court control diagnostic: ' + (', '.join(controls[:20]) or 'no form controls'), flush=True)
        raise ApiError('UPSTREAM_CHANGED', 'PlayLocal opened the reservation form, but its court selector was not recognized.', 502)

    return {
        'facilityId': facility_id,
        'courts': courts,
        'requestedDate': requested_date,
        'courtSourceDate': requested_date,
        'selectedDateAccessible': True,
        'selectedTime': selected_time,
        'reservationHref': href,
        'reservationReferer': referer,
        'reservationUrl': target,
    }


def set_fields(form, slot):
    out = {}
    hour = slot['start'] // 60
    wanted_id = str(slot.get('courtId') or '')
    wanted_name = clean(slot.get('courtName') or '')
    court_controls = _court_controls(form)
    court_names = {el.get('name') for el in court_controls if el.get('name')}
    matched_court = False

    for el in court_controls:
        name = el.get('name')
        if not name:
            continue
        if el.name == 'select':
            opts = [x for x in el.find_all('option') if x.get('value') and not x.has_attr('disabled')]
            option = next((x for x in opts if str(x.get('value')) == wanted_id), None)
            if option is None and wanted_name:
                option = next((x for x in opts if clean(x.get_text(' ', strip=True)).lower() == wanted_name.lower()), None)
            if option is not None:
                out[name] = option.get('value', '')
                matched_court = True
                break
        else:
            val = str(el.get('value') or '')
            label = _input_court_label(form, el)
            if val == wanted_id or (wanted_name and label and label.lower() == wanted_name.lower()):
                out[name] = val
                matched_court = True
                break

    if court_controls and not matched_court:
        raise ApiError('COURT_UNAVAILABLE', f'PlayLocal does not offer the selected court ({wanted_name or wanted_id}) on the reservation form.', 409, True)

    for el in form.find_all(['input', 'select', 'textarea']):
        name = el.get('name')
        typ = (el.get('type') or '').lower()
        if not name or el.has_attr('disabled') or name in court_names:
            continue
        desc = ' '.join(filter(None, [name, el.get('id'), el.get('aria-label')])).lower()
        if re.search(r'date|day', desc) and typ not in ('checkbox', 'radio'):
            out[name] = slot['date']
        elif re.search(r'time|hour|start|slot', desc):
            if el.name == 'select':
                pattern = rf'\b{hour % 12 or 12}(?::00)?\s*{"pm" if hour >= 12 else "am"}\b'
                option = next((x for x in el.find_all('option') if re.search(pattern, clean(x.text) + ' ' + x.get('value', ''), re.I)), None)
                if option:
                    out[name] = option.get('value', '')
            elif typ not in ('checkbox', 'radio'):
                out[name] = f'{hour % 12 or 12}:00 {"PM" if hour >= 12 else "AM"}'
        elif typ == 'checkbox' and (el.has_attr('required') or re.search(r'term|policy|agree|accept', desc)):
            out[name] = el.get('value') or '1'
    return out

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


def book(req):
    key = req['idempotencyKey']
    with LOCK:
        if key in IDEM:
            return IDEM[key]
    slot = req['slot']
    s = get_session(req['sessionToken'], req['accountId'])
    snap = availability({
        'date': slot['date'], 'sport': 'tennis', 'start': slot['start'], 'end': slot['end'],
        'facilityId': slot['facilityId'], 'location': slot.get('searchLocation', ''),
    }, sess=s)
    if not any(x['available'] and x['start'] == slot['start'] for x in snap['slots']):
        raise ApiError('SLOT_UNAVAILABLE', 'PlayLocal no longer shows that slot as available.', 409, True)
    booking_q = {
        'date': slot['date'],
        'location': slot.get('searchLocation', ''),
        'sport': 'tennis',
        'start': slot['start'],
        'end': slot['end'],
        'facilityId': slot['facilityId'],
    }
    p, d, form, _, _, selected_time, booking_url = _reservation_page_for_query(
        s, booking_q, slot['facilityId']
    )
    if p is None:
        raise ApiError('SLOT_UNAVAILABLE', 'PlayLocal no longer shows that exact time as available.', 409, True)
    if not form:
        detail = _page_diagnostic(p, d)
        raise ApiError('UPSTREAM_CHANGED', 'PlayLocal reservation form was not found. ' + detail, 502)
    prices = [int(round(float(x) * 100)) for x in re.findall(r'\$(\d+(?:\.\d{1,2})?)', clean(d.get_text(' ', strip=True)))]
    detected = max(prices) if prices else 0
    if detected > 0:
        raise ApiError('INTERACTIVE_REQUIRED', 'This reservation has a charge; automatic paid booking is not enabled.', 409, True)
    # PlayLocal currently gates the final reservation submission with browser-side
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
    m = re.search(r'/reservations/(\d+)', urlparse(r.url).path)
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
    with LOCK:
        IDEM[key] = result
    return result

def verify_booking(req):
    s = get_session(req['sessionToken'], req['accountId'])
    slot = req.get('slot') or {}
    if not slot.get('date') or slot.get('start') is None:
        raise ApiError('VERIFY_BOOKING', 'A reservation date and start time are required.')
    row = _reconcile_created_reservation(s, slot)
    return {
        'confirmed': row is not None,
        'reservation': row,
        'checkedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }


def dispatch(req):
    if req.get('version') != 1:
        raise ApiError('VERSION', 'CourtFlow protocol version 1 is required.')
    action = req.get('action')
    if action == 'capabilities':
        return {
            'vendor': 'playlocal', 'idempotency': True, 'reservationHistory': True,
            'completeDailyHistory': False, 'slotMinutes': 60,
            'siteAuthRequired': site_auth_required(),
            'serverAccountCount': len(configured_server_accounts()),
        }
    if action == 'site_login':
        return issue_site_token(req.get('sitePassword'))

    require_site_token(req)

    if action == 'accounts':
        return {'accounts': public_server_accounts()}
    if action == 'authenticate':
        if configured_server_accounts():
            return login_server_account(req.get('accountId'))
        return login(req['accountId'], req['username'], req['password'])
    if action == 'availability':
        sess = None
        if req.get('sessionToken') and req.get('accountId'):
            sess = get_session(req['sessionToken'], req['accountId'])
        return availability(req.get('query') or {}, sess=sess)
    if action == 'history':
        return history(req)
    if action == 'court_options':
        return court_options(req)
    if action == 'verify_booking':
        return verify_booking(req)
    if action == 'book':
        return book(req)
    raise ApiError('ACTION', 'Unknown adapter action.')

def upstream_probe():
    try:
        q = {'date': time.strftime('%Y-%m-%d'), 'location': 'Boston', 'sport': 'tennis', 'start': 960, 'end': 1200}
        pages = search_pages(q)
        status = pages[0].status_code if pages else 'none'
        print(f'PlayLocal upstream search probe: status={status} pages={len(pages)}', flush=True)
    except Exception as e:
        print(f'PlayLocal upstream search probe failed: {type(e).__name__}: {e}', flush=True)

class Handler(SimpleHTTPRequestHandler):
    def cors(self):
        origin = self.headers.get('Origin', '')
        allowed = os.environ.get('COURTFLOW_ALLOWED_ORIGIN', '*')
        if allowed == '*' or origin == allowed:
            self.send_header('Access-Control-Allow-Origin', '*' if allowed == '*' else origin)
        self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if self.path == '/' or self.path == '/health':
            raw = b'CourtFlow PlayLocal adapter'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.cors()
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == '/upstream':
            try:
                q = {'date': time.strftime('%Y-%m-%d'), 'location': 'Boston', 'sport': 'tennis', 'start': 960, 'end': 1200}
                pages = search_pages(q)
                payload = {'ok': True, 'status': pages[0].status_code if pages else None, 'pages': len(pages)}
                status = 200
            except ApiError as e:
                payload = {'ok': False, 'code': e.code, 'message': e.message}
                status = e.status
            except Exception as e:
                payload = {'ok': False, 'code': 'UPSTREAM_ERROR', 'message': str(e)}
                status = 502
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.cors()
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != '/adapter':
            return self.send_error(404)
        try:
            n = int(self.headers.get('Content-Length', '0'))
            req = json.loads(self.rfile.read(n) or b'{}')
            payload = {'version': 1, 'ok': True, 'data': dispatch(req)}
            status = 200
        except ApiError as e:
            print(f'API error {e.code}: {e.message}', flush=True)
            err = {'code': e.code, 'message': e.message, 'definitive': e.definitive}
            if e.data:
                err['data'] = e.data
            payload = {'version': 1, 'ok': False, 'error': err}
            status = e.status
        except requests.RequestException as e:
            payload = {'version': 1, 'ok': False, 'error': {'code': 'PLAYLOCAL_CONNECTION', 'message': 'Could not reach PlayLocal: ' + str(e), 'definitive': False}}
            status = 502
        except Exception as e:
            payload = {'version': 1, 'ok': False, 'error': {'code': 'CONNECTOR_ERROR', 'message': str(e), 'definitive': False}}
            status = 500
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.cors()
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8765'))
    host = os.environ.get('HOST', '0.0.0.0')
    print(f'CourtFlow adapter listening on {host}:{port}', flush=True)
    upstream_probe()
    ThreadingHTTPServer((host, port), Handler).serve_forever()
