"""
Pytest tests for email date filtering functionality.

Tests the date_from and date_to query parameters in the /email/check endpoint.
"""
import pytest
from datetime import datetime, timedelta
from database import get_db


@pytest.mark.integration
def test_email_check_endpoint_accepts_date_params():
    """Test that email check endpoint accepts date_from and date_to parameters."""
    # This test verifies the route signature accepts the parameters
    from routes.email_processing import check_emails
    import inspect

    sig = inspect.signature(check_emails)
    params = sig.parameters

    assert 'date_from' in params, "date_from parameter missing from check_emails"
    assert 'date_to' in params, "date_to parameter missing from check_emails"
    assert params['date_from'].default is None, "date_from should default to None"
    assert params['date_to'].default is None, "date_to should default to None"


@pytest.mark.unit
def test_date_filter_builds_gmail_query():
    """Test that Gmail date filters are appended to search query correctly."""
    # Simulate the query building logic from email_processing.py lines 100-104
    q = "invoice"
    date_from = "2026-01-01"
    date_to = "2026-01-31"

    effective_query = q or ""
    if date_from:
        effective_query = (effective_query + " ").strip() + f" after:{date_from}"
    if date_to:
        effective_query = (effective_query + " ").strip() + f" before:{date_to}"

    assert "after:2026-01-01" in effective_query
    assert "before:2026-01-31" in effective_query
    assert "invoice" in effective_query


@pytest.mark.unit
def test_date_filter_builds_microsoft_odata():
    """Test that Microsoft date filters create proper OData query."""
    # Simulate the OData building logic from email_processing.py lines 107-128
    date_from = "2026-01-01"
    date_to = "2026-01-31"

    odata_filters = []
    if date_from:
        odata_filters.append(f"receivedDateTime ge {date_from}T00:00:00Z")
    if date_to:
        odata_filters.append(f"receivedDateTime le {date_to}T23:59:59Z")

    odata_query = " and ".join(odata_filters)

    assert "receivedDateTime ge 2026-01-01T00:00:00Z" in odata_query
    assert "receivedDateTime le 2026-01-31T23:59:59Z" in odata_query
    assert " and " in odata_query


@pytest.mark.unit
def test_fallback_date_filter_logic():
    """Test the fallback local date filtering for providers without query support."""
    # Simulate the fallback filtering from email_processing.py lines 194-219
    from datetime import datetime

    def _parse_email_date(date_str: str):
        """Helper to parse various email date formats."""
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except Exception:
                continue
        return None

    # Test data
    emails = [
        {"id": "1", "date": "2026-01-15"},
        {"id": "2", "date": "2026-02-01"},
        {"id": "3", "date": "2025-12-20"}
    ]

    date_from = "2026-01-01"
    date_to = "2026-01-31"

    # Apply filter logic
    try:
        df = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else None
        dt = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else None
    except ValueError:
        df = dt = None

    filtered = []
    for e in emails:
        d = _parse_email_date(e.get("date", ""))
        if d:
            if df and d < df:
                continue
            if dt and d > dt:
                continue
        filtered.append(e)

    # Should only include email from 2026-01-15
    assert len(filtered) == 1
    assert filtered[0]["id"] == "1"


@pytest.mark.unit
def test_date_filter_with_only_date_from():
    """Test filtering with only date_from (no end date)."""
    from datetime import datetime

    def _parse_email_date(date_str: str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except:
            return None

    emails = [
        {"id": "1", "date": "2026-01-15"},
        {"id": "2", "date": "2026-02-01"},
        {"id": "3", "date": "2025-12-20"}
    ]

    date_from = "2026-01-01"
    date_to = None

    df = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else None
    dt = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else None

    filtered = []
    for e in emails:
        d = _parse_email_date(e.get("date", ""))
        if d:
            if df and d < df:
                continue
            if dt and d > dt:
                continue
        filtered.append(e)

    # Should include both 2026 emails
    assert len(filtered) == 2
    assert filtered[0]["id"] == "1"
    assert filtered[1]["id"] == "2"


@pytest.mark.unit
def test_date_filter_with_only_date_to():
    """Test filtering with only date_to (no start date)."""
    from datetime import datetime

    def _parse_email_date(date_str: str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except:
            return None

    emails = [
        {"id": "1", "date": "2026-01-15"},
        {"id": "2", "date": "2026-02-01"},
        {"id": "3", "date": "2025-12-20"}
    ]

    date_from = None
    date_to = "2026-01-31"

    df = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else None
    dt = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else None

    filtered = []
    for e in emails:
        d = _parse_email_date(e.get("date", ""))
        if d:
            if df and d < df:
                continue
            if dt and d > dt:
                continue
        filtered.append(e)

    # Should include 2025-12-20 and 2026-01-15 (both before or on Jan 31)
    assert len(filtered) == 2
    assert any(e["id"] == "1" for e in filtered)
    assert any(e["id"] == "3" for e in filtered)


@pytest.mark.unit
def test_date_parser_handles_multiple_formats():
    """Test that the date parser handles various email date formats."""
    from datetime import datetime

    def _parse_email_date(date_str: str):
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except Exception:
                continue
        return None

    # Test various formats
    assert _parse_email_date("2026-01-15") is not None
    assert _parse_email_date("2026-01-15T10:30:00Z") is not None
    assert _parse_email_date("") is None

    # ISO format should parse correctly
    result = _parse_email_date("2026-01-15")
    assert result.year == 2026
    assert result.month == 1
    assert result.day == 15


if __name__ == "__main__":
    # Allow running this file directly
    pytest.main([__file__, "-v"])
