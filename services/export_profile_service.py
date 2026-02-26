"""
Export signatory profile service.

Stores and retrieves reusable signatory names for schedule exports.
"""

from typing import Dict, Optional


SIGNATORY_FIELDS = (
    "sindku",
    "segretarju_ezekuttiv",
    "proponent",
    "sekondant",
)

SIGNATORY_SETTINGS_KEYS = {
    "sindku": "export_signatory_sindku",
    "segretarju_ezekuttiv": "export_signatory_segretarju_ezekuttiv",
    "proponent": "export_signatory_proponent",
    "sekondant": "export_signatory_sekondant",
}

MAX_SIGNATORY_LENGTH = 120


def normalize_signatory_value(value: Optional[str], preserve_none: bool = False) -> Optional[str]:
    """Normalize user-provided signatory text for safe, consistent storage."""
    if value is None:
        return None if preserve_none else ""

    cleaned = " ".join(str(value).strip().split())
    return cleaned[:MAX_SIGNATORY_LENGTH]


def get_export_signatories(conn) -> Dict[str, str]:
    """Load stored signatory values. Missing keys return empty strings."""
    cursor = conn.cursor()
    keys = tuple(SIGNATORY_SETTINGS_KEYS[field] for field in SIGNATORY_FIELDS)
    placeholders = ",".join("?" for _ in keys)

    cursor.execute(
        f"SELECT key, value FROM settings WHERE key IN ({placeholders})",
        keys
    )

    values_by_key = {row["key"]: row["value"] or "" for row in cursor.fetchall()}

    return {
        field: normalize_signatory_value(values_by_key.get(setting_key, "")) or ""
        for field, setting_key in SIGNATORY_SETTINGS_KEYS.items()
    }


def save_export_signatories(conn, values: Dict[str, Optional[str]]) -> Dict[str, str]:
    """Persist provided signatory values (None means ignore that field)."""
    cursor = conn.cursor()
    has_updates = False

    for field in SIGNATORY_FIELDS:
        if field not in values:
            continue

        raw_value = values.get(field)
        if raw_value is None:
            continue

        normalized_value = normalize_signatory_value(raw_value) or ""
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (SIGNATORY_SETTINGS_KEYS[field], normalized_value)
        )
        has_updates = True

    if has_updates:
        conn.commit()

    return get_export_signatories(conn)


def resolve_export_signatories(conn, overrides: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, str]:
    """
    Return current signatories, applying provided overrides first.

    An override value of None means "no change".
    An empty string means "clear this value".
    """
    if overrides:
        provided = {
            field: overrides[field]
            for field in SIGNATORY_FIELDS
            if field in overrides and overrides[field] is not None
        }
        if provided:
            return save_export_signatories(conn, provided)

    return get_export_signatories(conn)
