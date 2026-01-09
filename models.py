from sqlalchemy import Column, Integer, String, Text, Numeric, Date, Boolean, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    contact_email = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    invoices = relationship("Invoice", back_populates="supplier")

    def __repr__(self):
        return f"<Supplier(id={self.id}, name='{self.name}')>"


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Core invoice data
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    invoice_amount = Column(Numeric(10, 2), nullable=False)
    payment_amount = Column(Numeric(10, 2), nullable=False)

    # Method classifications
    method_request = Column(
        String(10),
        nullable=False,
        info={'check': "method_request IN ('P', 'Inv', 'Rec', 'RFP', 'PP', 'DP', 'EC')"}
    )
    method_procurement = Column(
        String(10),
        nullable=False,
        info={'check': "method_procurement IN ('DA', 'D', 'T', 'K', 'R')"}
    )

    # Invoice details
    description = Column(Text, nullable=False)
    invoice_date = Column(Date, nullable=False)
    invoice_number = Column(String(100), nullable=False)

    # Reference numbers
    po_number = Column(String(100), nullable=True)  # Purchase Order (optional)
    pjv_number = Column(String(100), nullable=False, unique=True)  # Purchase Journal Voucher (required)
    tf_number = Column(String(100), nullable=True)  # Transfer of Funds (only after approval)

    # Approval tracking
    is_approved = Column(Boolean, default=False)
    approved_date = Column(Date, nullable=True)
    proposer_councillor = Column(String(255), nullable=True)
    seconder_councillor = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Soft delete
    is_deleted = Column(Boolean, default=False)

    # Fiscal receipt attachment
    fiscal_receipt_path = Column(String(500), nullable=True)

    # Email source tracking (for AI-created invoices)
    source_email_id = Column(String(255), nullable=True)
    is_ai_generated = Column(Boolean, default=False)

    # Relationships
    supplier = relationship("Supplier", back_populates="invoices")

    __table_args__ = (
        CheckConstraint(
            "method_request IN ('P', 'Inv', 'Rec', 'RFP', 'PP', 'DP', 'EC')",
            name='check_method_request'
        ),
        CheckConstraint(
            "method_procurement IN ('DA', 'D', 'T', 'K', 'R')",
            name='check_method_procurement'
        ),
    )

    def __repr__(self):
        return f"<Invoice(id={self.id}, pjv='{self.pjv_number}', tf='{self.tf_number}')>"


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)

    def __repr__(self):
        return f"<Setting(key='{self.key}', value='{self.value}')>"


# Method code descriptions for display
METHOD_REQUEST_CODES = {
    'P': 'Part Payment',
    'Inv': 'Invoice',
    'Rec': 'Receipt',
    'RFP': 'Request for Payment',
    'PP': 'Part Payment',
    'DP': 'Deposit',
    'EC': 'Expense Claim'
}

METHOD_PROCUREMENT_CODES = {
    'DA': 'Direct Order Approvata (Approved Direct Order)',
    'D': 'Direct Order',
    'T': 'Tender',
    'K': 'Kwotazzjoni (Quotation)',
    'R': 'Refund'
}

