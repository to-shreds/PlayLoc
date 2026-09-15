# PlayLoc / CourtFlow

CourtFlow is a multi-account PlayLocal court-search and booking concept. This repository is set up for a GitHub Pages frontend plus a server-side PlayLocal connector.

## Frontend

The GitHub Pages site is deployed from `index.html` by `.github/workflows/pages.yml`.

Expected URL after Pages is enabled with **GitHub Actions** as the source:

`https://to-shreds.github.io/PlayLoc/`

The static site can run the simulation by itself. Live PlayLocal actions require the backend because GitHub Pages cannot run Python or maintain authenticated PlayLocal sessions.

## Backend

`playlocal_server.py` exposes CourtFlow's `/adapter` endpoint. It maintains separate PlayLocal sessions per configured account and implements availability, authentication, reservation history, free booking, and cancellation against PlayLocal's web flows.

The repo includes `render.yaml` so the same GitHub repo can be deployed as a Render web service. After deployment, enter the HTTPS service URL plus `/adapter` in **Settings → PlayLocal connection**.

Example: `https://YOUR-SERVICE.onrender.com/adapter`

## Local test

```bash
pip install -r requirements.txt
python playlocal_server.py
```

Then open `http://127.0.0.1:8765/` and use `/adapter`.

The backend reads `PORT` automatically when hosted and supports CORS for the Pages frontend. Paid reservations remain blocked pending an explicit payment flow.
