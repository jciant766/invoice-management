"""
Run full-backup restore drill without touching production data.

Usage:
    python tools/run_restore_drill.py
    python tools/run_restore_drill.py BACKUP_FILENAME.zip
"""

import json
import sys

from services.backup_service import run_full_backup_restore_drill


def main():
    backup_filename = sys.argv[1] if len(sys.argv) > 1 else None
    result = run_full_backup_restore_drill(backup_filename)
    print(json.dumps(result, indent=2))
    if not result.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
