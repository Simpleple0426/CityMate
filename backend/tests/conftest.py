import os
import uuid
from pathlib import Path
import pytest
import fakeredis
import redis
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from citymate.config import Settings
from citymate.models import Base, User
from citymate.runtime import build
from citymate.app import create_app


@pytest.fixture
def platform(tmp_path):
    url = os.getenv("CITYMATE_TEST_DATABASE_URL", "sqlite:///" + str(tmp_path / "test.sqlite3"))
    if not url.startswith("sqlite") and make_url(url).database != "citymate_test":
        raise RuntimeError("Integration tests only operate on the dedicated citymate_test database")
    client = (
        redis.Redis.from_url(os.environ["CITYMATE_TEST_REDIS_URL"], decode_responses=True)
        if os.getenv("CITYMATE_TEST_REDIS_URL")
        else fakeredis.FakeRedis(decode_responses=True)
    )
    cfg = Settings(database_url=url, demo=True, uploads=tmp_path / "uploads", api_key="")
    cfg.prefix = "test:{" + uuid.uuid4().hex + "}:"
    p, engine = build(cfg, client)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    p.seed()
    with p.db.begin() as db:
        db.add_all(
            User(id=f"u{i}", phone=f"1380000{i:04d}", nickname=f"User {i}") for i in range(25)
        )
    yield p
    p.close()
    keys = list(client.scan_iter(cfg.prefix + "*"))
    if keys:
        client.delete(*keys)
    Base.metadata.drop_all(engine)
    engine.dispose()
    client.close()


@pytest.fixture
def client(platform):
    with TestClient(
        create_app(platform.cfg, platform=platform), headers={"X-CityMate-Request": "1"}
    ) as c:
        yield c


def login(client, phone="13800000000"):
    result = client.post("/auth/code", json={"phone": phone})
    assert result.status_code == 200, result.text
    result = client.post("/auth/login", json={"phone": phone, "code": result.json()["demo_code"]})
    assert result.status_code == 200, result.text
    cookie = client.cookies.get("citymate_session")
    client.cookies.clear()
    return {"Cookie": "citymate_session=" + cookie}
