"""Task 6(U06) 보안: 남의 Host(DNS 리바인딩)와 남의 Origin(CSRF)을 막는다."""


# --- 계획서 Step 1(그대로) ---

def test_foreign_host_rejected(client):
    assert client.get("/health", headers={"host": "evil.example"}).status_code == 400


# --- 더한 것 ---

def test_localhost_host_allowed(client):
    assert client.get("/health", headers={"host": "localhost:8765"}).status_code == 200


def test_foreign_origin_post_rejected(client):
    for origin in ("http://evil.example", "null", "http://localhost:3000", "http://127.0.0.1:8766"):
        r = client.post("/health", headers={"origin": origin})
        assert r.status_code == 403, origin


def test_same_origin_post_passes_origin_check(client):
    # /health는 GET만 받으므로 405가 나오면 Origin 검사는 통과한 것이다.
    for origin in ("http://127.0.0.1:8765", "http://localhost:8765"):
        assert client.post("/health", headers={"origin": origin}).status_code == 405, origin
    assert client.post("/health").status_code == 405  # Origin 없는 요청(브라우저 아님)
