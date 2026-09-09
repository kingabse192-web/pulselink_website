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
- Consent-based full name, email, and stated purpose at signup
- Abuse-report contact: `absalew1234@gmail.com`
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

Create an account at `/signup`. Registration asks for a name, email, intended use, and explicit agreement to the privacy and acceptable-use notice. Passwords are stored as one-way hashes and each account only sees its own links and analytics. Abuse reports can be sent to `absalew1234@gmail.com` for manual review; the app does not automatically accuse or report users.

The app stores the signup details and consent timestamp for account security and abuse review. Publish a complete privacy policy and confirm applicable privacy-law obligations before collecting real user data.

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

## Feature readiness

| Feature | Status | Result |
|---|---|---|
| Homepage | Ready | Works |
| Professional signup | Ready | Name, email, purpose, username, password |
| Consent checkbox | Ready | Required before account creation |
| Password security | Ready | Passwords are hashed |
| Separate user accounts | Ready | Users cannot access each other's links |
| Link creation | Ready | Validates HTTP/HTTPS URLs |
| Tracking redirect | Ready | Uses HTTP 302 |
| Analytics | Ready | Browser, device, OS, referrer, approximate location |
| Raw IP storage | Disabled | Raw IP is not saved |
| Abuse contact | Ready | `absalew1234@gmail.com` |
| Health check | Ready | `/health` endpoint works |
| Local smoke test | Passed | `final smoke: ok` |
| Google sign-in | Not configured | Requires Google OAuth credentials |
| Live hosting | Not completed | Requires a hosting account and production secrets |

## Upcoming features

| Feature | Status | Planned result |
|---|---|---|
| Google sign-in | Planned | Users can authenticate with Google OAuth |
| Email verification | Planned | Confirm ownership of the signup email address |
| Password reset | Planned | Secure reset links sent by email |
| Abuse report dashboard | Planned | Review reports and account activity in one place |
| Rate limiting | Planned | Reduce automated abuse and login attacks |
| CSRF protection | Planned | Protect account-changing form submissions |
| Persistent production database | Planned | Keep accounts and analytics across deployments |
| Privacy policy page | Planned | Explain data collection, retention, and user rights |
| Data export and deletion | Planned | Let users download or remove their account data |
| Automated deployment checks | Planned | Run smoke tests before each production release |
