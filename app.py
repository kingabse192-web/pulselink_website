import os
import sqlite3
import secrets
import string
import ipaddress
import re
import requests
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
        FOREIGN KEY(link_id) REFERENCES links(id)
    );
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
    con.commit()
    con.close()

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
    con.execute("""
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
    con.commit()
    con.close()

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
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:14px}.box h3{font-size:13px;margin-top:0}.box p{font-size:13px;color:#6b7280}
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
 const rows=d.clicks;const mapped=rows.filter(x=>x.latitude!==null&&x.longitude!==null);
 p.innerHTML=`<h2>03 · Analytics — <code>${esc(code)}</code></h2><p class="muted">Destination: ${esc(d.link.destination)}</p>
 <div class="grid"><div class="box"><h3>Devices</h3>${list(countBy(rows,'device'))}</div><div class="box"><h3>Browsers</h3>${list(countBy(rows,'browser'))}</div><div class="box"><h3>OS</h3>${list(countBy(rows,'operating_system'))}</div><div class="box"><h3>Countries</h3>${list(countBy(rows,'country'))}</div></div>
 <h3>04 · Location Map</h3><div id="map"></div>
 <h3>05 · Location Details</h3><div class="scroll"><table><thead><tr><th>Time</th><th>Country</th><th>Region</th><th>City</th><th>ISP</th></tr></thead><tbody>
 ${rows.map(x=>`<tr><td>${time(x.created_at)}</td><td>${esc(x.country)} ${esc(x.country_code)}</td><td>${esc(x.region)}</td><td>${esc(x.city)}</td><td>${esc(x.isp)}</td></tr>`).join('')||'<tr><td colspan="5">No clicks yet.</td></tr>'}</tbody></table></div>
 <h3>06 · Click Details</h3><div class="scroll"><table><thead><tr><th>Time</th><th>Device</th><th>Browser</th><th>OS</th><th>Referrer</th></tr></thead><tbody>
 ${rows.map(x=>`<tr><td>${time(x.created_at)}</td><td>${esc(x.device)}</td><td>${esc(x.browser)}</td><td>${esc(x.operating_system)}</td><td>${esc(x.referrer)}</td></tr>`).join('')||'<tr><td colspan="5">No clicks yet.</td></tr>'}</tbody></table></div>`;
 const map=L.map('map').setView([20,0],2);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© OpenStreetMap contributors'}).addTo(map);
 const bounds=[];for(const x of mapped){const point=[Number(x.latitude),Number(x.longitude)];bounds.push(point);L.marker(point).addTo(map).bindPopup(`<b>${esc([x.city,x.region,x.country].filter(Boolean).join(', '))}</b><br>${esc(x.device)} · ${esc(x.browser)}<br>${esc(x.isp)}`)}if(bounds.length)map.fitBounds(bounds,{padding:[30,30]});p.scrollIntoView({behavior:'smooth'});
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
{% if title == 'Create account' %}<label class="check"><input name="consent" type="checkbox" required> I agree to the privacy notice and acceptable-use rules. I understand my account details may be used for security and abuse review.</label><br><br>{% endif %}
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
        SELECT created_at,device,browser,operating_system,referrer,country,country_code,
               region,city,isp,latitude,longitude,timezone
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
    con.execute("DELETE FROM clicks WHERE link_id=?", (link["id"],))
    con.execute("DELETE FROM links WHERE id=?", (link["id"],))
    con.commit()
    con.close()
    return jsonify(success=True)

@app.get("/r/<code>")
def tracking_get(code):
    link = get_link(code)
    if not link:
        return "Tracking link not found.", 404
    record_click(link["id"])
    return redirect(link["destination"], code=302)

@app.get("/health")
def health():
    return jsonify(status="ok", app=APP_NAME)

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
