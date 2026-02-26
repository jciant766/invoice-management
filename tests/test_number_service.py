"""
Pytest tests for number sequence service (services/number_service.py).

Tests the TF and CHQ auto-numbering system that generates numbers
in the format N/YYYY (e.g., 1/2026, 2/2026).

Each test uses an isolated temporary SQLite database to prevent
interference with production data or other tests.
"""
import sqlite3
import tempfile
import os
from datetime import datetime

import pytest

from services.number_service import (
    get_next_number,
    preview_next_number,
    update_counter,
    get_current_counts,
)

CURRENT_YEAR = datetime.now().year


@pytest.fixture
def db_conn():
    """
    Create an isolated temporary SQLite database for each test.

    Uses a temp file so that BEGIN IMMEDIATE locking works correctly
    (in-memory databases have different locking semantics).
    The connection's isolation_level is set to None (autocommit) so
    the service can manage its own transactions with BEGIN IMMEDIATE.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 5000")

    yield conn

    conn.close()
    os.unlink(db_path)


# ---------------------------------------------------------------------------
# 1. get_next_number("TF") returns "1/YYYY" format for first number
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_get_next_number_tf_first_returns_one_slash_year(db_conn):
    """First TF number generated should be 1/YYYY."""
    result = get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    assert result == f"1/{CURRENT_YEAR}"


# ---------------------------------------------------------------------------
# 2. get_next_number("TF") increments sequentially (1/2026, 2/2026, 3/2026)
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_get_next_number_tf_increments_sequentially(db_conn):
    """Successive calls should produce 1/YYYY, 2/YYYY, 3/YYYY."""
    first = get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    second = get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    third = get_next_number(db_conn, "TF", year=CURRENT_YEAR)

    assert first == f"1/{CURRENT_YEAR}"
    assert second == f"2/{CURRENT_YEAR}"
    assert third == f"3/{CURRENT_YEAR}"


# ---------------------------------------------------------------------------
# 3. get_next_number("CHQ") works independently from TF
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_get_next_number_chq_independent_from_tf(db_conn):
    """CHQ and TF sequences must be independent of each other."""
    # Advance TF to 3
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)

    # CHQ should still start at 1
    chq_first = get_next_number(db_conn, "CHQ", year=CURRENT_YEAR)
    assert chq_first == f"1/{CURRENT_YEAR}"

    # And TF should continue at 4
    tf_fourth = get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    assert tf_fourth == f"4/{CURRENT_YEAR}"

    # CHQ should be at 2
    chq_second = get_next_number(db_conn, "CHQ", year=CURRENT_YEAR)
    assert chq_second == f"2/{CURRENT_YEAR}"


# ---------------------------------------------------------------------------
# 4. get_next_number() with invalid type raises ValueError
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_get_next_number_invalid_type_raises_value_error(db_conn):
    """An unrecognised number_type must raise ValueError."""
    with pytest.raises(ValueError, match="Invalid number type"):
        get_next_number(db_conn, "INVALID", year=CURRENT_YEAR)


@pytest.mark.unit
def test_get_next_number_pjv_raises_value_error(db_conn):
    """PJV is manual-only and must not be accepted as a sequence type."""
    with pytest.raises(ValueError, match="Invalid number type"):
        get_next_number(db_conn, "PJV", year=CURRENT_YEAR)


# ---------------------------------------------------------------------------
# 5. preview_next_number() returns next number without consuming it
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_preview_next_number_does_not_consume(db_conn):
    """preview_next_number should report the next value but not advance the counter."""
    preview = preview_next_number(db_conn, "TF", year=CURRENT_YEAR)
    assert preview == f"1/{CURRENT_YEAR}"

    # Actually consume the number -- it should still be 1 because preview did not consume
    actual = get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    assert actual == f"1/{CURRENT_YEAR}"


# ---------------------------------------------------------------------------
# 6. preview_next_number() called twice returns same value (non-consuming)
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_preview_next_number_called_twice_returns_same_value(db_conn):
    """Two consecutive previews without any consumption must return the same value."""
    first_preview = preview_next_number(db_conn, "TF", year=CURRENT_YEAR)
    second_preview = preview_next_number(db_conn, "TF", year=CURRENT_YEAR)

    assert first_preview == second_preview
    assert first_preview == f"1/{CURRENT_YEAR}"


@pytest.mark.unit
def test_preview_reflects_consumed_numbers(db_conn):
    """After consuming numbers, preview should reflect the updated counter."""
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)  # consumes 1
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)  # consumes 2

    preview = preview_next_number(db_conn, "TF", year=CURRENT_YEAR)
    assert preview == f"3/{CURRENT_YEAR}"


# ---------------------------------------------------------------------------
# 7. update_counter() sets the counter to a specific value
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_update_counter_sets_specific_value(db_conn):
    """update_counter should set the counter so the next number follows from it."""
    update_counter(db_conn, "TF", 50, year=CURRENT_YEAR)

    next_num = get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    assert next_num == f"51/{CURRENT_YEAR}"


@pytest.mark.unit
def test_update_counter_overwrites_existing(db_conn):
    """update_counter should overwrite whatever value was there before."""
    # Advance to 3
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)

    # Reset to 10
    update_counter(db_conn, "TF", 10, year=CURRENT_YEAR)

    next_num = get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    assert next_num == f"11/{CURRENT_YEAR}"


@pytest.mark.unit
def test_update_counter_returns_true(db_conn):
    """update_counter should return True on success."""
    result = update_counter(db_conn, "TF", 5, year=CURRENT_YEAR)
    assert result is True


# ---------------------------------------------------------------------------
# 8. update_counter() with negative value raises ValueError
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_update_counter_negative_raises_value_error(db_conn):
    """Setting the counter to a negative number must raise ValueError."""
    with pytest.raises(ValueError, match="cannot be negative"):
        update_counter(db_conn, "TF", -1, year=CURRENT_YEAR)


@pytest.mark.unit
def test_update_counter_negative_chq_raises_value_error(db_conn):
    """Negative value for CHQ must also raise ValueError."""
    with pytest.raises(ValueError, match="cannot be negative"):
        update_counter(db_conn, "CHQ", -5, year=CURRENT_YEAR)


# ---------------------------------------------------------------------------
# 9. get_current_counts() returns correct counts for both types
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_get_current_counts_initial_zeros(db_conn):
    """Before any numbers are generated, both counts should be zero."""
    counts = get_current_counts(db_conn, year=CURRENT_YEAR)

    assert counts["year"] == CURRENT_YEAR
    assert counts["TF"] == 0
    assert counts["CHQ"] == 0


@pytest.mark.unit
def test_get_current_counts_after_generation(db_conn):
    """Counts should reflect the number of generated TF and CHQ values."""
    # Generate 3 TF numbers
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)
    get_next_number(db_conn, "TF", year=CURRENT_YEAR)

    # Generate 2 CHQ numbers
    get_next_number(db_conn, "CHQ", year=CURRENT_YEAR)
    get_next_number(db_conn, "CHQ", year=CURRENT_YEAR)

    counts = get_current_counts(db_conn, year=CURRENT_YEAR)

    assert counts["year"] == CURRENT_YEAR
    assert counts["TF"] == 3
    assert counts["CHQ"] == 2


@pytest.mark.unit
def test_get_current_counts_after_update_counter(db_conn):
    """Counts should reflect manual counter updates too."""
    update_counter(db_conn, "TF", 42, year=CURRENT_YEAR)
    update_counter(db_conn, "CHQ", 7, year=CURRENT_YEAR)

    counts = get_current_counts(db_conn, year=CURRENT_YEAR)

    assert counts["TF"] == 42
    assert counts["CHQ"] == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
