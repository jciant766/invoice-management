"""
Authentication Middleware

Protects all routes by requiring user login.
Uses pure ASGI middleware to avoid BaseHTTPMiddleware hanging issues.
Includes CSRF protection via Origin/Referer validation and per-session tokens.
"""

import hmac
import hashlib
import os
import secrets
from urllib.parse import urlparse, parse_qs

from fastapi import Request

from services.auth_service import validate_session, get_user_by_id
from database import get_connection

# Routes that don't require authentication
# Note: Only OAuth login/callback routes are public (needed for OAuth redirect flow).
# Logout/disconnect routes require authentication to prevent unauthorized disconnection.
PUBLIC_ROUTES = [
    "/login",
    "/forgot-password",
    "/reset-password",
    "/terms",
    "/privacy",
    "/static",
    "/health",
    "/favicon.ico",
    "/auth/status",
    "/auth/google/login",
    "/auth/google/callback",
    "/auth/microsoft/login",
    "/auth/microsoft/callback",
]

# Routes exempt from CSRF validation (login has no session, OAuth callbacks come from providers)
CSRF_EXEMPT_ROUTES = [
    "/login",
    "/auth/google/callback",
    "/auth/microsoft/callback",
]

# CSRF secret key - stable per server process
_CSRF_SECRET = os.getenv("CSRF_SECRET", secrets.token_hex(32))


def _generate_csrf_token(session_token: str) -> str:
    """Generate a CSRF token derived from the session token using HMAC."""
    return hmac.new(
        _CSRF_SECRET.encode(),
        session_token.encode(),
        hashlib.sha256
    ).hexdigest()


class AuthMiddleware:
    """Pure ASGI middleware that requires authentication and CSRF protection."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        method = scope.get("method", "GET")

        # Check if route is public
        if self._is_public_route(path):
            await self.app(scope, receive, send)
            return

        # Get cookies from headers
        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode()
        token = self._get_cookie(cookie_header, "session_token")

        if not token:
            await self._send_redirect(scope, send, path)
            return

        # Validate session
        user_id = validate_session(token)
        if not user_id:
            await self._send_redirect(scope, send, path)
            return

        # Get user from database
        conn = get_connection()
        try:
            user = get_user_by_id(conn, user_id)
            if not user or not user.get('is_active'):
                await self._send_redirect(scope, send, path)
                return

            # Store user info in scope state for routes to access
            class UserInfo:
                def __init__(self, user_dict):
                    self.id = user_dict['id']
                    self.username = user_dict['username']
                    self.email = user_dict['email']
                    self.full_name = user_dict.get('full_name')
                    self.role = user_dict['role']
                    self.is_active = user_dict['is_active']

            scope["state"] = scope.get("state", {})
            scope["state"]["user"] = UserInfo(user)
            scope["state"]["user_id"] = user['id']

            # Generate CSRF token from session (for templates to use)
            csrf_token = _generate_csrf_token(token)
            scope["state"]["csrf_token"] = csrf_token

        finally:
            conn.close()

        # CSRF validation for state-changing methods
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            if not self._is_csrf_exempt(path):
                if not self._validate_origin(scope):
                    await self._send_csrf_error(send, path)
                    return

                # Also validate CSRF token from form body (url-encoded forms only)
                token_valid, receive = await self._validate_csrf_token(scope, receive)
                if not token_valid:
                    await self._send_csrf_error(send, path)
                    return

        await self.app(scope, receive, send)

    def _is_public_route(self, path: str) -> bool:
        """Check if the path is a public route."""
        for route in PUBLIC_ROUTES:
            if path.startswith(route):
                return True
        return False

    def _is_csrf_exempt(self, path: str) -> bool:
        """Check if the path is exempt from CSRF validation."""
        for route in CSRF_EXEMPT_ROUTES:
            if path.startswith(route):
                return True
        return False

    def _validate_origin(self, scope) -> bool:
        """
        Validate Origin/Referer header matches the expected host.

        This prevents CSRF attacks by ensuring POST requests come from our own site.
        - If Origin header is present: it must match our host
        - If only Referer is present: its host must match our host
        - If neither is present: allow (SameSite=Strict cookie already protects)
        """
        headers_list = scope.get("headers", [])
        headers = {}
        for key, value in headers_list:
            headers[key.lower()] = value

        host = headers.get(b"host", b"").decode()
        if not host:
            return True  # Can't validate without host header

        # Check Origin header first (most reliable)
        origin = headers.get(b"origin", b"").decode()
        if origin:
            parsed = urlparse(origin)
            return parsed.netloc == host

        # Fall back to Referer header
        referer = headers.get(b"referer", b"").decode()
        if referer:
            parsed = urlparse(referer)
            return parsed.netloc == host

        # Neither Origin nor Referer present - allow
        # (SameSite=Strict cookie provides protection in this case)
        return True

    async def _validate_csrf_token(self, scope, receive):
        """
        Validate the CSRF token from form data for url-encoded POST requests.
        Returns (is_valid, new_receive) where new_receive replays the cached body.
        For non-form content types (JSON, multipart, etc.), skips token validation
        and returns (True, receive) since Origin/Referer already passed.
        """
        headers = {}
        for key, value in scope.get("headers", []):
            headers[key.lower()] = value

        content_type = headers.get(b"content-type", b"").decode().lower()

        # Only validate token for url-encoded form submissions
        if not content_type.startswith("application/x-www-form-urlencoded"):
            return True, receive

        # Read full body from the ASGI receive stream
        body_parts = []
        while True:
            message = await receive()
            chunk = message.get("body", b"")
            if chunk:
                body_parts.append(chunk)
            if not message.get("more_body", False):
                break
        full_body = b"".join(body_parts)

        # Parse form data to extract csrf_token
        try:
            form_data = parse_qs(full_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return False, receive

        submitted_tokens = form_data.get("csrf_token", [])
        submitted_token = submitted_tokens[0] if submitted_tokens else ""

        expected_token = scope.get("state", {}).get("csrf_token", "")

        if not submitted_token or not expected_token:
            return False, receive

        if not hmac.compare_digest(submitted_token, expected_token):
            return False, receive

        # Body was consumed - create a receive that replays it for downstream
        # Use a list as mutable flag to track state across calls
        state = {"body_sent": False}

        async def body_replay_receive():
            if not state["body_sent"]:
                state["body_sent"] = True
                return {"type": "http.request", "body": full_body, "more_body": False}
            # For subsequent calls (e.g. disconnect), pass through to original
            return await receive()

        return True, body_replay_receive

    def _get_cookie(self, cookie_header: str, name: str) -> str:
        """Extract a cookie value from the cookie header."""
        if not cookie_header:
            return None
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(f"{name}="):
                return part[len(name) + 1:]
        return None

    async def _send_redirect(self, scope, send, path: str):
        """Send a redirect response to login."""
        if path.startswith("/api/"):
            body = b'{"error": "Not authenticated", "detail": "Please log in"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
        else:
            query = scope.get("query_string", b"").decode()
            next_url = path
            if query:
                next_url += f"?{query}"
            redirect_url = f"/login?next={next_url}"
            await send({
                "type": "http.response.start",
                "status": 302,
                "headers": [[b"location", redirect_url.encode()]],
            })
            await send({
                "type": "http.response.body",
                "body": b"",
            })

    async def _send_csrf_error(self, send, path: str):
        """Send a CSRF validation error response."""
        if path.startswith("/api/"):
            body = b'{"error": "CSRF validation failed", "detail": "Request origin not trusted"}'
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
        else:
            body = b"CSRF validation failed. Please go back and try again."
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    [b"content-type", b"text/plain"],
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })


def get_current_user(request: Request):
    """Helper function to get current user from request state."""
    return getattr(request.state, "user", None)


def get_current_user_id(request: Request) -> int:
    """Helper function to get current user ID from request state."""
    return getattr(request.state, "user_id", None)


def require_admin(request: Request) -> bool:
    """Check if current user is admin."""
    user = get_current_user(request)
    return user and user.role == "admin"


def get_csrf_token(request: Request) -> str:
    """Helper function to get CSRF token from request state."""
    return getattr(request.state, "csrf_token", "")
