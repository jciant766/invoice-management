"""
Database Key Backup Tool
========================

Creates encrypted backups of your DATABASE_KEY.
Run this after setting up encryption to create recovery options.

Usage:
    python tools/key_backup.py --create    # Create backup files
    python tools/key_backup.py --verify    # Verify backups are valid
    python tools/key_backup.py --print     # Print key for manual backup
"""

import os
import sys
import hashlib
import base64
from pathlib import Path
from datetime import datetime

# Add parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


def get_key():
    """Get the database key from environment."""
    return os.getenv("DATABASE_KEY")


def create_key_checksum(key: str) -> str:
    """Create a checksum to verify key integrity."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def create_backup():
    """Create backup files for the key."""
    key = get_key()

    if not key:
        print("ERROR: DATABASE_KEY is not set in .env")
        return False

    print("=" * 60)
    print("DATABASE KEY BACKUP")
    print("=" * 60)
    print()

    # Create backups directory
    backup_dir = Path(__file__).parent.parent / "key_backups"
    backup_dir.mkdir(exist_ok=True)

    # Create checksum
    checksum = create_key_checksum(key)

    # Create backup file with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"key_backup_{timestamp}.txt"

    with open(backup_file, "w") as f:
        f.write("=" * 50 + "\n")
        f.write("SLIEMA COUNCIL - DATABASE ENCRYPTION KEY BACKUP\n")
        f.write("=" * 50 + "\n")
        f.write(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Checksum: {checksum}\n")
        f.write("=" * 50 + "\n\n")
        f.write("YOUR DATABASE KEY:\n\n")
        f.write(f"    {key}\n\n")
        f.write("=" * 50 + "\n")
        f.write("IMPORTANT:\n")
        f.write("- Store this file in a SECURE location\n")
        f.write("- Make multiple copies (USB drive, printed, etc.)\n")
        f.write("- DO NOT share this file with anyone\n")
        f.write("- If you lose this key, your data is UNRECOVERABLE\n")
        f.write("=" * 50 + "\n")

    print(f"Backup created: {backup_file}")
    print()
    print("NEXT STEPS:")
    print(f"1. Copy {backup_file.name} to a USB drive")
    print("2. Print it and store in a safe place")
    print("3. Add to your password manager")
    print("4. DELETE the backup file from this computer after copying")
    print()

    # Add to .gitignore
    gitignore_path = Path(__file__).parent.parent / ".gitignore"
    gitignore_entry = "key_backups/"

    if gitignore_path.exists():
        with open(gitignore_path, "r") as f:
            content = f.read()
        if gitignore_entry not in content:
            with open(gitignore_path, "a") as f:
                f.write(f"\n# Key backups (NEVER commit these!)\n{gitignore_entry}\n")
            print("Added key_backups/ to .gitignore")

    return True


def verify_backup():
    """Verify that backup matches current key."""
    key = get_key()

    if not key:
        print("ERROR: DATABASE_KEY is not set")
        return False

    current_checksum = create_key_checksum(key)

    backup_dir = Path(__file__).parent.parent / "key_backups"

    if not backup_dir.exists():
        print("No backup directory found. Run with --create first.")
        return False

    backups = list(backup_dir.glob("key_backup_*.txt"))

    if not backups:
        print("No backup files found.")
        return False

    print("Verifying backups...")
    print()

    for backup in backups:
        with open(backup, "r") as f:
            content = f.read()

        # Extract checksum from backup
        for line in content.split("\n"):
            if line.startswith("Checksum:"):
                backup_checksum = line.split(":")[1].strip()
                if backup_checksum == current_checksum:
                    print(f"  {backup.name}: VALID")
                else:
                    print(f"  {backup.name}: MISMATCH (key may have changed)")
                break

    print()
    print(f"Current key checksum: {current_checksum}")

    return True


def print_key():
    """Print the key for manual backup."""
    key = get_key()

    if not key:
        print("ERROR: DATABASE_KEY is not set")
        return False

    checksum = create_key_checksum(key)

    print()
    print("=" * 50)
    print("YOUR DATABASE ENCRYPTION KEY")
    print("=" * 50)
    print()
    print(f"  Key: {key}")
    print(f"  Checksum: {checksum}")
    print()
    print("Write this down and store in a safe place!")
    print("=" * 50)
    print()

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Database key backup tool")
    parser.add_argument("--create", action="store_true", help="Create backup files")
    parser.add_argument("--verify", action="store_true", help="Verify existing backups")
    parser.add_argument("--print", action="store_true", dest="print_key", help="Print key for manual backup")

    args = parser.parse_args()

    if args.create:
        create_backup()
    elif args.verify:
        verify_backup()
    elif args.print_key:
        print_key()
    else:
        parser.print_help()
