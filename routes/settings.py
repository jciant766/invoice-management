"""
Settings Routes

Handles system settings:
- TF number counter management (year-based: N/YYYY)
- CHQ number counter management (year-based: N/YYYY)
- Database backup
Note: PJV is manual input (no structure/counter)
"""

import os
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from io import BytesIO
from datetime import datetime

from database import get_db, get_encryption_status
from services.number_service import get_current_counts, preview_next_number, update_counter
from services.backup_service import (
    create_full_backup, restore_backup, restore_full_backup, list_backups, delete_backup, get_backup_stats, BACKUP_FOLDER
)
from routes.helpers import check_admin
from shared_templates import templates

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Display settings page (admin only)."""
    check_admin(request)
    with get_db() as conn:
        cursor = conn.cursor()

        # Get TF and CHQ number info (year-based: N/YYYY)
        current_year = datetime.now().year
        number_counts = get_current_counts(conn, current_year)

        current_tf = number_counts['TF']
        next_tf = preview_next_number(conn, 'TF', current_year)

        current_chq = number_counts['CHQ']
        next_chq = preview_next_number(conn, 'CHQ', current_year)

        # Stats
        cursor.execute("SELECT COUNT(*) FROM invoices WHERE is_deleted = 0")
        total_invoices = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM invoices WHERE is_deleted = 0 AND is_approved = 0")
        pending_invoices = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM invoices WHERE is_deleted = 0 AND is_approved = 1")
        approved_invoices = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM suppliers")
        total_suppliers = cursor.fetchone()[0]

        # Get backup info
        backups = list_backups()
        backup_stats = get_backup_stats()

        # Get encryption status
        encryption_status = get_encryption_status()

        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "current_tf_number": current_tf,
                "next_tf_number": next_tf,
                "current_chq_number": current_chq,
                "next_chq_number": next_chq,
                "current_year": current_year,
                "stats": {
                    "total_invoices": total_invoices,
                    "pending_invoices": pending_invoices,
                    "approved_invoices": approved_invoices,
                    "total_suppliers": total_suppliers
                },
                "backups": backups,
                "backup_stats": backup_stats,
                "encryption": encryption_status
            }
        )


@router.post("/tf-number")
async def update_tf_number(request: Request, new_tf_number: int = Form(...)):
    """Update TF number counter (admin only) for current year."""
    check_admin(request)
    if new_tf_number < 0:
        raise HTTPException(status_code=400, detail="TF number cannot be negative")

    with get_db() as conn:
        current_year = datetime.now().year

        # Get current max TF number for this year
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tf_number FROM invoices
            WHERE tf_number IS NOT NULL AND tf_number LIKE ? AND is_deleted = 0
            ORDER BY tf_number DESC LIMIT 1
        """, (f"%/{current_year}",))
        max_tf_row = cursor.fetchone()

        if max_tf_row and max_tf_row[0]:
            # Extract number from TF string (e.g., "5/2026" -> 5)
            try:
                # Format is "N/YYYY"
                max_used = int(max_tf_row[0].split("/")[0])
                if new_tf_number < max_used:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot set TF counter below {max_used} (already in use for {current_year})"
                    )
            except ValueError:
                pass

        update_counter(conn, 'TF', new_tf_number, current_year)

        return RedirectResponse(url="/settings", status_code=303)


@router.post("/chq-number")
async def update_chq_number(request: Request, new_chq_number: int = Form(...)):
    """Update CHQ number counter (admin only) for current year."""
    check_admin(request)
    if new_chq_number < 0:
        raise HTTPException(status_code=400, detail="CHQ number cannot be negative")

    with get_db() as conn:
        current_year = datetime.now().year

        # Get current max CHQ number for this year
        cursor = conn.cursor()
        cursor.execute("""
            SELECT chq_number FROM invoices
            WHERE chq_number IS NOT NULL AND chq_number LIKE ? AND is_deleted = 0
            ORDER BY chq_number DESC LIMIT 1
        """, (f"CHQ %/{current_year}",))
        max_chq_row = cursor.fetchone()

        if max_chq_row and max_chq_row[0]:
            # Extract number from CHQ string (e.g., "CHQ 5/2026" -> 5)
            try:
                # Format is "CHQ N/YYYY"
                max_used = int(max_chq_row[0].replace("CHQ ", "").split("/")[0])
                if new_chq_number < max_used:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot set CHQ counter below {max_used} (already in use for {current_year})"
                    )
            except ValueError:
                pass

        update_counter(conn, 'CHQ', new_chq_number, current_year)

        return RedirectResponse(url="/settings", status_code=303)


# Note: PJV numbers are manual input - no counter management needed
# (PJV numbers are entered by users, not auto-generated like TF/CHQ)


# Database Backup

@router.get("/backup")
async def backup_database(request: Request):
    """Download database backup (admin only)."""
    check_admin(request)
    from database import DATABASE_PATH

    db_path = DATABASE_PATH

    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail=f"Database not found at {db_path}")

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


# ============================================
# BACKUP MANAGEMENT
# ============================================

@router.post("/backup/create")
async def create_backup_route(request: Request):
    """Create a new backup (admin only)."""
    check_admin(request)
    filename = create_full_backup("manual")
    if filename:
        return RedirectResponse(url="/settings?backup_success=created", status_code=303)
    else:
        raise HTTPException(status_code=500, detail="Failed to create backup")


def validate_backup_filename(filename: str) -> bool:
    """Validate backup filename to prevent path traversal attacks."""
    import re
    # Allow alphanumeric, underscore, hyphen, and backup extensions (.db/.zip)
    if not re.match(r'^[\w\-]+\.(db|zip)$', filename):
        return False
    # Ensure no path separators
    if '/' in filename or '\\' in filename or '..' in filename:
        return False
    return True


@router.post("/backup/{filename}/restore")
async def restore_backup_route(request: Request, filename: str):
    """Restore database from a backup (admin only)."""
    check_admin(request)
    if not validate_backup_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if filename.lower().endswith(".zip"):
        success = restore_full_backup(filename)
    else:
        success = restore_backup(filename)
    if success:
        return RedirectResponse(url="/settings?backup_success=restored", status_code=303)
    else:
        raise HTTPException(status_code=500, detail="Failed to restore backup")


@router.post("/backup/{filename}/delete")
async def delete_backup_route(request: Request, filename: str):
    """Delete a backup file (admin only)."""
    check_admin(request)
    if not validate_backup_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    success = delete_backup(filename)
    if success:
        return RedirectResponse(url="/settings?backup_success=deleted", status_code=303)
    else:
        raise HTTPException(status_code=404, detail="Backup not found")


@router.get("/backup/{filename}/download")
async def download_specific_backup(request: Request, filename: str):
    """Download a specific backup file (admin only)."""
    check_admin(request)

    if not validate_backup_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    backup_dir = BACKUP_FOLDER.resolve()
    backup_path = (backup_dir / filename).resolve()

    # Ensure the resolved path is still within the backups directory
    if not str(backup_path).startswith(str(backup_dir)):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")

    with open(backup_path, 'rb') as f:
        db_bytes = f.read()

    buffer = BytesIO(db_bytes)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )
