# app/security.py
from __future__ import annotations

import os
import hmac
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException, Request, status
from dotenv import load_dotenv, find_dotenv

# --- Load .env robustly (works from OneDrive, nested folders, etc.) ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = find_dotenv(usecwd=True) or str(PROJECT_ROOT / ".env")
load_dotenv(dotenv_path=DOTENV_PATH, override=False)

# --- File-based key storage (used when ENV key is not set) ---
_DATA_DIR = (PROJECT_ROOT / "data")
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_KEY_FILE = _DATA_DIR / "api_key.secret"
_META_FILE = _DATA_DIR / "api_key.meta"


def expected_api_key() -> str:
    """
    Priority:
      1) ENV: X_API_KEY (or API_KEY)
      2) File: data/api_key.secret (written by admin rotation)
    """
    env = (os.getenv("X_API_KEY") or os.getenv("API_KEY") or "").strip()
    if env:
        return env
    if _KEY_FILE.exists():
        try:
            return _KEY_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    return ""


def _write_api_key(new_key: str) -> None:
    _KEY_FILE.write_text(new_key, encoding="utf-8")
    try:
        _KEY_FILE.chmod(0o600)  # best effort hardening
    except Exception:
        pass
    _META_FILE.write_text(str(int(time.time())), encoding="utf-8")


def generate_api_key(nbytes: int = 32) -> str:
    """Create a url-safe API key (admin can rotate)."""
    return "sk-" + secrets.token_urlsafe(nbytes)


def api_key_last_updated() -> Optional[int]:
    if _META_FILE.exists():
        try:
            return int(_META_FILE.read_text(encoding="utf-8").strip())
        except Exception:
            return None
    return None


async def enforce_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
) -> bool:
    """
    Authorize EITHER:
      • x-api-key header that matches the expected key, OR
      • a valid session (so the web dashboard works without pasting a key)

    Dev-friendly: if no key is configured at all, allow requests.
    """
    exp = expected_api_key()

    # 0) Dev mode: if no key configured, allow.
    if not exp:
        return True

    # 1) Header path for external clients/integrations.
    if x_api_key and hmac.compare_digest(x_api_key.strip(), exp):
        return True

    # 2) Session fallback for browser dashboard (valid JWT cookie).
    try:
        # Lazy import to avoid circular imports at app startup.
        from .deps import require_user  # type: ignore

        try:
            # Many implementations accept Request; if not, call without args.
            _ = require_user(request)  # may raise HTTPException
        except TypeError:
            _ = require_user()  # type: ignore

        return True
    except Exception:
        pass

    # 3) Deny if neither header nor session validated.
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: missing or invalid API key / session",
    )


def rotate_api_key() -> str:
    """Admin-only: generate and persist a new API key (file)."""
    key = generate_api_key()
    _write_api_key(key)
    return key


def preview_api_key() -> dict:
    """Return masked preview + metadata (never the full key)."""
    key = expected_api_key()
    if not key:
        return {"configured": False}
    preview = (key[:4] + "..." + key[-4:]) if len(key) >= 8 else "***"
    return {
        "configured": True,
        "preview": preview,
        "updated_at": api_key_last_updated(),
        "source": "env" if (os.getenv("X_API_KEY") or os.getenv("API_KEY")) else "file",
    }
