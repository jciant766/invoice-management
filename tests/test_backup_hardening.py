"""
Tests for backup and receipt hardening controls.
"""

import asyncio
import io
import json
import sqlite3
import zipfile
from contextlib import contextmanager

import pytest
from starlette.datastructures import UploadFile

from routes import invoices
from routes.settings import validate_backup_filename
from services import backup_service, receipt_integrity_service


def _create_minimal_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    cursor.execute(
        """
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY,
            supplier_id INTEGER,
            pjv_number TEXT,
            fiscal_receipt_path TEXT,
            is_deleted INTEGER DEFAULT 0
        )
        """
    )
    cursor.execute("INSERT INTO suppliers (id, name) VALUES (1, 'Test Supplier')")
    cursor.execute(
        "INSERT INTO invoices (id, supplier_id, pjv_number, fiscal_receipt_path, is_deleted) VALUES (1, 1, 'PJV-1', '1_a.pdf', 0)"
    )
    conn.commit()
    conn.close()


@pytest.mark.unit
def test_save_fiscal_receipt_file_keeps_old_file_until_db_swap(monkeypatch, tmp_path):
    """Saving a new receipt file should not delete the old file by itself."""
    upload_folder = tmp_path / "fiscal_receipts"
    upload_folder.mkdir(parents=True, exist_ok=True)
    old_file = upload_folder / "1_old.pdf"
    old_file.write_bytes(b"%PDF-1.4\nold-content")

    monkeypatch.setattr(invoices, "UPLOAD_FOLDER", upload_folder)

    upload = UploadFile(filename="replacement.pdf", file=io.BytesIO(b"%PDF-1.4\nnew-content"))
    new_filename = asyncio.run(invoices.save_fiscal_receipt_file(upload, 1))

    assert (upload_folder / new_filename).exists()
    assert old_file.exists(), "Old file should still exist until DB commit and post-commit cleanup"


@pytest.mark.unit
def test_validate_backup_filename_accepts_db_and_zip():
    assert validate_backup_filename("2026-02-26_10-00-00_auto-daily.db")
    assert validate_backup_filename("2026-02-26_10-00-00_auto-daily_full.zip")
    assert not validate_backup_filename("../bad.db")
    assert not validate_backup_filename("bad.exe")


@pytest.mark.integration
def test_create_full_backup_contains_db_and_receipts(monkeypatch, tmp_path):
    db_path = tmp_path / "invoice.db"
    _create_minimal_db(db_path)

    receipt_folder = tmp_path / "uploads" / "fiscal_receipts"
    receipt_folder.mkdir(parents=True, exist_ok=True)
    (receipt_folder / "1_a.pdf").write_bytes(b"%PDF-1.4\nreceipt-a")

    backup_folder = tmp_path / "backups"
    backup_folder.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(backup_service, "DATABASE_FILE", db_path)
    monkeypatch.setattr(backup_service, "RECEIPT_FOLDER", receipt_folder)
    monkeypatch.setattr(backup_service, "BACKUP_FOLDER", backup_folder)
    monkeypatch.setattr(backup_service, "BACKUP_LOG_FILE", backup_folder / "backup_log.txt")
    monkeypatch.setattr(backup_service, "EXTERNAL_BACKUP_FOLDER", None)

    filename = backup_service.create_full_backup("unit-test")
    assert filename is not None
    assert filename.endswith("_full.zip")

    backup_path = backup_folder / filename
    assert backup_path.exists()

    is_valid, _ = backup_service.verify_full_backup(backup_path)
    assert is_valid is True

    with zipfile.ZipFile(backup_path, "r") as zf:
        names = set(zf.namelist())
        assert "database.db" in names
        assert "uploads/fiscal_receipts/1_a.pdf" in names


@pytest.mark.integration
def test_restore_full_backup_restores_db_and_receipts(monkeypatch, tmp_path):
    db_path = tmp_path / "invoice.db"
    _create_minimal_db(db_path)

    receipt_folder = tmp_path / "uploads" / "fiscal_receipts"
    receipt_folder.mkdir(parents=True, exist_ok=True)
    (receipt_folder / "1_a.pdf").write_bytes(b"%PDF-1.4\noriginal")

    backup_folder = tmp_path / "backups"
    backup_folder.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(backup_service, "DATABASE_FILE", db_path)
    monkeypatch.setattr(backup_service, "RECEIPT_FOLDER", receipt_folder)
    monkeypatch.setattr(backup_service, "BACKUP_FOLDER", backup_folder)
    monkeypatch.setattr(backup_service, "BACKUP_LOG_FILE", backup_folder / "backup_log.txt")
    monkeypatch.setattr(backup_service, "EXTERNAL_BACKUP_FOLDER", None)

    full_backup = backup_service.create_full_backup("restore-test")
    assert full_backup is not None

    # Mutate both DB and receipt storage
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE invoices SET fiscal_receipt_path = '2_b.pdf' WHERE id = 1")
    conn.commit()
    conn.close()

    (receipt_folder / "1_a.pdf").unlink()
    (receipt_folder / "2_b.pdf").write_bytes(b"%PDF-1.4\nmutated")

    restored = backup_service.restore_full_backup(full_backup)
    assert restored is True

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT fiscal_receipt_path FROM invoices WHERE id = 1")
    restored_path = cursor.fetchone()[0]
    conn.close()

    assert restored_path == "1_a.pdf"
    assert (receipt_folder / "1_a.pdf").exists()
    assert not (receipt_folder / "2_b.pdf").exists()


@pytest.mark.integration
def test_receipt_integrity_report_detects_missing_orphan_and_checksum(monkeypatch, tmp_path):
    db_path = tmp_path / "integrity.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY,
            pjv_number TEXT,
            fiscal_receipt_path TEXT,
            is_deleted INTEGER DEFAULT 0
        )
        """
    )
    cursor.execute("INSERT INTO invoices (id, pjv_number, fiscal_receipt_path, is_deleted) VALUES (1, 'PJV-1', 'ok.pdf', 0)")
    cursor.execute("INSERT INTO invoices (id, pjv_number, fiscal_receipt_path, is_deleted) VALUES (2, 'PJV-2', 'missing.pdf', 0)")
    cursor.execute("INSERT INTO invoices (id, pjv_number, fiscal_receipt_path, is_deleted) VALUES (3, 'PJV-3', 'deleted.pdf', 1)")
    conn.commit()
    conn.close()

    receipt_folder = tmp_path / "uploads" / "fiscal_receipts"
    receipt_folder.mkdir(parents=True, exist_ok=True)
    ok_file = receipt_folder / "ok.pdf"
    ok_file.write_bytes(b"%PDF-1.4\nok-file")
    (receipt_folder / "orphan.pdf").write_bytes(b"%PDF-1.4\norphan-file")

    backup_folder = tmp_path / "backups"
    report_folder = backup_folder / "receipt_integrity_reports"
    backup_folder.mkdir(parents=True, exist_ok=True)
    report_folder.mkdir(parents=True, exist_ok=True)
    baseline_file = backup_folder / "receipt_integrity_baseline.json"
    baseline_file.write_text(
        json.dumps({"updated_at": "2026-01-01T00:00:00", "checksums": {"ok.pdf": "BAD_CHECKSUM"}}),
        encoding="utf-8"
    )

    @contextmanager
    def fake_get_db():
        c = sqlite3.connect(db_path)
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    monkeypatch.setattr(receipt_integrity_service, "get_db", fake_get_db)
    monkeypatch.setattr(receipt_integrity_service, "RECEIPT_FOLDER", receipt_folder)
    monkeypatch.setattr(receipt_integrity_service, "BACKUP_FOLDER", backup_folder)
    monkeypatch.setattr(receipt_integrity_service, "REPORT_FOLDER", report_folder)
    monkeypatch.setattr(receipt_integrity_service, "BASELINE_FILE", baseline_file)

    report = receipt_integrity_service.run_receipt_integrity_check(update_baseline=False, save_report=False)
    summary = report["summary"]

    assert summary["missing_linked_files"] == 1
    assert summary["orphan_files"] == 1
    assert summary["checksum_mismatches"] == 1
    assert report["missing_linked_files"][0]["receipt_path"] == "missing.pdf"
    assert "orphan.pdf" in report["orphan_files"]
    assert report["checksum_mismatches"][0]["receipt_path"] == "ok.pdf"
