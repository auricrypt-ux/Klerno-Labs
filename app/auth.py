from fastapi import APIRouter, Response, Depends, HTTPException, status, Body
from pydantic import BaseModel, EmailStr
import os
from . import store
from .security_session import hash_pw, verify_pw, issue_jwt
from .deps import require_user, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])

ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
DEMO_MODE   = (os.getenv("DEMO_MODE","false").lower() == "true")

class SignupReq(BaseModel):
    email: EmailStr
    password: str

class LoginReq(BaseModel):
    email: EmailStr
    password: str

@router.post("/signup")
def signup(payload: SignupReq, res: Response):
    email = payload.email.lower().strip()
    if store.get_user_by_email(email):
        raise HTTPException(status_code=400, detail="User exists")
    # bootstrap: first admin or ENV admin email gets admin + active subscription
    role = "viewer"
    sub_active = False
    if email == ADMIN_EMAIL or store.users_count() == 0:
        role = "admin"; sub_active = True
    user = store.create_user(email, hash_pw(payload.password), role=role, subscription_active=sub_active)
    token = issue_jwt(user["id"], user["email"], user["role"])
    res.set_cookie("session", token, httponly=True, secure=False, samesite="lax", max_age=60*60*24*7)
    return {"ok": True, "user": {"email": user["email"], "role": user["role"], "subscription_active": user["subscription_active"]}}

@router.post("/login")
def login(payload: LoginReq, res: Response):
    email = payload.email.lower().strip()
    user = store.get_user_by_email(email)
    if not user or not verify_pw(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = issue_jwt(user["id"], user["email"], user["role"])
    res.set_cookie("session", token, httponly=True, secure=False, samesite="lax", max_age=60*60*24*7)
    return {"ok": True, "user": {"email": user["email"], "role": user["role"], "subscription_active": user["subscription_active"]}}

@router.post("/logout")
def logout(res: Response, user = Depends(require_user)):
    res.delete_cookie("session")
    return {"ok": True}

@router.get("/me")
def me(user = Depends(require_user)):
    return {"email": user["email"], "role": user["role"], "subscription_active": user["subscription_active"]}

# ---- DEV helpers while Stripe isn't live ----
@router.post("/mock/activate")
def mock_activate(user = Depends(require_user)):
    """Simulate a paid subscription for the current user."""
    if user["role"] == "admin" or DEMO_MODE:
        store.set_subscription_active(user["email"], True)
        return {"ok": True, "activated": True}
    raise HTTPException(status_code=403, detail="Only admin/demo can mock")
