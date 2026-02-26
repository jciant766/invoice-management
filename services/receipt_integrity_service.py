"""
Receipt Integrity Service
=========================

Nightly-style integrity checks for invoice-linked receipt files.
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from database import get_db

logger = logging.getLogger("receipt_integrity_service")

BASE_DIR = Path(__file__).resolve().parent.parent
RECEIPT_FOLDER = BASE_DIR / "uploads" / "fiscal_receipts"
BACKUP_FOLDER = BASE_DIR / "backups"
REPORT_FOLDER = BACKUP_FOLDER / "receipt_integrity_reports"
BASELINE_FILE = BACKUP_FOLDER / "receipt_integrity_baseline.json"

RECEIPT_FOLDER.mkdir(parents=True, exist_ok=True)
BACKUP_FOLDER.mkdir(parents=True, exist_ok=True)
REPORT_FOLDER.mkdir(parents=True, exist_ok=True)


def _file_checksum(path: Path) -> str:
    hash_sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


def _load_json(path: Path, default: Dict) -> Dict:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: Path, payload: Dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def run_receipt_integrity_check(update_baseline: bool = True, save_report: bool = True) -> Dict:
    """
    Run integrity checks:
    - missing linked files
    - orphan files not linked in DB
    - checksum mismatches against previous baseline (same filename changed)
    """
    timestamp = datetime.now().isoformat()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, pjv_number, fiscal_receipt_path
            FROM invoices
            WHERE is_deleted = 0
              AND fiscal_receipt_path IS NOT NULL
              AND TRIM(fiscal_receipt_path) != ''
            """
        )
        linked_rows = cursor.fetchall()

    linked_receipts = []
    linked_paths = set()
    for invoice_id, pjv_number, receipt_path in linked_rows:
        path_str = str(receipt_path).strip()
        if not path_str:
            continue
        linked_receipts.append(
            {
                "invoice_id": invoice_id,
                "pjv_number": pjv_number,
                "receipt_path": path_str
            }
        )
        linked_paths.add(path_str)

    existing_files = set()
    current_checksums = {}
    for file_path in RECEIPT_FOLDER.rglob("*"):
        if not file_path.is_file():
            continue
        rel_path = str(file_path.relative_to(RECEIPT_FOLDER)).replace("\\", "/")
        existing_files.add(rel_path)
        current_checksums[rel_path] = _file_checksum(file_path)

    missing_files = []
    for rec in linked_receipts:
        if rec["receipt_path"] not in existing_files:
            missing_files.append(rec)

    orphan_files = sorted(existing_files - linked_paths)

    baseline = _load_json(BASELINE_FILE, {"checksums": {}})
    baseline_checksums = baseline.get("checksums", {})
    checksum_mismatches = []
    for rel_path, checksum in current_checksums.items():
        if rel_path in baseline_checksums and baseline_checksums[rel_path] != checksum:
            checksum_mismatches.append(
                {
                    "receipt_path": rel_path,
                    "previous_checksum": baseline_checksums[rel_path],
                    "current_checksum": checksum
                }
            )

    report = {
        "timestamp": timestamp,
        "summary": {
            "linked_receipt_records": len(linked_receipts),
            "files_on_disk": len(existing_files),
            "missing_linked_files": len(missing_files),
            "orphan_files": len(orphan_files),
            "checksum_mismatches": len(checksum_mismatches)
        },
        "missing_linked_files": missing_files,
        "orphan_files": orphan_files,
        "checksum_mismatches": checksum_mismatches
    }

    if save_report:
        report_name = f"receipt_integrity_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        _write_json(REPORT_FOLDER / report_name, report)

    if update_baseline:
        baseline_payload = {
            "updated_at": timestamp,
            "checksums": current_checksums
        }
        _write_json(BASELINE_FILE, baseline_payload)

    return report


def auto_integrity_check_on_start():
    """
    Run one integrity check per day when app starts.
    """
    today_prefix = f"receipt_integrity_{datetime.now().strftime('%Y-%m-%d')}"
    todays_reports = list(REPORT_FOLDER.glob(f"{today_prefix}_*.json"))
    if todays_reports:
        logger.info("Integrity report already exists for today (%s)", len(todays_reports))
        return

    logger.info("Running startup receipt integrity check...")
    report = run_receipt_integrity_check(update_baseline=True, save_report=True)
    summary = report.get("summary", {})
    logger.info(
        "Integrity check completed: missing=%s orphan=%s checksum_mismatch=%s",
        summary.get("missing_linked_files", 0),
        summary.get("orphan_files", 0),
        summary.get("checksum_mismatches", 0),
    )


def list_integrity_reports(limit: int = 30) -> List[Dict]:
    """
    Return newest integrity reports for admin display/debug tooling.
    """
    reports = []
    files = sorted(REPORT_FOLDER.glob("receipt_integrity_*.json"), reverse=True)
    for report_file in files[:limit]:
        payload = _load_json(report_file, {})
        summary = payload.get("summary", {})
        reports.append(
            {
                "filename": report_file.name,
                "timestamp": payload.get("timestamp"),
                "missing_linked_files": summary.get("missing_linked_files", 0),
                "orphan_files": summary.get("orphan_files", 0),
                "checksum_mismatches": summary.get("checksum_mismatches", 0),
            }
        )
    return reports
