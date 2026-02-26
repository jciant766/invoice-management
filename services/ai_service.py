"""
AI Service for parsing invoice emails using OpenRouter/GPT-5.2 with vision support.

Extracts structured invoice data from email conversations and attachments.
"""

import os
import json
import asyncio
import logging
import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime
from dotenv import load_dotenv
from .attachment_utils import prepare_attachments_for_vision

logger = logging.getLogger(__name__)

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-5.2")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds
MAX_BACKOFF = 30.0  # seconds
BACKOFF_MULTIPLIER = 2.0


# System prompt for invoice extraction
INVOICE_EXTRACTION_PROMPT = """You are an invoice extraction agent specialized in extracting invoice information from emails and attachments for a local council in Malta.

Your task is to analyze:
1. The email body text
2. Any PDF or image attachments provided (which may contain the actual invoice)
3. Previous email threads in the conversation

IMPORTANT: When multiple attachments are provided, you MUST identify which attachment is the actual invoice/fiscal receipt document. This could be labeled as "Image 1", "Image 2", etc. in the attachments.

Extract invoice/payment details from all available sources. The council uses specific codes for categorization.

METHOD REQUEST CODES:
- Inv: Invoice
- Rec: Receipt
- RFP: Request for Payment
- PP: Part Payment
- DP: Deposit
- EC: Expense Claim

METHOD PROCUREMENT CODES:
- DA: Direct Order Approvata (Approved Direct Order)
- D: Direct Order
- T: Tender
- K: Kwotazzjoni (Quotation)
- R: Refund

Extract the following information and return as JSON:
{
    "supplier_name": "Name of the supplier/vendor",
    "invoice_amount": 0.00,
    "payment_amount": 0.00,
    "method_request": "Inv",
    "method_procurement": "D",
    "description": "Brief description of what the invoice is for",
    "invoice_date": "YYYY-MM-DD",
    "invoice_number": "Invoice number from the document",
    "po_number": "Purchase order number if mentioned, or null",
    "confidence_score": 0.95,
    "notes": "Any additional notes or uncertainties",
    "invoice_attachment_index": 0
}

IMPORTANT RULES:
1. If invoice_amount and payment_amount are the same, use the same value for both
2. If you can't find a specific field, use null for optional fields or make a reasonable guess
3. For method_request, default to "Inv" (Invoice) if unclear
4. For method_procurement, default to "D" (Direct Order) if unclear
5. Dates should be in YYYY-MM-DD format
6. Amounts should be numbers without currency symbols
7. confidence_score should reflect how certain you are about the extraction (0.0 to 1.0)
8. The supplier_name should be clean and standardized (company name only, no addresses)
9. invoice_attachment_index: Set this to the 0-based index of the attachment that IS the invoice/receipt document. If Image 1 is the invoice, set to 0. If Image 2 is the invoice, set to 1. If no attachments contain an invoice, set to null.

Return ONLY the JSON object, no additional text or markdown formatting."""


async def parse_invoice_email(email_content: str, email_subject: str = "", email_from: str = "", attachments: List[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Parse an email to extract invoice information using AI with vision support.

    Args:
        email_content: The full email body/conversation
        email_subject: Email subject line
        email_from: Sender information
        attachments: List of attachment dictionaries with 'data', 'mime_type', 'filename'

    Returns:
        Dictionary with extracted invoice data or None if parsing fails
    """
    if not OPENROUTER_API_KEY:
        logger.error("OpenRouter API key not configured")
        return None

    # Process attachments for vision API
    processed_attachments = []
    attachment_errors = []
    if attachments:
        processed_attachments, attachment_errors = prepare_attachments_for_vision(attachments)
        logger.info(f"Processed {len(processed_attachments)} attachment(s) for vision API")
        if attachment_errors:
            for err in attachment_errors:
                logger.warning(f"Attachment warning: {err}")

    # Build user message content
    if processed_attachments:
        # Build attachment list description for AI
        attachment_list = "\n".join([
            f"- Image {i+1}: {att.get('filename', 'unknown')}"
            for i, att in enumerate(processed_attachments)
        ])

        # Vision API format with images
        user_content = [
            {
                "type": "text",
                "text": f"""Please extract invoice information from this email and the attached images:

SUBJECT: {email_subject}
FROM: {email_from}

EMAIL CONTENT:
{email_content}

ATTACHMENTS ({len(processed_attachments)} files):
{attachment_list}

The images below are labeled in order (Image 1, Image 2, etc.). Identify which image is the actual invoice/fiscal receipt document and set invoice_attachment_index accordingly. Return as JSON."""
            }
        ]

        # Add images with labels
        for i, attachment in enumerate(processed_attachments):
            # Add text label before each image
            user_content.append({
                "type": "text",
                "text": f"Image {i+1} ({attachment.get('filename', 'attachment')}):"
            })
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{attachment['mime_type']};base64,{attachment['base64']}"
                }
            })
    else:
        # Text-only format
        user_content = f"""Please extract invoice information from this email:

SUBJECT: {email_subject}
FROM: {email_from}

EMAIL CONTENT:
{email_content}

Extract the invoice details and return as JSON."""

    last_exception = None
    backoff = INITIAL_BACKOFF

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://council-invoice-system.local",
                        "X-Title": "Council Invoice System"
                    },
                    json={
                        "model": OPENROUTER_MODEL,
                        "messages": [
                            {"role": "system", "content": INVOICE_EXTRACTION_PROMPT},
                            {"role": "user", "content": user_content}
                        ],
                        "temperature": 0.1,  # Low temperature for consistent extraction
                        "max_tokens": 1000
                    }
                )

                if response.status_code != 200:
                    logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                    error_text = response.text.lower()

                    # Non-retryable errors - fail immediately
                    if response.status_code == 402 or "credits" in error_text:
                        raise Exception("OUT_OF_CREDITS")
                    elif response.status_code == 401:
                        raise Exception("INVALID_API_KEY")
                    elif "thinking_budget" in error_text:
                        raise Exception("MODEL_NOT_SUPPORTED: Try using a different model like Claude or GPT")

                    # Retryable errors - 429 (rate limit) or 5xx (server errors)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < MAX_RETRIES - 1:
                            logger.warning(f"Retrying in {backoff:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})")
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF)
                            continue
                        raise Exception("RATE_LIMITED" if response.status_code == 429 else "AI_SERVICE_ERROR: Server error after retries")

                    return None

                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Parse the JSON response
                # Clean up potential markdown formatting
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                # Try to parse JSON with better error handling
                try:
                    invoice_data = json.loads(content)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse AI response as JSON: {e}")
                    logger.debug(f"Raw AI response: {content[:200]}...")
                    # Return a structured error instead of None
                    raise Exception(f"AI_PARSE_ERROR: {str(e)}")

                # Validate and normalize the data
                invoice_data = normalize_invoice_data(invoice_data)

                # Include original attachments for saving the identified invoice
                if attachments:
                    invoice_data['_attachments'] = attachments  # Original attachment data with binary
                    invoice_data['_attachment_count'] = len(attachments)

                # Include any attachment processing warnings
                if attachment_errors:
                    invoice_data['_attachment_warnings'] = attachment_errors

                return invoice_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            raise Exception(f"AI_PARSE_ERROR: {str(e)}")
        except httpx.TimeoutException:
            last_exception = Exception("TIMEOUT: AI request timed out. Please try again.")
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"Request timed out, retrying in {backoff:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF)
                continue
            raise last_exception
        except Exception as e:
            # Re-raise exceptions that should be handled by the route
            error_str = str(e)
            if any(err in error_str for err in ["AI_PARSE_ERROR", "OUT_OF_CREDITS", "INVALID_API_KEY", "RATE_LIMITED", "MODEL_NOT_SUPPORTED", "TIMEOUT"]):
                raise  # Let the route handle these specific errors
            logger.error(f"Error calling OpenRouter API: {e}")
            raise Exception(f"AI_SERVICE_ERROR: {str(e)}")

    # Should not reach here, but just in case
    if last_exception:
        raise last_exception
    raise Exception("AI_SERVICE_ERROR: Max retries exceeded")


def normalize_invoice_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize and validate extracted invoice data.

    Args:
        data: Raw extracted data from AI

    Returns:
        Normalized invoice data
    """
    # Valid codes
    valid_method_request = ['Inv', 'Rec', 'RFP', 'PP', 'DP', 'EC']
    valid_method_procurement = ['DA', 'D', 'T', 'K', 'R']

    # Normalize method_request
    method_req = data.get('method_request', 'Inv')
    if method_req not in valid_method_request:
        method_req = 'Inv'
    data['method_request'] = method_req

    # Normalize method_procurement
    method_proc = data.get('method_procurement', 'D')
    if method_proc not in valid_method_procurement:
        method_proc = 'D'
    data['method_procurement'] = method_proc

    # Ensure amounts are floats
    try:
        data['invoice_amount'] = float(data.get('invoice_amount', 0))
    except (ValueError, TypeError):
        data['invoice_amount'] = 0.0

    try:
        data['payment_amount'] = float(data.get('payment_amount', 0))
    except (ValueError, TypeError):
        data['payment_amount'] = data['invoice_amount']

    # If payment_amount is 0 but invoice_amount isn't, use invoice_amount
    if data['payment_amount'] == 0 and data['invoice_amount'] > 0:
        data['payment_amount'] = data['invoice_amount']

    # Normalize date
    invoice_date = data.get('invoice_date')
    if invoice_date:
        try:
            # Try to parse and reformat
            if isinstance(invoice_date, str):
                for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y']:
                    try:
                        parsed = datetime.strptime(invoice_date, fmt)
                        data['invoice_date'] = parsed.strftime('%Y-%m-%d')
                        break
                    except ValueError:
                        continue
        except Exception:
            data['invoice_date'] = datetime.now().strftime('%Y-%m-%d')
    else:
        data['invoice_date'] = datetime.now().strftime('%Y-%m-%d')

    # Ensure required string fields
    data['supplier_name'] = str(data.get('supplier_name', 'Unknown Supplier')).strip()
    data['description'] = str(data.get('description', '')).strip()
    data['invoice_number'] = str(data.get('invoice_number', '')).strip()

    # Optional fields
    data['po_number'] = data.get('po_number')
    if data['po_number']:
        data['po_number'] = str(data['po_number']).strip()

    # Confidence score
    try:
        data['confidence_score'] = float(data.get('confidence_score', 0.5))
    except (ValueError, TypeError):
        data['confidence_score'] = 0.5

    # Invoice attachment index (which attachment is the invoice)
    invoice_idx = data.get('invoice_attachment_index')
    if invoice_idx is not None:
        try:
            data['invoice_attachment_index'] = int(invoice_idx)
        except (ValueError, TypeError):
            data['invoice_attachment_index'] = None
    else:
        data['invoice_attachment_index'] = None

    return data


async def test_ai_connection() -> Dict[str, Any]:
    """
    Test the AI service connection.

    Returns:
        Status dictionary with success flag and message
    """
    if not OPENROUTER_API_KEY:
        return {
            "success": False,
            "message": "OpenRouter API key not configured"
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "user", "content": "Hello, respond with 'OK' only."}
                    ],
                    "max_tokens": 10
                }
            )

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Connected to {OPENROUTER_MODEL}",
                    "model": OPENROUTER_MODEL
                }
            else:
                return {
                    "success": False,
                    "message": f"API error: {response.status_code}"
                }

    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }
