"""
Admin authentication middleware.
Validates Chainlit JWT cookie and checks admin access.
"""

import os
import logging
from typing import Optional, Dict, Any
from functools import wraps

import jwt
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

logger = logging.getLogger("hr_bot.admin.auth")

# Admin emails from environment
def _get_admin_emails() -> set:
    """Get set of admin emails from environment."""
    emails = os.getenv("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in emails.split(",") if e.strip()}


def _get_jwt_secret() -> str:
    """Get Chainlit JWT secret."""
    return os.getenv("CHAINLIT_AUTH_SECRET", "")


def decode_chainlit_token(request: Request) -> Optional[Dict[str, Any]]:
    """
    Decode Chainlit JWT token from cookies.
    
    Returns user data dict or None if invalid/missing.
    """
    # Chainlit uses 'access_token' cookie
    token = request.cookies.get("access_token")
    if not token:
        logger.debug("No access_token cookie found")
        return None
    
    secret = _get_jwt_secret()
    if not secret:
        logger.error("CHAINLIT_AUTH_SECRET not configured")
        return None
    
    try:
        # Chainlit uses HS256 by default
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Invalid JWT token: {e}")
        return None


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """
    Get current user from Chainlit JWT.
    
    Returns dict with 'email', 'name', 'is_admin' or None.
    """
    payload = decode_chainlit_token(request)
    if not payload:
        return None
    
    # Chainlit stores user info in 'sub' or nested structure
    # Check various possible locations
    email = None
    name = None
    
    # Try direct fields
    if "email" in payload:
        email = payload["email"]
    elif "sub" in payload:
        email = payload["sub"]
    elif "identifier" in payload:
        email = payload["identifier"]
    
    # Try nested user object
    if not email and "user" in payload:
        user = payload["user"]
        email = user.get("email") or user.get("identifier") or user.get("sub")
        name = user.get("name") or user.get("display_name")
    
    if not email:
        logger.debug(f"Could not extract email from JWT payload: {payload.keys()}")
        return None
    
    email = email.strip().lower()
    admin_emails = _get_admin_emails()
    
    return {
        "email": email,
        "name": name or email.split("@")[0],
        "is_admin": email in admin_emails
    }


def require_admin(request: Request) -> Optional[Response]:
    """
    Check if current user is admin.
    
    Returns None if authorized, or RedirectResponse if not.
    """
    user = get_current_user(request)
    
    if not user:
        # Not logged in - redirect to main app
        logger.warning("Admin access denied: not authenticated")
        return RedirectResponse(url="/?error=not_authenticated", status_code=302)
    
    if not user.get("is_admin"):
        # Logged in but not admin
        logger.warning(f"Admin access denied for user: {user.get('email')}")
        return RedirectResponse(url="/?error=not_admin", status_code=302)
    
    return None  # Authorized
