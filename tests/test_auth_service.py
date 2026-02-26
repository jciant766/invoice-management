"""
Pytest tests for the authentication service (services/auth_service.py).

Tests cover password hashing, password validation, session management,
and password reset token functionality using an isolated temporary SQLite database.
"""
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

import sys
import os

# Ensure the project root is on the path so we can import services and database
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.auth_service import (
    hash_password,
    verify_password,
    validate_password,
    create_session,
    validate_session,
    invalidate_session,
    create_password_reset_token,
    get_password_reset_token,
    mark_password_reset_token_used,
)


@pytest.fixture
def auth_db(tmp_path):
    """
    Create a temporary SQLite database with the required schema for auth tests.
    Patches database.DATABASE_PATH and database.get_connection so all service
    functions that call get_connection() use this isolated database.
    """
    db_path = str(tmp_path / "test_auth.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row

    # Create the tables the auth service depends on
    conn.executescript("""
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
        );

        CREATE TABLE sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP,
            request_ip TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
    """)
    conn.commit()
    conn.close()

    def _get_test_connection():
        c = sqlite3.connect(db_path, check_same_thread=False)
        c.execute("PRAGMA busy_timeout = 5000")
        c.execute("PRAGMA foreign_keys = ON")
        c.row_factory = sqlite3.Row
        return c

    with patch("services.auth_service.get_connection", side_effect=_get_test_connection):
        yield db_path, _get_test_connection


@pytest.fixture
def test_user(auth_db):
    """Insert a test user into the temporary database and return their details."""
    _, get_conn = auth_db
    hashed = hash_password("ValidPass1")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (username, email, password_hash, full_name, role) "
            "VALUES (?, ?, ?, ?, ?)",
            ("testuser", "testuser@example.com", hashed, "Test User", "user"),
        )
        conn.commit()
        user_id = conn.execute(
            "SELECT id FROM users WHERE username = 'testuser'"
        ).fetchone()[0]
    finally:
        conn.close()
    return {"id": user_id, "username": "testuser", "password": "ValidPass1"}


# ---------------------------------------------------------------------------
# 1. hash_password / verify_password roundtrip
# ---------------------------------------------------------------------------
class TestPasswordHashing:

    def test_hash_and_verify_roundtrip(self):
        """Hashing a password then verifying with the same input returns True."""
        plain = "MySecureP@ss1"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_hash_produces_different_hashes_for_same_input(self):
        """Two calls to hash_password with the same input produce different hashes (salt)."""
        plain = "SamePassword9"
        hash1 = hash_password(plain)
        hash2 = hash_password(plain)
        assert hash1 != hash2, "Hashes should differ due to random salt"
        # Both should still verify correctly
        assert verify_password(plain, hash1) is True
        assert verify_password(plain, hash2) is True

    def test_verify_rejects_wrong_password(self):
        """verify_password returns False when the plain password does not match."""
        hashed = hash_password("CorrectPassword1")
        assert verify_password("WrongPassword1", hashed) is False


# ---------------------------------------------------------------------------
# 4. validate_password - test each rule independently
# ---------------------------------------------------------------------------
class TestValidatePassword:

    def test_rejects_password_under_minimum_length(self):
        """Passwords shorter than 8 characters are rejected."""
        result = validate_password("Short1A")
        assert result is not None
        assert "8 characters" in result

    def test_rejects_password_without_uppercase(self):
        """Passwords without any uppercase letter are rejected."""
        result = validate_password("alllowercase1")
        assert result is not None
        assert "uppercase" in result

    def test_rejects_password_without_digit(self):
        """Passwords without any digit are rejected."""
        result = validate_password("NoDigitsHere")
        assert result is not None
        assert "number" in result

    def test_accepts_valid_password(self):
        """A password meeting all rules returns None (no error)."""
        result = validate_password("GoodPass1")
        assert result is None

    def test_accepts_password_at_exact_minimum_length(self):
        """A password that is exactly 8 characters and meets all rules is accepted."""
        result = validate_password("Abcdefg1")
        assert result is None


# ---------------------------------------------------------------------------
# 5. create_session creates a valid session record
# ---------------------------------------------------------------------------
class TestCreateSession:

    def test_create_session_returns_token_and_stores_record(self, auth_db, test_user):
        """create_session returns a non-empty token and stores it in the database."""
        _, get_conn = auth_db
        token = create_session(test_user["id"])

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

        # Verify the session row exists in the database
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token = ?",
                (token,),
            ).fetchone()
            assert row is not None
            assert row["user_id"] == test_user["id"]
            # expires_at should be in the future
            expires_at = row["expires_at"]
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            assert expires_at > datetime.now()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 6. validate_session returns user_id for valid session
# ---------------------------------------------------------------------------
class TestValidateSession:

    def test_validate_session_returns_user_id_for_valid_session(self, auth_db, test_user):
        """A freshly created session is valid and returns the correct user_id."""
        token = create_session(test_user["id"])
        user_id = validate_session(token)
        assert user_id == test_user["id"]

    def test_validate_session_returns_none_for_expired_session(self, auth_db, test_user):
        """An expired session returns None."""
        _, get_conn = auth_db

        # Manually insert an expired session
        expired_time = datetime.now() - timedelta(hours=1)
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                ("expired-token-abc", test_user["id"], expired_time),
            )
            conn.commit()
        finally:
            conn.close()

        result = validate_session("expired-token-abc")
        assert result is None

    def test_validate_session_returns_none_for_invalid_token(self, auth_db):
        """A token that does not exist in the database returns None."""
        result = validate_session("nonexistent-token-xyz")
        assert result is None

    def test_validate_session_returns_none_for_empty_token(self, auth_db):
        """An empty string or None token returns None."""
        assert validate_session("") is None
        assert validate_session(None) is None


# ---------------------------------------------------------------------------
# 8. invalidate_session removes session
# ---------------------------------------------------------------------------
class TestInvalidateSession:

    def test_invalidate_session_removes_session(self, auth_db, test_user):
        """After invalidation, the session token can no longer be validated."""
        token = create_session(test_user["id"])
        # Confirm it is valid first
        assert validate_session(token) == test_user["id"]

        result = invalidate_session(token)
        assert result is True

        # Now validation should fail
        assert validate_session(token) is None

    def test_invalidate_session_returns_false_for_unknown_token(self, auth_db):
        """Invalidating a token that does not exist returns False."""
        result = invalidate_session("does-not-exist-token")
        assert result is False


# ---------------------------------------------------------------------------
# 9. create_password_reset_token returns a token
# 10. Password reset token can be retrieved and used
# ---------------------------------------------------------------------------
class TestPasswordResetToken:

    def test_create_password_reset_token_returns_token(self, auth_db, test_user):
        """create_password_reset_token returns a non-empty string token."""
        _, get_conn = auth_db
        conn = get_conn()
        try:
            token = create_password_reset_token(conn, test_user["id"], request_ip="127.0.0.1")
            assert token is not None
            assert isinstance(token, str)
            assert len(token) > 0
        finally:
            conn.close()

    def test_password_reset_token_can_be_retrieved(self, auth_db, test_user):
        """A created reset token can be looked up via get_password_reset_token."""
        _, get_conn = auth_db
        conn = get_conn()
        try:
            plain_token = create_password_reset_token(conn, test_user["id"])
            record = get_password_reset_token(conn, plain_token)

            assert record is not None
            assert record["user_id"] == test_user["id"]
            assert record["used_at"] is None
        finally:
            conn.close()

    def test_password_reset_token_can_be_marked_used(self, auth_db, test_user):
        """After marking a token as used, it can no longer be retrieved."""
        _, get_conn = auth_db
        conn = get_conn()
        try:
            plain_token = create_password_reset_token(conn, test_user["id"])

            # Mark it used
            result = mark_password_reset_token_used(conn, plain_token)
            assert result is True

            # Now retrieval should return None (used tokens are excluded)
            record = get_password_reset_token(conn, plain_token)
            assert record is None
        finally:
            conn.close()

    def test_get_password_reset_token_returns_none_for_invalid_token(self, auth_db, test_user):
        """Looking up a token that was never created returns None."""
        _, get_conn = auth_db
        conn = get_conn()
        try:
            record = get_password_reset_token(conn, "bogus-token-value")
            assert record is None
        finally:
            conn.close()

    def test_expired_password_reset_token_returns_none(self, auth_db, test_user):
        """An expired password reset token cannot be retrieved."""
        _, get_conn = auth_db
        conn = get_conn()
        try:
            # Create a token that expires immediately (0 minutes)
            plain_token = create_password_reset_token(
                conn, test_user["id"], expires_minutes=0
            )
            record = get_password_reset_token(conn, plain_token)
            assert record is None
        finally:
            conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
