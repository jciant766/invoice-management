"""
Settings Routes

Handles system settings:
- TF number counter management
- Database backup
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from io import BytesIO
from datetime import datetime

from database import get_db
from models import Supplier, Invoice
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
    total_suppliers = db.query(Supplier).count()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "current_tf_number": current_tf,
            "next_tf_number": next_tf,
            "stats": {
                "total_invoices": total_invoices,
                "pending_invoices": pending_invoices,
                "approved_invoices": approved_invoices,
                "total_suppliers": total_suppliers
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
