from pathlib import Path

p = Path('playlocal_server.py')
s = p.read_text()
s = s.replace('from datetime import datetime\n', 'from datetime import datetime, timedelta\n', 1)
s = s.replace('    return forms[0] if len(forms) == 1 else None\n', '    return None\n', 1)

old = """                'available': available, 'priceCents': price,
            }
"""
new = """                'available': available, 'priceCents': price,
                'reservationHref': reservation_href,
                'reservationReferer': page.url,
                'searchLocation': q.get('location', ''),
            }
"""
if old not in s:
    raise SystemExit('slot metadata block not found')
s = s.replace(old, new, 1)

start = s.index('def court_options(req):\n')
end = s.index('\ndef set_fields(form, slot):\n', start)
replacement = '''def _reservation_page_for_query(s, q, facility_id):
    found_href = ''
    found_referer = ''
    for sp in search_pages(q, sess=s):
        sd = soup(sp.text)
        for box in sd.select('li[data-role="facility"]'):
            if str(box.get('data-id') or '') != str(facility_id):
                continue
            link = box.find('a', href=re.compile(r'/facilities/[^/]+/reservations/new'))
            if link:
                found_href = link.get('href', '')
                found_referer = sp.url
                break
        if found_href:
            break
    if not found_href:
        return None, None, None, '', ''
    target = urljoin(BASE, found_href)
    parsed = urlparse(target)
    if parsed.netloc not in ('www.playlocal.com', 'playlocal.com') or '/reservations/new' not in parsed.path:
        raise ApiError('COURT_OPTIONS', 'Invalid PlayLocal reservation link.', 400, True)
    p = browser_get(s, target, referer=found_referer, retry_403=True)
    if urlparse(p.url).path == '/sign_in':
        raise ApiError('AUTH_REJECTED', 'PlayLocal session expired.', 401, True)
    p.raise_for_status()
    d = soup(p.text)
    return p, d, _find_reservation_form(d), found_href, found_referer


def court_options(req):
    s = get_session(req['sessionToken'], req['accountId'])
    facility_id = str(req.get('facilityId') or '')
    if not facility_id:
        raise ApiError('COURT_OPTIONS', 'A facility is required.')
    requested_date = str(req.get('date') or '')
    q = {
        'date': requested_date,
        'location': req.get('location', ''),
        'sport': 'tennis',
        'start': int(req.get('start', 0) or 0),
        'end': int(req.get('end', 1440) or 1440),
        'facilityId': facility_id,
    }

    p, d, form, href, referer = _reservation_page_for_query(s, q, facility_id)
    requested_diag = ''
    if p is not None and d is not None:
        requested_diag = _page_diagnostic(p, d)
    if form is not None:
        courts = _extract_courts(form)
        if courts:
            return {
                'facilityId': facility_id,
                'courts': courts,
                'requestedDate': requested_date,
                'courtSourceDate': requested_date,
                'selectedDateAccessible': True,
                'reservationHref': href,
                'reservationReferer': referer,
            }

    today = datetime.now().date()
    probe_details = []
    for offset in range(1, 8):
        probe_date = (today + timedelta(days=offset)).isoformat()
        if probe_date == requested_date:
            continue
        pq = dict(q)
        pq['date'] = probe_date
        try:
            pp, pd, pf, phref, preferer = _reservation_page_for_query(s, pq, facility_id)
        except ApiError:
            raise
        except Exception as e:
            probe_details.append(f'{probe_date}: {type(e).__name__}')
            continue
        if pp is None or pd is None:
            probe_details.append(f'{probe_date}: no Reserve link')
            continue
        if pf is not None:
            courts = _extract_courts(pf)
            if courts:
                return {
                    'facilityId': facility_id,
                    'courts': courts,
                    'requestedDate': requested_date,
                    'courtSourceDate': probe_date,
                    'selectedDateAccessible': False,
                    'reservationHref': href or phref,
                    'reservationReferer': referer or preferer,
                    'notice': (
                        f'PlayLocal is not currently opening its reservation form for {requested_date}. '
                        f'The specific court list was loaded from {probe_date} instead. Exact-court '
                        f'availability for {requested_date} cannot be verified until PlayLocal opens '
                        f'the reservation form for that date.'
                    ),
                }
        probe_details.append(f'{probe_date}: ' + _page_diagnostic(pp, pd)[:260])

    detail = requested_diag or 'PlayLocal did not expose a Reserve link for the requested date.'
    if probe_details:
        detail += ' Probe results: ' + ' | '.join(probe_details[:3])
    raise ApiError('UPSTREAM_CHANGED', 'PlayLocal did not expose a usable reservation form. ' + detail, 502)

'''
s = s[:start] + replacement + s[end:]

old_snap = """        'date': slot['date'], 'sport': 'tennis', 'start': slot['start'], 'end': slot['end'],
        'facilityId': slot['facilityId'],
"""
new_snap = """        'date': slot['date'], 'sport': 'tennis', 'start': slot['start'], 'end': slot['end'],
        'facilityId': slot['facilityId'], 'location': slot.get('searchLocation', ''),
"""
if old_snap not in s:
    raise SystemExit('book availability query not found')
s = s.replace(old_snap, new_snap, 1)
p.write_text(s)

p = Path('index.html')
h = p.read_text()
h = h.replace('<div><label>Court</label><select id="court"></select></div>', '<div><label>Court</label><select id="court"></select><div id="courtNotice" class="small"></div></div>', 1)
h = h.replace('remoteBookings:[]};', 'remoteBookings:[],courtContext:null};', 1)

ls = h.index('async function loadCourts(){')
le = h.index('\nfunction t(', ls)
new_load = '''async function loadCourts(){
  let fid=$('facility').value;
  state.courtContext=null;
  if($('courtNotice'))$('courtNotice').textContent='';
  if(!fid){$('court').innerHTML='';return}
  if(state.mode!=='live'){
    let f=state.facilities.find(x=>String(x.id)===fid);
    $('court').innerHTML=(f?.courts||[]).map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');return
  }
  if(!state.accounts.length){$('court').innerHTML='<option value="">Add an account first</option>';return}
  let a=state.accounts[0];
  try{
    $('court').innerHTML='<option value="">Loading courts...</option>';
    let ss=await auth(a);
    let f=state.facilities.find(x=>String(x.id)===String(fid));
    let d=await rpc('court_options',{accountId:a.id,sessionToken:ss.sessionToken,facilityId:fid,reservationHref:f?.reservationHref||'',reservationReferer:f?.reservationReferer||'',date:$('pdate').value,location:$('loc').value.trim(),start:+$('pstart').value,end:+$('pend').value});
    state.courtContext=d;
    $('court').innerHTML=(d.courts||[]).map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
    if(d.selectedDateAccessible===false){
      let msg=d.notice||`PlayLocal is not opening exact-court booking for ${d.requestedDate} yet. Court names came from ${d.courtSourceDate}.`;
      if($('courtNotice'))$('courtNotice').textContent=msg;
      log(msg);
    }
    log(`Loaded ${(d.courts||[]).length} real court option${(d.courts||[]).length===1?'':'s'} from PlayLocal.`)
  }catch(e){
    $('court').innerHTML='<option value="">'+esc(e.message)+'</option>';
    if($('courtNotice'))$('courtNotice').textContent=e.message;
    log('Court lookup failed: '+e.message)
  }
}'''
h = h[:ls] + new_load + h[le:]

old_toggle = "$('bookPlan').classList.toggle('hidden',!rows.some(r=>r.status==='planned'));"
new_toggle = "$('bookPlan').classList.toggle('hidden',!rows.some(r=>r.status==='planned')||state.courtContext?.selectedDateAccessible===false);"
if old_toggle not in h:
    raise SystemExit('book-plan visibility expression not found')
h = h.replace(old_toggle, new_toggle, 1)
p.write_text(h)
