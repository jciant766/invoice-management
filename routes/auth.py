"""
OAuth Authentication Routes

Handles login, logout, and OAuth callbacks for Google and Microsoft.
"""

import os
import secrets
import time
import threading
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

from services.oauth_service import (
    GoogleOAuthService,
    MicrosoftOAuthService,
    OAuthTokenManager,
    get_authenticated_email,
    is_oauth_configured
)

router = APIRouter(prefix="/auth", tags=["auth"])


class StateTokenStore:
    """Thread-safe state token store with TTL expiration."""

    def __init__(self, ttl_seconds: int = 600):  # 10 minute TTL
        self._tokens: dict = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def add(self, token: str, provider: str) -> None:
        """Add a state token with timestamp."""
        with self._lock:
            self._cleanup()
            self._tokens[token] = {
                "provider": provider,
                "created_at": time.time()
            }

    def verify_and_remove(self, token: str) -> bool:
        """Verify token exists and remove it. Returns True if valid."""
        with self._lock:
            self._cleanup()
            if token in self._tokens:
                del self._tokens[token]
                return True
            return False

    def _cleanup(self):
        """Remove expired tokens (called with lock held)."""
        now = time.time()
        expired = [
            k for k, v in self._tokens.items()
            if now - v["created_at"] > self._ttl
        ]
        for k in expired:
            del self._tokens[k]


# TTL-based state token store (10 minute expiry)
_state_tokens = StateTokenStore(ttl_seconds=600)


# =============================================================================
# Status Endpoint
# =============================================================================

@router.get("/status", response_class=JSONResponse)
async def auth_status():
    """
    Get current authentication status.

    Returns:
        JSON with provider info, email, and configuration status
    """
    provider = OAuthTokenManager.get_active_provider()
    email = get_authenticated_email() if provider else None
    configured = is_oauth_configured()

    return {
        "authenticated": provider is not None,
        "provider": provider,
        "email": email,
        "configured": configured
    }


# =============================================================================
# Shared OAuth Helpers
# =============================================================================

def _validate_callback(provider: str, code, state, error_msg: str):
    """Validate OAuth callback params. Returns RedirectResponse on error, None on success."""
    if error_msg:
        return RedirectResponse(url=f"/email?error={provider}+login+cancelled:+{error_msg}", status_code=302)
    if not code:
        return RedirectResponse(url=f"/email?error=No+authorization+code+received+from+{provider}", status_code=302)
    if state:
        if not _state_tokens.verify_and_remove(state):
            return RedirectResponse(url="/email?error=Invalid+state+token+-+possible+CSRF+attack", status_code=302)
    else:
        return RedirectResponse(url="/email?error=Missing+state+token+-+possible+CSRF+attack", status_code=302)
    return None


def _handle_result(provider: str, result: dict):
    """Handle OAuth callback result, return appropriate redirect."""
    if result["success"]:
        return RedirectResponse(url=f"/email?success=Connected+to+{provider}+as+{result['email']}", status_code=302)
    return RedirectResponse(url=f"/email?error={provider}+login+failed:+{result.get('error', 'Unknown+error')}", status_code=302)


def _reset_services(include_outlook: bool = False):
    """Reset cached email services after auth changes."""
    from services.email_service import reset_email_service
    reset_email_service()
    if include_outlook:
        from services.outlook_service import reset_outlook_service
        reset_outlook_service()


def _start_oauth(service, provider: str):
    """Common OAuth login redirect logic."""
    if not service.is_configured():
        return RedirectResponse(
            url=f"/email?error={provider}+OAuth+not+configured.+Please+add+credentials+to+.env",
            status_code=302
        )
    state = secrets.token_urlsafe(32)
    _state_tokens.add(state, provider.lower())
    auth_url = service.get_authorization_url(state=state)
    if not auth_url:
        return RedirectResponse(url=f"/email?error=Failed+to+generate+{provider}+auth+URL", status_code=302)
    return RedirectResponse(url=auth_url, status_code=302)


# =============================================================================
# Google OAuth
# =============================================================================

@router.get("/google/login")
async def google_login(request: Request):
    """Redirect to Google OAuth consent screen."""
    return _start_oauth(GoogleOAuthService(), "Google")


@router.get("/google/callback")
async def google_callback(request: Request, code: str = None, state: str = None, error: str = None):
    """Handle Google OAuth callback."""
    err = _validate_callback("Google", code, state, error)
    if err:
        return err

    result = GoogleOAuthService().handle_callback(code)
    _reset_services()
    return _handle_result("Google", result)


@router.post("/google/logout")
async def google_logout():
    """Disconnect Google account."""
    OAuthTokenManager.delete_tokens("google")
    _reset_services()
    return {"success": True, "message": "Google account disconnected"}


# =============================================================================
# Microsoft OAuth
# =============================================================================

@router.get("/microsoft/login")
async def microsoft_login(request: Request):
    """Redirect to Microsoft OAuth consent screen."""
    return _start_oauth(MicrosoftOAuthService(), "Microsoft")


@router.get("/microsoft/callback")
async def microsoft_callback(request: Request, code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Handle Microsoft OAuth callback."""
    err = _validate_callback("Microsoft", code, state, error_description or error)
    if err:
        return err

    result = MicrosoftOAuthService().handle_callback(code)
    _reset_services(include_outlook=True)
    return _handle_result("Microsoft", result)


@router.post("/microsoft/logout")
async def microsoft_logout():
    """Disconnect Microsoft account."""
    OAuthTokenManager.delete_tokens("microsoft")
    _reset_services(include_outlook=True)
    return {"success": True, "message": "Microsoft account disconnected"}


# =============================================================================
# General Disconnect
# =============================================================================

@router.post("/disconnect")
async def disconnect_all():
    """Disconnect all OAuth accounts."""
    OAuthTokenManager.delete_tokens()

    # Remove legacy token.json if it exists
    legacy_token_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "token.json")
    if os.path.exists(legacy_token_path):
        try:
            os.remove(legacy_token_path)
        except OSError:
            pass

    _reset_services(include_outlook=True)
    return RedirectResponse(url="/email?success=Email+account+disconnected", status_code=302)
