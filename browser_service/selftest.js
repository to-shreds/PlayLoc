const puppeteer = require('puppeteer-core');
const chromium = require('@sparticuz/chromium');

(async()=>{
  let browser;
  try{
    browser = await puppeteer.launch({
      args: [...chromium.args, '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check'],
      defaultViewport: { width: 430, height: 760, deviceScaleFactor: 1, isMobile: true, hasTouch: true },
      executablePath: await chromium.executablePath(),
      headless: 'shell',
      dumpio: true,
    });
    const page = await browser.newPage();
    await page.goto('data:text/html,<title>CourtFlow Chromium Self Test</title><h1>ok</h1>', {waitUntil:'domcontentloaded', timeout:15000});
    const title = await page.title();
    if (title !== 'CourtFlow Chromium Self Test') throw new Error('Chromium page self-test returned an unexpected title.');
    const image = await page.screenshot({type:'jpeg', quality:68, fullPage:false, captureBeyondViewport:false});
    if (!image || image.length < 100) throw new Error('Chromium screenshot self-test failed.');
    await page.close();
    console.log('CourtFlow Chromium single-page self-test passed.');
  } catch (err) {
    console.error('CourtFlow Chromium self-test failed:', err?.stack || err);
    process.exitCode = 1;
  } finally {
    try { await browser?.close(); } catch {}
  }
})();
