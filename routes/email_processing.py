"""
Email Processing Routes

Handles Gmail integration and AI-powered invoice extraction.
"""

import os
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from decimal import Decimal

from database import get_db
from models import Invoice, Supplier, METHOD_REQUEST_CODES, METHOD_PROCUREMENT_CODES
from services.email_service import get_email_service
from services.ai_service import parse_invoice_email, test_ai_connection
from error_handlers import ai_parsing_error, validation_error, email_service_error

router = APIRouter(prefix="/email", tags=["email"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def email_inbox(request: Request, db: Session = Depends(get_db)):
    """Display email processing interface."""
    suppliers_db = db.query(Supplier).order_by(Supplier.name).all()
    # Convert to list of dicts for JSON serialization in template
    suppliers = [{"id": s.id, "name": s.name} for s in suppliers_db]

    # Check service status
    email_status = "Not connected"
    ai_status = "Checking..."

    try:
        email_service = get_email_service()
        if email_service.is_available():
            email_status = f"Connected ({email_service.get_service_type()})"
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
            "parsed_invoice": None
        }
    )


@router.get("/check", response_class=JSONResponse)
async def check_emails(q: Optional[str] = None):
    """
    Fetch emails from Gmail.

    Args:
        q: Optional search query. If not provided, fetches unread emails.
           Supports Gmail search syntax: 'from:supplier@example.com', 'subject:invoice', etc.
    """
    try:
        email_service = get_email_service()
        if not email_service or not email_service.is_available():
            return JSONResponse(
                status_code=503,
                content={"error": "Email service not connected. Please configure your email settings."}
            )

        # If search query provided, search all emails; otherwise get unread
        # Limited to 150 for better performance
        if q:
            emails = email_service.search_emails(query=q, max_results=150)
        else:
            emails = email_service.get_unread_emails(max_results=150)

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
            subject = e["subject"].encode('utf-8', errors='replace').decode('utf-8')
            sender = e["from"].encode('utf-8', errors='replace').decode('utf-8')
            snippet = e.get("snippet", "").encode('utf-8', errors='replace').decode('utf-8')

            grouped_emails.append({
                "id": e["id"],
                "thread_id": thread_id,
                "subject": subject,
                "from": sender,
                "date": e["date"],
                "snippet": snippet[:100] + "..." if len(snippet) > 100 else snippet,
                "thread_count": data["count"]
            })

        return JSONResponse(content={
            "success": True,
            "count": len(emails),  # Total message count
            "query": q or "is:unread",
            "emails": grouped_emails
        })

    except FileNotFoundError:
        return JSONResponse(
            status_code=503,
            content={"error": "Email credentials not found. Please check your email configuration."}
        )
    except Exception as e:
        error_str = str(e).lower()

        # Friendly error messages
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
            friendly_error = f"Something went wrong while fetching emails. Please try again."

        # Log the actual error for debugging (safely handle unicode)
        try:
            print(f"Email service error: {repr(e)}")
        except:
            pass

        return JSONResponse(
            status_code=500,
            content={"error": friendly_error}
        )


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

        # Check if email has content
        if not email_content:
            return JSONResponse(
                status_code=422,
                content={"error": "Email has no readable content. Try a different email."}
            )

        # Parse with AI
        parsed = await parse_invoice_email(
            email_content=email_content,
            email_subject=email_data["subject"],
            email_from=email_data["from"]
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

        return {
            "success": True,
            "invoice_data": parsed
        }

    except Exception as e:
        error_str = str(e)

        # Friendly error messages for AI service errors
        if "AI_PARSE_ERROR" in error_str:
            # AI returned malformed JSON - this is the error we saw in your logs!
            return ai_parsing_error(original_error=error_str)
        elif "OUT_OF_CREDITS" in error_str:
            friendly_error = "AI service out of credits. Please add credits at openrouter.ai/settings/credits"
        elif "INVALID_API_KEY" in error_str:
            friendly_error = "Invalid AI API key. Please check your OpenRouter API key in .env file."
        elif "RATE_LIMITED" in error_str:
            friendly_error = "Too many AI requests. Please wait a moment and try again."
        elif "timeout" in error_str.lower():
            friendly_error = "AI request timed out. Please try again."
        else:
            friendly_error = "Something went wrong while parsing the email. Please try again."

        print(f"Parse error: {e}")

        return JSONResponse(
            status_code=500,
            content={"error": friendly_error}
        )


@router.post("/parse-multiple", response_class=JSONResponse)
async def parse_multiple_emails(request: Request):
    """Parse multiple emails and extract invoice data. Returns array of parsed invoices."""
    try:
        data = await request.json()
        email_ids = data.get("email_ids", [])

        if not email_ids:
            return JSONResponse(
                status_code=400,
                content={"error": "No email IDs provided"}
            )

        email_service = get_email_service()
        if not email_service or not email_service.is_available():
            return JSONResponse(
                status_code=503,
                content={"error": "Email service not available"}
            )

        results = []

        for email_id in email_ids:
            try:
                # Get email data
                email_data = email_service.get_email_by_id(email_id)
                if not email_data:
                    results.append({
                        "email_id": email_id,
                        "success": False,
                        "error": "Email not found"
                    })
                    continue

                # Get thread if applicable
                email_content = email_data.get("body", "")
                thread_count = 1

                if email_data.get("thread_id"):
                    thread_msgs = email_service.get_thread_messages(email_data["thread_id"])
                    if len(thread_msgs) > 1:
                        thread_count = len(thread_msgs)
                        combined_content = "\n\n--- EMAIL THREAD ---\n\n"
                        for idx, msg in enumerate(thread_msgs, 1):
                            combined_content += f"Message {idx} (from {msg['from']}):\n"
                            combined_content += f"Subject: {msg['subject']}\n"
                            combined_content += f"{msg['body']}\n\n---\n\n"
                        email_content = combined_content

                # Parse with AI
                parsed = await parse_invoice_email(
                    email_content=email_content,
                    email_subject=email_data["subject"],
                    email_from=email_data["from"]
                )

                if parsed:
                    parsed["email_id"] = email_id
                    parsed["email_subject"] = email_data["subject"]
                    parsed["email_from"] = email_data["from"]
                    parsed["thread_count"] = thread_count

                    results.append({
                        "email_id": email_id,
                        "success": True,
                        "invoice_data": parsed
                    })
                else:
                    results.append({
                        "email_id": email_id,
                        "success": False,
                        "error": "Could not extract invoice data"
                    })

            except Exception as e:
                results.append({
                    "email_id": email_id,
                    "success": False,
                    "error": str(e)
                })

        return {
            "success": True,
            "count": len(results),
            "results": results
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Error parsing multiple emails: {str(e)}"}
        )


@router.post("/create-invoice", response_class=JSONResponse)
async def create_invoice_from_email(
    request: Request,
    db: Session = Depends(get_db),
    email_id: str = Form(...),
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

    # Handle new supplier creation
    if supplier_id == -1:
        if not new_supplier_name or not new_supplier_name.strip():
            errors["supplier"] = "Please select a supplier or enter a new name"
        else:
            # Check if supplier already exists
            existing = db.query(Supplier).filter(
                Supplier.name.ilike(new_supplier_name.strip())
            ).first()
            if existing:
                supplier_id = existing.id
            else:
                new_supplier = Supplier(name=new_supplier_name.strip())
                db.add(new_supplier)
                db.flush()
                supplier_id = new_supplier.id

    # Validations
    if invoice_amount <= 0:
        errors["invoice_amount"] = "Invoice amount must be greater than 0"

    if payment_amount <= 0:
        errors["payment_amount"] = "Payment amount must be greater than 0"

    if payment_amount > invoice_amount:
        errors["payment_amount"] = "Payment cannot exceed invoice amount"

    # Check PJV uniqueness
    existing_pjv = db.query(Invoice).filter(
        Invoice.pjv_number == pjv_number.strip(),
        Invoice.is_deleted == False
    ).first()
    if existing_pjv:
        errors["pjv_number"] = "This PJV number already exists"

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

    # Create invoice
    invoice = Invoice(
        supplier_id=supplier_id,
        invoice_amount=Decimal(str(invoice_amount)),
        payment_amount=Decimal(str(payment_amount)),
        method_request=method_request,
        method_procurement=method_procurement,
        description=description.strip(),
        invoice_date=parsed_date,
        invoice_number=invoice_number.strip(),
        po_number=po_number.strip() if po_number else None,
        pjv_number=pjv_number.strip(),
        source_email_id=email_id,
        is_ai_generated=True
    )

    db.add(invoice)
    db.commit()

    # Mark email as read and add label
    try:
        email_service = get_email_service()
        if email_service and email_service.is_available():
            email_service.mark_as_read(email_id)
            # Note: Label adding only works with Gmail API
            if email_service.get_service_type() == "Gmail API" and hasattr(email_service.service, 'add_label'):
                email_service.service.add_label(email_id, "Processed-Invoice")
    except Exception as e:
        try:
            print(f"Could not update email status: {repr(e)}")
        except:
            pass

    return {
        "success": True,
        "invoice_id": invoice.id,
        "message": "Invoice created successfully",
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
