from pathlib import Path

p = Path('playlocal_server.py')
s = p.read_text()
start = s.index('def _control_label(form, el):\n')
end = s.index('\ndef _find_reservation_form(d):\n', start)
replacement = r'''def _control_label(form, el):
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

'''
s = s[:start] + replacement + s[end:]

# Tighten input/radio matching in set_fields so the selected real PlayLocal
# reservable_id wins by ID even if display labels vary.
old = """            label = ''\n            if el.get('id'):\n                lab = form.find('label', attrs={'for': el.get('id')})\n                if lab:\n                    label = clean(lab.get_text(' ', strip=True))\n            if not label:\n                parent = el.find_parent('label') or el.parent\n                label = clean(parent.get_text(' ', strip=True)) if parent else ''\n            if val == wanted_id or (wanted_name and label.lower() == wanted_name.lower()):\n                out[name] = val\n                matched_court = True\n                break\n"""
new = """            label = _input_court_label(form, el)\n            if val == wanted_id or (wanted_name and label and label.lower() == wanted_name.lower()):\n                out[name] = val\n                matched_court = True\n                break\n"""
if old not in s:
    raise SystemExit('set_fields court input block not found')
s = s.replace(old, new, 1)

# Log only non-sensitive court IDs/names to make future markup changes easy to
# diagnose without exposing credentials or session tokens.
old = """    courts = _extract_courts(form)\n    if not courts:\n"""
new = """    courts = _extract_courts(form)\n    print(f'Court options facility={facility_id} time={selected_time}: {courts}', flush=True)\n    if not courts:\n"""
if old not in s:
    raise SystemExit('court_options extraction block not found')
s = s.replace(old, new, 1)
p.write_text(s)

# Frontend defense in depth: never display an accidental full reservation
# summary as a court label even if upstream markup changes again.
p = Path('index.html')
h = p.read_text()
needle = "function esc(s){return String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]))}"
if needle not in h:
    raise SystemExit('frontend esc function not found')
helper = needle + "\nfunction courtDisplayName(name){let s=String(name||'').replace(/\\s+/g,' ').trim(),m=s.match(/court\\s*name\\s*:\\s*(?:\\d+\\s+)?(.+?)(?=\\s+-\\s*\\$|\\s+prefer\\s+a\\s+different\\s+court|\\s+total\\b|$)/i);if(m&&m[1])return m[1].trim().slice(0,100);m=s.match(/\\bcourt\\s*#?\\s*\\d+\\b/i);if(s.length>100&&m)return m[0].replace('#','');return s.length>100?s.slice(0,97)+'...':s}"
h = h.replace(needle, helper, 1)
h = h.replace("(d.courts||[]).map(c=>`<option value=\"${esc(c.id)}\">${esc(c.name)}</option>`).join('')", "(d.courts||[]).map(c=>`<option value=\"${esc(c.id)}\">${esc(courtDisplayName(c.name))}</option>`).join('')")
p.write_text(h)
