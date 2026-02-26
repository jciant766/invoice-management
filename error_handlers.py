"""
Centralized Error Handling
===========================

This file handles all errors in a user-friendly way.

BEGINNER EXPLANATION:
---------------------
Instead of showing ugly browser errors (404, 500, etc.), we catch
them here and return nice JSON messages that the frontend can display
in pretty pop-ups.

Common errors we handle:
- 400: User sent bad data (missing fields, wrong format)
- 422: AI couldn't process the request
- 500: Something broke in our code
- Network: Internet connection issues
"""

import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any
import traceback
import os

logger = logging.getLogger(__name__)

# Check if running in debug/development mode
DEBUG_MODE = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")


class AppError(Exception):
    """
    Custom error class for our application.

    Use this instead of raising generic exceptions.
    It automatically formats errors for the frontend.

    Example:
        raise AppError(
            status_code=400,
            error_type="validation_error",
            message="Please fill in all required fields",
            details={"missing_fields": ["supplier_name", "amount"]}
        )
    """
    def __init__(
        self,
        status_code: int,
        error_type: str,
        message: str,
        details: Dict[str, Any] = None,
        user_action: str = None
    ):
        self.status_code = status_code
        self.error_type = error_type
        self.message = message
        self.details = details or {}
        self.user_action = user_action or "Please try again."
        super().__init__(self.message)


def create_error_response(
    status_code: int,
    error_type: str,
    message: str,
    details: Dict[str, Any] = None,
    user_action: str = None
) -> JSONResponse:
    """
    Create a standardized error response.

    This ensures all errors look the same to the frontend,
    making it easier to display them consistently.

    Args:
        status_code: HTTP status code (400, 422, 500, etc.)
        error_type: Type of error ("validation_error", "ai_error", etc.)
        message: User-friendly message to display
        details: Extra info for debugging (optional)
        user_action: What the user should do (optional)

    Returns:
        JSONResponse with consistent error format
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "type": error_type,
                "message": message,
                "details": details or {},
                "user_action": user_action or "Please try again or contact support."
            }
        }
    )


# --- SPECIFIC ERROR CREATORS ---
# These are shortcuts for common error types

def validation_error(message: str, missing_fields: list = None):
    """
    Return a validation error (missing or invalid fields).

    Example:
        return validation_error(
            "Please fill in all required fields",
            missing_fields=["supplier_name", "invoice_number"]
        )
    """
    return create_error_response(
        status_code=400,
        error_type="validation_error",
        message=message,
        details={"missing_fields": missing_fields} if missing_fields else {},
        user_action="Please check the form and fill in all required fields."
    )


def ai_parsing_error(original_error: str = None):
    """
    Return an AI parsing error.

    This happens when the AI service fails or returns bad data.
    """
    return create_error_response(
        status_code=422,
        error_type="ai_parsing_error",
        message="Unable to extract invoice data from email",
        details={"original_error": str(original_error)} if original_error else {},
        user_action="The email might not contain clear invoice information. Please try manually entering the invoice or check if the email contains the required details."
    )


def database_error(operation: str = "save"):
    """
    Return a database error.

    This happens when we can't read/write to the database.
    """
    return create_error_response(
        status_code=500,
        error_type="database_error",
        message=f"Unable to {operation} data to database",
        user_action="Please try again. If the problem persists, contact support."
    )


def email_service_error(service_type: str = "email"):
    """
    Return an email service error.

    This happens when we can't connect to Gmail or IMAP.
    """
    return create_error_response(
        status_code=503,
        error_type="email_service_error",
        message=f"{service_type} service is not available",
        user_action="Please check your email service configuration or try again later."
    )


def not_found_error(resource: str = "Resource"):
    """
    Return a 404 error.

    This happens when trying to access something that doesn't exist.
    """
    return create_error_response(
        status_code=404,
        error_type="not_found",
        message=f"{resource} not found",
        user_action="Please check the URL or go back to the previous page."
    )


# --- GLOBAL ERROR HANDLER ---
async def app_error_handler(request: Request, exc: Exception):
    """
    Global error handler for the entire application.

    This catches ANY error that wasn't handled elsewhere
    and turns it into a nice user-friendly response.

    Automatically called by FastAPI when errors occur.
    """
    # If it's our custom AppError, handle it nicely
    if isinstance(exc, AppError):
        return create_error_response(
            status_code=exc.status_code,
            error_type=exc.error_type,
            message=exc.message,
            details=exc.details,
            user_action=exc.user_action
        )

    # If it's a FastAPI HTTPException, convert it
    if isinstance(exc, HTTPException):
        return create_error_response(
            status_code=exc.status_code,
            error_type="http_error",
            message=exc.detail,
        )

    # For any other error, log it and return generic message
    logger.error(f"UNHANDLED ERROR: {exc}")
    logger.error(traceback.format_exc())

    return create_error_response(
        status_code=500,
        error_type="internal_error",
        message="An unexpected error occurred",
        details={"error": str(exc)} if DEBUG_MODE else {},  # Only show in debug mode
        user_action="Please try again or contact support if the problem persists."
    )
