# paddy2026

Truck event reporting for the paddy harvest: a mobile web app (PWA) feeding a FastAPI backend,
mirrored to WhatsApp. See [DESIGN.md](DESIGN.md) for the model and decisions.

## Dev

```bash
# backend (port 8000)
cd backend
DEV_LOGIN=1 ADMIN_EMAILS=you@example.com uv run uvicorn app.main:app --reload

# web (port 5173, proxies /api to 8000)
cd web && npm install && npm run dev

# tests
cd backend && uv run pytest
```

With `DEV_LOGIN=1` the login page shows an email box instead of Google sign-in.

## Deploy

Docker host `10.0.0.4`, code in `/software/paddy2026`, served at `10.0.0.4:8010` (VPN only).
nginx on the proxy box terminates HTTPS for `truck.qutrit.org` — see `deploy/nginx-truck.qutrit.org.conf`.

```bash
cd /software/paddy2026
cp .env.example .env            # fill in GOOGLE_CLIENT_ID, PADDY_SECRET, ADMIN_EMAILS
docker compose up -d --build
docker compose exec app .venv/bin/python -m app.seed   # once: sites + aliases
curl http://10.0.0.4:8010/api/health
```

Data lives in `/software/paddy2026/data/` — back it up. Google OAuth client: Web application,
authorised JavaScript origin `https://truck.qutrit.org`, consent screen published.

## Layout

```
backend/app/
  trips.py      trip reconstruction engine (slots, duplicates, inference, counts) — pure, no DB
  summary.py    shift / day / season summaries + WhatsApp text
  reports.py    reports + shifts (create/edit/delete, audit, outbox)
  registry.py   trucks / sites / verbs, aliases, merge / unmerge
  wa.py         WhatsApp line formats (relay, strikethrough edit, delete)
  auth.py       Google sign-in, session cookie, admin by email
  main.py       routes
  core.py       config, IST time, sqlite, audit, outbox
  schema.sql
web/src/
  App.svelte    tabs: Report | Mine | All | Summary | Admin
  lib/          ReportForm, Chips, ShiftBar, ReportList, api.js (IST helpers)
  pages/        Login, Onboard, Summary, Admin
```
