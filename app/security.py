# app/security.py
import os
import hmac
from pathlib import Path

from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from dotenv import load_dotenv, find_dotenv

# --- Load .env robustly (works from OneDrive, nested folders, etc.) ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = find_dotenv(usecwd=True) or str(PROJECT_ROOT / ".env")
load_dotenv(dotenv_path=DOTENV_PATH, override=False)

# The incoming header we expect from clients
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

def expected_api_key() -> str:
    """
    The API key the server should accept.
    Prefer X_API_KEY; fall back to API_KEY; trim whitespace.
    """
    return (os.getenv("X_API_KEY") or os.getenv("API_KEY") or "").strip()

async def enforce_api_key(api_key: str = Security(api_key_header)) -> bool:
    """
    Allow the request only if x-api-key matches the expected key.
    Uses constant-time compare to avoid timing attacks.
    """
    exp = expected_api_key()
    if not exp:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server missing X_API_KEY or API_KEY. Set it in your .env and restart.",
        )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Add header: x-api-key",
        )

    if hmac.compare_digest(api_key.strip(), exp):
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key. Add header: x-api-key",
    )
