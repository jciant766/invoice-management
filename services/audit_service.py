"""
Audit Logging Service

Tracks all user actions in the system for accountability and compliance.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any

from models import AuditAction


def log_action(
    conn,
    user_id: Optional[int],
    action: str,
    entity_type: str = None,
    entity_id: int = None,
    details: str = None,
    ip_address: str = None
) -> int:
    """Log an action to the audit trail. Returns the log ID."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details, ip_address, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, action, entity_type, entity_id, details, ip_address, datetime.now()))
    conn.commit()
    return cursor.lastrowid


def log_login(conn, user_id: int, ip_address: str = None, success: bool = True) -> int:
    """Log a login attempt."""
    action = AuditAction.LOGIN if success else AuditAction.LOGIN_FAILED
    details = "Successful login" if success else "Failed login attempt"
    return log_action(conn, user_id if success else None, action, "user", user_id, details, ip_address)


def log_logout(conn, user_id: int, ip_address: str = None) -> int:
    """Log a logout."""
    return log_action(conn, user_id, AuditAction.LOGOUT, "user", user_id, "User logged out", ip_address)


def log_invoice_created(conn, user_id: int, invoice_id: int, invoice_number: str, ip_address: str = None) -> int:
    """Log invoice creation."""
    return log_action(
        conn, user_id, AuditAction.INVOICE_CREATE, "invoice", invoice_id,
        f"Created invoice {invoice_number}", ip_address
    )


def log_invoice_updated(conn, user_id: int, invoice_id: int, invoice_number: str, changes: str = None, ip_address: str = None) -> int:
    """Log invoice update."""
    details = f"Updated invoice {invoice_number}"
    if changes:
        details += f": {changes}"
    return log_action(conn, user_id, AuditAction.INVOICE_UPDATE, "invoice", invoice_id, details, ip_address)


def log_invoice_deleted(conn, user_id: int, invoice_id: int, invoice_number: str, ip_address: str = None) -> int:
    """Log invoice deletion."""
    return log_action(
        conn, user_id, AuditAction.INVOICE_DELETE, "invoice", invoice_id,
        f"Deleted invoice {invoice_number}", ip_address
    )


def log_invoice_status_change(conn, user_id: int, invoice_id: int, invoice_number: str, new_status: str, ip_address: str = None) -> int:
    """Log invoice status change."""
    return log_action(
        conn, user_id, AuditAction.INVOICE_STATUS, "invoice", invoice_id,
        f"Changed invoice {invoice_number} status to {new_status}", ip_address
    )


def log_export(conn, user_id: int, export_type: str, details: str = None, ip_address: str = None) -> int:
    """Log an export action."""
    return log_action(conn, user_id, AuditAction.EXPORT, "export", None, f"Exported {export_type}: {details or ''}", ip_address)


def log_settings_change(conn, user_id: int, setting_name: str, ip_address: str = None) -> int:
    """Log a settings change."""
    return log_action(
        conn, user_id, AuditAction.SETTINGS_CHANGE, "settings", None,
        f"Changed setting: {setting_name}", ip_address
    )


def log_user_created(conn, admin_id: int, new_user_id: int, username: str, ip_address: str = None) -> int:
    """Log user creation by admin."""
    return log_action(
        conn, admin_id, AuditAction.USER_CREATE, "user", new_user_id,
        f"Created user: {username}", ip_address
    )


def log_user_updated(conn, admin_id: int, target_user_id: int, username: str, changes: str = None, ip_address: str = None) -> int:
    """Log user update by admin."""
    details = f"Updated user: {username}"
    if changes:
        details += f" - {changes}"
    return log_action(conn, admin_id, AuditAction.USER_UPDATE, "user", target_user_id, details, ip_address)


def log_user_deleted(conn, admin_id: int, target_user_id: int, username: str, ip_address: str = None) -> int:
    """Log user deletion by admin."""
    return log_action(
        conn, admin_id, AuditAction.USER_DELETE, "user", target_user_id,
        f"Deleted user: {username}", ip_address
    )


def log_password_change(conn, user_id: int, ip_address: str = None) -> int:
    """Log password change."""
    return log_action(conn, user_id, AuditAction.PASSWORD_CHANGE, "user", user_id, "Password changed", ip_address)


def get_audit_logs(
    conn,
    user_id: int = None,
    action: str = None,
    entity_type: str = None,
    entity_id: int = None,
    start_date: datetime = None,
    end_date: datetime = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Retrieve audit logs with optional filters."""
    cursor = conn.cursor()

    sql = """
        SELECT a.id, a.timestamp, a.user_id, u.username, a.action,
               a.entity_type, a.entity_id, a.details, a.ip_address
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        WHERE 1=1
    """
    params = []

    if user_id:
        sql += " AND a.user_id = ?"
        params.append(user_id)
    if action:
        sql += " AND a.action = ?"
        params.append(action)
    if entity_type:
        sql += " AND a.entity_type = ?"
        params.append(entity_type)
    if entity_id:
        sql += " AND a.entity_id = ?"
        params.append(entity_id)
    if start_date:
        sql += " AND a.timestamp >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND a.timestamp <= ?"
        params.append(end_date)

    sql += " ORDER BY a.timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(sql, params)

    logs = []
    for row in cursor.fetchall():
        logs.append({
            "id": row[0],
            "timestamp": row[1],
            "user_id": row[2],
            "username": row[3] or "System",
            "action": row[4],
            "entity_type": row[5],
            "entity_id": row[6],
            "details": row[7],
            "ip_address": row[8]
        })

    return logs


def get_audit_log_count(
    conn,
    user_id: int = None,
    action: str = None,
    entity_type: str = None,
    start_date: datetime = None,
    end_date: datetime = None
) -> int:
    """Get count of audit logs matching filters."""
    cursor = conn.cursor()

    sql = "SELECT COUNT(*) FROM audit_logs WHERE 1=1"
    params = []

    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)
    if action:
        sql += " AND action = ?"
        params.append(action)
    if entity_type:
        sql += " AND entity_type = ?"
        params.append(entity_type)
    if start_date:
        sql += " AND timestamp >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND timestamp <= ?"
        params.append(end_date)

    cursor.execute(sql, params)
    return cursor.fetchone()[0]
