"""
Audit Log Routes

Admin-only routes for viewing audit logs.
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from database import get_db
from models import AuditAction
from services.audit_service import get_audit_logs, get_audit_log_count
from services.auth_service import get_all_users
from middleware import get_current_user
from routes.helpers import check_admin, build_pagination
from shared_templates import templates

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_class=HTMLResponse)
async def view_audit_logs(
    request: Request,
    user_id: int = None,
    action: str = None,
    entity_type: str = None,
    days: int = 7,
    page: int = 1
):
    """View audit logs with filtering (admin only)."""
    admin = check_admin(request)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days) if days else None
    per_page = 50

    with get_db() as conn:
        total_count = get_audit_log_count(
            conn=conn, user_id=user_id, action=action,
            entity_type=entity_type, start_date=start_date, end_date=end_date
        )
        pagination = build_pagination(page, per_page, total_count)

        logs = get_audit_logs(
            conn=conn, user_id=user_id, action=action,
            entity_type=entity_type, start_date=start_date, end_date=end_date,
            limit=per_page, offset=pagination['offset']
        )

        # Get users for filter dropdown
        users = get_all_users(conn)

        # Get available actions for filter
        actions = [
            {"value": AuditAction.LOGIN, "label": "Login"},
            {"value": AuditAction.LOGIN_FAILED, "label": "Login Failed"},
            {"value": AuditAction.LOGOUT, "label": "Logout"},
            {"value": AuditAction.INVOICE_CREATE, "label": "Invoice Created"},
            {"value": AuditAction.INVOICE_UPDATE, "label": "Invoice Updated"},
            {"value": AuditAction.INVOICE_DELETE, "label": "Invoice Deleted"},
            {"value": AuditAction.INVOICE_STATUS, "label": "Invoice Status Change"},
            {"value": AuditAction.EXPORT, "label": "Export"},
            {"value": AuditAction.SETTINGS_CHANGE, "label": "Settings Change"},
            {"value": AuditAction.USER_CREATE, "label": "User Created"},
            {"value": AuditAction.USER_UPDATE, "label": "User Updated"},
            {"value": AuditAction.USER_DELETE, "label": "User Deleted"},
            {"value": AuditAction.PASSWORD_CHANGE, "label": "Password Change"},
        ]

        # Entity types for filter
        entity_types = [
            {"value": "invoice", "label": "Invoices"},
            {"value": "user", "label": "Users"},
            {"value": "settings", "label": "Settings"},
            {"value": "export", "label": "Exports"},
        ]

        return templates.TemplateResponse("audit_logs.html", {
            "request": request,
            "logs": logs,
            "users": users,
            "actions": actions,
            "entity_types": entity_types,
            "current_user": admin,
            "filters": {
                "user_id": user_id,
                "action": action,
                "entity_type": entity_type,
                "days": days
            },
            "pagination": pagination
        })


@router.get("/api/logs")
async def get_logs_api(
    request: Request,
    user_id: int = None,
    action: str = None,
    entity_type: str = None,
    days: int = 7,
    page: int = 1,
    per_page: int = 50
):
    """API endpoint for audit logs (admin only)."""
    check_admin(request)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days) if days else None

    with get_db() as conn:
        total_count = get_audit_log_count(
            conn=conn, user_id=user_id, action=action,
            entity_type=entity_type, start_date=start_date, end_date=end_date
        )
        pagination = build_pagination(page, per_page, total_count)

        logs = get_audit_logs(
            conn=conn, user_id=user_id, action=action,
            entity_type=entity_type, start_date=start_date, end_date=end_date,
            limit=per_page, offset=pagination['offset']
        )

        return {"success": True, "logs": logs, "pagination": pagination}
