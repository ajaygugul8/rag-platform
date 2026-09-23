import io


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_upload_requires_auth(client):
    files = {"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}
    resp = client.post("/documents", files=files)
    assert resp.status_code == 401


def test_upload_and_fetch_document(client, auth_headers):
    files = {"file": ("policy.txt", io.BytesIO(b"Employees get 20 days of leave per year."), "text/plain")}
    resp = client.post("/documents", files=files, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"] == "policy.txt"
    assert body["status"] == "uploaded"

    doc_id = body["id"]
    get_resp = client.get(f"/documents/{doc_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == doc_id


def test_upload_rejects_bad_file_type(client, auth_headers):
    files = {"file": ("virus.exe", io.BytesIO(b"MZ..."), "application/x-msdownload")}
    resp = client.post("/documents", files=files, headers=auth_headers)
    assert resp.status_code == 422


def test_upload_rejects_oversized_file(client, auth_headers, monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "max_upload_mb", 0)
    files = {"file": ("big.txt", io.BytesIO(b"x" * 1024), "text/plain")}
    resp = client.post("/documents", files=files, headers=auth_headers)
    assert resp.status_code == 422
