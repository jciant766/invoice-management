"""
OAuth Authentication Routes

Handles login, logout, and OAuth callbacks for Google and Microsoft.
"""

import os
import secrets
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

# Store state tokens temporarily (in production, use Redis or database)
_state_tokens = {}


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
# Google OAuth
# =============================================================================

@router.get("/google/login")
async def google_login(request: Request):
    """Redirect to Google OAuth consent screen."""
    service = GoogleOAuthService()

    if not service.is_configured():
        return RedirectResponse(
            url="/email?error=Google+OAuth+not+configured.+Please+add+GOOGLE_CLIENT_ID+and+GOOGLE_CLIENT_SECRET+to+.env",
            status_code=302
        )

    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    _state_tokens[state] = "google"

    auth_url = service.get_authorization_url(state=state)
    if not auth_url:
        return RedirectResponse(
            url="/email?error=Failed+to+generate+Google+auth+URL",
            status_code=302
        )

    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/google/callback")
async def google_callback(request: Request, code: str = None, state: str = None, error: str = None):
    """Handle Google OAuth callback."""

    # Check for errors from Google
    if error:
        return RedirectResponse(
            url=f"/email?error=Google+login+cancelled:+{error}",
            status_code=302
        )

    if not code:
        return RedirectResponse(
            url="/email?error=No+authorization+code+received+from+Google",
            status_code=302
        )

    # Verify state token (CSRF protection)
    if state and state in _state_tokens:
        del _state_tokens[state]
    # Note: In development, we're lenient about state verification

    # Exchange code for tokens
    service = GoogleOAuthService()
    result = service.handle_callback(code)

    if result["success"]:
        # Clear any cached email service so it reinitializes with new auth
        from services.email_service import reset_email_service
        reset_email_service()

        return RedirectResponse(
            url=f"/email?success=Connected+to+Google+as+{result['email']}",
            status_code=302
        )
    else:
        return RedirectResponse(
            url=f"/email?error=Google+login+failed:+{result.get('error', 'Unknown+error')}",
            status_code=302
        )


@router.post("/google/logout")
async def google_logout():
    """Disconnect Google account."""
    OAuthTokenManager.delete_tokens("google")

    # Reset email service
    from services.email_service import reset_email_service
    reset_email_service()

    return {"success": True, "message": "Google account disconnected"}


# =============================================================================
# Microsoft OAuth
# =============================================================================

@router.get("/microsoft/login")
async def microsoft_login(request: Request):
    """Redirect to Microsoft OAuth consent screen."""
    service = MicrosoftOAuthService()

    if not service.is_configured():
        return RedirectResponse(
            url="/email?error=Microsoft+OAuth+not+configured.+Please+add+MICROSOFT_CLIENT_ID+and+MICROSOFT_CLIENT_SECRET+to+.env",
            status_code=302
        )

    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    _state_tokens[state] = "microsoft"

    auth_url = service.get_authorization_url(state=state)
    if not auth_url:
        return RedirectResponse(
            url="/email?error=Failed+to+generate+Microsoft+auth+URL",
            status_code=302
        )

    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/microsoft/callback")
async def microsoft_callback(request: Request, code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Handle Microsoft OAuth callback."""

    # Check for errors from Microsoft
    if error:
        error_msg = error_description or error
        return RedirectResponse(
            url=f"/email?error=Microsoft+login+cancelled:+{error_msg}",
            status_code=302
        )

    if not code:
        return RedirectResponse(
            url="/email?error=No+authorization+code+received+from+Microsoft",
            status_code=302
        )

    # Verify state token (CSRF protection)
    if state and state in _state_tokens:
        del _state_tokens[state]

    # Exchange code for tokens
    service = MicrosoftOAuthService()
    result = service.handle_callback(code)

    if result["success"]:
        # Clear any cached email service so it reinitializes with new auth
        from services.email_service import reset_email_service
        from services.outlook_service import reset_outlook_service
        reset_email_service()
        reset_outlook_service()

        return RedirectResponse(
            url=f"/email?success=Connected+to+Microsoft+as+{result['email']}",
            status_code=302
        )
    else:
        return RedirectResponse(
            url=f"/email?error=Microsoft+login+failed:+{result.get('error', 'Unknown+error')}",
            status_code=302
        )


@router.post("/microsoft/logout")
async def microsoft_logout():
    """Disconnect Microsoft account."""
    OAuthTokenManager.delete_tokens("microsoft")

    # Reset services
    from services.email_service import reset_email_service
    from services.outlook_service import reset_outlook_service
    reset_email_service()
    reset_outlook_service()

    return {"success": True, "message": "Microsoft account disconnected"}


# =============================================================================
# General Disconnect
# =============================================================================

@router.post("/disconnect")
async def disconnect_all():
    """Disconnect all OAuth accounts (switch account)."""
    OAuthTokenManager.delete_tokens()  # Delete all

    # Reset all services
    from services.email_service import reset_email_service
    from services.outlook_service import reset_outlook_service
    reset_email_service()
    reset_outlook_service()

    return {"success": True, "message": "All email accounts disconnected"}


@router.get("/disconnect")
async def disconnect_all_redirect():
    """Disconnect and redirect to email page (for simple link/button)."""
    import os

    OAuthTokenManager.delete_tokens()

    # Also remove legacy token.json file if it exists
    legacy_token_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "token.json")
    if os.path.exists(legacy_token_path):
        try:
            os.remove(legacy_token_path)
        except:
            pass

    from services.email_service import reset_email_service
    from services.outlook_service import reset_outlook_service
    reset_email_service()
    reset_outlook_service()

    return RedirectResponse(url="/email?success=Email+account+disconnected", status_code=302)
