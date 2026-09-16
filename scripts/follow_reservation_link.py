from pathlib import Path

# Backend: preserve exact PlayLocal reservation href from each facility card,
# and use it for court lookup / booking instead of reconstructing the URL.
p = Path('playlocal_server.py')
s = p.read_text()

old = """        courts = [{'id': f'{fid}:any', 'name': 'Any available court'}]
        facilities[fid] = {'id': fid, 'name': name, 'courts': courts, 'reservableCourtCount': reservable_count}
        selector = box.select_one('[data-role=\"reservation-selector\"]')
"""
new = """        reserve_link = box.find('a', href=re.compile(r'/facilities/[^/]+/reservations/new'))
        reservation_href = reserve_link.get('href', '') if reserve_link else ''
        courts = [{'id': f'{fid}:any', 'name': 'Any available court'}]
        facilities[fid] = {
            'id': fid, 'name': name, 'courts': courts,
            'reservableCourtCount': reservable_count,
            'reservationHref': reservation_href,
        }
        selector = box.select_one('[data-role=\"reservation-selector\"]')
"""
if old not in s:
    raise SystemExit('facility block not found')
s = s.replace(old, new, 1)

old = """    params = {'sport': 'tennis'}
    if req.get('date'):
        params['date'] = req.get('date')
    url = f\"{BASE}/facilities/{facility_id}/reservations/new\"
    p = browser_get(s, url, params=params, referer=BASE + '/facilities', retry_403=True)
"""
new = """    href = str(req.get('reservationHref') or '')
    if href:
        parsed = urlparse(urljoin(BASE, href))
        if parsed.netloc not in ('www.playlocal.com', 'playlocal.com') or '/reservations/new' not in parsed.path:
            raise ApiError('COURT_OPTIONS', 'Invalid PlayLocal reservation link.', 400, True)
        url = urljoin(BASE, href)
        p = browser_get(s, url, referer=BASE + '/facilities', retry_403=True)
    else:
        # Fallback: re-run the same live search and recover PlayLocal's exact Reserve href.
        q = {
            'date': req.get('date', ''),
            'location': req.get('location', ''),
            'sport': 'tennis',
            'start': int(req.get('start', 0) or 0),
            'end': int(req.get('end', 1440) or 1440),
            'facilityId': facility_id,
        }
        found_href = ''
        for sp in search_pages(q, sess=s):
            sd = soup(sp.text)
            for box in sd.select('li[data-role=\"facility\"]'):
                bid = str(box.get('data-id') or '')
                link = box.find('a', href=re.compile(r'/facilities/[^/]+/reservations/new'))
                if bid == facility_id and link:
                    found_href = link.get('href', '')
                    break
            if found_href:
                break
        if not found_href:
            raise ApiError('RESERVATION_LINK_NOT_FOUND', 'PlayLocal did not expose a Reserve link for the selected facility/date/time.', 409, True)
        url = urljoin(BASE, found_href)
        p = browser_get(s, url, referer=BASE + '/facilities', retry_403=True)
"""
if old not in s:
    raise SystemExit('court_options URL block not found')
s = s.replace(old, new, 1)

# Booking path must also use the exact href carried on the slot.
old = """    p = browser_get(s, f\"{BASE}/facilities/{slot['facilityId']}/reservations/new?sport=tennis\", referer=BASE + '/facilities', retry_403=True)
"""
new = """    href = str(slot.get('reservationHref') or '')
    if href:
        parsed = urlparse(urljoin(BASE, href))
        if parsed.netloc not in ('www.playlocal.com', 'playlocal.com') or '/reservations/new' not in parsed.path:
            raise ApiError('BOOKING_LINK', 'Invalid PlayLocal reservation link.', 400, True)
        booking_url = urljoin(BASE, href)
    else:
        booking_url = f\"{BASE}/facilities/{slot['facilityId']}/reservations/new?sport=tennis\"
    p = browser_get(s, booking_url, referer=BASE + '/facilities', retry_403=True)
"""
if old not in s:
    raise SystemExit('book URL block not found')
s = s.replace(old, new, 1)
p.write_text(s)

# Frontend: pass the exact href plus the user's search/date/time context.
p = Path('index.html')
h = p.read_text()
old = """let d=await rpc('court_options',{accountId:a.id,sessionToken:ss.sessionToken,facilityId:fid,date:$('pdate').value});"""
new = """let f=state.facilities.find(x=>String(x.id)===String(fid));let d=await rpc('court_options',{accountId:a.id,sessionToken:ss.sessionToken,facilityId:fid,reservationHref:f?.reservationHref||'',date:$('pdate').value,location:$('loc').value.trim(),start:+$('pstart').value,end:+$('pend').value});"""
if old not in h:
    raise SystemExit('frontend court_options call not found')
h = h.replace(old, new, 1)

# When planner creates an exact-court slot, retain the exact reservation href.
old = """let s={...base,courtId:court,courtName};rows.push({status:'planned',start:tt,slot:s,account:a,label:a.name})"""
new = """let f=state.facilities.find(x=>String(x.id)===String(facilityId));let s={...base,courtId:court,courtName,reservationHref:f?.reservationHref||base.reservationHref||''};rows.push({status:'planned',start:tt,slot:s,account:a,label:a.name})"""
if old not in h:
    raise SystemExit('planner exact-court slot block not found')
h = h.replace(old, new, 1)
p.write_text(h)
