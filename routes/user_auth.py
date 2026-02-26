"""
User Authentication Routes

Handles local login/logout, password reset, and account-security actions.
Rate limiting is stored in the database for persistence across restarts.
"""

import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote_plus, urlparse

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse

from database import get_db
from models import AuditAction
from services.auth_service import (
    authenticate_user,
    cleanup_password_reset_tokens,
    create_default_admin,
    create_password_reset_token,
    create_session,
    get_password_reset_token,
    get_user_auth_by_email,
    get_user_by_id,
    invalidate_all_sessions,
    invalidate_session,
    mark_password_reset_token_used,
    mark_security_notification_sent,
    update_last_login,
    update_user_password,
    validate_password,
    validate_session,
    verify_user_password,
)
from services.audit_service import log_action, log_login, log_logout, log_password_change
from services.notification_service import send_lockout_email, send_password_reset_email
from shared_templates import templates
from routes.helpers import get_client_ip

router = APIRouter(tags=["user_auth"])

# Cookie name for session
SESSION_COOKIE = "session_token"

# --- RATE LIMITING (database-backed) ---
MAX_LOGIN_ATTEMPTS = 5
RATE_LIMIT_WINDOW = 15 * 60  # 15 minutes
LOCKOUT_NOTIFICATION_TYPE = "login_lockout"

PASSWORD_RESET_EXPIRY_MINUTES = 60


def _request_is_https(request: Request) -> bool:
    """Detect HTTPS, including reverse-proxy headers."""
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto.split(",")[0].strip().lower() == "https"


def _build_absolute_url(request: Request, path: str) -> str:
    """Build an absolute URL for emails."""
    scheme = "https" if _request_is_https(request) else "http"
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}{path}"


def _normalize_reset_token(raw_token: str) -> str:
    """
    Normalize a reset token from copy/pasted text.
    Accept only URL-safe token characters and ignore trailing text.
    """
    raw_token = (raw_token or "").strip()
    if not raw_token:
        return ""
    match = re.search(r"[A-Za-z0-9_-]{20,}", raw_token)
    return match.group(0) if match else ""


def _clean_old_attempts(ip: str) -> None:
    """Remove expired login attempts from the database."""
    cutoff = datetime.now() - timedelta(seconds=RATE_LIMIT_WINDOW)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM login_attempts WHERE ip_address = ? AND attempted_at < ?",
            (ip, cutoff)
        )


def _is_rate_limited(ip: str) -> bool:
    """Check if an IP is rate limited (database-backed)."""
    _clean_old_attempts(ip)
    with get_db() as conn:
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(seconds=RATE_LIMIT_WINDOW)
        cursor.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip_address = ? AND attempted_at >= ?",
            (ip, cutoff)
        )
        count = cursor.fetchone()[0]
        return count >= MAX_LOGIN_ATTEMPTS


def _record_failed_attempt(ip: str) -> None:
    """Record a failed login attempt in the database."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO login_attempts (ip_address, attempted_at) VALUES (?, ?)",
            (ip, datetime.now())
        )


def _get_lockout_remaining(ip: str) -> int:
    """Get remaining lockout time in seconds (database-backed)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(seconds=RATE_LIMIT_WINDOW)
        cursor.execute(
            "SELECT MIN(attempted_at) FROM login_attempts WHERE ip_address = ? AND attempted_at >= ?",
            (ip, cutoff)
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return 0
        oldest = row[0]
        if isinstance(oldest, str):
            oldest = datetime.fromisoformat(oldest)
        unlock_time = oldest + timedelta(seconds=RATE_LIMIT_WINDOW)
        remaining = (unlock_time - datetime.now()).total_seconds()
        return max(0, int(remaining))


def _clear_attempts(ip: str) -> None:
    """Clear all login attempts for an IP (on successful login)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM login_attempts WHERE ip_address = ?", (ip,))


def _is_safe_redirect(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return not parsed.scheme and not parsed.netloc and url.startswith("/")


def _sanitize_redirect(url: str) -> str:
    if _is_safe_redirect(url):
        return url
    return "/"


def _maybe_notify_lockout(conn, username_or_email: str, ip_address: str) -> None:
    """Send one lockout email per user per hour (best-effort)."""
    username_or_email = (username_or_email or "").strip()
    if not username_or_email:
        return

    user = get_user_auth_by_email(conn, username_or_email.lower())
    if not user:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, email
            FROM users
            WHERE username = ? AND is_active = 1
            """,
            (username_or_email,)
        )
        row = cursor.fetchone()
        if row:
            user = dict(row)

    if not user:
        return

    period_key = datetime.now().strftime("%Y%m%d%H")
    should_send = mark_security_notification_sent(
        conn,
        user_id=user["id"],
        notification_type=LOCKOUT_NOTIFICATION_TYPE,
        period_key=period_key
    )
    if not should_send:
        return

    lockout_minutes = max(1, RATE_LIMIT_WINDOW // 60)
    send_lockout_email(
        email=user["email"],
        username=user["username"],
        ip_address=ip_address,
        lockout_minutes=lockout_minutes
    )


def get_current_user(request: Request, conn):
    """Get current user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None

    user_id = validate_session(token)
    if not user_id:
        return None

    return get_user_by_id(conn, user_id)


def _build_user_gdpr_export(conn, user_id: int) -> dict:
    """Build a GDPR export payload for a user."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, username, email, full_name, role, is_active, created_at, last_login
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    )
    user_row = cursor.fetchone()
    if not user_row:
        return {}

    cursor.execute(
        """
        SELECT token, expires_at, created_at
        FROM sessions
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,)
    )
    sessions = [dict(row) for row in cursor.fetchall()]
    for session in sessions:
        session["token"] = f"{session['token'][:8]}..."

    cursor.execute(
        """
        SELECT action, entity_type, entity_id, details, ip_address, timestamp
        FROM audit_logs
        WHERE user_id = ?
        ORDER BY timestamp DESC
        LIMIT 1000
        """,
        (user_id,)
    )
    audit_logs = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        """
        SELECT created_at, expires_at, used_at, request_ip
        FROM password_reset_tokens
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,)
    )
    reset_requests = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        """
        SELECT notification_type, period_key, sent_at
        FROM security_notifications
        WHERE user_id = ?
        ORDER BY sent_at DESC
        """,
        (user_id,)
    )
    security_notifications = [dict(row) for row in cursor.fetchall()]

    return {
        "exported_at": datetime.now().isoformat(),
        "user": dict(user_row),
        "active_sessions": sessions,
        "audit_logs": audit_logs,
        "password_reset_requests": reset_requests,
        "security_notifications": security_notifications
    }


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None, next: str = None):
    """Display login page."""
    with get_db() as conn:
        # Create default admin if no users exist
        create_default_admin(conn)

        # Check if already logged in
        user = get_current_user(request, conn)
        if user:
            safe_redirect = _sanitize_redirect(next)
            return RedirectResponse(url=safe_redirect, status_code=302)

        # Check if IP is rate limited
        ip_address = get_client_ip(request)
        lockout_remaining = 0
        if _is_rate_limited(ip_address):
            lockout_remaining = _get_lockout_remaining(ip_address)
            minutes = max(1, (lockout_remaining + 59) // 60)
            error = f"Too many failed attempts. Please try again in {minutes} minutes."

        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": error,
            "next": _sanitize_redirect(next) if next else "/",
            "lockout_remaining": lockout_remaining
        })


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/")
):
    """Process login form."""
    ip_address = get_client_ip(request)
    safe_next = _sanitize_redirect(next)
    username = (username or "").strip()

    # Check rate limiting BEFORE attempting authentication
    if _is_rate_limited(ip_address):
        with get_db() as conn:
            _maybe_notify_lockout(conn, username, ip_address)
        lockout_remaining = _get_lockout_remaining(ip_address)
        minutes = max(1, (lockout_remaining + 59) // 60)
        return RedirectResponse(
            url=(
                f"/login?error=Too+many+failed+attempts.+Try+again+in+{minutes}+minutes."
                f"&next={quote_plus(safe_next)}"
            ),
            status_code=302
        )

    with get_db() as conn:
        user = authenticate_user(conn, username, password)

        if not user:
            _record_failed_attempt(ip_address)
            log_login(conn, None, ip_address, success=False)
            if _is_rate_limited(ip_address):
                _maybe_notify_lockout(conn, username, ip_address)
            return RedirectResponse(
                url=f"/login?error=Invalid+username+or+password&next={quote_plus(safe_next)}",
                status_code=302
            )

        # Successful login - clear any previous failed attempts
        _clear_attempts(ip_address)

        # Create session
        token = create_session(user["id"])

        # Update last login
        update_last_login(conn, user)

        # Log successful login
        log_login(conn, user["id"], ip_address, success=True)

        # Redirect with session cookie
        response = RedirectResponse(url=safe_next, status_code=302)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=token,
            httponly=True,
            max_age=86400,
            samesite="strict",
            secure=_request_is_https(request)
        )

        return response


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request, success: str = None):
    """Show forgot-password form."""
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "success": success,
        }
    )


@router.post("/forgot-password")
async def forgot_password_submit(request: Request, email: str = Form(...)):
    """Handle forgot-password request."""
    ip_address = get_client_ip(request)
    email = (email or "").strip().lower()

    with get_db() as conn:
        cleanup_password_reset_tokens(conn)
        user = get_user_auth_by_email(conn, email)
        if user:
            token = create_password_reset_token(
                conn,
                user_id=user["id"],
                request_ip=ip_address,
                expires_minutes=PASSWORD_RESET_EXPIRY_MINUTES
            )
            reset_link = _build_absolute_url(request, f"/reset-password?token={token}")
            send_password_reset_email(
                email=user["email"],
                username=user["username"],
                reset_link=reset_link,
                expires_minutes=PASSWORD_RESET_EXPIRY_MINUTES
            )
            log_action(
                conn,
                user_id=user["id"],
                action="password_reset_requested",
                entity_type="user",
                entity_id=user["id"],
                details="Password reset email requested",
                ip_address=ip_address
            )

    message = "If that email exists in our system, a reset link has been sent."
    return RedirectResponse(url=f"/forgot-password?success={quote_plus(message)}", status_code=302)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str = "", error: str = None):
    """Show reset-password form."""
    token = _normalize_reset_token(token)
    valid_token = False
    if token:
        with get_db() as conn:
            valid_token = bool(get_password_reset_token(conn, token))

    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "token": token,
            "valid_token": valid_token,
            "error": error
        }
    )


@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Apply a password reset using a one-time token."""
    token = _normalize_reset_token(token)
    ip_address = get_client_ip(request)

    if new_password != confirm_password:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "token": token,
                "valid_token": True,
                "error": "Passwords do not match"
            }
        )

    password_error = validate_password(new_password)
    if password_error:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "token": token,
                "valid_token": True,
                "error": password_error
            }
        )

    with get_db() as conn:
        token_row = get_password_reset_token(conn, token)
        if not token_row:
            return templates.TemplateResponse(
                "reset_password.html",
                {
                    "request": request,
                    "token": token,
                    "valid_token": False,
                    "error": "This reset link is invalid or expired."
                }
            )

        update_user_password(conn, token_row["user_id"], new_password)
        mark_password_reset_token_used(conn, token)
        cleanup_password_reset_tokens(conn)
        log_password_change(conn, token_row["user_id"], ip_address)

    # Force logout everywhere after a password reset.
    invalidate_all_sessions(token_row["user_id"])

    return RedirectResponse(
        url="/login?success=Password+updated.+Please+log+in+again.",
        status_code=302
    )


@router.get("/account/security", response_class=HTMLResponse)
async def account_security_page(request: Request):
    """Show account security page (password change, sessions, GDPR actions)."""
    with get_db() as conn:
        user = get_current_user(request, conn)
        if not user:
            return RedirectResponse(url="/login", status_code=302)

        return templates.TemplateResponse(
            "account_security.html",
            {
                "request": request,
                "current_user": user
            }
        )


@router.post("/account/password")
async def account_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Change password for the currently logged-in user."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return RedirectResponse(url="/login", status_code=302)

    user_id = validate_session(token)
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            return RedirectResponse(url="/login", status_code=302)

        if not verify_user_password(conn, user_id, current_password):
            return templates.TemplateResponse(
                "account_security.html",
                {
                    "request": request,
                    "current_user": user,
                    "error": "Current password is incorrect."
                }
            )

        if new_password != confirm_password:
            return templates.TemplateResponse(
                "account_security.html",
                {
                    "request": request,
                    "current_user": user,
                    "error": "Passwords do not match."
                }
            )

        password_error = validate_password(new_password)
        if password_error:
            return templates.TemplateResponse(
                "account_security.html",
                {
                    "request": request,
                    "current_user": user,
                    "error": password_error
                }
            )

        update_user_password(conn, user_id, new_password)
        log_password_change(conn, user_id, get_client_ip(request))

    # Keep current browser session, revoke all others.
    invalidate_all_sessions(user_id, keep_token=token)

    return RedirectResponse(
        url="/account/security?success=Password+updated+successfully",
        status_code=302
    )


@router.get("/account/data-export")
async def account_data_export(request: Request):
    """Download GDPR export for current user."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return RedirectResponse(url="/login", status_code=302)

    user_id = validate_session(token)
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    with get_db() as conn:
        export_data = _build_user_gdpr_export(conn, user_id)
        if not export_data:
            return RedirectResponse(url="/account/security?error=Unable+to+export+data", status_code=302)

        user = export_data["user"]
        log_action(
            conn,
            user_id=user_id,
            action="gdpr_export",
            entity_type="user",
            entity_id=user_id,
            details="User exported personal data",
            ip_address=get_client_ip(request)
        )

    payload = json.dumps(export_data, indent=2, default=str).encode("utf-8")
    filename = f"gdpr_export_{user['username']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/account/data-delete")
async def account_data_delete(
    request: Request,
    current_password: str = Form(...),
    confirm_text: str = Form(...)
):
    """Delete current user account and personal data (GDPR self-service)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return RedirectResponse(url="/login", status_code=302)

    user_id = validate_session(token)
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    if confirm_text.strip().upper() != "DELETE":
        return RedirectResponse(
            url="/account/security?error=Type+DELETE+to+confirm+account+deletion",
            status_code=302
        )

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            return RedirectResponse(url="/login", status_code=302)

        if user["role"] == "admin":
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1")
            admin_count = cursor.fetchone()[0]
            if admin_count <= 1:
                return RedirectResponse(
                    url="/account/security?error=Cannot+delete+the+last+active+admin+account",
                    status_code=302
                )

        if not verify_user_password(conn, user_id, current_password):
            return RedirectResponse(
                url="/account/security?error=Current+password+is+incorrect",
                status_code=302
            )

        cursor = conn.cursor()
        cursor.execute("UPDATE audit_logs SET user_id = NULL WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM security_notifications WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))

        log_action(
            conn,
            user_id=None,
            action="gdpr_delete",
            entity_type="user",
            entity_id=user_id,
            details=f"Self-service account deletion for user '{user['username']}'",
            ip_address=get_client_ip(request)
        )

    response = RedirectResponse(
        url="/login?success=Account+deleted+successfully",
        status_code=302
    )
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.post("/logout-all")
async def logout_all(request: Request):
    """Log out from all devices for the current user."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return RedirectResponse(url="/login", status_code=302)

    user_id = validate_session(token)
    if not user_id:
        response = RedirectResponse(url="/login", status_code=302)
        response.delete_cookie(SESSION_COOKIE)
        return response

    with get_db() as conn:
        log_action(
            conn,
            user_id=user_id,
            action=AuditAction.LOGOUT,
            entity_type="user",
            entity_id=user_id,
            details="User logged out from all devices",
            ip_address=get_client_ip(request)
        )

    invalidate_all_sessions(user_id)
    response = RedirectResponse(url="/login?success=Logged+out+from+all+devices", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.post("/logout")
async def logout(request: Request):
    """Log out current user."""
    token = request.cookies.get(SESSION_COOKIE)
    ip_address = get_client_ip(request)

    if token:
        user_id = validate_session(token)
        if user_id:
            with get_db() as conn:
                log_logout(conn, user_id, ip_address)
        invalidate_session(token)

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)

    return response


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    """Public Terms of Service page."""
    return templates.TemplateResponse("terms.html", {"request": request})


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    """Public Privacy Policy page."""
    return templates.TemplateResponse("privacy.html", {"request": request})


@router.get("/api/user/current")
async def get_current_user_api(request: Request):
    """API endpoint to get current user info."""
    with get_db() as conn:
        user = get_current_user(request, conn)

        if not user:
            return {"authenticated": False}

        return {
            "authenticated": True,
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "full_name": user.get("full_name"),
            "role": user["role"]
        }
