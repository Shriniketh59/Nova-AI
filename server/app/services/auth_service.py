import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt

from ..core.config import (
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRES_DAYS,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)
from ..core.logger import logger


def hash_password(password: str) -> str:
    """Hash a password using memory-hard scrypt with unique salt."""
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    key_b64 = base64.b64encode(key).decode("ascii")
    return f"scrypt:16384:8:1${salt_b64}${key_b64}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against an scrypt hash or fallback."""
    if not hashed or not password:
        return False
    try:
        parts = hashed.split("$")
        if len(parts) == 3 and parts[0].startswith("scrypt:"):
            _, n, r, p = parts[0].split(":")
            salt = base64.b64decode(parts[1])
            key = base64.b64decode(parts[2])
            candidate = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(key),
            )
            return hmac.compare_digest(candidate, key)
        # Development fallback for initial test accounts if unhashed
        return hmac.compare_digest(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception as err:
        logger.error(f"Error during password verification: {err}")
        return False


def create_access_token(user_id: str, email: str) -> str:
    """Create a signed JWT access token."""
    now = time.time()
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now),
        "exp": int(now + (JWT_EXPIRES_DAYS * 86400)),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def generate_reset_token() -> str:
    """Generate a secure high-entropy token for password reset."""
    return secrets.token_urlsafe(32)


def is_google_oauth_configured() -> bool:
    """Check if Google OAuth credentials have been supplied."""
    return bool(
        GOOGLE_CLIENT_ID
        and GOOGLE_CLIENT_SECRET
        and not GOOGLE_CLIENT_ID.startswith("mock-")
        and not GOOGLE_CLIENT_ID.startswith("your-")
    )


def get_google_oauth_url(state: str) -> str:
    """Generate the Google OAuth2 authorization consent screen URL."""
    if not GOOGLE_CLIENT_ID:
        raise ValueError("GOOGLE_CLIENT_ID is not configured in server environment")

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "state": state,
        "prompt": "select_account",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


async def exchange_google_code(code: str) -> dict:
    """Exchange authorization code for tokens and fetch user profile."""
    if not is_google_oauth_configured():
        raise ValueError("Google OAuth credentials are not configured in .env")

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            logger.error(f"Google token exchange failed: {token_resp.text}")
            raise ValueError(f"Google authentication failed: {token_resp.text}")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError("No access token returned by Google")

        userinfo_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code != 200:
            logger.error(f"Google userinfo request failed: {userinfo_resp.text}")
            raise ValueError("Could not retrieve user info from Google")

        return userinfo_resp.json()
