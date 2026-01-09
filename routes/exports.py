"""
Export Routes

Handles Excel, PDF, and CSV export generation for Schedule of Payments.
"""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from models import Invoice
from services.export_service import (
    generate_schedule_excel,
    generate_schedule_pdf,
    generate_schedule_csv,
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


# ============================================
# CSV EXPORTS
# ============================================

@router.get("/csv")
async def export_csv(
    db: Session = Depends(get_db),
    approved_only: bool = Query(False, description="Export only approved invoices"),
    status: Optional[str] = Query(None, description="Filter by status: pending, approved"),
    supplier_id: Optional[int] = Query(None, description="Filter by supplier"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    sitting_number: Optional[str] = Query(None, description="Council sitting number")
):
    """
    Export invoices to CSV file with optional filters.
    """
    query = db.query(Invoice).filter(Invoice.is_deleted == False)

    # Apply filters
    if approved_only or status == "approved":
        query = query.filter(Invoice.is_approved == True)
    elif status == "pending":
        query = query.filter(Invoice.is_approved == False)

    if supplier_id:
        query = query.filter(Invoice.supplier_id == supplier_id)

    if date_from:
        try:
            from datetime import datetime as dt
            from_date = dt.strptime(date_from, "%Y-%m-%d").date()
            query = query.filter(Invoice.invoice_date >= from_date)
        except ValueError:
            pass

    if date_to:
        try:
            from datetime import datetime as dt
            to_date = dt.strptime(date_to, "%Y-%m-%d").date()
            query = query.filter(Invoice.invoice_date <= to_date)
        except ValueError:
            pass

    invoices = query.order_by(desc(Invoice.created_at)).all()

    buffer = generate_schedule_csv(invoices, sitting_number)
    filename = get_export_filename("csv", approved_only)

    return StreamingResponse(
        buffer,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


# ============================================
# EXPORT SELECTED ITEMS
# ============================================

@router.post("/selected/csv")
async def export_selected_csv(
    request: Request,
    db: Session = Depends(get_db)
):
    """Export selected invoices to CSV."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])

    if not invoice_ids:
        return JSONResponse(
            status_code=400,
            content={"error": "No invoices selected"}
        )

    invoices = db.query(Invoice).filter(
        Invoice.id.in_(invoice_ids),
        Invoice.is_deleted == False
    ).order_by(desc(Invoice.created_at)).all()

    buffer = generate_schedule_csv(invoices)

    return StreamingResponse(
        buffer,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=Selected_Invoices_{datetime.now().strftime('%Y%m%d')}.csv"
        }
    )


@router.post("/selected/excel")
async def export_selected_excel(
    request: Request,
    db: Session = Depends(get_db)
):
    """Export selected invoices to Excel."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])

    if not invoice_ids:
        return JSONResponse(
            status_code=400,
            content={"error": "No invoices selected"}
        )

    invoices = db.query(Invoice).filter(
        Invoice.id.in_(invoice_ids),
        Invoice.is_deleted == False
    ).order_by(desc(Invoice.created_at)).all()

    month_year = datetime.now().strftime("%B %Y")
    buffer = generate_schedule_excel(invoices, None, month_year)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=Selected_Invoices_{datetime.now().strftime('%Y%m%d')}.xlsx"
        }
    )


@router.post("/selected/pdf")
async def export_selected_pdf(
    request: Request,
    db: Session = Depends(get_db)
):
    """Export selected invoices to PDF."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])

    if not invoice_ids:
        return JSONResponse(
            status_code=400,
            content={"error": "No invoices selected"}
        )

    invoices = db.query(Invoice).filter(
        Invoice.id.in_(invoice_ids),
        Invoice.is_deleted == False
    ).order_by(desc(Invoice.created_at)).all()

    month_year = datetime.now().strftime("%B %Y")
    buffer = generate_schedule_pdf(invoices, None, month_year)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=Selected_Invoices_{datetime.now().strftime('%Y%m%d')}.pdf"
        }
    )
