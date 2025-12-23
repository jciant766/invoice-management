"""
Settings Routes

Handles system settings and supplier management:
- TF number counter management
- Supplier CRUD
- Supplier merge functionality
- Database backup
"""

from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
import shutil
from io import BytesIO
from datetime import datetime

from database import get_db
from models import Supplier, Invoice, Setting
from services.tf_service import (
    get_current_tf_number,
    get_next_tf_number_preview,
    update_tf_counter
)

router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: Session = Depends(get_db)
):
    """Display settings page."""
    # Get TF number info
    current_tf = get_current_tf_number(db)
    next_tf = get_next_tf_number_preview(db)

    # Get all suppliers with invoice counts
    suppliers = db.query(
        Supplier,
        func.count(Invoice.id).label('invoice_count')
    ).outerjoin(
        Invoice, (Invoice.supplier_id == Supplier.id) & (Invoice.is_deleted == False)
    ).group_by(Supplier.id).order_by(Supplier.name).all()

    # Stats
    total_invoices = db.query(Invoice).filter(Invoice.is_deleted == False).count()
    pending_invoices = db.query(Invoice).filter(
        Invoice.is_deleted == False,
        Invoice.is_approved == False
    ).count()
    approved_invoices = db.query(Invoice).filter(
        Invoice.is_deleted == False,
        Invoice.is_approved == True
    ).count()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "current_tf_number": current_tf,
            "next_tf_number": next_tf,
            "suppliers": suppliers,
            "stats": {
                "total_invoices": total_invoices,
                "pending_invoices": pending_invoices,
                "approved_invoices": approved_invoices,
                "total_suppliers": len(suppliers)
            }
        }
    )


@router.post("/tf-number")
async def update_tf_number(
    db: Session = Depends(get_db),
    new_tf_number: int = Form(...)
):
    """Update TF number counter (admin function)."""
    if new_tf_number < 0:
        raise HTTPException(status_code=400, detail="TF number cannot be negative")

    # Get current max TF number in use
    max_tf = db.query(Invoice).filter(
        Invoice.tf_number.isnot(None),
        Invoice.is_deleted == False
    ).order_by(Invoice.tf_number.desc()).first()

    if max_tf:
        # Extract number from TF string
        try:
            max_used = int(max_tf.tf_number.replace("TF ", ""))
            if new_tf_number < max_used:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot set TF counter below {max_used} (already in use)"
                )
        except ValueError:
            pass

    update_tf_counter(db, new_tf_number)
    db.commit()

    return RedirectResponse(url="/settings", status_code=303)


# Supplier Management

@router.post("/suppliers/add")
async def add_supplier(
    db: Session = Depends(get_db),
    name: str = Form(...)
):
    """Add a new supplier."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Supplier name is required")

    # Check for duplicate
    existing = db.query(Supplier).filter(Supplier.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Supplier already exists")

    supplier = Supplier(name=name)
    db.add(supplier)
    db.commit()

    return RedirectResponse(url="/settings", status_code=303)


@router.post("/suppliers/{supplier_id}/edit")
async def edit_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...)
):
    """Edit supplier name."""
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
    db.commit()

    return RedirectResponse(url="/settings", status_code=303)


@router.post("/suppliers/{supplier_id}/delete")
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
            detail=f"Cannot delete supplier with {invoice_count} invoices. Merge instead."
        )

    db.delete(supplier)
    db.commit()

    return RedirectResponse(url="/settings", status_code=303)


@router.post("/suppliers/merge")
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

    return RedirectResponse(url="/settings", status_code=303)


# Database Backup

@router.get("/backup")
async def backup_database():
    """Download database backup."""
    import os

    db_path = "invoice_management.db"
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database not found")

    # Read database file
    with open(db_path, 'rb') as f:
        db_bytes = f.read()

    buffer = BytesIO(db_bytes)
    buffer.seek(0)

    filename = f"invoice_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"

    return StreamingResponse(
        buffer,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


# API endpoints for AJAX (JSON responses)

@router.get("/api/suppliers")
async def get_suppliers_json(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Search query")
):
    """Get suppliers list as JSON (for autocomplete)."""
    query = db.query(Supplier)

    if q:
        query = query.filter(Supplier.name.ilike(f"%{q}%"))

    suppliers = query.order_by(Supplier.name).all()

    return [{"id": s.id, "name": s.name} for s in suppliers]
