from pathlib import Path

p = Path('index.html')
h = p.read_text()

old = r'''function verificationHelp(row,url){
  let help=$('bookingHelp');
  let account=row.account;
  let court=row.slot?.courtName||'selected court';
  help.innerHTML=`<div class="notice"><b>One quick PlayLocal step</b><div style="margin-top:6px">Book <b>${esc(court)}</b> at <b>${t(row.start)}</b> using <b>${esc(account.name)}</b> (${esc(account.email)}). Complete PlayLocal's verification and submit the reservation. CourtFlow will check Activity when you return and continue automatically.</div><div style="margin-top:10px"><a class="btn primary" href="${esc(url)}" target="_blank" rel="noopener">Open PlayLocal for ${t(row.start)}</a> <button class="btn" id="checkPendingBooking">Check & continue</button></div></div>`;
  $('checkPendingBooking').onclick=()=>checkPendingBooking(true);
}
'''

new = r'''function verificationHelp(row,url){
  let help=$('bookingHelp');
  let account=row.account;
  let court=row.slot?.courtName||'selected court';
  if(window.CourtFlowNative&&typeof window.CourtFlowNative.startBooking==='function'){
    help.innerHTML=`<div class="notice"><b>Finishing in PlayLocal</b><div style="margin-top:6px">CourtFlow is opening <b>${esc(court)}</b> at <b>${t(row.start)}</b> using <b>${esc(account.name)}</b>. If PlayLocal shows a verification challenge, complete it in the booking window. CourtFlow will submit as soon as PlayLocal says verification is complete, then confirm the reservation in Activity and continue.</div></div>`;
    try{
      window.CourtFlowNative.startBooking(JSON.stringify({
        url,
        accountName:account.name,
        email:account.email,
        password:account.password,
        courtId:row.slot?.courtId||'',
        courtName:court,
        timeLabel:t(row.start)
      }));
    }catch(e){
      log('Could not open the native PlayLocal booking window: '+e.message);
    }
    return;
  }
  help.innerHTML=`<div class="notice"><b>One quick PlayLocal step</b><div style="margin-top:6px">Book <b>${esc(court)}</b> at <b>${t(row.start)}</b> using <b>${esc(account.name)}</b> (${esc(account.email)}). Complete PlayLocal's verification and submit the reservation. CourtFlow will check Activity when you return and continue automatically.</div><div style="margin-top:10px"><a class="btn primary" href="${esc(url)}" target="_blank" rel="noopener">Open PlayLocal for ${t(row.start)}</a> <button class="btn" id="checkPendingBooking">Check & continue</button></div></div>`;
  $('checkPendingBooking').onclick=()=>checkPendingBooking(true);
}
'''

if old not in h:
    raise SystemExit('verificationHelp block not found')
h = h.replace(old, new, 1)

marker = "window.addEventListener('focus',()=>{\n"
insert = r'''window.addEventListener('courtflow-native-booking-complete',()=>{
  if(state.pendingVerification)setTimeout(()=>checkPendingBooking(true),500);
});
window.addEventListener('courtflow-native-message',e=>{
  if(e?.detail)log(String(e.detail));
});
'''
if insert not in h:
    if marker not in h:
        raise SystemExit('focus listener marker not found')
    h = h.replace(marker, insert + marker, 1)

p.write_text(h)
