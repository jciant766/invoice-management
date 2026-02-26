"""
Backup Service - PRODUCTION GRADE
=================================

Handles database and receipt backups/restoration with verification.
"""

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from database import DATABASE_PATH

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backup_service")

# Where backups are stored (primary location)
BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_FOLDER = BASE_DIR / "backups"
BACKUP_FOLDER.mkdir(parents=True, exist_ok=True)

# Receipt storage location
RECEIPT_FOLDER = BASE_DIR / "uploads" / "fiscal_receipts"
RECEIPT_FOLDER.mkdir(parents=True, exist_ok=True)

# External backup location (optional - set via environment variable)
# Example: EXTERNAL_BACKUP_PATH=D:\backups\invoice_system
EXTERNAL_BACKUP_FOLDER = os.getenv("EXTERNAL_BACKUP_PATH")
if EXTERNAL_BACKUP_FOLDER:
    EXTERNAL_BACKUP_FOLDER = Path(EXTERNAL_BACKUP_FOLDER)
    EXTERNAL_BACKUP_FOLDER.mkdir(parents=True, exist_ok=True)

# Database file location
DATABASE_FILE = Path(DATABASE_PATH)

# Keep this many backups (delete older ones)
MAX_BACKUPS = 50

# Log file for backup operations
BACKUP_LOG_FILE = BACKUP_FOLDER / "backup_log.txt"


def _log_backup_operation(operation: str, details: str, success: bool):
    """Log backup operations to file for audit trail."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "SUCCESS" if success else "FAILED"
    log_entry = f"[{timestamp}] [{status}] {operation}: {details}\n"

    try:
        with open(BACKUP_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        logger.error(f"Failed to write to backup log: {e}")


def _copy_to_external(backup_path: Path):
    """Copy backup artifact to external location when configured."""
    if not EXTERNAL_BACKUP_FOLDER:
        return
    try:
        external_path = EXTERNAL_BACKUP_FOLDER / backup_path.name
        shutil.copy2(backup_path, external_path)
        logger.info(f"External backup created: {external_path}")
    except Exception as e:
        logger.warning(f"External backup failed (primary backup OK): {e}")


def verify_backup(backup_path: Path) -> Tuple[bool, str]:
    """
    Verify that a backup file is a valid SQLite database.

    Returns:
        Tuple of (is_valid, message)
    """
    if not backup_path.exists():
        return False, "File does not exist"

    if backup_path.stat().st_size == 0:
        return False, "File is empty"

    try:
        conn = sqlite3.connect(str(backup_path))
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        required_tables = ["invoices", "suppliers"]
        missing = [t for t in required_tables if t not in tables]

        if missing:
            conn.close()
            return False, f"Missing tables: {missing}"

        cursor.execute("SELECT COUNT(*) FROM invoices")
        invoice_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM suppliers")
        supplier_count = cursor.fetchone()[0]

        conn.close()

        return True, f"Valid database: {invoice_count} invoices, {supplier_count} suppliers"

    except sqlite3.Error as e:
        return False, f"SQLite error: {e}"
    except Exception as e:
        return False, f"Verification error: {e}"


def get_file_checksum(filepath: Path) -> str:
    """Calculate SHA-256 checksum of a file."""
    hash_sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


def _zip_directory(source_dir: Path, zip_path: Path):
    """Zip a directory recursively, preserving relative paths."""
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in source_dir.rglob("*"):
            zf.write(path, arcname=str(path.relative_to(source_dir)))


def verify_full_backup(backup_path: Path) -> Tuple[bool, str]:
    """
    Verify that a full backup zip contains a valid DB and receipt snapshot.

    Returns:
        Tuple of (is_valid, message)
    """
    if not backup_path.exists():
        return False, "File does not exist"
    if backup_path.suffix.lower() != ".zip":
        return False, "Not a full backup archive (.zip expected)"
    if backup_path.stat().st_size == 0:
        return False, "File is empty"

    try:
        with tempfile.TemporaryDirectory(prefix="verify_full_", dir=str(BACKUP_FOLDER)) as tmp_dir:
            extract_dir = Path(tmp_dir) / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(extract_dir)

            db_snapshot = extract_dir / "database.db"
            if not db_snapshot.exists():
                return False, "Missing database snapshot in full backup"

            is_valid_db, db_message = verify_backup(db_snapshot)
            if not is_valid_db:
                return False, f"Invalid DB in full backup: {db_message}"

            receipt_dir = extract_dir / "uploads" / "fiscal_receipts"
            receipt_count = 0
            if receipt_dir.exists():
                receipt_count = sum(1 for p in receipt_dir.rglob("*") if p.is_file())

            return True, f"Valid full backup: {db_message}; {receipt_count} receipt files"
    except zipfile.BadZipFile:
        return False, "Corrupt zip archive"
    except Exception as e:
        return False, f"Full backup verification error: {e}"


def create_backup(reason: str = "manual", skip_verification: bool = False) -> Optional[str]:
    """
    Create a verified backup of the database only.

    Args:
        reason: Why the backup was created (e.g., "manual", "auto", "pre-delete")
        skip_verification: Skip backup verification (not recommended)

    Returns:
        Backup filename if successful, None if failed
    """
    if not DATABASE_FILE.exists():
        logger.error(f"Database file not found: {DATABASE_FILE}")
        _log_backup_operation("CREATE_DB", f"Database not found: {DATABASE_FILE}", False)
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"{timestamp}_{reason}.db"
    backup_path = BACKUP_FOLDER / backup_filename

    try:
        source_checksum = get_file_checksum(DATABASE_FILE)
        shutil.copy2(DATABASE_FILE, backup_path)
        backup_checksum = get_file_checksum(backup_path)

        if source_checksum != backup_checksum:
            logger.error("Backup checksum mismatch - file may be corrupted")
            backup_path.unlink(missing_ok=True)
            _log_backup_operation("CREATE_DB", f"Checksum mismatch for {backup_filename}", False)
            return None

        if not skip_verification:
            is_valid, message = verify_backup(backup_path)
            if not is_valid:
                logger.error(f"Backup verification failed: {message}")
                backup_path.unlink(missing_ok=True)
                _log_backup_operation("CREATE_DB", f"Verification failed: {message}", False)
                return None
            logger.info(f"Backup verified: {message}")

        _copy_to_external(backup_path)

        logger.info(f"DB backup created: {backup_filename}")
        _log_backup_operation("CREATE_DB", f"{backup_filename} ({reason})", True)
        cleanup_old_backups()
        return backup_filename

    except Exception as e:
        logger.error(f"Backup failed: {e}")
        _log_backup_operation("CREATE_DB", f"Error: {e}", False)
        return None


def create_full_backup(reason: str = "manual", skip_verification: bool = False) -> Optional[str]:
    """
    Create a consistent full backup containing DB + receipt files.

    Returns:
        Full backup zip filename if successful, None if failed.
    """
    if not DATABASE_FILE.exists():
        logger.error(f"Database file not found: {DATABASE_FILE}")
        _log_backup_operation("CREATE_FULL", f"Database not found: {DATABASE_FILE}", False)
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"{timestamp}_{reason}_full.zip"
    backup_path = BACKUP_FOLDER / backup_filename
    staging_dir = BACKUP_FOLDER / f".staging_{timestamp}_{reason}_full"

    try:
        staging_dir.mkdir(parents=True, exist_ok=True)

        db_snapshot = staging_dir / "database.db"
        source_checksum = get_file_checksum(DATABASE_FILE)
        shutil.copy2(DATABASE_FILE, db_snapshot)
        snapshot_checksum = get_file_checksum(db_snapshot)
        if source_checksum != snapshot_checksum:
            raise RuntimeError("Database snapshot checksum mismatch")

        if not skip_verification:
            is_valid, message = verify_backup(db_snapshot)
            if not is_valid:
                raise RuntimeError(f"Database verification failed: {message}")

        receipts_snapshot = staging_dir / "uploads" / "fiscal_receipts"
        receipts_snapshot.mkdir(parents=True, exist_ok=True)

        receipt_count = 0
        if RECEIPT_FOLDER.exists():
            for src in RECEIPT_FOLDER.rglob("*"):
                if src.is_file():
                    rel_path = src.relative_to(RECEIPT_FOLDER)
                    dest = receipts_snapshot / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    receipt_count += 1

        manifest = {
            "created_at": datetime.now().isoformat(),
            "reason": reason,
            "database_file": "database.db",
            "database_sha256": snapshot_checksum,
            "receipt_file_count": receipt_count,
            "receipt_root": "uploads/fiscal_receipts"
        }
        with open(staging_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        _zip_directory(staging_dir, backup_path)
        _copy_to_external(backup_path)

        is_valid_full, verify_message = verify_full_backup(backup_path)
        if not is_valid_full:
            backup_path.unlink(missing_ok=True)
            raise RuntimeError(f"Full backup verification failed: {verify_message}")

        logger.info(f"Full backup created: {backup_filename}")
        _log_backup_operation("CREATE_FULL", f"{backup_filename} ({reason})", True)
        cleanup_old_backups()
        return backup_filename

    except Exception as e:
        logger.error(f"Full backup failed: {e}")
        _log_backup_operation("CREATE_FULL", f"Error: {e}", False)
        return None
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def restore_backup(backup_filename: str) -> bool:
    """
    Restore the database from a DB-only backup file.

    IMPORTANT: This will replace your current database file.
    """
    backup_path = BACKUP_FOLDER / backup_filename

    if not backup_path.exists():
        logger.error(f"Backup not found: {backup_filename}")
        _log_backup_operation("RESTORE_DB", f"File not found: {backup_filename}", False)
        return False

    is_valid, message = verify_backup(backup_path)
    if not is_valid:
        logger.error(f"Cannot restore - backup invalid: {message}")
        _log_backup_operation("RESTORE_DB", f"Invalid backup: {message}", False)
        return False

    try:
        pre_restore_backup = create_backup("pre-restore")
        if not pre_restore_backup:
            logger.error("Failed to create pre-restore backup - aborting restore")
            _log_backup_operation("RESTORE_DB", "Pre-restore backup failed", False)
            return False

        shutil.copy2(backup_path, DATABASE_FILE)

        is_valid_db, db_message = verify_backup(DATABASE_FILE)
        if not is_valid_db:
            pre_restore_path = BACKUP_FOLDER / pre_restore_backup
            shutil.copy2(pre_restore_path, DATABASE_FILE)
            _log_backup_operation("RESTORE_DB", f"Verification failed, rolled back: {db_message}", False)
            return False

        logger.info(f"Database restored from: {backup_filename}")
        _log_backup_operation("RESTORE_DB", f"Restored from {backup_filename}", True)
        return True

    except Exception as e:
        logger.error(f"Restore failed: {e}")
        _log_backup_operation("RESTORE_DB", f"Error: {e}", False)
        return False


def restore_full_backup(backup_filename: str) -> bool:
    """
    Restore DB + receipt files from a full backup archive.

    IMPORTANT: Replaces both current DB and receipt storage.
    """
    backup_path = BACKUP_FOLDER / backup_filename
    if not backup_path.exists():
        logger.error(f"Full backup not found: {backup_filename}")
        _log_backup_operation("RESTORE_FULL", f"File not found: {backup_filename}", False)
        return False

    is_valid, message = verify_full_backup(backup_path)
    if not is_valid:
        logger.error(f"Cannot restore full backup - invalid: {message}")
        _log_backup_operation("RESTORE_FULL", f"Invalid full backup: {message}", False)
        return False

    try:
        pre_restore_backup = create_full_backup("pre-restore")
        if not pre_restore_backup:
            logger.error("Failed to create pre-restore full backup - aborting restore")
            _log_backup_operation("RESTORE_FULL", "Pre-restore full backup failed", False)
            return False

        with tempfile.TemporaryDirectory(prefix="restore_full_", dir=str(BACKUP_FOLDER)) as tmp_dir:
            tmp_path = Path(tmp_dir)
            extract_dir = tmp_path / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(extract_dir)

            db_snapshot = extract_dir / "database.db"
            receipts_snapshot = extract_dir / "uploads" / "fiscal_receipts"

            current_db_copy = tmp_path / "current_database.db"
            if DATABASE_FILE.exists():
                shutil.copy2(DATABASE_FILE, current_db_copy)

            current_receipts_copy = tmp_path / "current_receipts"
            if RECEIPT_FOLDER.exists():
                shutil.copytree(RECEIPT_FOLDER, current_receipts_copy)

            try:
                shutil.copy2(db_snapshot, DATABASE_FILE)

                if RECEIPT_FOLDER.exists():
                    shutil.rmtree(RECEIPT_FOLDER, ignore_errors=True)
                RECEIPT_FOLDER.parent.mkdir(parents=True, exist_ok=True)
                RECEIPT_FOLDER.mkdir(parents=True, exist_ok=True)
                if receipts_snapshot.exists():
                    shutil.copytree(receipts_snapshot, RECEIPT_FOLDER, dirs_exist_ok=True)

                is_valid_db, db_message = verify_backup(DATABASE_FILE)
                if not is_valid_db:
                    raise RuntimeError(f"Restored DB failed verification: {db_message}")

            except Exception as restore_error:
                logger.error(f"Full restore verification failed: {restore_error}. Rolling back...")
                if current_db_copy.exists():
                    shutil.copy2(current_db_copy, DATABASE_FILE)

                if RECEIPT_FOLDER.exists():
                    shutil.rmtree(RECEIPT_FOLDER, ignore_errors=True)
                if current_receipts_copy.exists():
                    shutil.copytree(current_receipts_copy, RECEIPT_FOLDER)
                else:
                    RECEIPT_FOLDER.mkdir(parents=True, exist_ok=True)
                raise

        logger.info(f"Full restore completed from: {backup_filename}")
        _log_backup_operation("RESTORE_FULL", f"Restored from {backup_filename}", True)
        return True

    except Exception as e:
        logger.error(f"Full restore failed: {e}")
        _log_backup_operation("RESTORE_FULL", f"Error: {e}", False)
        return False


def run_full_backup_restore_drill(backup_filename: Optional[str] = None) -> Dict[str, object]:
    """
    Dry-run restore verification for a full backup archive.

    Does not change production DB or receipt files.
    """
    full_backups = [b for b in list_backups() if b.get("backup_type") == "full"]
    if not full_backups:
        result = {"success": False, "message": "No full backups available", "backup": None}
        _log_backup_operation("RESTORE_DRILL", result["message"], False)
        return result

    target = backup_filename or full_backups[0]["filename"]
    backup_path = BACKUP_FOLDER / target

    is_valid, message = verify_full_backup(backup_path)
    if not is_valid:
        result = {"success": False, "message": f"Full backup invalid: {message}", "backup": target}
        _log_backup_operation("RESTORE_DRILL", result["message"], False)
        return result

    try:
        with tempfile.TemporaryDirectory(prefix="restore_drill_", dir=str(BACKUP_FOLDER)) as tmp_dir:
            extract_dir = Path(tmp_dir) / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(extract_dir)

            db_snapshot = extract_dir / "database.db"
            receipts_snapshot = extract_dir / "uploads" / "fiscal_receipts"

            conn = sqlite3.connect(str(db_snapshot))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, fiscal_receipt_path FROM invoices WHERE fiscal_receipt_path IS NOT NULL AND TRIM(fiscal_receipt_path) != ''"
            )
            rows = cursor.fetchall()
            conn.close()

            missing_files = []
            for invoice_id, receipt_path in rows:
                file_path = receipts_snapshot / receipt_path
                if not file_path.exists():
                    missing_files.append({"invoice_id": invoice_id, "receipt_path": receipt_path})

            result = {
                "success": len(missing_files) == 0,
                "backup": target,
                "message": "Restore drill passed" if not missing_files else "Restore drill found missing receipt files",
                "linked_receipt_records": len(rows),
                "missing_receipt_files": missing_files
            }
            _log_backup_operation("RESTORE_DRILL", result["message"], result["success"])
            return result

    except Exception as e:
        result = {"success": False, "backup": target, "message": f"Restore drill failed: {e}"}
        _log_backup_operation("RESTORE_DRILL", result["message"], False)
        return result


def backup_before_dangerous_operation(operation: str) -> Optional[str]:
    """
    Create a full backup before a dangerous operation.
    """
    return create_full_backup(f"pre-{operation}")


def _parse_backup_entry(file_path: Path) -> dict:
    """Build backup metadata for UI listing."""
    try:
        parts = file_path.stem.split("_")
        date_str = parts[0] if len(parts) >= 1 else "Unknown"
        time_str = parts[1] if len(parts) >= 2 else "Unknown"
        reason = "_".join(parts[2:]) if len(parts) >= 3 else "unknown"
        backup_type = "database" if file_path.suffix.lower() == ".db" else "full"

        if backup_type == "full" and reason.endswith("_full"):
            reason = reason[:-5]

        date_formatted = f"{date_str} {time_str.replace('-', ':')}" if date_str != "Unknown" and time_str != "Unknown" else "Unknown"

        return {
            "filename": file_path.name,
            "date": date_formatted,
            "reason": reason or "unknown",
            "size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
            "backup_type": backup_type
        }
    except Exception:
        return {
            "filename": file_path.name,
            "date": "Unknown",
            "reason": "unknown",
            "size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
            "backup_type": "database" if file_path.suffix.lower() == ".db" else "full"
        }


def list_backups() -> List[dict]:
    """
    Get a list of all backup artifacts (.db and full .zip), newest first.
    """
    backups = []
    for pattern in ("*.db", "*.zip"):
        for file_path in BACKUP_FOLDER.glob(pattern):
            backups.append(_parse_backup_entry(file_path))

    backups.sort(key=lambda x: x["filename"], reverse=True)
    return backups


def delete_backup(backup_filename: str) -> bool:
    """
    Delete a specific backup artifact.

    NOTE: Will not delete if it's the only remaining backup.
    """
    backups = list_backups()
    if len(backups) <= 1:
        logger.warning("Cannot delete - this is the only backup")
        return False

    backup_path = BACKUP_FOLDER / backup_filename
    if not backup_path.exists():
        return False

    try:
        backup_path.unlink()
        logger.info(f"Backup deleted: {backup_filename}")
        _log_backup_operation("DELETE", backup_filename, True)

        if EXTERNAL_BACKUP_FOLDER:
            external_path = EXTERNAL_BACKUP_FOLDER / backup_filename
            if external_path.exists():
                external_path.unlink()

        return True
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        _log_backup_operation("DELETE", f"Error: {e}", False)
        return False


def cleanup_old_backups():
    """
    Remove old backups, keeping only the most recent MAX_BACKUPS artifacts.
    """
    backups = list_backups()

    if len(backups) > MAX_BACKUPS:
        for old_backup in backups[MAX_BACKUPS:]:
            backup_path = BACKUP_FOLDER / old_backup["filename"]
            try:
                backup_path.unlink()
                logger.info(f"Cleaned up old backup: {old_backup['filename']}")
            except Exception as e:
                logger.warning(f"Failed to clean up {old_backup['filename']}: {e}")

        logger.info(f"Cleaned up {len(backups) - MAX_BACKUPS} old backups")


def get_backup_stats() -> dict:
    """
    Get statistics about backup artifacts.
    """
    backups = list_backups()
    total_size = sum(b["size_mb"] for b in backups)
    db_backups = [b for b in backups if b.get("backup_type") == "database"]
    full_backups = [b for b in backups if b.get("backup_type") == "full"]

    return {
        "total_backups": len(backups),
        "database_backups": len(db_backups),
        "full_backups": len(full_backups),
        "total_size_mb": round(total_size, 2),
        "oldest_backup": backups[-1]["date"] if backups else None,
        "newest_backup": backups[0]["date"] if backups else None,
        "max_backups": MAX_BACKUPS,
        "external_backup_enabled": EXTERNAL_BACKUP_FOLDER is not None
    }


def auto_backup_on_start():
    """
    Startup safety:
    - verify current DB integrity
    - ensure one daily DB backup
    - ensure one daily full backup (DB + receipts)
    """
    if DATABASE_FILE.exists():
        is_valid, message = verify_backup(DATABASE_FILE)
        if not is_valid:
            logger.error(f"DATABASE INTEGRITY CHECK FAILED: {message}")
            logger.error("Attempting to restore from most recent valid DB backup...")

            backups = list_backups()
            db_backups = [b for b in backups if b.get("backup_type") == "database"]
            for backup in db_backups:
                backup_path = BACKUP_FOLDER / backup["filename"]
                is_backup_valid, _ = verify_backup(backup_path)
                if is_backup_valid:
                    logger.info(f"Restoring DB from: {backup['filename']}")
                    shutil.copy2(backup_path, DATABASE_FILE)
                    break
            return
        logger.info(f"Database integrity check passed: {message}")

    today = datetime.now().strftime("%Y-%m-%d")
    backups = list_backups()
    today_db_backups = [
        b for b in backups
        if b["date"].startswith(today) and b.get("backup_type") == "database" and b.get("reason") == "auto-daily"
    ]
    today_full_backups = [
        b for b in backups
        if b["date"].startswith(today) and b.get("backup_type") == "full" and b.get("reason") == "auto-daily"
    ]

    if not today_db_backups:
        logger.info("Creating automatic daily DB backup...")
        result = create_backup("auto-daily")
        if result:
            logger.info(f"Daily DB backup created: {result}")
        else:
            logger.error("Failed to create daily DB backup!")
    else:
        logger.info(f"DB backup already exists for today ({len(today_db_backups)} backups)")

    if not today_full_backups:
        logger.info("Creating automatic daily FULL backup (DB + receipts)...")
        result = create_full_backup("auto-daily")
        if result:
            logger.info(f"Daily full backup created: {result}")
        else:
            logger.error("Failed to create daily full backup!")
    else:
        logger.info(f"Full backup already exists for today ({len(today_full_backups)} backups)")


def get_backup_log() -> List[str]:
    """
    Get the backup operation log.

    Returns:
        List of log entries, newest first.
    """
    if not BACKUP_LOG_FILE.exists():
        return []

    try:
        with open(BACKUP_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return list(reversed(lines[-100:]))
    except Exception:
        return []
