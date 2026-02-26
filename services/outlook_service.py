"""
Outlook/Microsoft Email Service

Reads emails via Microsoft Graph API.
Matches the GmailService interface for interoperability.
"""

import logging
import requests
from typing import Optional, List, Dict, Any
from datetime import datetime
import base64

from .oauth_service import MicrosoftOAuthService, OAuthTokenManager

logger = logging.getLogger(__name__)

# Maximum attachment size (10MB)
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024


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
                logger.error("[OUTLOOK] No access token after authentication")
                raise Exception("Microsoft authentication failed. Please reconnect your account.")

        url = f"{self.GRAPH_BASE_URL}{endpoint}"
        logger.debug(f"[OUTLOOK] Making {method} request to: {url}")

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._get_headers(),
                params=params,
                json=json_data
            )

            logger.debug(f"[OUTLOOK] Response status: {response.status_code}")

            if response.status_code == 401:
                logger.warning("[OUTLOOK] Token expired (401), attempting refresh...")
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
                    logger.debug(f"[OUTLOOK] Retry response status: {response.status_code}")
                else:
                    logger.error("[OUTLOOK] Token refresh failed")
                    raise Exception("Microsoft token expired. Please reconnect your account.")

            if response.status_code == 403:
                error_msg = response.json().get("error", {}).get("message", "Access denied")
                logger.error(f"[OUTLOOK] 403: {error_msg}")
                raise Exception(f"Permission denied: {error_msg}. Check API permissions in Azure Portal.")

            if response.status_code >= 400:
                error_text = response.text[:200] if response.text else "Unknown error"
                logger.error(f"[OUTLOOK] {response.status_code}: {response.text}")
                raise Exception(f"Microsoft Graph API error ({response.status_code}): {error_text}")

            return response.json() if response.text else {}

        except requests.exceptions.RequestException as e:
            logger.error(f"[OUTLOOK] Network error: {e}")
            raise Exception(f"Network error connecting to Microsoft: {str(e)}")

    def get_unread_emails(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch unread emails from inbox.

        Args:
            max_results: Maximum number of emails to retrieve

        Returns:
            List of email dictionaries with id, subject, from, date, body
        """
        logger.debug(f"[OUTLOOK] get_unread_emails called (max_results={max_results})")
        return self.search_emails(query="isRead eq false", max_results=max_results)

    def search_emails(self, query: str = '', max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Search emails using OData filter syntax.

        Args:
            query: OData filter query or keyword search (empty string = all recent emails)
            max_results: Maximum number of emails to retrieve

        Returns:
            List of email dictionaries
        """
        logger.debug(f"[OUTLOOK] search_emails called")
        logger.debug(f"  - query: '{query}'")
        logger.debug(f"  - max_results: {max_results}")

        # Debug: Check which account we're querying
        try:
            profile = self._make_request("/me")
            if profile:
                logger.debug(f"  - Authenticated mailbox: {profile.get('mail') or profile.get('userPrincipalName')}")
        except Exception as e:
            logger.warning(f"  - Could not get mailbox info: {e}")

        params = {
            "$top": max_results,
            "$select": "id,subject,from,receivedDateTime,bodyPreview,conversationId,isRead",
            "$orderby": "receivedDateTime desc"
        }

        # Handle different query types
        # Empty query = fetch all recent emails (no filter applied)
        if query:
            # Treat explicit OData expressions as filters
            lowered_query = query.lower()
            is_odata_filter = any(op in lowered_query for op in [
                " eq ", " ne ", " ge ", " le ", " gt ", " lt ",
                "contains(", "startswith(", "endswith(", " and ", " or "
            ])
            if is_odata_filter:
                # OData filter
                params["$filter"] = query
            else:
                # Keyword search
                params["$search"] = f'"{query}"'

        logger.debug(f"  - endpoint: /me/messages")
        logger.debug(f"  - params: {params}")

        result = self._make_request("/me/messages", params=params)

        logger.debug(f"  - API response received: {bool(result)}")
        if result:
            value_count = len(result.get("value", []))
            logger.debug(f"  - Messages in response: {value_count}")

            # Check for pagination
            if "@odata.nextLink" in result:
                logger.debug(f"  - HAS MORE PAGES (nextLink exists)")
            else:
                logger.debug(f"  - NO MORE PAGES (no nextLink)")

            # Debug: log all keys in response
            logger.debug(f"  - Response keys: {list(result.keys())}")
        else:
            logger.debug(f"  - No result from API")

        emails = []
        for msg in result.get("value", []):
            email_data = self._parse_message(msg)
            if email_data:
                emails.append(email_data)

        logger.debug(f"  - Emails parsed successfully: {len(emails)}")
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
            logger.error(f"Error parsing message: {e}")
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
                # Check size before processing (Microsoft provides size field)
                att_size = att.get("size", 0)
                filename = att.get("name", "attachment")
                if att_size > MAX_ATTACHMENT_SIZE:
                    logger.warning(f"Skipping attachment {filename}: too large ({att_size} bytes, max {MAX_ATTACHMENT_SIZE})")
                    continue

                try:
                    # Decode base64 content
                    content_bytes = att.get("contentBytes", "")
                    if content_bytes:
                        data = base64.b64decode(content_bytes)

                        # Verify actual size after decoding
                        if len(data) > MAX_ATTACHMENT_SIZE:
                            logger.warning(f"Skipping attachment {filename}: decoded size too large ({len(data)} bytes)")
                            continue

                        attachments.append({
                            "filename": filename,
                            "mime_type": content_type,
                            "data": data,
                            "size": len(data)
                        })

                        logger.debug(f"Downloaded attachment: {filename} ({content_type}, {len(data)} bytes)")

                except Exception as e:
                    logger.error(f"Error processing attachment: {e}")

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

    def list_folders(self) -> List[Dict[str, Any]]:
        """
        List all mail folders in the user's mailbox.

        Returns:
            List of folder dictionaries with id, displayName, parentFolderId
        """
        result = self._make_request(
            "/me/mailFolders",
            params={"$top": 100, "$select": "id,displayName,parentFolderId,childFolderCount,totalItemCount"}
        )

        if not result:
            return []

        folders = []
        for folder in result.get("value", []):
            folders.append({
                "id": folder.get("id", ""),
                "name": folder.get("displayName", ""),
                "parent_id": folder.get("parentFolderId"),
                "child_count": folder.get("childFolderCount", 0),
                "total_items": folder.get("totalItemCount", 0)
            })

            # Get child folders if any
            if folder.get("childFolderCount", 0) > 0:
                child_folders = self._get_child_folders(folder.get("id"))
                folders.extend(child_folders)

        return folders

    def _get_child_folders(self, parent_id: str, depth: int = 0) -> List[Dict[str, Any]]:
        """Get child folders recursively (max depth 3)."""
        if depth > 3:
            return []

        result = self._make_request(
            f"/me/mailFolders/{parent_id}/childFolders",
            params={"$select": "id,displayName,parentFolderId,childFolderCount,totalItemCount"}
        )

        if not result:
            return []

        folders = []
        for folder in result.get("value", []):
            indent = "  " * (depth + 1)
            folders.append({
                "id": folder.get("id", ""),
                "name": f"{indent}{folder.get('displayName', '')}",
                "parent_id": folder.get("parentFolderId"),
                "child_count": folder.get("childFolderCount", 0),
                "total_items": folder.get("totalItemCount", 0)
            })

            if folder.get("childFolderCount", 0) > 0:
                child_folders = self._get_child_folders(folder.get("id"), depth + 1)
                folders.extend(child_folders)

        return folders

    def get_emails_from_folder(self, folder_id: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch emails from a specific folder.

        Args:
            folder_id: Microsoft folder ID
            max_results: Maximum number of emails to retrieve

        Returns:
            List of email dictionaries
        """

        logger.debug(f"[OUTLOOK] get_emails_from_folder called")
        logger.debug(f"  - folder_id: {folder_id}")
        logger.debug(f"  - max_results: {max_results}")

        params = {
            "$top": max_results,
            "$select": "id,subject,from,receivedDateTime,bodyPreview,conversationId,isRead",
            "$orderby": "receivedDateTime desc"
        }

        endpoint = f"/me/mailFolders/{folder_id}/messages"
        logger.debug(f"  - endpoint: {endpoint}")
        logger.debug(f"  - params: {params}")

        result = self._make_request(endpoint, params=params)

        logger.debug(f"  - API response received: {bool(result)}")
        if result:
            value_count = len(result.get("value", []))
            logger.debug(f"  - Messages in response: {value_count}")
        else:
            logger.debug(f"  - No result from API")

        if not result:
            return []

        emails = []
        for msg in result.get("value", []):
            email_data = self._parse_message(msg)
            if email_data:
                emails.append(email_data)

        logger.debug(f"  - Emails parsed successfully: {len(emails)}")
        return emails


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
            logger.error(f"Outlook service error: {e}")
            return None

    return _outlook_service_instance


def reset_outlook_service():
    """Reset the singleton instance (used after logout)."""
    global _outlook_service_instance
    _outlook_service_instance = None
