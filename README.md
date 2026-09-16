# PlayLoc / CourtFlow

CourtFlow is a multi-account PlayLocal court-search and booking concept with a GitHub Pages frontend and a server-side connector.

## Frontend

The hosted app is deployed at:

`https://to-shreds.github.io/PlayLoc/`

The live adapter URL is hard-wired into `index.html`:

`https://courtflow-playlocal.onrender.com/adapter`

Saved PlayLocal accounts persist in the browser on the device where they were entered. The frontend can search availability, plan account handoffs, make supported bookings, and load each saved account's current PlayLocal reservations through the Bookings tab when the upstream PlayLocal session is available.

## Backend

`playlocal_server.py` exposes CourtFlow's `/adapter` endpoint and keeps separate cookie/session state for each configured PlayLocal account. It implements authentication, availability, free booking, and reservation history. Reservation history is read from PlayLocal's authenticated Activity route at `/user/reservations`.

The connector is deployed on Render at:

`https://courtflow-playlocal.onrender.com`

## Current upstream blocker

The hosted connector is currently blocked from actually talking to PlayLocal. PlayLocal returns HTTP 403 with a Cloudflare `Just a moment...` challenge to ordinary server-side HTTP clients. This was reproduced independently from both the Render service and a GitHub-hosted Actions runner, so it is not just a stale frontend error or a malformed Render URL.

The connector now uses browser-like headers, cookies, referers, and account-authenticated sessions, but that does not solve the Cloudflare challenge because Python `requests` does not execute the browser challenge. The `/upstream` diagnostic endpoint and `.github/workflows/backend-smoke.yml` preserve this check.

As a result, the GitHub Pages interface and our adapter can reach each other, but live PlayLocal search, sign-in, history retrieval, and booking remain blocked until the PlayLocal interaction is moved to a transport that can establish a genuine browser session, such as a user-device/local browser bridge. Simulation mode remains available independently.

## Local test

```bash
pip install -r requirements.txt
python playlocal_server.py
```

Then use `http://127.0.0.1:8765/adapter` as the adapter URL from a locally served frontend.

Paid reservations remain blocked pending an explicit payment flow.
