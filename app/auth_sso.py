# app/auth_sso.py
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
import os
from . import store
from .security_session import issue_jwt

router = APIRouter(tags=["auth:sso"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
oauth.register(
    name="microsoft",
    client_id=os.getenv("MS_CLIENT_ID"),
    client_secret=os.getenv("MS_CLIENT_SECRET"),
    server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

def _set_cookie(resp: RedirectResponse, request: Request, jwt: str):
    from .main import _cookie_kwargs, SESSION_COOKIE
    resp.set_cookie(SESSION_COOKIE, jwt, **_cookie_kwargs(request))

@router.get("/login/google")
async def login_google(request: Request):
    return await oauth.google.authorize_redirect(request, request.url_for("auth_google_cb"))

@router.get("/auth/google/callback", name="auth_google_cb")
async def auth_google_cb(request: Request):
    tok = await oauth.google.authorize_access_token(request)
    ui = tok.get("userinfo") or {}
    email = (ui.get("email") or "").lower().strip()
    if not email: return RedirectResponse("/login?error=google")
    user = store.get_user_by_email(email) or store.create_user(email, password_hash="", role="viewer", subscription_active=True)
    jwt = issue_jwt(user["id"], user["email"], user["role"])
    resp = RedirectResponse("/dashboard", status_code=303); _set_cookie(resp, request, jwt); return resp

@router.get("/login/microsoft")
async def login_ms(request: Request):
    return await oauth.microsoft.authorize_redirect(request, request.url_for("auth_ms_cb"))

@router.get("/auth/microsoft/callback", name="auth_ms_cb")
async def auth_ms_cb(request: Request):
    tok = await oauth.microsoft.authorize_access_token(request)
    ui = tok.get("userinfo") or tok.get("id_token_claims") or {}
    email = (ui.get("email") or ui.get("preferred_username") or "").lower().strip()
    if not email: return RedirectResponse("/login?error=microsoft")
    user = store.get_user_by_email(email) or store.create_user(email, password_hash="", role="viewer", subscription_active=True)
    jwt = issue_jwt(user["id"], user["email"], user["role"])
    resp = RedirectResponse("/dashboard", status_code=303); _set_cookie(resp, request, jwt); return resp
