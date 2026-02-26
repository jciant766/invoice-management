"""
Email Processing Routes

Handles Gmail integration and AI-powered invoice extraction.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from decimal import Decimal

from database import get_db
from models import METHOD_REQUEST_CODES, METHOD_PROCUREMENT_CODES
from services.email_service import get_email_service
from services.ai_service import parse_invoice_email, test_ai_connection
from services.number_service import get_next_number, preview_next_number, get_current_counts
from services.supplier_matching import find_supplier_matches
from error_handlers import ai_parsing_error, validation_error, email_service_error
from shared_templates import templates

router = APIRouter(prefix="/email", tags=["email"])


@router.get("", response_class=HTMLResponse)
async def email_inbox(request: Request):
    """Display email processing interface."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM suppliers ORDER BY name")
        suppliers = [{"id": row["id"], "name": row["name"]} for row in cursor.fetchall()]

        # Check service status
        email_status = "Not connected"
        ai_status = "Checking..."
        authenticated_email = None
        active_provider = None
        oauth_configured = {"google": False, "microsoft": False}

        try:
            # Get OAuth configuration status
            from services.oauth_service import is_oauth_configured
            oauth_configured = is_oauth_configured()
        except ImportError:
            pass

        try:
            email_service = get_email_service()
            if email_service.is_available():
                email_status = f"Connected ({email_service.get_service_type()})"
                authenticated_email = email_service.get_authenticated_email()
                active_provider = email_service.get_active_provider()
        except Exception as e:
            email_status = f"Error: {str(e)}"

        return templates.TemplateResponse(
            "email_inbox.html",
            {
                "request": request,
                "suppliers": suppliers,
                "gmail_status": email_status,
                "method_request_codes": METHOD_REQUEST_CODES,
                "method_procurement_codes": METHOD_PROCUREMENT_CODES,
                "emails": [],
                "parsed_invoice": None,
                "authenticated_email": authenticated_email,
                "active_provider": active_provider,
                "oauth_configured": oauth_configured
            }
        )


@router.get("/check", response_class=JSONResponse)
async def check_emails(q: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None):
    """
    Fetch emails from the selected folder (or inbox if none selected).
    Supports Gmail search syntax: 'from:supplier@example.com', 'subject:invoice', etc.
    """
    with get_db() as conn:
        try:
            email_service = get_email_service()

            if not email_service or not email_service.is_available():
                return JSONResponse(
                    status_code=503,
                    content={"error": "Email service not connected. Please configure your email settings."}
                )

            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'email_folder_id'")
            folder_row = cursor.fetchone()
            selected_folder_id = folder_row[0] if folder_row and folder_row[0] else None

            service_type = email_service.get_service_type() if hasattr(email_service, "get_service_type") else ""

            effective_query = q or ""
            # Provider-specific date filters
            if service_type in ["Google", "Gmail API"]:
                if date_from:
                    effective_query = (effective_query + " ").strip() + f" after:{date_from}"
                if date_to:
                    effective_query = (effective_query + " ").strip() + f" before:{date_to}"
                emails = email_service.search_emails(query=effective_query, max_results=150)
            elif service_type == "Microsoft":
                # Build safe Microsoft query: combine date OData filter + optional keyword fallback
                odata_filters = []
                keyword_query = (q or "").strip()

                if date_from:
                    odata_filters.append(f"receivedDateTime ge {date_from}T00:00:00Z")
                if date_to:
                    odata_filters.append(f"receivedDateTime le {date_to}T23:59:59Z")

                converted_query = ""
                if keyword_query and hasattr(email_service, "_convert_query_to_odata"):
                    converted_query = email_service._convert_query_to_odata(keyword_query)

                # Only append converted query when it is actual OData, otherwise keep keyword search separate
                looks_like_odata = converted_query and any(op in converted_query.lower() for op in [
                    " eq ", " ne ", " ge ", " le ", " gt ", " lt ", "contains(", "startswith(", "endswith("
                ])
                if looks_like_odata:
                    odata_filters.append(converted_query)
                    keyword_query = ""

                odata_query = " and ".join(odata_filters) if odata_filters else ""
                if odata_query:
                    emails = email_service.search_emails(query=odata_query, max_results=300 if keyword_query else 150)
                    if keyword_query:
                        k = keyword_query.lower()
                        emails = [
                            e for e in emails
                            if k in (e.get("subject", "").lower())
                            or k in (e.get("from", "").lower())
                            or k in (e.get("snippet", "").lower())
                        ]
                else:
                    emails = email_service.search_emails(query=keyword_query, max_results=150)
            else:
                # IMAP or other providers: best-effort query, fall back to local date filter below
                if effective_query:
                    emails = email_service.search_emails(query=effective_query, max_results=150)
                elif selected_folder_id:
                    emails = email_service.get_emails_from_folder(selected_folder_id, max_results=150)
                else:
                    emails = email_service.search_emails(query="", max_results=150)

            # Group emails by thread - only keep the latest email from each thread
            thread_map = {}
            for e in emails:
                thread_id = e.get("thread_id", e["id"])

                # Count messages in this thread
                if thread_id not in thread_map:
                    thread_map[thread_id] = {
                        "email": e,
                        "count": 1
                    }
                else:
                    thread_map[thread_id]["count"] += 1
                    # Keep the first email (most recent, as emails come in reverse chronological order)

            # Build response with one email per thread
            grouped_emails = []
            for thread_id, data in thread_map.items():
                e = data["email"]
                # Clean unicode characters that might cause encoding issues
                # Handle None values gracefully
                subject = e.get("subject") or "(No Subject)"
                sender = e.get("from") or "Unknown Sender"
                snippet = e.get("snippet") or ""

                # Only encode if we have actual strings
                if subject:
                    subject = subject.encode('utf-8', errors='replace').decode('utf-8')
                if sender:
                    sender = sender.encode('utf-8', errors='replace').decode('utf-8')
                if snippet:
                    snippet = snippet.encode('utf-8', errors='replace').decode('utf-8')

                grouped_emails.append({
                    "id": e["id"],
                    "thread_id": thread_id,
                    "subject": subject,
                    "from": sender,
                    "date": e.get("date", ""),
                    "snippet": snippet[:100] + "..." if len(snippet) > 100 else snippet,
                    "thread_count": data["count"]
                })

            # Optional date filter fallback (for providers without query support)
            def _parse_email_date(date_str: str):
                if not date_str:
                    return None
                for fmt in ("%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
                    try:
                        return datetime.strptime(date_str, fmt).date()
                    except Exception:
                        continue
                return None

            if date_from or date_to:
                try:
                    df = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else None
                    dt = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else None
                except ValueError:
                    df = dt = None
                filtered = []
                for e in grouped_emails:
                    d = _parse_email_date(e.get("date", ""))
                    if d:
                        if df and d < df:
                            continue
                        if dt and d > dt:
                            continue
                    filtered.append(e)
                grouped_emails = filtered

            return JSONResponse(content={
                "success": True,
                "count": len(emails),  # Total message count
                "query": effective_query or q or "is:unread",
                "emails": grouped_emails
            })

        except FileNotFoundError:
            return JSONResponse(
                status_code=503,
                content={"error": "Email credentials not found. Please check your email configuration."}
            )
        except Exception as e:
            error_str = str(e).lower()
            if "invalid_grant" in error_str or "token" in error_str:
                friendly_error = "Email session expired. Please reconnect your email account."
            elif "access_denied" in error_str or "403" in error_str or "authentication" in error_str:
                friendly_error = "Access denied. Please check your email credentials."
            elif "quota" in error_str or "rate" in error_str:
                friendly_error = "Too many requests. Please wait a moment and try again."
            elif "network" in error_str or "connection" in error_str:
                friendly_error = "Network error. Please check your internet connection."
            elif "invalid" in error_str and "query" in error_str:
                friendly_error = "Invalid search query. Check your search syntax and try again."
            else:
                friendly_error = "Something went wrong while fetching emails. Please try again."
            return JSONResponse(status_code=500, content={"error": friendly_error})


@router.post("/parse/{email_id}", response_class=JSONResponse)
async def parse_email(email_id: str, include_thread: bool = True):
    """Parse a specific email and extract invoice data using AI. Optionally includes full thread."""
    try:
        email_service = get_email_service()
        if not email_service or not email_service.is_available():
            return JSONResponse(
                status_code=503,
                content={"error": "Email service not available"}
            )

        # Get full email content
        email_data = email_service.get_email_by_id(email_id)
        if not email_data:
            return JSONResponse(
                status_code=404,
                content={"error": "Email not found"}
            )

        # Check if we should include thread
        email_content = email_data.get("body", "")
        thread_messages = []

        if include_thread and email_data.get("thread_id"):
            try:
                # Get all messages in thread
                thread_msgs = email_service.get_thread_messages(email_data["thread_id"])

                if len(thread_msgs) > 1:
                    # Thread has multiple messages - combine them
                    thread_messages = thread_msgs
                    combined_content = "\n\n--- EMAIL THREAD ---\n\n"
                    for idx, msg in enumerate(thread_msgs, 1):
                        combined_content += f"Message {idx} (from {msg['from']}):\n"
                        combined_content += f"Subject: {msg['subject']}\n"
                        combined_content += f"{msg['body']}\n\n---\n\n"
                    email_content = combined_content
            except Exception:
                pass  # Thread fetching failed - use single email

        if not email_content and not email_data.get("attachments"):
            return JSONResponse(
                status_code=422,
                content={"error": "Email has no readable content or attachments. Try a different email."}
            )

        attachments = email_data.get("attachments", [])

        # Parse with AI (including attachments)
        parsed = await parse_invoice_email(
            email_content=email_content or "(No email body text - see attachments)",
            email_subject=email_data["subject"],
            email_from=email_data["from"],
            attachments=attachments
        )

        if not parsed:
            return JSONResponse(
                status_code=422,
                content={"error": "Could not extract invoice data. This email may not contain invoice information."}
            )

        # Add email metadata
        parsed["email_id"] = email_id
        parsed["email_subject"] = email_data["subject"]
        parsed["email_from"] = email_data["from"]
        parsed["thread_count"] = len(thread_messages) if thread_messages else 1
        parsed["thread_messages"] = [{"id": m["id"], "from": m["from"], "subject": m["subject"]} for m in thread_messages] if thread_messages else []

        # Fuzzy supplier matching
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM suppliers WHERE is_active = 1 ORDER BY name")
            all_suppliers = [{"id": row["id"], "name": row["name"]} for row in cursor.fetchall()]

            match_result = find_supplier_matches(
                extracted_name=parsed.get("supplier_name", ""),
                existing_suppliers=all_suppliers,
                top_k=5,
                auto_select_threshold=0.90
            )
            parsed["supplier_matches"] = match_result

        # Clean up internal fields from AI response
        parsed.pop("invoice_attachment_index", None)
        parsed.pop("_attachments", None)
        parsed.pop("_attachment_count", None)

        # Include any attachment processing warnings
        attachment_warnings = parsed.pop("_attachment_warnings", None)
        if attachment_warnings:
            parsed["attachment_warnings"] = attachment_warnings

        return {
            "success": True,
            "invoice_data": parsed
        }

    except Exception as e:
        error_str = str(e)
        if "AI_PARSE_ERROR" in error_str:
            return ai_parsing_error(original_error=error_str)

        # Map error types to responses
        error_map = {
            "MODEL_NOT_SUPPORTED": (422, "model_error", "The AI model you're using is incompatible",
                "Change your OpenRouter model to Claude or GPT-4 in .env"),
            "OUT_OF_CREDITS": (402, "credits_error", "AI service is out of credits",
                "Add more credits at openrouter.ai/settings/credits"),
            "INVALID_API_KEY": (401, "api_key_error", "Invalid OpenRouter API key",
                "Check OPENROUTER_API_KEY in your .env file"),
            "RATE_LIMITED": (429, "rate_limit_error", "Too many AI requests",
                "Please wait a moment and try again"),
        }

        for key, (status, err_type, msg, action) in error_map.items():
            if key in error_str:
                return JSONResponse(status_code=status, content={
                    "error": {"type": err_type, "message": msg, "details": {}, "user_action": action}
                })

        if "timeout" in error_str.lower():
            return JSONResponse(status_code=504, content={
                "error": {"type": "timeout_error", "message": "AI request timed out",
                          "details": {}, "user_action": "Please try again."}
            })

        return JSONResponse(status_code=500, content={
            "error": {"type": "parse_error", "message": "Unable to parse email",
                      "details": {"original_error": error_str},
                      "user_action": "Something went wrong. Try a different email."}
        })


@router.post("/parse-multiple", response_class=JSONResponse)
async def parse_multiple_emails(request: Request):
    """Parse multiple emails and extract invoice data."""
    try:
        data = await request.json()
        email_ids = data.get("email_ids", [])

        if not email_ids:
            return JSONResponse(status_code=400, content={"error": "No email IDs provided"})

        email_service = get_email_service()
        if not email_service or not email_service.is_available():
            return JSONResponse(status_code=503, content={"error": "Email service not available"})

        results = []

        for email_id in email_ids:
            try:
                email_data = email_service.get_email_by_id(email_id)
                if not email_data:
                    results.append({"email_id": email_id, "success": False, "error": "Email not found"})
                    continue

                email_content = email_data.get("body", "")
                thread_count = 1

                if email_data.get("thread_id"):
                    try:
                        thread_msgs = email_service.get_thread_messages(email_data["thread_id"])
                        if len(thread_msgs) > 1:
                            thread_count = len(thread_msgs)
                            combined = "\n\n--- EMAIL THREAD ---\n\n"
                            for i, msg in enumerate(thread_msgs, 1):
                                combined += f"Message {i} (from {msg['from']}):\nSubject: {msg['subject']}\n{msg['body']}\n\n---\n\n"
                            email_content = combined
                    except Exception:
                        pass

                attachments = email_data.get("attachments", [])
                parsed = await parse_invoice_email(
                    email_content=email_content or "(No email body text - see attachments)",
                    email_subject=email_data["subject"],
                    email_from=email_data["from"],
                    attachments=attachments
                )

                if parsed:
                    try:
                        with get_db() as conn_inner:
                            cursor_inner = conn_inner.cursor()
                            cursor_inner.execute("SELECT id, name FROM suppliers WHERE is_active = 1 ORDER BY name")
                            all_suppliers = [{"id": row["id"], "name": row["name"]} for row in cursor_inner.fetchall()]
                            match_result = find_supplier_matches(
                                extracted_name=parsed.get("supplier_name", ""),
                                existing_suppliers=all_suppliers,
                                top_k=5, auto_select_threshold=0.90
                            )
                            parsed["supplier_matches"] = match_result
                    except Exception:
                        pass

                    parsed.pop("_attachments", None)
                    parsed.pop("_attachment_count", None)
                    parsed.pop("_attachment_warnings", None)
                    parsed["email_id"] = email_id
                    parsed["email_subject"] = email_data["subject"]
                    parsed["email_from"] = email_data["from"]
                    parsed["thread_count"] = thread_count
                    results.append({"email_id": email_id, "success": True, "invoice_data": parsed})
                else:
                    results.append({"email_id": email_id, "success": False, "error": "Could not extract invoice data"})

            except Exception as e:
                results.append({"email_id": email_id, "success": False, "error": str(e)})

        return {"success": True, "count": len(results), "results": results}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Error parsing emails: {str(e)}"})


@router.get("/next-number/{number_type}", response_class=JSONResponse)
async def get_next_sequence_number(number_type: str):
    """Preview the next TF or CHQ number without reserving it."""
    with get_db() as conn:
        try:
            number_type = number_type.upper().strip()

            if number_type == 'PJV':
                return {"success": True, "number_type": "PJV", "next_number": "Manual input", "is_manual": True}

            if number_type not in ('TF', 'CHQ'):
                return JSONResponse(status_code=400, content={"error": f"Invalid type '{number_type}'. Must be TF or CHQ"})

            return {
                "success": True,
                "number_type": number_type,
                "next_number": preview_next_number(conn, number_type),
                "current_counts": get_current_counts(conn),
                "is_manual": False
            }
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/create-invoice", response_class=JSONResponse)
async def create_invoice_from_email(
    request: Request,
    email_id: str = Form(...),
    email_subject: Optional[str] = Form(None),
    email_from: Optional[str] = Form(None),
    supplier_id: int = Form(...),
    new_supplier_name: Optional[str] = Form(None),
    invoice_amount: float = Form(...),
    payment_amount: float = Form(...),
    method_request: str = Form(...),
    method_procurement: str = Form(...),
    description: str = Form(...),
    invoice_date: str = Form(...),
    invoice_number: str = Form(...),
    po_number: Optional[str] = Form(None),
    pjv_number: str = Form(...)
):
    """Create an invoice from parsed email data."""
    errors = {}

    with get_db() as conn:
        cursor = conn.cursor()

        # Handle new supplier creation
        if supplier_id == -1:
            if not new_supplier_name or not new_supplier_name.strip():
                errors["supplier"] = "Please select a supplier or enter a new name"
            else:
                # Check if supplier already exists
                cursor.execute(
                    "SELECT id FROM suppliers WHERE LOWER(name) = LOWER(?)",
                    (new_supplier_name.strip(),)
                )
                existing = cursor.fetchone()
                if existing:
                    supplier_id = existing[0]
                else:
                    cursor.execute(
                        "INSERT INTO suppliers (name, is_active) VALUES (?, 1)",
                        (new_supplier_name.strip(),)
                    )
                    supplier_id = cursor.lastrowid

        # Validations
        if invoice_amount <= 0:
            errors["invoice_amount"] = "Invoice amount must be greater than 0"

        if payment_amount <= 0:
            errors["payment_amount"] = "Payment amount must be greater than 0"

        if payment_amount > invoice_amount:
            errors["payment_amount"] = "Payment cannot exceed invoice amount"

        # Check duplicate PJV
        cursor.execute("SELECT id FROM invoices WHERE pjv_number = ? AND is_deleted = 0", (pjv_number.strip(),))
        if cursor.fetchone():
            errors["pjv_number"] = "This PJV number is already in use"

        # Parse date
        try:
            parsed_date = datetime.strptime(invoice_date, "%Y-%m-%d").date()
        except ValueError:
            errors["invoice_date"] = "Invalid date format"
            parsed_date = None

        if errors:
            return JSONResponse(
                status_code=400,
                content={"success": False, "errors": errors}
            )

        # Create invoice (unapproved by default, so no TF/CHQ number yet)
        cursor.execute("""
            INSERT INTO invoices (
                supplier_id, invoice_amount, payment_amount, method_request,
                method_procurement, description, invoice_date, invoice_number,
                po_number, number_type, pjv_number, source_email_id, email_subject,
                email_from, is_ai_generated, is_approved, is_deleted, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'TF', ?, ?, ?, ?, 1, 0, 0, ?)
        """, (
            supplier_id,
            str(Decimal(str(invoice_amount))),
            str(Decimal(str(payment_amount))),
            method_request,
            method_procurement,
            description.strip(),
            parsed_date.isoformat() if parsed_date else None,
            invoice_number.strip(),
            po_number.strip() if po_number else None,
            pjv_number,
            email_id,
            email_subject,
            email_from,
            datetime.now().isoformat()
        ))
        invoice_id = cursor.lastrowid

        # Mark email as read and add label
        try:
            email_service = get_email_service()
            if email_service and email_service.is_available():
                email_service.mark_as_read(email_id)
                if email_service.get_service_type() == "Gmail API" and hasattr(email_service.service, 'add_label'):
                    email_service.service.add_label(email_id, "Processed-Invoice")
        except Exception:
            pass

        return {
            "success": True,
            "invoice_id": invoice_id,
            "message": f"Invoice created successfully (PJV {pjv_number})",
            "pjv_number": pjv_number,
            "redirect": "/invoices"
        }


@router.get("/test-ai", response_class=JSONResponse)
async def test_ai_service():
    """Test AI service connection."""
    result = await test_ai_connection()
    return result


@router.post("/mark-read/{email_id}", response_class=JSONResponse)
async def mark_email_read(email_id: str):
    """Mark an email as read without creating an invoice."""
    try:
        email_service = get_email_service()
        if not email_service or not email_service.is_available():
            return JSONResponse(
                status_code=503,
                content={"error": "Email service not available"}
            )

        success = email_service.mark_as_read(email_id)

        return {
            "success": success,
            "message": "Email marked as read" if success else "Failed to mark as read"
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@router.get("/folders", response_class=JSONResponse)
async def list_email_folders():
    """List all available email folders/labels."""
    with get_db() as conn:
        try:
            email_service = get_email_service()
            if not email_service or not email_service.is_available():
                return JSONResponse(
                    status_code=503,
                    content={"error": "Email service not connected"}
                )

            folders = email_service.list_folders()

            # Get currently selected folder from settings
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'email_folder_id'")
            selected_row = cursor.fetchone()
            selected_folder_id = selected_row[0] if selected_row else None

            cursor.execute("SELECT value FROM settings WHERE key = 'email_folder_name'")
            name_row = cursor.fetchone()
            selected_folder_name = name_row[0] if name_row else None

            return {
                "success": True,
                "folders": folders,
                "selected_folder_id": selected_folder_id,
                "selected_folder_name": selected_folder_name,
                "provider": email_service.get_service_type()
            }

        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": str(e)}
            )


@router.post("/folders/select", response_class=JSONResponse)
async def select_email_folder(request: Request):
    """Save the selected email folder to use for invoice processing."""
    with get_db() as conn:
        try:
            data = await request.json()
            folder_id = data.get("folder_id")
            folder_name = data.get("folder_name", "")

            cursor = conn.cursor()

            # Save folder ID using INSERT OR REPLACE (key is PRIMARY KEY)
            cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('email_folder_id', ?)",
                (folder_id if folder_id else "",)
            )

            # Save folder name for display
            cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('email_folder_name', ?)",
                (folder_name,)
            )

            return {
                "success": True,
                "message": f"Folder '{folder_name}' selected" if folder_id else "Using inbox (default)",
                "folder_id": folder_id,
                "folder_name": folder_name
            }

        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": str(e)}
            )


@router.delete("/folders/select", response_class=JSONResponse)
async def clear_email_folder():
    """Clear the selected folder (revert to inbox/all unread)."""
    with get_db() as conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM settings WHERE key = 'email_folder_id'")
            cursor.execute("DELETE FROM settings WHERE key = 'email_folder_name'")

            return {
                "success": True,
                "message": "Folder selection cleared. Now using inbox."
            }

        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": str(e)}
            )
