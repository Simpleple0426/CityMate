"""Integration checks for the consolidated application entry point."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from citymate.app import create_app


def test_public_catalog_routes_and_validation(client):
    assert client.get("/health").json()["status"] == "ok"
    assert "美食" in client.get("/categories").json()
    shops = client.get("/shops", params={"category": "美食"}).json()
    assert shops and all(shop["category"] == "美食" for shop in shops)
    assert client.get("/shops", params={"longitude": 121.44}).status_code == 400
    assert client.get("/shops/s1/slots").json()
    assert client.get("/vouchers", params={"shop_id": "s1"}).json()
    assert client.get("/shops/s1").status_code == 401
    assert client.post("/eval/run").status_code == 404


def test_shared_routers_resolve_services_from_each_application(platform):
    def services(user_id):
        return SimpleNamespace(
            cfg=platform.cfg,
            authenticate=lambda _: {"id": user_id, "role": "user"},
            close=lambda: None,
        )

    first_app = create_app(platform.cfg, platform=services("first-user"))
    second_app = create_app(platform.cfg, platform=services("second-user"))
    with TestClient(first_app) as first, TestClient(second_app) as second:
        assert first.get("/me").json()["id"] == "first-user"
        assert second.get("/me").json()["id"] == "second-user"
        assert first.get("/me").json()["id"] == "first-user"
