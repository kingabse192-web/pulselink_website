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
| ✅ | Three sharing choices | Allow all files & folders / Allow selected files (folders) / Don't allow file system |
| ✅ | Signup notifications | Optional SMTP notification to the project owner |
| ✅ | User accounts | Each account sees only its own links and analytics |
| ✅ | Password hashing | Passwords are stored as one-way hashes |
| ✅ | Raw IP disabled | Raw visitor IP is not persisted |
| ✅ | Health check | /health endpoint |
| ✅ | Google sign-in | Optional Google OAuth; username/password sign-in can be used instead |
| ✅ | Email verification | Verification link required for password-based signup; requires SMTP |
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

## 📁 Consent-based file access

The visitor page has three explicit choices:

1. **Allow all files & folders** — the visitor explicitly selects one top-level folder. PulseLink can then enumerate and upload every file and subfolder inside that selected folder.
2. **Allow selected files (folders)** — the visitor can choose individual files or a folder through the browser picker.
3. **Don't allow file system** — no file content is uploaded.

The first choice does not mean hidden or unrestricted access to the whole computer. Browsers require an explicit user selection; PulseLink only receives files inside the folder the visitor selected. A browser cannot grant a website an unrestricted whole-device filesystem permission.

The dashboard provides a browsable shared tree with:

- Folder and file names
- Relative paths
- File type / MIME type
- File size and modification time
- **Open** for browser-viewable files
- **Download** individual shared files
- **Download available files as ZIP** for the whole shared folder
- Revoke shared files for a visitor click

File transfer is always initiated by a visible visitor action. The server stores only content the visitor explicitly selected and uploaded. It cannot silently unlock the visitor's entire computer filesystem.

Default upload limits are 50 MB per file, 512 MB total per visitor share, and 5,000 manifest entries. Adjust these with the PULSELINK_MAX_* settings shown below.

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

    # Optional Google OAuth.
    PULSELINK_GOOGLE_CLIENT_ID=
    PULSELINK_GOOGLE_CLIENT_SECRET=
    PULSELINK_GOOGLE_REDIRECT_URI=https://YOUR-DOMAIN/auth/google/callback

    # Explicit visitor file storage and limits.
    PULSELINK_SHARED_STORAGE=shared_files
    PULSELINK_MAX_FILE_MB=50
    PULSELINK_MAX_TOTAL_MB=512
    PULSELINK_MAX_FILES=5000
    PULSELINK_MAX_UPLOAD_MB=60

# Automatic GitHub update on startup (default: enabled).
PULSELINK_AUTO_UPDATE=1
PULSELINK_UPDATE_REMOTE=origin
PULSELINK_UPDATE_BRANCH=main

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
    python start.py

Both `python app.py` and `python start.py` use the startup update check. If this directory is a clean Git clone and GitHub's `main` is newer, PulseLink fast-forwards to the new version and restarts so the new code is the version actually running.

Open http://127.0.0.1:5000

Create an account, sign in, create a tracking link and open the generated link in a browser to test the visitor flow.

## 🏗️ Project structure

    pulselink_website/
    ├── app.py
    ├── requirements.txt
    ├── Procfile
    ├── .env.example
    ├── .gitignore
    ├── README.md
    ├── requirements-dev.txt
    └── test_app.py

SQLite creates the application database on first start.

## 🔐 Security notes

- Location sharing requires an explicit button click and browser permission.
- File/folder sharing requires a manual selection and an explicit agreement.
- Google sign-in is optional; users can skip it and use the username/password flow.
- Email verification can be completed later; **Maybe later — continue to PulseLink** opens the dashboard while keeping the account marked unverified.
- Raw visitor IP addresses are not saved.
- Accounts are isolated by user ID.
- For public deployment, use HTTPS, a strong secret key, persistent storage, backups, rate limiting and a clear privacy notice that matches the actual data practices.

## 🔄 Automatic project updates

When you start PulseLink with `python start.py`, the project checks the configured GitHub remote for a newer `main` commit. On a clean Git clone it fetches the remote and performs a **fast-forward-only** update. Local changes are never overwritten; when the working tree is dirty or the remote history cannot be fast-forwarded, PulseLink starts using the current local version instead.

Set `PULSELINK_AUTO_UPDATE=0` to disable the startup check.

## 📦 Download and use

This repository is public. Anyone can download it from GitHub with **Code → Download ZIP** or by cloning the repository.

Before deploying publicly, configure production secrets and persistent storage. Do not publish database files, private databases, SMTP credentials or other private runtime data.

## 📜 License

PulseLink is released under the MIT License. See [LICENSE](LICENSE).

## 👤 Project

**PulseLink**

Created by **ABSALEW BELAYNEH**

Project owner / notification email: **absalew1234@gmail.com**