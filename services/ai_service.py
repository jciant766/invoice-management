"""
AI Service for parsing invoice emails using OpenRouter/Gemini.

Extracts structured invoice data from email conversations.
"""

import os
import json
import httpx
from typing import Optional, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-pro-preview-03-25")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# System prompt for invoice extraction
INVOICE_EXTRACTION_PROMPT = """You are an AI assistant specialized in extracting invoice information from email conversations for a local council in Malta.

Your task is to analyze the email conversation and extract invoice/payment details. The council uses specific codes for categorization.

METHOD REQUEST CODES:
- P: Part Payment
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
    "notes": "Any additional notes or uncertainties"
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

Return ONLY the JSON object, no additional text or markdown formatting."""


async def parse_invoice_email(email_content: str, email_subject: str = "", email_from: str = "") -> Optional[Dict[str, Any]]:
    """
    Parse an email to extract invoice information using AI.

    Args:
        email_content: The full email body/conversation
        email_subject: Email subject line
        email_from: Sender information

    Returns:
        Dictionary with extracted invoice data or None if parsing fails
    """
    if not OPENROUTER_API_KEY:
        print("OpenRouter API key not configured")
        return None

    # Construct the message with context
    user_message = f"""Please extract invoice information from this email:

SUBJECT: {email_subject}
FROM: {email_from}

EMAIL CONTENT:
{email_content}

Extract the invoice details and return as JSON."""

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
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.1,  # Low temperature for consistent extraction
                    "max_tokens": 1000
                }
            )

            if response.status_code != 200:
                print(f"OpenRouter API error: {response.status_code} - {response.text}")
                error_text = response.text.lower()
                if response.status_code == 402 or "credits" in error_text:
                    raise Exception("OUT_OF_CREDITS")
                elif response.status_code == 401:
                    raise Exception("INVALID_API_KEY")
                elif response.status_code == 429:
                    raise Exception("RATE_LIMITED")
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
                print(f"Failed to parse AI response as JSON: {e}")
                print(f"Raw AI response: {content[:200]}...")  # Print first 200 chars
                # Return a structured error instead of None
                raise Exception(f"AI_PARSE_ERROR: {str(e)}")

            # Validate and normalize the data
            invoice_data = normalize_invoice_data(invoice_data)

            return invoice_data

    except json.JSONDecodeError as e:
        print(f"Failed to parse AI response as JSON: {e}")
        return None
    except httpx.TimeoutException:
        print("OpenRouter API request timed out")
        return None
    except Exception as e:
        print(f"Error calling OpenRouter API: {e}")
        return None


def normalize_invoice_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize and validate extracted invoice data.

    Args:
        data: Raw extracted data from AI

    Returns:
        Normalized invoice data
    """
    # Valid codes
    valid_method_request = ['P', 'Inv', 'Rec', 'RFP', 'PP', 'DP', 'EC']
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
