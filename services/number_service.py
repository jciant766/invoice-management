"""
Number Sequence Service

Handles auto-generation of TF and CHQ numbers.
Format: N/YYYY (e.g., 1/2026, 2/2026)
Each type has its own independent sequence that resets yearly.
Note: PJV is manual input (no structure/auto-generation).
"""

from datetime import datetime


def _ensure_number_sequences_table(conn):
    """Ensure the number_sequences table exists."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS number_sequences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number_type TEXT NOT NULL,
            year INTEGER NOT NULL,
            last_number INTEGER NOT NULL DEFAULT 0,
            UNIQUE(number_type, year)
        )
    """)
    conn.commit()


def get_next_number(conn, number_type: str, year: int = None) -> str:
    """
    Get the next number in sequence for the given type and year.
    Uses atomic UPDATE to prevent race conditions.

    Args:
        conn: Database connection
        number_type: 'TF' or 'CHQ'
        year: Year for the sequence (defaults to current year)

    Returns:
        Formatted number string (e.g., '1/2026')
    """
    if year is None:
        year = datetime.now().year

    # Normalize type
    number_type = number_type.upper()
    if number_type not in ('TF', 'CHQ'):
        raise ValueError(f"Invalid number type: {number_type}. Must be 'TF' or 'CHQ'")

    # Ensure table exists
    _ensure_number_sequences_table(conn)

    cursor = conn.cursor()

    # Use BEGIN IMMEDIATE to get exclusive database lock immediately
    # This prevents race conditions when multiple requests come in at once
    cursor.execute("BEGIN IMMEDIATE")

    try:
        # Try atomic increment first
        cursor.execute(
            """UPDATE number_sequences
               SET last_number = last_number + 1
               WHERE number_type = ? AND year = ?""",
            (number_type, year)
        )

        if cursor.rowcount == 0:
            # No existing row - insert new sequence starting at 1
            cursor.execute(
                "INSERT INTO number_sequences (number_type, year, last_number) VALUES (?, ?, 1)",
                (number_type, year)
            )
            next_number = 1
        else:
            # Get the new value after increment
            cursor.execute(
                "SELECT last_number FROM number_sequences WHERE number_type = ? AND year = ?",
                (number_type, year)
            )
            next_number = cursor.fetchone()[0]

        cursor.execute("COMMIT")

    except Exception as e:
        cursor.execute("ROLLBACK")
        raise e

    # Format: N/YYYY
    return f"{next_number}/{year}"


def preview_next_number(conn, number_type: str, year: int = None) -> str:
    """
    Preview what the next number would be WITHOUT reserving it.
    Useful for showing the user what number will be assigned.

    Args:
        conn: Database connection
        number_type: 'TF' or 'CHQ'
        year: Year for the sequence (defaults to current year)

    Returns:
        Formatted number string that would be next
    """
    if year is None:
        year = datetime.now().year

    number_type = number_type.upper()
    if number_type not in ('TF', 'CHQ'):
        raise ValueError(f"Invalid number type: {number_type}. Must be 'TF' or 'CHQ'")

    # Ensure table exists
    _ensure_number_sequences_table(conn)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT last_number FROM number_sequences WHERE number_type = ? AND year = ?",
        (number_type, year)
    )
    row = cursor.fetchone()

    if row:
        next_num = row[0] + 1
    else:
        next_num = 1

    return f"{next_num}/{year}"


def get_current_counts(conn, year: int = None) -> dict:
    """
    Get current sequence counts for display.

    Args:
        conn: Database connection
        year: Year to check (defaults to current year)

    Returns:
        Dictionary with TF and CHQ counts
    """
    if year is None:
        year = datetime.now().year

    result = {'year': year, 'TF': 0, 'CHQ': 0}

    # Ensure table exists
    _ensure_number_sequences_table(conn)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT number_type, last_number FROM number_sequences WHERE year = ?",
        (year,)
    )

    for row in cursor.fetchall():
        result[row[0]] = row[1]

    return result


def update_counter(conn, number_type: str, new_value: int, year: int = None) -> bool:
    """
    Manually update the counter for a given type and year (admin function).

    Args:
        conn: Database connection
        number_type: 'TF' or 'CHQ'
        new_value: New counter value to set
        year: Year for the sequence (defaults to current year)

    Returns:
        True if successful
    """
    if new_value < 0:
        raise ValueError(f"{number_type} number cannot be negative")

    if year is None:
        year = datetime.now().year

    number_type = number_type.upper()
    if number_type not in ('TF', 'CHQ'):
        raise ValueError(f"Invalid number type: {number_type}")

    # Ensure table exists
    _ensure_number_sequences_table(conn)

    cursor = conn.cursor()

    # Check if record exists
    cursor.execute(
        "SELECT id FROM number_sequences WHERE number_type = ? AND year = ?",
        (number_type, year)
    )
    row = cursor.fetchone()

    if row:
        # Update existing
        cursor.execute(
            "UPDATE number_sequences SET last_number = ? WHERE id = ?",
            (new_value, row[0])
        )
    else:
        # Create new
        cursor.execute(
            "INSERT INTO number_sequences (number_type, year, last_number) VALUES (?, ?, ?)",
            (number_type, year, new_value)
        )

    conn.commit()
    return True
