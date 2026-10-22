from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select, func
from citymate.models import User
from .conftest import login


def test_cookie_round_trip_rotation_and_logout(client, platform):
    result = client.post("/auth/code", json={"phone": "13800000000"})
    anonymous_id = client.cookies.get("citymate_session")
    assert "HttpOnly" in result.headers["set-cookie"]
    assert "SameSite=lax" in result.headers["set-cookie"]
    assert "Path=/" in result.headers["set-cookie"]
    assert 0 < platform.r.ttl(platform.session_key(anonymous_id)) <= 300
    result = client.post(
        "/auth/login", json={"phone": "13800000000", "code": result.json()["demo_code"]}
    )
    assert result.status_code == 200
    assert "token" not in result.json()
    session_id = client.cookies.get("citymate_session")
    assert session_id != anonymous_id
    assert not platform.r.exists(platform.session_key(anonymous_id))
    assert platform.r.hget(platform.session_key(session_id), "user")
    assert client.get("/me").json()["id"] == "u0"
    # Reusing the cookie across requests models a page reload.
    assert client.get("/me").json()["id"] == "u0"
    platform.r.expire(platform.session_key(session_id), 20)
    assert client.get("/me").status_code == 200
    assert platform.r.ttl(platform.session_key(session_id)) > 1700
    assert client.post("/auth/logout").status_code == 200
    assert not client.cookies.get("citymate_session")
    assert (
        client.get("/me", headers={"Cookie": "citymate_session=" + session_id}).status_code == 401
    )


def test_code_is_bound_to_browser_and_phone(client, platform):
    code = client.post("/auth/code", json={"phone": "13800000000"}).json()["demo_code"]
    sid = client.cookies.get("citymate_session")
    body = {"phone": "13800000000", "code": code}
    client.cookies.clear()
    assert client.post("/auth/login", json=body).status_code == 401
    assert (
        client.post(
            "/auth/login", json=body, headers={"Cookie": "citymate_session=forged"}
        ).status_code
        == 401
    )
    headers = {"Cookie": "citymate_session=" + sid}
    assert (
        client.post(
            "/auth/login", json={**body, "phone": "13800000001"}, headers=headers
        ).status_code
        == 401
    )
    assert client.post("/auth/login", json=body, headers=headers).status_code == 200
    assert client.post("/auth/login", json=body, headers=headers).status_code == 401


def test_code_expiry_attempt_limit_and_anonymous_access(client, platform):
    code = client.post("/auth/code", json={"phone": "13800000000"}).json()["demo_code"]
    key = platform.session_key(client.cookies.get("citymate_session"))
    platform.r.expire(key, 100)
    assert client.get("/me").status_code == 401
    assert platform.r.ttl(key) <= 100  # Anonymous requests must not renew codes.
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert (
            client.post("/auth/login", json={"phone": "13800000000", "code": wrong}).status_code
            == 401
        )
    assert (
        client.post("/auth/login", json={"phone": "13800000000", "code": code}).status_code == 401
    )
    platform.r.expire(key, 0)
    assert (
        client.post("/auth/login", json={"phone": "13800000000", "code": code}).status_code == 401
    )


def test_first_login_registers_and_sessions_are_isolated(client, platform):
    first = login(client, "13899999999")
    user = client.get("/me", headers=first).json()
    assert user["phone"] == "13899999999" and user["role"] != "admin"
    with platform.db() as db:
        assert (
            db.scalar(select(func.count()).select_from(User).where(User.phone == "13899999999"))
            == 1
        )
    second = login(client, "13800000001")

    def who(headers):
        return client.get("/me", headers=headers).json()["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(who, [first, second] * 6)) == [user["id"], "u1"] * 6
    assert client.get("/me").status_code == 401
    # The previous Bearer/localStorage mechanism no longer authenticates.
    sid = first["Cookie"].split("=", 1)[1]
    assert client.get("/me", headers={"Authorization": "Bearer " + sid}).status_code == 401
    platform.r.expire(platform.session_key(sid), 0)
    assert client.get("/me", headers=first).status_code == 401
    assert client.get("/me", headers=second).status_code == 200


def test_cookie_writes_require_csrf_header(client):
    headers = login(client)
    assert (
        client.post("/auth/logout", headers={**headers, "X-CityMate-Request": ""}).status_code
        == 403
    )
    assert client.get("/me", headers=headers).status_code == 200
    assert client.post("/auth/logout", headers=headers).status_code == 200


def test_secure_cookie_option(client, platform):
    platform.cfg.session_cookie_secure = True
    response = client.post("/auth/code", json={"phone": "13800000000"})
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
