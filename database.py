"""
Database Configuration
----------------------
This file sets up the connection to your database.

Simple explanation:
- Think of a database like an Excel file that stores all your invoices
- SQLAlchemy is the tool that lets Python talk to the database
- This file tells Python where to find the database file
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# --- DATABASE LOCATION ---
# You can change where the database is stored by setting DATABASE_URL in your .env file
# If not set, it defaults to a file called "invoice_management.db" in this folder
#
# Example .env setting:
#   DATABASE_URL=sqlite:///./my_invoices.db
#
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./invoice_management.db"  # Default location
)

# --- CREATE DATABASE ENGINE ---
# The "engine" is like the connection to your database
# check_same_thread=False lets multiple parts of the app use the database at once
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}  # Required for SQLite
)

# --- CREATE SESSION MAKER ---
# A "session" is like opening the Excel file to read/write data
# This creates a template for making sessions whenever we need them
SessionLocal = sessionmaker(
    autocommit=False,  # Don't save changes automatically (we control when)
    autoflush=False,   # Don't sync changes automatically
    bind=engine        # Connect to our database
)

# --- BASE CLASS FOR MODELS ---
# All our database tables (Invoice, Supplier, etc.) inherit from this
Base = declarative_base()


def get_db():
    """
    Get a database session.

    This function is used throughout the app to access the database.
    It automatically opens and closes the connection.

    Simple explanation:
    - Opens the database
    - Lets you do stuff with it
    - Closes it when you're done (even if there's an error)

    Usage example:
        from database import get_db
        db = next(get_db())
        invoices = db.query(Invoice).all()
    """
    db = SessionLocal()
    try:
        yield db  # Give the database session to whoever needs it
    finally:
        db.close()  # Always close when done (like closing an Excel file)
