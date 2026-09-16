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

## PlayLocal transport and search parsing

PlayLocal's Cloudflare layer rejects ordinary server-side HTTP clients with HTTP 403. The connector uses a Chrome-compatible TLS/browser fingerprint through `curl_cffi`, while preserving separate cookies and authenticated sessions for each PlayLocal account.

Search parsing now follows PlayLocal's current result markup directly: each facility card is identified by `data-role="facility"`, with the real facility heading, address, reservable-court count, and reservation-selector times read from the corresponding structured elements. This replaced the earlier ancestor-based parser that could return fallback names such as `Facility 30` and zero time slots.

The deployed live-search smoke test posts an availability query through the public Render adapter and requires nonzero facilities, nonzero slots, at least one available slot, and real facility names. The current benchmark returned 4 named Boston tennis facilities and 28 court/time rows for a 4–8 PM search on September 17, 2026.

Current-bookings retrieval has also been exercised successfully from the hosted app against saved PlayLocal accounts. Actual reservation creation remains a separate live-account test. Paid reservations remain blocked pending an explicit payment flow.

## Local test

```bash
pip install -r requirements.txt
python playlocal_server.py
```

Then use `http://127.0.0.1:8765/adapter` as the adapter URL from a locally served frontend.
