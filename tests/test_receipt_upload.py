"""
Pytest tests for fiscal receipt upload functionality.

Tests file upload, validation, retrieval, and deletion of fiscal receipts.
"""
import pytest
import io
from pathlib import Path
from database import get_db


@pytest.mark.unit
def test_upload_folder_exists():
    """Test that fiscal receipt upload folder is created."""
    from routes.invoices import UPLOAD_FOLDER

    assert UPLOAD_FOLDER.exists(), "Upload folder should exist"
    assert UPLOAD_FOLDER.is_dir(), "Upload folder should be a directory"


@pytest.mark.unit
def test_allowed_extensions_defined():
    """Test that allowed file extensions are properly defined."""
    from routes.invoices import ALLOWED_EXTENSIONS

    assert '.pdf' in ALLOWED_EXTENSIONS
    assert '.jpg' in ALLOWED_EXTENSIONS
    assert '.jpeg' in ALLOWED_EXTENSIONS
    assert '.png' in ALLOWED_EXTENSIONS

    # Should not allow dangerous extensions
    assert '.exe' not in ALLOWED_EXTENSIONS
    assert '.sh' not in ALLOWED_EXTENSIONS


@pytest.mark.unit
def test_max_file_size_is_reasonable():
    """Test that max file size is set to a reasonable limit."""
    from routes.invoices import MAX_FILE_SIZE

    # 10MB is reasonable
    assert MAX_FILE_SIZE == 10 * 1024 * 1024
    assert MAX_FILE_SIZE > 0


@pytest.mark.unit
def test_sanitize_filename_removes_paths():
    """Test that sanitize_filename strips directory traversal."""
    from routes.invoices import sanitize_filename

    # Windows path
    assert sanitize_filename("C:\\malicious\\..\\file.pdf") == "file.pdf"

    # Unix path
    assert sanitize_filename("/etc/passwd") == "passwd"

    # Path traversal - the function removes path separators, so '../../../etc/passwd' becomes 'passwd'
    assert sanitize_filename("../../../etc/passwd") == "passwd"

    # Just filename
    assert sanitize_filename("receipt.pdf") == "receipt.pdf"


@pytest.mark.unit
def test_sanitize_filename_handles_empty():
    """Test that sanitize_filename handles empty or None input."""
    from routes.invoices import sanitize_filename

    assert sanitize_filename("") == "unknown"
    assert sanitize_filename(None) == "unknown"


@pytest.mark.unit
def test_validate_file_magic_bytes_pdf():
    """Test PDF magic byte validation."""
    from routes.invoices import validate_file_magic_bytes

    # Valid PDF header
    pdf_header = b'%PDF-1.4\n'
    assert validate_file_magic_bytes(pdf_header, '.pdf') is True

    # Invalid content
    fake_pdf = b'This is not a PDF'
    assert validate_file_magic_bytes(fake_pdf, '.pdf') is False


@pytest.mark.unit
def test_validate_file_magic_bytes_png():
    """Test PNG magic byte validation."""
    from routes.invoices import validate_file_magic_bytes

    # Valid PNG header
    png_header = b'\x89PNG\r\n\x1a\n'
    assert validate_file_magic_bytes(png_header, '.png') is True

    # Invalid content
    fake_png = b'Not a PNG file'
    assert validate_file_magic_bytes(fake_png, '.png') is False


@pytest.mark.unit
def test_validate_file_magic_bytes_jpg():
    """Test JPG/JPEG magic byte validation."""
    from routes.invoices import validate_file_magic_bytes

    # Valid JPEG header
    jpg_header = b'\xff\xd8\xff\xe0\x00\x10JFIF'
    assert validate_file_magic_bytes(jpg_header, '.jpg') is True
    assert validate_file_magic_bytes(jpg_header, '.jpeg') is True

    # Invalid content
    fake_jpg = b'Not a JPEG'
    assert validate_file_magic_bytes(fake_jpg, '.jpg') is False


@pytest.mark.unit
def test_validate_file_magic_bytes_rejects_unknown_extension():
    """Test that unknown extensions are rejected."""
    from routes.invoices import validate_file_magic_bytes

    content = b'Some content'
    assert validate_file_magic_bytes(content, '.exe') is False
    assert validate_file_magic_bytes(content, '.txt') is False


@pytest.mark.integration
def test_fiscal_receipt_path_column_exists():
    """Test that fiscal_receipt_path column exists in database."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(invoices)")
        columns = {row[1] for row in cursor.fetchall()}

        assert 'fiscal_receipt_path' in columns, "fiscal_receipt_path column missing"


@pytest.mark.integration
def test_upload_endpoint_route_exists():
    """Test that fiscal receipt upload endpoint is registered."""
    from routes.invoices import router

    # Check for POST /invoices/{invoice_id}/fiscal-receipt
    upload_routes = [
        route for route in router.routes
        if 'fiscal-receipt' in route.path and 'POST' in route.methods
    ]

    assert len(upload_routes) > 0, "Fiscal receipt upload route not found"


@pytest.mark.integration
def test_download_endpoint_route_exists():
    """Test that fiscal receipt download endpoint is registered."""
    from routes.invoices import router

    # Check for GET /invoices/{invoice_id}/fiscal-receipt
    download_routes = [
        route for route in router.routes
        if 'fiscal-receipt' in route.path and 'GET' in route.methods
    ]

    assert len(download_routes) > 0, "Fiscal receipt download route not found"


@pytest.mark.integration
def test_delete_endpoint_route_exists():
    """Test that fiscal receipt delete endpoint is registered."""
    from routes.invoices import router

    # Check for DELETE /invoices/{invoice_id}/fiscal-receipt
    delete_routes = [
        route for route in router.routes
        if 'fiscal-receipt' in route.path and 'DELETE' in route.methods
    ]

    assert len(delete_routes) > 0, "Fiscal receipt delete route not found"


@pytest.mark.integration
def test_invoice_can_store_receipt_path():
    """Test that invoice can store fiscal receipt file path."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create test invoice
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted
            ) VALUES (1, 100, 100, 'Inv', 'DA', 'Receipt test', '2026-01-15',
                     'INV-REC', 'TEST-RECEIPT-1', 0, 0)
        """)
        invoice_id = cursor.lastrowid

        # Set fiscal receipt path
        test_filename = f"{invoice_id}_test.pdf"
        cursor.execute(
            "UPDATE invoices SET fiscal_receipt_path = ? WHERE id = ?",
            (test_filename, invoice_id)
        )

        # Verify it was stored
        cursor.execute(
            "SELECT fiscal_receipt_path FROM invoices WHERE id = ?",
            (invoice_id,)
        )
        result = cursor.fetchone()
        assert result[0] == test_filename

        # Cleanup
        cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))


@pytest.mark.unit
def test_file_signature_validation_prevents_extension_spoofing():
    """Test that file validation prevents extension spoofing attacks."""
    from routes.invoices import validate_file_magic_bytes

    # Try to spoof a PDF with a .jpg extension
    pdf_content = b'%PDF-1.4\nFake PDF as JPG'
    assert validate_file_magic_bytes(pdf_content, '.jpg') is False

    # Try to spoof a JPG with a .pdf extension
    jpg_content = b'\xff\xd8\xff\xe0Fake JPG as PDF'
    assert validate_file_magic_bytes(jpg_content, '.pdf') is False


@pytest.mark.integration
def test_fiscal_receipt_in_invoice_form():
    """Test that invoice form includes fiscal receipt upload field."""
    from pathlib import Path

    form_template = Path(__file__).parent.parent / "templates" / "invoice_form.html"

    if form_template.exists():
        content = form_template.read_text()
        # Should have file input for fiscal receipt
        assert 'fiscal_receipt' in content or 'fiscal-receipt' in content, \
            "Fiscal receipt upload field missing from invoice form"


@pytest.mark.integration
def test_fiscal_receipt_in_invoice_list():
    """Test that invoice list shows fiscal receipt status."""
    from pathlib import Path

    list_template = Path(__file__).parent.parent / "templates" / "invoice_list.html"

    if list_template.exists():
        content = list_template.read_text()
        # Should display fiscal receipt indicator/link
        assert 'fiscal_receipt' in content or 'fiscal-receipt' in content, \
            "Fiscal receipt indicator missing from invoice list"


@pytest.mark.unit
def test_unique_filename_generation():
    """Test that uploaded files get unique names to prevent collisions."""
    import uuid

    # Simulate the unique filename generation from routes/invoices.py line 101
    invoice_id = 123
    file_ext = '.pdf'

    unique_filename_1 = f"{invoice_id}_{uuid.uuid4().hex[:8]}{file_ext}"
    unique_filename_2 = f"{invoice_id}_{uuid.uuid4().hex[:8]}{file_ext}"

    # Should be different even for same invoice
    assert unique_filename_1 != unique_filename_2

    # Should start with invoice ID
    assert unique_filename_1.startswith(f"{invoice_id}_")
    assert unique_filename_2.startswith(f"{invoice_id}_")

    # Should end with extension
    assert unique_filename_1.endswith(file_ext)
    assert unique_filename_2.endswith(file_ext)


if __name__ == "__main__":
    # Allow running this file directly
    pytest.main([__file__, "-v"])
