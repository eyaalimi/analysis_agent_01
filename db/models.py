"""
db/models.py — SQLAlchemy ORM models for the procurement database.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, Text, DateTime, ForeignKey,
    create_engine,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config import settings

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


# ── Tables ───────────────────────────────────────────────────────────────────

class ProcurementRequest(Base):
    __tablename__ = "procurement_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product = Column(Text, nullable=False)
    category = Column(String(100))
    quantity = Column(Float)
    unit = Column(String(50))
    budget_min = Column(Float)
    budget_max = Column(Float)
    deadline = Column(String(20))
    requester_email = Column(String(255), nullable=False)
    is_valid = Column(Boolean, default=True)
    rejection_reason = Column(Text)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    suppliers = relationship("Supplier", back_populates="request", cascade="all, delete-orphan")
    rfqs = relationship("RFQ", back_populates="request", cascade="all, delete-orphan")
    offers = relationship("Offer", back_populates="request", cascade="all, delete-orphan")
    evaluations = relationship("Evaluation", back_populates="request", cascade="all, delete-orphan")


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("procurement_requests.id"), nullable=False)
    name = Column(String(255), nullable=False)
    website = Column(Text)
    email = Column(String(255))
    country = Column(String(100))
    category = Column(String(100))
    relevance_score = Column(Float)
    source_url = Column(Text)

    request = relationship("ProcurementRequest", back_populates="suppliers")
    rfqs = relationship("RFQ", back_populates="supplier", cascade="all, delete-orphan")
    offers = relationship("Offer", back_populates="supplier", cascade="all, delete-orphan")


class RFQ(Base):
    __tablename__ = "rfqs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("procurement_requests.id"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    subject = Column(String(500))
    message_id = Column(String(500))
    status = Column(String(50), nullable=False)
    sent_at = Column(DateTime(timezone=True), default=utcnow)
    reminder_sent = Column(Boolean, default=False)
    reminder_at = Column(DateTime(timezone=True))

    request = relationship("ProcurementRequest", back_populates="rfqs")
    supplier = relationship("Supplier", back_populates="rfqs")
    offers = relationship("Offer", back_populates="rfq", cascade="all, delete-orphan")


class Offer(Base):
    __tablename__ = "offers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("procurement_requests.id"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    rfq_id = Column(UUID(as_uuid=True), ForeignKey("rfqs.id"), nullable=False)
    unit_price = Column(Float)
    total_price = Column(Float)
    currency = Column(String(10), default="TND")
    delivery_days = Column(Integer)
    warranty = Column(Text)
    payment_terms = Column(Text)
    notes = Column(Text)
    raw_body = Column(Text)
    has_pdf = Column(Boolean, default=False)
    received_at = Column(DateTime(timezone=True), default=utcnow)

    request = relationship("ProcurementRequest", back_populates="offers")
    supplier = relationship("Supplier", back_populates="offers")
    rfq = relationship("RFQ", back_populates="offers")
    evaluation = relationship("Evaluation", back_populates="offer", uselist=False)


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("procurement_requests.id"), nullable=False)
    offer_id = Column(UUID(as_uuid=True), ForeignKey("offers.id"), nullable=False)
    price_score = Column(Float)
    delivery_score = Column(Float)
    warranty_score = Column(Float)
    overall_score = Column(Float)
    rank = Column(Integer)
    recommendation = Column(Text)

    request = relationship("ProcurementRequest", back_populates="evaluations")
    offer = relationship("Offer", back_populates="evaluation")


# ── Engine & Session ─────────────────────────────────────────────────────────

def get_engine(url: str = None):
    return create_engine(url or settings.database_url, echo=False)


def get_session_factory(engine=None):
    eng = engine or get_engine()
    return sessionmaker(bind=eng)


def create_tables(engine=None):
    eng = engine or get_engine()
    Base.metadata.create_all(eng)
