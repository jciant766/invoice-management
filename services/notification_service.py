"""
Notification Service

Sends security and account emails via SMTP.
"""

import logging
import os
import smtplib
import ssl
from datetime import datetime
from pathlib import Path
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    """Parse common truthy environment variable values."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_email_configured() -> bool:
    """Return True when SMTP settings are present."""
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"))


def _fallback_to_file_enabled() -> bool:
    """Whether failed emails should be written to a local outbox file."""
    return _as_bool(os.getenv("EMAIL_FALLBACK_TO_FILE"), default=False)


def _get_outbox_file() -> Path:
    """Get local outbox file path."""
    configured = os.getenv("EMAIL_OUTBOX_FILE", "").strip()
    if configured:
        return Path(configured)
    base_dir = Path(__file__).resolve().parent.parent
    return base_dir / "dev_outbox_emails.log"


def _write_email_to_outbox(to_address: str, subject: str, text_body: str) -> None:
    """Write email content to a local file for dev/testing fallback."""
    outbox_file = _get_outbox_file()
    outbox_file.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"[{datetime.now().isoformat()}]\n"
        f"TO: {to_address}\n"
        f"SUBJECT: {subject}\n\n"
        f"{text_body}\n"
        f"{'-' * 80}\n"
    )
    with open(outbox_file, "a", encoding="utf-8") as handle:
        handle.write(entry)
    logger.info(f"Email fallback written to file: {outbox_file}")


def _write_latest_reset_link(reset_link: str) -> None:
    """Write the latest password-reset link to a dedicated file for quick local testing."""
    file_name = os.getenv("EMAIL_LATEST_RESET_LINK_FILE", "dev_outbox_latest_reset_link.txt").strip()
    target = Path(file_name)
    if not target.is_absolute():
        target = (Path(__file__).resolve().parent.parent / target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(reset_link + "\n")
    logger.info(f"Latest reset link written to file: {target}")


def send_email(
    to_address: str,
    subject: str,
    text_body: str,
    html_body: str = None
) -> bool:
    """Send an email using SMTP. Returns True when sent."""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_from = os.getenv("SMTP_FROM")
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_use_ssl = _as_bool(os.getenv("SMTP_USE_SSL"), default=False)
    smtp_use_starttls = _as_bool(os.getenv("SMTP_USE_STARTTLS"), default=not smtp_use_ssl)

    if not smtp_host or not smtp_from:
        if _fallback_to_file_enabled():
            _write_email_to_outbox(to_address, subject, text_body)
            return True
        return False

    message = EmailMessage()
    message["From"] = smtp_from
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(
                smtp_host,
                smtp_port,
                timeout=15,
                context=ssl.create_default_context()
            ) as server:
                if smtp_username and smtp_password:
                    server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                if smtp_use_starttls:
                    server.starttls(context=ssl.create_default_context())
                if smtp_username and smtp_password:
                    server.login(smtp_username, smtp_password)
                server.send_message(message)
        return True
    except Exception as exc:
        logger.error(f"Email send failed to {to_address}: {exc}")
        if _fallback_to_file_enabled():
            _write_email_to_outbox(to_address, subject, text_body)
            return True
        return False


def send_password_reset_email(
    email: str,
    username: str,
    reset_link: str,
    expires_minutes: int = 60
) -> bool:
    """Send a password reset email."""
    subject = "Password Reset Request"
    text_body = (
        f"Hello {username},\n\n"
        "A password reset was requested for your account.\n"
        f"Use this link to reset your password (expires in {expires_minutes} minutes):\n\n"
        f"{reset_link}\n\n"
        "If you did not request this, you can ignore this email.\n"
    )
    sent = send_email(email, subject, text_body)
    if _fallback_to_file_enabled():
        _write_latest_reset_link(reset_link)
    return sent


def send_lockout_email(
    email: str,
    username: str,
    ip_address: str,
    lockout_minutes: int
) -> bool:
    """Send login lockout notification email."""
    subject = "Security Alert: Login Attempts Blocked"
    text_body = (
        f"Hello {username},\n\n"
        "Your account triggered the failed login protection.\n"
        f"Further attempts from IP {ip_address} were blocked for {lockout_minutes} minutes.\n\n"
        "If this was not you, please change your password immediately.\n"
    )
    return send_email(email, subject, text_body)
