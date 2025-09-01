# app/security.py
import os
import hmac
from pathlib import Path
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from dotenv import load_dotenv, find_dotenv

# --- Load .env robustly (works from OneDrive, subfolders, etc.) ---
# Try to find a .env starting from the current working dir;
# if not found, fall back to the project root: one level above /app
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = find_dotenv(usecwd=True) or str(PROJECT_ROOT / ".env")
load_dotenv(dotenv_path=DOTENV_PATH, override=False)

# Swagger/OpenAPI name for the header
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

def expected_api_key() -> str:
    """Return the API key the server loaded from the environment (trimmed)."""
    return (os.getenv("API_KEY") or "").strip()

async def enforce_api_key(api_key: str = Security(api_key_header)) -> bool:
    """
    Allow the request only if x-api-key matches .env:API_KEY.
    Uses constant-time compare to avoid timing leaks.
    """
    exp = expected_api_key()
    if not exp:
        # Server-side misconfig: we didn't load any API_KEY
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server missing API_KEY. Set API_KEY=... in your .env and restart the server."
        )
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Add header: x-api-key",
        )

    # Normalize whitespace just in case
    api_key = api_key.strip()

    if hmac.compare_digest(api_key, exp):
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key. Add header: x-api-key",
    )
