"""
User Management Routes

Admin-only routes for managing users.
"""

import re
import json
from datetime import datetime
from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse

from database import get_db
from services.auth_service import (
    get_all_users,
    get_user_by_id,
    get_user_by_username,
    create_user,
    update_user_password,
    validate_password
)
from services.audit_service import (
    log_user_created,
    log_user_updated,
    log_user_deleted,
    log_password_change,
    log_action
)
from routes.helpers import check_admin, get_client_ip, build_pagination
from shared_templates import templates

router = APIRouter(prefix="/users", tags=["users"])
ALLOWED_USER_ROLES = {"user", "admin"}


def _build_user_gdpr_export(conn, user_id: int) -> dict:
    """Build a GDPR export payload for admin download."""
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


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=10, le=100, description="Items per page")
):
    """List all users with pagination (admin only)."""
    admin = check_admin(request)

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM users")
        total_count = cursor.fetchone()[0]
        pagination = build_pagination(page, per_page, total_count)

        cursor.execute("""
            SELECT id, username, email, full_name, role, is_active, created_at, last_login
            FROM users ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (per_page, pagination['offset']))
        users = [dict(row) for row in cursor.fetchall()]

        return templates.TemplateResponse("users.html", {
            "request": request,
            "users": users,
            "current_user": admin,
            "pagination": pagination
        })


@router.get("/create", response_class=HTMLResponse)
async def create_user_form(request: Request):
    """Show create user form (admin only)."""
    admin = check_admin(request)

    return templates.TemplateResponse("user_form.html", {
        "request": request,
        "user": None,
        "current_user": admin,
        "title": "Create User"
    })


@router.post("/create")
async def create_user_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(None),
    role: str = Form("user")
):
    """Create a new user (admin only)."""
    admin = check_admin(request)
    ip_address = get_client_ip(request)
    username = (username or "").strip()
    email = (email or "").strip().lower()
    role = (role or "user").strip().lower()
    full_name = full_name.strip() if full_name else None

    if not re.fullmatch(r"[A-Za-z0-9_]+", username):
        return templates.TemplateResponse("user_form.html", {
            "request": request,
            "user": None,
            "current_user": admin,
            "title": "Create User",
            "error": "Username can only contain letters, numbers, and underscores"
        })

    if role not in ALLOWED_USER_ROLES:
        return templates.TemplateResponse("user_form.html", {
            "request": request,
            "user": None,
            "current_user": admin,
            "title": "Create User",
            "error": "Invalid role selected"
        })

    password_error = validate_password(password)
    if password_error:
        return templates.TemplateResponse("user_form.html", {
            "request": request,
            "user": None,
            "current_user": admin,
            "title": "Create User",
            "error": password_error
        })

    with get_db() as conn:
        # Check for duplicate username
        existing = get_user_by_username(conn, username)
        if existing:
            return templates.TemplateResponse("user_form.html", {
                "request": request,
                "user": None,
                "current_user": admin,
                "title": "Create User",
                "error": f"Username '{username}' already exists"
            })

        # Check for duplicate email
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(?)", (email,))
        if cursor.fetchone():
            return templates.TemplateResponse("user_form.html", {
                "request": request,
                "user": None,
                "current_user": admin,
                "title": "Create User",
                "error": f"Email '{email}' already exists"
            })

        # Create user
        new_user = create_user(
            conn=conn,
            username=username,
            email=email,
            password=password,
            full_name=full_name,
            role=role
        )

        # Log the action
        log_user_created(conn, admin.id, new_user['id'], username, ip_address)

        return RedirectResponse(url="/users?success=User+created+successfully", status_code=302)


@router.get("/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_form(request: Request, user_id: int):
    """Show edit user form (admin only)."""
    admin = check_admin(request)

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return templates.TemplateResponse("user_form.html", {
            "request": request,
            "user": user,
            "current_user": admin,
            "title": "Edit User"
        })


@router.post("/{user_id}/edit")
async def edit_user_submit(
    request: Request,
    user_id: int,
    email: str = Form(...),
    full_name: str = Form(None),
    role: str = Form("user"),
    is_active: bool = Form(False)
):
    """Update user details (admin only)."""
    admin = check_admin(request)
    ip_address = get_client_ip(request)
    email = (email or "").strip().lower()
    full_name = full_name.strip() if full_name else None
    role = (role or "user").strip().lower()
    is_active_int = 1 if is_active else 0

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if role not in ALLOWED_USER_ROLES:
            return templates.TemplateResponse("user_form.html", {
                "request": request,
                "user": user,
                "current_user": admin,
                "title": "Edit User",
                "error": "Invalid role selected"
            })

        # Prevent deactivating your own account from the edit form
        if user['id'] == admin.id and is_active_int == 0:
            return RedirectResponse(url="/users?error=Cannot+deactivate+your+own+account", status_code=302)

        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(?) AND id != ?",
            (email, user_id)
        )
        if cursor.fetchone():
            user_preview = dict(user)
            user_preview["email"] = email
            user_preview["full_name"] = full_name
            user_preview["role"] = role
            user_preview["is_active"] = is_active_int
            return templates.TemplateResponse("user_form.html", {
                "request": request,
                "user": user_preview,
                "current_user": admin,
                "title": "Edit User",
                "error": f"Email '{email}' already exists"
            })

        # Track changes for audit log
        changes = []
        if user['email'] != email:
            changes.append(f"email: {user['email']} -> {email}")
        if user.get('full_name') != full_name:
            changes.append(f"name: {user.get('full_name') or 'None'} -> {full_name or 'None'}")
        if user['role'] != role:
            changes.append(f"role: {user['role']} -> {role}")
        if user['is_active'] != is_active_int:
            changes.append(f"active: {user['is_active']} -> {is_active_int}")

        # Update user
        cursor.execute("""
            UPDATE users SET email = ?, full_name = ?, role = ?, is_active = ?
            WHERE id = ?
        """, (email, full_name, role, is_active_int, user_id))

        # Log the action
        if changes:
            log_user_updated(conn, admin.id, user_id, user['username'], ", ".join(changes), ip_address)

        return RedirectResponse(url="/users?success=User+updated+successfully", status_code=302)


@router.get("/{user_id}/password", response_class=HTMLResponse)
async def change_password_form(request: Request, user_id: int):
    """Show change password form (admin only)."""
    admin = check_admin(request)
    if user_id == admin.id:
        return RedirectResponse(
            url="/account/security?error=Use+Account+Security+to+change+your+own+password",
            status_code=302
        )

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return templates.TemplateResponse("user_password.html", {
            "request": request,
            "user": user,
            "current_user": admin
        })


@router.post("/{user_id}/password")
async def change_password_submit(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Change user password (admin only)."""
    admin = check_admin(request)
    if user_id == admin.id:
        return RedirectResponse(
            url="/account/security?error=Use+Account+Security+to+change+your+own+password",
            status_code=302
        )
    ip_address = get_client_ip(request)

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if new_password != confirm_password:
            return templates.TemplateResponse("user_password.html", {
                "request": request,
                "user": user,
                "current_user": admin,
                "error": "Passwords do not match"
            })

        password_error = validate_password(new_password)
        if password_error:
            return templates.TemplateResponse("user_password.html", {
                "request": request,
                "user": user,
                "current_user": admin,
                "error": password_error
            })

        # Update password
        update_user_password(conn, user_id, new_password)

        # Log the action
        log_password_change(conn, user_id, ip_address)

        return RedirectResponse(url="/users?success=Password+changed+successfully", status_code=302)


@router.post("/{user_id}/delete")
async def delete_user(request: Request, user_id: int):
    """Delete a user (admin only)."""
    admin = check_admin(request)
    ip_address = get_client_ip(request)

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Prevent deleting yourself
        if user['id'] == admin.id:
            return RedirectResponse(url="/users?error=Cannot+delete+your+own+account", status_code=302)

        # Delete user first, then log (audit should reflect actual state)
        cursor = conn.cursor()
        username_for_log = user['username']  # Save before deletion
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))

        # Log AFTER successful deletion
        log_user_deleted(conn, admin.id, user_id, username_for_log, ip_address)

        return RedirectResponse(url="/users?success=User+deleted+successfully", status_code=302)


@router.get("/{user_id}/gdpr-export")
async def gdpr_export_user(request: Request, user_id: int):
    """Export a user's personal data in JSON format (admin only)."""
    admin = check_admin(request)
    ip_address = get_client_ip(request)

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        payload = _build_user_gdpr_export(conn, user_id)
        if not payload:
            raise HTTPException(status_code=404, detail="User not found")

        log_action(
            conn,
            user_id=admin.id,
            action="gdpr_export",
            entity_type="user",
            entity_id=user_id,
            details=f"Admin exported GDPR data for user '{user['username']}'",
            ip_address=ip_address
        )

    content = json.dumps(payload, indent=2, default=str).encode("utf-8")
    filename = f"gdpr_export_{user['username']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/{user_id}/gdpr-delete")
async def gdpr_delete_user(request: Request, user_id: int):
    """Delete user account and related personal data (admin only)."""
    admin = check_admin(request)
    ip_address = get_client_ip(request)

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if user["id"] == admin.id:
            return RedirectResponse(url="/users?error=Use+account+settings+to+delete+your+own+account", status_code=302)

        if user["role"] == "admin":
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1")
            admin_count = cursor.fetchone()[0]
            if admin_count <= 1:
                return RedirectResponse(url="/users?error=Cannot+delete+the+last+active+admin", status_code=302)

        cursor = conn.cursor()
        cursor.execute("UPDATE audit_logs SET user_id = NULL WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM security_notifications WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))

        log_action(
            conn,
            user_id=admin.id,
            action="gdpr_delete",
            entity_type="user",
            entity_id=user_id,
            details=f"Admin deleted user '{user['username']}' under GDPR request",
            ip_address=ip_address
        )

        return RedirectResponse(url="/users?success=User+data+deleted+for+GDPR+request", status_code=302)


@router.post("/{user_id}/toggle-active")
async def toggle_user_active(request: Request, user_id: int):
    """Toggle user active status (admin only)."""
    admin = check_admin(request)
    ip_address = get_client_ip(request)

    with get_db() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Prevent deactivating yourself
        if user['id'] == admin.id:
            return RedirectResponse(url="/users?error=Cannot+deactivate+your+own+account", status_code=302)

        old_status = user['is_active']
        new_status = 0 if old_status else 1

        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, user_id))

        # Log the action
        status_change = f"active: {old_status} -> {new_status}"
        log_user_updated(conn, admin.id, user_id, user['username'], status_change, ip_address)

        status_text = "activated" if new_status else "deactivated"
        return RedirectResponse(url=f"/users?success=User+{status_text}+successfully", status_code=302)
