"""
Database migration: Add new columns to suppliers table.

Run this script once to update existing database with new supplier fields.
"""

import sqlite3
import os

DB_PATH = "invoice_management.db"


def migrate():
    """Add new columns to suppliers table."""
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(suppliers)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    # New columns to add
    new_columns = [
        ("contact_email", "VARCHAR(255)"),
        ("contact_phone", "VARCHAR(50)"),
        ("address", "TEXT"),
        ("vat_number", "VARCHAR(50)"),
        ("bank_name", "VARCHAR(255)"),
        ("bank_iban", "VARCHAR(50)"),
        ("category", "VARCHAR(50)"),
        ("notes", "TEXT"),
        ("is_active", "BOOLEAN DEFAULT 1"),
        ("updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
    ]

    added = []
    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE suppliers ADD COLUMN {col_name} {col_type}")
                added.append(col_name)
                print(f"  Added column: {col_name}")
            except sqlite3.OperationalError as e:
                print(f"  Error adding {col_name}: {e}")

    conn.commit()
    conn.close()

    if added:
        print(f"\nMigration complete! Added {len(added)} columns.")
    else:
        print("\nNo migration needed - all columns already exist.")

    return True


if __name__ == "__main__":
    print("Running supplier table migration...\n")
    migrate()
