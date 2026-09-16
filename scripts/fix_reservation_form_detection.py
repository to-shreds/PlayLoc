from pathlib import Path

p=Path('playlocal_server.py')
s=p.read_text()

marker='def court_options(req):\n'
helper='''def _find_reservation_form(d):
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
    return forms[0] if len(forms) == 1 else None


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


'''
if 'def _find_reservation_form(d):' not in s:
    if marker not in s:
        raise SystemExit('court_options marker not found')
    s=s.replace(marker,helper+marker,1)

old="""    forms = d.find_all('form')
    form = next((f for f in forms if re.search(r'reservation|booking', (f.get('action') or '') + ' ' + clean(f.get_text(' ', strip=True)), re.I)), None)
    if not form:
        raise ApiError('UPSTREAM_CHANGED', 'PlayLocal reservation form was not found.', 502)
"""
new="""    form = _find_reservation_form(d)
    if not form:
        detail = _page_diagnostic(p, d)
        raise ApiError('UPSTREAM_CHANGED', 'PlayLocal reservation form was not found. ' + detail, 502)
"""
if old not in s:
    raise SystemExit('court_options form block not found')
s=s.replace(old,new,1)

old2="""    d = soup(p.text)
    form = next((f for f in d.find_all('form') if re.search(r'reservation|booking', (f.get('action') or '') + ' ' + clean(f.get_text(' ', strip=True)), re.I)), None)
    if not form:
        raise ApiError('UPSTREAM_CHANGED', 'PlayLocal reservation form was not found.', 502)
"""
new2="""    d = soup(p.text)
    form = _find_reservation_form(d)
    if not form:
        detail = _page_diagnostic(p, d)
        raise ApiError('UPSTREAM_CHANGED', 'PlayLocal reservation form was not found. ' + detail, 502)
"""
if old2 not in s:
    raise SystemExit('book form block not found')
s=s.replace(old2,new2,1)

p.write_text(s)
