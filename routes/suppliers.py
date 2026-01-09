"""
Supplier Routes

Handles supplier management:
- List suppliers with search and filtering
- Add, edit, delete suppliers
- Merge suppliers
"""

from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from database import get_db
from models import Supplier, Invoice

router = APIRouter(prefix="/suppliers", tags=["suppliers"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def suppliers_page(
    request: Request,
    q: Optional[str] = Query(None, description="Search query"),
    status: str = Query("all", description="Filter by status"),
    db: Session = Depends(get_db)
):
    """Display suppliers list page."""
    # Base query with invoice count
    query = db.query(
        Supplier,
        func.count(Invoice.id).label('invoice_count')
    ).outerjoin(
        Invoice, (Invoice.supplier_id == Supplier.id) & (Invoice.is_deleted == False)
    ).group_by(Supplier.id)

    # Search filter
    if q:
        query = query.filter(
            or_(
                Supplier.name.ilike(f"%{q}%"),
                Supplier.contact_email.ilike(f"%{q}%")
            )
        )

    # Status filter
    if status == "active":
        query = query.filter(Supplier.is_active == True)
    elif status == "inactive":
        query = query.filter(Supplier.is_active == False)

    suppliers = query.order_by(Supplier.name).all()

    # Stats
    total = db.query(Supplier).count()
    active = db.query(Supplier).filter(Supplier.is_active == True).count()
    inactive = total - active

    return templates.TemplateResponse(
        "suppliers.html",
        {
            "request": request,
            "suppliers": suppliers,
            "search_query": q,
            "status_filter": status,
            "stats": {
                "total": total,
                "active": active,
                "inactive": inactive
            }
        }
    )


@router.post("/add")
async def add_supplier(
    db: Session = Depends(get_db),
    name: str = Form(...),
    email: Optional[str] = Form(None)
):
    """Add a new supplier."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Supplier name is required")

    # Check for duplicate
    existing = db.query(Supplier).filter(Supplier.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Supplier already exists")

    supplier = Supplier(
        name=name,
        contact_email=email.strip() if email else None,
        is_active=True
    )
    db.add(supplier)
    db.commit()

    return RedirectResponse(url="/suppliers", status_code=303)


@router.post("/{supplier_id}/edit")
async def edit_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    email: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None)
):
    """Edit supplier."""
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Supplier name is required")

    # Check for duplicate (excluding current)
    existing = db.query(Supplier).filter(
        Supplier.name.ilike(name),
        Supplier.id != supplier_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Another supplier with this name exists")

    supplier.name = name
    supplier.contact_email = email.strip() if email else None
    supplier.is_active = is_active == "1"
    db.commit()

    return RedirectResponse(url="/suppliers", status_code=303)


@router.post("/{supplier_id}/delete")
async def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db)
):
    """Delete a supplier (only if no invoices)."""
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    # Check for invoices
    invoice_count = db.query(Invoice).filter(
        Invoice.supplier_id == supplier_id,
        Invoice.is_deleted == False
    ).count()

    if invoice_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete supplier with {invoice_count} invoices. Use merge instead."
        )

    db.delete(supplier)
    db.commit()

    return RedirectResponse(url="/suppliers", status_code=303)


@router.post("/merge")
async def merge_suppliers(
    db: Session = Depends(get_db),
    source_id: int = Form(...),
    target_id: int = Form(...)
):
    """Merge one supplier into another (reassign all invoices)."""
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot merge supplier with itself")

    source = db.query(Supplier).filter(Supplier.id == source_id).first()
    target = db.query(Supplier).filter(Supplier.id == target_id).first()

    if not source or not target:
        raise HTTPException(status_code=404, detail="Supplier not found")

    # Reassign all invoices from source to target
    db.query(Invoice).filter(Invoice.supplier_id == source_id).update(
        {Invoice.supplier_id: target_id}
    )

    # Delete source supplier
    db.delete(source)
    db.commit()

    return RedirectResponse(url="/suppliers", status_code=303)


# API endpoint for AJAX
@router.get("/api/list")
async def get_suppliers_json(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Search query")
):
    """Get suppliers list as JSON (for autocomplete)."""
    query = db.query(Supplier).filter(Supplier.is_active == True)

    if q:
        query = query.filter(Supplier.name.ilike(f"%{q}%"))

    suppliers = query.order_by(Supplier.name).all()

    return [{"id": s.id, "name": s.name, "email": s.contact_email} for s in suppliers]
