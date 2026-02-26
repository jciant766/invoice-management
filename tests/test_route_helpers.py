"""
Pytest tests for routes/helpers.py

Focuses on the pure-logic helpers build_pagination() and parse_date().
No database or HTTP fixtures required.
"""
import pytest
from datetime import date

from routes.helpers import build_pagination, parse_date


# ---------- build_pagination() ----------

@pytest.mark.unit
def test_build_pagination_first_page():
    """Page 1 of a multi-page result set."""
    result = build_pagination(page=1, per_page=10, total_count=35)

    assert result["page"] == 1
    assert result["per_page"] == 10
    assert result["total_count"] == 35
    assert result["total_pages"] == 4          # ceil(35/10) = 4
    assert result["offset"] == 0
    assert result["start_item"] == 1
    assert result["end_item"] == 10
    assert result["has_prev"] is False
    assert result["has_next"] is True


@pytest.mark.unit
def test_build_pagination_last_page():
    """Last page should show remaining items and no 'next' link."""
    result = build_pagination(page=4, per_page=10, total_count=35)

    assert result["page"] == 4
    assert result["total_pages"] == 4
    assert result["offset"] == 30
    assert result["start_item"] == 31
    assert result["end_item"] == 35
    assert result["has_prev"] is True
    assert result["has_next"] is False


@pytest.mark.unit
def test_build_pagination_empty_results():
    """With total_count=0 everything should be zeroed out."""
    result = build_pagination(page=1, per_page=10, total_count=0)

    assert result["page"] == 1
    assert result["total_pages"] == 0
    assert result["offset"] == 0
    assert result["start_item"] == 0
    assert result["end_item"] == 0
    assert result["has_prev"] is False
    assert result["has_next"] is False


@pytest.mark.unit
def test_build_pagination_single_page():
    """When all items fit on one page, no prev/next links."""
    result = build_pagination(page=1, per_page=25, total_count=12)

    assert result["page"] == 1
    assert result["total_pages"] == 1
    assert result["offset"] == 0
    assert result["start_item"] == 1
    assert result["end_item"] == 12
    assert result["has_prev"] is False
    assert result["has_next"] is False


# ---------- parse_date() ----------

@pytest.mark.unit
def test_parse_date_valid_string():
    """A well-formed YYYY-MM-DD string should return (date, None)."""
    parsed, error = parse_date("2024-06-15", allow_future=True)

    assert error is None
    assert parsed == date(2024, 6, 15)


@pytest.mark.unit
def test_parse_date_invalid_format_returns_none():
    """A malformed date string should return (None, error_message)."""
    parsed, error = parse_date("15/06/2024")

    assert parsed is None
    assert error is not None
    assert "Invalid" in error


@pytest.mark.unit
def test_parse_date_empty_string_returns_none():
    """An empty string should return (None, error_message)."""
    parsed, error = parse_date("")

    assert parsed is None
    assert error is not None
    assert "required" in error.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
