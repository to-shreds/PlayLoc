# PlayLoc / CourtFlow

CourtFlow is a multi-account PlayLocal court-search and booking concept with a GitHub Pages frontend and a server-side connector.

## Frontend

The hosted app is deployed at:

`https://to-shreds.github.io/PlayLoc/`

The live adapter URL is hard-wired into `index.html`:

`https://courtflow-playlocal.onrender.com/adapter`

Saved PlayLocal accounts persist in the browser on the device where they were entered. The frontend can search availability, plan account handoffs, make supported bookings, and load each saved account's current PlayLocal reservations through the Bookings tab.

## Backend

`playlocal_server.py` exposes CourtFlow's `/adapter` endpoint and keeps separate cookie/session state for each configured PlayLocal account. It implements authentication, availability, free booking, and reservation history. Reservation history is read from PlayLocal's authenticated Activity route at `/user/reservations`.

The connector is deployed on Render at:

`https://courtflow-playlocal.onrender.com`

## PlayLocal transport

PlayLocal's Cloudflare layer rejects ordinary server-side HTTP clients with HTTP 403. The connector therefore uses a Chrome-compatible TLS/browser fingerprint through `curl_cffi`, while preserving separate cookies and authenticated sessions for each PlayLocal account.

The Render startup probe now reaches PlayLocal search successfully with HTTP 200. The external GitHub Actions smoke test also requires the Render `/upstream` diagnostic to report `ok: true` and HTTP 200 before passing.

This verifies the hosted connector's public search transport. Authentication, reservation-history parsing, and actual reservation creation still require live-account validation because no PlayLocal credentials are stored in the repository or available to automated CI.

## Local test

```bash
pip install -r requirements.txt
python playlocal_server.py
```

Then use `http://127.0.0.1:8765/adapter` as the adapter URL from a locally served frontend.

Paid reservations remain blocked pending an explicit payment flow.
