# 🚀 PulseLink

[![CI](https://github.com/kingabse192-web/pulselink_website/actions/workflows/ci.yml/badge.svg)](https://github.com/kingabse192-web/pulselink_website/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Privacy-conscious link analytics built with Flask, SQLite and Leaflet.

PulseLink creates shareable tracking links and provides a private dashboard for clicks, device, browser, OS, referrer and approximate IP-based geography data.

## ✨ Feature status

| Status | Feature | Details |
|---|---|---|
| ✅ | Tracking links | YouTube, Google, Instagram and other HTTP/HTTPS destinations |
| ✅ | Dashboard | Private account analytics dashboard |
| ✅ | Device analytics | Desktop / Mobile / Tablet |
| ✅ | Browser + OS | Parsed from User-Agent |
| ✅ | Approximate IP map | Approximate country/region/city/ISP data |
| ✅ | One-time location sharing | Visitor must click Share my location and approve browser permission |
| ✅ | Exact shared coordinates | Dashboard map shows browser-provided latitude, longitude, accuracy and time |
| ✅ | Visitor details | Device, browser, OS, referrer, timezone and location details |
| ✅ | Consent-based folder explorer | Visitor chooses a folder or selected files; dashboard shows the shared structure |
| ✅ | Folder/file metadata | Names, relative paths, sizes, modification times and MIME types are available in the dashboard |
| ✅ | Three sharing choices | Allow selected folder / Allow selected files / Don't allow |
| ✅ | Signup notifications | Optional SMTP notification to the project owner |
| ✅ | User accounts | Each account sees only its own links and analytics |
| ✅ | Password hashing | Passwords are stored as one-way hashes |
| ✅ | Raw IP disabled | Raw visitor IP is not persisted |
| ✅ | Health check | /health endpoint |
| 🚧 | Google sign-in | Coming soon |
| 🚧 | Email verification | Coming soon |
| 🚧 | Password reset | Coming soon |
| 🚧 | Rate limiting | Coming soon |
| 🚧 | CSRF protection | Coming soon |
| 🚧 | Data export/deletion UI | Coming soon |
| 🚧 | Production deployment automation | Coming soon |
| ✅ | Consent-based precise location | Explicit browser permission; one-time location share |
| ✅ | Privacy-limited IP analytics | Approximate geography without storing raw IP |
| ❌ | Silent GPS tracking | Never enabled; use explicit location sharing |
| ❌ | Silent filesystem browsing | Never enabled; use explicit folder/file selection |
| ❌ | Raw IP database storage | Not used by default |

## 🗺️ Location

PulseLink keeps approximate IP location separate from explicitly shared browser location.

**Approximate IP location:** the server may use a visitor's public IP transiently for approximate geography. The raw IP is not stored.

**Explicit browser location:** the visitor must press **Share my location** and approve the browser's native permission prompt. Only one location share is accepted for that click.

The dashboard map can show the shared latitude, longitude, accuracy in meters, sharing timestamp, device, browser and operating system.

⚠️ Browser location accuracy is an estimate, not a mathematical guarantee of an exact physical point.

## 📁 Consent-based folder explorer

The tracking page gives visitors three clear choices:

1. **Allow selected folder** — the visitor chooses a folder and PulseLink receives a one-time snapshot of its folder/file names and metadata.
2. **Allow selected files** — the visitor chooses individual files and PulseLink receives their names and metadata.
3. **Don't allow** — nothing from the file selection is shared.

The dashboard can expand the shared folder tree and display:

- Folder and file names
- Relative paths
- File type / MIME type
- File size
- Modification time

**File contents are not uploaded by this feature.** The browser only shares the selected structure and metadata.

A normal website cannot silently request unrestricted access to a person's computer. For a whole-disk-style snapshot, the visitor would have to explicitly select the relevant top-level folder in a browser that permits that selection; browser security rules still control what can be granted.


## 📧 New-account notifications

When SMTP is configured, a new account can notify the project owner at absalew1234@gmail.com with the signup name, email, username, stated purpose and creation time.

Configure these environment variables on your server:

    PULSELINK_SECRET_KEY=replace-with-a-long-random-secret
    PULSELINK_DB=pulselink.db
    PULSELINK_OWNER_EMAIL=absalew1234@gmail.com
    PULSELINK_SMTP_HOST=smtp.gmail.com
    PULSELINK_SMTP_PORT=587
    PULSELINK_SMTP_USERNAME=your-sending-gmail@gmail.com
    PULSELINK_SMTP_PASSWORD=your-gmail-app-password
    PULSELINK_SMTP_FROM=your-sending-gmail@gmail.com

Never commit real passwords, app passwords or API secrets to GitHub.

## ⚡ Quick start

### 1. Download

Use GitHub **Code → Download ZIP**, or run:

    git clone https://github.com/kingabse192-web/pulselink_website.git
    cd pulselink_website

### 2. Windows

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python app.py

### 3. Linux / macOS

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000

Create an account, sign in, create a tracking link and open the generated link in a browser to test the visitor flow.

## 🏗️ Project structure

    pulselink_website/
    ├── app.py
    ├── requirements.txt
    ├── Procfile
    ├── .env.example
    ├── .gitignore
    └── README.md

SQLite creates the application database on first start.

## 🔐 Security notes

- Location sharing requires an explicit button click and browser permission.
- File/folder sharing requires a manual selection and an explicit agreement.
- Raw visitor IP addresses are not saved.
- Accounts are isolated by user ID.
- For public deployment, use HTTPS, a strong secret key, persistent storage, backups, rate limiting and a clear privacy notice that matches the actual data practices.

## 📦 Download and use

This repository is public. Anyone can download it from GitHub with **Code → Download ZIP** or by cloning the repository.

Before deploying publicly, configure production secrets and persistent storage. Do not publish database files, private databases, SMTP credentials or other private runtime data.

## 📜 License

PulseLink is released under the MIT License. See [LICENSE](LICENSE).

## 👤 Project

**PulseLink**

Created by **ABSALEW BELAYNEH**

Project owner / notification email: **absalew1234@gmail.com**