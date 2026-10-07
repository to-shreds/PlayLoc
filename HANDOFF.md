# CourtFlow continuation

Implementation: `to-shreds/PlayLoc`, branch `main`. Readiness: `to-shreds/ProjectStatus/projects/playlocal-courtflow/STATUS.md`.

Live HTML: https://to-shreds.github.io/PlayLoc/. Adapter: https://courtflow-playlocal.onrender.com/adapter. Optional remote display: https://courtflow-browser-playlocal.onrender.com.

## Current work

The default My calendar view aggregates Activity reservations from all accounts, uses Eastern dates, shows West Roxbury High School Court 1/2/3, and offers month navigation plus a date/time agenda. Identical date/time/court entries are collapsed across accounts; different courts at the same time remain separate. Partial loads are visibly marked. The calendar was published first in `93d3e09d1877e150332764c835827ff2c21cb6d0`; both Pages deployment and regression CI passed.

CAPTCHA now defaults to a normal-browser handoff. The user signs in to PlayLocal as the assigned account, chooses the displayed exact court/date/time, completes verification and submits, then returns to Check & continue. This does not transfer the remote server session into the phone browser. Existing remote verification remains an optional display. Uncertain remote submissions never expose a new submit link. Activity matching requires the exact date, start time, venue and court number, including PlayLocal's actual `West Roxbury High School 2` naming.

The remote display recognizes iframe/widget-only security pages before the form exists, checks required form validity, stops rejected or timed-out submissions without repeating them, bounds session-transfer requests, and releases canceled sessions without waiting on a hung transfer. The old add-remote-browser patch workflow is manual-only to keep it from rewriting the current app after service edits.

## Controlling external source

Cloudflare explicitly does not support automated browsers/Puppeteer for production challenges: https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/. Normal mobile browsers are supported: https://developers.cloudflare.com/turnstile/get-started/mobile-implementation/. Human taps on the remote screenshot do not change its underlying automated browser. No synthetic tokens, solver service, or anti-detection change was added.

## Preserve

West Roxbury default, all three Render-managed accounts and unchanged private passwords/site password, exact court/hour planning, sequential assignment, paid-booking restriction, and Activity reconciliation. Never automatically resubmit an uncertain booking. Do not expose private passwords or session cookies in HTML, repository or logs.

## Verification and next action

Browser fixtures cover the calendar, mobile width, court-number naming, deduplication, canceled entries, month navigation and partial failures. Verification regression tests cover pre-form display, validation, uncertain/rejected submissions, cancellation, native handoff and the original exact-court/queue boundaries. Python tests cover actual Activity naming and reject wrong courts/dates/times, missing fields and canceled reservations. Fixture tests never create real reservations.

Code benchmark: `b406d620446f645633e408a517c4e6aee7b7c8ef`. Local regression verification passed 25 Node/browser tests and four Python Activity tests. GitHub Actions verification run `37569201123` and Pages run `37569200962` passed for this code. The HTML build is `reservation-calendar-native-2`; the browser service is `verification-native-handoff-3`; the adapter health header is `activity-exact-native-3`.

Both Render services were explicitly deployed to this code after source pushes did not initiate deployments despite their `autoDeploy=yes` setting. Browser deploy `dep-db2s7159fdbs7393cjq0` became live at 2026-10-07T03:59:41Z; adapter deploy `dep-db2s71cs728c73afblag` became live at 2026-10-07T03:59:42Z. For later changes, verify the actual deployed commit rather than assuming a push deployed. Service IDs: browser `srv-dalhg7740ujc73e27qb0`; adapter `srv-dakujse7bikc73do4h60`; workspace `tea-dakujgmk1f9s73d2v8ng`.

Legacy workflows remain separate from current regression verification: backend-smoke's upstream connectivity check passed HTTP 200, but its unauthenticated availability request fails the site-password gate with HTTP 401. live-search-test still requests the past date September 17, 2026 and returns no facilities. The old fix-session-transfer workflow is invalid. These are not acceptance tests for the new native flow; repair or retire them separately when doing workflow maintenance.

Read ProjectStatus for readiness. A real user still needs to sign in in their normal browser, complete the real CAPTCHA, reserve the chosen slot, and confirm Activity-driven queue advancement. Real CAPTCHA acceptance is not proved by fixtures or browser health checks.
