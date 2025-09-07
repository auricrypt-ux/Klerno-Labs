# app/settings.py
import os
from functools import lru_cache

class Settings:
    # Env is read at import time; fine for simple configs
    app_env = os.getenv("APP_ENV", "dev")
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"

    # Auth
    jwt_secret = os.getenv("JWT_SECRET", "CHANGE_ME_32+")
    access_token_expire_minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    admin_email = os.getenv("ADMIN_EMAIL", "klerno@outlook.com")

    # Paywall/Stripe
    paywall_code = os.getenv("PAYWALL_CODE", "Labs2025")
    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_price_id = os.getenv("STRIPE_PRICE_ID", "")
    stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # OpenAI
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Email
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "")
    alert_email_from = os.getenv("ALERT_EMAIL_FROM", "alerts@example.com")
    alert_email_to = os.getenv("ALERT_EMAIL_TO", "you@example.com")

    # Risk/XRPL
    api_key = os.getenv("API_KEY", "dev-api-key")
    risk_threshold = float(os.getenv("RISK_THRESHOLD", "0.75"))
    xrpl_rpc_url = os.getenv("XRPL_RPC_URL", "https://s2.ripple.com:51234")

@lru_cache
def get_settings() -> Settings:
    return Settings()
