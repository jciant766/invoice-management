"""
Run receipt integrity check from command line.

Usage:
    python tools/run_receipt_integrity_check.py
"""

from services.receipt_integrity_service import run_receipt_integrity_check


def main():
    report = run_receipt_integrity_check(update_baseline=True, save_report=True)
    summary = report.get("summary", {})
    print("Receipt integrity check completed")
    print(f"- linked receipt records: {summary.get('linked_receipt_records', 0)}")
    print(f"- files on disk: {summary.get('files_on_disk', 0)}")
    print(f"- missing linked files: {summary.get('missing_linked_files', 0)}")
    print(f"- orphan files: {summary.get('orphan_files', 0)}")
    print(f"- checksum mismatches: {summary.get('checksum_mismatches', 0)}")


if __name__ == "__main__":
    main()
