"""
Export Service for generating Excel and PDF files.

Generates Schedule of Payments (Skeda tal-Hlasijiet) in the exact format
required by Malta's Department of Local Government (DLG).
"""

from io import BytesIO
from datetime import datetime
from typing import List, Optional
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from models import Invoice


def generate_schedule_excel(
    invoices: List[Invoice],
    sitting_number: Optional[str] = None,
    month_year: Optional[str] = None
) -> BytesIO:
    """
    Generate Excel file matching exact DLG template format.

    Args:
        invoices: List of Invoice objects to export
        sitting_number: Council sitting number (e.g., "23")
        month_year: Month and year string (e.g., "November 2025")

    Returns:
        BytesIO: Excel file as bytes buffer
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Skeda tal-Hlasijiet"

    # Define styles
    header_font = Font(bold=True, size=12)
    title_font = Font(bold=True, size=14)
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    header_fill = PatternFill(start_color="1e3a8a", end_color="1e3a8a", fill_type="solid")
    header_font_white = Font(bold=True, size=10, color="FFFFFF")

    # Row 1: Title
    ws.merge_cells('A1:Q1')
    ws['A1'] = "KUNSILL LOKALI TAS-SLIEMA"
    ws['A1'].font = title_font
    ws['A1'].alignment = Alignment(horizontal='center')

    # Row 2: Subtitle
    ws.merge_cells('A2:Q2')
    title_text = "SKEDA TAL-HLASIJIET"
    if sitting_number:
        title_text += f" - Seduta Nru. {sitting_number}"
    if month_year:
        title_text += f" - {month_year}"
    ws['A2'] = title_text
    ws['A2'].font = header_font
    ws['A2'].alignment = Alignment(horizontal='center')

    # Row 3: Empty row
    ws.row_dimensions[3].height = 10

    # Row 4: Column headers (Maltese)
    headers = [
        ("A", "Seduta Nru", 10),
        ("B", "Supplier Code", 12),
        ("C", "#", 5),
        ("D", "Fornitur", 30),
        ("E", "Ammont tal-Invoice", 15),
        ("F", "Ammont li ser Jithallas", 18),
        ("G", "Metodu*", 8),
        ("H", "Prokur.", 8),
        ("I", "Deskrizzjoni", 40),
        ("J", "Data tal-Invoice", 15),
        ("K", "Nru. tal-Invoice", 15),
        ("L", "Nru. Tal-PR", 12),
        ("M", "Nru. Tal-PO", 12),
        ("N", "Nru. Tac-Cekk (TF)", 15),
        ("O", "PJV Number", 12),
    ]

    for col, header_text, width in headers:
        cell = ws[f'{col}4']
        cell.value = header_text
        cell.font = header_font_white
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = border
        ws.column_dimensions[col].width = width

    # Row 5+: Invoice data
    row = 5
    total_invoice = 0
    total_payment = 0

    for idx, invoice in enumerate(invoices, start=1):
        # Seduta Nru
        ws[f'A{row}'] = sitting_number or ""
        ws[f'A{row}'].border = border

        # Supplier Code (using supplier ID for now)
        ws[f'B{row}'] = str(invoice.supplier_id)
        ws[f'B{row}'].border = border

        # Sequential number
        ws[f'C{row}'] = idx
        ws[f'C{row}'].border = border

        # Supplier name
        ws[f'D{row}'] = invoice.supplier.name
        ws[f'D{row}'].border = border

        # Invoice amount
        ws[f'E{row}'] = float(invoice.invoice_amount)
        ws[f'E{row}'].number_format = '#,##0.00'
        ws[f'E{row}'].border = border
        total_invoice += float(invoice.invoice_amount)

        # Payment amount
        ws[f'F{row}'] = float(invoice.payment_amount)
        ws[f'F{row}'].number_format = '#,##0.00'
        ws[f'F{row}'].border = border
        total_payment += float(invoice.payment_amount)

        # Method of request
        ws[f'G{row}'] = invoice.method_request
        ws[f'G{row}'].border = border
        ws[f'G{row}'].alignment = Alignment(horizontal='center')

        # Procurement method
        ws[f'H{row}'] = invoice.method_procurement
        ws[f'H{row}'].border = border
        ws[f'H{row}'].alignment = Alignment(horizontal='center')

        # Description
        ws[f'I{row}'] = invoice.description
        ws[f'I{row}'].border = border
        ws[f'I{row}'].alignment = Alignment(wrap_text=True)

        # Invoice date (DD/MM/YYYY format)
        ws[f'J{row}'] = invoice.invoice_date.strftime('%d/%m/%Y') if invoice.invoice_date else ""
        ws[f'J{row}'].border = border
        ws[f'J{row}'].alignment = Alignment(horizontal='center')

        # Invoice number
        ws[f'K{row}'] = invoice.invoice_number
        ws[f'K{row}'].border = border

        # PR number (using PJV for now)
        ws[f'L{row}'] = invoice.pjv_number
        ws[f'L{row}'].border = border

        # PO number
        ws[f'M{row}'] = invoice.po_number or ""
        ws[f'M{row}'].border = border

        # TF number
        ws[f'N{row}'] = invoice.tf_number or ""
        ws[f'N{row}'].border = border
        ws[f'N{row}'].alignment = Alignment(horizontal='center')

        # PJV number
        ws[f'O{row}'] = invoice.pjv_number
        ws[f'O{row}'].border = border

        row += 1

    # Totals row
    ws[f'D{row}'] = "TOTALI:"
    ws[f'D{row}'].font = Font(bold=True)
    ws[f'D{row}'].border = border

    ws[f'E{row}'] = total_invoice
    ws[f'E{row}'].number_format = '#,##0.00'
    ws[f'E{row}'].font = Font(bold=True)
    ws[f'E{row}'].border = border

    ws[f'F{row}'] = total_payment
    ws[f'F{row}'].number_format = '#,##0.00'
    ws[f'F{row}'].font = Font(bold=True)
    ws[f'F{row}'].border = border

    # Add borders to empty cells in totals row
    for col in ['A', 'B', 'C', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O']:
        ws[f'{col}{row}'].border = border

    # Row height for header
    ws.row_dimensions[4].height = 30

    # Legend row
    row += 2
    ws[f'A{row}'] = "* Metodu: P=Part Payment, Inv=Invoice, Rec=Receipt, RFP=Request for Payment, PP=Part Payment, DP=Deposit, EC=Expense Claim"
    ws[f'A{row}'].font = Font(italic=True, size=9)

    row += 1
    ws[f'A{row}'] = "  Prokur.: DA=Direct Order Approvata, D=Direct Order, T=Tender, K=Kwotazzjoni, R=Refund"
    ws[f'A{row}'].font = Font(italic=True, size=9)

    # Save to buffer
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return buffer


def generate_schedule_pdf(
    invoices: List[Invoice],
    sitting_number: Optional[str] = None,
    month_year: Optional[str] = None
) -> BytesIO:
    """
    Generate PDF file for public viewing.

    Args:
        invoices: List of Invoice objects to export
        sitting_number: Council sitting number
        month_year: Month and year string

    Returns:
        BytesIO: PDF file as bytes buffer
    """
    buffer = BytesIO()

    # Create document in landscape
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=10*mm,
        leftMargin=10*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )

    elements = []
    styles = getSampleStyleSheet()

    # Title style
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        alignment=1,  # Center
        spaceAfter=6
    )

    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=12,
        alignment=1,
        spaceAfter=12
    )

    # Add title
    elements.append(Paragraph("KUNSILL LOKALI TAS-SLIEMA", title_style))

    subtitle_text = "SKEDA TAL-HLASIJIET"
    if sitting_number:
        subtitle_text += f" - Seduta Nru. {sitting_number}"
    if month_year:
        subtitle_text += f" - {month_year}"
    elements.append(Paragraph(subtitle_text, subtitle_style))
    elements.append(Spacer(1, 10*mm))

    # Table headers
    table_headers = [
        "#",
        "Fornitur",
        "Ammont (EUR)",
        "Hlas (EUR)",
        "Met.",
        "Prok.",
        "Deskrizzjoni",
        "Data",
        "Inv. Nru",
        "TF Nru"
    ]

    # Table data
    table_data = [table_headers]

    total_invoice = 0
    total_payment = 0

    for idx, invoice in enumerate(invoices, start=1):
        total_invoice += float(invoice.invoice_amount)
        total_payment += float(invoice.payment_amount)

        row = [
            str(idx),
            invoice.supplier.name[:25] + "..." if len(invoice.supplier.name) > 25 else invoice.supplier.name,
            f"{float(invoice.invoice_amount):,.2f}",
            f"{float(invoice.payment_amount):,.2f}",
            invoice.method_request,
            invoice.method_procurement,
            invoice.description[:40] + "..." if len(invoice.description) > 40 else invoice.description,
            invoice.invoice_date.strftime('%d/%m/%Y') if invoice.invoice_date else "",
            invoice.invoice_number[:15] if len(invoice.invoice_number) > 15 else invoice.invoice_number,
            invoice.tf_number or "-"
        ]
        table_data.append(row)

    # Add totals row
    table_data.append([
        "",
        "TOTALI:",
        f"{total_invoice:,.2f}",
        f"{total_payment:,.2f}",
        "", "", "", "", "", ""
    ])

    # Column widths (in mm, converted to points)
    col_widths = [8*mm, 35*mm, 22*mm, 22*mm, 12*mm, 12*mm, 60*mm, 20*mm, 25*mm, 20*mm]

    # Create table
    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    # Table style
    table_style = TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

        # Data rows
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # # column
        ('ALIGN', (2, 1), (3, -1), 'RIGHT'),   # Amount columns
        ('ALIGN', (4, 1), (5, -1), 'CENTER'),  # Method columns
        ('ALIGN', (7, 1), (7, -1), 'CENTER'),  # Date column
        ('ALIGN', (9, 1), (9, -1), 'CENTER'),  # TF column

        # Totals row
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f3f4f6')),

        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),

        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f9fafb')]),
    ])

    table.setStyle(table_style)
    elements.append(table)

    # Legend
    elements.append(Spacer(1, 10*mm))
    legend_style = ParagraphStyle(
        'Legend',
        parent=styles['Normal'],
        fontSize=7,
        textColor=colors.grey
    )
    elements.append(Paragraph(
        "Met.: P=Part Payment, Inv=Invoice, Rec=Receipt, RFP=Request for Payment, PP=Part Payment, DP=Deposit, EC=Expense Claim",
        legend_style
    ))
    elements.append(Paragraph(
        "Prok.: DA=Direct Order Approvata, D=Direct Order, T=Tender, K=Kwotazzjoni, R=Refund",
        legend_style
    ))

    # Footer with generation date
    elements.append(Spacer(1, 5*mm))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=7,
        textColor=colors.grey,
        alignment=2  # Right
    )
    elements.append(Paragraph(
        f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        footer_style
    ))

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    return buffer


def get_export_filename(file_type: str, approved_only: bool = False) -> str:
    """Generate filename for export."""
    now = datetime.now()
    month_year = now.strftime("%B_%Y")
    suffix = "_Approved" if approved_only else "_All"
    return f"Schedule_of_Payments_{month_year}{suffix}.{file_type}"
