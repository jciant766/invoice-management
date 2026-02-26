"""
Data Models and Constants
=========================
Simple constants and helpers - no ORM needed.
"""

# Method code descriptions for display
METHOD_REQUEST_CODES = {
    'Inv': 'Invoice',
    'Rec': 'Receipt',
    'RFP': 'Request for Payment',
    'PP': 'Part Payment',
    'DP': 'Deposit',
    'EC': 'Expense Claim'
}

METHOD_PROCUREMENT_CODES = {
    'DA': 'Direct Order Approvata (Approved Direct Order)',
    'D': 'Direct Order',
    'T': 'Tender',
    'K': 'Kwotazzjoni (Quotation)',
    'R': 'Refund'
}


# Audit action constants
class AuditAction:
    # Authentication
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"

    # Invoice actions
    INVOICE_CREATE = "invoice_create"
    INVOICE_UPDATE = "invoice_update"
    INVOICE_DELETE = "invoice_delete"
    INVOICE_STATUS = "invoice_status"
    INVOICE_RESTORE = "invoice_restore"

    # Export actions
    EXPORT = "export"
    EXPORT_PDF = "export_pdf"
    EXPORT_EXCEL = "export_excel"
    EXPORT_CSV = "export_csv"

    # User management
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    USER_DELETE = "user_delete"
    PASSWORD_CHANGE = "password_change"

    # Supplier actions
    SUPPLIER_CREATE = "supplier_create"
    SUPPLIER_UPDATE = "supplier_update"
    SUPPLIER_DELETE = "supplier_delete"

    # Settings
    SETTINGS_CHANGE = "settings_change"

    # Email
    EMAIL_CONNECT = "email_connect"
    EMAIL_DISCONNECT = "email_disconnect"
    EMAIL_FOLDER_SELECT = "email_folder_select"


def row_to_dict(row):
    """Convert a sqlite3.Row to a dictionary."""
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows):
    """Convert a list of sqlite3.Row to list of dictionaries."""
    return [dict(row) for row in rows]
