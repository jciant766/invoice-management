"""
TF (Transfer of Funds) Number Generation Service

TF numbers are sacred:
- Only assigned after council approval
- Sequential, never skip
- Never reuse (even if invoice deleted)
- Must continue across months/years
"""

from sqlalchemy.orm import Session
from models import Setting
import logging

logger = logging.getLogger(__name__)

TF_NUMBER_KEY = "current_tf_number"
DEFAULT_TF_START = "5460"


def get_current_tf_number(db: Session) -> int:
    """Get the current TF number counter value."""
    setting = db.query(Setting).filter(Setting.key == TF_NUMBER_KEY).first()
    if setting:
        return int(setting.value)
    return int(DEFAULT_TF_START)


def get_next_tf_number_preview(db: Session) -> str:
    """Preview what the next TF number will be (without incrementing)."""
    current = get_current_tf_number(db)
    return f"TF {current + 1}"


def generate_next_tf_number(db: Session) -> str:
    """
    Generate the next TF number and increment the counter.

    CRITICAL: This should ONLY be called when approving an invoice.
    The number is assigned atomically to prevent race conditions.

    Returns:
        str: The new TF number in format "TF XXXX"
    """
    # Get current value
    setting = db.query(Setting).filter(Setting.key == TF_NUMBER_KEY).first()

    if setting is None:
        # Initialize if not exists
        setting = Setting(key=TF_NUMBER_KEY, value=DEFAULT_TF_START)
        db.add(setting)
        db.flush()

    # Increment and update
    current_number = int(setting.value)
    next_number = current_number + 1
    setting.value = str(next_number)

    # Commit will happen in the calling function
    tf_string = f"TF {next_number}"

    logger.info(f"Generated TF number: {tf_string}")

    return tf_string


def update_tf_counter(db: Session, new_value: int) -> bool:
    """
    Manually update the TF counter (admin function).

    WARNING: Use with extreme caution. Should only be used for:
    - Initial setup
    - Correcting errors
    - Database migration

    Returns:
        bool: True if successful
    """
    if new_value < 0:
        raise ValueError("TF number cannot be negative")

    setting = db.query(Setting).filter(Setting.key == TF_NUMBER_KEY).first()

    if setting is None:
        setting = Setting(key=TF_NUMBER_KEY, value=str(new_value))
        db.add(setting)
    else:
        setting.value = str(new_value)

    logger.warning(f"TF counter manually updated to: {new_value}")

    return True
