import io
import os
import re
import tempfile
import uuid
from pathlib import Path

TEST_ROOT = Path(tempfile.gettempdir()) / ("pulselink-test-" + uuid.uuid4().hex)
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["PULSELINK_DB"] = str(TEST_ROOT / "test.db")
os.environ["PULSELINK_SHARED_STORAGE"] = str(TEST_ROOT / "shared")
os.environ["PULSELINK_SECRET_KEY"] = "test-secret"

import app as pulselink


def make_user(client, monkeypatch, username="tester", email="tester@example.com"):
    sent = {}
    monkeypatch.setattr(pulselink, "send_verification_email", lambda email, username, token: sent.setdefault("token", token) or True)
    response = client.post(
        "/signup",
        data={
            "full_name": "Test User",
            "email": email,
            "purpose": "Testing PulseLink",
            "username": username,
            "password": "correct-horse-123",
            "consent": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Check your email" in response.get_data(as_text=True)
    assert "token" in sent
    verify = client.get("/verify-email/" + sent["token"])
    assert verify.status_code == 200
    login = client.post(
        "/login",
        data={"username": username, "password": "correct-horse-123"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    return client


def create_link(client):
    response = client.post("/api/links", json={"destination": "https://example.com/path?q=1"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["url"].startswith("http://localhost/")
    return data["code"]


def get_click_token(code):
    response = client.get("/r/" + code)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    click_id = int(re.search(r"const clickId=([^;]+);", body).group(1))
    share_token = __import__("json").loads(re.search(r"const shareToken=([^;]+);", body).group(1))
    assert "Allow all files & folders" in body
    assert "Allow selected files (folders)" in body
    assert "Don't allow file system" in body
    return click_id, share_token


client = None


def setup_function():
    global client
    client = pulselink.app.test_client()
    db_path = Path(os.environ["PULSELINK_DB"])
    if db_path.exists():
        db_path.unlink()
    storage = Path(os.environ["PULSELINK_SHARED_STORAGE"])
    if storage.exists():
        import shutil
        shutil.rmtree(storage)
    pulselink.init_db()


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_email_verification_and_login(monkeypatch):
    make_user(client, monkeypatch, "verifyuser", "verify@example.com")
    response = client.get("/dashboard")
    assert response.status_code == 200


def test_maybe_later_continues_without_email_verification(monkeypatch):
    sent = {}
    monkeypatch.setattr(pulselink, "send_verification_email", lambda email, username, token: sent.setdefault("token", token) or True)
    response = client.post(
        "/signup",
        data={
            "full_name": "Later User",
            "email": "later@example.com",
            "purpose": "Testing later verification",
            "username": "lateruser",
            "password": "correct-horse-123",
            "consent": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Maybe later" in body
    continue_response = client.get("/continue-without-verification", follow_redirects=False)
    assert continue_response.status_code == 302
    assert continue_response.headers["Location"].endswith("/dashboard")
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200

    con = pulselink.db()
    row = con.execute("SELECT email_verified FROM users WHERE username=?", ("lateruser",)).fetchone()
    con.close()
    assert row["email_verified"] == 0


def test_google_configuration_guard(monkeypatch):
    monkeypatch.setattr(pulselink, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(pulselink, "GOOGLE_REDIRECT_URI", "")
    response = client.get("/auth/google")
    assert response.status_code == 503
    assert "not configured" in response.get_data(as_text=True)


def test_google_oauth_state_and_callback(monkeypatch):
    monkeypatch.setattr(pulselink, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(pulselink, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(pulselink, "GOOGLE_REDIRECT_URI", "http://localhost/auth/google/callback")

    start = client.get("/auth/google", follow_redirects=False)
    assert start.status_code == 302
    assert "accounts.google.com" in start.headers["Location"]

    with client.session_transaction() as session:
        state = session["google_oauth_state"]

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    monkeypatch.setattr(
        pulselink.requests,
        "post",
        lambda *args, **kwargs: FakeResponse({"access_token": "fake-access-token"}),
    )
    monkeypatch.setattr(
        pulselink.requests,
        "get",
        lambda *args, **kwargs: FakeResponse({
            "sub": "google-sub-1",
            "email": "google@example.com",
            "email_verified": True,
            "name": "Google Test",
        }),
    )

    callback = client.get("/auth/google/callback?code=fake-code&state=" + state, follow_redirects=False)
    assert callback.status_code == 302
    assert callback.headers["Location"].endswith("/dashboard")
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200


def test_consented_file_transfer_view_download_and_owner_isolation(monkeypatch):
    make_user(client, monkeypatch)
    code = create_link(client)
    click_id, token = get_click_token(code)

    manifest = client.post(
        "/api/file-share/" + code + "/manifest",
        json={
            "click_id": click_id,
            "share_token": token,
            "mode": "all_files",
            "root_name": "Documents",
            "entries": [
                {
                    "path": "notes.txt",
                    "name": "notes.txt",
                    "kind": "file",
                    "size_bytes": 11,
                    "modified_at": "2026-09-27T00:00:00+00:00",
                    "mime_type": "text/plain",
                },
                {
                    "path": "photos",
                    "name": "photos",
                    "kind": "folder",
                    "size_bytes": 0,
                    "modified_at": None,
                    "mime_type": "",
                },
                {
                    "path": "photos/pic.txt",
                    "name": "pic.txt",
                    "kind": "file",
                    "size_bytes": 9,
                    "modified_at": "2026-09-27T00:00:00+00:00",
                    "mime_type": "text/plain",
                },
            ],
        },
    )
    assert manifest.status_code == 200
    share_id = manifest.get_json()["share_id"]

    upload = client.post(
        "/api/file-share/" + code + "/upload",
        data={
            "click_id": str(click_id),
            "share_id": str(share_id),
            "share_token": token,
            "relative_path": "notes.txt",
            "file": (io.BytesIO(b"hello world"), "notes.txt"),
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200
    entry_id = upload.get_json()["entry_id"]

    view = client.get("/api/shared-files/" + str(entry_id) + "/view")
    assert view.status_code == 200
    assert view.data == b"hello world"

    download = client.get("/api/shared-files/" + str(entry_id) + "/download")
    assert download.status_code == 200
    assert download.data == b"hello world"

    analytics = client.get("/api/links/" + code)
    assert analytics.status_code == 200
    payload = analytics.get_json()
    assert payload["folder_shares"][0]["access_mode"] == "all_files"
    files = {x["relative_path"]: x for x in payload["folder_entries"]}
    assert files["notes.txt"]["has_content"] == 1
    assert files["photos/pic.txt"]["has_content"] == 0

    with client.session_transaction() as session:
        session.clear()
    anonymous = client.get("/api/shared-files/" + str(entry_id) + "/download")
    assert anonymous.status_code == 401


def test_file_share_token_and_path_traversal_rejected(monkeypatch):
    make_user(client, monkeypatch, "secureuser", "secure@example.com")
    code = create_link(client)
    click_id, token = get_click_token(code)

    bad_token = client.post(
        "/api/file-share/" + code + "/manifest",
        json={
            "click_id": click_id,
            "share_token": "wrong",
            "mode": "selected_files",
            "root_name": "Selected files",
            "entries": [{"path": "a.txt", "name": "a.txt", "kind": "file", "size_bytes": 1}],
        },
    )
    assert bad_token.status_code == 404

    traversal = client.post(
        "/api/file-share/" + code + "/manifest",
        json={
            "click_id": click_id,
            "share_token": token,
            "mode": "selected_files",
            "root_name": "Selected files",
            "entries": [{"path": "../secret.txt", "name": "secret.txt", "kind": "file", "size_bytes": 1}],
        },
    )
    assert traversal.status_code == 400


def test_deny_file_access(monkeypatch):
    make_user(client, monkeypatch, "denyuser", "deny@example.com")
    code = create_link(client)
    click_id, token = get_click_token(code)
    denied = client.post(
        "/api/file-share/" + code + "/manifest",
        json={"click_id": click_id, "share_token": token, "mode": "deny", "root_name": "", "entries": []},
    )
    assert denied.status_code == 200
    data = client.get("/api/links/" + code).get_json()
    assert data["clicks"][0]["file_share_mode"] == "deny"
