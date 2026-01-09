"""
Utility functions for processing email attachments.

Handles PDF to image conversion and image processing for AI vision API.
"""

import io
import base64
from typing import List, Dict, Any, Optional
from PIL import Image


def pdf_to_images(pdf_data: bytes) -> List[bytes]:
    """
    Convert PDF to list of images (one per page).

    Args:
        pdf_data: PDF file data as bytes

    Returns:
        List of image data as bytes (PNG format)
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
            print(f"Using local poppler: {poppler_path}")

        # Convert PDF to images (one per page)
        images = convert_from_bytes(pdf_data, poppler_path=poppler_path)

        # Convert PIL images to PNG bytes
        image_bytes_list = []
        for img in images:
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            image_bytes_list.append(img_byte_arr.getvalue())

        return image_bytes_list

    except ImportError:
        print("Warning: pdf2image not installed. PDF attachments will be skipped.")
        print("Install with: pip install pdf2image")
        print("Note: Also requires poppler - see https://pdf2image.readthedocs.io/")
        return []
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return []


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
        print(f"Error resizing image: {e}")
        return image_data


def prepare_attachments_for_vision(attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prepare attachments for vision API by converting PDFs and encoding images.

    Args:
        attachments: List of attachment dictionaries with 'data', 'mime_type', 'filename'

    Returns:
        List of processed attachments ready for vision API
    """
    processed = []

    for attachment in attachments:
        mime_type = attachment.get('mime_type', '')
        data = attachment.get('data')
        filename = attachment.get('filename', 'unknown')

        if not data:
            continue

        # Handle PDFs - convert to images
        if mime_type == 'application/pdf':
            print(f"Converting PDF to images: {filename}")
            images = pdf_to_images(data)

            for i, img_data in enumerate(images):
                # Resize if needed
                img_data = resize_image_if_needed(img_data)

                processed.append({
                    'type': 'image',
                    'mime_type': 'image/png',
                    'data': img_data,
                    'base64': image_to_base64(img_data),
                    'filename': f"{filename}_page_{i+1}.png"
                })

        # Handle images
        elif mime_type.startswith('image/'):
            # Resize if needed
            data = resize_image_if_needed(data)

            processed.append({
                'type': 'image',
                'mime_type': mime_type,
                'data': data,
                'base64': image_to_base64(data),
                'filename': filename
            })

    return processed
