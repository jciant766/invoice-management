"""
Pytest configuration and fixtures for invoice management tests.

This file provides reusable test fixtures that can be used across all test files.
"""
import pytest
from database import get_db


@pytest.fixture(scope="session", autouse=True)
def setup_test_data():
    """
    Create test data once for all tests.
    This runs automatically before any tests execute.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Ensure we have at least one supplier with ID=1 for tests to use
        cursor.execute("SELECT id FROM suppliers WHERE id = 1")
        if not cursor.fetchone():
            # Create test supplier
            cursor.execute("""
                INSERT INTO suppliers (id, name, contact_email, is_active)
                VALUES (1, 'Test Supplier', 'test@example.com', 1)
            """)

    yield  # Run all tests

    # Cleanup is handled by each test


@pytest.fixture
def test_supplier_id():
    """
    Provide a valid supplier ID for tests.
    Returns supplier ID 1, which is guaranteed to exist.
    """
    return 1
