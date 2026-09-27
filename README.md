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
| ✅ | Explicit file uploads | Visitor chooses files and presses Upload |
| ✅ | downloads/ storage | Uploaded files are stored in the project downloads folder |
| ✅ | Owner-only downloads | Authenticated owner can download files from the dashboard |
| ✅ | Signup notifications | Optional SMTP notification to the project owner |
| ✅ | User accounts | Each account sees only its own links and analytics |
| ✅ | Password hashing | Passwords are stored as one-way hashes |
| ✅ | Raw IP disabled | Raw visitor IP is not persisted |
| ✅ | Health check | /health endpoint |
| 🚧 | Google sign-in | Coming soon; requires OAuth credentials and a callback domain |
| 🚧 | Email verification | Coming soon |
| 🚧 | Password reset | Coming soon |
| 🚧 | Rate limiting | Coming soon |
| 🚧 | CSRF protection | Coming soon |
| 🚧 | Data export/deletion UI | Coming soon |
| 🚧 | Production deployment automation | Coming soon |
| ✅ | Consent-based precise location | Supported: visitor actively requests and approves location sharing |
| ✅ | User-selected file access | Supported: visitor manually selects files and presses Upload |
| ✅ | Privacy-limited IP analytics | Supported: approximate geography without storing the raw IP |
| ❌ | Silent GPS tracking | Never enabled; replaced by explicit one-time location sharing |
| ❌ | Silent filesystem browsing | Never enabled; replaced by manual file selection/upload |
| ❌ | Raw IP database storage | Not used by default; privacy-limited analytics is the supported design |

## 🗺️ Location

PulseLink keeps approximate IP location separate from explicitly shared browser location.

**Approximate IP location:** the server may use a visitor's public IP transiently for approximate geography. The raw IP is not stored.

**Explicit browser location:** the visitor must press **Share my location** and approve the browser's native permission prompt. Only one location share is accepted for that click.

The dashboard map can show the shared latitude, longitude, accuracy in meters, sharing timestamp, device, browser and operating system.

⚠️ Browser location accuracy is an estimate, not a mathematical guarantee of an exact physical point.

## 📁 Explicit file uploads

The tracking page provides an optional file picker. A visitor manually selects supported files and presses **Upload selected files**. PulseLink does not receive blanket permission to browse the visitor's computer.

Supported extensions include: .jpg, .jpeg, .png, .gif, .webp, .pdf, .txt, .csv, .doc, .docx, .xls, .xlsx, .ppt, .pptx and .zip.

Default limits: up to 5 files per upload request and 25 MB per file.

Runtime uploads are stored under:

    downloads/

Only the repository placeholder file is committed; real uploaded files stay out of Git.

## 📧 New-account notifications

When SMTP is configured, a new account can notify the project owner at absalew1234@gmail.com with the signup name, email, username, stated purpose and creation time.

Configure these environment variables on your server:

    PULSELINK_SECRET_KEY=replace-with-a-long-random-secret
    PULSELINK_DB=pulselink.db
    PULSELINK_OWNER_EMAIL=absalew1234@gmail.com
    PULSELINK_MAX_UPLOAD_MB=25
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
    ├── downloads/
    │   └── .gitkeep
    └── README.md

SQLite creates the application database on first start.

## 🔐 Security notes

- Location sharing requires an explicit button click and browser permission.
- File uploads require manual selection and an Upload action.
- Raw visitor IP addresses are not saved.
- Accounts are isolated by user ID.
- Uploaded files use randomized server-side filenames.
- Dashboard file downloads require authentication and ownership of the tracking link.
- For public deployment, use HTTPS, a strong secret key, persistent storage, backups, rate limiting and a clear privacy notice that matches the actual data practices.

## 📦 Download and use

This repository is public. Anyone can download it from GitHub with **Code → Download ZIP** or by cloning the repository.

Before deploying publicly, configure production secrets and persistent storage. Do not publish database files, uploaded files, passwords, SMTP credentials or other private runtime data.

## 📜 License

PulseLink is released under the MIT License. See [LICENSE](LICENSE).

## 👤 Project

**PulseLink**

Created by **ABSALEW BELAYNEH**

Project owner / notification email: **absalew1234@gmail.com**