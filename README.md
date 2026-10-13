# truck-tracking

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

Docker host `10.0.0.4`, code in `/root/software/truck-tracking`, served at `10.0.0.4:8010` (VPN only).
nginx on the proxy box terminates HTTPS for `truck.qutrit.org` — see `deploy/nginx-truck.qutrit.org.conf`.

```bash
cd /root/software/truck-tracking
cp .env.example .env            # fill in GOOGLE_CLIENT_ID, PADDY_SECRET, ADMIN_EMAILS
docker compose up -d --build
docker compose exec app .venv/bin/python -m app.seed   # once: sites + aliases
curl http://10.0.0.4:8010/api/health
```

Data lives in `/root/software/truck-tracking/data/` (database + WhatsApp session) — back it up.

### Updating with live data

Schema changes are additive only (new tables / columns / settings, never drops or rewrites), and
the app copies the database to `data/backups/` automatically before applying any. Still, before
an update during a running shift, take a manual copy:

```bash
cd /root/software/truck-tracking
docker compose exec app .venv/bin/python -c "from app import core; print(core.backup(core.connect(), 'manual'))"
git pull && docker compose up -d --build
```

The open shift, reports and the WhatsApp session carry over a restart. Queued WhatsApp messages
younger than 30 min are still sent afterwards. Restore = stop the container, copy a backup over
`data/paddy.db` (delete `paddy.db-wal` / `-shm`), start again.

### WhatsApp

Everything is set in **Admin → WhatsApp**: scan the QR with the phone that should send messages
(Linked devices), pick the fleet and control groups, then switch WhatsApp on. The session survives
restarts and redeploys (it lives in `data/wa_session`). Unlink there to switch numbers.

Control group commands: `shift start [SITE]`, `shift end`, `summary`, `summary last`, `summary today`, `help`. Google OAuth client: Web application,
authorised JavaScript origin `https://truck.qutrit.org`, consent screen published.

## Layout

```
backend/app/
  trips.py      trip reconstruction engine (slots, duplicates, inference, counts) — pure, no DB
  summary.py    shift / day / season summaries + WhatsApp text
  reports.py    reports + shifts (create/edit/delete, audit, outbox)
  registry.py   trucks / sites / verbs, aliases, merge / unmerge
  wa.py         WhatsApp line formats (relay, strikethrough edit, delete)
  relay.py      outbox → WhatsApp routing, periodic summaries, stale-shift warning
  inbound.py    control-group commands, fleet-group messages → reports
  parse.py      strict deterministic parser for typed reports ("A,B LS KN4")
  wa_client.py  calls to the bridge
  auth.py       Google sign-in, session cookie, admin by email
  main.py       routes
  core.py       config, IST time, sqlite, audit, outbox
  schema.sql
wa/index.js     Baileys bridge (localhost only): status/QR, groups, send, inbound forwarding
web/src/
  App.svelte    tabs: Report | Mine | All | Summary | Admin
  lib/          ReportForm, Chips, ShiftBar, ReportList, api.js (IST helpers)
  pages/        Login, Onboard, Summary, Admin
```
