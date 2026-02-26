"""
Supplier Routes

Handles supplier management:
- List suppliers with search and filtering
- Add, edit, delete suppliers
- Merge suppliers
"""

import unicodedata
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from database import get_db
from services.backup_service import backup_before_dangerous_operation
from services.audit_service import log_action
from routes.helpers import build_pagination
from shared_templates import templates
from middleware import get_current_user

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def normalize_name(name: str) -> str:
    """Normalize Unicode to NFC form to prevent duplicate entries with different encodings."""
    return unicodedata.normalize('NFC', name.strip())


@router.get("", response_class=HTMLResponse)
async def suppliers_page(
    request: Request,
    q: Optional[str] = Query(None, description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=10, le=100, description="Items per page"),
    error: Optional[str] = Query(None, description="Error message to display")
):
    """Display suppliers list page with pagination."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Build query with invoice count, total spend, and last invoice date
        sql = """
            SELECT s.*,
                   COUNT(i.id) as invoice_count,
                   COALESCE(SUM(i.invoice_amount), 0) as total_spend,
                   MAX(i.invoice_date) as last_invoice_date
            FROM suppliers s
            LEFT JOIN invoices i ON i.supplier_id = s.id AND i.is_deleted = 0
        """
        params = []

        # Search filter
        if q:
            sql += " WHERE (s.name LIKE ? OR s.contact_email LIKE ? OR s.contact_phone LIKE ? OR s.vat_number LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])

        sql += " GROUP BY s.id ORDER BY s.name"

        count_sql = f"SELECT COUNT(*) FROM ({sql})"
        cursor.execute(count_sql, params)
        total_count = cursor.fetchone()[0]
        pagination = build_pagination(page, per_page, total_count)

        sql += " LIMIT ? OFFSET ?"
        params.extend([per_page, pagination['offset']])

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        # Convert to list of tuples (supplier_dict, invoice_count) for template
        suppliers = []
        for row in rows:
            d = dict(row)
            inv_count = d.pop('invoice_count', 0)
            spend = d.pop('total_spend', 0)
            last_date = d.pop('last_invoice_date', None)

            class SupplierWrapper:
                def __init__(self, data, count, spend, last_date):
                    self.id = data['id']
                    self.name = data['name']
                    self.contact_email = data.get('contact_email')
                    self.phone = data.get('contact_phone')
                    self.vat_number = data.get('vat_number')
                    self.address = data.get('address')
                    self.notes = data.get('notes')
                    self.is_active = data.get('is_active', 1)
                    self.created_at = data.get('created_at')
                    self.invoice_count = count
                    self.total_spend = spend
                    self.last_invoice_date = last_date
            suppliers.append((SupplierWrapper(d, inv_count, spend, last_date), inv_count))

        cursor.execute("SELECT COUNT(*) FROM suppliers")
        total_suppliers = cursor.fetchone()[0]

        return templates.TemplateResponse(
            "suppliers.html",
            {
                "request": request,
                "suppliers": suppliers,
                "search_query": q,
                "error": error,
                "stats": {"total": total_suppliers},
                "pagination": pagination
            }
        )


@router.post("/add")
async def add_supplier(
    request: Request,
    name: str = Form(...),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    vat_number: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    notes: Optional[str] = Form(None)
):
    """Add a new supplier."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    name = normalize_name(name)
    if not name:
        return RedirectResponse(url=f"/suppliers?error={quote('Supplier name is required')}", status_code=303)
    if len(name) > 200:
        return RedirectResponse(url=f"/suppliers?error={quote('Supplier name too long (max 200 characters)')}", status_code=303)

    with get_db() as conn:
        cursor = conn.cursor()

        # Check for duplicate (case-insensitive)
        cursor.execute("SELECT id FROM suppliers WHERE LOWER(name) = LOWER(?)", (name,))
        if cursor.fetchone():
            return RedirectResponse(url=f"/suppliers?error={quote('A supplier with this name already exists')}", status_code=303)

        # Insert new supplier
        cursor.execute(
            """INSERT INTO suppliers (name, contact_email, contact_phone, vat_number, address, notes, is_active)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (
                name,
                email.strip() if email else None,
                phone.strip() if phone else None,
                vat_number.strip() if vat_number else None,
                address.strip() if address else None,
                notes.strip() if notes else None
            )
        )

        new_id = cursor.lastrowid
        log_action(conn, user.id, "supplier_add", "supplier", new_id, f"Added supplier '{name}'")

        return RedirectResponse(url="/suppliers", status_code=303)


@router.post("/{supplier_id}/edit")
async def edit_supplier(
    request: Request,
    supplier_id: int,
    name: str = Form(...),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    vat_number: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    notes: Optional[str] = Form(None)
):
    """Edit supplier."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    name = normalize_name(name)
    if not name:
        return RedirectResponse(url=f"/suppliers?error={quote('Supplier name is required')}", status_code=303)
    if len(name) > 200:
        return RedirectResponse(url=f"/suppliers?error={quote('Supplier name too long (max 200 characters)')}", status_code=303)

    with get_db() as conn:
        cursor = conn.cursor()

        # Check if supplier exists
        cursor.execute("SELECT id FROM suppliers WHERE id = ?", (supplier_id,))
        if not cursor.fetchone():
            return RedirectResponse(url=f"/suppliers?error={quote('Supplier not found')}", status_code=303)

        # Check for duplicate (excluding current)
        cursor.execute(
            "SELECT id FROM suppliers WHERE LOWER(name) = LOWER(?) AND id != ?",
            (name, supplier_id)
        )
        if cursor.fetchone():
            return RedirectResponse(url=f"/suppliers?error={quote('Another supplier with this name already exists')}", status_code=303)

        # Update supplier
        cursor.execute(
            """UPDATE suppliers SET name = ?, contact_email = ?, contact_phone = ?,
               vat_number = ?, address = ?, notes = ? WHERE id = ?""",
            (
                name,
                email.strip() if email else None,
                phone.strip() if phone else None,
                vat_number.strip() if vat_number else None,
                address.strip() if address else None,
                notes.strip() if notes else None,
                supplier_id
            )
        )

        log_action(conn, user.id, "supplier_edit", "supplier", supplier_id, f"Edited supplier '{name}'")

        return RedirectResponse(url="/suppliers", status_code=303)


@router.post("/{supplier_id}/delete")
async def delete_supplier(request: Request, supplier_id: int):
    """Delete a supplier (only if no invoices)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if supplier exists
        cursor.execute("SELECT id, name FROM suppliers WHERE id = ?", (supplier_id,))
        supplier = cursor.fetchone()
        if not supplier:
            return RedirectResponse(url=f"/suppliers?error={quote('Supplier not found')}", status_code=303)

        # Check for invoices
        cursor.execute(
            "SELECT COUNT(*) FROM invoices WHERE supplier_id = ? AND is_deleted = 0",
            (supplier_id,)
        )
        invoice_count = cursor.fetchone()[0]

        if invoice_count > 0:
            msg = f"Cannot delete {supplier['name']} - it has {invoice_count} invoice{'s' if invoice_count != 1 else ''}. Use merge instead."
            return RedirectResponse(url=f"/suppliers?error={quote(msg)}", status_code=303)

        # Delete supplier
        cursor.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))

        log_action(conn, user.id, "supplier_delete", "supplier", supplier_id, f"Deleted supplier '{supplier['name']}'")

        return RedirectResponse(url="/suppliers", status_code=303)


@router.post("/bulk-delete")
async def bulk_delete_suppliers(request: Request, supplier_ids: str = Form(...)):
    """Delete multiple suppliers (only those with no invoices)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not supplier_ids:
        return RedirectResponse(url=f"/suppliers?error={quote('No suppliers selected')}", status_code=303)

    # Create backup before bulk delete (safety measure)
    backup_before_dangerous_operation("bulk-delete-suppliers")

    try:
        ids = [int(id.strip()) for id in supplier_ids.split(",") if id.strip()]
    except ValueError:
        return RedirectResponse(url=f"/suppliers?error={quote('Invalid supplier IDs')}", status_code=303)
    if not ids:
        return RedirectResponse(url=f"/suppliers?error={quote('No valid supplier IDs')}", status_code=303)

    with get_db() as conn:
        cursor = conn.cursor()
        deleted = 0
        skipped = []

        for supplier_id in ids:
            # Check if supplier exists
            cursor.execute("SELECT name FROM suppliers WHERE id = ?", (supplier_id,))
            supplier = cursor.fetchone()
            if not supplier:
                continue

            # Check for invoices
            cursor.execute(
                "SELECT COUNT(*) FROM invoices WHERE supplier_id = ? AND is_deleted = 0",
                (supplier_id,)
            )
            invoice_count = cursor.fetchone()[0]

            if invoice_count > 0:
                skipped.append(supplier[0])
            else:
                cursor.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
                deleted += 1
                log_action(conn, user.id, "supplier_delete", "supplier", supplier_id, f"Bulk deleted supplier '{supplier['name']}'")

        return RedirectResponse(url="/suppliers", status_code=303)


@router.post("/merge")
async def merge_suppliers(
    request: Request,
    source_id: int = Form(...),
    target_id: int = Form(...)
):
    """Merge one supplier into another (reassign all invoices)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if source_id == target_id:
        return RedirectResponse(url=f"/suppliers?error={quote('Cannot merge a supplier with itself')}", status_code=303)

    # Create backup before merge (safety measure)
    backup_before_dangerous_operation("merge-suppliers")

    with get_db() as conn:
        cursor = conn.cursor()

        # Check source exists
        cursor.execute("SELECT id, name, is_active FROM suppliers WHERE id = ?", (source_id,))
        source = cursor.fetchone()
        if not source:
            return RedirectResponse(url=f"/suppliers?error={quote('Source supplier not found')}", status_code=303)

        # Check target exists
        cursor.execute("SELECT id, name, is_active FROM suppliers WHERE id = ?", (target_id,))
        target = cursor.fetchone()
        if not target:
            return RedirectResponse(url=f"/suppliers?error={quote('Target supplier not found')}", status_code=303)

        if target["is_active"] == 0:
            return RedirectResponse(url=f"/suppliers?error={quote('Target supplier is inactive. Reactivate first.')}", status_code=303)

        # Reassign all invoices from source to target
        cursor.execute(
            "UPDATE invoices SET supplier_id = ? WHERE supplier_id = ?",
            (target_id, source_id)
        )

        # Delete source supplier
        cursor.execute("DELETE FROM suppliers WHERE id = ?", (source_id,))

        # Audit log
        log_action(conn, user.id, "supplier_merge", "supplier", target_id, f"Merged supplier {source['name']} (id {source_id}) into {target['name']} (id {target_id})")

        return RedirectResponse(url="/suppliers", status_code=303)


# API endpoint for AJAX
@router.get("/api/list")
async def get_suppliers_json(request: Request, q: Optional[str] = Query(None, description="Search query")):
    """Get suppliers list as JSON (for autocomplete)."""
    user = get_current_user(request)
    if not user:
        return {"error": "Not authenticated"}
    with get_db() as conn:
        cursor = conn.cursor()

        sql = "SELECT id, name, contact_email, contact_phone, vat_number FROM suppliers"
        params = []

        if q:
            sql += " WHERE name LIKE ? OR contact_email LIKE ? OR vat_number LIKE ?"
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

        sql += " ORDER BY name"

        cursor.execute(sql, params)
        suppliers = [
            {
                "id": row["id"],
                "name": row["name"],
                "email": row["contact_email"],
                "phone": row["contact_phone"],
                "vat_number": row["vat_number"]
            }
            for row in cursor.fetchall()
        ]

        return suppliers


@router.get("/api/check-similar")
async def check_similar_suppliers(
    request: Request,
    name: str = Query(..., min_length=2, description="Supplier name to check"),
    exclude_id: Optional[int] = Query(None, description="Supplier ID to exclude (for edit mode)")
):
    """Check for similar existing suppliers using fuzzy matching."""
    user = get_current_user(request)
    if not user:
        return {"error": "Not authenticated"}
    from services.supplier_matching import find_supplier_matches

    with get_db() as conn:
        cursor = conn.cursor()
        sql = "SELECT id, name FROM suppliers WHERE is_active = 1"
        params = []

        if exclude_id:
            sql += " AND id != ?"
            params.append(exclude_id)

        cursor.execute(sql, params)
        existing_suppliers = [
            {"id": row["id"], "name": row["name"]}
            for row in cursor.fetchall()
        ]

        match_result = find_supplier_matches(
            extracted_name=name,
            existing_suppliers=existing_suppliers,
            top_k=5,
            auto_select_threshold=0.90
        )

        # Filter to Medium+ confidence (>= 0.60)
        similar = [
            m for m in match_result["matches"]
            if m["confidence"] >= 0.60
        ]

        return {"similar": similar, "query": name}
