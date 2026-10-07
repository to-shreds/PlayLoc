# PlayLoc / CourtFlow

CourtFlow is a browser-first PlayLocal court calendar and booking concept. This repository controls the implementation. `to-shreds/ProjectStatus/projects/playlocal-courtflow/STATUS.md` records verified readiness and remaining work.

## Hosted app

`https://to-shreds.github.io/PlayLoc/`

The HTML app uses the hard-wired Render adapter at `https://courtflow-playlocal.onrender.com/adapter`. West Roxbury is the default search location. Users choose a venue and date, select exact court/hour cells, review account assignments, and book.

My calendar is the opening tab. It combines Activity records from every account into an Eastern-time month view and date/time agenda, showing West Roxbury High School Court 1, 2 or 3 without account names. Refresh retrieves current records; incomplete account loads are visibly flagged.

In the primary hosted configuration, a site password unlocks three server-managed account nicknames. PlayLocal usernames and passwords stay in Render environment variables. GitHub, HTML, localStorage, and client request payloads do not contain the server-held credentials. The original browser-saved account mode remains available only when the server vault is not configured.

## Backend and verification

`playlocal_server.py` implements authentication, availability, free booking, and reservation history. Each PlayLocal account has separate HTTP cookie/session state. History and final confirmation use PlayLocal's authenticated Activity route at `/user/reservations`.

The Android app opens PlayLocal already signed in to the assigned saved account. CourtFlow issues a signed ticket that expires after two minutes and can be redeemed once by native code at `/native-session`. The app installs authenticated PlayLocal cookies, selects the exact court, and submits once after genuine verification completes. No account password is sent to the HTML or APK. Only exact Activity confirmation advances the booking queue. A rejected session refreshes automatically once; an uncertain submission is never repeated.

Install the current app from `https://to-shreds.github.io/PlayLoc/downloads/CourtFlow-debug.apk`. The hosted HTML detects the versioned native bridge; older apps are prompted to update. A normal webpage cannot install another site's login cookies, so authenticated verification runs inside the Android app. Physical-device CAPTCHA acceptance still needs validation on the user's phone.

`browser_service/server.js` retains an optional interactive verification display at `https://courtflow-browser-playlocal.onrender.com`. A signed, one-use ticket authorizes transfer of an already-authenticated session directly between the two Render services. The temporary PlayLocal page is rendered as authenticated JPEG responses. Cloudflare does not support automated browsers such as Puppeteer for production challenges, so this optional display is not a reliable replacement for the normal browser path. CourtFlow does not synthesize verification tokens.

The current Chromium configuration uses one active verification at a time. A second request is rejected while another verification is open, rather than silently closing somebody else's page. Bookings are processed sequentially. The image is displayed only after it decodes successfully, startup status polls remain nonterminal, and the pre-booking form's "reservation receipt" text is not treated as success. Only the exact selected court's reservation form can be submitted. An uncertain submission is not automatically repeated; Activity reconciliation determines whether it booked.

Paid reservations remain unsupported. My calendar and court planning work in the normal browser. Automatic saved-account sign-in for on-device CAPTCHA uses the Android companion.

## Regression tests

```bash
npm install --prefix browser_service --ignore-scripts
node --test browser_service/verification.test.js
pip install -r requirements.txt
python -m unittest discover -s tests
```

The suite exercises actual Chromium pages, authenticated HTTP frame responses, delayed startup, cancellation, failed initialization, false receipt text, exact court selection, single submission, read-only guards, and the mobile HTML interface. All PlayLocal-looking content in this suite is a local fixture. It does not use live accounts or create reservations. The permanent GitHub Actions verification workflow runs it after browser-service or frontend changes.

`browser_service/readonly-probe.js` is an opt-in Render diagnostic for the real authenticated display flow. It uses a temporary site credential configured only in Render, blocks all non-GET/HEAD browser requests and all interactive input, decodes five HTTP-delivered frames, and checks that Activity history is unchanged. It never calls the booking action. Disable its environment flag and clear the temporary diagnostic credential after testing. A successful display probe is not evidence that a human CAPTCHA or real reservation creation has been completed.

## Local adapter

```bash
pip install -r requirements.txt
python playlocal_server.py
```

The local adapter is `http://127.0.0.1:8765/adapter`. No production credentials are needed for the browser regression tests.
