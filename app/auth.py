from fastapi import APIRouter, Response, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from . import store
from .security_session import hash_pw, verify_pw, issue_jwt
from .deps import require_user
from .settings import get_settings, Settings

router = APIRouter(prefix="/auth", tags=["auth"])

# Single source of truth for config
S: Settings = get_settings()

# ---------- Schemas ----------
class SignupReq(BaseModel):
    email: EmailStr
    password: str

class LoginReq(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    email: EmailStr
    role: str
    subscription_active: bool

class AuthResponse(BaseModel):
    ok: bool
    user: UserOut

# ---------- Helpers ----------
def _set_session_cookie(res: Response, token: str) -> None:
    """Set the session cookie with sane defaults."""
    res.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=(S.app_env != "dev"),   # HTTPS in staging/prod
        samesite="lax",                # use "none" if cross-site SPA
        max_age=60 * 60 * 24 * 7,      # 7 days
        path="/",
    )

# ---------- Routes ----------
@router.post("/signup", response_model=AuthResponse, status_code=201)
def signup(payload: SignupReq, res: Response):
    email = payload.email.lower().strip()

    if store.get_user_by_email(email):
        # Avoid leaking too much; 409 is the conventional code here
        raise HTTPException(status_code=409, detail="User already exists")

    # bootstrap: first user or ENV admin becomes admin + active subscription
    role = "viewer"
    sub_active = False
    if email == S.admin_email or store.users_count() == 0:
        role, sub_active = "admin", True

    user = store.create_user(
        email=email,
        password_hash=hash_pw(payload.password),
        role=role,
        subscription_active=sub_active,
    )
    token = issue_jwt(user["id"], user["email"], user["role"])
    _set_session_cookie(res, token)

    return {"ok": True, "user": {"email": user["email"], "role": user["role"], "subscription_active": user["subscription_active"]}}

@router.post("/login", response_model=AuthResponse)
def login(payload: LoginReq, res: Response):
    email = payload.email.lower().strip()
    user = store.get_user_by_email(email)

    if not user or not verify_pw(payload.password, user["password_hash"]):
        # Generic message prevents user enumeration
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = issue_jwt(user["id"], user["email"], user["role"])
    _set_session_cookie(res, token)

    return {"ok": True, "user": {"email": user["email"], "role": user["role"], "subscription_active": user["subscription_active"]}}

@router.post("/logout", status_code=204)
def logout(res: Response, user=Depends(require_user)):
    res.delete_cookie("session", path="/")
    # 204 No Content
    return Response(status_code=204)

@router.get("/me", response_model=UserOut)
def me(user=Depends(require_user)):
    return {"email": user["email"], "role": user["role"], "subscription_active": user["subscription_active"]}

# ---- DEV helpers while Stripe isn't live ----
@router.post("/mock/activate")
def mock_activate(user=Depends(require_user)):
    """Simulate a paid subscription for the current user."""
    if user["role"] == "admin" or S.demo_mode:
        store.set_subscription_active(user["email"], True)
        return {"ok": True, "activated": True}
    raise HTTPException(status_code=403, detail="Only admin/demo can mock")
