from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from edutictac_community.db import connect
from edutictac_community.oidc import OIDCClient
from edutictac_community.session import SignedSession
from fastapi import Cookie, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

DB_PATH = os.environ.get("PROMPT_DB_PATH", "data/prompts.sqlite3")
APP_URL = os.environ.get("PROMPT_APP_URL", "http://localhost:5173").rstrip("/")
API_URL = os.environ.get("PROMPT_API_URL", "http://localhost:8012").rstrip("/")
SESSION_COOKIE = "edutictac_prompt_session"
STATE_COOKIE = "edutictac_prompt_oidc_state"
COOKIE_SECURE = os.environ.get("PROMPT_COOKIE_SECURE", "1") != "0"
DEV_USER = os.environ.get("PROMPT_DEV_USER", "").strip()

db_path = Path(DB_PATH)
db_path.parent.mkdir(parents=True, exist_ok=True)
session = SignedSession(
    os.environ.get("PROMPT_SESSION_SECRET", ""), SESSION_COOKIE,
    cookie_secure=COOKIE_SECURE,
)
oidc = OIDCClient(
    os.environ.get("OIDC_CLIENT_ID", ""),
    os.environ.get("OIDC_CLIENT_SECRET", ""),
    os.environ.get("OIDC_ISSUER", ""),
    os.environ.get("OIDC_REDIRECT_URI", f"{API_URL}/api/auth/callback"),
    scope=os.environ.get("OIDC_SCOPE", "openid profile email"),
    session_secret=os.environ.get("PROMPT_SESSION_SECRET", ""),
    state_cookie_name=STATE_COOKIE,
    user_agent="EduTicTac-Prompt-API/0.1",
)

app = FastAPI(title="EduTicTac Prompt API", version="0.2.0")
logger = logging.getLogger("edutictac.prompt.auth")
origins = [x.strip().rstrip("/") for x in os.environ.get("PROMPT_CORS_ORIGINS", APP_URL).split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "PUT", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with connect(str(db_path)) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS prompts (
                owner_id TEXT NOT NULL,
                prompt_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (owner_id, prompt_id)
            )"""
        )
        conn.commit()


init_db()


def current_user(request: Request) -> dict[str, str]:
    if DEV_USER:
        return {"sub": DEV_USER, "name": "Development user", "email": ""}
    value = session.decode(request.cookies.get(SESSION_COOKIE))
    if not value or not value.get("sub"):
        raise HTTPException(status_code=401, detail="authentication required")
    return {"sub": str(value["sub"]), "name": str(value.get("name", "")), "email": str(value.get("email", ""))}


def safe_return_url(value: str) -> str:
    parsed = urlparse(value or APP_URL)
    if parsed.scheme not in {"http", "https"} or parsed.netloc not in {urlparse(APP_URL).netloc}:
        return APP_URL
    return value


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/login")
def auth_login(next_url: str = Query("", alias="next")) -> Response:
    if not oidc.enabled():
        raise HTTPException(status_code=503, detail="oidc not configured")
    url, state = oidc.build_login_url()
    response = RedirectResponse(url)
    response.set_cookie(STATE_COOKIE, state, httponly=True, secure=COOKIE_SECURE, samesite="lax", path="/api/auth", max_age=600)
    response.set_cookie("edutictac_prompt_next", safe_return_url(next_url), httponly=True, secure=COOKIE_SECURE, samesite="lax", path="/", max_age=600)
    return response


@app.get("/api/auth/callback")
def auth_callback(request: Request, code: str = "", state: str = "") -> Response:
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code or state")
    try:
        state_cookie = request.cookies.get(STATE_COOKIE)
        decoded_state = oidc._decode(state_cookie)
        logger.info("OIDC callback state cookie present=%s matches=%s", bool(state_cookie), bool(decoded_state and decoded_state.get("state") == state))
        info = oidc.handle_callback(state, code, state_cookie)
    except Exception as exc:
        # Log only the exception class: never log authorization codes, tokens or cookies.
        reason = getattr(exc, "error", None) or (str(exc) if isinstance(exc, ValueError) else "oauth error")
        logger.warning("OIDC callback failed (%s): %s", type(exc).__name__, reason[:80])
        raise HTTPException(status_code=400, detail="oidc callback failed") from exc
    response = RedirectResponse(safe_return_url(request.cookies.get("edutictac_prompt_next", APP_URL)))
    session.set_cookie(response, {"sub": info["sub"], "name": info.get("name", ""), "email": info.get("email", "")}, max_age=60 * 60 * 24 * 30)
    response.delete_cookie(STATE_COOKIE, path="/api/auth")
    response.delete_cookie("edutictac_prompt_next", path="/")
    return response


@app.get("/api/auth/logout")
def auth_logout() -> Response:
    response = RedirectResponse(APP_URL)
    session.delete_cookie(response)
    return response


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    if DEV_USER:
        return {"authenticated": True, "user": current_user(request)}
    value = session.decode(request.cookies.get(SESSION_COOKIE))
    if not value or not value.get("sub"):
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": {"sub": value["sub"], "name": value.get("name", ""), "email": value.get("email", "")}}


@app.get("/api/prompts")
def list_prompts(request: Request, since: str = "") -> dict[str, list[dict[str, Any]]]:
    user = current_user(request)
    with connect(str(db_path)) as conn:
        rows = conn.execute("SELECT payload FROM prompts WHERE owner_id = ? AND updated_at > ? ORDER BY updated_at", (user["sub"], since)).fetchall()
    return {"prompts": [json.loads(row[0]) for row in rows]}


@app.put("/api/prompts/{prompt_id}")
async def save_prompt(prompt_id: str, request: Request) -> dict[str, Any]:
    user = current_user(request)
    payload = await request.json()
    if not isinstance(payload, dict) or payload.get("id") != prompt_id or not payload.get("title") or not payload.get("prompt"):
        raise HTTPException(status_code=400, detail="invalid prompt")
    payload = {**payload, "id": prompt_id, "ownerId": user["sub"], "remoteId": prompt_id, "syncStatus": "synced", "lastSyncedAt": now()}
    updated_at = str(payload.get("updatedAt") or now())
    with connect(str(db_path)) as conn:
        conn.execute("INSERT INTO prompts(owner_id,prompt_id,updated_at,payload) VALUES(?,?,?,?) ON CONFLICT(owner_id,prompt_id) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload", (user["sub"], prompt_id, updated_at, json.dumps(payload, ensure_ascii=False)))
        conn.commit()
    return payload


@app.delete("/api/prompts/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: str, request: Request) -> Response:
    user = current_user(request)
    with connect(str(db_path)) as conn:
        conn.execute("DELETE FROM prompts WHERE owner_id = ? AND prompt_id = ?", (user["sub"], prompt_id))
        conn.commit()
    return Response(status_code=204)


from app.skills import install_skills
install_skills(app, connect, db_path, current_user, origins, now)
