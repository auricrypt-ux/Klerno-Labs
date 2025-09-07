# app/paywall.py
import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from .security import expected_api_key

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

PAYWALL_CODE = os.getenv("PAYWALL_CODE", "Labs2025").strip()

@router.get("/paywall", include_in_schema=False)
def paywall(request: Request):
    err = request.query_params.get("err")
    return templates.TemplateResponse("paywall.html", {"request": request, "error": bool(err)})

@router.post("/paywall/verify", include_in_schema=False)
def paywall_verify(code: str = Form(...)):
    accepted = PAYWALL_CODE or (expected_api_key() or "").strip()
    if accepted and code.strip() == accepted:
        api_key = (expected_api_key() or "").strip()
        target = "/dashboard"
        if api_key:
            target = f"/dashboard?key={api_key}"
        resp = RedirectResponse(url=target, status_code=303)
        resp.set_cookie("cw_paid", "1", max_age=60*60*24*30, httponly=True, samesite="lax")
        return resp
    return RedirectResponse(url="/paywall?err=1", status_code=303)

@router.get("/logout", include_in_schema=False)
def logout():
    resp = RedirectResponse(url="/paywall", status_code=303)
    resp.delete_cookie("cw_paid")
    return resp
