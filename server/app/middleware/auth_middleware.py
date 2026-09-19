from typing import Optional
from fastapi import Request, HTTPException, status, Depends
from ..core.config import AUTH_COOKIE_NAME
from ..core import db
from ..core.logger import logger
from ..services.auth_service import decode_access_token


def _extract_token_from_request(request: Request) -> Optional[str]:
    """Extract JWT token from cookies or Authorization Bearer header."""
    # 1. Check HTTP-only cookie
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        return token

    # 2. Check Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :].strip()

    return None


async def get_current_user(request: Request) -> dict:
    """Dependency that ensures the user is authenticated and returns user data."""
    token = _extract_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
    except Exception as e:
        logger.warn(f"Token validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_res = await db.query(
        "SELECT id, email, name, profile_image, auth_provider, created_at, updated_at, last_login FROM users WHERE id = $1",
        [user_id],
    )
    if not user_res["rows"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found",
        )

    user = user_res["rows"][0]
    return user


async def get_optional_user(request: Request) -> Optional[dict]:
    """Dependency that returns current user if authenticated, otherwise None."""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None
