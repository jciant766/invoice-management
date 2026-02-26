"""
Shared Route Helpers

Common utility functions used across multiple route modules.
"""

from datetime import datetime, date
from typing import Optional, Dict, Any, List
from fastapi import Request, HTTPException
from middleware import get_current_user


def check_admin(request: Request):
    """Check if current user is admin, raise exception if not."""
    user = get_current_user(request)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def get_client_ip(request: Request) -> str:
    """Get client IP from the actual network connection (not spoofable headers)."""
    return request.client.host if request.client else "unknown"


def build_pagination(page: int, per_page: int, total_count: int) -> Dict[str, Any]:
    """Build pagination dict for templates. Consolidates repeated pagination logic."""
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 0
    if page > total_pages and total_pages > 0:
        page = total_pages
    offset = (page - 1) * per_page
    start_item = offset + 1 if total_count > 0 else 0
    end_item = min(offset + per_page, total_count)
    return {
        "page": page,
        "per_page": per_page,
        "total_count": total_count,
        "total_pages": total_pages,
        "start_item": start_item,
        "end_item": end_item,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "offset": offset
    }


def parse_date(date_str: str, allow_future: bool = False, min_year: int = 2000) -> tuple:
    """
    Parse and validate a date string.
    Returns (parsed_date, error_message). If error_message is None, parsing succeeded.
    """
    if not date_str:
        return None, "Date is required"
    try:
        parsed = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        if not allow_future and parsed > date.today():
            return None, "Date cannot be in the future"
        if parsed.year < min_year:
            return None, f"Date must be year {min_year} or later"
        return parsed, None
    except ValueError:
        return None, "Invalid date format"


class InvoiceWrapper:
    """Wrapper to provide ORM-like interface for invoice dict from SQLite row."""
    def __init__(self, data: dict):
        for key, value in data.items():
            setattr(self, key, value)
        self.supplier = type('Supplier', (), {
            'name': data.get('supplier_name') or 'Unknown Supplier',
            'contact_email': data.get('supplier_email')
        })()


def wrap_invoices(rows: List[Any]) -> List[InvoiceWrapper]:
    """Convert list of SQLite rows to InvoiceWrapper objects."""
    return [InvoiceWrapper(dict(row)) for row in rows]
