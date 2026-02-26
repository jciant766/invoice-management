"""
Utility functions for processing email attachments.

Handles PDF to image conversion and image processing for AI vision API.
"""

import io
import base64
import logging
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)


class PDFConversionError(Exception):
    """Exception raised when PDF conversion fails."""
    pass


def pdf_to_images(pdf_data: bytes) -> Tuple[List[bytes], Optional[str]]:
    """
    Convert PDF to list of images (one per page).

    Args:
        pdf_data: PDF file data as bytes

    Returns:
        Tuple of (List of image data as bytes (PNG format), error message if any)
    """
    try:
        # Try using pdf2image (requires poppler)
        from pdf2image import convert_from_bytes
        import os

        # Find poppler path - check local installation first
        poppler_path = None
        local_poppler = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "poppler", "poppler-24.08.0", "Library", "bin"
        )
        if os.path.exists(local_poppler):
            poppler_path = local_poppler
            logger.debug(f"Using local poppler: {poppler_path}")

        # Convert PDF to images (one per page)
        images = convert_from_bytes(pdf_data, poppler_path=poppler_path)

        if not images:
            return [], "PDF conversion produced no images"

        # Convert PIL images to PNG bytes
        image_bytes_list = []
        for img in images:
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            image_bytes_list.append(img_byte_arr.getvalue())

        return image_bytes_list, None

    except ImportError as e:
        error_msg = "pdf2image not installed. Install with: pip install pdf2image (also requires poppler)"
        logger.warning(error_msg)
        return [], error_msg
    except Exception as e:
        error_msg = f"PDF conversion failed: {str(e)}"
        logger.error(error_msg)
        # Check for common errors
        if "poppler" in str(e).lower():
            error_msg = "Poppler not found. Please install poppler or add it to PATH"
        elif "password" in str(e).lower():
            error_msg = "PDF is password protected"
        elif "corrupt" in str(e).lower() or "invalid" in str(e).lower():
            error_msg = "PDF file appears to be corrupted or invalid"
        return [], error_msg


def image_to_base64(image_data: bytes) -> str:
    """
    Convert image data to base64 string for API.

    Args:
        image_data: Image file data as bytes

    Returns:
        Base64 encoded string
    """
    return base64.b64encode(image_data).decode('utf-8')


def resize_image_if_needed(image_data: bytes, max_size: int = 2048) -> bytes:
    """
    Resize image if it's too large, maintaining aspect ratio.

    Args:
        image_data: Image file data as bytes
        max_size: Maximum width or height in pixels

    Returns:
        Resized image data as bytes (or original if no resize needed)
    """
    try:
        img = Image.open(io.BytesIO(image_data))

        # Check if resize is needed
        if max(img.size) > max_size:
            # Calculate new size maintaining aspect ratio
            ratio = max_size / max(img.size)
            new_size = tuple([int(x * ratio) for x in img.size])

            # Resize image
            img = img.resize(new_size, Image.Resampling.LANCZOS)

            # Convert back to bytes
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format=img.format or 'PNG')
            return img_byte_arr.getvalue()

        return image_data

    except Exception as e:
        logger.error(f"Error resizing image: {e}")
        return image_data


def prepare_attachments_for_vision(attachments: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Prepare attachments for vision API by converting PDFs and encoding images.

    Args:
        attachments: List of attachment dictionaries with 'data', 'mime_type', 'filename'

    Returns:
        Tuple of (List of processed attachments ready for vision API, List of error messages)
    """
    processed = []
    errors = []

    for attachment in attachments:
        mime_type = attachment.get('mime_type', '')
        data = attachment.get('data')
        filename = attachment.get('filename', 'unknown')

        if not data:
            errors.append(f"Attachment '{filename}' has no data")
            continue

        # Handle PDFs - convert to images
        if mime_type == 'application/pdf':
            logger.info(f"Converting PDF to images: {filename}")
            images, error = pdf_to_images(data)

            if error:
                errors.append(f"PDF '{filename}': {error}")
                # Continue processing other attachments

            for i, img_data in enumerate(images):
                # Resize if needed
                img_data = resize_image_if_needed(img_data)

                processed.append({
                    'type': 'image',
                    'mime_type': 'image/png',
                    'data': img_data,
                    'base64': image_to_base64(img_data),
                    'filename': f"{filename}_page_{i+1}.png",
                    'original_filename': filename,
                    'is_pdf_page': True
                })

        # Handle images
        elif mime_type.startswith('image/'):
            try:
                # Resize if needed
                data = resize_image_if_needed(data)

                processed.append({
                    'type': 'image',
                    'mime_type': mime_type,
                    'data': data,
                    'base64': image_to_base64(data),
                    'filename': filename,
                    'is_pdf_page': False
                })
            except Exception as e:
                errors.append(f"Image '{filename}': {str(e)}")

    return processed, errors
