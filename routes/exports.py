"""
Export Routes

Handles Excel and PDF export generation for Schedule of Payments.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from models import Invoice
from services.export_service import (
    generate_schedule_excel,
    generate_schedule_pdf,
    get_export_filename
)

router = APIRouter(prefix="/export", tags=["exports"])


@router.get("/excel")
async def export_excel(
    db: Session = Depends(get_db),
    approved_only: bool = Query(False, description="Export only approved invoices"),
    sitting_number: Optional[str] = Query(None, description="Council sitting number")
):
    """
    Export invoices to Excel file matching DLG template format.

    Parameters:
    - approved_only: If True, only export approved invoices (for council meeting)
    - sitting_number: Optional council sitting number to include in export
    """
    query = db.query(Invoice).filter(Invoice.is_deleted == False)

    if approved_only:
        query = query.filter(Invoice.is_approved == True)

    invoices = query.order_by(desc(Invoice.created_at)).all()

    month_year = datetime.now().strftime("%B %Y")
    buffer = generate_schedule_excel(invoices, sitting_number, month_year)
    filename = get_export_filename("xlsx", approved_only)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.get("/pdf")
async def export_pdf(
    db: Session = Depends(get_db),
    approved_only: bool = Query(False, description="Export only approved invoices"),
    sitting_number: Optional[str] = Query(None, description="Council sitting number")
):
    """
    Export invoices to PDF file for public viewing.

    Parameters:
    - approved_only: If True, only export approved invoices
    - sitting_number: Optional council sitting number to include in export
    """
    query = db.query(Invoice).filter(Invoice.is_deleted == False)

    if approved_only:
        query = query.filter(Invoice.is_approved == True)

    invoices = query.order_by(desc(Invoice.created_at)).all()

    month_year = datetime.now().strftime("%B %Y")
    buffer = generate_schedule_pdf(invoices, sitting_number, month_year)
    filename = get_export_filename("pdf", approved_only)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.get("/pending/excel")
async def export_pending_excel(
    db: Session = Depends(get_db),
    sitting_number: Optional[str] = Query(None, description="Council sitting number")
):
    """
    Export only pending invoices to Excel (for council meeting review).
    """
    invoices = db.query(Invoice).filter(
        Invoice.is_deleted == False,
        Invoice.is_approved == False
    ).order_by(desc(Invoice.created_at)).all()

    month_year = datetime.now().strftime("%B %Y")
    buffer = generate_schedule_excel(invoices, sitting_number, month_year)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=Schedule_Pending_{datetime.now().strftime('%B_%Y')}.xlsx"
        }
    )


@router.get("/pending/pdf")
async def export_pending_pdf(
    db: Session = Depends(get_db),
    sitting_number: Optional[str] = Query(None, description="Council sitting number")
):
    """
    Export only pending invoices to PDF (for council meeting review).
    """
    invoices = db.query(Invoice).filter(
        Invoice.is_deleted == False,
        Invoice.is_approved == False
    ).order_by(desc(Invoice.created_at)).all()

    month_year = datetime.now().strftime("%B %Y")
    buffer = generate_schedule_pdf(invoices, sitting_number, month_year)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=Schedule_Pending_{datetime.now().strftime('%B_%Y')}.pdf"
        }
    )
