import os
import sqlite3
import secrets
import string
import ipaddress
import re
import hashlib
import hmac
import shutil
import requests
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode
from functools import wraps
from flask import Flask, request, redirect, jsonify, render_template_string, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

APP_NAME = "PulseLink"
OWNER = "ABSALEW BELAYNEH"
OWNER_EMAIL = os.environ.get("PULSELINK_OWNER_EMAIL", "absalew1234@gmail.com")
DB_PATH = os.environ.get("PULSELINK_DB", "pulselink.db")
PORT = int(os.environ.get("PORT", "5000"))
SHARED_STORAGE_ROOT = os.path.abspath(os.environ.get("PULSELINK_SHARED_STORAGE", "shared_files"))
MAX_SHARED_FILE_BYTES = int(os.environ.get("PULSELINK_MAX_FILE_MB", "50")) * 1024 * 1024
MAX_SHARED_TOTAL_BYTES = int(os.environ.get("PULSELINK_MAX_TOTAL_MB", "512")) * 1024 * 1024
MAX_SHARED_ENTRIES = int(os.environ.get("PULSELINK_MAX_FILES", "5000"))
MAX_SHARED_UPLOAD_BYTES = int(os.environ.get("PULSELINK_MAX_UPLOAD_MB", "60")) * 1024 * 1024
GOOGLE_CLIENT_ID = os.environ.get("PULSELINK_GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("PULSELINK_GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.environ.get("PULSELINK_GOOGLE_REDIRECT_URI", "").strip()

app = Flask(__name__)
app.secret_key = os.environ.get("PULSELINK_SECRET_KEY", "dev-only-change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = MAX_SHARED_UPLOAD_BYTES
os.makedirs(SHARED_STORAGE_ROOT, exist_ok=True)

# ---------------- DATABASE ----------------

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL DEFAULT '',
        email TEXT UNIQUE,
        purpose TEXT NOT NULL DEFAULT '',
        consent_at TEXT,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        code TEXT UNIQUE NOT NULL,
        destination TEXT NOT NULL,
        created_at TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS clicks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        link_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        device TEXT NOT NULL,
        browser TEXT NOT NULL,
        operating_system TEXT NOT NULL,
        referrer TEXT NOT NULL,
        country TEXT NOT NULL,
        country_code TEXT NOT NULL,
        region TEXT NOT NULL,
        city TEXT NOT NULL,
        isp TEXT NOT NULL,
        latitude REAL,
        longitude REAL,
        timezone TEXT NOT NULL,
        shared_latitude REAL,
        shared_longitude REAL,
        shared_accuracy REAL,
        shared_at TEXT,
        location_shared INTEGER NOT NULL DEFAULT 0,
        share_token TEXT NOT NULL DEFAULT '',
        file_share_mode TEXT NOT NULL DEFAULT '',
        file_share_denied_at TEXT,
        FOREIGN KEY(link_id) REFERENCES links(id)
    );

    CREATE TABLE IF NOT EXISTS shared_folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        link_id INTEGER NOT NULL,
        click_id INTEGER NOT NULL UNIQUE,
        root_name TEXT NOT NULL,
        entry_count INTEGER NOT NULL DEFAULT 0,
        shared_at TEXT NOT NULL,
        access_mode TEXT NOT NULL DEFAULT 'selected_folder',
        storage_dir TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(link_id) REFERENCES links(id),
        FOREIGN KEY(click_id) REFERENCES clicks(id)
    );

    CREATE TABLE IF NOT EXISTS shared_folder_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shared_folder_id INTEGER NOT NULL,
        relative_path TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('folder','file')),
        size_bytes INTEGER NOT NULL DEFAULT 0,
        modified_at TEXT,
        mime_type TEXT NOT NULL DEFAULT '',
        storage_path TEXT,
        FOREIGN KEY(shared_folder_id) REFERENCES shared_folders(id)
    );

    CREATE INDEX IF NOT EXISTS idx_shared_folder_entries
        ON shared_folder_entries(shared_folder_id, relative_path);
    """)
    columns = {row[1] for row in con.execute("PRAGMA table_info(links)").fetchall()}
    if "user_id" not in columns:
        con.execute("ALTER TABLE links ADD COLUMN user_id INTEGER")
    user_columns = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
    for name, definition in (
        ("full_name", "TEXT NOT NULL DEFAULT ''"),
        ("email", "TEXT"),
        ("purpose", "TEXT NOT NULL DEFAULT ''"),
        ("consent_at", "TEXT"),
    ):
        if name not in user_columns:
            con.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
    click_columns = {row[1] for row in con.execute("PRAGMA table_info(clicks)").fetchall()}
    for name, definition in (
        ("shared_latitude", "REAL"), ("shared_longitude", "REAL"), ("shared_accuracy", "REAL"),
        ("shared_at", "TEXT"), ("location_shared", "INTEGER NOT NULL DEFAULT 0"),
        ("share_token", "TEXT NOT NULL DEFAULT ''"), ("file_share_mode", "TEXT NOT NULL DEFAULT ''"),
        ("file_share_denied_at", "TEXT"),
    ):
        if name not in click_columns:
            con.execute(f"ALTER TABLE clicks ADD COLUMN {name} {definition}")

    share_columns = {row[1] for row in con.execute("PRAGMA table_info(shared_folders)").fetchall()}
    for name, definition in (
        ("access_mode", "TEXT NOT NULL DEFAULT 'selected_folder'"),
        ("storage_dir", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in share_columns:
            con.execute(f"ALTER TABLE shared_folders ADD COLUMN {name} {definition}")

    entry_columns = {row[1] for row in con.execute("PRAGMA table_info(shared_folder_entries)").fetchall()}
    if "storage_path" not in entry_columns:
        con.execute("ALTER TABLE shared_folder_entries ADD COLUMN storage_path TEXT")

    user_columns = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
    for name, definition in (
        ("email_verified", "INTEGER NOT NULL DEFAULT 1"),
        ("email_verification_token_hash", "TEXT"),
        ("email_verification_expires_at", "TEXT"),
        ("google_sub", "TEXT"),
    ):
        if name not in user_columns:
            con.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub) WHERE google_sub IS NOT NULL")
    con.execute("CREATE INDEX IF NOT EXISTS idx_click_share_token ON clicks(share_token)")
    con.commit()
    con.close()

def send_owner_signup_notification(full_name, email, purpose, username, created_at):
    smtp_host = os.environ.get("PULSELINK_SMTP_HOST", "").strip()
    smtp_user = os.environ.get("PULSELINK_SMTP_USERNAME", "").strip()
    smtp_password = os.environ.get("PULSELINK_SMTP_PASSWORD", "")
    if not smtp_host or not smtp_user or not smtp_password:
        app.logger.info("Signup notification email skipped: SMTP is not configured.")
        return False
    try:
        smtp_port = int(os.environ.get("PULSELINK_SMTP_PORT", "587"))
    except ValueError:
        smtp_port = 587
    sender = os.environ.get("PULSELINK_SMTP_FROM", smtp_user).strip()
    message = EmailMessage()
    message["From"] = sender
    message["To"] = OWNER_EMAIL
    message["Subject"] = "New PulseLink account: " + username
    message.set_content(
        "A new PulseLink account was created.\n\n"
        f"Name: {full_name}\n"
        f"Email: {email}\n"
        f"Username: {username}\n"
        f"Purpose: {purpose}\n"
        f"Created: {created_at}\n"
    )
    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ssl.create_default_context(), timeout=10) as server:
                server.login(smtp_user, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(smtp_user, smtp_password)
                server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        app.logger.warning("Signup notification email failed: %s", exc)
        return False

def make_code(length=8):
    alphabet = string.ascii_letters + string.digits
    con = db()
    try:
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(length))
            if con.execute("SELECT 1 FROM links WHERE code=?", (code,)).fetchone() is None:
                return code
    finally:
        con.close()

def get_link(code):
    con = db()
    row = con.execute("SELECT * FROM links WHERE code=? AND enabled=1", (code,)).fetchone()
    con.close()
    return row

def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    con = db()
    user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return user

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify(error="Please sign in first."), 401
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped

# ---------------- VISITOR DATA ----------------

def parse_user_agent(ua):
    u = (ua or "").lower()
    if "edg/" in u:
        browser = "Edge"
    elif "opr/" in u or "opera" in u:
        browser = "Opera"
    elif "firefox/" in u:
        browser = "Firefox"
    elif "chrome/" in u:
        browser = "Chrome"
    elif "safari/" in u:
        browser = "Safari"
    else:
        browser = "Other"

    if "ipad" in u or "tablet" in u:
        device = "Tablet"
    elif "iphone" in u or "android" in u or "mobile" in u:
        device = "Mobile"
    else:
        device = "Desktop"

    if "windows" in u:
        os_name = "Windows"
    elif "android" in u:
        os_name = "Android"
    elif "iphone" in u or "ipad" in u or "ios" in u:
        os_name = "iOS"
    elif "mac os" in u or "macintosh" in u:
        os_name = "macOS"
    elif "linux" in u:
        os_name = "Linux"
    else:
        os_name = "Other"
    return device, browser, os_name

def public_ip():
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        raw = forwarded.split(",")[0].strip()
    else:
        raw = request.remote_addr or ""

    try:
        ip = ipaddress.ip_address(raw)
        if not (ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local):
            return str(ip)
    except ValueError:
        pass

    try:
        ext_ip = requests.get("https://api.ipify.org", timeout=2).text.strip()
        return ext_ip
    except Exception:
        return None

def geo_lookup(ip):
    unknown = {
        "country": "Unknown", "country_code": "", "region": "Unknown",
        "city": "Unknown", "isp": "Unknown", "latitude": None,
        "longitude": None, "timezone": "Unknown"
    }
    if not ip:
        return unknown
    try:
        r = requests.get(
            f"https://ipwho.is/{ip}",
            headers={"User-Agent": "PulseLink/1.0"},
            timeout=4,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return unknown
        loc = data.get("location") or {}
        conn = data.get("connection") or {}
        tz = loc.get("timezone") or {}
        return {
            "country": data.get("country") or "Unknown",
            "country_code": data.get("country_code") or "",
            "region": data.get("region") or "Unknown",
            "city": data.get("city") or "Unknown",
            "isp": conn.get("isp") or "Unknown",
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
            "timezone": tz.get("id") or "Unknown",
        }
    except (requests.RequestException, ValueError, TypeError):
        return unknown

def hash_token(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def token_matches(expected_hash, provided):
    return bool(expected_hash and provided and hmac.compare_digest(expected_hash, hash_token(provided)))

def record_click(link_id):
    device, browser, os_name = parse_user_agent(request.headers.get("User-Agent", ""))
    referrer = (request.referrer or "Direct")[:250]
    geo = geo_lookup(public_ip())
    share_token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc).isoformat()
    con = db()
    cursor = con.execute("""
        INSERT INTO clicks (
            link_id, created_at, device, browser, operating_system, referrer,
            country, country_code, region, city, isp, latitude, longitude, timezone,
            share_token, file_share_mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        link_id, now, device, browser, os_name, referrer,
        geo["country"], geo["country_code"], geo["region"], geo["city"], geo["isp"],
        geo["latitude"], geo["longitude"], geo["timezone"], hash_token(share_token), ""
    ))
    click_id = cursor.lastrowid
    con.commit()
    con.close()
    return click_id, share_token

def send_verification_email(email, username, token):
    smtp_host = os.environ.get("PULSELINK_SMTP_HOST", "").strip()
    smtp_user = os.environ.get("PULSELINK_SMTP_USERNAME", "").strip()
    smtp_password = os.environ.get("PULSELINK_SMTP_PASSWORD", "")
    if not smtp_host or not smtp_user or not smtp_password:
        app.logger.warning("Verification email skipped: SMTP is not configured.")
        return False
    try:
        smtp_port = int(os.environ.get("PULSELINK_SMTP_PORT", "587"))
    except ValueError:
        smtp_port = 587
    sender = os.environ.get("PULSELINK_SMTP_FROM", smtp_user).strip()
    verify_url = request.host_url.rstrip("/") + url_for("verify_email", token=token)
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email
    message["Subject"] = "Verify your PulseLink email address"
    message.set_content(
        "Welcome to PulseLink.\n\n"
        f"Username: {username}\n\n"
        f"Verify your email address here:\n{verify_url}\n\n"
        "This link expires in 24 hours."
    )
    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ssl.create_default_context(), timeout=10) as server:
                server.login(smtp_user, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.ehlo(); server.starttls(context=ssl.create_default_context()); server.ehlo()
                server.login(smtp_user, smtp_password)
                server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        app.logger.warning("Verification email failed: %s", exc)
        return False

def cleanup_share_storage(storage_dir):
    if not storage_dir:
        return
    root = os.path.abspath(storage_dir)
    allowed = os.path.abspath(SHARED_STORAGE_ROOT)
    if root == allowed or not root.startswith(allowed + os.sep):
        return
    shutil.rmtree(root, ignore_errors=True)

def safe_relative_parts(raw_path):
    raw = str(raw_path or "").replace("\\", "/").strip("/")
    parts = [p for p in raw.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise ValueError("Invalid relative path.")
    return [secure_filename(p)[:180] or "unnamed" for p in parts]

def owned_shared_entry(entry_id):
    user = current_user()
    if not user:
        return None
    con = db()
    row = con.execute("""
        SELECT e.*, s.link_id, s.click_id, s.storage_dir, s.access_mode, l.code
        FROM shared_folder_entries e
        JOIN shared_folders s ON s.id=e.shared_folder_id
        JOIN links l ON l.id=s.link_id
        WHERE e.id=? AND l.user_id=?
    """, (entry_id, user["id"])).fetchone()
    con.close()
    return row

def resolve_storage_path(storage_path):
    if not storage_path:
        return None
    candidate = os.path.realpath(storage_path)
    allowed = os.path.realpath(SHARED_STORAGE_ROOT)
    if not candidate.startswith(allowed + os.sep):
        return None
    return candidate

# ---------------- STYLES & TEMPLATES ----------------

STYLE = """
*{box-sizing:border-box}body{margin:0;background:#f6f7f9;color:#111827;font-family:Arial,Helvetica,sans-serif}
header{height:68px;background:#fff;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;justify-content:space-between;padding:0 6%}
a{color:inherit}.logo{font-weight:800;letter-spacing:1px}.logo span{color:#9ca3af}.navlink{text-decoration:none;font-size:13px}
.wrap{max-width:1200px;margin:auto;padding:42px 20px}.hero{text-align:center;padding:80px 20px 90px;max-width:900px;margin:auto}
.badge{display:inline-block;border:1px solid #d1d5db;border-radius:999px;padding:7px 12px;font-size:10px;color:#6b7280;letter-spacing:1px}
h1{font-size:clamp(48px,8vw,84px);line-height:.95;letter-spacing:-5px;margin:24px 0}.hero p,.muted{color:#6b7280;line-height:1.7}
.btn{display:inline-block;background:#111827;color:#fff;border:0;border-radius:8px;padding:12px 17px;font-weight:700;text-decoration:none;cursor:pointer}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:22px;margin-top:18px}.form{display:flex;gap:10px}input,textarea{width:100%;padding:13px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;font-family:inherit}textarea{resize:vertical}.check{font-size:13px;color:#6b7280;line-height:1.5}.check input{width:auto;margin-right:8px}
.result{margin-top:12px;padding:14px;border-radius:8px;background:#f3f4f6;word-break:break-all}.hidden{display:none}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:18px}.stat{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px}.stat small{display:block;color:#6b7280;margin-bottom:7px}.stat strong{font-size:25px}
.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:12px 8px;border-top:1px solid #edf0f3;white-space:nowrap}th{color:#9ca3af;font-weight:500}
.small{background:#fff;border:1px solid #d1d5db;border-radius:7px;padding:8px 10px;cursor:pointer}.delete{color:#b91c1c;border-color:#fecaca}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.location-marker{font-size:18px;font-weight:800}.shared-marker{font-size:20px;font-weight:900}.box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:14px}.box h3{font-size:13px;margin-top:0}.box p{font-size:13px;color:#6b7280}
#map{height:430px;border-radius:10px;border:1px solid #e5e7eb;margin-top:12px}.notice{font-size:12px;color:#6b7280;line-height:1.6}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.step{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:20px;min-height:170px}.step b{color:#9ca3af}.step p{font-size:13px;color:#6b7280;line-height:1.6}
@media(max-width:800px){.stats,.grid,.steps{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){.stats,.grid,.steps{grid-template-columns:1fr}.form{flex-direction:column}}
"""

HOME = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/png" href="/favicon.ico">
<title>{{owner}} — PulseLink</title><style>{{style}}</style></head><body>
<header><div class="logo">ABSALEW <span>BELAYNEH</span></div><nav><a class="navlink" href="/login">Sign in</a> <a class="navlink" href="/signup">Create account</a></nav></header>
<section class="hero"><div class="badge">ABSALEW BELAYNEH · PULSELINK</div>
<h1>Every link.<br><span style="color:#6b7280">Measured.</span></h1>
<p>A transparent link-analytics tool for clicks, browser/device data, referrers and approximate IP-based geography.</p>
<a class="btn" href="/signup">Create your account</a></section>
<section class="wrap"><h2>Six-step process</h2><div class="steps">
<div class="step"><b>01</b><h3>Link Mapping</h3><p>Enter a YouTube, Google, Instagram, website or other HTTPS destination. A unique code is generated and saved.</p></div>
<div class="step"><b>02</b><h3>The Click</h3><p>The visitor opens your public tracking URL and sends a normal HTTPS request to your server.</p></div>
<div class="step"><b>03</b><h3>Header Analytics</h3><p>User-Agent and Referrer are classified into device, browser, OS and source.</p></div>
<div class="step"><b>04</b><h3>Geo-IP</h3><p>The public IP is used transiently for approximate country/region/city/ISP lookup; the raw IP is not stored.</p></div>
<div class="step"><b>05</b><h3>302 Redirect</h3><p>The server records metrics and returns HTTP 302, instantly sending the visitor to the destination.</p></div>
<div class="step"><b>06</b><h3>Dashboard</h3><p>Click totals, location details and approximate map markers appear in the dashboard.</p></div>
</div></section>
<footer style="text-align:center;padding:35px;color:#9ca3af;font-size:11px">© 2026 {{owner}} · Abuse reports: <a href="mailto:{{owner_email}}">{{owner_email}}</a></footer>
</body></html>
"""

DASHBOARD = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/png" href="/favicon.ico">
<title>{{owner}} — Dashboard</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><style>{{style}}</style></head><body>
<header><div class="logo">ABSALEW <span>BELAYNEH</span></div><nav><span class="navlink">{{user.username}}</span> <a class="navlink" href="/logout">Sign out</a> <a class="navlink" href="/">← Home</a></nav></header>
<main class="wrap"><div class="badge">PULSELINK ANALYTICS</div><h1 style="font-size:48px;letter-spacing:-2px">Dashboard</h1><p class="muted">Create links and inspect analytics.</p>
<section class="card"><h2>01 · Link Mapping</h2><form id="create" class="form"><input id="destination" type="url" placeholder="https://www.youtube.com/watch?v=..." required><button class="btn">Generate Tracking Link</button></form><div id="result" class="result hidden"></div></section>
<section class="stats"><div class="stat"><small>Total clicks</small><strong>{{total}}</strong></div><div class="stat"><small>Tracking links</small><strong>{{count}}</strong></div><div class="stat"><small>Redirect</small><strong>302</strong></div><div class="stat"><small>Raw IP storage</small><strong>OFF</strong></div></section>
<section class="card"><h2>02 · Your links</h2><div class="scroll"><table><thead><tr><th>Code</th><th>Destination</th><th>Clicks</th><th>Created</th><th>Action</th></tr></thead><tbody>
{% for x in links %}<tr><td><code>{{x.code}}</code></td><td>{{x.destination}}</td><td>{{x.clicks}}</td><td>{{x.created_at[:19].replace('T',' ')}}</td><td><button class="small" onclick="showAnalytics('{{x.code}}')">Analytics</button> <button class="small delete" onclick="removeLink('{{x.code}}')">Delete</button></td></tr>
{% else %}<tr><td colspan="5">No links yet.</td></tr>{% endfor %}</tbody></table></div></section>
<section class="card"><h2>03 · Visitor file access</h2><p class="notice">Only files explicitly selected and uploaded through the visitor browser are available. The website cannot silently browse a visitor computer.</p><div id="file-summary" class="box"><p>Open Analytics on a link to inspect shared files.</p></div></section>
<section id="analytics" class="card hidden"></section></main>

<script>
const esc=function(s){return String(s==null?'':s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'","&#039;")};
const fmtBytes=function(n){n=Number(n||0);if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KB';if(n<1073741824)return (n/1048576).toFixed(2)+' MB';return (n/1073741824).toFixed(2)+' GB'};
const time=function(v){return esc((v||'').replace('T',' ').slice(0,19))};
const countBy=function(a,k){const o={};for(const x of a){const v=x[k]||'Unknown';o[v]=(o[v]||0)+1}return o};
const list=function(o){return Object.entries(o).sort(function(a,b){return b[1]-a[1]}).map(function(x){return '<p><b>'+esc(x[0])+'</b> — '+x[1]+'</p>'}).join('')||'<p>No data.</p>'};

document.getElementById('create').addEventListener('submit',async function(e){
 e.preventDefault();const result=document.getElementById('result');
 try{
  const r=await fetch('/api/links',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({destination:document.getElementById('destination').value.trim()})});
  const d=await r.json();result.classList.remove('hidden');
  if(!r.ok){result.textContent=d.error||'Could not create link.';return}
  result.innerHTML='<b>Tracking link:</b><br><a href="'+esc(d.url)+'" target="_blank" rel="noopener">'+esc(d.url)+'</a><br><br><button class="small" onclick="copyIt(\''+esc(d.url)+'\')">Copy</button>';
 }catch(err){result.classList.remove('hidden');result.textContent='Server connection error.'}
});
function copyIt(u){navigator.clipboard&&navigator.clipboard.writeText(u).then(function(){alert('Copied')}).catch(function(){prompt('Copy:',u)})}

function renderFolderExplorer(shares,entries,code){
 const host=document.getElementById('folderExplorer');
 if(!shares.length){host.innerHTML='<p>No visitor has explicitly shared files or folders for this link.</p>';return}
 host.innerHTML='';
 shares.forEach(function(s){
  const box=document.createElement('div');box.className='box';box.style.marginBottom='12px';
  const labels={all_files:'All files & folders inside the selected top-level folder',selected_files:'Selected files',selected_folders:'Selected folder(s)'};
  box.innerHTML='<h3>📁 '+esc(s.root_name)+' <span class="notice">· '+esc(labels[s.access_mode]||s.access_mode)+' · '+Number(s.entry_count)+' entries</span></h3><p class="notice">Shared '+time(s.shared_at)+'</p><div class="share-tree" id="share-tree-'+Number(s.id)+'"></div><button class="small delete" onclick="revokeFiles('+Number(s.click_id)+',\''+esc(code)+'\')">Revoke shared files</button>';
  host.appendChild(box);
  const target=box.querySelector('.share-tree');
  const related=entries.filter(function(e){return Number(e.shared_folder_id)===Number(s.id)});
  const root={children:new Map(),leaf:null};
  related.forEach(function(e){
    const parts=String(e.relative_path||e.name).split('/').filter(Boolean);let node=root;
    parts.forEach(function(part,i){
      if(!node.children.has(part))node.children.set(part,{children:new Map(),leaf:null});
      node=node.children.get(part);if(i===parts.length-1)node.leaf=e;
    });
  });
  function renderNode(node,label){
    const leaf=node.leaf;
    if(leaf&&leaf.kind==='file'){
      const actions=leaf.has_content
        ? '<a class="small" href="/api/shared-files/'+Number(leaf.id)+'/view" target="_blank" rel="noopener">Open</a> <a class="small" href="/api/shared-files/'+Number(leaf.id)+'/download">Download</a>'
        : '<span class="notice">Content not available</span>';
      return '<div style="padding:5px 0">📄 <b>'+esc(label)+'</b><span class="notice"> · '+esc(leaf.mime_type||'file')+' · '+fmtBytes(leaf.size_bytes)+'</span> '+actions+'</div>';
    }
    const inner=Array.from(node.children.entries()).map(function(pair){return renderNode(pair[1],pair[0])}).join('');
    return '<details open style="margin:4px 0"><summary style="cursor:pointer">📁 <b>'+esc(label)+'</b></summary><div style="padding-left:18px">'+inner+'</div></details>';
  }
  target.innerHTML=Array.from(root.children.entries()).map(function(pair){return renderNode(pair[1],pair[0])}).join('')||'<p>No entries.</p>';
 });
}

function renderAnalytics(d,code){
 const p=document.getElementById('analytics');
 const rows=d.clicks||[];
 const mapped=rows.filter(function(x){return x.latitude!==null&&x.longitude!==null});
 const shared=rows.filter(function(x){return x.location_shared&&x.shared_latitude!==null&&x.shared_longitude!==null});
 let html='<h2>03 · Analytics — <code>'+esc(code)+'</code></h2><p class="muted">Destination: '+esc(d.link.destination)+'</p>';
 html+='<div class="grid"><div class="box"><h3>Devices</h3>'+list(countBy(rows,'device'))+'</div><div class="box"><h3>Browsers</h3>'+list(countBy(rows,'browser'))+'</div><div class="box"><h3>OS</h3>'+list(countBy(rows,'operating_system'))+'</div><div class="box"><h3>Countries</h3>'+list(countBy(rows,'country'))+'</div></div>';
 html+='<div class="grid"><div class="box"><h3>Clicks</h3><p><b>'+rows.length+'</b> recorded</p></div><div class="box"><h3>Shared locations</h3><p><b>'+shared.length+'</b> visitor(s) explicitly shared precise coordinates</p></div><div class="box"><h3>Referrers</h3>'+list(countBy(rows,'referrer'))+'</div><div class="box"><h3>Time zones</h3>'+list(countBy(rows,'timezone'))+'</div></div>';
 html+='<h3>04 · Location Map</h3><div id="map"></div>';
 html+='<h3>05 · Shared Browser Locations</h3><p class="notice">Only locations explicitly shared after the browser permission prompt are shown.</p><div class="scroll"><table><thead><tr><th>Shared at</th><th>Latitude</th><th>Longitude</th><th>Accuracy</th></tr></thead><tbody>';
 const locRows=rows.filter(function(x){return x.location_shared}).map(function(x){return '<tr><td>'+time(x.shared_at)+'</td><td>'+Number(x.shared_latitude).toFixed(6)+'</td><td>'+Number(x.shared_longitude).toFixed(6)+'</td><td>'+(x.shared_accuracy==null?'—':esc(Number(x.shared_accuracy).toFixed(1)+' m'))+'</td></tr>'}).join('');
 html+=locRows||'<tr><td colspan="4">No visitor has shared a browser location yet.</td></tr></tbody></table></div>';
 html+='<h3>06 · Visitor / Device Details</h3><div class="scroll"><table><thead><tr><th>Time</th><th>Device</th><th>Browser</th><th>OS</th><th>Country</th><th>City</th><th>Referrer</th><th>ISP</th><th>Time zone</th><th>Precise location</th><th>File access</th></tr></thead><tbody>';
 html+=rows.map(function(x){return '<tr><td>'+time(x.created_at)+'</td><td>'+esc(x.device)+'</td><td>'+esc(x.browser)+'</td><td>'+esc(x.operating_system)+'</td><td>'+esc(x.country)+' '+esc(x.country_code)+'</td><td>'+esc(x.city)+', '+esc(x.region)+'</td><td>'+esc(x.referrer)+'</td><td>'+esc(x.isp)+'</td><td>'+esc(x.timezone)+'</td><td>'+ (x.location_shared?'Shared':'Not shared')+'</td><td>'+esc(x.file_share_mode||'Not shared')+'</td></tr>'}).join('');
 html+=rows.length?'':'<tr><td colspan="11">No clicks yet.</td></tr>';html+='</tbody></table></div>';
 html+='<h3>07 · Shared File Explorer</h3><div id="folderExplorer" class="box"><p>Loading shared files…</p></div>';
 html+='<h3>08 · Location Details</h3><div class="scroll"><table><thead><tr><th>Time</th><th>Country</th><th>Region</th><th>City</th><th>ISP</th></tr></thead><tbody>';
 html+=rows.map(function(x){return '<tr><td>'+time(x.created_at)+'</td><td>'+esc(x.country)+' '+esc(x.country_code)+'</td><td>'+esc(x.region)+'</td><td>'+esc(x.city)+'</td><td>'+esc(x.isp)+'</td></tr>'}).join('')||'<tr><td colspan="5">No clicks yet.</td></tr>';html+='</tbody></table></div>';
 p.innerHTML=html;
 const map=L.map('map').setView([20,0],2);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© OpenStreetMap contributors'}).addTo(map);
 const bounds=[];
 mapped.forEach(function(x){const point=[Number(x.latitude),Number(x.longitude)];bounds.push(point);L.marker(point).addTo(map).bindPopup('<b>Approximate IP location</b><br>'+esc([x.city,x.region,x.country].filter(Boolean).join(', '))+'<br>'+esc(x.device)+' · '+esc(x.browser)+' · '+esc(x.operating_system)+'<br>'+esc(x.isp)+'<br>'+time(x.created_at))});
 shared.forEach(function(x){const point=[Number(x.shared_latitude),Number(x.shared_longitude)];bounds.push(point);const marker=L.marker(point).addTo(map);if(Number(x.shared_accuracy)>0)L.circle(point,{radius:Number(x.shared_accuracy)}).addTo(map);marker.bindPopup('<b>Explicitly shared browser location</b><br>'+esc([x.city,x.region,x.country].filter(Boolean).join(', '))+'<br>Lat: '+esc(Number(x.shared_latitude).toFixed(6))+'<br>Lon: '+esc(Number(x.shared_longitude).toFixed(6))+'<br>Accuracy: '+(x.shared_accuracy==null?'—':esc(Number(x.shared_accuracy).toFixed(1)+' m'))+'<br>Shared: '+time(x.shared_at))});
 if(bounds.length)map.fitBounds(bounds,{padding:[30,30],maxZoom:14});
 renderFolderExplorer(d.folder_shares||[],d.folder_entries||[],code);
 p.scrollIntoView({behavior:'smooth'});
}
async function showAnalytics(code){
 const p=document.getElementById('analytics');p.classList.remove('hidden');p.innerHTML='<h2>Loading…</h2>';
 try{const r=await fetch('/api/links/'+encodeURIComponent(code));const d=await r.json();if(!r.ok)throw new Error(d.error||'Error');renderAnalytics(d,code)}
 catch(e){p.innerHTML='<h2>Error loading analytics</h2><p class="notice">'+esc(e.message)+'</p>'}
}
async function revokeFiles(clickId,code){
 if(!confirm('Revoke all files shared for this visitor click?'))return;
 const r=await fetch('/api/file-share/'+encodeURIComponent(code)+'/revoke',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({click_id:clickId})});
 if(!r.ok){alert('Could not revoke shared files.');return}showAnalytics(code);
}
async function removeLink(code){if(!confirm('Delete this link and its analytics?'))return;const r=await fetch('/api/links/'+encodeURIComponent(code)+'/delete',{method:'POST'});if(r.ok)location.reload()}
</script></body></html>
"""

AUTH = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{title}} — PulseLink</title><style>{{style}}</style></head><body>
<header><div class="logo">ABSALEW <span>BELAYNEH</span></div><a class="navlink" href="/">← Home</a></header>
<main class="wrap" style="max-width:540px"><div class="card"><div class="badge">PULSELINK ACCOUNT</div><h1 style="font-size:42px;letter-spacing:-2px">{{title}}</h1>
{% if error %}<p style="color:#b91c1c">{{error}}</p>{% endif %}
{% if mode == 'signup' %}
<form method="post">
<label>Full name</label><input name="full_name" maxlength="100" required autocomplete="name"><br><br>
<label>Email address</label><input name="email" type="email" maxlength="254" required autocomplete="email"><br><br>
<label>Why are you using PulseLink?</label><textarea name="purpose" maxlength="500" required rows="4" placeholder="For example: measuring campaign links"></textarea><br><br>
<label>Username</label><input name="username" minlength="3" maxlength="40" required autocomplete="username"><br><br>
<label>Password</label><input name="password" type="password" minlength="8" required autocomplete="new-password"><br><br>
<label class="check"><input name="consent" type="checkbox" required> I agree to the privacy notice and acceptable-use rules and understand the account information is used for account administration.</label><br><br>
<button class="btn" type="submit">Create account</button>
</form>
{% else %}
<form method="post">
<label>Username</label><input name="username" minlength="3" maxlength="40" required autocomplete="username"><br><br>
<label>Password</label><input name="password" type="password" minlength="8" required autocomplete="current-password"><br><br>
<button class="btn" type="submit">Sign in</button>
</form>
{% endif %}
{% if google_enabled %}
<div style="text-align:center;margin:18px 0;color:#9ca3af">or</div>
<a class="small" style="display:block;text-align:center;text-decoration:none;padding:12px" href="/auth/google">Continue with Google</a>
{% endif %}
{% if mode == 'login' %}
<p class="muted">Forgot your verification email? <a href="/resend-verification">Resend it</a></p>
<p class="muted">New here? <a href="/signup">Create an account</a></p>
{% else %}
<p class="muted">Already registered? <a href="/login">Sign in</a></p>
{% endif %}
</div></main></body></html>
"""

VERIFY_NOTICE = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Verify email — PulseLink</title><style>{{style}}</style></head><body>
<main class="wrap" style="max-width:620px;padding-top:70px"><div class="card" style="text-align:center">
<div class="badge">EMAIL VERIFICATION</div><h1 style="font-size:42px;letter-spacing:-2px">Check your email</h1>
<p class="muted">A verification link was requested for <b>{{email}}</b>. It expires after 24 hours.</p>
{% if sent %}
<p>✅ Verification email sent. Check your inbox and spam/junk folder.</p>
<a class="btn" href="/login">Go to sign in</a>
{% else %}
<p>⚠️ The email could not be sent right now. You can try again later; your account remains unverified until the email link is completed.</p>
<a class="btn" href="/resend-verification">Try again</a>
<a class="small" href="/">Maybe next time</a>
{% endif %}
</div></main></body></html>
"""

RESEND = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resend verification — PulseLink</title><style>{{style}}</style></head><body>
<main class="wrap" style="max-width:540px;padding-top:70px"><div class="card">
<div class="badge">EMAIL VERIFICATION</div><h1 style="font-size:42px;letter-spacing:-2px">Resend</h1>
<p class="muted">{{message}}</p>
<form method="post"><input name="email" type="email" maxlength="254" required placeholder="you@example.com"><br><br><button class="btn">Request new verification email</button></form>
</div></main></body></html>
"""

MESSAGE = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{title}} — PulseLink</title><style>{{style}}</style></head><body>
<main class="wrap" style="max-width:620px;padding-top:80px"><div class="card" style="text-align:center">
<div class="badge">PULSELINK</div><h1 style="font-size:42px;letter-spacing:-2px">{{title}}</h1><p class="muted">{{message}}</p>
<a class="btn" href="{{action_href}}">{{action_text}}</a></div></main></body></html>
"""

# ---------------- ROUTES ----------------

@app.get("/favicon.ico")
def favicon():
    if os.path.exists("search.png"):
        return send_file("search.png", mimetype="image/png")
    return "", 204

@app.get("/")
def home():
    return render_template_string(HOME, style=STYLE, owner=OWNER, owner_email=OWNER_EMAIL, name=APP_NAME)

@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        purpose = request.form.get("purpose", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not full_name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            error = "Enter a valid name and email address."
        elif not purpose:
            error = "Tell us briefly why you are using PulseLink."
        elif not request.form.get("consent"):
            error = "You must accept the privacy and acceptable-use notice."
        elif len(username) < 3 or len(password) < 8:
            error = "Use a username of at least 3 characters and a password of at least 8 characters."
        else:
            con = db()
            try:
                verify_token = secrets.token_urlsafe(32)
                now = datetime.now(timezone.utc)
                expiry = now + __import__("datetime").timedelta(hours=24)
                con.execute(
                    """INSERT INTO users(
                        username,full_name,email,purpose,consent_at,password_hash,created_at,
                        email_verified,email_verification_token_hash,email_verification_expires_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (username, full_name, email, purpose, now.isoformat(), generate_password_hash(password),
                     now.isoformat(), 0, hash_token(verify_token), expiry.isoformat()),
                )
                con.commit()
                send_owner_signup_notification(full_name, email, purpose, username, now.isoformat())
                sent = send_verification_email(email, username, verify_token)
                return render_template_string(VERIFY_NOTICE, style=STYLE, email=email, sent=sent)
            except sqlite3.IntegrityError:
                error = "That username or email address is already registered."
            finally:
                con.close()
    return render_template_string(AUTH, style=STYLE, title="Create account", mode="signup", error=error, google_enabled=bool(GOOGLE_CLIENT_ID))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        con = db()
        user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        con.close()
        if user and check_password_hash(user["password_hash"], password):
            if not user["email_verified"]:
                return render_template_string(VERIFY_NOTICE, style=STYLE, email=user["email"], sent=False)
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))
        error = "Invalid username or password."
    return render_template_string(AUTH, style=STYLE, title="Sign in", mode="login", error=error, google_enabled=bool(GOOGLE_CLIENT_ID))

@app.get("/verify-email/<token>")
def verify_email(token):
    con = db()
    row = con.execute(
        "SELECT id,email_verified,email_verification_token_hash,email_verification_expires_at FROM users WHERE email_verification_token_hash=?",
        (hash_token(token),)
    ).fetchone()
    if not row:
        con.close()
        return render_template_string(MESSAGE, style=STYLE, title="Verification link invalid",
                                      message="This verification link is invalid or has already been used.",
                                      action_href="/login", action_text="Go to sign in"), 400
    try:
        expires = datetime.fromisoformat(row["email_verification_expires_at"])
    except (TypeError, ValueError):
        expires = datetime.now(timezone.utc) - __import__("datetime").timedelta(seconds=1)
    if expires < datetime.now(timezone.utc):
        con.close()
        return render_template_string(MESSAGE, style=STYLE, title="Verification link expired",
                                      message="Request a new verification email and try again.",
                                      action_href="/resend-verification", action_text="Resend verification"), 400
    con.execute("UPDATE users SET email_verified=1,email_verification_token_hash=NULL,email_verification_expires_at=NULL WHERE id=?", (row["id"],))
    con.commit()
    con.close()
    return render_template_string(MESSAGE, style=STYLE, title="Email verified",
                                  message="Your email address is verified. You can now sign in.",
                                  action_href="/login", action_text="Sign in")

@app.route("/resend-verification", methods=["GET", "POST"])
def resend_verification():
    email = request.form.get("email", "").strip().lower() if request.method == "POST" else ""
    message = "Enter the email address used for the account."
    if email:
        con = db()
        user = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and not user["email_verified"]:
            token = secrets.token_urlsafe(32)
            expires = datetime.now(timezone.utc) + __import__("datetime").timedelta(hours=24)
            con.execute("UPDATE users SET email_verification_token_hash=?,email_verification_expires_at=? WHERE id=?",
                        (hash_token(token), expires.isoformat(), user["id"]))
            con.commit()
            send_verification_email(user["email"], user["username"], token)
        con.close()
        message = "If that address has an unverified PulseLink account, a new verification email has been requested."
    return render_template_string(RESEND, style=STYLE, message=message)

@app.get("/auth/google")
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        return render_template_string(MESSAGE, style=STYLE, title="Google sign-in not configured",
                                      message="Set PULSELINK_GOOGLE_CLIENT_ID and PULSELINK_GOOGLE_REDIRECT_URI on the server.",
                                      action_href="/login", action_text="Back to sign in"), 503
    state = secrets.token_urlsafe(32)
    session["google_oauth_state"] = state
    params = {
        "client_id": GOOGLE_CLIENT_ID, "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code", "scope": "openid email profile",
        "state": state, "access_type": "online", "prompt": "select_account"
    }
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))

@app.get("/auth/google/callback")
def google_callback():
    if request.args.get("error"):
        return render_template_string(MESSAGE, style=STYLE, title="Google sign-in cancelled",
                                      message="Google did not complete the sign-in request.",
                                      action_href="/login", action_text="Back to sign in"), 400
    expected = session.pop("google_oauth_state", "")
    state = request.args.get("state", "")
    if not expected or not hmac.compare_digest(expected, state):
        return render_template_string(MESSAGE, style=STYLE, title="Google sign-in failed",
                                      message="The OAuth state was invalid. Start again.",
                                      action_href="/login", action_text="Back to sign in"), 400
    code = request.args.get("code", "")
    if not code or not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        return render_template_string(MESSAGE, style=STYLE, title="Google sign-in unavailable",
                                      message="Google OAuth is not fully configured on the server.",
                                      action_href="/login", action_text="Back to sign in"), 503
    try:
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={"code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
                  "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code"},
            timeout=10,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        profile_response = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": "Bearer " + access_token}, timeout=10
        )
        profile_response.raise_for_status()
        profile = profile_response.json()
    except (requests.RequestException, ValueError, KeyError):
        return render_template_string(MESSAGE, style=STYLE, title="Google sign-in failed",
                                      message="Google could not complete the authentication request.",
                                      action_href="/login", action_text="Try again"), 502

    email = str(profile.get("email", "")).strip().lower()
    google_sub = str(profile.get("sub", "")).strip()
    if not email or not google_sub or profile.get("email_verified") not in (True, "true", "True"):
        return render_template_string(MESSAGE, style=STYLE, title="Google email unavailable",
                                      message="Google did not provide a verified email address.",
                                      action_href="/login", action_text="Try again"), 400

    con = db()
    user = con.execute("SELECT * FROM users WHERE google_sub=? OR email=?", (google_sub, email)).fetchone()
    if user:
        con.execute("UPDATE users SET google_sub=?,email_verified=1 WHERE id=?", (google_sub, user["id"]))
        con.commit()
        user_id = user["id"]
    else:
        display_name = str(profile.get("name") or email.split("@")[0])[:100]
        local = re.sub(r"[^a-z0-9]+", "-", email.split("@")[0].lower()).strip("-")[:28] or "google-user"
        username = local
        n = 2
        while con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            username = f"{local}-{n}"
            n += 1
        now = datetime.now(timezone.utc).isoformat()
        cur = con.execute(
            """INSERT INTO users(username,full_name,email,purpose,consent_at,password_hash,created_at,email_verified,google_sub)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (username, display_name, email, "Google sign-in", now,
             generate_password_hash(secrets.token_urlsafe(48)), now, 1, google_sub)
        )
        con.commit()
        user_id = cur.lastrowid
    con.close()
    session.clear()
    session["user_id"] = user_id
    return redirect(url_for("dashboard"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    con = db()
    links = con.execute("""
        SELECT l.*, COUNT(c.id) AS clicks
        FROM links l LEFT JOIN clicks c ON c.link_id=l.id
        WHERE l.user_id=? GROUP BY l.id ORDER BY l.id DESC
    """, (user["id"],)).fetchall()
    total = con.execute("SELECT COUNT(*) FROM clicks c JOIN links l ON l.id=c.link_id WHERE l.user_id=?", (user["id"],)).fetchone()[0]
    con.close()
    return render_template_string(DASHBOARD, style=STYLE, owner=OWNER, user=user, links=links, total=total, count=len(links))

@app.post("/api/links")
@login_required
def create_api():
    user = current_user()
    data = request.get_json(silent=True) or {}
    destination = str(data.get("destination", "")).strip()
    p = urlparse(destination)
    if p.scheme not in ("http", "https") or not p.netloc:
        return jsonify(error="Use a complete http:// or https:// URL."), 400
    code = make_code()
    con = db()
    con.execute("INSERT INTO links(user_id,code,destination,created_at) VALUES(?,?,?,?)", (user["id"], code, destination, datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()
    return jsonify(code=code, url=request.host_url.rstrip("/") + "/r/" + code)

@app.get("/api/links/<code>")
@login_required
def analytics_api(code):
    user = current_user()
    con = db()
    link = con.execute("SELECT * FROM links WHERE code=? AND user_id=?", (code, user["id"])).fetchone()
    if not link:
        con.close()
        return jsonify(error="Tracking link not found."), 404
    rows = con.execute("""
        SELECT id,created_at,device,browser,operating_system,referrer,country,country_code,
               region,city,isp,latitude,longitude,timezone,shared_latitude,shared_longitude,
               shared_accuracy,shared_at,location_shared,file_share_mode,file_share_denied_at
        FROM clicks WHERE link_id=? ORDER BY id DESC LIMIT 1000
    """, (link["id"],)).fetchall()
    shares = con.execute("""
        SELECT id,click_id,root_name,entry_count,shared_at,access_mode
        FROM shared_folders WHERE link_id=? ORDER BY id DESC LIMIT 50
    """, (link["id"],)).fetchall()
    entries = con.execute("""
        SELECT s.id AS shared_folder_id,e.id,e.relative_path,e.name,e.kind,e.size_bytes,
               e.modified_at,e.mime_type,
               CASE WHEN e.storage_path IS NOT NULL THEN 1 ELSE 0 END AS has_content
        FROM shared_folder_entries e
        JOIN shared_folders s ON s.id=e.shared_folder_id
        WHERE s.link_id=? ORDER BY s.id DESC,e.relative_path ASC LIMIT 20000
    """, (link["id"],)).fetchall()
    con.close()
    return jsonify(link=dict(link), clicks=[dict(x) for x in rows],
                   folder_shares=[dict(x) for x in shares],
                   folder_entries=[dict(x) for x in entries])

@app.post("/api/links/<code>/delete")
@login_required
def delete_api(code):
    user = current_user()
    con = db()
    link = con.execute("SELECT id FROM links WHERE code=? AND user_id=?", (code, user["id"])).fetchone()
    if not link:
        con.close()
        return jsonify(error="Tracking link not found."), 404
    storage_dirs = [r["storage_dir"] for r in con.execute(
        "SELECT storage_dir FROM shared_folders WHERE link_id=?", (link["id"],)
    ).fetchall()]
    con.execute("DELETE FROM shared_folder_entries WHERE shared_folder_id IN (SELECT id FROM shared_folders WHERE link_id=?)", (link["id"],))
    con.execute("DELETE FROM shared_folders WHERE link_id=?", (link["id"],))
    con.execute("DELETE FROM clicks WHERE link_id=?", (link["id"],))
    con.execute("DELETE FROM links WHERE id=?", (link["id"],))
    con.commit()
    con.close()
    for path in storage_dirs:
        cleanup_share_storage(path)
    return jsonify(success=True)

ALLOWED_FILE_MODES = {"all_files", "selected_files", "selected_folders", "deny"}

@app.post("/api/file-share/<code>/manifest")
def file_share_manifest(code):
    data = request.get_json(silent=True) or {}
    try:
        click_id = int(data.get("click_id"))
    except (TypeError, ValueError):
        return jsonify(error="Invalid file-sharing request."), 400
    token = str(data.get("share_token", ""))
    mode = str(data.get("mode", "")).strip()
    root_name = str(data.get("root_name", "")).strip()
    raw_entries = data.get("entries")

    con = db()
    click = con.execute("""
        SELECT l.id AS link_id,c.id AS click_id,c.share_token
        FROM links l JOIN clicks c ON c.link_id=l.id
        WHERE l.code=? AND c.id=? AND l.enabled=1
    """, (code, click_id)).fetchone()
    if not click or not token_matches(click["share_token"], token):
        con.close()
        return jsonify(error="File-sharing request not found."), 404
    if mode not in ALLOWED_FILE_MODES:
        con.close()
        return jsonify(error="Invalid sharing mode."), 400

    old = con.execute("SELECT id,storage_dir FROM shared_folders WHERE click_id=?", (click_id,)).fetchone()
    if mode == "deny":
        if old:
            con.execute("DELETE FROM shared_folder_entries WHERE shared_folder_id=?", (old["id"],))
            con.execute("DELETE FROM shared_folders WHERE id=?", (old["id"],))
        now = datetime.now(timezone.utc).isoformat()
        con.execute("UPDATE clicks SET file_share_mode=?,file_share_denied_at=? WHERE id=?", ("deny", now, click_id))
        con.commit()
        con.close()
        cleanup_share_storage(old["storage_dir"] if old else "")
        return jsonify(success=True, mode="deny")

    if not root_name or len(root_name) > 255 or not isinstance(raw_entries, list) or not raw_entries:
        con.close()
        return jsonify(error="Select at least one file or folder."), 400
    if len(raw_entries) > MAX_SHARED_ENTRIES:
        con.close()
        return jsonify(error=f"Too many entries. Limit is {MAX_SHARED_ENTRIES}."), 400

    normalized = []
    seen = set()
    total_bytes = 0
    for item in raw_entries:
        if not isinstance(item, dict):
            con.close(); return jsonify(error="Invalid entry."), 400
        try:
            path_parts = safe_relative_parts(item.get("path"))
        except ValueError:
            con.close(); return jsonify(error="Invalid relative path."), 400
        path = "/".join(path_parts)
        name = str(item.get("name", "")).strip()
        kind = str(item.get("kind", "")).strip().lower()
        if not name or len(name) > 255 or kind not in ("file", "folder") or path in seen:
            con.close(); return jsonify(error="Invalid entry data."), 400
        if mode == "selected_files" and kind != "file":
            con.close(); return jsonify(error="Selected-file mode accepts files only."), 400
        seen.add(path)
        try:
            size = int(item.get("size_bytes") or 0)
        except (TypeError, ValueError):
            con.close(); return jsonify(error="Invalid file size."), 400
        if size < 0 or size > MAX_SHARED_FILE_BYTES:
            con.close(); return jsonify(error="A selected file exceeds the configured per-file size limit."), 400
        if kind == "file":
            total_bytes += size
        modified = str(item.get("modified_at") or "")[:100] or None
        mime = str(item.get("mime_type") or "")[:120]
        normalized.append((path, name, kind, size, modified, mime))

    if total_bytes > MAX_SHARED_TOTAL_BYTES:
        con.close()
        return jsonify(error="The selected files exceed the configured total size limit."), 400

    if old:
        con.execute("DELETE FROM shared_folder_entries WHERE shared_folder_id=?", (old["id"],))
        con.execute("DELETE FROM shared_folders WHERE id=?", (old["id"],))
        con.commit()
        cleanup_share_storage(old["storage_dir"])

    now = datetime.now(timezone.utc).isoformat()
    cur = con.execute(
        """INSERT INTO shared_folders(
            link_id,click_id,root_name,entry_count,shared_at,access_mode,storage_dir
        ) VALUES(?,?,?,?,?,?,?)""",
        (click["link_id"], click_id, root_name, len(normalized), now, mode, "")
    )
    share_id = cur.lastrowid
    storage_dir = os.path.abspath(os.path.join(
        SHARED_STORAGE_ROOT, f"{click_id}-{share_id}-{secrets.token_hex(8)}"
    ))
    os.makedirs(storage_dir, exist_ok=True)
    con.execute("UPDATE shared_folders SET storage_dir=? WHERE id=?", (storage_dir, share_id))
    con.executemany(
        """INSERT INTO shared_folder_entries(
            shared_folder_id,relative_path,name,kind,size_bytes,modified_at,mime_type,storage_path
        ) VALUES(?,?,?,?,?,?,?,NULL)""",
        [(share_id,) + row for row in normalized]
    )
    con.execute("UPDATE clicks SET file_share_mode=?,file_share_denied_at=NULL WHERE id=?", (mode, click_id))
    con.commit()
    con.close()
    return jsonify(success=True, share_id=share_id, mode=mode, entry_count=len(normalized))

@app.post("/api/file-share/<code>/upload")
def file_share_upload(code):
    try:
        click_id = int(request.form.get("click_id", ""))
        share_id = int(request.form.get("share_id", ""))
    except ValueError:
        return jsonify(error="Invalid upload request."), 400
    token = str(request.form.get("share_token", ""))
    relative_path = str(request.form.get("relative_path", "")).strip()

    con = db()
    click = con.execute("""
        SELECT l.id AS link_id,c.id AS click_id,c.share_token
        FROM links l JOIN clicks c ON c.link_id=l.id
        WHERE l.code=? AND c.id=? AND l.enabled=1
    """, (code, click_id)).fetchone()
    if not click or not token_matches(click["share_token"], token):
        con.close()
        return jsonify(error="Upload request not found."), 404
    try:
        relative_path = "/".join(safe_relative_parts(relative_path))
    except ValueError:
        con.close()
        return jsonify(error="Invalid relative path."), 400

    entry = con.execute("""
        SELECT e.id,e.name,e.kind,e.size_bytes,e.storage_path,s.storage_dir,s.access_mode
        FROM shared_folder_entries e JOIN shared_folders s ON s.id=e.shared_folder_id
        WHERE e.shared_folder_id=? AND e.relative_path=?
    """, (share_id, relative_path)).fetchone()
    if not entry or entry["kind"] != "file":
        con.close()
        return jsonify(error="Selected file was not declared in the manifest."), 404

    upload = request.files.get("file")
    if not upload:
        con.close()
        return jsonify(error="No file was uploaded."), 400
    payload = upload.read(MAX_SHARED_FILE_BYTES + 1)
    if len(payload) > MAX_SHARED_FILE_BYTES:
        con.close()
        return jsonify(error="This file exceeds the configured per-file size limit."), 413

    uploaded_total = con.execute(
        """SELECT COALESCE(SUM(size_bytes),0)
           FROM shared_folder_entries
           WHERE shared_folder_id=? AND storage_path IS NOT NULL AND id<>?""",
        (share_id, entry["id"])
    ).fetchone()[0]
    if uploaded_total + len(payload) > MAX_SHARED_TOTAL_BYTES:
        con.close()
        return jsonify(error="The shared file set exceeds the configured total size limit."), 413

    storage_dir = os.path.realpath(entry["storage_dir"])
    allowed_root = os.path.realpath(SHARED_STORAGE_ROOT)
    if not storage_dir.startswith(allowed_root + os.sep):
        con.close()
        return jsonify(error="Invalid storage location."), 500
    os.makedirs(storage_dir, exist_ok=True)
    filename = secure_filename(entry["name"])[:180] or f"file-{entry['id']}"
    storage_path = os.path.abspath(os.path.join(storage_dir, f"{entry['id']}-{filename}"))
    with open(storage_path, "wb") as handle:
        handle.write(payload)
    con.execute(
        "UPDATE shared_folder_entries SET size_bytes=?,mime_type=COALESCE(NULLIF(?,''),mime_type),storage_path=? WHERE id=?",
        (len(payload), upload.mimetype or "", storage_path, entry["id"])
    )
    con.commit()
    con.close()
    return jsonify(success=True, entry_id=entry["id"], bytes=len(payload))

@app.get("/api/shared-files/<int:entry_id>/view")
@login_required
def view_shared_file(entry_id):
    row = owned_shared_entry(entry_id)
    if not row or row["kind"] != "file":
        return jsonify(error="Shared file not found."), 404
    path = resolve_storage_path(row["storage_path"])
    if not path or not os.path.isfile(path):
        return jsonify(error="File content is not available."), 404
    return send_file(path, as_attachment=False, download_name=row["name"], mimetype=row["mime_type"] or None, max_age=0)

@app.get("/api/shared-files/<int:entry_id>/download")
@login_required
def download_shared_file(entry_id):
    row = owned_shared_entry(entry_id)
    if not row or row["kind"] != "file":
        return jsonify(error="Shared file not found."), 404
    path = resolve_storage_path(row["storage_path"])
    if not path or not os.path.isfile(path):
        return jsonify(error="File content is not available."), 404
    return send_file(path, as_attachment=True, download_name=row["name"], mimetype=row["mime_type"] or None, max_age=0)

@app.post("/api/file-share/<code>/revoke")
@login_required
def revoke_file_share(code):
    user = current_user()
    data = request.get_json(silent=True) or {}
    try:
        click_id = int(data.get("click_id"))
    except (TypeError, ValueError):
        return jsonify(error="Invalid request."), 400
    con = db()
    share = con.execute("""
        SELECT s.id,s.storage_dir
        FROM shared_folders s JOIN links l ON l.id=s.link_id
        WHERE l.code=? AND l.user_id=? AND s.click_id=?
    """, (code, user["id"], click_id)).fetchone()
    if not share:
        con.close()
        return jsonify(error="Shared files not found."), 404
    con.execute("DELETE FROM shared_folder_entries WHERE shared_folder_id=?", (share["id"],))
    con.execute("DELETE FROM shared_folders WHERE id=?", (share["id"],))
    con.execute("UPDATE clicks SET file_share_mode='revoked' WHERE id=?", (click_id,))
    con.commit()
    con.close()
    cleanup_share_storage(share["storage_dir"])
    return jsonify(success=True)

@app.post("/api/location-share/<code>")
def location_share_api(code):
    data = request.get_json(silent=True) or {}
    try:
        click_id = int(data.get("click_id"))
        latitude = float(data.get("latitude"))
        longitude = float(data.get("longitude"))
        accuracy = float(data["accuracy"]) if data.get("accuracy") is not None else None
    except (TypeError, ValueError, KeyError):
        return jsonify(error="Invalid location data."), 400
    token = str(data.get("share_token", ""))
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify(error="Invalid coordinates."), 400
    if accuracy is not None and (accuracy < 0 or accuracy > 100000):
        return jsonify(error="Invalid accuracy."), 400
    con = db()
    row = con.execute("""
        SELECT c.id,c.share_token FROM clicks c JOIN links l ON l.id=c.link_id
        WHERE c.id=? AND l.code=? AND l.enabled=1
    """, (click_id, code)).fetchone()
    if not row or not token_matches(row["share_token"], token):
        con.close()
        return jsonify(error="Location request not found."), 404
    now = datetime.now(timezone.utc).isoformat()
    updated = con.execute(
        """UPDATE clicks SET shared_latitude=?,shared_longitude=?,shared_accuracy=?,
           shared_at=?,location_shared=1 WHERE id=? AND location_shared=0""",
        (latitude, longitude, accuracy, now, click_id)
    ).rowcount
    con.commit()
    con.close()
    if not updated:
        return jsonify(error="Location was already shared for this click."), 409
    return jsonify(success=True)

LOCATION_PAGE = r"""
<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PulseLink — Visitor permissions</title><style>{{style}}</style></head><body>
<main class="wrap" style="max-width:760px;padding-top:55px"><div class="card">
<div class="badge">PULSELINK · VISITOR CONTROL</div>
<h1 style="font-size:46px;letter-spacing:-3px">Choose what to share</h1>
<p class="muted">Nothing is granted silently. Every file option below starts only after you click the button and make the browser selection yourself.</p>

<section class="box">
<h3>📍 Precise location</h3>
<p class="notice">Your browser will show its native location permission prompt. PulseLink receives coordinates only after you approve that prompt.</p>
<button id="locationBtn" class="btn" type="button">Share my location</button>
<span id="locationState" class="notice"></span>
</section>

<section class="box" style="margin-top:16px">
<h3>📁 File & folder access</h3>
<p class="notice"><b>Allow all files & folders</b> means all files and subfolders inside the one top-level folder you explicitly choose. A normal website cannot silently unlock your entire computer filesystem.</p>
<div class="form" style="display:flex;gap:10px;flex-wrap:wrap">
<button id="allBtn" class="btn" type="button">Allow all files & folders</button>
<button id="filesBtn" class="small" type="button">Allow selected files</button>
<button id="foldersBtn" class="small" type="button">Allow selected folders</button>
<button id="denyBtn" class="small delete" type="button">Don't allow</button>
</div>
<input id="fileInput" type="file" multiple hidden>
<input id="folderInput" type="file" webkitdirectory multiple hidden>
<p id="fileState" class="notice" style="margin-top:12px"></p>
</section>

<section class="box" style="margin-top:16px">
<h3>Continue</h3>
<p class="notice">When you are finished, press Continue to open the original destination.</p>
<button id="continueBtn" class="btn" type="button">Continue to destination</button>
</section>
</div></main>

<script>
const clickId={{click_id|tojson}};
const code={{code|tojson}};
const shareToken={{share_token|tojson}};
const destination={{destination|tojson}};
const maxEntries={{max_entries|tojson}};
const locationState=document.getElementById('locationState');
const fileState=document.getElementById('fileState');
const fileInput=document.getElementById('fileInput');
const folderInput=document.getElementById('folderInput');

function go(){ window.location.replace(destination); }

document.getElementById('continueBtn').addEventListener('click',go);

document.getElementById('locationBtn').addEventListener('click',function(){
  if(!navigator.geolocation){locationState.textContent='This browser does not support location sharing.';return;}
  locationState.textContent='Waiting for browser permission…';
  navigator.geolocation.getCurrentPosition(async function(pos){
    try{
      const r=await fetch('/api/location-share/'+encodeURIComponent(code),{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          click_id:clickId,share_token:shareToken,
          latitude:pos.coords.latitude,longitude:pos.coords.longitude,accuracy:pos.coords.accuracy
        })
      });
      if(!r.ok)throw new Error('share failed');
      locationState.textContent='✓ Location shared.';
    }catch(e){locationState.textContent='Could not share the location.';}
  },function(err){
    locationState.textContent=err.code===1?'Permission denied.':'Location unavailable.';
  },{enableHighAccuracy:true,maximumAge:0,timeout:10000});
});

function listSelection(files, folderMode){
  const entries=[]; const uploadFiles=[]; const seen=new Set();
  for(const file of Array.from(files||[])){
    const raw=folderMode ? (file.webkitRelativePath||file.name) : file.name;
    const parts=raw.replaceAll('\\\\','/').split('/').filter(Boolean);
    if(!parts.length)continue;
    const relative=folderMode ? parts.slice(1) : [parts[parts.length-1]];
    if(!relative.length)continue;
    if(folderMode){
      for(let i=0;i<relative.length-1;i++){
        const path=relative.slice(0,i+1).join('/');
        if(!seen.has(path)){
          seen.add(path);
          entries.push({path:path,name:relative[i],kind:'folder',size_bytes:0,modified_at:null,mime_type:''});
        }
      }
    }
    const path=relative.join('/');
    if(!seen.has(path)){
      seen.add(path);
      entries.push({
        path:path,name:relative[relative.length-1],kind:'file',
        size_bytes:file.size,modified_at:new Date(file.lastModified).toISOString(),mime_type:file.type||''
      });
    }
    uploadFiles.push({path:path,file:file});
  }
  return {entries:entries,uploadFiles:uploadFiles};
}

async function walkDirectory(handle,prefix,entries,uploadFiles){
  for await(const child of handle.values()){
    const path=prefix+child.name;
    if(child.kind==='directory'){
      entries.push({path:path,name:child.name,kind:'folder',size_bytes:0,modified_at:null,mime_type:''});
      await walkDirectory(child,path+'/',entries,uploadFiles);
    }else{
      const file=await child.getFile();
      entries.push({
        path:path,name:child.name,kind:'file',size_bytes:file.size,
        modified_at:new Date(file.lastModified).toISOString(),mime_type:file.type||''
      });
      uploadFiles.push({path:path,file:file});
    }
  }
}

async function uploadSelection(mode,rootName,selection){
  if(!selection.entries.length){fileState.textContent='Nothing was selected.';return;}
  if(selection.entries.length>maxEntries){fileState.textContent='Selection exceeds the allowed entry limit.';return;}

  fileState.textContent='Creating the permission record…';
  const manifest=await fetch('/api/file-share/'+encodeURIComponent(code)+'/manifest',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      click_id:clickId,share_token:shareToken,mode:mode,
      root_name:rootName,entries:selection.entries
    })
  });
  const md=await manifest.json();
  if(!manifest.ok)throw new Error(md.error||'Could not create the file permission.');

  let done=0;
  for(const item of selection.uploadFiles){
    const form=new FormData();
    form.append('click_id',String(clickId));
    form.append('share_id',String(md.share_id));
    form.append('share_token',shareToken);
    form.append('relative_path',item.path);
    form.append('file',item.file,item.file.name);
    const r=await fetch('/api/file-share/'+encodeURIComponent(code)+'/upload',{method:'POST',body:form});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||'A file upload failed.');
    done++;
    fileState.textContent='Uploading files… '+done+'/'+selection.uploadFiles.length;
  }
  fileState.textContent='✓ '+done+' file(s) uploaded. The owner can now open or download the permitted files.';
}

document.getElementById('allBtn').addEventListener('click',async function(){
  try{
    if(!window.showDirectoryPicker){
      fileState.textContent='This browser does not support the modern folder picker. Use Allow selected folders instead.';
      return;
    }
    const handle=await window.showDirectoryPicker({mode:'read'});
    fileState.textContent='Reading the selected folder…';
    const entries=[];const uploadFiles=[];
    await walkDirectory(handle,'',entries,uploadFiles);
    await uploadSelection('all_files',handle.name,{entries:entries,uploadFiles:uploadFiles});
  }catch(e){
    fileState.textContent=e.name==='AbortError'?'Selection cancelled.':(e.message||'Could not share the folder.');
  }
});

document.getElementById('filesBtn').addEventListener('click',function(){
  fileInput.value='';fileInput.click();
});
document.getElementById('foldersBtn').addEventListener('click',function(){
  folderInput.value='';folderInput.click();
});

fileInput.addEventListener('change',async function(e){
  try{
    await uploadSelection('selected_files','Selected files',listSelection(e.target.files,false));
  }catch(err){fileState.textContent=err.message||'Could not share selected files.';}
});

folderInput.addEventListener('change',async function(e){
  try{
    const files=Array.from(e.target.files||[]);
    const root=((files[0]&&files[0].webkitRelativePath)||'').split('/')[0]||'Selected folder';
    await uploadSelection('selected_folders',root,listSelection(files,true));
  }catch(err){fileState.textContent=err.message||'Could not share selected folders.';}
});

document.getElementById('denyBtn').addEventListener('click',async function(){
  try{
    const r=await fetch('/api/file-share/'+encodeURIComponent(code)+'/manifest',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({click_id:clickId,share_token:shareToken,mode:'deny',root_name:'',entries:[]})
    });
    if(!r.ok)throw new Error('Could not record the choice.');
    fileState.textContent='✓ File access denied.';
  }catch(e){fileState.textContent=e.message||'Could not record the choice.';}
});
</script>
</body></html>
"""

@app.get("/r/<code>")
def tracking_get(code):
    link = get_link(code)
    if not link:
        return "Tracking link not found.", 404
    click_id, share_token = record_click(link["id"])
    return render_template_string(
        LOCATION_PAGE,
        style=STYLE,
        click_id=click_id,
        share_token=share_token,
        code=code,
        destination=link["destination"],
        max_entries=MAX_SHARED_ENTRIES,
    )

@app.get("/health")
def health():
    return jsonify(status="ok", app=APP_NAME)

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
