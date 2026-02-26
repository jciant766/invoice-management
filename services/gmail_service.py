"""
Gmail Service for fetching forwarded invoice emails.

Handles OAuth2 authentication and email retrieval from Gmail.
Supports both file-based tokens (legacy) and database-stored OAuth tokens.
"""

import logging
import os
import base64
import email
import time
from email.header import decode_header
from typing import Optional, List, Dict, Any
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Gmail API scopes - readonly is sufficient for reading emails
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.modify']

# Maximum attachment size (10MB)
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024


class GmailService:
    """Service for interacting with Gmail API."""

    def __init__(self, credentials_path: str = "credentials.json", token_path: str = "token.json", credentials: Credentials = None):
        """
        Initialize Gmail service.

        Args:
            credentials_path: Path to OAuth credentials file (legacy)
            token_path: Path to token file (legacy)
            credentials: Pre-authenticated credentials object (for OAuth flow)
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        self._credentials = credentials

        if credentials:
            # Use provided credentials (from OAuth flow)
            self._init_with_credentials(credentials)
        else:
            # Legacy file-based auth
            self._authenticate()

    def _init_with_credentials(self, credentials: Credentials):
        """Initialize service with provided credentials."""
        self.service = build('gmail', 'v1', credentials=credentials)
        self._credentials = credentials

    @classmethod
    def from_oauth_credentials(cls, credentials: Credentials) -> 'GmailService':
        """
        Create GmailService from OAuth credentials (database-stored tokens).

        Args:
            credentials: Google OAuth credentials object

        Returns:
            GmailService instance
        """
        instance = cls.__new__(cls)
        instance.credentials_path = None
        instance.token_path = None
        instance.service = None
        instance._credentials = credentials
        instance._init_with_credentials(credentials)
        return instance

    def get_authenticated_email(self) -> Optional[str]:
        """Get the email address of the authenticated account."""
        try:
            profile = self.service.users().getProfile(userId='me').execute()
            return profile.get('emailAddress')
        except Exception as e:
            logger.error(f"Error getting Gmail profile: {e}")
            return None

    def _authenticate(self):
        """Authenticate with Gmail API using OAuth2 (legacy file-based method).

        NOTE: This method only works with EXISTING token.json files.
        It will NOT start a new browser-based OAuth flow.
        For new authentication, use the OAuth login buttons instead.
        """
        creds = None

        # Check for existing token - ONLY proceed if token.json exists
        if not os.path.exists(self.token_path):
            raise FileNotFoundError(
                f"No token file found at {self.token_path}. "
                "Please use the 'Login with Google' button to authenticate."
            )

        creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        # If credentials expired, try to refresh
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save refreshed credentials
                with open(self.token_path, 'w') as token:
                    token.write(creds.to_json())
            else:
                # Can't refresh - need to re-authenticate via OAuth buttons
                raise RuntimeError(
                    "Gmail credentials expired and cannot be refreshed. "
                    "Please use the 'Login with Google' button to reconnect."
                )

        self.service = build('gmail', 'v1', credentials=creds)

    def get_unread_emails(self, max_results: int = 10, label: str = "INBOX") -> List[Dict[str, Any]]:
        """
        Fetch unread emails from inbox.

        Args:
            max_results: Maximum number of emails to retrieve
            label: Gmail label to search in

        Returns:
            List of email dictionaries with id, subject, from, date, body
        """
        return self.search_emails(query='is:unread', max_results=max_results, label=label)

    def search_emails(self, query: str = '', max_results: int = 20, label: str = "INBOX") -> List[Dict[str, Any]]:
        """
        Search emails with Gmail query syntax.

        Args:
            query: Gmail search query (e.g., 'from:supplier@example.com', 'subject:invoice', 'is:unread')
            max_results: Maximum number of emails to retrieve
            label: Gmail label to search in

        Returns:
            List of email dictionaries with id, subject, from, date, snippet
        """
        try:
            # Search for emails with query
            results = self.service.users().messages().list(
                userId='me',
                labelIds=[label] if label else None,
                q=query if query else None,
                maxResults=max_results
            ).execute()

            messages = results.get('messages', [])
            emails = []

            # Use batch request to fetch metadata for all emails efficiently
            # This is MUCH faster than individual requests
            if messages:
                emails = self._batch_get_email_metadata(messages)

            return emails

        except HttpError as error:
            logger.error(f"Gmail API error: {error}")
            return []

    def _batch_get_email_metadata(self, messages: List[Dict]) -> List[Dict[str, Any]]:
        """
        Fetch email metadata for multiple messages using batch requests.
        Only fetches headers and snippet - NOT full body (much faster).

        Args:
            messages: List of message objects with 'id' key

        Returns:
            List of email metadata dictionaries
        """
        emails = []

        # Use smaller batch size to avoid Gmail rate limits (429 errors)
        # Gmail allows 100 per batch but rate limits concurrent requests
        batch_size = 50

        for i in range(0, len(messages), batch_size):
            batch_messages = messages[i:i + batch_size]

            # Create batch request
            batch = self.service.new_batch_http_request()

            def create_callback(msg_id):
                def callback(request_id, response, exception):
                    if exception:
                        logger.error(f"Error fetching email {msg_id}: {exception}")
                        return

                    headers = response.get('payload', {}).get('headers', [])

                    subject = ''
                    sender = ''
                    date = ''

                    for header in headers:
                        name = header.get('name', '').lower()
                        if name == 'subject':
                            subject = header.get('value', '')
                        elif name == 'from':
                            sender = header.get('value', '')
                        elif name == 'date':
                            date = header.get('value', '')

                    emails.append({
                        'id': response['id'],
                        'thread_id': response.get('threadId', ''),
                        'subject': subject,
                        'from': sender,
                        'date': date,
                        'snippet': response.get('snippet', ''),
                        'body': '',  # Not fetched in list view for speed
                        'attachments': []  # Not fetched in list view
                    })
                return callback

            # Add each message to the batch - only fetch metadata, not full content
            for msg in batch_messages:
                batch.add(
                    self.service.users().messages().get(
                        userId='me',
                        id=msg['id'],
                        format='metadata',  # Only headers, much faster!
                        metadataHeaders=['Subject', 'From', 'Date']
                    ),
                    callback=create_callback(msg['id'])
                )

            # Execute batch with retry on rate limit
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    batch.execute()
                    break
                except HttpError as e:
                    if e.resp.status == 429 and attempt < max_retries - 1:
                        # Rate limited - wait and retry
                        wait_time = (attempt + 1) * 2  # 2s, 4s, 6s
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                    else:
                        raise

            # Small delay between batches to avoid rate limiting
            if i + batch_size < len(messages):
                time.sleep(0.3)  # 300ms between batches

        return emails

    def get_email_by_id(self, email_id: str) -> Optional[Dict[str, Any]]:
        """
        Get full email content by ID.

        Args:
            email_id: Gmail message ID

        Returns:
            Dictionary with email details or None
        """
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=email_id,
                format='full'
            ).execute()

            headers = message.get('payload', {}).get('headers', [])

            # Extract headers
            subject = ''
            sender = ''
            date = ''

            for header in headers:
                name = header.get('name', '').lower()
                if name == 'subject':
                    subject = header.get('value', '')
                elif name == 'from':
                    sender = header.get('value', '')
                elif name == 'date':
                    date = header.get('value', '')

            # Extract body
            body = self._get_email_body(message.get('payload', {}))

            # Extract attachments
            attachments = self._get_attachments(message.get('payload', {}), email_id)

            return {
                'id': email_id,
                'thread_id': message.get('threadId', ''),
                'subject': subject,
                'from': sender,
                'date': date,
                'body': body,
                'snippet': message.get('snippet', ''),
                'attachments': attachments
            }

        except HttpError as error:
            logger.error(f"Error fetching email {email_id}: {error}")
            return None

    def get_thread_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        Get all messages in a thread.

        Args:
            thread_id: Gmail thread ID

        Returns:
            List of email dictionaries in chronological order
        """
        try:
            thread = self.service.users().threads().get(
                userId='me',
                id=thread_id,
                format='full'
            ).execute()

            messages = thread.get('messages', [])
            email_list = []

            for message in messages:
                headers = message.get('payload', {}).get('headers', [])

                # Extract headers
                subject = ''
                sender = ''
                date = ''

                for header in headers:
                    name = header.get('name', '').lower()
                    if name == 'subject':
                        subject = header.get('value', '')
                    elif name == 'from':
                        sender = header.get('value', '')
                    elif name == 'date':
                        date = header.get('value', '')

                # Extract body
                body = self._get_email_body(message.get('payload', {}))

                # Extract attachments
                attachments = self._get_attachments(message.get('payload', {}), message['id'])

                email_list.append({
                    'id': message['id'],
                    'thread_id': thread_id,
                    'subject': subject,
                    'from': sender,
                    'date': date,
                    'body': body,
                    'snippet': message.get('snippet', ''),
                    'internal_date': message.get('internalDate', ''),
                    'attachments': attachments
                })

            # Sort by internal date (chronological order)
            email_list.sort(key=lambda x: x.get('internal_date', '0'))

            return email_list

        except HttpError as error:
            logger.error(f"Error fetching thread {thread_id}: {error}")
            return []

    def _get_email_body(self, payload: Dict) -> str:
        """
        Extract email body from payload, handling multipart messages.

        Args:
            payload: Gmail message payload

        Returns:
            Plain text email body
        """
        body = ''

        if 'body' in payload and payload['body'].get('data'):
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')

        if 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType', '')

                if mime_type == 'text/plain':
                    if part.get('body', {}).get('data'):
                        body = base64.urlsafe_b64decode(
                            part['body']['data']
                        ).decode('utf-8')
                        break
                elif mime_type == 'text/html' and not body:
                    # Fallback to HTML if no plain text
                    if part.get('body', {}).get('data'):
                        body = base64.urlsafe_b64decode(
                            part['body']['data']
                        ).decode('utf-8')
                elif mime_type.startswith('multipart/'):
                    # Recursively handle nested multipart
                    body = self._get_email_body(part)
                    if body:
                        break

        return body

    def _get_attachments(self, payload: Dict, email_id: str) -> List[Dict[str, Any]]:
        """
        Extract attachments from email payload.

        Args:
            payload: Gmail message payload
            email_id: Email ID for fetching attachment data

        Returns:
            List of attachment dictionaries with filename, mime_type, and data
        """
        attachments = []

        if 'parts' in payload:
            for part in payload['parts']:
                # Check if part is an attachment
                filename = part.get('filename', '')
                mime_type = part.get('mimeType', '')

                # Only process image and PDF attachments
                if filename and (mime_type.startswith('image/') or mime_type == 'application/pdf'):
                    attachment_id = part.get('body', {}).get('attachmentId')

                    if attachment_id:
                        # Check estimated size before downloading (body.size is in bytes)
                        estimated_size = part.get('body', {}).get('size', 0)
                        if estimated_size > MAX_ATTACHMENT_SIZE:
                            logger.warning(f"Skipping attachment {filename}: too large ({estimated_size} bytes, max {MAX_ATTACHMENT_SIZE})")
                            continue

                        try:
                            # Download attachment data
                            attachment = self.service.users().messages().attachments().get(
                                userId='me',
                                messageId=email_id,
                                id=attachment_id
                            ).execute()

                            # Decode attachment data
                            data = base64.urlsafe_b64decode(attachment['data'])

                            # Verify actual size after decoding
                            if len(data) > MAX_ATTACHMENT_SIZE:
                                logger.warning(f"Skipping attachment {filename}: decoded size too large ({len(data)} bytes)")
                                continue

                            attachments.append({
                                'filename': filename,
                                'mime_type': mime_type,
                                'data': data,
                                'size': len(data)
                            })

                            logger.debug(f"Downloaded attachment: {filename} ({mime_type}, {len(data)} bytes)")

                        except HttpError as error:
                            logger.error(f"Error downloading attachment {filename}: {error}")

                # Recursively check nested multipart
                elif mime_type.startswith('multipart/'):
                    nested_attachments = self._get_attachments(part, email_id)
                    attachments.extend(nested_attachments)

        return attachments

    def mark_as_read(self, email_id: str) -> bool:
        """
        Mark an email as read by removing UNREAD label.

        Args:
            email_id: Gmail message ID

        Returns:
            True if successful
        """
        try:
            self.service.users().messages().modify(
                userId='me',
                id=email_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            return True
        except HttpError as error:
            logger.error(f"Error marking email as read: {error}")
            return False

    def add_label(self, email_id: str, label_name: str) -> bool:
        """
        Add a label to an email (creates label if doesn't exist).

        Args:
            email_id: Gmail message ID
            label_name: Name of label to add

        Returns:
            True if successful
        """
        try:
            # Get or create label
            label_id = self._get_or_create_label(label_name)

            if label_id:
                self.service.users().messages().modify(
                    userId='me',
                    id=email_id,
                    body={'addLabelIds': [label_id]}
                ).execute()
                return True
            return False

        except HttpError as error:
            logger.error(f"Error adding label: {error}")
            return False

    def _get_or_create_label(self, label_name: str) -> Optional[str]:
        """Get label ID, creating it if it doesn't exist."""
        try:
            # List existing labels
            results = self.service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])

            for label in labels:
                if label['name'].lower() == label_name.lower():
                    return label['id']

            # Create label if not found
            label_body = {
                'name': label_name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            created = self.service.users().labels().create(
                userId='me',
                body=label_body
            ).execute()
            return created['id']

        except HttpError as error:
            logger.error(f"Error with labels: {error}")
            return None

    def list_labels(self) -> List[Dict[str, Any]]:
        """
        List all labels (folders) in the user's Gmail account.

        Returns:
            List of label dictionaries with id, name, type
        """
        try:
            results = self.service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])

            # Get detailed info for each label
            folder_list = []
            for label in labels:
                label_type = label.get('type', 'user')

                # Skip system labels we don't want to show
                if label['id'] in ['SPAM', 'TRASH', 'DRAFT', 'SENT', 'STARRED',
                                   'IMPORTANT', 'CHAT', 'CATEGORY_PERSONAL',
                                   'CATEGORY_SOCIAL', 'CATEGORY_PROMOTIONS',
                                   'CATEGORY_UPDATES', 'CATEGORY_FORUMS']:
                    continue

                # Get message count for user labels
                total_items = 0
                if label_type == 'user':
                    try:
                        label_info = self.service.users().labels().get(
                            userId='me',
                            id=label['id']
                        ).execute()
                        total_items = label_info.get('messagesTotal', 0)
                    except Exception:
                        pass

                folder_list.append({
                    "id": label['id'],
                    "name": label['name'],
                    "type": label_type,
                    "total_items": total_items
                })

            # Sort: INBOX first, then user labels alphabetically
            def sort_key(l):
                if l['id'] == 'INBOX':
                    return (0, '')
                if l['type'] == 'system':
                    return (1, l['name'])
                return (2, l['name'])

            folder_list.sort(key=sort_key)

            return folder_list

        except HttpError as error:
            logger.error(f"Error listing labels: {error}")
            return []

    def get_emails_from_label(self, label_id: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch emails from a specific label (folder).

        Args:
            label_id: Gmail label ID
            max_results: Maximum number of emails to retrieve

        Returns:
            List of email dictionaries
        """
        return self.search_emails(query='', max_results=max_results, label=label_id)


# Singleton instance
_gmail_service_instance = None


def get_gmail_service() -> Optional[GmailService]:
    """
    Factory function to get Gmail service instance (cached).

    Returns:
        GmailService instance or None if credentials not available
    """
    global _gmail_service_instance

    if _gmail_service_instance is not None:
        return _gmail_service_instance

    try:
        _gmail_service_instance = GmailService()
        return _gmail_service_instance
    except FileNotFoundError as e:
        logger.warning(f"Gmail setup required: {e}")
        return None
    except Exception as e:
        logger.error(f"Gmail service error: {e}")
        return None


def get_gmail_service_oauth() -> Optional[GmailService]:
    """
    Get Gmail service using OAuth tokens from database.

    Returns:
        GmailService instance or None if not authenticated
    """
    global _gmail_service_instance

    if _gmail_service_instance is not None:
        return _gmail_service_instance

    try:
        from .oauth_service import GoogleOAuthService, OAuthTokenManager

        # Check if Google OAuth is authenticated
        if not OAuthTokenManager.is_authenticated('google'):
            return None

        credentials = GoogleOAuthService.get_credentials()
        if not credentials:
            return None

        _gmail_service_instance = GmailService.from_oauth_credentials(credentials)
        return _gmail_service_instance

    except Exception as e:
        logger.error(f"Gmail OAuth service error: {e}")
        return None


def reset_gmail_service():
    """Reset the singleton instance (used after logout)."""
    global _gmail_service_instance
    _gmail_service_instance = None
