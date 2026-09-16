from pathlib import Path

# Repair remote Chromium lifecycle.
p = Path('browser_service/server.js')
s = p.read_text()
s = s.replace("const VIEWPORT = { width: 980, height: 720, deviceScaleFactor: 1 };", "const VIEWPORT = { width: 430, height: 760, deviceScaleFactor: 1, isMobile: true, hasTouch: true };", 1)
s = s.replace("let browserPromise = null;\n", "", 1)
old = '''async function getBrowser() {
  if (!browserPromise) {
    browserPromise = puppeteer.launch({
      args: [...chromium.args, '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check'],
      defaultViewport: VIEWPORT,
      executablePath: await chromium.executablePath(),
      headless: 'shell',
    }).catch(err => {
      browserPromise = null;
      throw err;
    });
  }
  return browserPromise;
}
'''
new = '''async function launchBrowser() {
  return puppeteer.launch({
    args: [...chromium.args, '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check'],
    defaultViewport: VIEWPORT,
    executablePath: await chromium.executablePath(),
    headless: 'shell',
  });
}
'''
if old not in s:
    raise SystemExit('getBrowser block not found')
s = s.replace(old, new, 1)
s = s.replace("  try { await session.context?.close(); } catch {}", "  try { await session.browser?.close(); } catch {}", 1)
s = s.replace("app.post('/session/start', async (req, res) => {\n  try {", "app.post('/session/start', async (req, res) => {\n  let browser = null;\n  try {", 1)
s = s.replace("    const browser = await getBrowser();\n    const context = await browser.createBrowserContext();\n    const page = await context.newPage();", "    browser = await launchBrowser();\n    const page = await browser.newPage();", 1)
s = s.replace("      id, key, page, context, payload,", "      id, key, page, browser, payload,", 1)
s = s.replace("  } catch (err) {\n    console.error('start session failed:', err?.stack || err);", "  } catch (err) {\n    try { await browser?.close(); } catch {}\n    console.error('start session failed:', err?.stack || err);", 1)
p.write_text(s)

# Simplify the hosted mobile flow.
p = Path('index.html')
h = p.read_text()
h = h.replace('value="Boston" autocomplete="off"', 'value="West Roxbury" autocomplete="off"', 1)
h = h.replace('<section id="calendar" class="page">\n    <div class="card">\n      <h2>Choose a venue and date</h2>', '<section id="calendar" class="page">\n    <div id="nextStep" class="step-banner"><b>Step 1 of 4</b><span>Choose a date and find the venue.</span></div>\n    <div class="card" id="searchCard">\n      <h2>1. Find the venue</h2>', 1)
h = h.replace('<button class="btn primary" id="findVenues">Find venues</button>', '<button class="btn primary" id="findVenues">Find venues</button>', 1)
h = h.replace('<button class="btn primary" id="loadCalendar">Load court calendar</button>', '<button class="btn primary" id="loadCalendar">Show availability</button>', 1)
h = h.replace('<div class="notice">Green means that exact court is available at that hour. Red means that exact court is unavailable. Tap green cells to select the reservations you want.</div>\n    </div>', '<div class="notice">Choose the venue, then show its exact court-by-hour availability.</div>\n      <div id="searchSummary" class="search-summary hidden"><div><b id="searchSummaryTitle"></b><div class="small" id="searchSummaryMeta"></div></div><button class="btn" id="changeSearch">Change</button></div>\n    </div>', 1)
h = h.replace('    <div class="card">\n      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><h2 style="margin:0">Court availability</h2>', '    <div class="card" id="availabilityCard">\n      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><h2 style="margin:0">2. Pick available times</h2>', 1)
h = h.replace('    <div class="card">\n      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><h2 style="margin:0">Booking plan</h2><button class="btn primary" id="buildPlan">Build plan from selected cells</button><button class="btn primary hidden" id="bookPlan">Book planned slots</button></div>', '    <div class="card" id="planCard">\n      <div class="plan-head"><h2 style="margin:0">3. Review and book</h2><button class="btn primary" id="buildPlan">Build booking plan</button><button class="btn primary hidden" id="bookPlan">Book planned slots</button></div>', 1)
h = h.replace('  <div class="card"><h2>Activity</h2><div class="status" id="log">Ready.</div></div>', '  <details class="card debug-card"><summary>Technical activity</summary><div class="status" id="log" style="margin-top:10px">Ready.</div></details>', 1)
h = h.replace('<div class="browser-head"><div class="grow"><b>PlayLocal verification</b><div id="browserStatus" class="browser-status">Opening remote browser…</div></div><button class="btn" id="browserClose">Close</button></div>', '<div class="browser-head"><div class="grow"><b>4. Complete PlayLocal verification</b><div id="browserStatus" class="browser-status">Opening remote browser…</div></div><button class="btn hidden" id="browserRetry">Retry</button><button class="btn" id="browserClose">Close</button></div>', 1)
h = h.replace('<div class="browser-tools"><button class="btn" id="browserUp">Scroll up</button><button class="btn" id="browserDown">Scroll down</button><input id="browserText" placeholder="Type here only if PlayLocal asks for text"><button class="btn" id="browserSendText">Send text</button><button class="btn" id="browserEnter">Enter</button></div>', '<div class="browser-tools"><div class="browser-instruction"><b>Next:</b> Tap the verification control in the PlayLocal image above. CourtFlow will submit automatically when verification completes.</div><button class="btn" id="browserUp">↑</button><button class="btn" id="browserDown">↓</button><details class="browser-more"><summary>Keyboard controls</summary><div class="browser-keyboard"><input id="browserText" placeholder="Type only if PlayLocal asks"><button class="btn" id="browserSendText">Send</button><button class="btn" id="browserEnter">Enter</button></div></details></div>', 1)

css_marker = '.browser-modal{position:fixed;'
extra_css = '''.step-banner{display:flex;gap:10px;align-items:center;background:#173f31;color:#fff;border-radius:14px;padding:12px 14px;margin-bottom:12px}.step-banner span{opacity:.9}.search-summary{align-items:center;justify-content:space-between;gap:12px}.search-summary:not(.hidden){display:flex}.plan-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.plan-head h2{margin-right:auto!important}.debug-card summary{cursor:pointer;font-weight:750}.browser-instruction{flex:1 1 100%;font-size:13px;background:#eef4f0;padding:9px 10px;border-radius:9px}.browser-more{flex:1 1 100%}.browser-more summary{cursor:pointer;font-size:12px;color:var(--muted)}.browser-keyboard{display:flex;gap:7px;margin-top:8px}.browser-keyboard input{flex:1}.browser-status{font-size:13px!important;font-weight:650;margin-top:2px}\n'''
if extra_css not in h:
    h = h.replace(css_marker, extra_css + css_marker, 1)
mobile_old = '@media(max-width:820px){.wrap{padding:12px}.top{align-items:flex-start}.controls,.controls.second,.two-col{grid-template-columns:1fr 1fr}.controls .wide,.controls.second .wide{grid-column:1/-1}.plan-row{grid-template-columns:1fr 1fr}.plan-row .who{grid-column:1/-1;text-align:left}.booking-row{grid-template-columns:1fr}.matrix-wrap{max-height:58vh}.matrix th,.matrix td{min-width:92px}.matrix td:first-child,.matrix th:first-child{min-width:76px}}'
mobile_new = '@media(max-width:820px){.wrap{padding:9px}.top{align-items:flex-start}.brand{font-size:24px}.sub{display:none}.tabs{margin:10px 0}.controls,.controls.second,.two-col{grid-template-columns:1fr 1fr}.controls .wide,.controls.second .wide{grid-column:1/-1}.card{padding:12px;margin-bottom:9px}.step-banner{position:sticky;top:4px;z-index:20;padding:10px 11px}.plan-row{grid-template-columns:1fr 1fr}.plan-row .who{grid-column:1/-1;text-align:left}.booking-row{grid-template-columns:1fr}.matrix-wrap{max-height:52vh}.matrix th,.matrix td{min-width:86px;padding:5px}.matrix td:first-child,.matrix th:first-child{min-width:68px}.cell{min-height:42px;font-size:12px}.browser-modal{padding:0}.browser-card{width:100%;height:100dvh;border-radius:0}.browser-head{padding:8px 9px}.browser-view{min-height:0}.browser-view img{width:100%;height:auto;max-height:none;object-fit:contain}.browser-tools{padding:7px 9px;gap:6px}.browser-tools>.btn{padding:8px 12px}.browser-instruction{font-size:12px}.browser-keyboard{flex-wrap:wrap}.debug-card{margin-top:6px}}'
if mobile_old not in h:
    raise SystemExit('mobile CSS marker not found')
h = h.replace(mobile_old, mobile_new, 1)

# Prefer West Roxbury result and guide the user after each step.
h = h.replace("    $('venue').innerHTML=state.facilities.length?state.facilities.map(f=>`<option value=\"${esc(f.id)}\">${esc(f.name)}</option>`).join(''):'<option value=\"\">No venues found</option>';", "    $('venue').innerHTML=state.facilities.length?state.facilities.map(f=>`<option value=\"${esc(f.id)}\">${esc(f.name)}</option>`).join(''):'<option value=\"\">No venues found</option>';\n    const west=state.facilities.find(f=>/west roxbury/i.test(f.name));if(west)$('venue').value=String(west.id);\n    setNextStep(1,'Choose the venue, then tap Show availability.');", 1)
h = h.replace("    state.matrix={facility,courts,hours,slots};renderMatrix();log(`Loaded exact-court calendar: ${courts.length} court${courts.length===1?'':'s'} across ${hours.length} hour${hours.length===1?'':'s'}.`);", "    state.matrix={facility,courts,hours,slots};renderMatrix();\n    $('searchCard').classList.add('done');$('searchSummary').classList.remove('hidden');$('searchSummaryTitle').textContent=facility?.name||'Selected venue';$('searchSummaryMeta').textContent=`${$('date').value} · ${shortTime(start)} to ${shortTime(end)}`;\n    setNextStep(2,'Tap the green court/time cells you want.');\n    log(`Loaded exact-court calendar: ${courts.length} court${courts.length===1?'':'s'} across ${hours.length} hour${hours.length===1?'':'s'}.`);", 1)
h = h.replace("function renderSelectedSummary(){$('selectedSummary').textContent=`${state.selected.size} selected`}", "function renderSelectedSummary(){$('selectedSummary').textContent=`${state.selected.size} selected`;if(state.matrix){if(state.selected.size)setNextStep(3,`${state.selected.size} selected. Next: build the booking plan.`);else setNextStep(2,'Tap the green court/time cells you want.')}}", 1)
h = h.replace("document.querySelectorAll('[data-cell]').forEach(b=>b.onclick=()=>{const k=b.dataset.cell;if(state.selected.has(k))state.selected.delete(k);else state.selected.add(k);renderMatrix();renderSelectedSummary()});", "document.querySelectorAll('[data-cell]').forEach(b=>b.onclick=()=>{const k=b.dataset.cell;if(state.selected.has(k))state.selected.delete(k);else state.selected.add(k);state.plan=[];renderPlan();renderMatrix();renderSelectedSummary()});", 1)
h = h.replace("function renderPlan(){if(!state.plan.length){$('plan').innerHTML='<div class=\"small\">Select one or more green cells first.</div>';$('bookPlan').classList.add('hidden');return}$('plan').innerHTML=state.plan.map", "function renderPlan(){if(!state.plan.length){$('plan').innerHTML='<div class=\"small\">Select one or more green cells first.</div>';$('bookPlan').classList.add('hidden');$('buildPlan').classList.remove('hidden');return}$('plan').innerHTML=state.plan.map", 1)
h = h.replace(".join('');$('bookPlan').classList.toggle('hidden',!state.plan.some(r=>r.status==='planned'))}", ".join('');const planned=state.plan.filter(r=>r.status==='planned').length;$('bookPlan').classList.toggle('hidden',!planned);$('buildPlan').classList.toggle('hidden',!!planned);$('bookPlan').textContent=planned===1?'Book 1 slot':`Book ${planned} slots`;if(planned)setNextStep(4,`Plan ready. Next: book ${planned} slot${planned===1?'':'s'}.`)}", 1)
h = h.replace("$('bookPlan').onclick=async()=>{state.bookingQueue=state.plan.filter(r=>r.status==='planned');", "$('bookPlan').onclick=async()=>{setNextStep(4,'Booking in progress. Follow the prompt below if PlayLocal asks for verification.');state.bookingQueue=state.plan.filter(r=>r.status==='planned');", 1)

# Add step helpers and search-change control before account rendering bootstrap.
marker = "renderAccounts();renderSelectedSummary();renderPlan();"
helper = '''function setNextStep(step,message){const el=$('nextStep');if(!el)return;el.innerHTML=`<b>Step ${step} of 4</b><span>${esc(message)}</span>`;}
$('changeSearch').onclick=()=>{$('searchCard').classList.remove('done');$('searchSummary').classList.add('hidden');state.matrix=null;state.selected.clear();state.plan=[];renderMatrix();renderSelectedSummary();renderPlan();setNextStep(1,'Choose a date and find the venue.');$('searchCard').scrollIntoView({behavior:'smooth',block:'start'});};
'''
if marker not in h:
    raise SystemExit('bootstrap marker not found')
h = h.replace(marker, helper + marker, 1)

# Browser retry and clearer startup states.
h = h.replace("$('browserModal').classList.remove('hidden');$('browserStatus').textContent='Preparing a private PlayLocal browser…';$('browserFrame').removeAttribute('src');", "$('browserModal').classList.remove('hidden');$('browserRetry').classList.add('hidden');$('browserStatus').textContent='Preparing a private PlayLocal browser…';$('browserFrame').removeAttribute('src');", 1)
h = h.replace("  }catch(e){$('browserStatus').textContent='Could not open verification browser: '+e.message;log('Verification browser failed: '+e.message)}", "  }catch(e){$('browserStatus').textContent='Could not open verification browser: '+e.message;$('browserRetry').classList.remove('hidden');log('Verification browser failed: '+e.message)}", 1)
h = h.replace("$('browserClose').onclick=closeRemoteBrowser;", "$('browserClose').onclick=closeRemoteBrowser;\n$('browserRetry').onclick=async()=>{await closeRemoteBrowser();const row=state.pendingVerification?.row;if(row)startRemoteBrowser(row)};", 1)

p.write_text(h)
