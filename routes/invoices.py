"""
Invoice CRUD Routes - Simple SQLite Version
"""

import logging
import uuid
import ntpath
import posixpath
import aiofiles
from pathlib import Path
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Request, Query, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from database import get_db
from models import METHOD_REQUEST_CODES, METHOD_PROCUREMENT_CODES
from services.number_service import get_next_number, preview_next_number
from services.export_profile_service import get_export_signatories
from services.audit_service import (
    log_invoice_created, log_invoice_updated, log_invoice_status_change
)
from middleware import get_current_user_id
from routes.helpers import get_client_ip, build_pagination
from shared_templates import templates

router = APIRouter(prefix="/invoices", tags=["invoices"])
logger = logging.getLogger(__name__)

# Upload configuration
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_FOLDER = BASE_DIR / "uploads" / "fiscal_receipts"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_NUMBER_TYPES = {"TF", "CHQ"}

FILE_SIGNATURES = {
    '.pdf': [b'%PDF'],
    '.jpg': [b'\xff\xd8\xff'],
    '.jpeg': [b'\xff\xd8\xff'],
    '.png': [b'\x89PNG\r\n\x1a\n'],
}


def validate_file_magic_bytes(content: bytes, extension: str) -> bool:
    if extension not in FILE_SIGNATURES:
        return False
    for signature in FILE_SIGNATURES[extension]:
        if content.startswith(signature):
            return True
    return False


def sanitize_filename(filename: str) -> str:
    if not filename:
        return "unknown"
    filename = ntpath.basename(filename)
    filename = posixpath.basename(filename)
    filename = filename.replace('/', '').replace('\\', '').replace('..', '')
    return filename or "unknown"

ALLOWED_SORT_COLUMNS = {
    'created_at', 'invoice_date', 'invoice_amount', 'payment_amount',
    'supplier_id', 'pjv_number', 'invoice_number', 'tf_number', 'is_approved'
}


def delete_fiscal_receipt_file(filename: Optional[str]) -> None:
    """Delete a stored receipt file if it exists. Best-effort cleanup."""
    if not filename:
        return
    file_path = UPLOAD_FOLDER / filename
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception as exc:
        logger.warning("Failed to delete receipt file '%s': %s", filename, exc)


async def save_fiscal_receipt_file(file: UploadFile, invoice_id: int) -> str:
    """Validate and save a fiscal receipt file; returns stored filename."""
    if not file or not file.filename:
        return ""

    safe_filename = sanitize_filename(file.filename)
    file_ext = Path(safe_filename).suffix.lower()

    if file_ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    # Read file in chunks to avoid memory issues
    chunks = []
    total_size = 0
    chunk_size = 64 * 1024

    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_FILE_SIZE:
            raise ValueError(f"File too large. Maximum: {MAX_FILE_SIZE // (1024*1024)}MB")
        chunks.append(chunk)

    content = b"".join(chunks)

    if not validate_file_magic_bytes(content, file_ext):
        raise ValueError("File content does not match extension")

    unique_filename = f"{invoice_id}_{uuid.uuid4().hex[:8]}{file_ext}"
    file_path = UPLOAD_FOLDER / unique_filename

    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)

    return unique_filename


@router.get("", response_class=HTMLResponse)
async def list_invoices(
    request: Request,
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    supplier_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    include_void: bool = Query(False),
    sort_by: Optional[str] = Query("created_at"),
    sort_order: Optional[str] = Query("desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=100)
):
    """List all invoices with optional filters and pagination."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Build query
        sql = """
            SELECT i.*, s.name as supplier_name, s.contact_email as supplier_email
            FROM invoices i
            LEFT JOIN suppliers s ON i.supplier_id = s.id
            WHERE i.is_deleted = 0
        """
        count_sql = "SELECT COUNT(*) FROM invoices i WHERE i.is_deleted = 0"
        params = []
        count_params = []

        # Search filter
        if q:
            search_clause = """
                AND (s.name LIKE ? OR i.invoice_number LIKE ? OR i.pjv_number LIKE ? OR i.tf_number LIKE ?)
            """
            sql += search_clause
            count_sql += " AND (EXISTS (SELECT 1 FROM suppliers s WHERE s.id = i.supplier_id AND s.name LIKE ?) OR i.invoice_number LIKE ? OR i.pjv_number LIKE ? OR i.tf_number LIKE ?)"
            search_term = f"%{q}%"
            params.extend([search_term, search_term, search_term, search_term])
            count_params.extend([search_term, search_term, search_term, search_term])

        # Status filter
        if status == "pending":
            sql += " AND i.is_approved = 0"
            count_sql += " AND i.is_approved = 0"
        elif status == "approved":
            sql += " AND i.is_approved = 1"
            count_sql += " AND i.is_approved = 1"
        elif status == "voided":
            sql += " AND i.is_void = 1"
            count_sql += " AND i.is_void = 1"

        # Exclude voided unless explicitly included or explicitly filtered.
        if not include_void and status != "voided":
            sql += " AND i.is_void = 0"
            count_sql += " AND i.is_void = 0"

        # Supplier filter
        supplier_id_int = None
        if supplier_id:
            try:
                supplier_id_str = str(supplier_id).strip()
                if supplier_id_str:
                    supplier_id_int = int(supplier_id_str)
                    sql += " AND i.supplier_id = ?"
                    count_sql += " AND i.supplier_id = ?"
                    params.append(supplier_id_int)
                    count_params.append(supplier_id_int)
            except (ValueError, TypeError):
                pass

        # Date filters
        if date_from:
            try:
                date_from_str = str(date_from).strip() if date_from else ""
                if date_from_str:
                    datetime.strptime(date_from_str, "%Y-%m-%d")
                    sql += " AND i.invoice_date >= ?"
                    count_sql += " AND i.invoice_date >= ?"
                    params.append(date_from_str)
                    count_params.append(date_from_str)
            except (ValueError, TypeError):
                pass

        if date_to:
            try:
                date_to_str = str(date_to).strip() if date_to else ""
                if date_to_str:
                    datetime.strptime(date_to_str, "%Y-%m-%d")
                    sql += " AND i.invoice_date <= ?"
                    count_sql += " AND i.invoice_date <= ?"
                    params.append(date_to_str)
                    count_params.append(date_to_str)
            except (ValueError, TypeError):
                pass

        # Sorting
        if sort_by not in ALLOWED_SORT_COLUMNS:
            sort_by = 'created_at'
        if sort_order not in ('asc', 'desc'):
            sort_order = 'desc'
        sql += f" ORDER BY i.{sort_by} {sort_order.upper()}"

        cursor.execute(count_sql, count_params)
        total_count = cursor.fetchone()[0]
        pagination = build_pagination(page, per_page, total_count)

        sql += " LIMIT ? OFFSET ?"
        params.extend([per_page, pagination['offset']])

        cursor.execute(sql, params)
        invoices = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM suppliers ORDER BY name")
        suppliers = [dict(row) for row in cursor.fetchall()]
        export_signatories = get_export_signatories(conn)

        total_invoice_amount = sum(float(inv['invoice_amount'] or 0) for inv in invoices)
        total_payment_amount = sum(float(inv['payment_amount'] or 0) for inv in invoices)

        return templates.TemplateResponse(
            "invoice_list.html",
            {
                "request": request,
                "invoices": invoices,
                "suppliers": suppliers,
                "filters": {
                    "q": q,
                    "status": status or "all",
                    "supplier_id": supplier_id_int,
                    "date_from": date_from,
                    "date_to": date_to,
                    "include_void": include_void,
                    "sort_by": sort_by,
                    "sort_order": sort_order
                },
                "totals": {
                    "invoice_amount": total_invoice_amount,
                    "payment_amount": total_payment_amount,
                    "count": total_count
                },
                "pagination": pagination,
                "export_signatories": export_signatories
            }
        )
@router.get("/create", response_class=HTMLResponse)
async def create_invoice_form(request: Request):
    """Display invoice creation form."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM suppliers ORDER BY name")
        suppliers = [dict(row) for row in cursor.fetchall()]

        next_tf = preview_next_number(conn, 'TF')  # Year-based: TF 1/2026
        next_chq = preview_next_number(conn, 'CHQ')  # Year-based: CHQ 1/2026

        return templates.TemplateResponse(
            "invoice_form.html",
            {
                "request": request,
                "suppliers": suppliers,
                "invoice": None,
                "next_tf_number": next_tf,
                "next_chq_number": next_chq,
                "method_request_codes": METHOD_REQUEST_CODES,
                "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                "is_edit": False,
                "errors": {},
                "today": date.today().isoformat()
            }
        )


@router.post("/create")
async def create_invoice(
    request: Request,
    supplier_id: Optional[str] = Form(None),
    new_supplier_name: Optional[str] = Form(None),
    new_supplier_email: Optional[str] = Form(None),
    new_supplier_phone: Optional[str] = Form(None),
    invoice_amount: float = Form(...),
    payment_amount: float = Form(...),
    method_request: str = Form(...),
    method_procurement: str = Form(...),
    description: str = Form(...),
    invoice_date: str = Form(...),
    invoice_number: str = Form(...),
    po_number: Optional[str] = Form(None),
    pjv_number: str = Form(...),
    is_approved: bool = Form(False),
    number_type: Optional[str] = Form("TF"),
    proposer_councillor: Optional[str] = Form(None),
    seconder_councillor: Optional[str] = Form(None),
    fiscal_receipt: UploadFile = File(None)
):
    """Create a new invoice."""
    with get_db() as conn:
        cursor = conn.cursor()
        errors = {}
        description = (description or "").strip()
        invoice_number = (invoice_number or "").strip()
        pjv_number = (pjv_number or "").strip()
        po_number = po_number.strip() if po_number else None

        # Validate supplier
        supplier_id_int = None
        if not supplier_id or supplier_id == "":
            errors["supplier_id"] = "Please select a supplier"
        else:
            try:
                supplier_id_int = int(str(supplier_id).strip())
            except (ValueError, TypeError):
                errors["supplier_id"] = "Invalid supplier selected"

        # Handle new supplier
        if supplier_id_int == -1:
            if not new_supplier_name or not new_supplier_name.strip():
                errors["new_supplier_name"] = "Please enter a supplier name"
            else:
                # Use exact case-insensitive match (not LIKE which matches partial strings)
                cursor.execute("SELECT id FROM suppliers WHERE LOWER(name) = LOWER(?)", (new_supplier_name.strip(),))
                existing = cursor.fetchone()
                if existing:
                    supplier_id_int = existing[0]
                else:
                    cursor.execute(
                        """INSERT INTO suppliers (name, contact_email, contact_phone) VALUES (?, ?, ?)""",
                        (new_supplier_name.strip(), (new_supplier_email or "").strip() or None, (new_supplier_phone or "").strip() or None)
                    )
                    supplier_id_int = cursor.lastrowid
        elif supplier_id_int is not None:
            cursor.execute("SELECT id FROM suppliers WHERE id = ?", (supplier_id_int,))
            if not cursor.fetchone():
                errors["supplier_id"] = "Selected supplier does not exist"

        # Validations
        if invoice_amount <= 0:
            errors["invoice_amount"] = "Invoice amount must be greater than 0"
        if payment_amount > invoice_amount:
            errors["payment_amount"] = "Payment amount cannot exceed invoice amount"
        if payment_amount <= 0:
            errors["payment_amount"] = "Payment amount must be greater than 0"
        if not description:
            errors["description"] = "Description is required"
        if not invoice_number:
            errors["invoice_number"] = "Invoice number is required"
        if not pjv_number:
            errors["pjv_number"] = "PJV number is required"
        if method_request not in METHOD_REQUEST_CODES:
            errors["method_request"] = "Invalid request method selected"
        if method_procurement not in METHOD_PROCUREMENT_CODES:
            errors["method_procurement"] = "Invalid procurement method selected"
        if number_type and number_type.upper() not in ALLOWED_NUMBER_TYPES:
            errors["number_type"] = "Invalid approval type selected"
            number_type = "TF"
        else:
            number_type = (number_type or "TF").upper()

        # Check duplicate PJV
        cursor.execute("SELECT id FROM invoices WHERE pjv_number = ? AND is_deleted = 0", (pjv_number,))
        if cursor.fetchone():
            errors["pjv_number"] = "This PJV number is already in use"

        # Parse date
        try:
            parsed_date = datetime.strptime(invoice_date, "%Y-%m-%d").date()
            if parsed_date > date.today():
                errors["invoice_date"] = "Invoice date cannot be in the future"
            # Prevent unrealistic old dates (before year 2000)
            elif parsed_date.year < 2000:
                errors["invoice_date"] = "Invoice date must be year 2000 or later"
        except ValueError:
            errors["invoice_date"] = "Invalid date format"
            parsed_date = None

        if errors:
            cursor.execute("SELECT * FROM suppliers ORDER BY name")
            suppliers = [dict(row) for row in cursor.fetchall()]
            next_tf = preview_next_number(conn, 'TF')
            next_chq = preview_next_number(conn, 'CHQ')

            return templates.TemplateResponse(
                "invoice_form.html",
                {
                "request": request,
                "suppliers": suppliers,
                "invoice": None,
                "next_tf_number": next_tf,
                "next_chq_number": next_chq,
                "method_request_codes": METHOD_REQUEST_CODES,
                "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                "is_edit": False,
                "errors": errors,
                "form_data": {
                    "supplier_id": supplier_id_int,
                    "new_supplier_name": new_supplier_name,
                    "new_supplier_email": new_supplier_email,
                    "new_supplier_phone": new_supplier_phone,
                    "invoice_amount": invoice_amount,
                    "payment_amount": payment_amount,
                    "method_request": method_request,
                    "method_procurement": method_procurement,
                    "description": description,
                        "invoice_date": invoice_date,
                        "invoice_number": invoice_number,
                        "po_number": po_number,
                        "pjv_number": pjv_number,
                        "is_approved": is_approved,
                        "number_type": number_type
                    },
                    "today": date.today().isoformat()
                },
                status_code=400
            )

        # Generate TF/CHQ number if approved
        tf_number = None
        chq_number = None
        approved_date = None

        if is_approved:
            approved_date = date.today().isoformat()
            if number_type == "CHQ":
                chq_number = get_next_number(conn, 'CHQ')
            else:
                tf_number = get_next_number(conn, 'TF')

        # Insert invoice
        try:
            cursor.execute("""
                INSERT INTO invoices (
                    supplier_id, invoice_amount, payment_amount, method_request,
                    method_procurement, description, invoice_date, invoice_number,
                    po_number, pjv_number, number_type, tf_number, chq_number,
                    is_approved, approved_date, proposer_councillor, seconder_councillor,
                    is_deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                supplier_id_int, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                po_number, pjv_number,
                number_type or "TF", tf_number, chq_number,
                1 if is_approved else 0, approved_date,
                proposer_councillor, seconder_councillor
            ))
            invoice_id = cursor.lastrowid
        except Exception as e:
            # Log actual error for debugging
            print(f"[ERROR] Error saving invoice: {str(e)}")
            cursor.execute("SELECT * FROM suppliers ORDER BY name")
            suppliers = [dict(row) for row in cursor.fetchall()]
            next_tf = preview_next_number(conn, 'TF')
            next_chq = preview_next_number(conn, 'CHQ')

            return templates.TemplateResponse(
                "invoice_form.html",
                {
                    "request": request,
                    "suppliers": suppliers,
                    "invoice": None,
                    "next_tf_number": next_tf,
                    "next_chq_number": next_chq,
                    "method_request_codes": METHOD_REQUEST_CODES,
                    "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                    "is_edit": False,
                    "errors": {"database": "An error occurred while saving the invoice. Please try again."},
                    "form_data": {
                        "supplier_id": supplier_id_int,
                        "new_supplier_name": new_supplier_name,
                    "invoice_amount": invoice_amount,
                    "payment_amount": payment_amount,
                    "method_request": method_request,
                    "method_procurement": method_procurement,
                    "description": description,
                    "invoice_date": invoice_date,
                    "invoice_number": invoice_number,
                    "po_number": po_number,
                    "pjv_number": pjv_number,
                    "is_approved": is_approved,
                    "number_type": number_type
                },
                "today": date.today().isoformat()
            },
            status_code=500
            )

        # Optional fiscal receipt upload
        if fiscal_receipt and fiscal_receipt.filename:
            try:
                filename = await save_fiscal_receipt_file(fiscal_receipt, invoice_id)
                cursor.execute("UPDATE invoices SET fiscal_receipt_path = ? WHERE id = ?", (filename, invoice_id))
            except ValueError as e:
                # Clean up the created invoice to keep state consistent
                cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))

                cursor.execute("SELECT * FROM suppliers ORDER BY name")
                suppliers = [dict(row) for row in cursor.fetchall()]
                next_tf = preview_next_number(conn, 'TF')
                next_chq = preview_next_number(conn, 'CHQ')

                errors["fiscal_receipt"] = str(e)
                return templates.TemplateResponse(
                    "invoice_form.html",
                    {
                        "request": request,
                        "suppliers": suppliers,
                        "invoice": None,
                        "next_tf_number": next_tf,
                        "next_chq_number": next_chq,
                        "method_request_codes": METHOD_REQUEST_CODES,
                        "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                        "is_edit": False,
                        "errors": errors,
                        "form_data": {
                            "supplier_id": supplier_id_int,
                            "new_supplier_name": new_supplier_name,
                            "invoice_amount": invoice_amount,
                            "payment_amount": payment_amount,
                            "method_request": method_request,
                            "method_procurement": method_procurement,
                            "description": description,
                            "invoice_date": invoice_date,
                            "invoice_number": invoice_number,
                            "po_number": po_number,
                            "pjv_number": pjv_number,
                            "is_approved": is_approved,
                            "number_type": number_type
                        },
                        "today": date.today().isoformat()
                    },
                    status_code=400
                )

        # Log action
        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)
        log_invoice_created(conn, user_id, invoice_id, pjv_number, ip_address)

        # Redirect with success message
        return RedirectResponse(url="/invoices?success=Invoice+created+successfully", status_code=303)


@router.get("/{invoice_id}/edit", response_class=HTMLResponse)
async def edit_invoice_form(request: Request, invoice_id: int):
    """Display invoice edit form."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM invoices WHERE id = ? AND is_deleted = 0", (invoice_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Invoice not found")

        invoice = dict(row)

        cursor.execute("SELECT * FROM suppliers ORDER BY name")
        suppliers = [dict(row) for row in cursor.fetchall()]

        next_tf = preview_next_number(conn, 'TF')
        next_chq = preview_next_number(conn, 'CHQ')

        return templates.TemplateResponse(
            "invoice_form.html",
            {
                "request": request,
                "suppliers": suppliers,
                "invoice": invoice,
                "next_tf_number": next_tf,
                "next_chq_number": next_chq,
                "method_request_codes": METHOD_REQUEST_CODES,
                "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                "is_edit": True,
                "errors": {},
                "today": date.today().isoformat()
            }
        )


@router.get("/{invoice_id}/voucher", response_class=HTMLResponse)
async def invoice_voucher(request: Request, invoice_id: int):
    """Printable voucher view for a single invoice."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT i.*, s.name as supplier_name
            FROM invoices i
            LEFT JOIN suppliers s ON s.id = i.supplier_id
            WHERE i.id = ? AND i.is_deleted = 0
        """, (invoice_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Invoice not found")

        invoice = dict(row)

        return templates.TemplateResponse(
            "invoice_voucher.html",
            {
                "request": request,
                "invoice": invoice
            }
        )


@router.post("/{invoice_id}/edit")
async def update_invoice(
    request: Request,
    invoice_id: int,
    supplier_id: int = Form(...),
    new_supplier_name: Optional[str] = Form(None),
    new_supplier_email: Optional[str] = Form(None),
    new_supplier_phone: Optional[str] = Form(None),
    invoice_amount: float = Form(...),
    payment_amount: float = Form(...),
    method_request: str = Form(...),
    method_procurement: str = Form(...),
    description: str = Form(...),
    invoice_date: str = Form(...),
    invoice_number: str = Form(...),
    po_number: Optional[str] = Form(None),
    pjv_number: str = Form(...),
    is_approved: bool = Form(False),
    number_type: Optional[str] = Form("TF"),
    proposer_councillor: Optional[str] = Form(None),
    seconder_councillor: Optional[str] = Form(None),
    fiscal_receipt: UploadFile = File(None)
):
    """Update an existing invoice."""
    new_receipt_filename = None
    old_receipt_to_delete = None
    response = None

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM invoices WHERE id = ? AND is_deleted = 0", (invoice_id,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Invoice not found")

            invoice = dict(row)
            if invoice.get("is_void"):
                raise HTTPException(status_code=400, detail="Voided invoices cannot be edited")
            errors = {}
            description = (description or "").strip()
            invoice_number = (invoice_number or "").strip()
            pjv_number = (pjv_number or "").strip()
            po_number = po_number.strip() if po_number else None

            # Handle new supplier
            if supplier_id == -1:
                if not new_supplier_name or not new_supplier_name.strip():
                    errors["new_supplier_name"] = "Please enter a supplier name"
                else:
                    # Use exact case-insensitive match (not LIKE which matches partial strings)
                    cursor.execute("SELECT id FROM suppliers WHERE LOWER(name) = LOWER(?)", (new_supplier_name.strip(),))
                    existing = cursor.fetchone()
                    if existing:
                        supplier_id = existing[0]
                    else:
                        cursor.execute(
                            "INSERT INTO suppliers (name, contact_email, contact_phone) VALUES (?, ?, ?)",
                            (new_supplier_name.strip(), (new_supplier_email or '').strip() or None, (new_supplier_phone or '').strip() or None)
                        )
                        supplier_id = cursor.lastrowid
            else:
                cursor.execute("SELECT id FROM suppliers WHERE id = ?", (supplier_id,))
                if not cursor.fetchone():
                    errors["supplier_id"] = "Selected supplier does not exist"

            # Validations
            if invoice_amount <= 0:
                errors["invoice_amount"] = "Invoice amount must be greater than 0"
            if payment_amount > invoice_amount:
                errors["payment_amount"] = "Payment amount cannot exceed invoice amount"
            if payment_amount <= 0:
                errors["payment_amount"] = "Payment amount must be greater than 0"
            if not description:
                errors["description"] = "Description is required"
            if not invoice_number:
                errors["invoice_number"] = "Invoice number is required"
            if not pjv_number:
                errors["pjv_number"] = "PJV number is required"
            if method_request not in METHOD_REQUEST_CODES:
                errors["method_request"] = "Invalid request method selected"
            if method_procurement not in METHOD_PROCUREMENT_CODES:
                errors["method_procurement"] = "Invalid procurement method selected"
            if number_type and number_type.upper() not in ALLOWED_NUMBER_TYPES:
                errors["number_type"] = "Invalid approval type selected"
                number_type = "TF"
            else:
                number_type = (number_type or "TF").upper()

            # Check duplicate PJV (excluding current)
            cursor.execute("SELECT id FROM invoices WHERE pjv_number = ? AND id != ? AND is_deleted = 0", (pjv_number, invoice_id))
            if cursor.fetchone():
                errors["pjv_number"] = "This PJV number is already in use"

            # Parse date
            try:
                parsed_date = datetime.strptime(invoice_date, "%Y-%m-%d").date()
                if parsed_date > date.today():
                    errors["invoice_date"] = "Invoice date cannot be in the future"
                # Prevent unrealistic old dates (before year 2000)
                elif parsed_date.year < 2000:
                    errors["invoice_date"] = "Invoice date must be year 2000 or later"
            except ValueError:
                errors["invoice_date"] = "Invalid date format"

            if errors:
                cursor.execute("SELECT * FROM suppliers ORDER BY name")
                suppliers = [dict(row) for row in cursor.fetchall()]
                next_tf = preview_next_number(conn, 'TF')
                next_chq = preview_next_number(conn, 'CHQ')

                return templates.TemplateResponse(
                    "invoice_form.html",
                    {
                        "request": request,
                        "suppliers": suppliers,
                        "invoice": invoice,
                        "next_tf_number": next_tf,
                        "next_chq_number": next_chq,
                        "method_request_codes": METHOD_REQUEST_CODES,
                        "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                        "is_edit": True,
                        "errors": errors,
                        "form_data": {
                            "new_supplier_email": new_supplier_email,
                            "new_supplier_phone": new_supplier_phone
                        },
                        "today": date.today().isoformat()
                    },
                    status_code=400
                )

            # Handle approval
            tf_number = invoice['tf_number']
            chq_number = invoice['chq_number']
            approved_date = invoice['approved_date']

            if is_approved and not invoice['is_approved']:
                approved_date = date.today().isoformat()
                if not tf_number and not chq_number:
                    if number_type == "CHQ":
                        chq_number = get_next_number(conn, 'CHQ')
                    else:
                        tf_number = get_next_number(conn, 'TF')

            # Update invoice
            try:
                cursor.execute("""
                    UPDATE invoices SET
                        supplier_id = ?, invoice_amount = ?, payment_amount = ?,
                        method_request = ?, method_procurement = ?, description = ?,
                        invoice_date = ?, invoice_number = ?, po_number = ?, pjv_number = ?,
                        number_type = ?, tf_number = ?, chq_number = ?,
                        is_approved = ?, approved_date = ?,
                        proposer_councillor = ?, seconder_councillor = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    supplier_id, invoice_amount, payment_amount,
                    method_request, method_procurement, description,
                    invoice_date, invoice_number,
                    po_number, pjv_number,
                    number_type or "TF", tf_number, chq_number,
                    1 if is_approved else 0, approved_date,
                    proposer_councillor, seconder_councillor,
                    invoice_id
                ))
            except Exception as e:
                print(f"[ERROR] Error updating invoice {invoice_id}: {str(e)}")
                cursor.execute("SELECT * FROM suppliers ORDER BY name")
                suppliers = [dict(row) for row in cursor.fetchall()]
                next_tf = preview_next_number(conn, 'TF')
                next_chq = preview_next_number(conn, 'CHQ')

                return templates.TemplateResponse(
                    "invoice_form.html",
                    {
                        "request": request,
                        "suppliers": suppliers,
                        "invoice": invoice,
                        "next_tf_number": next_tf,
                        "next_chq_number": next_chq,
                        "method_request_codes": METHOD_REQUEST_CODES,
                        "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                        "is_edit": True,
                        "errors": {"database": "An error occurred while updating the invoice. Please try again."},
                        "today": date.today().isoformat()
                    },
                    status_code=500
                )

            # Optional fiscal receipt upload (atomic replace: write new -> update DB -> delete old after commit)
            if fiscal_receipt and fiscal_receipt.filename:
                try:
                    new_receipt_filename = await save_fiscal_receipt_file(fiscal_receipt, invoice_id)
                    cursor.execute(
                        "UPDATE invoices SET fiscal_receipt_path = ? WHERE id = ?",
                        (new_receipt_filename, invoice_id)
                    )
                    old_receipt_to_delete = invoice.get("fiscal_receipt_path")
                except ValueError as e:
                    errors["fiscal_receipt"] = str(e)
                    cursor.execute("SELECT * FROM suppliers ORDER BY name")
                    suppliers = [dict(row) for row in cursor.fetchall()]
                    next_tf = preview_next_number(conn, 'TF')
                    next_chq = preview_next_number(conn, 'CHQ')

                    return templates.TemplateResponse(
                        "invoice_form.html",
                        {
                            "request": request,
                            "suppliers": suppliers,
                            "invoice": invoice,
                            "next_tf_number": next_tf,
                            "next_chq_number": next_chq,
                            "method_request_codes": METHOD_REQUEST_CODES,
                            "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                            "is_edit": True,
                            "errors": errors,
                            "today": date.today().isoformat()
                        },
                        status_code=400
                    )

            # Log action
            user_id = get_current_user_id(request)
            ip_address = get_client_ip(request)
            log_invoice_updated(conn, user_id, invoice_id, pjv_number, None, ip_address)

            response = RedirectResponse(url="/invoices?success=Invoice+updated+successfully", status_code=303)
    except Exception:
        # If DB transaction fails after file write, remove newly written file to avoid orphans.
        if new_receipt_filename:
            delete_fiscal_receipt_file(new_receipt_filename)
        raise

    # Delete old file only after DB commit succeeds.
    if old_receipt_to_delete and old_receipt_to_delete != new_receipt_filename:
        delete_fiscal_receipt_file(old_receipt_to_delete)

    return response


@router.post("/{invoice_id}/delete")
async def delete_invoice(request: Request, invoice_id: int):
    """Soft delete an invoice."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pjv_number, tf_number, chq_number, is_void FROM invoices WHERE id = ? AND is_deleted = 0", (invoice_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Invoice not found")

        pjv_number = row[0]
        tf_number = row[1]
        chq_number = row[2]
        already_void = row[3]

        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)

        # Preserve a full audit trail by marking deletion requests as voided invoices.
        if not already_void:
            reason = "Voided after deletion request (TF/CHQ present)" if (tf_number or chq_number) else "Voided after deletion request"
            cursor.execute(
                """UPDATE invoices
                   SET is_void = 1,
                       void_reason = ?,
                       voided_at = ?,
                       voided_by = ?
                 WHERE id = ?""",
                (reason, datetime.now().isoformat(), user_id, invoice_id)
            )
            log_invoice_status_change(conn, user_id, invoice_id, pjv_number, "Voided", ip_address)
        elif already_void:
            # No-op but keep audit entry
            log_invoice_status_change(conn, user_id, invoice_id, pjv_number, "Voided (re-request)", ip_address)

        return RedirectResponse(url="/invoices", status_code=303)


@router.post("/{invoice_id}/approve")
async def quick_approve_invoice(
    request: Request,
    invoice_id: int,
    number_type: str = Form("TF")
):
    """Quick approve an invoice."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Use IMMEDIATE transaction to prevent race condition with TF number generation
        cursor.execute("BEGIN IMMEDIATE")

        try:
            cursor.execute("SELECT * FROM invoices WHERE id = ? AND is_deleted = 0 AND is_approved = 0 AND is_void = 0", (invoice_id,))
            row = cursor.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Invoice not found or already approved")

            invoice = dict(row)

            tf_number = invoice['tf_number']
            chq_number = invoice['chq_number']

            if not tf_number and not chq_number:
                if number_type == "CHQ":
                    chq_number = get_next_number(conn, 'CHQ')
                else:
                    tf_number = get_next_number(conn, 'TF')

            # Use WHERE clause to double-check not already approved (race condition protection)
            cursor.execute("""
                UPDATE invoices SET
                    is_approved = 1, approved_date = ?, number_type = ?,
                    tf_number = ?, chq_number = ?
                WHERE id = ? AND is_approved = 0
            """, (date.today().isoformat(), number_type or "TF", tf_number, chq_number, invoice_id))

            if cursor.rowcount == 0:
                raise HTTPException(status_code=409, detail="Invoice was already approved by another user")
        except HTTPException:
            raise
        except Exception as e:
            raise e

        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)
        log_invoice_status_change(conn, user_id, invoice_id, invoice['pjv_number'], "Approved", ip_address)

        return RedirectResponse(url="/invoices", status_code=303)


@router.post("/{invoice_id}/unapprove")
async def unapprove_invoice(request: Request, invoice_id: int):
    """Unapprove an invoice (keeps TF number)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pjv_number FROM invoices WHERE id = ? AND is_deleted = 0 AND is_approved = 1 AND is_void = 0", (invoice_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Invoice not found or not approved")

        pjv_number = row[0]
        cursor.execute("UPDATE invoices SET is_approved = 0, approved_date = NULL WHERE id = ?", (invoice_id,))

        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)
        log_invoice_status_change(conn, user_id, invoice_id, pjv_number, "Unapproved", ip_address)

        return RedirectResponse(url=f"/invoices/{invoice_id}/edit", status_code=303)


# ============================================
# FISCAL RECEIPT ENDPOINTS
# ============================================

@router.post("/{invoice_id}/fiscal-receipt", response_class=JSONResponse)
async def upload_fiscal_receipt(request: Request, invoice_id: int, file: UploadFile = File(...)):
    """Upload a fiscal receipt."""
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    new_receipt_filename = None
    old_receipt_to_delete = None
    pjv_number = None

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT fiscal_receipt_path, pjv_number FROM invoices WHERE id = ? AND is_deleted = 0", (invoice_id,))
            row = cursor.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Invoice not found")

            old_receipt_to_delete, pjv_number = row

            try:
                new_receipt_filename = await save_fiscal_receipt_file(file, invoice_id)
            except ValueError as e:
                return JSONResponse(status_code=400, content={"error": str(e)})

            cursor.execute(
                "UPDATE invoices SET fiscal_receipt_path = ? WHERE id = ?",
                (new_receipt_filename, invoice_id)
            )
    except Exception:
        if new_receipt_filename:
            delete_fiscal_receipt_file(new_receipt_filename)
        raise

    if old_receipt_to_delete and old_receipt_to_delete != new_receipt_filename:
        delete_fiscal_receipt_file(old_receipt_to_delete)

    return {
        "success": True,
        "message": "Fiscal receipt uploaded",
        "filename": new_receipt_filename,
        "pjv_number": pjv_number
    }


@router.get("/{invoice_id}/fiscal-receipt")
async def get_fiscal_receipt(request: Request, invoice_id: int, download: bool = Query(False)):
    """Download/view a fiscal receipt."""
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT fiscal_receipt_path, pjv_number FROM invoices WHERE id = ? AND is_deleted = 0", (invoice_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Invoice not found")

        receipt_path, pjv_number = row

        if not receipt_path:
            raise HTTPException(status_code=404, detail="No fiscal receipt attached")

        file_path = UPLOAD_FOLDER / receipt_path

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        ext = file_path.suffix.lower()
        media_types = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
        media_type = media_types.get(ext, 'application/octet-stream')

        from starlette.responses import Response
        with open(file_path, "rb") as f:
            content = f.read()

        disposition = "attachment" if download else "inline"

        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'{disposition}; filename="fiscal_receipt_{pjv_number}{ext}"'}
        )


@router.delete("/{invoice_id}/fiscal-receipt", response_class=JSONResponse)
async def delete_fiscal_receipt(request: Request, invoice_id: int):
    """Delete a fiscal receipt."""
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT fiscal_receipt_path FROM invoices WHERE id = ? AND is_deleted = 0", (invoice_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Invoice not found")

        receipt_path = row[0]

        if not receipt_path:
            return JSONResponse(status_code=400, content={"error": "No fiscal receipt to delete"})

        file_path = UPLOAD_FOLDER / receipt_path
        if file_path.exists():
            file_path.unlink()

        cursor.execute("UPDATE invoices SET fiscal_receipt_path = NULL WHERE id = ?", (invoice_id,))

        return {"success": True, "message": "Fiscal receipt deleted"}


# ============================================
# BULK OPERATIONS
# ============================================

@router.post("/bulk-approve", response_class=JSONResponse)
async def bulk_approve_invoices(request: Request):
    """Approve multiple invoices."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])
    number_type = data.get("number_type", "TF").upper()  # TF or CHQ

    if not invoice_ids:
        return JSONResponse(status_code=400, content={"error": "No invoices selected"})

    if number_type not in ("TF", "CHQ"):
        return JSONResponse(status_code=400, content={"error": "Invalid number type. Must be TF or CHQ"})

    # Validate all IDs are integers to prevent injection
    try:
        invoice_ids = [int(id) for id in invoice_ids]
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"error": "Invalid invoice IDs"})

    with get_db() as conn:
        cursor = conn.cursor()
        approved_count = 0
        errors = []

        # Use IMMEDIATE transaction to prevent race conditions with TF/CHQ number generation
        cursor.execute("BEGIN IMMEDIATE")

        try:
            for inv_id in invoice_ids:
                cursor.execute("SELECT tf_number, chq_number FROM invoices WHERE id = ? AND is_deleted = 0 AND is_approved = 0 AND is_void = 0", (inv_id,))
                row = cursor.fetchone()

                if not row:
                    errors.append(f"Invoice {inv_id} not found or already approved")
                    continue

                tf_number = row[0]
                chq_number = row[1]

                # Generate the appropriate number based on type
                if number_type == "CHQ":
                    if not chq_number:
                        chq_number = get_next_number(conn, 'CHQ')
                    cursor.execute("""
                        UPDATE invoices SET is_approved = 1, approved_date = ?, chq_number = ?, number_type = 'CHQ'
                        WHERE id = ?
                    """, (date.today().isoformat(), chq_number, inv_id))
                else:  # TF
                    if not tf_number:
                        tf_number = get_next_number(conn, 'TF')
                    cursor.execute("""
                        UPDATE invoices SET is_approved = 1, approved_date = ?, tf_number = ?, number_type = 'TF'
                        WHERE id = ?
                    """, (date.today().isoformat(), tf_number, inv_id))

                approved_count += 1
        except Exception as e:
            raise e

        type_label = "CHQ" if number_type == "CHQ" else "TF"
        return {
            "success": True,
            "approved_count": approved_count,
            "errors": errors if errors else None,
            "message": f"Successfully approved {approved_count} invoice(s) with {type_label} numbers"
        }


@router.post("/bulk-unapprove", response_class=JSONResponse)
async def bulk_unapprove_invoices(request: Request):
    """Unapprove multiple invoices (keeps TF numbers)."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])

    if not invoice_ids:
        return JSONResponse(status_code=400, content={"error": "No invoices selected"})

    # Validate all IDs are integers to prevent injection
    try:
        invoice_ids = [int(id) for id in invoice_ids]
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"error": "Invalid invoice IDs"})

    with get_db() as conn:
        cursor = conn.cursor()
        unapproved_count = 0
        errors = []

        # Use BEGIN IMMEDIATE to prevent race conditions (consistent with bulk_approve)
        cursor.execute("BEGIN IMMEDIATE")
        try:
            for inv_id in invoice_ids:
                cursor.execute("SELECT id FROM invoices WHERE id = ? AND is_deleted = 0 AND is_approved = 1 AND is_void = 0", (inv_id,))
                if not cursor.fetchone():
                    errors.append(f"Invoice {inv_id} not found or not approved")
                    continue

                cursor.execute("UPDATE invoices SET is_approved = 0, approved_date = NULL WHERE id = ?", (inv_id,))
                unapproved_count += 1
        except Exception:
            raise

        return {
            "success": True,
            "unapproved_count": unapproved_count,
            "errors": errors if errors else None,
            "message": f"Successfully unapproved {unapproved_count} invoice(s)"
        }
