# app/paywall_hooks.py
import os
import importlib
from typing import Any, Optional

from fastapi import APIRouter, Request, HTTPException
from . import store  # ← fixed: was `from .. import store`

router = APIRouter(prefix="/paywall", tags=["paywall"])

def _stripe() -> Optional[Any]:
    """
    Lazy loader for the Stripe SDK that won't trigger static 'missing import'
    warnings if stripe isn't installed yet.
    """
    try:
        stripe_sdk = importlib.import_module("stripe")
        stripe_sdk.api_key = (os.getenv("STRIPE_SECRET_KEY", "") or "").strip()
        return stripe_sdk
    except Exception:
        return None

@router.post("/create-checkout-session")
async def create_checkout_session(req: Request):
    stripe_sdk = _stripe()
    price_id = (os.getenv("STRIPE_PRICE_ID", "") or "").strip()
    if not stripe_sdk or not price_id:
        raise HTTPException(status_code=501, detail="Stripe not configured")

    data = await req.json()
    email = (data.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    base = str(req.base_url)  # usually ends with '/'
    session = stripe_sdk.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=email,
        success_url=f"{base}create-account?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base}?canceled=1",
    )
    return {"id": session.id, "url": session.url}

@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    stripe_sdk = _stripe()
    if not stripe_sdk:
        raise HTTPException(status_code=501, detail="Stripe not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature") or ""
    secret = (os.getenv("STRIPE_WEBHOOK_SECRET", "") or "").strip()
    if not sig_header or not secret:
        raise HTTPException(status_code=400, detail="missing webhook signature or secret")

    try:
        event = stripe_sdk.Webhook.construct_event(payload, sig_header, secret)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if event.get("type") in ("checkout.session.completed", "customer.subscription.updated"):
        session = event["data"]["object"]
        email = (session.get("customer_details", {}) or {}).get("email") or session.get("customer_email")
        if email:
            email_l = email.lower()
            # upsert user if not exists; activate subscription
            u = store.get_user_by_email(email_l)
            if not u:
                from .security_session import hash_pw
                store.create_user(email_l, hash_pw(os.urandom(8).hex()), role="viewer", subscription_active=True)
            else:
                store.set_subscription_active(email_l, True)

    return {"received": True}
