from pathlib import Path

p=Path('playlocal_server.py')
s=p.read_text()

# Attach the exact dated search URL to every facility result so the frontend can
# preserve the browser context that PlayLocal uses when Reserve is clicked.
old="""            'reservationHref': reservation_href,
        }
"""
new="""            'reservationHref': reservation_href,
            'reservationReferer': page.url,
        }
"""
if old not in s:
    raise SystemExit('facility reservation metadata block not found')
s=s.replace(old,new,1)

# Replace court_options reservation navigation with an immediate same-session
# search + Reserve click, matching the site's normal browser flow.
start=s.index("def court_options(req):")
needle="    if urlparse(p.url).path == '/sign_in':\n"
pos=s.index(needle,start)
prefix=s[start:pos]
nav_start=prefix.index("    href = str(req.get('reservationHref') or '')\n")
old_nav=prefix[nav_start:]
new_nav="""    q = {
        'date': req.get('date', ''),
        'location': req.get('location', ''),
        'sport': 'tennis',
        'start': int(req.get('start', 0) or 0),
        'end': int(req.get('end', 1440) or 1440),
        'facilityId': facility_id,
    }
    found_href = ''
    found_referer = ''
    for sp in search_pages(q, sess=s):
        sd = soup(sp.text)
        for box in sd.select('li[data-role="facility"]'):
            bid = str(box.get('data-id') or '')
            if bid != facility_id:
                continue
            link = box.find('a', href=re.compile(r'/facilities/[^/]+/reservations/new'))
            if link:
                found_href = link.get('href', '')
                found_referer = sp.url
                break
        if found_href:
            break
    if not found_href:
        # Use the exact href returned to the frontend only as a fallback.
        found_href = str(req.get('reservationHref') or '')
        found_referer = str(req.get('reservationReferer') or BASE + '/facilities')
    if not found_href:
        raise ApiError('RESERVATION_LINK_NOT_FOUND', 'PlayLocal did not expose a Reserve link for the selected facility/date/time.', 409, True)
    parsed = urlparse(urljoin(BASE, found_href))
    if parsed.netloc not in ('www.playlocal.com', 'playlocal.com') or '/reservations/new' not in parsed.path:
        raise ApiError('COURT_OPTIONS', 'Invalid PlayLocal reservation link.', 400, True)
    url = urljoin(BASE, found_href)
    p = browser_get(s, url, referer=found_referer, retry_403=True)
"""
new_prefix=prefix[:nav_start]+new_nav
s=s[:start]+new_prefix+s[pos:]

# Booking should warm the exact search page context (if present) and use it as Referer.
old="""    p = browser_get(s, booking_url, referer=BASE + '/facilities', retry_403=True)
"""
new="""    booking_referer = str(slot.get('reservationReferer') or BASE + '/facilities')
    if booking_referer.startswith(BASE + '/facilities'):
        browser_get(s, booking_referer, referer=BASE + '/facilities', retry_403=True)
    p = browser_get(s, booking_url, referer=booking_referer, retry_403=True)
"""
if old not in s:
    raise SystemExit('booking referer block not found')
s=s.replace(old,new,1)
p.write_text(s)

p=Path('index.html')
h=p.read_text()
old="""reservationHref:f?.reservationHref||'',date:$('pdate').value,location:$('loc').value.trim(),start:+$('pstart').value,end:+$('pend').value"""
new="""reservationHref:f?.reservationHref||'',reservationReferer:f?.reservationReferer||'',date:$('pdate').value,location:$('loc').value.trim(),start:+$('pstart').value,end:+$('pend').value"""
if old not in h:
    raise SystemExit('frontend court metadata call not found')
h=h.replace(old,new,1)
old="""reservationHref:f?.reservationHref||base.reservationHref||''};rows.push"""
new="""reservationHref:f?.reservationHref||base.reservationHref||'',reservationReferer:f?.reservationReferer||base.reservationReferer||''};rows.push"""
if old not in h:
    raise SystemExit('planned slot reservation metadata not found')
h=h.replace(old,new,1)
p.write_text(h)
