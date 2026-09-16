from pathlib import Path
import re

p = Path('playlocal_server.py')
s = p.read_text()

s = s.replace(
    'from urllib.parse import urljoin, urlparse\n',
    'from urllib.parse import urljoin, urlparse, urlencode, parse_qsl\n',
    1,
)

old_params = """            'search[date]': q.get('date', ''),
            'search[location]': q.get('location', ''),
            'search[sport]': q.get('sport', 'tennis'),
            'search[time]': part,
            'commit': 'Find Courts',
"""
new_params = """            'search[date]': q.get('date', ''),
            'search[location]': q.get('location', ''),
            'search[reservable_type]': 'TennisCourt',
            'search[sport]': q.get('sport', 'tennis'),
            'search[time]': part,
            'commit': 'Search Courts',
"""
if old_params not in s:
    raise SystemExit('search params block not found')
s = s.replace(old_params, new_params, 1)

old_court = """        if re.search(r'court', hay, re.I) or re.search(r'court[_\\- ]?id', el.get('name') or '', re.I):
            controls.append(el)
"""
new_court = """        field_name = (el.get('name') or '') + ' ' + (el.get('id') or '')
        if (re.search(r'court', hay, re.I)
                or re.search(r'court[_\\- ]?id', field_name, re.I)
                or re.search(r'reservable[_\\- ]?id', field_name, re.I)):
            controls.append(el)
"""
if old_court not in s:
    raise SystemExit('court control block not found')
s = s.replace(old_court, new_court, 1)

start = s.index('def _reservation_page_for_query(s, q, facility_id):\n')
end = s.index('\ndef set_fields(form, slot):\n', start)
replacement = r'''def _slot_time_minutes(text):
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

'''
s = s[:start] + replacement + s[end:]

old_book = r'''    href = str(slot.get('reservationHref') or '')
    if href:
        parsed = urlparse(urljoin(BASE, href))
        if parsed.netloc not in ('www.playlocal.com', 'playlocal.com') or '/reservations/new' not in parsed.path:
            raise ApiError('BOOKING_LINK', 'Invalid PlayLocal reservation link.', 400, True)
        booking_url = urljoin(BASE, href)
    else:
        booking_url = f"{BASE}/facilities/{slot['facilityId']}/reservations/new?sport=tennis"
    booking_referer = str(slot.get('reservationReferer') or BASE + '/facilities')
    if booking_referer.startswith(BASE + '/facilities'):
        browser_get(s, booking_referer, referer=BASE + '/facilities', retry_403=True)
    p = browser_get(s, booking_url, referer=booking_referer, retry_403=True)
    if urlparse(p.url).path == '/sign_in':
        raise ApiError('AUTH_REJECTED', 'PlayLocal session expired.', 401, True)
    p.raise_for_status()
    d = soup(p.text)
    form = _find_reservation_form(d)
'''
new_book = r'''    booking_q = {
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
'''
if old_book not in s:
    raise SystemExit('booking page block not found')
s = s.replace(old_book, new_book, 1)
p.write_text(s)

p = Path('index.html')
h = p.read_text()
h = h.replace(
    "$('facility').onchange=loadCourts;$('pdate').onchange=loadCourts;",
    "$('facility').onchange=loadCourts;$('pdate').onchange=loadCourts;$('pstart').onchange=loadCourts;",
    1,
)

ps = h.index("$('planBtn').onclick=async()=>{")
pe = h.index("\n$('bookPlan').onclick", ps)
new_plan = r'''$('planBtn').onclick=async()=>{
  try{
    if(!state.accounts.length)throw Error('Add at least one account.');
    let facilityId=$('facility').value,court=$('court').value,location=$('loc').value.trim();
    if(!facilityId)throw Error('Search first, then choose a facility.');
    if(!court)throw Error('Choose a specific court.');
    let q={location,sport:'tennis',date:$('pdate').value,start:+$('pstart').value,end:+$('pend').value,facilityId};
    let courtName=$('court').selectedOptions[0]?.textContent||court;
    let d=await availability(q);
    state.facilities=d.facilities;state.slots=d.slots;
    let limit=+$('limit').value,usage=Object.fromEntries(state.accounts.map(a=>[a.id,0])),rows=[];
    let lookupAccount=state.accounts[0],lookupSession=state.mode==='live'?await auth(lookupAccount):null;

    for(let tt=q.start;tt<q.end;tt+=60){
      let base=d.slots.find(x=>x.start===tt);
      if(!base||!base.available){rows.push({status:'unavailable',start:tt,label:'Unavailable'});continue}

      let exact=null;
      if(state.mode==='live'){
        try{
          exact=await rpc('court_options',{
            accountId:lookupAccount.id,sessionToken:lookupSession.sessionToken,
            facilityId,date:q.date,location,start:tt,end:tt+60
          });
        }catch(e){
          rows.push({status:'unavailable',start:tt,label:'Court unavailable'});
          log(`Court check ${t(tt)}: ${e.message}`);
          continue;
        }
        if(!(exact.courts||[]).some(c=>String(c.id)===String(court))){
          rows.push({status:'unavailable',start:tt,label:'Court unavailable'});
          continue;
        }
      }

      let a=state.accounts.find(a=>usage[a.id]+60<=limit);
      if(!a){rows.push({status:'limit',start:tt,label:'Account limit reached'});continue}
      usage[a.id]+=60;
      let f=state.facilities.find(x=>String(x.id)===String(facilityId));
      let s={
        ...base,courtId:court,courtName,searchLocation:location,
        reservationHref:exact?.reservationHref||f?.reservationHref||base.reservationHref||'',
        reservationReferer:exact?.reservationReferer||f?.reservationReferer||base.reservationReferer||''
      };
      rows.push({status:'planned',start:tt,slot:s,account:a,label:a.name});
    }
    state.plan=rows;
    $('plan').innerHTML=rows.map(r=>`<div class="planrow"><span>${t(r.start)}</span><span class="${r.status==='planned'?'ok':'bad'}">${r.status==='planned'?esc(r.account.name):esc(r.label)}</span></div>`).join('');
    $('bookPlan').classList.toggle('hidden',!rows.some(r=>r.status==='planned'));
    let filled=rows.filter(r=>r.status==='planned').length;
    log(`Plan built: ${filled} of ${rows.length} hour${rows.length===1?'':'s'} assigned for ${courtName}.`)
  }catch(e){log('Plan failed: '+e.message)}
};'''
h = h[:ps] + new_plan + h[pe:]
p.write_text(h)

q = Path('CourtFlow.html')
if q.exists():
    q.write_text(h)
