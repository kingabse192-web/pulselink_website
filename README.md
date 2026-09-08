# PulseLink - privacy-first link analytics

A small Flask starter for:
- Homepage
- Analytics dashboard
- Tracking-link creation
- HTTP 302 redirects
- Click counts
- Device/browser/OS/referrer analytics
- SQLite storage
- Username/password accounts with per-user link isolation
- No raw IP address persistence
- No silent GPS collection

## Run locally

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

Create an account at `/signup`. Passwords are stored as one-way hashes and each account only sees its own links and analytics. Set `PULSELINK_SECRET_KEY` to a long random value before deploying. The default development key must not be used in production.

## Deploy

The included `Procfile` runs Gunicorn. A hosted service needs:

```text
PULSELINK_SECRET_KEY=<long-random-secret>
PULSELINK_DB=/var/data/pulselink.db
```

Use a persistent disk for `PULSELINK_DB`; otherwise SQLite data will be reset when the service is redeployed. For production analytics, also add HTTPS, rate limiting, backups, and a privacy notice.

## How the tracking link works

A visitor opens `/r/<code>`. The server records privacy-limited analytics, increments the click counter, and returns an HTTP 302 redirect to the destination.

Google sign-in is not enabled by default because it requires a Google Cloud OAuth client and a verified callback domain. It can be added after the live domain is chosen; local username/password accounts are ready now and do not require entering a Google password.
