"""
Universal IMAP Email Service
Works with Gmail, Outlook, Yahoo, and any IMAP-enabled email provider
"""

import imaplib
import email
from email.header import decode_header
from typing import Optional, List, Dict, Any
from datetime import datetime
import re


class IMAPEmailService:
    """Universal email service using IMAP protocol."""

    def __init__(self, email_address: str, password: str, imap_server: str, imap_port: int = 993):
        """
        Initialize IMAP connection.

        Args:
            email_address: Email address (e.g., invoices@council.gov.mt)
            password: Email password or app-specific password
            imap_server: IMAP server address (e.g., imap.gmail.com, outlook.office365.com)
            imap_port: IMAP port (default 993 for SSL)
        """
        self.email_address = email_address
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.mail = None
        self._connect()

    def _connect(self):
        """Establish IMAP connection with SSL."""
        try:
            self.mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.mail.login(self.email_address, self.password)
            return True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {self.imap_server}: {str(e)}")

    def _decode_header(self, header_value: str) -> str:
        """Decode email header that might be encoded."""
        if not header_value:
            return ""

        decoded_parts = decode_header(header_value)
        decoded_string = ""

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_string += part.decode(encoding or 'utf-8', errors='ignore')
            else:
                decoded_string += part

        return decoded_string

    def _get_email_body(self, msg) -> str:
        """Extract email body, preferring plain text."""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break  # Prefer plain text
                    except:
                        pass
                elif content_type == "text/html" and not body:
                    try:
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            except:
                body = str(msg.get_payload())

        return body

    def _get_attachments(self, msg) -> List[Dict[str, Any]]:
        """Extract attachments from email message."""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Check if this is an attachment and is image or PDF
                if "attachment" in content_disposition:
                    if content_type.startswith('image/') or content_type == 'application/pdf':
                        filename = part.get_filename()
                        if filename:
                            try:
                                # Get attachment data
                                data = part.get_payload(decode=True)

                                attachments.append({
                                    'filename': self._decode_header(filename),
                                    'mime_type': content_type,
                                    'data': data,
                                    'size': len(data)
                                })

                                print(f"Downloaded attachment: {filename} ({content_type}, {len(data)} bytes)")

                            except Exception as e:
                                print(f"Error extracting attachment {filename}: {e}")

        return attachments

    def _extract_thread_info(self, msg) -> Dict[str, Any]:
        """Extract thread-related headers for grouping."""
        message_id = msg.get("Message-ID", "")
        in_reply_to = msg.get("In-Reply-To", "")
        references = msg.get("References", "")

        # Thread ID is the first message ID in the references chain, or message ID if new thread
        if references:
            # First reference is usually the original message
            thread_id = references.split()[0].strip("<>")
        elif in_reply_to:
            thread_id = in_reply_to.strip("<>")
        else:
            thread_id = message_id.strip("<>")

        return {
            "thread_id": thread_id,
            "message_id": message_id.strip("<>"),
            "in_reply_to": in_reply_to.strip("<>"),
            "is_reply": bool(in_reply_to or references)
        }

    def search_emails(self, query: str = "ALL", max_results: int = 500, folder: str = "INBOX") -> List[Dict[str, Any]]:
        """
        Search emails using IMAP search syntax.

        Args:
            query: IMAP search query (e.g., "ALL", "UNSEEN", "FROM supplier@example.com")
            max_results: Maximum number of emails to retrieve
            folder: Email folder to search (default: INBOX)

        Returns:
            List of email dictionaries
        """
        try:
            # Select folder
            self.mail.select(folder, readonly=True)

            # Search for emails
            status, messages = self.mail.search(None, query)

            if status != "OK":
                return []

            email_ids = messages[0].split()

            # Limit results
            email_ids = email_ids[-max_results:] if len(email_ids) > max_results else email_ids

            emails = []

            # Fetch emails (in reverse order - newest first)
            for email_id in reversed(email_ids):
                email_data = self._fetch_email_by_id(email_id)
                if email_data:
                    emails.append(email_data)

            # Group by threads and add thread count
            emails = self._add_thread_counts(emails)

            return emails

        except Exception as e:
            print(f"Error searching emails: {e}")
            return []

    def _fetch_email_by_id(self, email_id: bytes) -> Optional[Dict[str, Any]]:
        """Fetch a single email by ID."""
        try:
            status, msg_data = self.mail.fetch(email_id, "(RFC822)")

            if status != "OK":
                return None

            # Parse email
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Extract headers
            subject = self._decode_header(msg.get("Subject", ""))
            sender = self._decode_header(msg.get("From", ""))
            date_str = msg.get("Date", "")

            # Extract body
            body = self._get_email_body(msg)

            # Extract attachments
            attachments = self._get_attachments(msg)

            # Extract thread info
            thread_info = self._extract_thread_info(msg)

            # Create snippet (first 200 chars of body)
            snippet = body[:200].replace('\n', ' ').strip() if body else ""

            return {
                "id": email_id.decode(),
                "thread_id": thread_info["thread_id"],
                "message_id": thread_info["message_id"],
                "subject": subject,
                "from": sender,
                "date": date_str,
                "body": body,
                "snippet": snippet,
                "is_reply": thread_info["is_reply"],
                "attachments": attachments
            }

        except Exception as e:
            print(f"Error fetching email {email_id}: {e}")
            return None

    def _add_thread_counts(self, emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add thread_count to each email based on thread grouping."""
        # Group emails by thread_id
        thread_groups = {}
        for email_data in emails:
            thread_id = email_data.get("thread_id")
            if thread_id:
                if thread_id not in thread_groups:
                    thread_groups[thread_id] = []
                thread_groups[thread_id].append(email_data)

        # Add thread_count to each email
        for email_data in emails:
            thread_id = email_data.get("thread_id")
            email_data["thread_count"] = len(thread_groups.get(thread_id, []))

        return emails

    def get_unread_emails(self, max_results: int = 500) -> List[Dict[str, Any]]:
        """Fetch unread emails."""
        return self.search_emails(query="UNSEEN", max_results=max_results)

    def get_thread_messages(self, thread_id: str, emails_cache: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Get all messages in a thread.

        Args:
            thread_id: Thread ID to search for
            emails_cache: Optional list of already-fetched emails to search through

        Returns:
            List of email dictionaries in chronological order
        """
        if emails_cache:
            # Search in provided cache
            thread_msgs = [e for e in emails_cache if e.get("thread_id") == thread_id]
        else:
            # Fetch all emails and filter (less efficient)
            all_emails = self.search_emails(query="ALL", max_results=1000)
            thread_msgs = [e for e in all_emails if e.get("thread_id") == thread_id]

        # Sort by date (chronological)
        thread_msgs.sort(key=lambda x: x.get("date", ""))

        return thread_msgs

    def mark_as_read(self, email_id: str) -> bool:
        """Mark an email as read."""
        try:
            self.mail.select("INBOX")
            self.mail.store(email_id.encode(), '+FLAGS', '\\Seen')
            return True
        except Exception as e:
            print(f"Error marking email as read: {e}")
            return False

    def close(self):
        """Close IMAP connection."""
        try:
            if self.mail:
                self.mail.close()
                self.mail.logout()
        except:
            pass


# Email provider configurations
EMAIL_PROVIDERS = {
    "gmail": {
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
        "note": "Use app-specific password, not regular password"
    },
    "outlook": {
        "imap_server": "outlook.office365.com",
        "imap_port": 993,
        "note": "Works with Outlook.com, Hotmail, Live, Office365"
    },
    "yahoo": {
        "imap_server": "imap.mail.yahoo.com",
        "imap_port": 993,
        "note": "Requires app password"
    },
    "icloud": {
        "imap_server": "imap.mail.me.com",
        "imap_port": 993,
        "note": "Requires app-specific password"
    },
    "custom": {
        "imap_server": "",
        "imap_port": 993,
        "note": "Enter your email provider's IMAP server"
    }
}


# Singleton instance
_imap_service_instance = None


def get_imap_service(email_address: str = None, password: str = None,
                     imap_server: str = None, imap_port: int = 993) -> Optional[IMAPEmailService]:
    """
    Factory function to create IMAP service (cached).

    If no parameters provided, tries to load from environment variables.
    """
    global _imap_service_instance
    import os

    # If already initialized, return cached instance
    if _imap_service_instance is not None:
        return _imap_service_instance

    email_address = email_address or os.getenv("IMAP_EMAIL")
    password = password or os.getenv("IMAP_PASSWORD")
    imap_server = imap_server or os.getenv("IMAP_SERVER")
    imap_port = imap_port or int(os.getenv("IMAP_PORT", 993))

    if not all([email_address, password, imap_server]):
        print("IMAP credentials not configured. Set environment variables: IMAP_EMAIL, IMAP_PASSWORD, IMAP_SERVER")
        return None

    try:
        _imap_service_instance = IMAPEmailService(email_address, password, imap_server, imap_port)
        return _imap_service_instance
    except Exception as e:
        print(f"IMAP service error: {e}")
        return None
