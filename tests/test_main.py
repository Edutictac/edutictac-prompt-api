import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPT_DB_PATH", str(tmp_path / "prompts.sqlite3"))
    monkeypatch.setenv("PROMPT_DEV_USER", "user-1")
    import importlib
    import app.main as main
    importlib.reload(main)
    return TestClient(main.app)


def prompt(prompt_id="p-1"):
    return {"id": prompt_id, "title": "Mi prompt", "prompt": "Diseña una actividad", "tags": [], "updatedAt": "2026-09-23T10:00:00+00:00"}


def test_health_and_dev_identity(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/auth/me").json()["user"]["sub"] == "user-1"


def test_prompt_roundtrip_and_delete(client):
    saved = client.put("/api/prompts/p-1", json=prompt()).json()
    assert saved["syncStatus"] == "synced"
    assert client.get("/api/prompts").json()["prompts"][0]["id"] == "p-1"
    assert client.delete("/api/prompts/p-1").status_code == 204
    assert client.get("/api/prompts").json() == {"prompts": []}


def test_prompt_owner_is_not_client_controlled(client):
    data = prompt()
    data["ownerId"] = "another-user"
    assert client.put("/api/prompts/p-1", json=data).json()["ownerId"] == "user-1"


def test_requires_authentication(monkeypatch, client):
    import app.main as main
    main.DEV_USER = ""
    assert client.get("/api/prompts").status_code == 401


def test_rejects_invalid_prompt(client):
    assert client.put("/api/prompts/p-1", json={"id": "p-1", "prompt": "sin título"}).status_code == 400
    assert client.put("/api/prompts/p-1", json={"id": "other", "title": "x", "prompt": "y"}).status_code == 400


def test_since_only_returns_newer_prompts(client):
    client.put("/api/prompts/old", json=prompt("old") | {"updatedAt": "2026-09-22T10:00:00+00:00"})
    client.put("/api/prompts/new", json=prompt("new") | {"updatedAt": "2026-09-24T10:00:00+00:00"})
    result = client.get("/api/prompts?since=2026-09-23T00:00:00+00:00").json()["prompts"]
    assert [item["id"] for item in result] == ["new"]


def test_users_cannot_read_each_other_prompts(monkeypatch, client):
    import app.main as main
    client.put("/api/prompts/private", json=prompt("private"))
    main.DEV_USER = "user-2"
    assert client.get("/api/prompts").json() == {"prompts": []}
    assert client.delete("/api/prompts/private").status_code == 204
    main.DEV_USER = "user-1"
    assert client.get("/api/prompts").json()["prompts"][0]["id"] == "private"
