from pathlib import Path

# Backend: add an explicit Activity-based booking verification action.
p = Path('playlocal_server.py')
s = p.read_text()

marker = "\ndef dispatch(req):\n"
if marker not in s:
    raise SystemExit('dispatch marker not found')

if 'def verify_booking(req):' not in s:
    helper = r'''
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

'''
    s = s.replace(marker, helper + marker, 1)

old_dispatch = """    if action == 'court_options':
        return court_options(req)
    if action == 'book':
        return book(req)
"""
new_dispatch = """    if action == 'court_options':
        return court_options(req)
    if action == 'verify_booking':
        return verify_booking(req)
    if action == 'book':
        return book(req)
"""
if old_dispatch not in s and "if action == 'verify_booking':" not in s:
    raise SystemExit('dispatch action block not found')
if old_dispatch in s:
    s = s.replace(old_dispatch, new_dispatch, 1)

p.write_text(s)

# Frontend: preserve the plan across the verification handoff and automatically
# resume after Activity confirms the reservation.
p = Path('index.html')
h = p.read_text()

old_book = """$('bookPlan').onclick=async()=>{let help=$('bookingHelp');help.innerHTML='';for(let r of state.plan.filter(x=>x.status==='planned')){try{let result=await doBook(r.slot,r.account);log(`Booked ${t(r.start)} with ${r.account.name}${result?.reconciled?' (confirmed in PlayLocal Activity)':''}`)}catch(e){if(e.code==='VERIFICATION_REQUIRED'){let u=e.data?.reservationUrl||r.slot.reservationUrl||'';log(`Stopped at ${t(r.start)}: PlayLocal requires browser verification before booking.`);if(u)help.innerHTML=`<a class=\"btn primary\" href=\"${esc(u)}\" target=\"_blank\" rel=\"noopener\">Verify and book ${t(r.start)} on PlayLocal</a>`}else{log(`Stopped at ${t(r.start)}: ${e.message}`)}break}}await refreshCurrentBookings();renderBookings()};"""

new_book = r'''function renderPlanState(){
  $('plan').innerHTML=state.plan.map(r=>{
    let label=r.label||'';
    let cls='bad';
    if(r.status==='planned'){label=r.account?.name||label;cls='ok'}
    else if(r.status==='booked'){label=`Booked · ${r.account?.name||''}`;cls='ok'}
    else if(r.status==='verification'){label=`Verify · ${r.account?.name||''}`;cls='bad'}
    return `<div class="planrow"><span>${t(r.start)}</span><span class="${cls}">${esc(label)}</span></div>`
  }).join('');
}

function verificationHelp(row,url){
  let help=$('bookingHelp');
  let account=row.account;
  let court=row.slot?.courtName||'selected court';
  help.innerHTML=`<div class="notice"><b>One quick PlayLocal step</b><div style="margin-top:6px">Book <b>${esc(court)}</b> at <b>${t(row.start)}</b> using <b>${esc(account.name)}</b> (${esc(account.email)}). Complete PlayLocal's verification and submit the reservation. CourtFlow will check Activity when you return and continue automatically.</div><div style="margin-top:10px"><a class="btn primary" href="${esc(url)}" target="_blank" rel="noopener">Open PlayLocal for ${t(row.start)}</a> <button class="btn" id="checkPendingBooking">Check & continue</button></div></div>`;
  $('checkPendingBooking').onclick=()=>checkPendingBooking(true);
}

async function verifyRowInActivity(row){
  let ss=await auth(row.account);
  return rpc('verify_booking',{accountId:row.account.id,sessionToken:ss.sessionToken,slot:row.slot});
}

async function checkPendingBooking(manual=false){
  let pending=state.pendingVerification;
  if(!pending||state.pendingCheckRunning)return false;
  state.pendingCheckRunning=true;
  try{
    for(let attempt=0;attempt<5;attempt++){
      let v=await verifyRowInActivity(pending.row);
      if(v.confirmed){
        pending.row.status='booked';
        pending.row.label=`Booked · ${pending.row.account.name}`;
        log(`Confirmed ${t(pending.row.start)} in PlayLocal Activity for ${pending.row.account.name}.`);
        state.pendingVerification=null;
        $('bookingHelp').innerHTML='';
        state.bookingCursor++;
        renderPlanState();
        await refreshCurrentBookings();
        state.pendingCheckRunning=false;
        await continuePlanBooking();
        return true;
      }
      if(attempt<4)await new Promise(r=>setTimeout(r,1800));
    }
    if(manual)log(`No ${t(pending.row.start)} reservation is showing in PlayLocal Activity yet.`);
    return false;
  }catch(e){
    if(manual)log('Booking check failed: '+e.message);
    return false;
  }finally{
    state.pendingCheckRunning=false;
  }
}

async function continuePlanBooking(){
  if(state.pendingVerification)return;
  let queue=state.bookingQueue||[];
  while((state.bookingCursor||0)<queue.length){
    let row=queue[state.bookingCursor];
    try{
      let result=await doBook(row.slot,row.account);
      row.status='booked';
      row.label=`Booked · ${row.account.name}`;
      log(`Booked ${t(row.start)} with ${row.account.name}${result?.reconciled?' (confirmed in PlayLocal Activity)':''}.`);
      state.bookingCursor++;
      renderPlanState();
      continue;
    }catch(e){
      if(e.code==='VERIFICATION_REQUIRED'){
        let url=e.data?.reservationUrl||row.slot.reservationUrl||'';
        row.status='verification';
        row.label=`Verify · ${row.account.name}`;
        state.pendingVerification={row,url};
        renderPlanState();
        log(`${t(row.start)} needs PlayLocal browser verification for ${row.account.name}.`);
        if(url)verificationHelp(row,url);
        else $('bookingHelp').textContent='PlayLocal requires browser verification, but CourtFlow did not receive a continuation URL.';
        return;
      }
      row.status='failed';
      row.label=e.message||'Booking failed';
      renderPlanState();
      log(`Stopped at ${t(row.start)}: ${e.message}`);
      return;
    }
  }
  $('bookingHelp').innerHTML='<span class="ok">All planned reservations are confirmed.</span>';
  log('All planned slots are confirmed in PlayLocal.');
  await refreshCurrentBookings();
}

$('bookPlan').onclick=async()=>{
  $('bookingHelp').innerHTML='';
  state.bookingQueue=state.plan.filter(x=>x.status==='planned'||x.status==='verification');
  state.bookingCursor=0;
  state.pendingVerification=null;
  state.pendingCheckRunning=false;
  await continuePlanBooking();
};

window.addEventListener('focus',()=>{
  if(state.pendingVerification)setTimeout(()=>checkPendingBooking(false),700);
});
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden&&state.pendingVerification)setTimeout(()=>checkPendingBooking(false),700);
});'''

if old_book not in h:
    if 'function checkPendingBooking(' not in h:
        raise SystemExit('current bookPlan block not found')
else:
    h = h.replace(old_book, new_book, 1)

p.write_text(h)
