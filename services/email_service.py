"""
Unified Email Service - Supports Gmail OAuth, Microsoft OAuth, and IMAP

Priority order:
1. OAuth-authenticated providers (Google or Microsoft from database)
2. Legacy file-based Gmail API
3. IMAP with username/password
"""

import logging
import os
from typing import Optional, List, Dict, Any
from .gmail_service import get_gmail_service, get_gmail_service_oauth, reset_gmail_service
from .imap_service import get_imap_service

logger = logging.getLogger(__name__)


class UnifiedEmailService:
    """Wrapper that uses the best available email service."""

    def __init__(self):
        self.service = None
        self.service_type = None
        self._authenticated_email = None
        self._initialize()

    def _initialize(self):
        """Try to initialize email service (OAuth first, then legacy)."""

        # 1. Try OAuth providers first (stored in database)
        try:
            from .oauth_service import OAuthTokenManager, GoogleOAuthService

            active_provider = OAuthTokenManager.get_active_provider()

            if active_provider == 'google':
                # Try Google OAuth
                gmail_service = get_gmail_service_oauth()
                if gmail_service:
                    self.service = gmail_service
                    self.service_type = "Google"
                    self._authenticated_email = GoogleOAuthService.get_authenticated_email()
                    return

            elif active_provider == 'microsoft':
                # Try Microsoft OAuth
                from .outlook_service import get_outlook_service
                from .oauth_service import MicrosoftOAuthService

                outlook_service = get_outlook_service()
                if outlook_service:
                    self.service = outlook_service
                    self.service_type = "Microsoft"
                    self._authenticated_email = MicrosoftOAuthService.get_authenticated_email()
                    return

        except ImportError as e:
            logger.warning(f"OAuth services not available: {e}")
        except Exception as e:
            logger.error(f"OAuth initialization error: {e}")

        # 2. Try legacy file-based Gmail API
        gmail_service = get_gmail_service()
        if gmail_service:
            self.service = gmail_service
            self.service_type = "Gmail API"
            try:
                self._authenticated_email = gmail_service.get_authenticated_email()
            except Exception:
                pass
            return

        # 3. Fall back to IMAP
        imap_service = get_imap_service()
        if imap_service:
            self.service = imap_service
            self.service_type = "IMAP"
            self._authenticated_email = os.getenv("IMAP_EMAIL")
            return

        self.service_type = "Not Connected"

    def is_available(self) -> bool:
        """Check if any email service is available."""
        return self.service is not None

    def get_service_type(self) -> str:
        """Get the type of service being used."""
        return self.service_type

    def get_authenticated_email(self) -> Optional[str]:
        """Get the email address of the authenticated account."""
        return self._authenticated_email

    def get_active_provider(self) -> Optional[str]:
        """Get the active OAuth provider (google, microsoft, or None)."""
        try:
            from .oauth_service import OAuthTokenManager
            return OAuthTokenManager.get_active_provider()
        except Exception:
            return None

    def get_unread_emails(self, max_results: int = 500) -> List[Dict[str, Any]]:
        """Fetch unread emails."""
        if not self.service:
            return []
        return self.service.get_unread_emails(max_results=max_results)

    def search_emails(self, query: str = None, max_results: int = 500) -> List[Dict[str, Any]]:
        """Search emails."""
        if not self.service:
            return []

        if self.service_type in ["Gmail API", "Google"]:
            return self.service.search_emails(query=query or "", max_results=max_results)
        elif self.service_type == "Microsoft":
            # Convert Gmail-style query to OData if needed
            odata_query = self._convert_query_to_odata(query) if query else ""
            return self.service.search_emails(query=odata_query, max_results=max_results)
        else:  # IMAP
            # Convert Gmail-style query to IMAP if needed
            imap_query = self._convert_query_to_imap(query) if query else "ALL"
            return self.service.search_emails(query=imap_query, max_results=max_results)

    def _convert_query_to_imap(self, gmail_query: str) -> str:
        """Convert Gmail search syntax to IMAP."""
        if not gmail_query or gmail_query == "is:unread":
            return "UNSEEN"

        import re
        if "from:" in gmail_query.lower():
            match = re.search(r'from:(\S+)', gmail_query, re.IGNORECASE)
            if match:
                return f'FROM "{match.group(1)}"'

        if "subject:" in gmail_query.lower():
            match = re.search(r'subject:(\S+)', gmail_query, re.IGNORECASE)
            if match:
                return f'SUBJECT "{match.group(1)}"'

        return f'TEXT "{gmail_query}"'

    def _convert_query_to_odata(self, gmail_query: str) -> str:
        """Convert Gmail search syntax to OData filter for Microsoft Graph."""
        if not gmail_query:
            return ""

        if gmail_query == "is:unread":
            return "isRead eq false"

        import re

        # from: query
        if "from:" in gmail_query.lower():
            match = re.search(r'from:(\S+)', gmail_query, re.IGNORECASE)
            if match:
                return f"from/emailAddress/address eq '{match.group(1)}'"

        # subject: query
        if "subject:" in gmail_query.lower():
            match = re.search(r'subject:(.+)', gmail_query, re.IGNORECASE)
            if match:
                subject = match.group(1).strip().strip('"')
                return f"contains(subject, '{subject}')"

        # Default: treat as keyword search (handled differently)
        return gmail_query

    def get_email_by_id(self, email_id: str) -> Optional[Dict[str, Any]]:
        """Get email by ID."""
        if not self.service:
            return None

        if self.service_type in ["Gmail API", "Google"]:
            return self.service.get_email_by_id(email_id)
        elif self.service_type == "Microsoft":
            return self.service.get_email_by_id(email_id)
        else:  # IMAP
            return self.service._fetch_email_by_id(email_id.encode())

    def get_thread_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """Get all messages in a thread."""
        if not self.service:
            return []

        if self.service_type in ["Gmail API", "Google"]:
            return self.service.get_thread_messages(thread_id)
        elif self.service_type == "Microsoft":
            return self.service.get_thread_messages(thread_id)
        else:  # IMAP
            return self.service.get_thread_messages(thread_id)

    def mark_as_read(self, email_id: str) -> bool:
        """Mark email as read."""
        if not self.service:
            return False
        return self.service.mark_as_read(email_id)

    def list_folders(self) -> List[Dict[str, Any]]:
        """List all available folders/labels."""
        if not self.service:
            return []

        if self.service_type in ["Gmail API", "Google"]:
            if hasattr(self.service, 'list_labels'):
                return self.service.list_labels()
        elif self.service_type == "Microsoft":
            if hasattr(self.service, 'list_folders'):
                return self.service.list_folders()

        return []

    def get_emails_from_folder(self, folder_id: str, max_results: int = 150) -> List[Dict[str, Any]]:
        """Fetch emails from a specific folder/label."""
        if not self.service:
            return []

        if self.service_type in ["Gmail API", "Google"]:
            if hasattr(self.service, 'get_emails_from_label'):
                return self.service.get_emails_from_label(folder_id, max_results)
        elif self.service_type == "Microsoft":
            if hasattr(self.service, 'get_emails_from_folder'):
                return self.service.get_emails_from_folder(folder_id, max_results)

        return []


# Singleton instance
_email_service = None


def get_email_service() -> UnifiedEmailService:
    """Get or create the email service instance."""
    global _email_service
    if _email_service is None:
        _email_service = UnifiedEmailService()
    return _email_service


def reset_email_service():
    """Reset the email service singleton (used after OAuth login/logout)."""
    global _email_service
    _email_service = None

    # Also reset underlying services
    reset_gmail_service()

    try:
        from .outlook_service import reset_outlook_service
        reset_outlook_service()
    except ImportError:
        pass
