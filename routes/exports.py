"""
Export Routes

Handles Excel, PDF, and CSV export generation for Schedule of Payments.
"""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse

from database import get_db
from services.export_service import (
    generate_schedule_excel,
    generate_schedule_pdf,
    generate_schedule_csv,
    generate_bulk_vouchers_pdf,
    get_export_filename
)
from services.export_profile_service import resolve_export_signatories
from services.audit_service import log_export
from middleware import get_current_user_id
from routes.helpers import get_client_ip, wrap_invoices

router = APIRouter(prefix="/export", tags=["exports"])


def build_period_label(date_from: Optional[str], date_to: Optional[str]) -> str:
    """Build period label shown in schedule exports."""
    if date_from or date_to:
        return f"{date_from or '...'} to {date_to or '...'}"
    return datetime.now().strftime("%B %Y")


def infer_period_from_invoices(invoices) -> tuple[Optional[str], Optional[str]]:
    """Infer min/max invoice_date across selected invoices."""
    dates = []
    for invoice in invoices:
        value = getattr(invoice, "invoice_date", None)
        if not value:
            continue
        if hasattr(value, "strftime"):
            dates.append(value.strftime("%Y-%m-%d"))
        else:
            dates.append(str(value)[:10])

    if not dates:
        return None, None

    return min(dates), max(dates)


def build_signatory_overrides(
    sindku: Optional[str] = None,
    segretarju_ezekuttiv: Optional[str] = None,
    proponent: Optional[str] = None,
    sekondant: Optional[str] = None,
) -> dict:
    """Build a signatory override dictionary for reuse across export endpoints."""
    return {
        "sindku": sindku,
        "segretarju_ezekuttiv": segretarju_ezekuttiv,
        "proponent": proponent,
        "sekondant": sekondant,
    }


def get_invoices_for_export(
    conn,
    approved_only: bool = False,
    invoice_ids: List[int] = None,
    date_from: str = None,
    date_to: str = None,
    status: Optional[str] = None,
    supplier_id: Optional[int] = None,
    include_void: bool = False
):
    """Get invoices for export with supplier data."""
    cursor = conn.cursor()

    sql = """
        SELECT i.*, s.name as supplier_name, s.contact_email as supplier_email
        FROM invoices i
        LEFT JOIN suppliers s ON i.supplier_id = s.id
        WHERE i.is_deleted = 0
    """
    params = []

    if approved_only:
        sql += " AND i.is_approved = 1"

    if status == "pending":
        sql += " AND i.is_approved = 0"
    elif status == "approved":
        sql += " AND i.is_approved = 1"

    if not include_void:
        sql += " AND i.is_void = 0"

    if supplier_id:
        sql += " AND i.supplier_id = ?"
        params.append(supplier_id)

    # Date filters (invoice_date)
    if date_from:
        try:
            from_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            sql += " AND i.invoice_date >= ?"
            params.append(from_date.isoformat())
        except ValueError:
            pass
    if date_to:
        try:
            to_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            sql += " AND i.invoice_date <= ?"
            params.append(to_date.isoformat())
        except ValueError:
            pass

    if invoice_ids:
        placeholders = ",".join("?" * len(invoice_ids))
        sql += f" AND i.id IN ({placeholders})"
        params.extend(invoice_ids)

    sql += " ORDER BY i.created_at DESC"

    cursor.execute(sql, params)
    return wrap_invoices(cursor.fetchall())


@router.get("/excel")
async def export_excel(
    request: Request,
    approved_only: bool = Query(False, description="Export only approved invoices"),
    sitting_number: Optional[str] = Query(None, description="Council sitting number"),
    status: Optional[str] = Query(None, description="Filter by status: pending, approved"),
    supplier_id: Optional[str] = Query(None, description="Filter by supplier"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    include_void: bool = Query(False, description="Include voided invoices"),
    sindku: Optional[str] = Query(None, description="Sindku name for signature section"),
    segretarju_ezekuttiv: Optional[str] = Query(None, description="Segretarju Ezekuttiv name for signature section"),
    proponent: Optional[str] = Query(None, description="Proponent name for signature section"),
    sekondant: Optional[str] = Query(None, description="Sekondant name for signature section")
):
    """
    Export invoices to Excel file matching DLG template format.

    Parameters:
    - approved_only: If True, only export approved invoices (for council meeting)
    - sitting_number: Optional council sitting number to include in export
    """
    with get_db() as conn:
        supplier_id_int = None
        try:
            supplier_id_int = int(supplier_id) if supplier_id else None
        except (ValueError, TypeError):
            supplier_id_int = None

        invoices = get_invoices_for_export(
            conn,
            approved_only=approved_only,
            date_from=date_from,
            date_to=date_to,
            status=status,
            supplier_id=supplier_id_int,
            include_void=include_void
        )

        period_label = build_period_label(date_from, date_to)
        signatories = resolve_export_signatories(
            conn,
            build_signatory_overrides(
                sindku=sindku,
                segretarju_ezekuttiv=segretarju_ezekuttiv,
                proponent=proponent,
                sekondant=sekondant,
            ),
        )

        buffer = generate_schedule_excel(invoices, sitting_number, period_label, signatories=signatories)
        filename = get_export_filename("xlsx", approved_only)

        # Log the export
        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)
        filter_desc = "approved only" if approved_only else ("pending only" if status == "pending" else "all invoices")
        if date_from or date_to:
            filter_desc += f"; dates {date_from or '...'} to {date_to or '...'}"
        log_export(conn, user_id, "Excel", f"{len(invoices)} invoices ({filter_desc})", ip_address)

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )


@router.get("/pdf")
async def export_pdf(
    request: Request,
    approved_only: bool = Query(False, description="Export only approved invoices"),
    sitting_number: Optional[str] = Query(None, description="Council sitting number"),
    status: Optional[str] = Query(None, description="Filter by status: pending, approved"),
    supplier_id: Optional[str] = Query(None, description="Filter by supplier"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    include_void: bool = Query(False, description="Include voided invoices"),
    sindku: Optional[str] = Query(None, description="Sindku name for signature section"),
    segretarju_ezekuttiv: Optional[str] = Query(None, description="Segretarju Ezekuttiv name for signature section"),
    proponent: Optional[str] = Query(None, description="Proponent name for signature section"),
    sekondant: Optional[str] = Query(None, description="Sekondant name for signature section")
):
    """
    Export invoices to PDF file for public viewing.

    Parameters:
    - approved_only: If True, only export approved invoices
    - sitting_number: Optional council sitting number to include in export
    """
    with get_db() as conn:
        supplier_id_int = None
        try:
            supplier_id_int = int(supplier_id) if supplier_id else None
        except (ValueError, TypeError):
            supplier_id_int = None

        invoices = get_invoices_for_export(
            conn,
            approved_only=approved_only,
            date_from=date_from,
            date_to=date_to,
            status=status,
            supplier_id=supplier_id_int,
            include_void=include_void
        )

        period_label = build_period_label(date_from, date_to)
        signatories = resolve_export_signatories(
            conn,
            build_signatory_overrides(
                sindku=sindku,
                segretarju_ezekuttiv=segretarju_ezekuttiv,
                proponent=proponent,
                sekondant=sekondant,
            ),
        )

        buffer = generate_schedule_pdf(invoices, sitting_number, period_label, signatories=signatories)
        filename = get_export_filename("pdf", approved_only)

        # Log the export
        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)
        filter_desc = "approved only" if approved_only else ("pending only" if status == "pending" else "all invoices")
        if date_from or date_to:
            filter_desc += f"; dates {date_from or '...'} to {date_to or '...'}"
        log_export(conn, user_id, "PDF", f"{len(invoices)} invoices ({filter_desc})", ip_address)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )


@router.get("/pending/excel")
async def export_pending_excel(
    request: Request,
    sitting_number: Optional[str] = Query(None, description="Council sitting number")
):
    """
    Export only pending invoices to Excel (for council meeting review).
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT i.*, s.name as supplier_name, s.contact_email as supplier_email
            FROM invoices i
            LEFT JOIN suppliers s ON i.supplier_id = s.id
            WHERE i.is_deleted = 0 AND i.is_approved = 0 AND i.is_void = 0
            ORDER BY i.created_at DESC
        """)
        invoices = wrap_invoices(cursor.fetchall())

        month_year = datetime.now().strftime("%B %Y")
        signatories = resolve_export_signatories(conn)
        buffer = generate_schedule_excel(invoices, sitting_number, month_year, signatories=signatories)

        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)
        log_export(conn, user_id, "Excel", f"{len(invoices)} invoices (pending only)", ip_address)

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=Schedule_Pending_{datetime.now().strftime('%B_%Y')}.xlsx"
            }
        )


@router.get("/pending/pdf")
async def export_pending_pdf(
    request: Request,
    sitting_number: Optional[str] = Query(None, description="Council sitting number")
):
    """Export only pending invoices to PDF (for council meeting review)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT i.*, s.name as supplier_name, s.contact_email as supplier_email
            FROM invoices i
            LEFT JOIN suppliers s ON i.supplier_id = s.id
            WHERE i.is_deleted = 0 AND i.is_approved = 0 AND i.is_void = 0
            ORDER BY i.created_at DESC
        """)
        invoices = wrap_invoices(cursor.fetchall())

        month_year = datetime.now().strftime("%B %Y")
        signatories = resolve_export_signatories(conn)
        buffer = generate_schedule_pdf(invoices, sitting_number, month_year, signatories=signatories)

        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)
        log_export(conn, user_id, "PDF", f"{len(invoices)} invoices (pending only)", ip_address)

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
    request: Request,
    approved_only: bool = Query(False, description="Export only approved invoices"),
    status: Optional[str] = Query(None, description="Filter by status: pending, approved"),
    supplier_id: Optional[str] = Query(None, description="Filter by supplier"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    sitting_number: Optional[str] = Query(None, description="Council sitting number"),
    include_void: bool = Query(False, description="Include voided invoices"),
    sindku: Optional[str] = Query(None, description="Sindku name for signature section"),
    segretarju_ezekuttiv: Optional[str] = Query(None, description="Segretarju Ezekuttiv name for signature section"),
    proponent: Optional[str] = Query(None, description="Proponent name for signature section"),
    sekondant: Optional[str] = Query(None, description="Sekondant name for signature section")
):
    """
    Export invoices to CSV file with optional filters.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        sql = """
            SELECT i.*, s.name as supplier_name, s.contact_email as supplier_email
            FROM invoices i
            LEFT JOIN suppliers s ON i.supplier_id = s.id
            WHERE i.is_deleted = 0
        """
        params = []
        supplier_id_int = None
        if supplier_id:
            try:
                supplier_id_int = int(supplier_id)
            except (ValueError, TypeError):
                pass

        # Apply filters
        if approved_only or status == "approved":
            sql += " AND i.is_approved = 1"
        elif status == "pending":
            sql += " AND i.is_approved = 0"

        if not include_void:
            sql += " AND i.is_void = 0"

        if supplier_id_int:
            sql += " AND i.supplier_id = ?"
            params.append(supplier_id_int)

        if date_from:
            try:
                from_date = datetime.strptime(date_from, "%Y-%m-%d").date()
                sql += " AND i.invoice_date >= ?"
                params.append(from_date.isoformat())
            except ValueError:
                pass

        if date_to:
            try:
                to_date = datetime.strptime(date_to, "%Y-%m-%d").date()
                sql += " AND i.invoice_date <= ?"
                params.append(to_date.isoformat())
            except ValueError:
                pass

        sql += " ORDER BY i.created_at DESC"

        cursor.execute(sql, params)
        invoices = wrap_invoices(cursor.fetchall())

        # Persist any explicitly provided signatory fields so the next PDF/Excel export is pre-filled.
        resolve_export_signatories(
            conn,
            build_signatory_overrides(
                sindku=sindku,
                segretarju_ezekuttiv=segretarju_ezekuttiv,
                proponent=proponent,
                sekondant=sekondant,
            ),
        )

        buffer = generate_schedule_csv(invoices, sitting_number)
        filename = get_export_filename("csv", approved_only)

        # Log the export
        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)
        filter_desc = "approved only" if approved_only else ("pending only" if status == "pending" else "all invoices")
        if date_from or date_to:
            filter_desc += f"; dates {date_from or '...'} to {date_to or '...'}"
        log_export(conn, user_id, "CSV", f"{len(invoices)} invoices ({filter_desc})", ip_address)

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
async def export_selected_csv(request: Request):
    """Export selected invoices to CSV."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])
    signatory_overrides = build_signatory_overrides(
        sindku=data.get("sindku"),
        segretarju_ezekuttiv=data.get("segretarju_ezekuttiv"),
        proponent=data.get("proponent"),
        sekondant=data.get("sekondant"),
    )

    if not invoice_ids:
        return JSONResponse(
            status_code=400,
            content={"error": "No invoices selected"}
        )

    # Validate all IDs are integers
    try:
        invoice_ids = [int(id) for id in invoice_ids]
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid invoice IDs"}
        )

    with get_db() as conn:
        invoices = get_invoices_for_export(conn, invoice_ids=invoice_ids)
        resolve_export_signatories(conn, signatory_overrides)

        buffer = generate_schedule_csv(invoices)

        return StreamingResponse(
            buffer,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=Selected_Invoices_{datetime.now().strftime('%Y%m%d')}.csv"
            }
        )


@router.post("/selected/excel")
async def export_selected_excel(request: Request):
    """Export selected invoices to Excel."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])
    date_from = data.get("date_from")
    date_to = data.get("date_to")
    signatory_overrides = build_signatory_overrides(
        sindku=data.get("sindku"),
        segretarju_ezekuttiv=data.get("segretarju_ezekuttiv"),
        proponent=data.get("proponent"),
        sekondant=data.get("sekondant"),
    )

    if not invoice_ids:
        return JSONResponse(
            status_code=400,
            content={"error": "No invoices selected"}
        )

    # Validate all IDs are integers
    try:
        invoice_ids = [int(id) for id in invoice_ids]
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid invoice IDs"}
        )

    with get_db() as conn:
        invoices = get_invoices_for_export(conn, invoice_ids=invoice_ids)
        signatories = resolve_export_signatories(conn, signatory_overrides)

        if not (date_from or date_to):
            date_from, date_to = infer_period_from_invoices(invoices)
        period_label = build_period_label(date_from, date_to)
        buffer = generate_schedule_excel(invoices, None, period_label, signatories=signatories)

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=Selected_Invoices_{datetime.now().strftime('%Y%m%d')}.xlsx"
            }
        )


@router.post("/selected/pdf")
async def export_selected_pdf(request: Request):
    """Export selected invoices to PDF."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])
    date_from = data.get("date_from")
    date_to = data.get("date_to")
    signatory_overrides = build_signatory_overrides(
        sindku=data.get("sindku"),
        segretarju_ezekuttiv=data.get("segretarju_ezekuttiv"),
        proponent=data.get("proponent"),
        sekondant=data.get("sekondant"),
    )

    if not invoice_ids:
        return JSONResponse(
            status_code=400,
            content={"error": "No invoices selected"}
        )

    # Validate all IDs are integers
    try:
        invoice_ids = [int(id) for id in invoice_ids]
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid invoice IDs"}
        )

    with get_db() as conn:
        invoices = get_invoices_for_export(conn, invoice_ids=invoice_ids)
        signatories = resolve_export_signatories(conn, signatory_overrides)

        if not (date_from or date_to):
            date_from, date_to = infer_period_from_invoices(invoices)
        period_label = build_period_label(date_from, date_to)
        buffer = generate_schedule_pdf(invoices, None, period_label, signatories=signatories)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=Selected_Invoices_{datetime.now().strftime('%Y%m%d')}.pdf"
            }
        )


@router.post("/selected/voucher-pdf")
async def export_selected_voucher_pdf(request: Request):
    """Export selected invoices as payment vouchers (one voucher per page)."""
    data = await request.json()
    invoice_ids = data.get("invoice_ids", [])

    if not invoice_ids:
        return JSONResponse(
            status_code=400,
            content={"error": "No invoices selected"}
        )

    try:
        invoice_ids = [int(id) for id in invoice_ids]
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid invoice IDs"}
        )

    with get_db() as conn:
        invoices = get_invoices_for_export(conn, invoice_ids=invoice_ids, include_void=True)

        if not invoices:
            return JSONResponse(
                status_code=404,
                content={"error": "Selected invoices were not found"}
            )

        buffer = generate_bulk_vouchers_pdf(invoices)
        filename = f"Payment_Vouchers_{datetime.now().strftime('%Y%m%d')}.pdf"

        user_id = get_current_user_id(request)
        ip_address = get_client_ip(request)
        log_export(conn, user_id, "Voucher PDF", f"{len(invoices)} invoices", ip_address)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
