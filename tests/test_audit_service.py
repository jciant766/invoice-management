"""
Pytest tests for services/audit_service.py

Uses isolated in-memory SQLite databases so tests never touch the real database.
"""
import sqlite3
import pytest

from models import AuditAction
from services.audit_service import (
    log_action,
    log_invoice_created,
    log_invoice_updated,
    log_invoice_deleted,
    log_invoice_status_change,
    log_user_created,
    log_user_deleted,
    log_user_updated,
    log_login,
    log_logout,
    log_export,
    log_settings_change,
    log_password_change,
    get_audit_logs,
    get_audit_log_count,
)


@pytest.fixture
def conn():
    """Create an isolated in-memory database with the required schema."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            details TEXT,
            ip_address TEXT,
            user_agent TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    # Insert a test user so that get_audit_logs LEFT JOIN resolves a username.
    db.execute("""
        INSERT INTO users (id, username, email, password_hash, role)
        VALUES (1, 'testadmin', 'admin@test.com', 'hash', 'admin')
    """)
    db.commit()
    yield db
    db.close()


# ---------- log_action() ----------

@pytest.mark.unit
def test_log_action_returns_row_id(conn):
    """log_action() should insert a record and return a positive integer row ID."""
    row_id = log_action(conn, user_id=1, action="test_action")
    assert isinstance(row_id, int)
    assert row_id > 0


@pytest.mark.unit
def test_log_action_stores_all_fields(conn):
    """log_action() should persist every supplied field correctly."""
    row_id = log_action(
        conn,
        user_id=1,
        action="full_field_test",
        entity_type="invoice",
        entity_id=42,
        details="testing all fields",
        ip_address="192.168.1.100",
    )

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["user_id"] == 1
    assert row["action"] == "full_field_test"
    assert row["entity_type"] == "invoice"
    assert row["entity_id"] == 42
    assert row["details"] == "testing all fields"
    assert row["ip_address"] == "192.168.1.100"
    assert row["timestamp"] is not None


# ---------- get_audit_logs() ----------

@pytest.mark.unit
def test_get_audit_logs_returns_logged_entries(conn):
    """get_audit_logs() should return entries that were previously logged."""
    log_action(conn, user_id=1, action="alpha", entity_type="invoice", entity_id=10)
    log_action(conn, user_id=1, action="beta", entity_type="user", entity_id=20)

    logs = get_audit_logs(conn)
    assert len(logs) >= 2

    actions = [entry["action"] for entry in logs]
    assert "alpha" in actions
    assert "beta" in actions


@pytest.mark.unit
def test_get_audit_logs_filters_by_action(conn):
    """get_audit_logs(action=...) should return only matching actions."""
    log_action(conn, user_id=1, action="keep_me", entity_type="invoice")
    log_action(conn, user_id=1, action="skip_me", entity_type="invoice")

    logs = get_audit_logs(conn, action="keep_me")
    assert len(logs) == 1
    assert logs[0]["action"] == "keep_me"


@pytest.mark.unit
def test_get_audit_logs_filters_by_entity_type(conn):
    """get_audit_logs(entity_type=...) should return only matching entity types."""
    log_action(conn, user_id=1, action="a1", entity_type="invoice")
    log_action(conn, user_id=1, action="a2", entity_type="user")
    log_action(conn, user_id=1, action="a3", entity_type="invoice")

    logs = get_audit_logs(conn, entity_type="invoice")
    assert len(logs) == 2
    assert all(entry["entity_type"] == "invoice" for entry in logs)


# ---------- get_audit_log_count() ----------

@pytest.mark.unit
def test_get_audit_log_count_returns_correct_count(conn):
    """get_audit_log_count() should reflect the exact number of matching records."""
    assert get_audit_log_count(conn) == 0

    log_action(conn, user_id=1, action="c1", entity_type="invoice")
    log_action(conn, user_id=1, action="c2", entity_type="invoice")
    log_action(conn, user_id=1, action="c3", entity_type="user")

    assert get_audit_log_count(conn) == 3
    assert get_audit_log_count(conn, entity_type="invoice") == 2
    assert get_audit_log_count(conn, action="c3") == 1


# ---------- Convenience functions ----------

@pytest.mark.unit
def test_log_invoice_created_action_string(conn):
    """log_invoice_created() should store the INVOICE_CREATE action."""
    row_id = log_invoice_created(conn, user_id=1, invoice_id=5, invoice_number="INV-001")
    cursor = conn.cursor()
    cursor.execute("SELECT action, entity_type, entity_id, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.INVOICE_CREATE
    assert row["entity_type"] == "invoice"
    assert row["entity_id"] == 5
    assert "INV-001" in row["details"]


@pytest.mark.unit
def test_log_invoice_updated_action_string(conn):
    """log_invoice_updated() should store INVOICE_UPDATE and optional changes."""
    row_id = log_invoice_updated(conn, user_id=1, invoice_id=5, invoice_number="INV-002", changes="amount changed")
    cursor = conn.cursor()
    cursor.execute("SELECT action, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.INVOICE_UPDATE
    assert "INV-002" in row["details"]
    assert "amount changed" in row["details"]


@pytest.mark.unit
def test_log_invoice_deleted_action_string(conn):
    """log_invoice_deleted() should store the INVOICE_DELETE action."""
    row_id = log_invoice_deleted(conn, user_id=1, invoice_id=7, invoice_number="INV-003")
    cursor = conn.cursor()
    cursor.execute("SELECT action, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.INVOICE_DELETE
    assert "INV-003" in row["details"]


@pytest.mark.unit
def test_log_invoice_status_change_action_string(conn):
    """log_invoice_status_change() should store INVOICE_STATUS with the new status."""
    row_id = log_invoice_status_change(conn, user_id=1, invoice_id=8, invoice_number="INV-004", new_status="approved")
    cursor = conn.cursor()
    cursor.execute("SELECT action, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.INVOICE_STATUS
    assert "approved" in row["details"]


@pytest.mark.unit
def test_log_user_created_action_string(conn):
    """log_user_created() should store USER_CREATE with the username."""
    row_id = log_user_created(conn, admin_id=1, new_user_id=99, username="newuser")
    cursor = conn.cursor()
    cursor.execute("SELECT action, entity_type, entity_id, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.USER_CREATE
    assert row["entity_type"] == "user"
    assert row["entity_id"] == 99
    assert "newuser" in row["details"]


@pytest.mark.unit
def test_log_user_deleted_action_string(conn):
    """log_user_deleted() should store USER_DELETE with the username."""
    row_id = log_user_deleted(conn, admin_id=1, target_user_id=50, username="olduser")
    cursor = conn.cursor()
    cursor.execute("SELECT action, entity_type, entity_id, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.USER_DELETE
    assert row["entity_type"] == "user"
    assert row["entity_id"] == 50
    assert "olduser" in row["details"]


@pytest.mark.unit
def test_log_login_success_action_string(conn):
    """log_login(success=True) should store LOGIN action."""
    row_id = log_login(conn, user_id=1, ip_address="10.0.0.1", success=True)
    cursor = conn.cursor()
    cursor.execute("SELECT action, details, ip_address FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.LOGIN
    assert "Successful" in row["details"]
    assert row["ip_address"] == "10.0.0.1"


@pytest.mark.unit
def test_log_login_failure_action_string(conn):
    """log_login(success=False) should store LOGIN_FAILED action."""
    row_id = log_login(conn, user_id=1, success=False)
    cursor = conn.cursor()
    cursor.execute("SELECT action, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.LOGIN_FAILED
    assert "Failed" in row["details"]


@pytest.mark.unit
def test_log_logout_action_string(conn):
    """log_logout() should store LOGOUT action."""
    row_id = log_logout(conn, user_id=1)
    cursor = conn.cursor()
    cursor.execute("SELECT action, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.LOGOUT
    assert "logged out" in row["details"]


@pytest.mark.unit
def test_log_export_action_string(conn):
    """log_export() should store EXPORT action with the export type."""
    row_id = log_export(conn, user_id=1, export_type="PDF", details="all invoices")
    cursor = conn.cursor()
    cursor.execute("SELECT action, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.EXPORT
    assert "PDF" in row["details"]


@pytest.mark.unit
def test_log_settings_change_action_string(conn):
    """log_settings_change() should store SETTINGS_CHANGE with the setting name."""
    row_id = log_settings_change(conn, user_id=1, setting_name="tax_rate")
    cursor = conn.cursor()
    cursor.execute("SELECT action, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.SETTINGS_CHANGE
    assert "tax_rate" in row["details"]


@pytest.mark.unit
def test_log_password_change_action_string(conn):
    """log_password_change() should store PASSWORD_CHANGE action."""
    row_id = log_password_change(conn, user_id=1)
    cursor = conn.cursor()
    cursor.execute("SELECT action, details FROM audit_logs WHERE id = ?", (row_id,))
    row = cursor.fetchone()

    assert row["action"] == AuditAction.PASSWORD_CHANGE
    assert "Password changed" in row["details"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
