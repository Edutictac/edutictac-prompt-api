import importlib

import httpx
import pytest
from fastapi.testclient import TestClient


class FakeRequest:
    def __init__(self, cookie="edutictac_oidc=central"):
        self.headers = {"cookie": cookie}


@pytest.fixture()
def loaded(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPT_DB_PATH", str(tmp_path / "central.sqlite3"))
    monkeypatch.delenv("PROMPT_DEV_USER", raising=False)
    monkeypatch.setenv("PROMPT_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PROMPT_CENTRAL_SESSION_URL", "http://id-api.internal")
    monkeypatch.setenv("PROMPT_APP_TOKEN", "test-app-token")
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app) as client:
        yield main, client


def mock_client(status=200, payload=None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/internal/session/resolve"
        assert request.headers["authorization"] == "Bearer test-app-token"
        return httpx.Response(status, json=payload or {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_resolves_the_central_subject(loaded):
    main, _ = loaded
    status, user = main.resolve_central_identity(
        FakeRequest(), mock_client(200, {"kind": "oidc", "sub": "hashed-user", "role": "profesor", "display_name": "Docente"})
    )
    assert status == "user"
    assert user == {"sub": "hashed-user", "name": "Docente", "email": ""}


def test_resolves_student_identity(loaded):
    main, _ = loaded
    status, user = main.resolve_central_identity(
        FakeRequest(), mock_client(200, {"kind": "student", "id": "s1", "public_code": "ABC"})
    )
    assert status == "user"
    assert user == {"sub": "student:s1", "name": "ABC", "email": ""}


def test_central_anonymous_and_errors(loaded):
    main, _ = loaded
    assert main.resolve_central_identity(FakeRequest(""), mock_client(200, {"kind": "anonymous"})) == ("anonymous", None)
    assert main.resolve_central_identity(FakeRequest(), mock_client(503, {})) == ("error", None)


def test_central_user_authenticates_both_endpoints(loaded, monkeypatch):
    main, client = loaded
    monkeypatch.setattr(main, "resolve_central_identity", lambda request, client=None: ("user", {"sub": "hashed-user", "name": "Docente", "email": ""}))
    assert client.get("/api/auth/me").json() == {"authenticated": True, "user": {"sub": "hashed-user", "name": "Docente", "email": ""}, "central": True}
    client.put("/api/prompts/p-1", json={"id": "p-1", "title": "T", "prompt": "P", "tags": []})
    assert client.get("/api/prompts").json()["prompts"][0]["ownerId"] == "hashed-user"


def test_central_anonymous_does_not_resurrect_a_local_session(loaded, monkeypatch):
    main, client = loaded
    token = main.session.encode({"sub": "local-user", "name": "Local", "email": ""})
    client.cookies.set(main.SESSION_COOKIE, token)
    monkeypatch.setattr(main, "resolve_central_identity", lambda request, client=None: ("anonymous", None))
    assert client.get("/api/auth/me").json() == {"authenticated": False, "user": None, "central": True}
    assert client.get("/api/prompts").status_code == 401


def test_central_error_falls_back_to_the_local_session(loaded, monkeypatch):
    main, client = loaded
    token = main.session.encode({"sub": "local-user", "name": "Local", "email": ""})
    client.cookies.set(main.SESSION_COOKIE, token)
    monkeypatch.setattr(main, "resolve_central_identity", lambda request, client=None: ("error", None))
    state = client.get("/api/auth/me").json()
    assert state["authenticated"] is True
    assert state["user"]["sub"] == "local-user"
    assert state["central"] is True
