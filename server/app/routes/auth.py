import re
import secrets
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

from ..core import db
from ..core.config import AUTH_COOKIE_NAME, COOKIE_SECURE, CSRF_COOKIE_NAME, JWT_EXPIRES_DAYS
from ..core.logger import logger
from ..middleware.auth_middleware import get_current_user
from ..services.auth_service import (
    create_access_token,
    exchange_google_code,
    generate_reset_token,
    get_google_oauth_url,
    hash_password,
    is_google_oauth_configured,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class RegisterBody(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class LoginBody(BaseModel):
    email: str
    password: str


class ForgotPasswordBody(BaseModel):
    email: str


class ResetPasswordBody(BaseModel):
    token: str
    new_password: str


def _set_auth_cookie(response: Response, token: str) -> None:
    """Set secure, HTTP-only authentication cookie, plus a companion,
    non-httponly CSRF token cookie for the double-submit CSRF check
    (see app/middleware/csrf.py)."""
    max_age = JWT_EXPIRES_DAYS * 86400
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=secrets.token_urlsafe(32),
        max_age=max_age,
        httponly=False,  # must be readable by frontend JS to echo back as a header
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    """Clear authentication and CSRF cookies."""
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        httponly=False,
        samesite="lax",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterBody, response: Response):
    """Register a new user account with email and password."""
    email = body.email.strip().lower()
    if not EMAIL_REGEX.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address format")

    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Check if user already exists
    existing = await db.query("SELECT id FROM users WHERE email = $1", [email])
    if existing["rows"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists",
        )

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(body.password)
    user_name = (body.name or "").strip() or email.split("@")[0].capitalize()

    # Create user
    insert_res = await db.query(
        """INSERT INTO users (id, email, password_hash, name, profile_image, auth_provider, provider_user_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id, email, name, profile_image, auth_provider, created_at""",
        [user_id, email, pw_hash, user_name, None, "local", None],
    )
    user = insert_res["rows"][0]

    # Generate JWT & set cookie
    token = create_access_token(user["id"], user["email"])
    _set_auth_cookie(response, token)

    return {
        "success": True,
        "message": "Account created successfully",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "profile_image": user.get("profile_image"),
            "auth_provider": user.get("auth_provider", "local"),
        },
        "token": token,
    }


@router.post("/login")
async def login(body: LoginBody, response: Response):
    """Authenticate user with email and password."""
    email = body.email.strip().lower()
    if not email or not body.password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    user_res = await db.query("SELECT * FROM users WHERE email = $1", [email])
    if not user_res["rows"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    user = user_res["rows"][0]
    stored_hash = user.get("password_hash") or ""
    if not verify_password(body.password, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Update last_login
    await db.query("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = $1", [user["id"]])

    # Generate JWT & set cookie
    token = create_access_token(user["id"], user["email"])
    _set_auth_cookie(response, token)

    return {
        "success": True,
        "message": "Signed in successfully",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name") or email.split("@")[0].capitalize(),
            "profile_image": user.get("profile_image"),
            "auth_provider": user.get("auth_provider", "local"),
        },
        "token": token,
    }


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    """Retrieve the currently authenticated user's profile."""
    return {
        "user": {
            "id": current_user["id"],
            "email": current_user["email"],
            "name": current_user.get("name"),
            "profile_image": current_user.get("profile_image"),
            "auth_provider": current_user.get("auth_provider", "local"),
            "created_at": current_user.get("created_at"),
            "last_login": current_user.get("last_login"),
        }
    }


@router.post("/logout")
async def logout(response: Response):
    """Clear session cookie and log out the user."""
    _clear_auth_cookie(response)
    return {"success": True, "message": "Logged out successfully"}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordBody):
    """Initiate password reset flow."""
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    user_res = await db.query("SELECT id, email FROM users WHERE email = $1", [email])
    if not user_res["rows"]:
        # Do not reveal whether account exists for security
        return {
            "success": True,
            "message": "If an account with that email exists, password reset instructions have been generated.",
        }

    user = user_res["rows"][0]
    token = generate_reset_token()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))  # 1 hour expiry

    await db.query(
        "UPDATE users SET reset_token = $1, reset_token_expires_at = $2, updated_at = CURRENT_TIMESTAMP WHERE id = $3",
        [token, now_iso, user["id"]],
    )

    return {
        "success": True,
        "message": "Password reset instructions generated successfully.",
        # Provide token in response for development / demo usability
        "reset_token": token,
        "reset_url": f"/reset-password?token={token}",
    }


@router.post("/reset-password")
async def reset_password(body: ResetPasswordBody):
    """Reset password using a valid reset token."""
    token = body.token.strip()
    new_pw = body.new_password.strip()

    if not token:
        raise HTTPException(status_code=400, detail="Reset token is required")

    if len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user_res = await db.query("SELECT id, reset_token_expires_at FROM users WHERE reset_token = $1", [token])
    if not user_res["rows"]:
        raise HTTPException(status_code=400, detail="Invalid or expired password reset token")

    user = user_res["rows"][0]
    new_hash = hash_password(new_pw)

    await db.query(
        "UPDATE users SET password_hash = $1, reset_token = NULL, reset_token_expires_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
        [new_hash, user["id"]],
    )

    return {
        "success": True,
        "message": "Password has been successfully reset. You may now log in with your new password.",
    }


@router.get("/google/url")
async def google_auth_url():
    """Return Google OAuth2 authorization URL or status."""
    configured = is_google_oauth_configured()
    if not configured:
        return {
            "configured": False,
            "url": None,
            "message": "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env.",
        }

    state = secrets.token_urlsafe(16)
    auth_url = get_google_oauth_url(state)
    return {
        "configured": True,
        "url": auth_url,
        "state": state,
    }


@router.get("/google/callback")
async def google_callback(code: Optional[str] = None, error: Optional[str] = None):
    """Handle Google OAuth2 redirect callback."""
    if error or not code:
        logger.warn(f"Google OAuth callback received error: {error}")
        return RedirectResponse(url=f"/login?error={error or 'cancelled'}")

    try:
        user_info = await exchange_google_code(code)
        google_id = user_info.get("id")
        email = (user_info.get("email") or "").lower()
        name = user_info.get("name") or email.split("@")[0].capitalize()
        picture = user_info.get("picture")

        if not email:
            return RedirectResponse(url="/login?error=no_email_from_google")

        # 1. Check if user exists by Google provider ID
        user_res = await db.query(
            "SELECT * FROM users WHERE auth_provider = $1 AND provider_user_id = $2",
            ["google", google_id],
        )

        user = None
        if user_res["rows"]:
            user = user_res["rows"][0]
        else:
            # 2. Check if user exists with matching email (link account)
            email_res = await db.query("SELECT * FROM users WHERE email = $1", [email])
            if email_res["rows"]:
                user = email_res["rows"][0]
                # Update auth provider link if local
                await db.query(
                    "UPDATE users SET auth_provider = $1, provider_user_id = $2, profile_image = COALESCE(profile_image, $3) WHERE id = $4",
                    ["google", google_id, picture, user["id"]],
                )
            else:
                # 3. Create brand new user
                user_id = str(uuid.uuid4())
                ins_res = await db.query(
                    """INSERT INTO users (id, email, password_hash, name, profile_image, auth_provider, provider_user_id)
                       VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""",
                    [user_id, email, "", name, picture, "google", google_id],
                )
                user = ins_res["rows"][0]

        # Update last login
        await db.query("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = $1", [user["id"]])

        # Generate JWT
        token = create_access_token(user["id"], user["email"])

        redirect = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        _set_auth_cookie(redirect, token)
        return redirect

    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        return RedirectResponse(url=f"/login?error={str(e)}")
