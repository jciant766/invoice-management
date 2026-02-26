"""
Database Encryption Tool
========================

This tool encrypts an existing unencrypted SQLite database using SQLCipher.

Usage:
    python tools/encrypt_database.py

IMPORTANT:
- Back up your database before running this!
- You must have DATABASE_KEY set in your .env file
- You need sqlcipher3-binary installed: pip install sqlcipher3-binary

How it works:
1. Opens your existing unencrypted database
2. Creates a new encrypted copy
3. Verifies the encrypted database works
4. Replaces the old database with the encrypted one
"""

import os
import sys
import shutil
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


def encrypt_database():
    """Encrypt an existing SQLite database with SQLCipher."""

    # Get configuration
    database_path = os.getenv("DATABASE_PATH", "./invoice_management.db")
    database_key = os.getenv("DATABASE_KEY")

    # Resolve to absolute path
    if not os.path.isabs(database_path):
        database_path = os.path.join(Path(__file__).parent.parent, database_path)

    print("=" * 60)
    print("DATABASE ENCRYPTION TOOL")
    print("=" * 60)
    print()

    # Check prerequisites
    if not database_key:
        print("ERROR: DATABASE_KEY is not set in your .env file!")
        print()
        print("Add this line to your .env file:")
        print("  DATABASE_KEY=YourSecretKeyHere123!")
        print()
        print("Use a strong key with letters, numbers, and symbols.")
        return False

    if len(database_key) < 8:
        print("ERROR: DATABASE_KEY must be at least 8 characters!")
        return False

    try:
        import sqlcipher3
    except ImportError:
        print("ERROR: SQLCipher is not installed!")
        print()
        print("Install it with:")
        print("  pip install sqlcipher3-binary")
        return False

    if not os.path.exists(database_path):
        print(f"ERROR: Database not found at: {database_path}")
        return False

    # Check if database is already encrypted
    try:
        import sqlite3
        conn = sqlite3.connect(database_path)
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn.close()
        print(f"Found unencrypted database: {database_path}")
    except Exception as e:
        print(f"Database may already be encrypted or corrupted: {e}")
        print("If it's encrypted, no action needed.")
        return False

    # Create backup
    backup_path = f"{database_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"\nCreating backup: {backup_path}")
    shutil.copy2(database_path, backup_path)
    print("Backup created successfully.")

    # Create encrypted copy
    encrypted_path = f"{database_path}.encrypted"
    print(f"\nEncrypting database...")

    try:
        # Open unencrypted database with standard sqlite3
        import sqlite3
        source_conn = sqlite3.connect(database_path)

        # Create encrypted database with sqlcipher
        dest_conn = sqlcipher3.connect(encrypted_path)
        dest_conn.execute(f"PRAGMA key = '{database_key}'")
        dest_conn.execute("PRAGMA cipher_compatibility = 4")

        # Copy all data
        source_conn.backup(dest_conn)

        source_conn.close()
        dest_conn.close()

        print("Encryption complete.")

    except Exception as e:
        print(f"ERROR during encryption: {e}")
        if os.path.exists(encrypted_path):
            os.remove(encrypted_path)
        return False

    # Verify encrypted database
    print("\nVerifying encrypted database...")
    try:
        verify_conn = sqlcipher3.connect(encrypted_path)
        verify_conn.execute(f"PRAGMA key = '{database_key}'")
        verify_conn.execute("PRAGMA cipher_compatibility = 4")

        # Try to read some data
        cursor = verify_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        verify_conn.close()

        if not tables:
            print("WARNING: No tables found in encrypted database!")
            return False

        print(f"Verified: Found {len(tables)} tables")

    except Exception as e:
        print(f"ERROR: Failed to verify encrypted database: {e}")
        os.remove(encrypted_path)
        return False

    # Replace original with encrypted
    print("\nReplacing original database with encrypted version...")
    try:
        os.remove(database_path)
        shutil.move(encrypted_path, database_path)
        print("Done!")
    except Exception as e:
        print(f"ERROR: Failed to replace database: {e}")
        print(f"Encrypted database saved at: {encrypted_path}")
        return False

    print()
    print("=" * 60)
    print("SUCCESS! Database is now encrypted.")
    print("=" * 60)
    print()
    print("IMPORTANT:")
    print(f"- Backup saved at: {backup_path}")
    print("- Keep your DATABASE_KEY safe - you need it to access your data!")
    print("- Delete the backup once you've verified everything works.")
    print()

    return True


def decrypt_database():
    """Decrypt an encrypted database back to plain SQLite."""

    database_path = os.getenv("DATABASE_PATH", "./invoice_management.db")
    database_key = os.getenv("DATABASE_KEY")

    if not os.path.isabs(database_path):
        database_path = os.path.join(Path(__file__).parent.parent, database_path)

    print("=" * 60)
    print("DATABASE DECRYPTION TOOL")
    print("=" * 60)
    print()

    if not database_key:
        print("ERROR: DATABASE_KEY is required to decrypt!")
        return False

    try:
        import sqlcipher3
    except ImportError:
        print("ERROR: SQLCipher is not installed!")
        return False

    if not os.path.exists(database_path):
        print(f"ERROR: Database not found at: {database_path}")
        return False

    # Create backup
    backup_path = f"{database_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"Creating backup: {backup_path}")
    shutil.copy2(database_path, backup_path)

    # Create decrypted copy
    decrypted_path = f"{database_path}.decrypted"
    print(f"Decrypting database...")

    try:
        # Open encrypted database
        source_conn = sqlcipher3.connect(database_path)
        source_conn.execute(f"PRAGMA key = '{database_key}'")
        source_conn.execute("PRAGMA cipher_compatibility = 4")

        # Create unencrypted database
        import sqlite3
        dest_conn = sqlite3.connect(decrypted_path)

        # Copy all data
        source_conn.backup(dest_conn)

        source_conn.close()
        dest_conn.close()

        print("Decryption complete.")

    except Exception as e:
        print(f"ERROR during decryption: {e}")
        if os.path.exists(decrypted_path):
            os.remove(decrypted_path)
        return False

    # Replace original
    print("Replacing encrypted database with decrypted version...")
    os.remove(database_path)
    shutil.move(decrypted_path, database_path)

    print()
    print("SUCCESS! Database is now decrypted (unencrypted).")
    print(f"Backup saved at: {backup_path}")
    print()
    print("Remember to remove DATABASE_KEY from .env if you don't want encryption.")

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Database encryption tool")
    parser.add_argument("--decrypt", action="store_true", help="Decrypt instead of encrypt")
    args = parser.parse_args()

    if args.decrypt:
        success = decrypt_database()
    else:
        success = encrypt_database()

    sys.exit(0 if success else 1)
