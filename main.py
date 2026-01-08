"""
Invoice Management System for Sliema Local Council
===================================================

This is the main file that starts your web application.

SIMPLE EXPLANATION FOR BEGINNERS:
----------------------------------
Think of this like the "control center" of your app.
- It sets up the web server
- Connects all the different pages (invoices, suppliers, emails)
- Tells the app where to find files (CSS, images, etc.)
- Creates the database if it doesn't exist

To run the app:
    python main.py

Then open your web browser to: http://localhost:8000
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn

# --- LOAD ENVIRONMENT VARIABLES ---
# This reads your .env file to get settings like API keys
from dotenv import load_dotenv
load_dotenv()

# --- IMPORT DATABASE SETUP ---
# This brings in the database connection and table definitions
from database import engine, Base

# --- IMPORT ERROR HANDLING ---
# This catches errors and makes them user-friendly
from error_handlers import app_error_handler, AppError

# --- IMPORT ALL THE PAGES/FEATURES ---
# Each "router" handles a different section of the website:
#   - invoices: Main invoice list and forms
#   - suppliers: Managing supplier information
#   - exports: Creating Excel schedules
#   - settings: App settings and TF numbers
#   - email_processing: AI email parsing
from routes import invoices, exports, settings, email_processing, suppliers

# --- CREATE DATABASE TABLES ---
# If the database doesn't exist, this creates it with all the tables
# (Like creating a new Excel file with multiple sheets)
Base.metadata.create_all(bind=engine)

# --- INITIALIZE THE WEB APP ---
# This creates your FastAPI application
app = FastAPI(
    title="Invoice Management System",
    description="Invoice Management System for Sliema Local Council",
    version="1.0.0"
)

# --- SETUP STATIC FILES ---
# This tells the app where to find CSS, JavaScript, and images
# Example: http://localhost:8000/static/css/styles.css
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- SETUP HTML TEMPLATES ---
# Jinja2 turns your HTML templates into actual web pages
templates = Jinja2Templates(directory="templates")

# --- CONNECT ALL THE PAGES ---
# Each router handles URLs starting with:
#   /invoices/...   -> invoices page
#   /suppliers/...  -> suppliers page
#   /exports/...    -> export schedules
#   /settings/...   -> settings page
#   /email/...      -> email processing
app.include_router(invoices.router)
app.include_router(suppliers.router)
app.include_router(exports.router)
app.include_router(settings.router)
app.include_router(email_processing.router)

# --- REGISTER ERROR HANDLERS ---
# This catches all errors and converts them to user-friendly messages
# instead of showing ugly Chrome error pages
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, app_error_handler)


# --- HOME PAGE ---
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """
    When someone visits http://localhost:8000/
    Automatically send them to the invoices page
    """
    return RedirectResponse(url="/invoices", status_code=302)


# --- HEALTH CHECK ---
@app.get("/health")
async def health_check():
    """
    Simple endpoint to check if the app is running.
    Useful for deployment monitoring.

    Visit: http://localhost:8000/health
    """
    return {"status": "healthy", "service": "Invoice Management System"}


# --- ERROR HANDLERS ---
# These handle errors gracefully instead of showing ugly error messages

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """
    Custom 404 page - shown when someone visits a page that doesn't exist.

    Example: http://localhost:8000/this-page-doesnt-exist
    """
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error_code": 404,
            "error_message": "The page you are looking for was not found."
        },
        status_code=404
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    """
    Custom 500 page - shown when something breaks in the code.

    This prevents users from seeing scary error messages.
    """
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error_code": 500,
            "error_message": "Something went wrong. Please try again."
        },
        status_code=500
    )


# --- START THE SERVER ---
# This code only runs when you execute: python main.py
if __name__ == "__main__":
    uvicorn.run(
        "main:app",           # Tell uvicorn where to find the app
        host="0.0.0.0",       # Listen on all network interfaces (allows access from other devices)
        port=8000,            # The port to run on (http://localhost:8000)
        reload=True           # Auto-restart when you change code (helpful during development)
    )
