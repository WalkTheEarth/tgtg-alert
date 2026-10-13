"""API smoke tests.

Covers the surface the phone app depends on, and the auth boundary -- an
unauthenticated request must not be able to read watches or push to devices.
TGTG itself is never called here.
"""

import pytest
from fastapi.testclient import TestClient

from tgtg_alert.api import create_app
from tgtg_alert.config import Config
from tgtg_alert.db import init_db

TOKEN = "test-token-please-ignore"


@pytest.fixture()
def client(tmp_path):
    config = Config(
        data_dir=tmp_path,
        db_path=tmp_path / "test.db",
        poll_interval=600,
        host="127.0.0.1",
        port=0,
        api_token=TOKEN,
        expo_access_token=None,
        default_language="en-GB",
        request_timeout=5.0,
        log_level="INFO",
        user_agent="TGTG/26.10.0 test",
        dev_mode=False,
        dev_fixture=None,
    )
    init_db(config.db_path)
    app = create_app(config)
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield c


def test_health_needs_no_auth(client):
    response = client.get("/health", headers={"Authorization": ""})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_watches_require_a_token(client):
    assert client.get("/api/watches", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/watches", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/watches", headers={"Authorization": "token abc"}).status_code == 401


def test_empty_state(client):
    assert client.get("/api/watches").json() == []
    assert client.get("/api/devices").json() == []
    assert client.get("/api/alerts").json() == []
    status = client.get("/api/status").json()
    assert status["logged_in"] is False
    assert status["watches"] == 0
    assert status["last_run"] is None


def test_create_and_list_watch(client):
    response = client.post(
        "/api/watches",
        json={
            "label": "Coffee near work",
            "store_pattern": "Blank Street",
            "max_price": 4.5,
            "latitude": 51.5072,
            "longitude": -0.1276,
            "radius_km": 3,
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["id"] == 1
    assert created["store_pattern"] == "Blank Street"
    assert created["max_price"] == 4.5          # round-trips as major units
    assert created["baselined"] is False        # nothing polled yet

    listed = client.get("/api/watches").json()
    assert len(listed) == 1
    assert listed[0]["label"] == "Coffee near work"


def test_watch_validation_rejects_bad_coordinates(client):
    response = client.post(
        "/api/watches",
        json={"latitude": 999, "longitude": 0},
    )
    assert response.status_code == 422


def test_update_watch(client):
    client.post("/api/watches", json={"latitude": 51.5, "longitude": -0.12})
    response = client.patch("/api/watches/1", json={"enabled": False, "radius_km": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["radius_km"] == 2


def test_update_missing_watch_is_404(client):
    assert client.patch("/api/watches/999", json={"enabled": False}).status_code == 404


def test_delete_watch(client):
    client.post("/api/watches", json={"latitude": 51.5, "longitude": -0.12})
    assert client.delete("/api/watches/1").status_code == 204
    assert client.get("/api/watches").json() == []
    assert client.delete("/api/watches/1").status_code == 404


def test_register_device_is_idempotent_and_hides_token(client):
    payload = {"expo_push_token": "ExponentPushToken[abc123]", "platform": "ios", "label": "iPhone"}
    first = client.post("/api/devices", json=payload)
    assert first.status_code == 201
    second = client.post("/api/devices", json=payload)
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    devices = client.get("/api/devices").json()
    assert len(devices) == 1
    # The token is a capability; listing must not hand it back.
    assert "expo_push_token" not in devices[0]
    assert "abc123" not in devices[0]["token_hint"]


def test_delete_device(client):
    client.post("/api/devices", json={"expo_push_token": "ExponentPushToken[zzz]"})
    assert client.delete("/api/devices/1").status_code == 204
    assert client.get("/api/devices").json() == []


def test_test_notify_without_devices_is_409(client):
    assert client.post("/api/test-notify").status_code == 409


def test_preview_without_login_is_409(client):
    response = client.post("/api/preview", json={"latitude": 51.5, "longitude": -0.12})
    assert response.status_code == 409
    assert "logged in" in response.json()["detail"]
