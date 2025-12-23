"""
Invoice CRUD Routes

Handles all invoice operations including:
- Create, Read, Update, Delete
- Approval with TF number generation
- Filtering and sorting
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc

from database import get_db
from models import Invoice, Supplier, METHOD_REQUEST_CODES, METHOD_PROCUREMENT_CODES
from services.tf_service import generate_next_tf_number, get_next_tf_number_preview

router = APIRouter(prefix="/invoices", tags=["invoices"])
templates = Jinja2Templates(directory="templates")


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

    # Apply sorting
    sort_column = getattr(Invoice, sort_by, Invoice.created_at)
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

    # Handle approval (one-way: can approve but not un-approve)
    if is_approved and not invoice.is_approved:
        invoice.is_approved = True
        invoice.approved_date = date.today()
        invoice.proposer_councillor = proposer_councillor.strip() if proposer_councillor else None
        invoice.seconder_councillor = seconder_councillor.strip() if seconder_councillor else None
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
    invoice.tf_number = generate_next_tf_number(db)

    db.commit()

    return RedirectResponse(url="/invoices", status_code=303)
