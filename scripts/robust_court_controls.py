from pathlib import Path

p = Path('playlocal_server.py')
s = p.read_text()

start = s.index('def court_options(req):')
end = s.index('\ndef book(req):', start)
new = r'''def _control_label(form, el):
    bits = [el.get('name'), el.get('id'), el.get('aria-label')]
    if el.get('id'):
        lab = form.find('label', attrs={'for': el.get('id')})
        if lab:
            bits.append(clean(lab.get_text(' ', strip=True)))
    parent = el.find_parent(['label', 'div', 'li', 'td'])
    if parent:
        bits.append(clean(parent.get_text(' ', strip=True))[:160])
    return clean(' '.join(x for x in bits if x))


def _court_controls(form):
    controls = []
    for el in form.find_all(['select', 'input']):
        if el.has_attr('disabled'):
            continue
        typ = (el.get('type') or '').lower()
        if el.name == 'input' and typ not in ('radio', 'hidden'):
            continue
        desc = _control_label(form, el)
        option_text = ''
        if el.name == 'select':
            option_text = ' '.join(clean(o.get_text(' ', strip=True)) for o in el.find_all('option'))
        hay = clean(desc + ' ' + option_text)
        if re.search(r'court', hay, re.I) or re.search(r'court[_\- ]?id', el.get('name') or '', re.I):
            controls.append(el)
    return controls


def _extract_courts(form):
    courts = []
    seen = set()
    for el in _court_controls(form):
        if el.name == 'select':
            for opt in el.find_all('option'):
                val = opt.get('value')
                label = clean(opt.get_text(' ', strip=True))
                if not val or opt.has_attr('disabled') or not label:
                    continue
                if re.search(r'choose|select|please', label, re.I) and not re.search(r'court\s*\d', label, re.I):
                    continue
                key = (str(val), label.lower())
                if key not in seen:
                    seen.add(key)
                    courts.append({'id': str(val), 'name': label})
        else:
            val = el.get('value')
            if not val:
                continue
            label = ''
            if el.get('id'):
                lab = form.find('label', attrs={'for': el.get('id')})
                if lab:
                    label = clean(lab.get_text(' ', strip=True))
            if not label:
                parent = el.find_parent('label') or el.parent
                label = clean(parent.get_text(' ', strip=True)) if parent else ''
            if not label:
                label = _control_label(form, el)
            if not label:
                continue
            key = (str(val), label.lower())
            if key not in seen:
                seen.add(key)
                courts.append({'id': str(val), 'name': label})
    return courts


def court_options(req):
    s = get_session(req['sessionToken'], req['accountId'])
    facility_id = str(req.get('facilityId') or '')
    if not facility_id:
        raise ApiError('COURT_OPTIONS', 'A facility is required.')
    params = {'sport': 'tennis'}
    if req.get('date'):
        params['date'] = req.get('date')
    url = f"{BASE}/facilities/{facility_id}/reservations/new"
    p = browser_get(s, url, params=params, referer=BASE + '/facilities', retry_403=True)
    if urlparse(p.url).path == '/sign_in':
        raise ApiError('AUTH_REJECTED', 'PlayLocal session expired.', 401, True)
    p.raise_for_status()
    d = soup(p.text)
    forms = d.find_all('form')
    form = next((f for f in forms if re.search(r'reservation|booking', (f.get('action') or '') + ' ' + clean(f.get_text(' ', strip=True)), re.I)), None)
    if not form:
        raise ApiError('UPSTREAM_CHANGED', 'PlayLocal reservation form was not found.', 502)
    courts = _extract_courts(form)
    if not courts:
        controls = []
        for el in form.find_all(['select', 'input'])[:40]:
            controls.append(f"{el.name}:{el.get('type','')}:{el.get('name','')}:{el.get('id','')}")
        detail = ', '.join(controls[:20]) or 'no form controls'
        raise ApiError('UPSTREAM_CHANGED', 'PlayLocal court control was not recognized. Form controls: ' + detail, 502)
    return {'facilityId': facility_id, 'courts': courts}


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
            label = ''
            if el.get('id'):
                lab = form.find('label', attrs={'for': el.get('id')})
                if lab:
                    label = clean(lab.get_text(' ', strip=True))
            if not label:
                parent = el.find_parent('label') or el.parent
                label = clean(parent.get_text(' ', strip=True)) if parent else ''
            if val == wanted_id or (wanted_name and label.lower() == wanted_name.lower()):
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
'''
p.write_text(s[:start] + new + s[end:])
