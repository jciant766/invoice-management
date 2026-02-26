"""
Example pytest tests for the Invoice Management System.

These are proper pytest-style tests that can be run with:
    pytest
    pytest tests/
    pytest tests/test_example.py
    pytest -k test_database
"""
import pytest
from database import get_db


@pytest.mark.unit
def test_database_connection():
    """Test that database connection works."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        assert result[0] == 1


@pytest.mark.unit
def test_database_has_required_tables():
    """Test that all required tables exist."""
    required_tables = [
        'users', 'suppliers', 'invoices', 'sessions',
        'audit_logs', 'settings', 'number_sequences'
    ]

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = {row[0] for row in cursor.fetchall()}

        for table in required_tables:
            assert table in existing_tables, f"Table '{table}' is missing"


@pytest.mark.unit
def test_invoice_void_column_exists():
    """Test that is_void column exists in invoices table."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(invoices)")
        columns = {row[1] for row in cursor.fetchall()}

        assert 'is_void' in columns, "is_void column missing from invoices table"
        assert 'void_reason' in columns, "void_reason column missing"
        assert 'voided_at' in columns, "voided_at column missing"


@pytest.mark.unit
def test_password_hash_column_exists():
    """Test that users table has password_hash column."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in cursor.fetchall()}

        assert 'password_hash' in columns, "password_hash column missing"
        assert 'role' in columns, "role column missing"
        assert 'is_active' in columns, "is_active column missing"


if __name__ == "__main__":
    # Allow running this file directly
    pytest.main([__file__, "-v"])
