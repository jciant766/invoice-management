# Invoice Management System
## Kunsill Lokali Tas-Sliema - Sistema ta' Gestjoni tal-Fatturi

A web application for managing invoices and generating Schedule of Payments (Skeda tal-Hlasijiet) for Malta's Department of Local Government.

## Features

- **Invoice Management**: Create, edit, delete, and approve invoices
- **TF Number Generation**: Automatic sequential Transfer of Funds numbers
- **Supplier Management**: Add, edit, merge suppliers
- **Excel Export**: Generate DLG-compliant Schedule of Payments
- **PDF Export**: Generate reports for public viewing
- **Database Backup**: Download database backup files

## Quick Start

### 1. Install Python Dependencies

```bash
cd invoice_management
pip install -r requirements.txt
```

### 2. Initialize Database

```bash
python init_db.py
```

This will:
- Create the SQLite database
- Add default suppliers
- Set initial TF counter to 5460

### 3. Run the Application

**Development mode (with auto-reload):**
```bash
python main.py
```

**Production mode:**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Or with Gunicorn (Linux/Mac):
```bash
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### 4. Access the Application

Open your browser and go to: `http://localhost:8000`

## User Guide

### Creating an Invoice

1. Click "Fattura Gdida" (New Invoice) in the navigation
2. Select a supplier or add a new one
3. Enter invoice amount and payment amount
4. Select method of request and procurement method
5. Add description, invoice date, and invoice number
6. Enter the PJV number (stamp number when invoice was received)
7. Optionally check "Approve" to assign a TF number
8. Click "Oħloq Fattura" (Create Invoice)

### Approving Invoices

**From the list view:**
1. Click the green checkmark icon next to a pending invoice
2. Enter proposer and seconder councillor names
3. Click "Approva"

**From the edit form:**
1. Edit the invoice
2. Check the "Approve" checkbox
3. Enter councillor names
4. Save

### Exporting Data

**Excel Export (for DLG):**
- Go to Export menu
- Select "Excel - Kollox" for all invoices
- Select "Excel - Approvati Biss" for approved only
- Select "Excel - Pending Biss" for council meeting review

**PDF Export (for website):**
- Same options as Excel
- Formatted for public viewing

### Managing Suppliers

1. Go to Settings page
2. Click "+ Żid Fornitur" to add new supplier
3. Click edit icon to rename
4. Click merge icon to combine duplicate suppliers
5. Click delete icon to remove (only if no invoices)

### Database Backup

1. Go to Settings page
2. Click "Download Backup"
3. Save the .db file to a safe location

## Method Codes

### Request Methods (Metodu tat-Talba)
| Code | Description (English) | Description (Maltese) |
|------|----------------------|----------------------|
| P | Part Payment | Pagament Parzjali |
| Inv | Invoice | Fattura |
| Rec | Receipt | Riċevuta |
| RFP | Request for Payment | Talba ghall-Hlas |
| PP | Part Payment | Pagament Parzjali |
| DP | Deposit | Depożitu |
| EC | Expense Claim | Talba ta' Spejjeż |

### Procurement Methods (Metodu tal-Akkwist)
| Code | Description (English) | Description (Maltese) |
|------|----------------------|----------------------|
| DA | Direct Order Approved | Ordni Diretta Approvata |
| D | Direct Order | Ordni Diretta |
| T | Tender | Sejħa |
| K | Quotation | Kwotazzjoni |
| R | Refund | Rifużjoni |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+S | Save form |
| Escape | Cancel / Close modal |

## File Structure

```
invoice_management/
├── main.py              # FastAPI application entry point
├── database.py          # Database connection
├── models.py            # SQLAlchemy models
├── init_db.py           # Database initialization script
├── requirements.txt     # Python dependencies
├── routes/
│   ├── invoices.py      # Invoice CRUD routes
│   ├── exports.py       # Excel/PDF export routes
│   └── settings.py      # Settings and supplier routes
├── services/
│   ├── tf_service.py    # TF number generation
│   └── export_service.py# Export file generation
├── templates/
│   ├── base.html        # Base layout template
│   ├── invoice_list.html
│   ├── invoice_form.html
│   ├── settings.html
│   └── error.html
└── static/
    ├── css/styles.css
    └── js/app.js
```

## Technical Notes

### TF Numbers
- TF numbers are **sequential and never reset**
- Once assigned, they cannot be changed or reused
- Even if an invoice is deleted, the TF number is not recycled
- Format: "TF 5461", "TF 5462", etc.

### PJV Numbers
- Must be unique across all invoices
- Cannot be duplicated
- This is the stamp number assigned when invoice is received

### Data Security
- All data stored locally in SQLite database
- No cloud connectivity required
- Regular backups recommended

## Troubleshooting

### "PJV number already in use"
This PJV has been used on another invoice. Check existing invoices or use a different PJV number.

### "Payment cannot exceed invoice amount"
The payment amount must be less than or equal to the invoice amount.

### "Invoice date cannot be in the future"
Invoice dates must be today or earlier.

### Database locked
If you see database lock errors, make sure only one instance of the application is running.

## Support

For technical support or feature requests, contact the IT administrator.

---

Built for Kunsill Lokali Tas-Sliema
