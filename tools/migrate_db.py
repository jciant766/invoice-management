"""
Database Migration Script
=========================
Adds missing columns to the database schema.

Run this script once to update your database:
    python tools/migrate_db.py
"""

import os
import sys
import sqlite3

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DATABASE_PATH

def get_existing_columns(cursor, table_name):
    """Get list of existing columns in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]

def migrate():
    """Run database migrations."""
    print(f"Connecting to database: {DATABASE_PATH}")

    # Connect to the database
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    try:
        # Get existing columns in invoices table
        existing_columns = get_existing_columns(cursor, "invoices")
        print(f"Existing columns in 'invoices': {existing_columns}")

        migrations_run = 0

        # Add number_type column if missing
        if "number_type" not in existing_columns:
            print("Adding 'number_type' column to invoices table...")
            cursor.execute("""
                ALTER TABLE invoices
                ADD COLUMN number_type VARCHAR(10) DEFAULT 'TF'
            """)
            migrations_run += 1
            print("  -> Added 'number_type' column")

        # Add chq_number column if missing
        if "chq_number" not in existing_columns:
            print("Adding 'chq_number' column to invoices table...")
            cursor.execute("""
                ALTER TABLE invoices
                ADD COLUMN chq_number VARCHAR(100)
            """)
            migrations_run += 1
            print("  -> Added 'chq_number' column")

        # Add fiscal_receipt_path column if missing
        if "fiscal_receipt_path" not in existing_columns:
            print("Adding 'fiscal_receipt_path' column to invoices table...")
            cursor.execute("""
                ALTER TABLE invoices
                ADD COLUMN fiscal_receipt_path VARCHAR(500)
            """)
            migrations_run += 1
            print("  -> Added 'fiscal_receipt_path' column")

        # Add source_email_id column if missing
        if "source_email_id" not in existing_columns:
            print("Adding 'source_email_id' column to invoices table...")
            cursor.execute("""
                ALTER TABLE invoices
                ADD COLUMN source_email_id VARCHAR(255)
            """)
            migrations_run += 1
            print("  -> Added 'source_email_id' column")

        # Add is_ai_generated column if missing
        if "is_ai_generated" not in existing_columns:
            print("Adding 'is_ai_generated' column to invoices table...")
            cursor.execute("""
                ALTER TABLE invoices
                ADD COLUMN is_ai_generated BOOLEAN DEFAULT 0
            """)
            migrations_run += 1
            print("  -> Added 'is_ai_generated' column")

        # Commit changes
        conn.commit()

        if migrations_run > 0:
            print(f"\nMigration complete! {migrations_run} column(s) added.")
        else:
            print("\nNo migrations needed - database schema is up to date.")

        # Show final schema
        print("\nFinal 'invoices' table columns:")
        final_columns = get_existing_columns(cursor, "invoices")
        for col in final_columns:
            print(f"  - {col}")

    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
