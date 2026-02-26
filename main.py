"""Invoice Management System for Sliema Local Council."""

import logging
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(override=True)

from database import init_db
from error_handlers import app_error_handler, AppError
from routes import invoices, exports, settings, email_processing, suppliers, auth, user_auth, users, audit
from middleware import AuthMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        allow_same_origin_frame = (
            request.method == "GET"
            and
            path.startswith("/invoices/")
            and path.endswith("/fiscal-receipt")
        )

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN" if allow_same_origin_frame else "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        frame_ancestors = "'self'" if allow_same_origin_frame else "'none'"
        # CSP: unsafe-inline/unsafe-eval required by Tailwind CDN
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            f"frame-ancestors {frame_ancestors};"
        )
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        is_https = request.url.scheme == "https" or forwarded_proto.split(",")[0].strip().lower() == "https"
        if is_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# Initialize database and auto-backup
init_db()
from services.backup_service import auto_backup_on_start
from services.receipt_integrity_service import auto_integrity_check_on_start
auto_backup_on_start()
auto_integrity_check_on_start()

# Create app
app = FastAPI(
    title="Invoice Management System",
    description="Invoice Management System for Sliema Local Council",
    version="1.0.0"
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def format_date(value, format='%d/%m/%Y'):
    """Format a date value that may be a string or datetime object."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            from datetime import datetime
            if 'T' in value:
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(value, '%Y-%m-%d')
            return dt.strftime(format)
        except (ValueError, TypeError):
            return value
    elif hasattr(value, 'strftime'):
        return value.strftime(format)
    return str(value)

templates.env.filters['format_date'] = format_date

# Register routes
app.include_router(user_auth.router)
app.include_router(invoices.router)
app.include_router(suppliers.router)
app.include_router(exports.router)
app.include_router(settings.router)
app.include_router(email_processing.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(audit.router)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, app_error_handler)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Redirect to invoices page."""
    return RedirectResponse(url="/invoices", status_code=302)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "Invoice Management System"}


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 page."""
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error_code": 404, "error_message": "The page you are looking for was not found."},
        status_code=404
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    """Custom 500 page."""
    import traceback
    logger.error(f"500 ERROR on {request.url}: {exc}")
    logger.error(traceback.format_exc())

    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error_code": 500, "error_message": "Something went wrong. Please try again."},
        status_code=500
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
