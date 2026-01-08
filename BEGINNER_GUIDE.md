# 🚀 Beginner's Guide to Understanding This Code

Hey! If you're new to coding, this guide will help you understand how this invoice system works.

## 📁 Project Structure (What Each Folder Does)

```
invoice_management/
├── main.py              ⭐ START HERE - This runs the app
├── database.py          💾 Database connection (like Excel file)
├── models.py            📋 Defines tables (Invoice, Supplier, etc.)
├── .env                 🔐 Your secret settings (API keys, passwords)
│
├── routes/              📄 Different pages of your website
│   ├── invoices.py      → Invoice list and forms
│   ├── suppliers.py     → Supplier management
│   ├── email_processing.py → AI email parsing
│   ├── exports.py       → Excel schedule generation
│   └── settings.py      → App settings
│
├── services/            🛠️ Helper tools that do the hard work
│   ├── ai_service.py    → Talks to OpenRouter AI
│   ├── gmail_service.py → Reads emails from Gmail
│   ├── imap_service.py  → Reads emails from any provider
│   ├── email_service.py → Picks Gmail or IMAP automatically
│   ├── export_service.py → Creates Excel files
│   └── tf_service.py    → Manages TF numbers
│
├── templates/           🎨 HTML pages (what users see)
│   ├── base.html        → Template all pages use
│   ├── invoice_list.html → Main invoice table
│   ├── invoice_form.html → Add/edit invoice form
│   ├── email_inbox.html  → Email processing page
│   └── suppliers.html    → Supplier management
│
├── static/              🖼️ CSS, JavaScript, images
│   ├── css/styles.css   → Makes things look pretty
│   └── js/app.js        → Interactive features
│
└── sample_emails/       📧 Test emails for trying features
```

## 🔄 How the App Works (Simple Flow)

### When You Start the App:

1. **Run `python main.py`**
   - `main.py` reads your `.env` file for settings
   - Creates database if it doesn't exist
   - Starts web server on http://localhost:8000

2. **User Opens Browser**
   - Goes to http://localhost:8000
   - `main.py` redirects them to `/invoices`

3. **Invoice Page Loads**
   - `routes/invoices.py` handles the request
   - Fetches invoices from `database.py`
   - Uses `templates/invoice_list.html` to show them
   - Applies styling from `static/css/styles.css`

### When Processing an Email:

1. **User clicks "Process Emails"** → Goes to `/email`
2. **Email Processing Page** (`routes/email_processing.py`)
   - Shows `templates/email_inbox.html`
3. **User clicks "Refresh"** → JavaScript calls `/email/check`
4. **Backend fetches emails**:
   - `services/email_service.py` checks if Gmail or IMAP
   - Fetches emails via `services/gmail_service.py` or `services/imap_service.py`
   - Groups threads together
   - Returns to frontend
5. **User clicks "Parse"** on an email
   - JavaScript calls `/email/parse/{email_id}`
   - Backend sends email to `services/ai_service.py`
   - AI extracts invoice details
   - Returns parsed data to form
6. **User reviews and clicks "Create Invoice"**
   - Saves to database via `models.py`
   - Marks email as read

## 🗂️ Understanding the Database

Think of the database like an Excel workbook with 3 sheets:

### Sheet 1: Invoices
```
| ID | Supplier | Invoice # | Amount | Date | Status |
|----|----------|-----------|--------|------|--------|
| 1  | ABC Ltd  | INV-001   | €500   | ...  | Draft  |
```

### Sheet 2: Suppliers
```
| ID | Name      | Email            | Phone |
|----|-----------|------------------|-------|
| 1  | ABC Ltd   | abc@example.com  | ...   |
```

### Sheet 3: Settings
```
| Key              | Value  |
|------------------|--------|
| current_tf_number| TF 0001|
```

## 🔧 Key Files for Different Tasks

### Want to change how invoices look?
- **File**: `templates/invoice_list.html`
- **What to change**: HTML structure, table columns

### Want to change colors/styling?
- **File**: `static/css/styles.css`
- **What to change**: CSS classes, colors, fonts

### Want to add a new field to invoices?
1. **File**: `models.py` - Add column to `Invoice` class
2. **File**: `templates/invoice_form.html` - Add input field
3. **File**: `routes/invoices.py` - Handle new field in save logic

### Want to change AI parsing?
- **File**: `services/ai_service.py`
- **What to change**: The `prompt` sent to the AI

### Want to change email fetching?
- **Gmail**: `services/gmail_service.py`
- **IMAP**: `services/imap_service.py`
- **Both**: `services/email_service.py` (wrapper)

## 🎯 Common Tasks You Might Do

### Task: Add a new supplier manually
1. Go to http://localhost:8000/suppliers
2. Click "Add Supplier"
3. Fill in the form
4. Code handling this: `routes/suppliers.py` line ~100

### Task: Change TF number format
1. File: `services/tf_service.py`
2. Function: `generate_next_tf_number()`
3. Change the format string

### Task: Export invoices to Excel
1. User clicks "Export Schedule" on invoice list
2. Code: `routes/exports.py` → `export_schedules()`
3. Uses: `services/export_service.py` to create Excel

## 🐛 Where Things Can Go Wrong

### "Can't connect to email"
- **Check**: `.env` file has `OPENROUTER_API_KEY`
- **Check**: Gmail credentials.json exists OR IMAP settings set

### "Database error"
- **Check**: `invoice_management.db` file permissions
- **Fix**: Delete the .db file and restart (creates new one)

### "AI parsing fails"
- **Check**: `.env` has `OPENROUTER_API_KEY`
- **Check**: Internet connection
- **File**: `services/ai_service.py` - error handling

### "Slow page loads"
- **Cause**: Email services reconnecting (now fixed with caching)
- **Files**: `services/gmail_service.py`, `services/imap_service.py`

## 💡 Tips for Learning

1. **Start with `main.py`** - Read the comments, understand the flow
2. **Look at `models.py`** - See what data you're storing
3. **Open a template** - See how HTML is generated
4. **Follow one feature** - Pick "create invoice" and trace it:
   - Template → Route → Service → Database

## 📚 What Each Technology Does

- **FastAPI**: Web framework (like WordPress but for Python)
- **SQLAlchemy**: Talks to database (like pandas for databases)
- **Jinja2**: Puts data into HTML templates
- **Uvicorn**: Web server (serves your pages)
- **OpenRouter**: AI service for email parsing
- **Tailwind CSS**: Styling framework (makes things pretty)

## 🎓 Learning Resources

- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **SQLAlchemy Basics**: https://docs.sqlalchemy.org/en/20/orm/quickstart.html
- **Python Basics**: https://www.learnpython.org/

## ✅ What We Just Fixed

1. ✅ Removed database from git (security)
2. ✅ Removed cache files from git (cleanliness)
3. ✅ Made database path configurable
4. ✅ Added missing dependencies
5. ✅ Added beginner comments everywhere

Your code is now cleaner and safer to deploy! 🎉
