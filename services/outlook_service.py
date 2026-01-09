"""
Outlook/Microsoft Email Service

Reads emails via Microsoft Graph API.
Matches the GmailService interface for interoperability.
"""

import requests
from typing import Optional, List, Dict, Any
from datetime import datetime
import base64

from .oauth_service import MicrosoftOAuthService, OAuthTokenManager


class OutlookService:
    """Service for interacting with Microsoft Graph API for email."""

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.access_token = None
        self._authenticate()

    def _authenticate(self):
        """Get access token from stored OAuth tokens."""
        self.access_token = MicrosoftOAuthService.get_access_token()

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers for API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def _make_request(self, endpoint: str, method: str = "GET",
                      params: Dict = None, json_data: Dict = None) -> Optional[Dict]:
        """Make authenticated request to Graph API."""
        if not self.access_token:
            self._authenticate()
            if not self.access_token:
                return None

        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._get_headers(),
                params=params,
                json=json_data
            )

            if response.status_code == 401:
                # Token might be expired, try to refresh
                self._authenticate()
                if self.access_token:
                    response = requests.request(
                        method=method,
                        url=url,
                        headers=self._get_headers(),
                        params=params,
                        json=json_data
                    )

            if response.status_code >= 400:
                print(f"Graph API error: {response.status_code} - {response.text}")
                return None

            return response.json() if response.text else {}

        except Exception as e:
            print(f"Graph API request error: {e}")
            return None

    def get_unread_emails(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch unread emails from inbox.

        Args:
            max_results: Maximum number of emails to retrieve

        Returns:
            List of email dictionaries with id, subject, from, date, body
        """
        return self.search_emails(query="isRead eq false", max_results=max_results)

    def search_emails(self, query: str = '', max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Search emails using OData filter syntax.

        Args:
            query: OData filter query or keyword search
            max_results: Maximum number of emails to retrieve

        Returns:
            List of email dictionaries
        """
        params = {
            "$top": max_results,
            "$select": "id,subject,from,receivedDateTime,bodyPreview,conversationId,isRead",
            "$orderby": "receivedDateTime desc"
        }

        # Handle different query types
        if query:
            if "eq" in query or "ne" in query or "contains" in query:
                # OData filter
                params["$filter"] = query
            else:
                # Keyword search
                params["$search"] = f'"{query}"'

        result = self._make_request("/me/messages", params=params)
        if not result:
            return []

        emails = []
        for msg in result.get("value", []):
            email_data = self._parse_message(msg)
            if email_data:
                emails.append(email_data)

        return emails

    def _parse_message(self, msg: Dict, include_body: bool = False) -> Dict[str, Any]:
        """Parse Graph API message to standard format."""
        try:
            # Extract sender
            from_data = msg.get("from", {}).get("emailAddress", {})
            sender_name = from_data.get("name", "")
            sender_email = from_data.get("address", "")
            sender = f"{sender_name} <{sender_email}>" if sender_name else sender_email

            # Parse date
            date_str = msg.get("receivedDateTime", "")

            return {
                "id": msg.get("id", ""),
                "thread_id": msg.get("conversationId", msg.get("id", "")),
                "subject": msg.get("subject", "(No Subject)"),
                "from": sender,
                "date": date_str,
                "body": msg.get("body", {}).get("content", "") if include_body else "",
                "snippet": msg.get("bodyPreview", "")[:200],
                "is_read": msg.get("isRead", False),
                "attachments": []
            }
        except Exception as e:
            print(f"Error parsing message: {e}")
            return None

    def get_email_by_id(self, email_id: str) -> Optional[Dict[str, Any]]:
        """
        Get full email content by ID.

        Args:
            email_id: Microsoft message ID

        Returns:
            Dictionary with email details or None
        """
        params = {
            "$select": "id,subject,from,receivedDateTime,body,conversationId,isRead,hasAttachments"
        }

        result = self._make_request(f"/me/messages/{email_id}", params=params)
        if not result:
            return None

        email_data = self._parse_message(result, include_body=True)
        if email_data:
            email_data["body"] = result.get("body", {}).get("content", "")

            # Get attachments if present
            if result.get("hasAttachments"):
                email_data["attachments"] = self._get_attachments(email_id)

        return email_data

    def _get_attachments(self, email_id: str) -> List[Dict[str, Any]]:
        """
        Get attachments for an email.

        Args:
            email_id: Microsoft message ID

        Returns:
            List of attachment dictionaries
        """
        result = self._make_request(f"/me/messages/{email_id}/attachments")
        if not result:
            return []

        attachments = []
        for att in result.get("value", []):
            content_type = att.get("contentType", "")

            # Only process images and PDFs
            if content_type.startswith("image/") or content_type == "application/pdf":
                try:
                    # Decode base64 content
                    content_bytes = att.get("contentBytes", "")
                    if content_bytes:
                        data = base64.b64decode(content_bytes)

                        attachments.append({
                            "filename": att.get("name", "attachment"),
                            "mime_type": content_type,
                            "data": data,
                            "size": len(data)
                        })

                        print(f"Downloaded attachment: {att.get('name')} ({content_type}, {len(data)} bytes)")

                except Exception as e:
                    print(f"Error processing attachment: {e}")

        return attachments

    def get_thread_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        Get all messages in a conversation thread.

        Args:
            thread_id: Microsoft conversation ID

        Returns:
            List of email dictionaries in chronological order
        """
        params = {
            "$filter": f"conversationId eq '{thread_id}'",
            "$select": "id,subject,from,receivedDateTime,body,conversationId",
            "$orderby": "receivedDateTime asc",
            "$top": 50
        }

        result = self._make_request("/me/messages", params=params)
        if not result:
            return []

        emails = []
        for msg in result.get("value", []):
            # Get full message with body
            full_msg = self.get_email_by_id(msg.get("id"))
            if full_msg:
                emails.append(full_msg)

        return emails

    def mark_as_read(self, email_id: str) -> bool:
        """
        Mark an email as read.

        Args:
            email_id: Microsoft message ID

        Returns:
            True if successful
        """
        result = self._make_request(
            f"/me/messages/{email_id}",
            method="PATCH",
            json_data={"isRead": True}
        )
        return result is not None


# Singleton instance
_outlook_service_instance = None


def get_outlook_service() -> Optional[OutlookService]:
    """
    Factory function to get Outlook service instance.

    Returns:
        OutlookService instance or None if not authenticated
    """
    global _outlook_service_instance

    # Check if Microsoft OAuth is authenticated
    if not OAuthTokenManager.is_authenticated('microsoft'):
        return None

    if _outlook_service_instance is None:
        try:
            _outlook_service_instance = OutlookService()
        except Exception as e:
            print(f"Outlook service error: {e}")
            return None

    return _outlook_service_instance


def reset_outlook_service():
    """Reset the singleton instance (used after logout)."""
    global _outlook_service_instance
    _outlook_service_instance = None
