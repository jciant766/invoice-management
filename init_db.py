"""
Database Initialization Script

Creates database tables and seeds with initial data:
- Common suppliers from Malta councils
- Initial TF counter value (5460)

Run this script once when setting up the system:
    python init_db.py
"""

from database import engine, SessionLocal, Base
from models import Supplier, Setting

# Default suppliers commonly used by Malta local councils
DEFAULT_SUPPLIERS = [
    "Callus Blooming Gardens",
    "ARMS Ltd",
    "Melita Limited",
    "LESA",
    "City Security Ltd",
    "GO plc",
    "Enemalta plc",
    "Water Services Corporation",
    "Transport Malta",
    "Malta Tourism Authority",
    "Malta Post plc",
    "Mater Dei Hospital",
    "Malta Information Technology Agency",
    "Servizzi Ewropej f'Malta",
    "Identity Malta",
]

# Initial TF counter value
INITIAL_TF_NUMBER = "5460"


def init_database():
    """Initialize database with tables and seed data."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully.")

    db = SessionLocal()

    try:
        # Check if already initialized
        existing_tf = db.query(Setting).filter(Setting.key == "current_tf_number").first()
        if existing_tf:
            print(f"Database already initialized. Current TF number: {existing_tf.value}")
            response = input("Do you want to reset the database? (y/N): ")
            if response.lower() != 'y':
                print("Initialization cancelled.")
                return

            # Clear existing data
            print("Clearing existing data...")
            db.query(Setting).delete()
            db.query(Supplier).delete()
            db.commit()

        # Seed TF counter
        print(f"Setting initial TF counter to: {INITIAL_TF_NUMBER}")
        tf_setting = Setting(key="current_tf_number", value=INITIAL_TF_NUMBER)
        db.add(tf_setting)

        # Seed suppliers
        print("Adding default suppliers...")
        for supplier_name in DEFAULT_SUPPLIERS:
            existing = db.query(Supplier).filter(Supplier.name == supplier_name).first()
            if not existing:
                supplier = Supplier(name=supplier_name)
                db.add(supplier)
                print(f"  Added: {supplier_name}")

        db.commit()

        # Summary
        supplier_count = db.query(Supplier).count()
        print(f"\nDatabase initialized successfully!")
        print(f"  - TF counter set to: {INITIAL_TF_NUMBER}")
        print(f"  - Suppliers added: {supplier_count}")
        print(f"\nYou can now run the application with: python main.py")

    except Exception as e:
        print(f"Error initializing database: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def add_sample_invoices():
    """Add sample invoices for testing (optional)."""
    from datetime import date, timedelta
    from decimal import Decimal
    from models import Invoice

    db = SessionLocal()

    try:
        # Check if invoices already exist
        existing = db.query(Invoice).first()
        if existing:
            print("Sample invoices already exist. Skipping...")
            return

        suppliers = db.query(Supplier).all()
        if not suppliers:
            print("No suppliers found. Run init_database() first.")
            return

        sample_invoices = [
            {
                "supplier_id": suppliers[0].id,  # Callus Blooming Gardens
                "invoice_amount": Decimal("850.00"),
                "payment_amount": Decimal("850.00"),
                "method_request": "Inv",
                "method_procurement": "DA",
                "description": "Manutenzjoni tal-gonna pubblici - Xahar ta' Novembru 2025",
                "invoice_date": date.today() - timedelta(days=5),
                "invoice_number": "INV-2025-1234",
                "pjv_number": "PJV-001",
            },
            {
                "supplier_id": suppliers[1].id,  # ARMS Ltd
                "invoice_amount": Decimal("2450.75"),
                "payment_amount": Decimal("2450.75"),
                "method_request": "Inv",
                "method_procurement": "D",
                "description": "Kont tad-dawl u ilma - Q3 2025",
                "invoice_date": date.today() - timedelta(days=10),
                "invoice_number": "ARMS-2025-5678",
                "pjv_number": "PJV-002",
            },
            {
                "supplier_id": suppliers[4].id,  # City Security Ltd
                "invoice_amount": Decimal("1200.00"),
                "payment_amount": Decimal("1200.00"),
                "method_request": "RFP",
                "method_procurement": "T",
                "description": "Servizz ta' sigurta' - Festa tas-Sliema 2025",
                "invoice_date": date.today() - timedelta(days=3),
                "invoice_number": "CS-NOV-2025-42",
                "pjv_number": "PJV-003",
            },
        ]

        print("Adding sample invoices...")
        for inv_data in sample_invoices:
            invoice = Invoice(**inv_data)
            db.add(invoice)
            print(f"  Added invoice: {inv_data['invoice_number']}")

        db.commit()
        print(f"Added {len(sample_invoices)} sample invoices.")

    except Exception as e:
        print(f"Error adding sample invoices: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    print("=" * 50)
    print("Invoice Management System - Database Setup")
    print("Kunsill Lokali Tas-Sliema")
    print("=" * 50)
    print()

    init_database()

    # Ask about sample data
    print()
    response = input("Do you want to add sample invoices for testing? (y/N): ")
    if response.lower() == 'y':
        add_sample_invoices()

    print()
    print("Setup complete!")
