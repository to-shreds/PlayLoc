# CourtFlow continuation

Implementation: `to-shreds/PlayLoc`, branch `main`. Readiness: `to-shreds/ProjectStatus/projects/playlocal-courtflow/STATUS.md`. Read both before continuing.

Live HTML: https://to-shreds.github.io/PlayLoc/. Adapter: https://courtflow-playlocal.onrender.com/adapter. Verification display: https://courtflow-browser-playlocal.onrender.com.

## Controlling user requirements

CourtFlow must be an HTML website. On October 13 the user explicitly rejected the APK solution. Do not recommend installing an app or switching the deliverable to Android. The user also rejected manual PlayLocal login. Preserve automatic use of the three server-managed accounts; only genuine CAPTCHA completion should require human input.

## Current source and completed work

My calendar remains the opening tab. It aggregates every account's Activity into an Eastern-time month calendar and date/time agenda, showing West Roxbury High School Court 1, 2 or 3 without account names. Identical date/time/court entries are deduplicated; distinct courts remain separate. Partial loads are marked. Do not undo this completed work.

The HTML verification entry now opens the existing in-page display automatically using saved server accounts. All native bridge handlers and APK/install controls were removed from `index.html`. Authentication and a signed one-use `browser_ticket` transfer remain server-side; passwords and PlayLocal cookies never enter HTML. An expired account session is refreshed automatically once. Closing verification leaves its controls visible on Find courts. Exact Activity confirmation advances the queue. An uncertain or unknown submitted reservation cannot open a second submission session, including after Close/Resume or Retry; delayed close results belong to their original row.

HTML build marker: `calendar-html-verification-4`. The previous Android source and download are archived in the repository, not part of the requested delivery path. Backend/native asset tests remain as regression coverage for preserved source.

## CAPTCHA blocker and verified boundaries

Changing the frontend format does not solve genuine CAPTCHA acceptance. The existing display runs Puppeteer with headless Chromium. Cloudflare excludes automated browsers and automation frameworks from production challenge support: https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/. A visible widget, JPEG, or fixture token does not establish real CAPTCHA success. No real CAPTCHA or reservation was completed during the format correction.

CourtFlow cannot set PlayLocal cookies in the user's local browser from its unrelated origin: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie#invalid_domains. Do not suggest a reverse proxy or transplanting a solved challenge token as proof of a solution.

A candidate HTML-only replacement is a stock desktop browser launched normally and streamed through an authenticated browser-based remote desktop such as noVNC: https://github.com/novnc/noVNC. Keep login, genuine human challenge and submission in the same PlayLocal-origin browser. This candidate has NOT been built, deployed or verified. Do not merely set Puppeteer headful mode and call it supported. Prototype separately and prove authenticated session portability and genuine challenge acceptance before treating it as the solution.

A live read-only proof must block reservation mutations specifically while allowing legitimate challenge requests. The existing readonly probe blocks every POST, including challenge requests, so it proves display only.

## Preserve and verification

Preserve the site-password gate, all three unchanged Render-managed credentials, West Roxbury default, exact court/hour planning, sequential assignment, free-booking restriction, and date/start/venue/exact-court Activity matching. Never automatically repeat an uncertain reservation. Never expose private passwords, session cookies or service secrets in HTML, repository or logs. No real reservation may be created as a fixture test.

The browser suite verifies the default HTML booking entry, saved-account authentication without client credentials, in-page display, exact Activity-driven queue continuation, absence of APK/native controls, and prevention of duplicate sessions after uncertain Close/Resume. The full suite also covers existing startup/cancellation/form/court/input/price protections. Fixture verification and real CAPTCHA acceptance must remain distinct.

Backend services were not changed for this HTML correction. Adapter build remains `authenticated-native-session-4`; browser build remains `verification-native-handoff-3`. Workspace `tea-dakujgmk1f9s73d2v8ng`; adapter `srv-dakujse7bikc73do4h60`; browser `srv-dalhg7740ujc73e27qb0`. Future backend changes require checking actual deployed source because source pushes previously did not initiate deployments despite advertised autoDeploy.

Legacy smoke/search/invalid patch workflows are separate from the current regression suite; inspect ProjectStatus for context. No need to build or publish another APK.

## Next action

The HTML format correction can be used at the existing website. The calendar is ready, while reliable CAPTCHA-protected booking remains blocked. Continue the normal-browser remote desktop prototype and a genuine read-only CAPTCHA proof; do not replace the user's HTML requirement or fall back to manual PlayLocal sign-in.
