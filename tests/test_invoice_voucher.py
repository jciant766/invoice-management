"""
Pytest tests for invoice voucher/print view functionality.

Tests the GET /invoices/{invoice_id}/voucher endpoint.
"""
import pytest
from database import get_db


@pytest.mark.integration
def test_voucher_endpoint_exists():
    """Test that voucher endpoint is registered in router."""
    from routes.invoices import router

    # Check that the voucher route exists
    voucher_routes = [route for route in router.routes if 'voucher' in route.path]
    assert len(voucher_routes) > 0, "Voucher route not found in router"


@pytest.mark.integration
def test_voucher_template_exists():
    """Test that invoice_voucher.html template exists."""
    from pathlib import Path

    template_path = Path(__file__).parent.parent / "templates" / "invoice_voucher.html"
    assert template_path.exists(), "invoice_voucher.html template not found"


@pytest.mark.integration
def test_voucher_displays_required_fields():
    """Test that voucher template includes all required fields."""
    from pathlib import Path

    template_path = Path(__file__).parent.parent / "templates" / "invoice_voucher.html"
    content = template_path.read_text()

    # Check for essential fields
    required_fields = [
        'supplier_name',
        'invoice_date',
        'pjv_number',
        'tf_number',
        'invoice_number',
        'description',
        'invoice_amount',
        'payment_amount'
    ]

    for field in required_fields:
        assert field in content, f"Field '{field}' not found in voucher template"


@pytest.mark.integration
def test_voucher_has_print_functionality():
    """Test that voucher template includes print button and print styles."""
    from pathlib import Path

    template_path = Path(__file__).parent.parent / "templates" / "invoice_voucher.html"
    content = template_path.read_text()

    # Should have window.print() for printing
    assert 'window.print()' in content, "Print functionality missing"

    # Should have print-specific CSS classes
    assert 'print:' in content, "Print-specific styles missing"


@pytest.mark.integration
def test_voucher_returns_404_for_nonexistent_invoice():
    """Test that voucher endpoint returns 404 for non-existent invoice."""
    from routes.invoices import invoice_voucher
    from fastapi import HTTPException
    from unittest.mock import Mock

    # Create a mock request
    request = Mock()
    request.state = Mock()

    # Test with a very high invoice ID that won't exist
    with pytest.raises(HTTPException) as exc_info:
        import asyncio
        asyncio.run(invoice_voucher(request, 999999999))

    assert exc_info.value.status_code == 404


@pytest.mark.integration
def test_voucher_returns_404_for_deleted_invoice():
    """Test that voucher returns 404 for deleted invoices."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create and delete a test invoice
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted
            ) VALUES (1, 100, 100, 'Inv', 'DA', 'Deleted test', '2026-01-15',
                     'INV-DEL', 'TEST-VOUCHER-DEL', 0, 1)
        """)
        deleted_id = cursor.lastrowid

        # Try to get voucher for deleted invoice
        from routes.invoices import invoice_voucher
        from fastapi import HTTPException
        from unittest.mock import Mock

        request = Mock()
        request.state = Mock()

        with pytest.raises(HTTPException) as exc_info:
            import asyncio
            asyncio.run(invoice_voucher(request, deleted_id))

        assert exc_info.value.status_code == 404

        # Cleanup (though it's already marked deleted)
        cursor.execute("DELETE FROM invoices WHERE id = ?", (deleted_id,))


@pytest.mark.integration
def test_voucher_includes_supplier_name():
    """Test that voucher properly joins supplier data."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Get or create a test supplier
        cursor.execute("SELECT id, name FROM suppliers LIMIT 1")
        supplier = cursor.fetchone()

        if not supplier:
            cursor.execute("INSERT INTO suppliers (name) VALUES ('Test Supplier Voucher')")
            supplier_id = cursor.lastrowid
            supplier_name = 'Test Supplier Voucher'
        else:
            supplier_id = supplier[0]
            supplier_name = supplier[1]

        # Create test invoice
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted
            ) VALUES (?, 100, 100, 'Inv', 'DA', 'Voucher test', '2026-01-15',
                     'INV-VOU', 'TEST-VOUCHER-SUP', 0, 0)
        """, (supplier_id,))
        invoice_id = cursor.lastrowid

        # Get the invoice via the voucher query
        cursor.execute("""
            SELECT i.*, s.name as supplier_name
            FROM invoices i
            LEFT JOIN suppliers s ON s.id = i.supplier_id
            WHERE i.id = ? AND i.is_deleted = 0
        """, (invoice_id,))

        result = cursor.fetchone()
        assert result is not None, "Invoice not found"
        assert result['supplier_name'] == supplier_name, "Supplier name not joined correctly"

        # Cleanup
        cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))


@pytest.mark.unit
def test_voucher_route_path():
    """Test that voucher route has correct path pattern."""
    from routes.invoices import router

    # Find the voucher route
    voucher_route = None
    for route in router.routes:
        if 'voucher' in route.path:
            voucher_route = route
            break

    assert voucher_route is not None, "Voucher route not found"
    assert '{invoice_id}' in voucher_route.path, "Route should include invoice_id parameter"


@pytest.mark.unit
def test_voucher_formats_currency():
    """Test that voucher template formats currency correctly."""
    from pathlib import Path

    template_path = Path(__file__).parent.parent / "templates" / "invoice_voucher.html"
    content = template_path.read_text()

    # Should format currency with euro symbol and 2 decimal places
    assert '&euro;' in content or '€' in content, "Euro symbol missing"
    assert ',.2f' in content, "Currency formatting to 2 decimal places missing"


if __name__ == "__main__":
    # Allow running this file directly
    pytest.main([__file__, "-v"])
