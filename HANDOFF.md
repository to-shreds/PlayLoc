# CourtFlow continuation

Implementation: `to-shreds/PlayLoc`, branch `main`. Readiness: `to-shreds/ProjectStatus/projects/playlocal-courtflow/STATUS.md`. Read both before continuing.

Live HTML: https://to-shreds.github.io/PlayLoc/. Adapter: https://courtflow-playlocal.onrender.com/adapter. Optional remote display: https://courtflow-browser-playlocal.onrender.com. Android download: https://to-shreds.github.io/PlayLoc/downloads/CourtFlow-debug.apk.

## Current work and user requirement

The user explicitly rejected manual PlayLocal sign-in because it defeats CourtFlow's purpose. Do not recommend it as the solution. CourtFlow must use the three saved server accounts automatically; the only human booking step is genuine CAPTCHA completion.

My calendar is the opening tab. It aggregates all accounts' Activity, uses Eastern dates, shows West Roxbury High School Court 1/2/3, and offers month navigation plus date/time agenda without account names. Identical date/time/court entries are collapsed; different courts at the same time remain separate. Partial loads are marked. Calendar was published first in `93d3e09d1877e150332764c835827ff2c21cb6d0` and remains live.

The updated Android companion now invokes a versioned, origin-checked native bridge. The HTML sends only a signed ticket and request ID. `/native-session` verifies signature, native audience and expiration, atomically redeems a one-use bridge, and returns authenticated PlayLocal cookies plus the canonical account/slot/URL directly to native code. Tickets expire after two minutes. Passwords never go to HTML or APK. Foreign-domain and Cloudflare challenge cookies are excluded; HttpOnly is retained. The native endpoint has no browser-readable CORS response and uses no-store.

The app installs cookies before navigating, selects the exact court, validates date/start/end/duration and free price, shows the genuine on-device CAPTCHA, and submits once when verification completes. The device's standard WebView user agent and APIs are preserved. Rejected authentication refreshes automatically once. Exact Activity confirmation, never receipt text alone, advances the queue. Native and remote submission ownership and asynchronous callbacks stay bound to their original row. Uncertain submissions cannot start another attempt. Rotation preserves the running Activity. Cookie cleanup is scoped to PlayLocal and serialized across accounts.

Normal Chrome can still show the calendar and plan courts. A normal webpage cannot install PlayLocal's cross-origin login cookies; automatic saved-account authentication for a device CAPTCHA uses the companion app. An older app is prompted to update, with no manual credential fallback. The old APK's private signing key was not retained, so a one-time uninstall/reinstall may be necessary. Subsequent builds restore a dedicated v3 signing key. Gradle and the final explicit apksigner step use that preserved key; certificate verification rejects mismatches or a changed published signer. Missing later keys fail rather than silently rotating the signature. The key is never committed. APK metadata is in `downloads/CourtFlow-build.json`.

## Preserve and controlling sources

Preserve the West Roxbury default, all three Render-managed accounts and unchanged private passwords/site password, exact court/hour planning, sequential assignment, paid-booking restriction, and exact Activity reconciliation. Never automatically resubmit an uncertain reservation. Never expose private passwords or session cookies in HTML, repository or logs. No real reservation was created during implementation tests.

Cloudflare documents native WebView integration requirements: https://developers.cloudflare.com/turnstile/get-started/mobile-implementation/. Automated browsers/Puppeteer are not supported for production challenges: https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/. The optional remote display remains available but cannot prove real CAPTCHA acceptance. No synthetic tokens, solver service, or anti-detection modification was added.

Preserve prior remote repairs: pre-form iframe/widget detection, required form validation, rejected/45-second uncertain submission termination, bounded session transfer and prompt cancellation release. Activity matching requires date/start/venue/exact court number, including real `West Roxbury High School 2` names. Source-rewriting Android patch steps were removed from its build; the add-remote-browser patch workflow remains manual-only.

## Verification and deployments

Native implementation commit: `ff5af93e655892c6d80315847296f6b280f9614b`. Final callback/POST/rotation safeguards: `0585a8e526bfcb6e2633950abf173d1337affed9`. Final signing source: `67cce5ca9fe968c7cd39489845d3048aaedcce9c` (same native Java/HTML as the safeguards commit). APK publication: `5fdc9be41f538a633d139a81543c2b49997a3ac0`.

Local verification passed 44 Node/browser tests and 17 Python tests. Coverage includes actual native asset DOM behavior, genuine-fixture token waiting, exact court/time/form binding, free price, one submission, stale callbacks, bounded auth refresh, queue confirmation, ticket tamper/expiry/audience/replay/concurrent redemption and cookie isolation. All PlayLocal-looking content is offline fixture data. The final GitHub verification run `37577075498` passed. Android run `37578039399` passed Gradle compilation, cached signing, artifact upload and artifact-only publication. Android version: 0.2.0, code 2, native API 2. The final APK certificate matches the restored keystore SHA-256 `f54cb146e6e429fcde86a10f453718159cff7696f64e1c416d1b8a6a4f8e61cb`, consistent with the prior fresh runner's signing report. The old unconfigured debug builds changed certificates; the explicit preserved key fixes that. Final APK SHA-256: `7ad5ded39ee324da4cb623b4eeef9b11137da94c3782fb950dd9bcb21cfd3391`.

Adapter deploy `dep-db2tk5qjnfac73808pn0`, source `9742df70a35acd8dd4685bf05c9b7cda26274859` (same backend code as ff5af), became live at 2026-10-07T05:35:59Z. Public health confirms `authenticated-native-session-4`; the native endpoint rejects invalid tickets with HTTP401/no-store and no exposed cookies. HTML build is `calendar-authenticated-native-3`. Browser service remains the prior `verification-native-handoff-3` deploy `dep-db2s7159fdbs7393cjq0`.

Render pushes still did not initiate deployment despite autoDeploy being advertised, so adapter deployment was explicit after confirming no new deployment. Verify the actual deployed commit for future changes. Service IDs: browser `srv-dalhg7740ujc73e27qb0`; adapter `srv-dakujse7bikc73do4h60`; workspace `tea-dakujgmk1f9s73d2v8ng`.

Legacy workflow failures remain separate from passing regression verification: backend-smoke's unauthenticated availability call fails the site-password gate with HTTP401, live-search-test requests the past date September17,2026, and fix-session-transfer is invalid. Repair or retire separately during workflow maintenance.

## Remaining acceptance

Install the current APK, open CourtFlow, unlock its site gate if prompted, and book the next intended slot. Confirm that the correct saved account opens already authenticated, the planned court/date/time stays selected, genuine CAPTCHA completes, Activity confirms that exact booking, and the next queued account/slot opens automatically. No PlayLocal manual login should be needed. Physical-phone session portability, real CAPTCHA acceptance and real booking continuation are not proved by fixtures, a successful build or a health check. If authentication still rejects on the device, diagnose that session transfer rather than replacing it with manual sign-in.
