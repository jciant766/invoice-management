"""
Invoice CRUD Routes

Handles all invoice operations including:
- Create, Read, Update, Delete
- Approval with TF number generation
- Filtering and sorting
"""

import os
import uuid
import aiofiles
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc

from database import get_db
from models import Invoice, Supplier, METHOD_REQUEST_CODES, METHOD_PROCUREMENT_CODES
from services.tf_service import generate_next_tf_number, get_next_tf_number_preview

# Upload configuration
UPLOAD_FOLDER = Path("uploads/fiscal_receipts")
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

router = APIRouter(prefix="/invoices", tags=["invoices"])
templates = Jinja2Templates(directory="templates")

# Whitelist of allowed sort columns (security - prevent accessing arbitrary attributes)
ALLOWED_SORT_COLUMNS = {
    'created_at', 'invoice_date', 'invoice_amount', 'payment_amount',
    'supplier_id', 'pjv_number', 'invoice_number', 'tf_number', 'is_approved'
}


@router.get("", response_class=HTMLResponse)
async def list_invoices(
    request: Request,
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, all"),
    supplier_id: Optional[int] = Query(None, description="Filter by supplier"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    sort_by: Optional[str] = Query("created_at", description="Sort field"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc")
):
    """List all invoices with optional filters."""
    query = db.query(Invoice).filter(Invoice.is_deleted == False)

    # Apply filters
    if status == "pending":
        query = query.filter(Invoice.is_approved == False)
    elif status == "approved":
        query = query.filter(Invoice.is_approved == True)

    if supplier_id:
        query = query.filter(Invoice.supplier_id == supplier_id)

    if date_from:
        try:
            from_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            query = query.filter(Invoice.invoice_date >= from_date)
        except ValueError:
            pass

    if date_to:
        try:
            to_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            query = query.filter(Invoice.invoice_date <= to_date)
        except ValueError:
            pass

    # Apply sorting (with security whitelist)
    if sort_by not in ALLOWED_SORT_COLUMNS:
        sort_by = 'created_at'  # Default to safe value
    sort_column = getattr(Invoice, sort_by, Invoice.created_at)
    if sort_order not in ('asc', 'desc'):
        sort_order = 'desc'  # Default to safe value
    if sort_order == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))

    invoices = query.all()
    suppliers = db.query(Supplier).order_by(Supplier.name).all()

    # Calculate totals
    total_invoice_amount = sum(float(inv.invoice_amount) for inv in invoices)
    total_payment_amount = sum(float(inv.payment_amount) for inv in invoices)

    return templates.TemplateResponse(
        "invoice_list.html",
        {
            "request": request,
            "invoices": invoices,
            "suppliers": suppliers,
            "filters": {
                "status": status or "all",
                "supplier_id": supplier_id,
                "date_from": date_from,
                "date_to": date_to,
                "sort_by": sort_by,
                "sort_order": sort_order
            },
            "totals": {
                "invoice_amount": total_invoice_amount,
                "payment_amount": total_payment_amount,
                "count": len(invoices)
            }
        }
    )


@router.get("/create", response_class=HTMLResponse)
async def create_invoice_form(
    request: Request,
    db: Session = Depends(get_db)
):
    """Display invoice creation form."""
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    next_tf = get_next_tf_number_preview(db)

    return templates.TemplateResponse(
        "invoice_form.html",
        {
            "request": request,
            "suppliers": suppliers,
            "invoice": None,
            "next_tf_number": next_tf,
            "method_request_codes": METHOD_REQUEST_CODES,
            "method_procurement_codes": METHOD_PROCUREMENT_CODES,
            "is_edit": False,
            "errors": {}
        }
    )


@router.post("/create")
async def create_invoice(
    request: Request,
    db: Session = Depends(get_db),
    supplier_id: int = Form(...),
    new_supplier_name: Optional[str] = Form(None),
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
    proposer_councillor: Optional[str] = Form(None),
    seconder_councillor: Optional[str] = Form(None)
):
    """Create a new invoice."""
    errors = {}

    # Handle new supplier creation
    if supplier_id == -1:  # New supplier selected
        if not new_supplier_name or not new_supplier_name.strip():
            errors["new_supplier_name"] = "Please enter a supplier name"
        else:
            # Check if supplier already exists
            existing = db.query(Supplier).filter(
                Supplier.name.ilike(new_supplier_name.strip())
            ).first()
            if existing:
                supplier_id = existing.id
            else:
                new_supplier = Supplier(name=new_supplier_name.strip())
                db.add(new_supplier)
                db.flush()
                supplier_id = new_supplier.id

    # Validate required fields
    if invoice_amount <= 0:
        errors["invoice_amount"] = "Invoice amount must be greater than 0"

    if payment_amount > invoice_amount:
        errors["payment_amount"] = "Payment amount cannot exceed invoice amount"

    if payment_amount <= 0:
        errors["payment_amount"] = "Payment amount must be greater than 0"

    # Check for duplicate PJV number
    existing_pjv = db.query(Invoice).filter(
        Invoice.pjv_number == pjv_number.strip(),
        Invoice.is_deleted == False
    ).first()
    if existing_pjv:
        errors["pjv_number"] = "This PJV number is already in use. Please check your records."

    # Parse invoice date
    try:
        parsed_date = datetime.strptime(invoice_date, "%Y-%m-%d").date()
        if parsed_date > date.today():
            errors["invoice_date"] = "Invoice date cannot be in the future"
    except ValueError:
        errors["invoice_date"] = "Invalid date format"
        parsed_date = None

    # Validate approval requirements
    if is_approved:
        if not proposer_councillor or not proposer_councillor.strip():
            errors["proposer_councillor"] = "Proposer councillor is required for approval"
        if not seconder_councillor or not seconder_councillor.strip():
            errors["seconder_councillor"] = "Seconder councillor is required for approval"

    # Check for similar invoice (warning only)
    similar_invoice = db.query(Invoice).filter(
        Invoice.supplier_id == supplier_id,
        Invoice.invoice_number == invoice_number.strip(),
        Invoice.is_deleted == False
    ).first()

    # If errors, return to form
    if errors:
        suppliers = db.query(Supplier).order_by(Supplier.name).all()
        next_tf = get_next_tf_number_preview(db)

        return templates.TemplateResponse(
            "invoice_form.html",
            {
                "request": request,
                "suppliers": suppliers,
                "invoice": None,
                "next_tf_number": next_tf,
                "method_request_codes": METHOD_REQUEST_CODES,
                "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                "is_edit": False,
                "errors": errors,
                "form_data": {
                    "supplier_id": supplier_id,
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
                    "proposer_councillor": proposer_councillor,
                    "seconder_councillor": seconder_councillor
                },
                "warning": "Similar invoice found" if similar_invoice else None
            },
            status_code=400
        )

    # Create invoice
    invoice = Invoice(
        supplier_id=supplier_id,
        invoice_amount=Decimal(str(invoice_amount)),
        payment_amount=Decimal(str(payment_amount)),
        method_request=method_request,
        method_procurement=method_procurement,
        description=description.strip(),
        invoice_date=parsed_date,
        invoice_number=invoice_number.strip(),
        po_number=po_number.strip() if po_number else None,
        pjv_number=pjv_number.strip()
    )

    # Handle approval
    if is_approved:
        invoice.is_approved = True
        invoice.approved_date = date.today()
        invoice.proposer_councillor = proposer_councillor.strip()
        invoice.seconder_councillor = seconder_councillor.strip()
        invoice.tf_number = generate_next_tf_number(db)

    db.add(invoice)
    db.commit()

    return RedirectResponse(url="/invoices", status_code=303)


@router.get("/{invoice_id}/edit", response_class=HTMLResponse)
async def edit_invoice_form(
    request: Request,
    invoice_id: int,
    db: Session = Depends(get_db)
):
    """Display invoice edit form."""
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.is_deleted == False
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    next_tf = get_next_tf_number_preview(db)

    return templates.TemplateResponse(
        "invoice_form.html",
        {
            "request": request,
            "suppliers": suppliers,
            "invoice": invoice,
            "next_tf_number": next_tf,
            "method_request_codes": METHOD_REQUEST_CODES,
            "method_procurement_codes": METHOD_PROCUREMENT_CODES,
            "is_edit": True,
            "errors": {}
        }
    )


@router.post("/{invoice_id}/edit")
async def update_invoice(
    request: Request,
    invoice_id: int,
    db: Session = Depends(get_db),
    supplier_id: int = Form(...),
    new_supplier_name: Optional[str] = Form(None),
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
    proposer_councillor: Optional[str] = Form(None),
    seconder_councillor: Optional[str] = Form(None)
):
    """Update an existing invoice."""
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.is_deleted == False
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    errors = {}

    # Handle new supplier creation
    if supplier_id == -1:
        if not new_supplier_name or not new_supplier_name.strip():
            errors["new_supplier_name"] = "Please enter a supplier name"
        else:
            existing = db.query(Supplier).filter(
                Supplier.name.ilike(new_supplier_name.strip())
            ).first()
            if existing:
                supplier_id = existing.id
            else:
                new_supplier = Supplier(name=new_supplier_name.strip())
                db.add(new_supplier)
                db.flush()
                supplier_id = new_supplier.id

    # Validations
    if invoice_amount <= 0:
        errors["invoice_amount"] = "Invoice amount must be greater than 0"

    if payment_amount > invoice_amount:
        errors["payment_amount"] = "Payment amount cannot exceed invoice amount"

    if payment_amount <= 0:
        errors["payment_amount"] = "Payment amount must be greater than 0"

    # Check for duplicate PJV (excluding current invoice)
    existing_pjv = db.query(Invoice).filter(
        Invoice.pjv_number == pjv_number.strip(),
        Invoice.id != invoice_id,
        Invoice.is_deleted == False
    ).first()
    if existing_pjv:
        errors["pjv_number"] = "This PJV number is already in use. Please check your records."

    # Parse date
    try:
        parsed_date = datetime.strptime(invoice_date, "%Y-%m-%d").date()
        if parsed_date > date.today():
            errors["invoice_date"] = "Invoice date cannot be in the future"
    except ValueError:
        errors["invoice_date"] = "Invalid date format"
        parsed_date = invoice.invoice_date

    # Validate approval (only if newly approving)
    if is_approved and not invoice.is_approved:
        if not proposer_councillor or not proposer_councillor.strip():
            errors["proposer_councillor"] = "Proposer councillor is required for approval"
        if not seconder_councillor or not seconder_councillor.strip():
            errors["seconder_councillor"] = "Seconder councillor is required for approval"

    if errors:
        suppliers = db.query(Supplier).order_by(Supplier.name).all()
        next_tf = get_next_tf_number_preview(db)

        return templates.TemplateResponse(
            "invoice_form.html",
            {
                "request": request,
                "suppliers": suppliers,
                "invoice": invoice,
                "next_tf_number": next_tf,
                "method_request_codes": METHOD_REQUEST_CODES,
                "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                "is_edit": True,
                "errors": errors
            },
            status_code=400
        )

    # Update invoice
    invoice.supplier_id = supplier_id
    invoice.invoice_amount = Decimal(str(invoice_amount))
    invoice.payment_amount = Decimal(str(payment_amount))
    invoice.method_request = method_request
    invoice.method_procurement = method_procurement
    invoice.description = description.strip()
    invoice.invoice_date = parsed_date
    invoice.invoice_number = invoice_number.strip()
    invoice.po_number = po_number.strip() if po_number else None
    invoice.pjv_number = pjv_number.strip()

    # Handle approval
    if is_approved and not invoice.is_approved:
        # Approving (or re-approving) an invoice
        invoice.is_approved = True
        invoice.approved_date = date.today()
        invoice.proposer_councillor = proposer_councillor.strip() if proposer_councillor else None
        invoice.seconder_councillor = seconder_councillor.strip() if seconder_councillor else None
        # Only generate new TF if doesn't have one (re-approval keeps existing TF)
        if not invoice.tf_number:
            invoice.tf_number = generate_next_tf_number(db)
    elif invoice.is_approved:
        # Update councillor names if already approved
        if proposer_councillor:
            invoice.proposer_councillor = proposer_councillor.strip()
        if seconder_councillor:
            invoice.seconder_councillor = seconder_councillor.strip()

    db.commit()

    return RedirectResponse(url="/invoices", status_code=303)


@router.post("/{invoice_id}/delete")
async def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db)
):
    """Soft delete an invoice."""
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.is_deleted == False
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Soft delete - TF number is NOT reused
    invoice.is_deleted = True
    db.commit()

    return RedirectResponse(url="/invoices", status_code=303)


@router.post("/{invoice_id}/approve")
async def quick_approve_invoice(
    request: Request,
    invoice_id: int,
    db: Session = Depends(get_db),
    proposer_councillor: str = Form(...),
    seconder_councillor: str = Form(...)
):
    """Quick approve an invoice (from list view)."""
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.is_deleted == False,
        Invoice.is_approved == False
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found or already approved")

    if not proposer_councillor.strip() or not seconder_councillor.strip():
        raise HTTPException(status_code=400, detail="Both councillor names are required")

    invoice.is_approved = True
    invoice.approved_date = date.today()
    invoice.proposer_councillor = proposer_councillor.strip()
    invoice.seconder_councillor = seconder_councillor.strip()
    # Only generate new TF if doesn't have one (re-approval keeps existing TF)
    if not invoice.tf_number:
        invoice.tf_number = generate_next_tf_number(db)

    db.commit()

    return RedirectResponse(url="/invoices", status_code=303)


@router.post("/{invoice_id}/unapprove")
async def unapprove_invoice(
    invoice_id: int,
    db: Session = Depends(get_db)
):
    """
    Unapprove an invoice (reverse approval).

    KEEPS the TF number and councillor names - only changes status.
    This allows fixing mistakes without losing the TF reference.
    """
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.is_deleted == False,
        Invoice.is_approved == True  # Must be approved to unapprove
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found or not approved")

    # Only change approval status - KEEP TF number and councillor names
    invoice.is_approved = False
    invoice.approved_date = None
    # TF number stays - it's a permanent reference ID
    # Councillor names stay - so user doesn't have to re-enter

    db.commit()

    return RedirectResponse(url=f"/invoices/{invoice_id}/edit", status_code=303)


# ============================================
# FISCAL RECEIPT ENDPOINTS
# ============================================

@router.post("/{invoice_id}/fiscal-receipt", response_class=JSONResponse)
async def upload_fiscal_receipt(
    invoice_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload a fiscal receipt PDF/image for an invoice."""
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.is_deleted == False
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Validate file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"error": f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}
        )

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        return JSONResponse(
            status_code=400,
            content={"error": f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"}
        )

    # Delete old file if exists
    if invoice.fiscal_receipt_path:
        old_path = UPLOAD_FOLDER / invoice.fiscal_receipt_path
        if old_path.exists():
            old_path.unlink()

    # Generate unique filename
    unique_filename = f"{invoice_id}_{uuid.uuid4().hex[:8]}{file_ext}"
    file_path = UPLOAD_FOLDER / unique_filename

    # Save file
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)

    # Update invoice record
    invoice.fiscal_receipt_path = unique_filename
    db.commit()

    return {
        "success": True,
        "message": "Fiscal receipt uploaded successfully",
        "filename": unique_filename
    }


@router.get("/{invoice_id}/fiscal-receipt")
async def get_fiscal_receipt(
    invoice_id: int,
    download: bool = Query(False, description="Set to true to download instead of preview"),
    db: Session = Depends(get_db)
):
    """Download/view a fiscal receipt. Use ?download=true to force download."""
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.is_deleted == False
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if not invoice.fiscal_receipt_path:
        raise HTTPException(status_code=404, detail="No fiscal receipt attached")

    file_path = UPLOAD_FOLDER / invoice.fiscal_receipt_path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")

    # Determine media type
    ext = file_path.suffix.lower()
    media_types = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png'
    }
    media_type = media_types.get(ext, 'application/octet-stream')

    from starlette.responses import Response
    with open(file_path, "rb") as f:
        content = f.read()

    # Use 'attachment' for download, 'inline' for preview
    disposition = "attachment" if download else "inline"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="fiscal_receipt_{invoice.pjv_number}{ext}"'
        }
    )


@router.delete("/{invoice_id}/fiscal-receipt", response_class=JSONResponse)
async def delete_fiscal_receipt(
    invoice_id: int,
    db: Session = Depends(get_db)
):
    """Delete a fiscal receipt from an invoice."""
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.is_deleted == False
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if not invoice.fiscal_receipt_path:
        return JSONResponse(
            status_code=400,
            content={"error": "No fiscal receipt to delete"}
        )

    # Delete file
    file_path = UPLOAD_FOLDER / invoice.fiscal_receipt_path
    if file_path.exists():
        file_path.unlink()

    # Update record
    invoice.fiscal_receipt_path = None
    db.commit()

    return {
        "success": True,
        "message": "Fiscal receipt deleted"
    }


# ============================================
# BULK OPERATIONS
# ============================================

@router.post("/bulk-approve", response_class=JSONResponse)
async def bulk_approve_invoices(
    request: Request,
    db: Session = Depends(get_db)
):
    """Approve multiple invoices at once (no councillor names required)."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])

    if not invoice_ids:
        return JSONResponse(
            status_code=400,
            content={"error": "No invoices selected"}
        )

    approved_count = 0
    errors = []

    for inv_id in invoice_ids:
        invoice = db.query(Invoice).filter(
            Invoice.id == inv_id,
            Invoice.is_deleted == False,
            Invoice.is_approved == False
        ).first()

        if not invoice:
            errors.append(f"Invoice {inv_id} not found or already approved")
            continue

        invoice.is_approved = True
        invoice.approved_date = date.today()
        # Only generate new TF if doesn't have one (re-approval keeps existing TF)
        if not invoice.tf_number:
            invoice.tf_number = generate_next_tf_number(db)
        approved_count += 1

    db.commit()

    return {
        "success": True,
        "approved_count": approved_count,
        "errors": errors if errors else None,
        "message": f"Successfully approved {approved_count} invoice(s)"
    }


@router.post("/bulk-unapprove", response_class=JSONResponse)
async def bulk_unapprove_invoices(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Unapprove multiple invoices at once.

    KEEPS TF numbers and councillor names - only changes status.
    """
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])

    if not invoice_ids:
        return JSONResponse(
            status_code=400,
            content={"error": "No invoices selected"}
        )

    unapproved_count = 0
    errors = []

    for inv_id in invoice_ids:
        invoice = db.query(Invoice).filter(
            Invoice.id == inv_id,
            Invoice.is_deleted == False,
            Invoice.is_approved == True  # Must be approved to unapprove
        ).first()

        if not invoice:
            errors.append(f"Invoice {inv_id} not found or not approved")
            continue

        # Only change status - KEEP TF number and councillor names
        invoice.is_approved = False
        invoice.approved_date = None
        # TF number stays - permanent reference ID
        # Councillor names stay
        unapproved_count += 1

    db.commit()

    return {
        "success": True,
        "unapproved_count": unapproved_count,
        "errors": errors if errors else None,
        "message": f"Successfully unapproved {unapproved_count} invoice(s)"
    }
