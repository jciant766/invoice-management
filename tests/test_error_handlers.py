"""
Tests for the centralized error handling system.

Tests cover:
- AppError creation and default values
- create_error_response() structure and status codes
- Factory functions: validation_error, ai_parsing_error,
  database_error, email_service_error, not_found_error
"""
import pytest
from error_handlers import (
    AppError,
    create_error_response,
    validation_error,
    ai_parsing_error,
    database_error,
    email_service_error,
    not_found_error,
)


# --- AppError class tests ---

@pytest.mark.unit
def test_app_error_with_all_fields():
    """AppError stores all provided fields correctly."""
    details = {"missing_fields": ["supplier_name", "amount"]}
    err = AppError(
        status_code=400,
        error_type="validation_error",
        message="Bad request",
        details=details,
        user_action="Fix the form.",
    )

    assert err.status_code == 400
    assert err.error_type == "validation_error"
    assert err.message == "Bad request"
    assert err.details == details
    assert err.user_action == "Fix the form."
    # AppError inherits from Exception; str() should return the message
    assert str(err) == "Bad request"


@pytest.mark.unit
def test_app_error_default_values():
    """AppError uses sensible defaults when optional fields are omitted."""
    err = AppError(
        status_code=500,
        error_type="internal_error",
        message="Something broke",
    )

    assert err.details == {}
    assert err.user_action == "Please try again."


# --- create_error_response() tests ---

@pytest.mark.unit
def test_create_error_response_structure():
    """create_error_response returns a JSONResponse with the correct body structure."""
    resp = create_error_response(
        status_code=400,
        error_type="validation_error",
        message="Invalid input",
        details={"field": "email"},
        user_action="Check your email address.",
    )

    body = resp.body  # raw bytes
    # Decode and parse the JSON content
    import json
    content = json.loads(body)

    assert content["success"] is False
    assert "error" in content

    error = content["error"]
    assert error["type"] == "validation_error"
    assert error["message"] == "Invalid input"
    assert error["details"] == {"field": "email"}
    assert error["user_action"] == "Check your email address."


@pytest.mark.unit
def test_create_error_response_status_code():
    """create_error_response sets the HTTP status code on the response."""
    resp = create_error_response(
        status_code=422,
        error_type="ai_parsing_error",
        message="Parse failure",
    )

    assert resp.status_code == 422


@pytest.mark.unit
def test_create_error_response_defaults():
    """create_error_response fills in defaults for details and user_action."""
    import json

    resp = create_error_response(
        status_code=500,
        error_type="internal_error",
        message="Unexpected error",
    )
    content = json.loads(resp.body)
    error = content["error"]

    assert error["details"] == {}
    assert error["user_action"] == "Please try again or contact support."


# --- Factory function tests ---

@pytest.mark.unit
def test_validation_error_status_400():
    """validation_error() creates a response with 400 status code."""
    resp = validation_error("Missing fields", missing_fields=["name"])

    assert resp.status_code == 400


@pytest.mark.unit
def test_validation_error_body():
    """validation_error() includes missing_fields in the details."""
    import json

    resp = validation_error("Missing fields", missing_fields=["name", "amount"])
    content = json.loads(resp.body)
    error = content["error"]

    assert error["type"] == "validation_error"
    assert error["message"] == "Missing fields"
    assert error["details"]["missing_fields"] == ["name", "amount"]


@pytest.mark.unit
def test_validation_error_no_missing_fields():
    """validation_error() without missing_fields gives empty details."""
    import json

    resp = validation_error("Bad input")
    content = json.loads(resp.body)

    assert content["error"]["details"] == {}


@pytest.mark.unit
def test_ai_parsing_error_type():
    """ai_parsing_error() creates a response with the correct error type."""
    import json

    resp = ai_parsing_error(original_error="JSON decode failed")
    content = json.loads(resp.body)

    assert content["error"]["type"] == "ai_parsing_error"


@pytest.mark.unit
def test_ai_parsing_error_status():
    """ai_parsing_error() returns a 422 status code."""
    resp = ai_parsing_error()

    assert resp.status_code == 422


@pytest.mark.unit
def test_ai_parsing_error_includes_original_error():
    """ai_parsing_error() stores the original error string in details."""
    import json

    resp = ai_parsing_error(original_error="timeout")
    content = json.loads(resp.body)

    assert content["error"]["details"]["original_error"] == "timeout"


@pytest.mark.unit
def test_database_error_status_500():
    """database_error() creates a response with 500 status code."""
    resp = database_error()

    assert resp.status_code == 500


@pytest.mark.unit
def test_database_error_type():
    """database_error() has the correct error type."""
    import json

    resp = database_error()
    content = json.loads(resp.body)

    assert content["error"]["type"] == "database_error"


@pytest.mark.unit
def test_database_error_custom_operation():
    """database_error() includes the operation name in the message."""
    import json

    resp = database_error(operation="delete")
    content = json.loads(resp.body)

    assert "delete" in content["error"]["message"]


@pytest.mark.unit
def test_email_service_error_type():
    """email_service_error() creates a response with the correct error type."""
    import json

    resp = email_service_error()
    content = json.loads(resp.body)

    assert content["error"]["type"] == "email_service_error"


@pytest.mark.unit
def test_email_service_error_status():
    """email_service_error() returns a 503 status code."""
    resp = email_service_error()

    assert resp.status_code == 503


@pytest.mark.unit
def test_email_service_error_custom_service():
    """email_service_error() includes the service type in the message."""
    import json

    resp = email_service_error(service_type="IMAP")
    content = json.loads(resp.body)

    assert "IMAP" in content["error"]["message"]


@pytest.mark.unit
def test_not_found_error_status_404():
    """not_found_error() creates a response with 404 status code."""
    resp = not_found_error()

    assert resp.status_code == 404


@pytest.mark.unit
def test_not_found_error_type():
    """not_found_error() has the correct error type."""
    import json

    resp = not_found_error()
    content = json.loads(resp.body)

    assert content["error"]["type"] == "not_found"


@pytest.mark.unit
def test_not_found_error_custom_resource():
    """not_found_error() includes the resource name in the message."""
    import json

    resp = not_found_error(resource="Invoice")
    content = json.loads(resp.body)

    assert content["error"]["message"] == "Invoice not found"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
