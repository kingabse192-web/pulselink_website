import os
import sqlite3
import secrets
import string
import ipaddress
import re
import requests
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timezone
from urllib.parse import urlparse
from functools import wraps
from flask import Flask, request, redirect, jsonify, render_template_string, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

APP_NAME = "PulseLink"
OWNER = "ABSALEW BELAYNEH"
OWNER_EMAIL = os.environ.get("PULSELINK_OWNER_EMAIL", "absalew1234@gmail.com")
DB_PATH = os.environ.get("PULSELINK_DB", "pulselink.db")
PORT = int(os.environ.get("PORT", "5000"))

app = Flask(__name__)
app.secret_key = os.environ.get("PULSELINK_SECRET_KEY", "dev-only-change-this-secret")

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
        FOREIGN KEY(link_id) REFERENCES links(id)
    );

    CREATE TABLE IF NOT EXISTS shared_folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        link_id INTEGER NOT NULL,
        click_id INTEGER NOT NULL UNIQUE,
        root_name TEXT NOT NULL,
        entry_count INTEGER NOT NULL DEFAULT 0,
        shared_at TEXT NOT NULL,
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
    for name, definition in (("shared_latitude", "REAL"),("shared_longitude", "REAL"),("shared_accuracy", "REAL"),("shared_at", "TEXT"),("location_shared", "INTEGER NOT NULL DEFAULT 0")):
        if name not in click_columns:
            con.execute(f"ALTER TABLE clicks ADD COLUMN {name} {definition}")
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

def safe_upload_filename(filename):
    cleaned = secure_filename(filename or "")
    if not cleaned:
        return None
    extension = os.path.splitext(cleaned)[1].lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        return None
    return cleaned

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

def record_click(link_id):
    device, browser, os_name = parse_user_agent(request.headers.get("User-Agent", ""))
    referrer = (request.referrer or "Direct")[:250]
    geo = geo_lookup(public_ip())

    con = db()
    cursor = con.execute("""
        INSERT INTO clicks (
            link_id, created_at, device, browser, operating_system, referrer,
            country, country_code, region, city, isp, latitude, longitude, timezone
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        link_id,
        datetime.now(timezone.utc).isoformat(),
        device, browser, os_name, referrer,
        geo["country"], geo["country_code"], geo["region"], geo["city"], geo["isp"],
        geo["latitude"], geo["longitude"], geo["timezone"],
    ))
    click_id = cursor.lastrowid
    con.commit()
    con.close()
    return click_id

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
<section class="card"><h2>03 · Uploaded files</h2><p class="notice">Files appear here only when a visitor explicitly chooses them and presses Upload. PulseLink does not browse a visitor's device.</p><div class="scroll"><table><thead><tr><th>File</th><th>Link</th><th>Uploaded</th><th>Device</th><th>Type</th><th>Size</th><th>Action</th></tr></thead><tbody>
{% for f in uploads %}<tr><td>{{f.original_name}}</td><td><code>{{f.code}}</code></td><td>{{f.created_at[:19].replace('T',' ')}}</td><td>{{f.device}} · {{f.browser}} · {{f.operating_system}}</td><td>{{f.content_type}}</td><td>{% if f.size_bytes >= 1048576 %}{{'%.2f'|format(f.size_bytes/1048576)}} MB{% else %}{{'%.1f'|format(f.size_bytes/1024)}} KB{% endif %}</td><td><a class="small" href="/api/uploads/{{f.id}}/download">Download</a></td></tr>
{% else %}<tr><td colspan="7">No files have been uploaded.</td></tr>{% endfor %}</tbody></table></div></section>
<section id="analytics" class="card hidden"></section></main>
<script>
const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
function countBy(a,k){const o={};for(const x of a){const v=x[k]||'Unknown';o[v]=(o[v]||0)+1}return o}
function list(o){return Object.entries(o).sort((a,b)=>b[1]-a[1]).map(x=>`<p><b>${esc(x[0])}</b> — ${x[1]}</p>`).join('')||'<p>No data.</p>'}
function time(v){return esc((v||'').replace('T',' ').slice(0,19))}

document.getElementById('create').addEventListener('submit',async e=>{
 e.preventDefault();const result=document.getElementById('result');
 try{const r=await fetch('/api/links',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({destination:document.getElementById('destination').value.trim()})});
 const d=await r.json();result.classList.remove('hidden');
 if(!r.ok){result.textContent=d.error||'Could not create link.';return}
 result.innerHTML=`<b>Tracking link:</b><br><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.url)}</a><br><br><button class="small" onclick="copyIt('${esc(d.url)}')">Copy</button>`;
 }catch(err){result.classList.remove('hidden');result.textContent='Server connection error.';}
});
function copyIt(u){navigator.clipboard?.writeText(u).then(()=>alert('Copied')).catch(()=>prompt('Copy:',u))}
async function showAnalytics(code){
 const p=document.getElementById('analytics');p.classList.remove('hidden');p.innerHTML='<h2>Loading…</h2>';
 const r=await fetch('/api/links/'+encodeURIComponent(code));const d=await r.json();if(!r.ok){p.innerHTML='<h2>Error</h2>';return}
 const rows=d.clicks;const mapped=rows.filter(x=>x.latitude!==null&&x.longitude!==null);const shared=rows.filter(x=>x.location_shared&&x.shared_latitude!==null&&x.shared_longitude!==null);
 p.innerHTML=`<h2>03 · Analytics — <code>${esc(code)}</code></h2><p class="muted">Destination: ${esc(d.link.destination)}</p>
 <div class="grid"><div class="box"><h3>Devices</h3>${list(countBy(rows,'device'))}</div><div class="box"><h3>Browsers</h3>${list(countBy(rows,'browser'))}</div><div class="box"><h3>OS</h3>${list(countBy(rows,'operating_system'))}</div><div class="box"><h3>Countries</h3>${list(countBy(rows,'country'))}</div></div><div class="grid"><div class="box"><h3>Clicks</h3><p><b>${rows.length}</b> recorded</p></div><div class="box"><h3>Shared locations</h3><p><b>${shared.length}</b> visitor(s) explicitly shared precise coordinates</p></div><div class="box"><h3>Referrers</h3>${list(countBy(rows,'referrer'))}</div><div class="box"><h3>Time zones</h3>${list(countBy(rows,'timezone'))}</div></div>
 <h3>04 · Location Map</h3><div id="map"></div>
 <h3>05 · Shared Browser Locations</h3>
<p class="notice">Only locations explicitly shared by a visitor after the browser permission prompt are shown here.</p>
<div class="scroll"><table><thead><tr><th>Shared at</th><th>Latitude</th><th>Longitude</th><th>Accuracy</th></tr></thead><tbody>
${rows.filter(x=>x.location_shared).map(x=>'<tr><td>'+time(x.shared_at)+'</td><td>'+Number(x.shared_latitude).toFixed(6)+'</td><td>'+Number(x.shared_longitude).toFixed(6)+'</td><td>'+(x.shared_accuracy==null?'—':esc(Number(x.shared_accuracy).toFixed(1)+' m'))+'</td></tr>').join('')||'<tr><td colspan="4">No visitor has shared a browser location yet.</td></tr>'}
</tbody></table></div>
<h3>07 · Visitor / Device Details</h3><div class="scroll"><table><thead><tr><th>Time</th><th>Device</th><th>Browser</th><th>OS</th><th>Country</th><th>City</th><th>Referrer</th><th>ISP</th><th>Time zone</th><th>Precise location</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${time(x.created_at)}</td><td>${esc(x.device)}</td><td>${esc(x.browser)}</td><td>${esc(x.operating_system)}</td><td>${esc(x.country)} ${esc(x.country_code)}</td><td>${esc(x.city)}, ${esc(x.region)}</td><td>${esc(x.referrer)}</td><td>${esc(x.isp)}</td><td>${esc(x.timezone)}</td><td>${x.location_shared?'Shared':'Not shared'}</td></tr>`).join('')||'<tr><td colspan="10">No clicks yet.</td></tr>'}</tbody></table></div>
 <h3>08 · Location Details</h3><div class="scroll"><table><thead><tr><th>Time</th><th>Country</th><th>Region</th><th>City</th><th>ISP</th></tr></thead><tbody>
 ${rows.map(x=>`<tr><td>${time(x.created_at)}</td><td>${esc(x.country)} ${esc(x.country_code)}</td><td>${esc(x.region)}</td><td>${esc(x.city)}</td><td>${esc(x.isp)}</td></tr>`).join('')||'<tr><td colspan="5">No clicks yet.</td></tr>'}</tbody></table></div>
 <h3>06 · Click Details</h3><div class="scroll"><table><thead><tr><th>Time</th><th>Device</th><th>Browser</th><th>OS</th><th>Referrer</th></tr></thead><tbody>
 ${rows.map(x=>`<tr><td>${time(x.created_at)}</td><td>${esc(x.device)}</td><td>${esc(x.browser)}</td><td>${esc(x.operating_system)}</td><td>${esc(x.referrer)}</td></tr>`).join('')||'<tr><td colspan="5">No clicks yet.</td></tr>'}</tbody></table></div>`;
 const map=L.map('map').setView([20,0],2);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© OpenStreetMap contributors'}).addTo(map);
 const bounds=[];for(const x of mapped){const point=[Number(x.latitude),Number(x.longitude)];bounds.push(point);L.marker(point).addTo(map).bindPopup(`<b>Approximate IP location</b><br>${esc([x.city,x.region,x.country].filter(Boolean).join(', '))}<br>${esc(x.device)} · ${esc(x.browser)} · ${esc(x.operating_system)}<br>${esc(x.isp)}<br>${time(x.created_at)}`)}for(const x of shared){const point=[Number(x.shared_latitude),Number(x.shared_longitude)];bounds.push(point);const marker=L.marker(point).addTo(map);if(Number.isFinite(Number(x.shared_accuracy))&&Number(x.shared_accuracy)>0)L.circle(point,{radius:Number(x.shared_accuracy)}).addTo(map);marker.bindPopup(`<b>Explicitly shared browser location</b><br>${esc([x.city,x.region,x.country].filter(Boolean).join(', '))}<br><b>Device:</b> ${esc(x.device)}<br><b>Browser:</b> ${esc(x.browser)}<br><b>OS:</b> ${esc(x.operating_system)}<br><b>Latitude:</b> ${esc(Number(x.shared_latitude).toFixed(6))}<br><b>Longitude:</b> ${esc(Number(x.shared_longitude).toFixed(6))}<br><b>Accuracy:</b> ${x.shared_accuracy==null?'—':esc(Number(x.shared_accuracy).toFixed(1)+' m')}<br><b>Shared:</b> ${time(x.shared_at)}`)}if(bounds.length)map.fitBounds(bounds,{padding:[30,30],maxZoom:14});p.scrollIntoView({behavior:'smooth'});
}
async function removeLink(code){if(!confirm('Delete this link and its analytics?'))return;const r=await fetch('/api/links/'+encodeURIComponent(code)+'/delete',{method:'POST'});if(r.ok)location.reload()}
</script></body></html>
"""

AUTH = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{title}} — PulseLink</title><style>{{style}}</style></head><body>
<header><div class="logo">ABSALEW <span>BELAYNEH</span></div><a class="navlink" href="/">← Home</a></header>
<main class="wrap" style="max-width:520px"><div class="card"><div class="badge">PULSELINK ACCOUNT</div><h1 style="font-size:42px;letter-spacing:-2px">{{title}}</h1>
{% if error %}<p style="color:#b91c1c">{{error}}</p>{% endif %}<form method="post">
{% if title == 'Create account' %}<label>Full name</label><input name="full_name" maxlength="100" required autocomplete="name"><br><br>
<label>Email address</label><input name="email" type="email" maxlength="254" required autocomplete="email"><br><br>
<label>Why are you using PulseLink?</label><textarea name="purpose" maxlength="500" required rows="4" placeholder="For example: measuring campaign links"></textarea><br><br>{% endif %}
<label>Username</label><input name="username" minlength="3" maxlength="40" required autocomplete="username"><br><br>
<label>Password</label><input name="password" type="password" minlength="8" required autocomplete="{{'new-password' if title == 'Create account' else 'current-password'}}"><br><br>
{% if title == 'Create account' %}<label class="check"><input name="consent" type="checkbox" required> I agree to the privacy notice and acceptable-use rules. I understand my name, email, username, and stated purpose are sent to the PulseLink project owner for account and security administration.</label><br><br>{% endif %}
<button class="btn" type="submit">{{title}}</button></form>
<p class="muted">{% if title == 'Sign in' %}New here? <a href="/signup">Create an account</a>{% else %}Already registered? <a href="/login">Sign in</a>{% endif %}</p></div></main></body></html>
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
                cursor = con.execute(
                    "INSERT INTO users(username,full_name,email,purpose,consent_at,password_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                    (username, full_name, email, purpose, datetime.now(timezone.utc).isoformat(), generate_password_hash(password), datetime.now(timezone.utc).isoformat()),
                )
                con.commit()
                created_at = datetime.now(timezone.utc).isoformat()
                send_owner_signup_notification(full_name, email, purpose, username, created_at)
                session.clear()
                session["user_id"] = cursor.lastrowid
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                error = "That username or email address is already registered."
            finally:
                con.close()
    return render_template_string(AUTH, style=STYLE, title="Create account", error=error)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        con = db()
        user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        con.close()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))
        error = "Invalid username or password."
    return render_template_string(AUTH, style=STYLE, title="Sign in", error=error)

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
    uploads = con.execute("""
        SELECT u.id, u.original_name, u.content_type, u.size_bytes, u.created_at,
               l.code, c.device, c.browser, c.operating_system
        FROM uploads u
        JOIN links l ON l.id=u.link_id
        JOIN clicks c ON c.id=u.click_id
        WHERE l.user_id=? ORDER BY u.id DESC LIMIT 500
    """, (user["id"],)).fetchall()
    con.close()
    return render_template_string(DASHBOARD, style=STYLE, owner=OWNER, user=user, links=links, total=total, count=len(links), uploads=uploads)

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
        SELECT created_at,device,browser,operating_system,referrer,country,country_code,
               region,city,isp,latitude,longitude,timezone,shared_latitude,shared_longitude,shared_accuracy,shared_at,location_shared
        FROM clicks WHERE link_id=? ORDER BY id DESC LIMIT 1000
    """, (link["id"],)).fetchall()
    con.close()
    return jsonify(link=dict(link), clicks=[dict(x) for x in rows])

@app.post("/api/links/<code>/delete")
@login_required
def delete_api(code):
    user = current_user()
    con = db()
    link = con.execute("SELECT id FROM links WHERE code=? AND user_id=?", (code, user["id"])).fetchone()
    if not link:
        con.close()
        return jsonify(error="Tracking link not found."), 404
    files = con.execute("SELECT stored_name FROM uploads WHERE link_id=?", (link["id"],)).fetchall()
    for item in files:
        path = os.path.join(DOWNLOAD_DIR, os.path.basename(item["stored_name"]))
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
    con.execute("DELETE FROM uploads WHERE link_id=?", (link["id"],))
    con.execute("DELETE FROM clicks WHERE link_id=?", (link["id"],))
    con.execute("DELETE FROM links WHERE id=?", (link["id"],))
    con.commit()
    con.close()
    return jsonify(success=True)

@app.post("/api/upload/<code>")
def upload_api(code):
    try:
        click_id = int(request.form.get("click_id", ""))
    except (TypeError, ValueError):
        return jsonify(error="Invalid upload request."), 400

    con = db()
    row = con.execute("""
        SELECT l.id AS link_id, c.id AS click_id
        FROM links l JOIN clicks c ON c.link_id=l.id
        WHERE l.code=? AND c.id=? AND l.enabled=1
    """, (code, click_id)).fetchone()
    if not row:
        con.close()
        return jsonify(error="Upload request not found."), 404

    files = request.files.getlist("files")
    if not files:
        con.close()
        return jsonify(error="Choose at least one file."), 400
    if len(files) > 5:
        con.close()
        return jsonify(error="You can upload at most 5 files at once."), 400

    saved_paths = []
    uploaded = []
    try:
        for file in files:
            original = safe_upload_filename(file.filename)
            if not original:
                raise ValueError("One or more files use an unsupported file type.")
            stored = uuid.uuid4().hex + "_" + original
            path = os.path.join(DOWNLOAD_DIR, stored)
            file.save(path)
            saved_paths.append(path)
            size_bytes = os.path.getsize(path)
            if size_bytes <= 0:
                raise ValueError("Empty files are not supported.")
            if size_bytes > MAX_UPLOAD_BYTES:
                raise ValueError(f"Each file must be {MAX_UPLOAD_MB} MB or smaller.")
            content_type = (file.mimetype or "application/octet-stream")[:120]
            created_at = datetime.now(timezone.utc).isoformat()
            con.execute("""
                INSERT INTO uploads(link_id,click_id,original_name,stored_name,content_type,size_bytes,created_at)
                VALUES(?,?,?,?,?,?,?)
            """, (row["link_id"], row["click_id"], original, stored, content_type, size_bytes, created_at))
            uploaded.append({"name": original, "size_bytes": size_bytes})
        con.commit()
        return jsonify(success=True, uploaded=uploaded)
    except ValueError as exc:
        con.rollback()
        for path in saved_paths:
            try:
                os.remove(path)
            except OSError:
                pass
        return jsonify(error=str(exc)), 400
    except OSError:
        con.rollback()
        for path in saved_paths:
            try:
                os.remove(path)
            except OSError:
                pass
        return jsonify(error="The server could not save the selected file(s)."), 500
    finally:
        con.close()


@app.get("/api/uploads/<int:upload_id>/download")
@login_required
def download_upload(upload_id):
    user = current_user()
    con = db()
    row = con.execute("""
        SELECT u.original_name, u.stored_name
        FROM uploads u JOIN links l ON l.id=u.link_id
        WHERE u.id=? AND l.user_id=?
    """, (upload_id, user["id"])).fetchone()
    con.close()
    if not row:
        return "File not found.", 404
    path = os.path.join(DOWNLOAD_DIR, os.path.basename(row["stored_name"]))
    if not os.path.isfile(path):
        return "File not found on disk.", 404
    return send_file(path, as_attachment=True, download_name=row["original_name"], mimetype="application/octet-stream")


LOCATION_PAGE = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Location sharing — PulseLink</title><style>{{style}}</style></head><body>
<main class="wrap" style="max-width:620px;padding-top:70px"><div class="card" style="text-align:center">
<div class="badge">PULSELINK · OPTIONAL LOCATION SHARING</div>
<h1 style="font-size:42px;letter-spacing:-2px">Share your location?</h1>
<p class="muted">You can optionally share your current browser location with the link owner. Your location is sent only after you press <b>Share my location</b> and approve the browser permission prompt.</p>
<button id="share" class="btn" type="button">Share my location</button>
<button id="skip" class="small" type="button" style="display:block;width:100%;margin-top:10px">Continue without sharing</button>
<hr style="border:0;border-top:1px solid #e5e7eb;margin:24px 0">
<h2 style="font-size:20px">Optional file upload</h2>
<p class="notice">Choose photos or supported documents yourself. Nothing is uploaded until you select files and press Upload.</p>
<input id="files" type="file" multiple accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.txt,.csv,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip" style="margin:10px 0">
<button id="upload" class="small" type="button">Upload selected files</button>
<p id="uploadStatus" class="notice" style="margin-top:10px"></p>
<p id="status" class="notice" style="margin-top:16px"></p></div></main>
<script>
const clickId={{click_id|tojson}}, code={{code|tojson}}, destination={{destination|tojson}};
let done=false; const statusEl=document.getElementById('status');
function finish(){if(done)return;done=true;window.location.replace(destination)}
async function share(){
 if(!navigator.geolocation){statusEl.textContent='Location sharing is not supported here. Continuing…';setTimeout(finish,800);return}
 statusEl.textContent='Waiting for your permission…';
 navigator.geolocation.getCurrentPosition(async position=>{
   try{
     const response=await fetch('/api/location-share/'+encodeURIComponent(code),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({click_id:clickId,latitude:position.coords.latitude,longitude:position.coords.longitude,accuracy:position.coords.accuracy}),keepalive:true});
     if(!response.ok)throw new Error('upload failed');
     statusEl.textContent='Location shared. Continuing…';
   }catch(e){statusEl.textContent='Could not share the location. Continuing…'}
   setTimeout(finish,250);
 }, error=>{statusEl.textContent=error.code===1?'Location permission was not granted. Continuing…':'Location is unavailable. Continuing…';setTimeout(finish,800)}, {enableHighAccuracy:true,maximumAge:0,timeout:10000});
}
document.getElementById('share').addEventListener('click',share);
document.getElementById('skip').addEventListener('click',finish);
document.getElementById('upload').addEventListener('click',async()=>{
 const input=document.getElementById('files');
 const uploadStatus=document.getElementById('uploadStatus');
 if(!input.files.length){uploadStatus.textContent='Choose at least one supported file first.';return}
 const form=new FormData();
 form.append('click_id',clickId);
 for(const file of input.files)form.append('files',file);
 uploadStatus.textContent='Uploading…';
 try{
   const response=await fetch('/api/upload/'+encodeURIComponent(code),{method:'POST',body:form});
   const data=await response.json();
   if(!response.ok)throw new Error(data.error||'Upload failed.');
   uploadStatus.textContent='Uploaded '+data.uploaded.length+' file(s).';
 }catch(e){uploadStatus.textContent=e.message||'Upload failed.'}
});
</script></body></html>
"""

@app.get("/r/<code>")
def tracking_get(code):
    link = get_link(code)
    if not link:
        return "Tracking link not found.", 404
    click_id = record_click(link["id"])
    return render_template_string(LOCATION_PAGE, style=STYLE, click_id=click_id, code=code, destination=link["destination"])

@app.post("/api/location-share/<code>")
def location_share_api(code):
    data=request.get_json(silent=True) or {}
    try:
        click_id=int(data.get("click_id")); latitude=float(data.get("latitude")); longitude=float(data.get("longitude"))
        accuracy=float(data["accuracy"]) if data.get("accuracy") is not None else None
    except (TypeError,ValueError,KeyError):
        return jsonify(error="Invalid location data."),400
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180): return jsonify(error="Invalid coordinates."),400
    if accuracy is not None and (accuracy < 0 or accuracy > 100000): return jsonify(error="Invalid accuracy."),400
    con=db()
    row=con.execute("SELECT c.id FROM clicks c JOIN links l ON l.id=c.link_id WHERE c.id=? AND l.code=?",(click_id,code)).fetchone()
    if not row: con.close(); return jsonify(error="Location request not found."),404
    now=datetime.now(timezone.utc).isoformat()
    updated=con.execute("UPDATE clicks SET shared_latitude=?, shared_longitude=?, shared_accuracy=?, shared_at=?, location_shared=1 WHERE id=? AND location_shared=0",(latitude,longitude,accuracy,now,click_id)).rowcount
    con.commit(); con.close()
    if not updated: return jsonify(error="Location was already shared for this click."),409
    return jsonify(success=True)

@app.get("/health")
def health():
    return jsonify(status="ok", app=APP_NAME)

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
