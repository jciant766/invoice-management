"""
Gmail Service for fetching forwarded invoice emails.

Handles OAuth2 authentication and email retrieval from Gmail.
Supports both file-based tokens (legacy) and database-stored OAuth tokens.
"""

import os
import base64
import email
from email.header import decode_header
from typing import Optional, List, Dict, Any
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Gmail API scopes - readonly is sufficient for reading emails
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.modify']


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
            print(f"Error getting Gmail profile: {e}")
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
            List of email dictionaries with id, subject, from, date, body
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

            for msg in messages:
                email_data = self.get_email_by_id(msg['id'])
                if email_data:
                    emails.append(email_data)

            return emails

        except HttpError as error:
            print(f"Gmail API error: {error}")
            return []

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
            print(f"Error fetching email {email_id}: {error}")
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
            print(f"Error fetching thread {thread_id}: {error}")
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
                        try:
                            # Download attachment data
                            attachment = self.service.users().messages().attachments().get(
                                userId='me',
                                messageId=email_id,
                                id=attachment_id
                            ).execute()

                            # Decode attachment data
                            data = base64.urlsafe_b64decode(attachment['data'])

                            attachments.append({
                                'filename': filename,
                                'mime_type': mime_type,
                                'data': data,
                                'size': len(data)
                            })

                            print(f"Downloaded attachment: {filename} ({mime_type}, {len(data)} bytes)")

                        except HttpError as error:
                            print(f"Error downloading attachment {filename}: {error}")

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
            print(f"Error marking email as read: {error}")
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
            print(f"Error adding label: {error}")
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
            print(f"Error with labels: {error}")
            return None


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
        print(f"Gmail setup required: {e}")
        return None
    except Exception as e:
        print(f"Gmail service error: {e}")
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
        print(f"Gmail OAuth service error: {e}")
        return None


def reset_gmail_service():
    """Reset the singleton instance (used after logout)."""
    global _gmail_service_instance
    _gmail_service_instance = None
