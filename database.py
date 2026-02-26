"""
Database Configuration - Simple SQLite/SQLCipher
================================================
Direct database access without ORM overhead.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# --- DATABASE CONFIGURATION ---
# Use absolute path relative to this file's location to avoid directory confusion
_DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "invoice_management.db")
DATABASE_PATH = os.getenv("DATABASE_PATH", _DEFAULT_DB_PATH)
DATABASE_KEY = os.getenv("DATABASE_KEY", None)

# Check if SQLCipher is available
SQLCIPHER_AVAILABLE = False
sqlcipher3 = None
try:
    import sqlcipher3
    SQLCIPHER_AVAILABLE = True
except ImportError:
    try:
        import pysqlcipher3 as sqlcipher3
        SQLCIPHER_AVAILABLE = True
    except ImportError:
        pass

USE_ENCRYPTION = DATABASE_KEY and SQLCIPHER_AVAILABLE

if DATABASE_KEY and not SQLCIPHER_AVAILABLE:
    logger.warning("=" * 60)
    logger.warning("DATABASE_KEY is set but SQLCipher is not installed!")
    logger.warning("Database will NOT be encrypted.")
    logger.warning("=" * 60)


def get_connection():
    """Get a database connection (encrypted or plain)."""
    if USE_ENCRYPTION:
        conn = sqlcipher3.connect(DATABASE_PATH, check_same_thread=False)
        key_hex = DATABASE_KEY.encode('utf-8').hex()
        conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        conn.execute("PRAGMA cipher_compatibility = 4")
    else:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)

    # Critical SQLite pragmas for stability and data integrity
    conn.execute("PRAGMA busy_timeout = 5000")  # Wait 5s before SQLITE_BUSY error
    conn.execute("PRAGMA foreign_keys = ON")     # Enforce foreign key constraints

    # Return rows as dictionaries
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database tables if they don't exist."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Enable WAL mode for better concurrency (readers don't block writers)
        cursor.execute("PRAGMA journal_mode=WAL")

        # Suppliers table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                contact_email TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Invoices table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER NOT NULL,
                invoice_amount REAL NOT NULL,
                payment_amount REAL NOT NULL,
                method_request TEXT NOT NULL,
                method_procurement TEXT NOT NULL,
                description TEXT NOT NULL,
                invoice_date DATE NOT NULL,
                invoice_number TEXT NOT NULL,
                po_number TEXT,
                number_type TEXT DEFAULT 'TF',
                pjv_number TEXT NOT NULL UNIQUE,
                tf_number TEXT,
                chq_number TEXT,
                is_approved INTEGER DEFAULT 0,
                approved_date DATE,
                proposer_councillor TEXT,
                seconder_councillor TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_deleted INTEGER DEFAULT 0,
                fiscal_receipt_path TEXT,
                source_email_id TEXT,
                is_ai_generated INTEGER DEFAULT 0,
                is_void INTEGER DEFAULT 0,
                void_reason TEXT,
                voided_at TIMESTAMP,
                voided_by INTEGER,
                FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
            )
        """)

        # Settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Number sequences table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS number_sequences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number_type TEXT NOT NULL,
                year INTEGER NOT NULL,
                last_number INTEGER NOT NULL DEFAULT 0,
                UNIQUE(number_type, year)
            )
        """)

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
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

        # Sessions table (persistent session storage)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Login attempts table (persistent rate limiting)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Password reset tokens table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                request_ip TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Notification throttling table (prevents duplicate lockout emails)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                period_key TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, notification_type, period_key),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Audit logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
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

        # Add email metadata columns if they don't exist (migration)
        # Check if email_subject column exists
        cursor.execute("PRAGMA table_info(invoices)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'email_subject' not in columns:
            cursor.execute("ALTER TABLE invoices ADD COLUMN email_subject TEXT")
            logger.info("Added email_subject column to invoices table")

        if 'email_from' not in columns:
            cursor.execute("ALTER TABLE invoices ADD COLUMN email_from TEXT")
            logger.info("Added email_from column to invoices table")

        # Add voiding/audit columns for TF/CHQ preservation
        if 'is_void' not in columns:
            cursor.execute("ALTER TABLE invoices ADD COLUMN is_void INTEGER DEFAULT 0")
            logger.info("Added is_void column to invoices table")

        if 'void_reason' not in columns:
            cursor.execute("ALTER TABLE invoices ADD COLUMN void_reason TEXT")
            logger.info("Added void_reason column to invoices table")

        if 'voided_at' not in columns:
            cursor.execute("ALTER TABLE invoices ADD COLUMN voided_at TIMESTAMP")
            logger.info("Added voided_at column to invoices table")

        if 'voided_by' not in columns:
            cursor.execute("ALTER TABLE invoices ADD COLUMN voided_by INTEGER")
            logger.info("Added voided_by column to invoices table")

        # Suppliers table already has: contact_phone, address, vat_number, notes
        # No migration needed for those columns

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices(supplier_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_tf ON invoices(tf_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_deleted ON invoices(is_deleted)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip_address)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_time ON login_attempts(attempted_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reset_tokens_hash ON password_reset_tokens(token_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reset_tokens_user ON password_reset_tokens(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reset_tokens_expires ON password_reset_tokens(expires_at)")


def is_encrypted() -> bool:
    """Check if the database is using encryption."""
    return USE_ENCRYPTION


def get_encryption_status() -> dict:
    """Get detailed encryption status."""
    return {
        "encryption_enabled": USE_ENCRYPTION,
        "sqlcipher_available": SQLCIPHER_AVAILABLE,
        "key_configured": DATABASE_KEY is not None,
        "database_path": DATABASE_PATH
    }


# Log status on import
if USE_ENCRYPTION:
    logger.info("Database encryption: ENABLED (SQLCipher)")
else:
    logger.info("Database encryption: DISABLED (no DATABASE_KEY set)")
