"""
OAuth Service - Handles Google and Microsoft OAuth authentication

Provides:
- Encrypted token storage in database
- Google OAuth web flow for Gmail access
- Microsoft OAuth flow for Outlook access
- Automatic token refresh
"""

import os
import json
import time
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet, InvalidToken

# Google OAuth imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

# Microsoft OAuth imports
import msal

from database import SessionLocal
from models import Setting


# =============================================================================
# Token Encryption
# =============================================================================

def get_encryption_key() -> bytes:
    """Get or generate encryption key for token storage."""
    key = os.getenv("OAUTH_ENCRYPTION_KEY")
    if not key:
        # Generate a key if not set (for development)
        # In production, this should be set in .env
        key = Fernet.generate_key().decode()
        print(f"WARNING: No OAUTH_ENCRYPTION_KEY set. Generated temporary key.")
        print(f"Add this to your .env file: OAUTH_ENCRYPTION_KEY={key}")
    return key.encode() if isinstance(key, str) else key


def encrypt_token(token_data: Dict[str, Any]) -> str:
    """Encrypt token data for database storage."""
    fernet = Fernet(get_encryption_key())
    json_data = json.dumps(token_data)
    encrypted = fernet.encrypt(json_data.encode())
    return encrypted.decode()


def decrypt_token(encrypted_data: str) -> Optional[Dict[str, Any]]:
    """Decrypt token data from database."""
    try:
        fernet = Fernet(get_encryption_key())
        decrypted = fernet.decrypt(encrypted_data.encode())
        return json.loads(decrypted.decode())
    except (InvalidToken, json.JSONDecodeError) as e:
        print(f"Error decrypting token: {e}")
        return None


# =============================================================================
# Token Storage (Database)
# =============================================================================

class OAuthTokenManager:
    """Manages OAuth token storage in database."""

    TOKEN_KEY_PREFIX = "oauth_tokens_"
    PROVIDER_KEY = "oauth_active_provider"

    @staticmethod
    def save_tokens(provider: str, tokens: Dict[str, Any]) -> bool:
        """Save encrypted tokens to database."""
        db = SessionLocal()
        try:
            key = f"{OAuthTokenManager.TOKEN_KEY_PREFIX}{provider}"
            encrypted = encrypt_token(tokens)

            # Upsert the setting
            setting = db.query(Setting).filter(Setting.key == key).first()
            if setting:
                setting.value = encrypted
            else:
                setting = Setting(key=key, value=encrypted)
                db.add(setting)

            # Also save the active provider
            provider_setting = db.query(Setting).filter(
                Setting.key == OAuthTokenManager.PROVIDER_KEY
            ).first()
            if provider_setting:
                provider_setting.value = provider
            else:
                provider_setting = Setting(
                    key=OAuthTokenManager.PROVIDER_KEY,
                    value=provider
                )
                db.add(provider_setting)

            db.commit()
            return True
        except Exception as e:
            print(f"Error saving tokens: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    @staticmethod
    def get_tokens(provider: str) -> Optional[Dict[str, Any]]:
        """Retrieve and decrypt tokens from database."""
        db = SessionLocal()
        try:
            key = f"{OAuthTokenManager.TOKEN_KEY_PREFIX}{provider}"
            setting = db.query(Setting).filter(Setting.key == key).first()
            if setting:
                return decrypt_token(setting.value)
            return None
        finally:
            db.close()

    @staticmethod
    def delete_tokens(provider: str = None) -> bool:
        """Delete tokens from database. If provider is None, delete all."""
        db = SessionLocal()
        try:
            if provider:
                key = f"{OAuthTokenManager.TOKEN_KEY_PREFIX}{provider}"
                db.query(Setting).filter(Setting.key == key).delete()
            else:
                # Delete all OAuth tokens
                db.query(Setting).filter(
                    Setting.key.like(f"{OAuthTokenManager.TOKEN_KEY_PREFIX}%")
                ).delete(synchronize_session=False)

            # Clear active provider
            db.query(Setting).filter(
                Setting.key == OAuthTokenManager.PROVIDER_KEY
            ).delete()

            db.commit()
            return True
        except Exception as e:
            print(f"Error deleting tokens: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    @staticmethod
    def get_active_provider() -> Optional[str]:
        """Get the currently active OAuth provider."""
        db = SessionLocal()
        try:
            setting = db.query(Setting).filter(
                Setting.key == OAuthTokenManager.PROVIDER_KEY
            ).first()
            return setting.value if setting else None
        finally:
            db.close()

    @staticmethod
    def is_authenticated(provider: str = None) -> bool:
        """Check if tokens exist for a provider (or any provider if None)."""
        if provider:
            tokens = OAuthTokenManager.get_tokens(provider)
            return tokens is not None
        else:
            # Check if any provider is authenticated
            return OAuthTokenManager.get_active_provider() is not None


# =============================================================================
# Google OAuth Service
# =============================================================================

class GoogleOAuthService:
    """Handles Google OAuth web flow for Gmail access."""

    SCOPES = [
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.modify',
        'https://www.googleapis.com/auth/userinfo.email'
    ]

    def __init__(self):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.redirect_uri = os.getenv(
            "GOOGLE_REDIRECT_URI",
            "http://localhost:8000/auth/google/callback"
        )

    def is_configured(self) -> bool:
        """Check if Google OAuth is configured."""
        return bool(self.client_id and self.client_secret)

    def get_authorization_url(self, state: str = None) -> Optional[str]:
        """Generate Google OAuth authorization URL."""
        if not self.is_configured():
            return None

        # Include 'openid' since Google adds it automatically
        scopes_with_openid = self.SCOPES + ['openid']

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=scopes_with_openid
        )
        flow.redirect_uri = self.redirect_uri

        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
            state=state
        )

        return authorization_url

    def handle_callback(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens.

        Returns:
            Dict with 'success', 'email', 'error' keys
        """
        if not self.is_configured():
            return {"success": False, "error": "Google OAuth not configured"}

        try:
            # Include 'openid' in scopes since Google adds it automatically
            scopes_with_openid = self.SCOPES + ['openid']

            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [self.redirect_uri]
                    }
                },
                scopes=scopes_with_openid
            )
            flow.redirect_uri = self.redirect_uri

            # Exchange code for tokens
            flow.fetch_token(code=code)
            credentials = flow.credentials

            # Get user email
            from googleapiclient.discovery import build
            service = build('oauth2', 'v2', credentials=credentials)
            user_info = service.userinfo().get().execute()
            email = user_info.get('email', 'Unknown')

            # Prepare token data for storage
            token_data = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': list(credentials.scopes) if credentials.scopes else self.SCOPES,
                'expiry': credentials.expiry.isoformat() if credentials.expiry else None,
                'email': email
            }

            # Save tokens
            if OAuthTokenManager.save_tokens('google', token_data):
                return {"success": True, "email": email}
            else:
                return {"success": False, "error": "Failed to save tokens"}

        except Exception as e:
            print(f"Google OAuth callback error: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_credentials() -> Optional[Credentials]:
        """Get Google credentials from stored tokens."""
        tokens = OAuthTokenManager.get_tokens('google')
        if not tokens:
            return None

        try:
            from datetime import datetime

            expiry = None
            if tokens.get('expiry'):
                expiry = datetime.fromisoformat(tokens['expiry'])

            credentials = Credentials(
                token=tokens['token'],
                refresh_token=tokens.get('refresh_token'),
                token_uri=tokens.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=tokens.get('client_id'),
                client_secret=tokens.get('client_secret'),
                scopes=tokens.get('scopes')
            )

            # Check if token needs refresh
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())

                # Update stored tokens
                new_token_data = {
                    'token': credentials.token,
                    'refresh_token': credentials.refresh_token,
                    'token_uri': credentials.token_uri,
                    'client_id': credentials.client_id,
                    'client_secret': credentials.client_secret,
                    'scopes': list(credentials.scopes) if credentials.scopes else [],
                    'expiry': credentials.expiry.isoformat() if credentials.expiry else None,
                    'email': tokens.get('email')
                }
                OAuthTokenManager.save_tokens('google', new_token_data)

            return credentials

        except Exception as e:
            print(f"Error getting Google credentials: {e}")
            return None

    @staticmethod
    def get_authenticated_email() -> Optional[str]:
        """Get the email address of the authenticated Google account."""
        tokens = OAuthTokenManager.get_tokens('google')
        return tokens.get('email') if tokens else None


# =============================================================================
# Microsoft OAuth Service
# =============================================================================

class MicrosoftOAuthService:
    """Handles Microsoft OAuth flow for Outlook access."""

    SCOPES = [
        'https://graph.microsoft.com/Mail.Read',
        'https://graph.microsoft.com/Mail.ReadWrite',
        'https://graph.microsoft.com/User.Read'
    ]

    AUTHORITY = "https://login.microsoftonline.com/common"

    def __init__(self):
        self.client_id = os.getenv("MICROSOFT_CLIENT_ID")
        self.client_secret = os.getenv("MICROSOFT_CLIENT_SECRET")
        self.redirect_uri = os.getenv(
            "MICROSOFT_REDIRECT_URI",
            "http://localhost:8000/auth/microsoft/callback"
        )
        self.tenant_id = os.getenv("MICROSOFT_TENANT_ID", "common")

        if self.tenant_id != "common":
            self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        else:
            self.authority = self.AUTHORITY

    def is_configured(self) -> bool:
        """Check if Microsoft OAuth is configured."""
        return bool(self.client_id and self.client_secret)

    def _get_msal_app(self) -> Optional[msal.ConfidentialClientApplication]:
        """Get MSAL confidential client application."""
        if not self.is_configured():
            return None

        return msal.ConfidentialClientApplication(
            self.client_id,
            authority=self.authority,
            client_credential=self.client_secret
        )

    def get_authorization_url(self, state: str = None) -> Optional[str]:
        """Generate Microsoft OAuth authorization URL."""
        app = self._get_msal_app()
        if not app:
            return None

        auth_url = app.get_authorization_request_url(
            scopes=self.SCOPES,
            redirect_uri=self.redirect_uri,
            state=state
        )

        return auth_url

    def handle_callback(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens.

        Returns:
            Dict with 'success', 'email', 'error' keys
        """
        app = self._get_msal_app()
        if not app:
            return {"success": False, "error": "Microsoft OAuth not configured"}

        try:
            # Exchange code for tokens
            result = app.acquire_token_by_authorization_code(
                code=code,
                scopes=self.SCOPES,
                redirect_uri=self.redirect_uri
            )

            if "error" in result:
                return {
                    "success": False,
                    "error": result.get("error_description", result.get("error"))
                }

            # Get user info
            import requests
            headers = {"Authorization": f"Bearer {result['access_token']}"}
            user_response = requests.get(
                "https://graph.microsoft.com/v1.0/me",
                headers=headers
            )
            user_data = user_response.json()
            email = user_data.get("mail") or user_data.get("userPrincipalName", "Unknown")

            # Prepare token data
            token_data = {
                'access_token': result['access_token'],
                'refresh_token': result.get('refresh_token'),
                'token_type': result.get('token_type', 'Bearer'),
                'expires_in': result.get('expires_in'),
                'expires_at': time.time() + result.get('expires_in', 3600),
                'scope': result.get('scope', ''),
                'email': email
            }

            # Save tokens
            if OAuthTokenManager.save_tokens('microsoft', token_data):
                return {"success": True, "email": email}
            else:
                return {"success": False, "error": "Failed to save tokens"}

        except Exception as e:
            print(f"Microsoft OAuth callback error: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_access_token() -> Optional[str]:
        """Get valid Microsoft access token, refreshing if needed."""
        tokens = OAuthTokenManager.get_tokens('microsoft')
        if not tokens:
            return None

        try:
            # Check if token is expired
            expires_at = tokens.get('expires_at', 0)
            if time.time() > expires_at - 300:  # 5 minute buffer
                # Token expired or expiring soon, try to refresh
                refresh_token = tokens.get('refresh_token')
                if not refresh_token:
                    return None

                service = MicrosoftOAuthService()
                app = service._get_msal_app()
                if not app:
                    return None

                result = app.acquire_token_by_refresh_token(
                    refresh_token=refresh_token,
                    scopes=MicrosoftOAuthService.SCOPES
                )

                if "error" in result:
                    print(f"Token refresh error: {result.get('error_description')}")
                    return None

                # Update stored tokens
                tokens['access_token'] = result['access_token']
                tokens['refresh_token'] = result.get('refresh_token', refresh_token)
                tokens['expires_at'] = time.time() + result.get('expires_in', 3600)
                OAuthTokenManager.save_tokens('microsoft', tokens)

            return tokens.get('access_token')

        except Exception as e:
            print(f"Error getting Microsoft access token: {e}")
            return None

    @staticmethod
    def get_authenticated_email() -> Optional[str]:
        """Get the email address of the authenticated Microsoft account."""
        tokens = OAuthTokenManager.get_tokens('microsoft')
        return tokens.get('email') if tokens else None


# =============================================================================
# Helper Functions
# =============================================================================

def get_authenticated_email() -> Optional[str]:
    """Get email of currently authenticated provider."""
    provider = OAuthTokenManager.get_active_provider()
    if provider == 'google':
        return GoogleOAuthService.get_authenticated_email()
    elif provider == 'microsoft':
        return MicrosoftOAuthService.get_authenticated_email()
    return None


def is_oauth_configured() -> Dict[str, bool]:
    """Check which OAuth providers are configured."""
    return {
        'google': GoogleOAuthService().is_configured(),
        'microsoft': MicrosoftOAuthService().is_configured()
    }
