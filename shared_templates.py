"""
Shared Jinja2 Templates configuration with custom filters.

All route files should import templates from here instead of creating their own.
"""

import os
from datetime import datetime
from fastapi.templating import Jinja2Templates

# Get the templates directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates_path = os.path.join(BASE_DIR, "templates")

# Create the Jinja2Templates instance
templates = Jinja2Templates(directory=templates_path)


# Custom filter for formatting dates (handles both string and datetime)
def format_date(value, fmt='%d/%m/%Y'):
    """Format a date value that may be a string or datetime object."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            if 'T' in value:
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(value, '%Y-%m-%d')
            return dt.strftime(fmt)
        except (ValueError, TypeError):
            return value
    elif hasattr(value, 'strftime'):
        return value.strftime(fmt)
    return str(value)


# Register the filter
templates.env.filters['format_date'] = format_date
