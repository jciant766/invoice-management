"""
Database Migration Script

Adds new columns to the invoices table:
- fiscal_receipt_path
- source_email_id
- is_ai_generated
"""

import sqlite3
import os

# Find database file
db_paths = [
    "invoice_management.db",
    "../invoice_management.db",
]

db_path = None
for path in db_paths:
    if os.path.exists(path):
        db_path = path
        break

if not db_path:
    print("Database not found!")
    exit(1)

print(f"Migrating database: {db_path}")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check which columns exist
cursor.execute("PRAGMA table_info(invoices)")
existing_columns = [col[1] for col in cursor.fetchall()]
print(f"Existing columns: {existing_columns}")

# Add new columns if they don't exist
migrations = [
    ("fiscal_receipt_path", "VARCHAR(500)"),
    ("source_email_id", "VARCHAR(255)"),
    ("is_ai_generated", "BOOLEAN DEFAULT 0"),
]

for col_name, col_type in migrations:
    if col_name not in existing_columns:
        try:
            sql = f"ALTER TABLE invoices ADD COLUMN {col_name} {col_type}"
            cursor.execute(sql)
            print(f"Added column: {col_name}")
        except sqlite3.OperationalError as e:
            print(f"Error adding {col_name}: {e}")
    else:
        print(f"Column {col_name} already exists")

conn.commit()
conn.close()

print("Migration complete!")
