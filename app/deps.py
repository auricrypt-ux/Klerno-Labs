from fastapi import Depends, HTTPException, status, Request
from typing import Optional
from . import store
from .security_session import decode_jwt

def current_user(request: Request) -> Optional[dict]:
    token = None
    # prefer cookie
    if "session" in request.cookies:
        token = request.cookies.get("session")
    # allow Authorization: Bearer <jwt> too
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ",1)[1].strip()
    if not token:
        return None
    try:
        data = decode_jwt(token)
        uid = int(data.get("sub"))
        return store.get_user_by_id(uid)
    except Exception:
        return None

def require_user(user = Depends(current_user)):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    return user

def require_paid_or_admin(user = Depends(require_user)):
    if user["role"] == "admin" or user.get("subscription_active"):
        return user
    raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Subscription required")

def require_admin(user = Depends(require_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
