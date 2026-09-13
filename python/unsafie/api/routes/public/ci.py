import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from unsafie import cluster
from unsafie.api.dependencies.auth import COOKIE as ADMIN_COOKIE
from unsafie.api.dependencies.auth import verify as verify_admin
from unsafie.database import SessionLocal
from unsafie.database.repositories.ci import CiRepository
from unsafie.database.repositories.github import GithubAppRepository
from unsafie.github.ci import service as ci_service
from unsafie.github.client.base import session as http_session
from unsafie.log import get_logger
from unsafie.settings import settings

logger = get_logger(__name__)

router = APIRouter(prefix="/api/ci", tags=["ci"])

CI_COOKIE = "unsafie_ci_session"
LOGS_DIR = Path("/var/lib/unsafie/ci/logs")

def _ci_callback_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "ci.unsafie.com"
    proto = request.headers.get("x-forwarded-proto") or "https"
    return f"{proto}://{host}/api/ci/auth/callback"

def _sign_session(login: str, avatar: str = "") -> str:
    exp = int(time.time()) + 30 * 86400
    payload = f"{login.lower()}:{exp}:{avatar}"
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode().rstrip("=")

def _verify_session(cookie: str | None) -> tuple[str, str] | None:
    if not cookie:
        return None
    try:
        raw = base64.urlsafe_b64decode(cookie + "=" * (-len(cookie) % 4)).decode()
        login, exp_str, avatar, sig = raw.rsplit(":", 3)
    except Exception:
        return None
    if int(exp_str) < time.time():
        return None
    expected_sig = hmac.new(settings.secret_key.encode(), f"{login}:{exp_str}:{avatar}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    return login, avatar

async def get_current_ci_user(request: Request) -> str:
    if verify_admin(request.cookies.get(ADMIN_COOKIE)):
        return "admin"

    auth_hdr = request.headers.get("authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        token = auth_hdr[7:].strip()
        if token.startswith("uci_live_"):
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            async with SessionLocal() as session:
                tok_row = await CiRepository(session).get_api_token(token_hash)
                if tok_row:
                    is_white = await CiRepository(session).is_whitelisted(tok_row.github_login)
                    if is_white:
                        return tok_row.github_login

    sess = _verify_session(request.cookies.get(CI_COOKIE))
    if sess:
        login, _ = sess
        async with SessionLocal() as session:
            if await CiRepository(session).is_whitelisted(login):
                return login

    raise HTTPException(401, "unauthorized or not in ci whitelist")

CurrentUser = Annotated[str, Depends(get_current_ci_user)]

class SecretSetRequest(BaseModel):
    key: str
    value: str

class TokenCreateRequest(BaseModel):
    name: str

@router.get("/auth/me")
async def get_me(request: Request):
    if verify_admin(request.cookies.get(ADMIN_COOKIE)):
        return {"authenticated": True, "login": "admin", "whitelisted": True, "avatar_url": ""}
    sess = _verify_session(request.cookies.get(CI_COOKIE))
    if not sess:
        return {"authenticated": False, "login": None, "whitelisted": False}
    login, avatar = sess
    async with SessionLocal() as session:
        is_white = await CiRepository(session).is_whitelisted(login)
    return {
        "authenticated": True,
        "login": login,
        "whitelisted": is_white,
        "avatar_url": avatar,
    }

@router.get("/auth/github")
async def auth_github(request: Request, redirect: str = "/ci"):
    async with SessionLocal() as session:
        app_row = await GithubAppRepository(session).get()
    if not app_row or not app_row.client_id:
        raise HTTPException(500, "GitHub App OAuth is not configured")
    params = {
        "client_id": app_row.client_id,
        "redirect_uri": _ci_callback_url(request),
        "state": redirect,
        "scope": "read:user",
    }
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{urlencode(params)}")

@router.get("/auth/callback")
async def auth_callback(request: Request, code: str, state: str = "/ci"):
    async with SessionLocal() as session:
        app_row = await GithubAppRepository(session).get()
    if not app_row or not app_row.client_id or not app_row.client_secret:
        raise HTTPException(500, "GitHub App credentials missing")

    http = await http_session()
    async with http.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": app_row.client_id,
            "client_secret": app_row.client_secret,
            "code": code,
        },
    ) as token_resp:
        token_data = await token_resp.json(content_type=None)
        access_token = token_data.get("access_token")

    if not access_token:
        raise HTTPException(400, "failed to exchange oauth code")

    async with http.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}", "User-Agent": "unsafie-ci"},
    ) as user_resp:
        gh_user = await user_resp.json(content_type=None)

    login = gh_user.get("login") or ""
    avatar = gh_user.get("avatar_url") or ""

    async with SessionLocal() as session:
        is_white = await CiRepository(session).is_whitelisted(login)

    if not is_white:
        return RedirectResponse(f"/access-denied?login={login}&avatar={avatar}")

    cookie_val = _sign_session(login, avatar)
    target_url = state if state.startswith("/") else "/ci"
    response = RedirectResponse(target_url)
    response.set_cookie(CI_COOKIE, cookie_val, max_age=30 * 86400, httponly=True, samesite="lax")
    return response

@router.post("/auth/logout")
async def auth_logout():
    resp = Response(content=json.dumps({"ok": True}), media_type="application/json")
    resp.delete_cookie(CI_COOKIE)
    return resp

@router.get("/runs")
async def list_runs(
    user: CurrentUser,
    repo: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    async with SessionLocal() as session:
        runs = await CiRepository(session).list_runs(repo, limit=min(limit, 100), offset=offset)
        return [
            {
                "id": r.id,
                "repo_full_name": r.repo_full_name,
                "commit_sha": r.commit_sha,
                "ref": r.ref,
                "branch": r.branch,
                "is_default_branch": r.is_default_branch,
                "check_run_id": r.check_run_id,
                "status": r.status,
                "trigger_event": r.trigger_event,
                "sender": r.sender,
                "commit_message": r.commit_message,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "exit_code": r.exit_code,
                "current_stage": r.current_stage,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ]

@router.get("/runs/{run_id}")
async def get_run(run_id: int, user: CurrentUser):
    async with SessionLocal() as session:
        r = await CiRepository(session).get_run(run_id)
        if not r:
            raise HTTPException(404, "run not found")
        return {
            "id": r.id,
            "repo_full_name": r.repo_full_name,
            "commit_sha": r.commit_sha,
            "ref": r.ref,
            "branch": r.branch,
            "is_default_branch": r.is_default_branch,
            "check_run_id": r.check_run_id,
            "status": r.status,
            "trigger_event": r.trigger_event,
            "sender": r.sender,
            "commit_message": r.commit_message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "exit_code": r.exit_code,
            "current_stage": r.current_stage,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat(),
        }

@router.post("/runs/{run_id}/rerun")
async def rerun(run_id: int, user: CurrentUser):
    new_run = await ci_service.rerequest_run(run_id, triggered_by=user)
    if not new_run:
        raise HTTPException(404, "run not found")
    return {"ok": True, "run_id": new_run.id}

@router.get("/runs/{run_id}/metrics")
async def get_run_metrics(run_id: int, user: CurrentUser):
    async with SessionLocal() as session:
        metrics = await CiRepository(session).get_metrics(run_id)
        return [
            {
                "time": m.recorded_at.isoformat(),
                "cpu": m.cpu_percent,
                "rss": m.memory_rss_mb,
                "rx": m.network_rx_kbps,
                "tx": m.network_tx_kbps,
            }
            for m in metrics
        ]

@router.get("/runs/{run_id}/logs/raw")
async def get_raw_logs(run_id: int, user: CurrentUser):
    log_file = LOGS_DIR / f"{run_id}.log"
    if not log_file.is_file():
        raise HTTPException(404, "log not found")
    return PlainTextResponse(log_file.read_text(encoding="utf-8", errors="replace"))

@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: int, request: Request):
    await get_current_ci_user(request)
    log_file = LOGS_DIR / f"{run_id}.log"

    async def _generator():
        offset = 0
        if log_file.is_file():
            try:
                data = log_file.read_bytes()
                offset = len(data)
                yield f"data: {json.dumps({'type': 'init', 'log': data.decode('utf-8', 'replace')})}\n\n"
            except Exception:
                pass

        pubsub = cluster.client().pubsub()
        await pubsub.subscribe(f"ci:run:{run_id}:stream")
        try:
            while True:
                if await request.is_disconnected():
                    break
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("data"):
                    payload = msg["data"]
                    if isinstance(payload, bytes):
                        payload = payload.decode("utf-8", "replace")
                    yield f"data: {payload}\n\n"

                async with SessionLocal() as session:
                    run = await CiRepository(session).get_run(run_id)
                    if run and run.status in ("success", "failure", "crash", "cancelled"):
                        if log_file.is_file():
                            cur_data = log_file.read_bytes()
                            if len(cur_data) > offset:
                                new_chunk = cur_data[offset:].decode("utf-8", "replace")
                                yield f"data: {json.dumps({'type': 'log', 'chunk': new_chunk})}\n\n"
                        yield f"data: {json.dumps({'type': 'status', 'status': run.status, 'exit_code': run.exit_code})}\n\n"
                        break
        finally:
            await pubsub.unsubscribe(f"ci:run:{run_id}:stream")

    return StreamingResponse(_generator(), media_type="text/event-stream")

@router.get("/secrets/{owner}/{repo}")
async def list_secrets(owner: str, repo: str, user: CurrentUser):
    repo_full_name = f"{owner}/{repo}"
    async with SessionLocal() as session:
        items = await CiRepository(session).list_secrets(repo_full_name)
        return [
            {
                "key": item.key,
                "updated_by": item.updated_by,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in items
        ]

@router.post("/secrets/{owner}/{repo}")
async def set_secret(owner: str, repo: str, req: SecretSetRequest, user: CurrentUser):
    repo_full_name = f"{owner}/{repo}"
    key = req.key.strip()
    if not key:
        raise HTTPException(400, "key required")
    async with SessionLocal() as session:
        await CiRepository(session).set_secret(repo_full_name, key, req.value, updated_by=user)
    return {"ok": True, "key": key}

@router.put("/secrets/{owner}/{repo}/bulk")
async def set_secrets_bulk(owner: str, repo: str, request: Request, user: CurrentUser):
    repo_full_name = f"{owner}/{repo}"
    content_type = request.headers.get("content-type") or ""
    body = await request.body()
    text = body.decode("utf-8", "replace")

    secrets_dict: dict[str, str] = {}
    if "application/json" in content_type:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                secrets_dict = {str(k): str(v) for k, v in data.items()}
        except Exception as err:
            raise HTTPException(400, "invalid json") from err
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            k, sep, v = line.partition("=")
            if sep:
                k = k.strip()
                v = v.strip().strip("'").strip('"')
                if k:
                    secrets_dict[k] = v

    if not secrets_dict:
        raise HTTPException(400, "no valid secrets found in payload")

    async with SessionLocal() as session:
        repo_obj = CiRepository(session)
        for k, v in secrets_dict.items():
            await repo_obj.set_secret(repo_full_name, k, v, updated_by=user)

    return {"ok": True, "count": len(secrets_dict), "keys": list(secrets_dict.keys())}

@router.delete("/secrets/{owner}/{repo}/{key}")
async def delete_secret(owner: str, repo: str, key: str, user: CurrentUser):
    repo_full_name = f"{owner}/{repo}"
    async with SessionLocal() as session:
        ok = await CiRepository(session).delete_secret(repo_full_name, key)
    return {"ok": ok}

@router.get("/tokens")
async def list_tokens(user: CurrentUser):
    async with SessionLocal() as session:
        tokens = await CiRepository(session).list_api_tokens(user)
        return [
            {
                "id": t.id,
                "name": t.name,
                "prefix": t.token_prefix,
                "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
                "created_at": t.created_at.isoformat(),
            }
            for t in tokens
        ]

@router.post("/tokens")
async def create_token(req: TokenCreateRequest, user: CurrentUser):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "token name required")
    raw_secret = secrets.token_hex(24)
    full_token = f"uci_live_{raw_secret}"
    token_hash = hashlib.sha256(full_token.encode()).hexdigest()
    prefix = f"uci_live_{raw_secret[:6]}..."
    async with SessionLocal() as session:
        item = await CiRepository(session).create_api_token(user, name, token_hash, prefix)
    return {
        "ok": True,
        "token": full_token,
        "id": item.id,
        "name": item.name,
        "prefix": item.token_prefix,
    }

@router.delete("/tokens/{token_id}")
async def delete_token(token_id: int, user: CurrentUser):
    async with SessionLocal() as session:
        ok = await CiRepository(session).delete_api_token(user, token_id)
    return {"ok": ok}
