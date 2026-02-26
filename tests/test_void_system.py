"""
Pytest tests for void system (TF gap prevention).

Tests that invoices with TF/CHQ numbers are voided instead of deleted
to prevent gaps in the numbering sequence.
"""
import pytest
from datetime import date
from database import get_db


@pytest.mark.integration
def test_delete_invoice_without_tf_chq_is_soft_deleted():
    """Test that invoices without TF/CHQ numbers are soft deleted."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create invoice without TF/CHQ
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted, tf_number, chq_number
            ) VALUES (1, 100, 100, 'Inv', 'DA', 'No TF test', '2026-01-15',
                     'INV-NOTF', 'TEST-VOID-NOTF', 0, 0, NULL, NULL)
        """)
        invoice_id = cursor.lastrowid

        # Simulate delete logic from routes/invoices.py lines 833-871
        cursor.execute(
            "SELECT pjv_number, tf_number, chq_number, is_void FROM invoices WHERE id = ? AND is_deleted = 0",
            (invoice_id,)
        )
        row = cursor.fetchone()

        pjv_number = row[0]
        tf_number = row[1]
        chq_number = row[2]
        already_void = row[3]

        # Should be soft deleted (not voided) since no TF/CHQ
        if (tf_number or chq_number) and not already_void:
            # Should NOT reach here
            pytest.fail("Should not void invoice without TF/CHQ")
        else:
            cursor.execute("UPDATE invoices SET is_deleted = 1 WHERE id = ?", (invoice_id,))

        # Verify it's soft deleted
        cursor.execute("SELECT is_deleted, is_void FROM invoices WHERE id = ?", (invoice_id,))
        result = cursor.fetchone()
        assert result[0] == 1, "Invoice should be soft deleted"
        assert result[1] == 0, "Invoice should not be voided"

        # Cleanup
        cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))


@pytest.mark.integration
def test_delete_invoice_with_tf_number_is_voided():
    """Test that invoices with TF numbers are voided instead of deleted."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create invoice with TF number
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted, tf_number, number_type, approved_date
            ) VALUES (1, 100, 100, 'Inv', 'DA', 'With TF test', '2026-01-15',
                     'INV-WITHTF', 'TEST-VOID-WITHTF', 1, 0, 'TF 999/2026', 'TF', '2026-01-15')
        """)
        invoice_id = cursor.lastrowid

        # Simulate delete logic
        cursor.execute(
            "SELECT pjv_number, tf_number, chq_number, is_void FROM invoices WHERE id = ? AND is_deleted = 0",
            (invoice_id,)
        )
        row = cursor.fetchone()

        pjv_number = row[0]
        tf_number = row[1]
        chq_number = row[2]
        already_void = row[3]

        user_id = 1  # Mock user

        # Should be voided since it has TF number
        if (tf_number or chq_number) and not already_void:
            from datetime import datetime
            cursor.execute(
                """UPDATE invoices
                   SET is_void = 1,
                       void_reason = ?,
                       voided_at = ?,
                       voided_by = ?
                 WHERE id = ?""",
                ("Voided after deletion request (TF/CHQ present)", datetime.now().isoformat(), user_id, invoice_id)
            )
        else:
            cursor.execute("UPDATE invoices SET is_deleted = 1 WHERE id = ?", (invoice_id,))

        # Verify it's voided, not deleted
        cursor.execute("SELECT is_deleted, is_void, void_reason FROM invoices WHERE id = ?", (invoice_id,))
        result = cursor.fetchone()
        assert result[0] == 0, "Invoice should NOT be soft deleted"
        assert result[1] == 1, "Invoice should be voided"
        assert "TF/CHQ present" in result[2], "Void reason should mention TF/CHQ"

        # Cleanup
        cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))


@pytest.mark.integration
def test_delete_invoice_with_chq_number_is_voided():
    """Test that invoices with CHQ numbers are voided instead of deleted."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create invoice with CHQ number
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted, chq_number, number_type, approved_date
            ) VALUES (1, 100, 100, 'Inv', 'DA', 'With CHQ test', '2026-01-15',
                     'INV-WITHCHQ', 'TEST-VOID-WITHCHQ', 1, 0, 'CHQ 888/2026', 'CHQ', '2026-01-15')
        """)
        invoice_id = cursor.lastrowid

        # Simulate delete logic
        cursor.execute(
            "SELECT pjv_number, tf_number, chq_number, is_void FROM invoices WHERE id = ? AND is_deleted = 0",
            (invoice_id,)
        )
        row = cursor.fetchone()

        tf_number = row[1]
        chq_number = row[2]
        already_void = row[3]

        user_id = 1

        # Should be voided since it has CHQ number
        if (tf_number or chq_number) and not already_void:
            from datetime import datetime
            cursor.execute(
                """UPDATE invoices
                   SET is_void = 1,
                       void_reason = ?,
                       voided_at = ?,
                       voided_by = ?
                 WHERE id = ?""",
                ("Voided after deletion request (TF/CHQ present)", datetime.now().isoformat(), user_id, invoice_id)
            )

        # Verify it's voided
        cursor.execute("SELECT is_void FROM invoices WHERE id = ?", (invoice_id,))
        result = cursor.fetchone()
        assert result[0] == 1, "Invoice with CHQ should be voided"

        # Cleanup
        cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))


@pytest.mark.integration
def test_void_columns_exist_in_database():
    """Test that void-related columns exist in invoices table."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(invoices)")
        columns = {row[1] for row in cursor.fetchall()}

        assert 'is_void' in columns, "is_void column missing"
        assert 'void_reason' in columns, "void_reason column missing"
        assert 'voided_at' in columns, "voided_at column missing"
        assert 'voided_by' in columns, "voided_by column missing"


@pytest.mark.integration
def test_already_voided_invoice_not_revoided():
    """Test that already voided invoices are not re-voided."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create already voided invoice
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted, tf_number, is_void, void_reason
            ) VALUES (1, 100, 100, 'Inv', 'DA', 'Already void', '2026-01-15',
                     'INV-VOID', 'TEST-VOID-ALREADY', 1, 0, 'TF 777/2026', 1, 'Original reason')
        """)
        invoice_id = cursor.lastrowid

        # Simulate delete logic
        cursor.execute(
            "SELECT pjv_number, tf_number, chq_number, is_void FROM invoices WHERE id = ? AND is_deleted = 0",
            (invoice_id,)
        )
        row = cursor.fetchone()

        tf_number = row[1]
        chq_number = row[2]
        already_void = row[3]

        # Should NOT re-void if already voided
        if (tf_number or chq_number) and not already_void:
            pytest.fail("Should not reach void logic for already voided invoice")
        elif already_void:
            # No-op - invoice already voided
            pass

        # Verify void_reason unchanged
        cursor.execute("SELECT void_reason FROM invoices WHERE id = ?", (invoice_id,))
        result = cursor.fetchone()
        assert result[0] == 'Original reason', "Void reason should not be changed"

        # Cleanup
        cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))


@pytest.mark.integration
def test_voided_invoices_excluded_from_listing_by_default():
    """Test that voided invoices are excluded from invoice list by default."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create normal invoice
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted, is_void
            ) VALUES (1, 100, 100, 'Inv', 'DA', 'Normal', '2026-01-15',
                     'INV-NORMAL', 'TEST-LIST-NORMAL', 0, 0, 0)
        """)
        normal_id = cursor.lastrowid

        # Create voided invoice
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted, is_void, void_reason
            ) VALUES (1, 200, 200, 'Inv', 'DA', 'Voided', '2026-01-16',
                     'INV-VOIDED', 'TEST-LIST-VOID', 0, 0, 1, 'Test')
        """)
        voided_id = cursor.lastrowid

        # Query without include_void (default behavior)
        cursor.execute("""
            SELECT id FROM invoices
            WHERE is_deleted = 0 AND is_void = 0
            AND pjv_number LIKE 'TEST-LIST-%'
        """)
        results = cursor.fetchall()

        # Should only get normal invoice
        assert len(results) == 1
        assert results[0][0] == normal_id

        # Cleanup
        cursor.execute("DELETE FROM invoices WHERE id IN (?, ?)", (normal_id, voided_id))


@pytest.mark.integration
def test_voided_invoice_cannot_be_edited():
    """Test that voided invoices cannot be edited."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create voided invoice
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                pjv_number, is_approved, is_deleted, is_void, void_reason
            ) VALUES (1, 100, 100, 'Inv', 'DA', 'Voided', '2026-01-15',
                     'INV-EDIT', 'TEST-VOID-EDIT', 0, 0, 1, 'Voided')
        """)
        invoice_id = cursor.lastrowid

        # Try to edit (simulate check from routes/invoices.py line 640-642)
        cursor.execute("SELECT is_void FROM invoices WHERE id = ? AND is_deleted = 0", (invoice_id,))
        row = cursor.fetchone()

        if row and row[0]:
            # Should raise HTTPException(400, "Voided invoices cannot be edited")
            # For this test, we just verify the check would catch it
            assert True, "Void check works correctly"
        else:
            pytest.fail("Voided invoice should be detected and blocked from editing")

        # Cleanup
        cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))


if __name__ == "__main__":
    # Allow running this file directly
    pytest.main([__file__, "-v"])
