"""
Authentication Service

Handles user authentication, password hashing, and session management.
Sessions are stored in the database for persistence across restarts.
"""

import logging
import os
import hashlib
import secrets
import sqlite3
import string
from datetime import datetime, timedelta
from typing import Optional
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

from database import get_connection

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Session duration
SESSION_DURATION_HOURS = 24


def hash_password(password: str) -> str:
    """Hash a password for storing."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(conn, username: str, password: str) -> Optional[dict]:
    """
    Authenticate a user with username and password.
    Returns user dict if successful, None otherwise.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, password_hash, full_name, role, is_active
        FROM users
        WHERE (username = ? OR email = ?) AND is_active = 1
    """, (username, username))

    row = cursor.fetchone()
    if not row:
        return None

    user = dict(row)

    # Verify password using bcrypt
    if not verify_password(password, user['password_hash']):
        return None

    return user


def create_session(user_id: int) -> str:
    """Create a new session token for a user (stored in database)."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=SESSION_DURATION_HOURS)

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires)
        )
        conn.commit()
    finally:
        conn.close()

    return token


def validate_session(token: str) -> Optional[int]:
    """Validate a session token. Returns user_id if valid."""
    if not token:
        return None

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token = ?",
            (token,)
        )
        row = cursor.fetchone()

        if not row:
            return None

        expires_at = row["expires_at"]
        # Handle both string and datetime formats
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)

        if datetime.now() > expires_at:
            # Expired - clean it up
            cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None

        return row["user_id"]
    finally:
        conn.close()


def invalidate_session(token: str) -> bool:
    """Invalidate (logout) a session."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def cleanup_expired_sessions() -> int:
    """Remove all expired sessions from the database. Returns count removed."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now(),))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def invalidate_all_sessions(user_id: int, keep_token: Optional[str] = None) -> int:
    """Invalidate all sessions for a user. Optionally keep one token."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if keep_token:
            cursor.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token != ?",
                (user_id, keep_token)
            )
        else:
            cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def _hash_reset_token(token: str) -> str:
    """Hash a password reset token for safe storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_password_reset_token(
    conn,
    user_id: int,
    request_ip: str = None,
    expires_minutes: int = 60
) -> str:
    """Create and store a password reset token, returning the plain token."""
    plain_token = secrets.token_urlsafe(48)
    token_hash = _hash_reset_token(plain_token)
    expires_at = datetime.now() + timedelta(minutes=expires_minutes)

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, request_ip)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, token_hash, expires_at, request_ip)
    )
    conn.commit()
    return plain_token


def get_password_reset_token(conn, token: str) -> Optional[dict]:
    """Get an unused, unexpired password reset token record."""
    token_hash = _hash_reset_token(token)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT t.id, t.user_id, t.expires_at, t.used_at, u.email, u.username
        FROM password_reset_tokens t
        JOIN users u ON u.id = t.user_id
        WHERE t.token_hash = ? AND t.used_at IS NULL
        """,
        (token_hash,)
    )
    row = cursor.fetchone()
    if not row:
        return None

    token_row = dict(row)
    expires_at = token_row["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if datetime.now() > expires_at:
        return None

    return token_row


def mark_password_reset_token_used(conn, token: str) -> bool:
    """Mark a reset token as used. Returns True when token was updated."""
    token_hash = _hash_reset_token(token)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE password_reset_tokens
        SET used_at = ?
        WHERE token_hash = ? AND used_at IS NULL
        """,
        (datetime.now(), token_hash)
    )
    conn.commit()
    return cursor.rowcount > 0


def cleanup_password_reset_tokens(conn) -> int:
    """Delete expired password reset tokens."""
    cursor = conn.cursor()
    cursor.execute(
        """
        DELETE FROM password_reset_tokens
        WHERE expires_at < ?
        """,
        (datetime.now(),)
    )
    conn.commit()
    return cursor.rowcount


def mark_security_notification_sent(
    conn,
    user_id: int,
    notification_type: str,
    period_key: str
) -> bool:
    """
    Mark a security notification as sent.
    Returns False if already sent for this user/type/period.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO security_notifications (user_id, notification_type, period_key)
            VALUES (?, ?, ?)
            """,
            (user_id, notification_type, period_key)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_user_by_id(conn, user_id: int) -> Optional[dict]:
    """Get a user by their ID."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, full_name, role, is_active, created_at, last_login
        FROM users WHERE id = ?
    """, (user_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_user_by_username(conn, username: str) -> Optional[dict]:
    """Get a user by their username."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, full_name, role, is_active, created_at, last_login
        FROM users WHERE username = ?
    """, (username,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_user_by_email(conn, email: str) -> Optional[dict]:
    """Get a user by email (case-insensitive)."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, full_name, role, is_active, created_at, last_login
        FROM users WHERE LOWER(email) = LOWER(?)
    """, (email,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_user_auth_by_email(conn, email: str) -> Optional[dict]:
    """Get a user by email including password hash (for auth checks)."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, password_hash, full_name, role, is_active
        FROM users WHERE LOWER(email) = LOWER(?) AND is_active = 1
    """, (email,))
    row = cursor.fetchone()
    return dict(row) if row else None


def create_user(conn, username: str, email: str, password: str,
                full_name: str = None, role: str = "user") -> dict:
    """Create a new user."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (username, email, password_hash, full_name, role, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
    """, (username, email, hash_password(password), full_name, role))

    user_id = cursor.lastrowid
    conn.commit()

    return get_user_by_id(conn, user_id)


def update_user_password(conn, user_id: int, new_password: str) -> None:
    """Update a user's password."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET password_hash = ? WHERE id = ?
    """, (hash_password(new_password), user_id))
    conn.commit()


def verify_user_password(conn, user_id: int, plain_password: str) -> bool:
    """Verify a plain password against the user's current password hash."""
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE id = ? AND is_active = 1", (user_id,))
    row = cursor.fetchone()
    if not row:
        return False
    return verify_password(plain_password, row["password_hash"])


def update_last_login(conn, user: dict) -> None:
    """Update the user's last login timestamp."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET last_login = ? WHERE id = ?
    """, (datetime.now(), user['id']))
    conn.commit()


def get_all_users(conn) -> list:
    """Get all users (for admin user management)."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, email, full_name, role, is_active, created_at, last_login
        FROM users ORDER BY created_at DESC
    """)
    return [dict(row) for row in cursor.fetchall()]


def validate_password(password: str) -> Optional[str]:
    """Validate password meets policy. Returns error message or None if valid."""
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not any(c.isupper() for c in password):
        return "Password must contain at least one uppercase letter"
    if not any(c.isdigit() for c in password):
        return "Password must contain at least one number"
    return None


def generate_secure_password(length: int = 16) -> str:
    """Generate a cryptographically secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def create_default_admin(conn) -> Optional[dict]:
    """Create a default admin user if no users exist."""
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users LIMIT 1")

    if cursor.fetchone():
        return None

    # Generate a secure random password
    secure_password = generate_secure_password(20)

    # Create default admin
    admin = create_user(
        conn=conn,
        username="admin",
        email="admin@localhost",
        password=secure_password,
        full_name="Administrator",
        role="admin"
    )

    # Write credentials to a file instead of printing to console/logs
    creds_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ADMIN_CREDENTIALS.txt")
    with open(creds_path, "w") as f:
        f.write("FIRST-TIME SETUP: DEFAULT ADMIN ACCOUNT\n")
        f.write("=" * 45 + "\n")
        f.write(f"Username: admin\n")
        f.write(f"Password: {secure_password}\n")
        f.write("=" * 45 + "\n")
        f.write("IMPORTANT: Delete this file after you save the password.\n")
        f.write("Change this password after your first login.\n")

    logger.info("=" * 60)
    logger.info("FIRST-TIME SETUP: Admin account created.")
    logger.info(f"Credentials saved to: {creds_path}")
    logger.info("=" * 60)

    return admin
