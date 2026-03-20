"""
agents/agent_storage/tools.py
Database operations for the Storage Agent.
No LLM needed — pure CRUD with SQLAlchemy.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from db.models import (
    ProcurementRequest, Supplier, RFQ, Offer,
    get_engine, get_session_factory, create_tables,
)
from logger import get_logger

logger = get_logger(__name__)


class StorageTools:
    """Database CRUD operations for the procurement pipeline."""

    def __init__(self, database_url: str = None):
        self._engine = get_engine(database_url)
        self._Session = get_session_factory(self._engine)
        create_tables(self._engine)

    def _session(self):
        return self._Session()

    # ── Procurement Request ──────────────────────────────────────────────────

    def store_request(self, spec: dict) -> str:
        """
        Store a ProcurementSpec from Agent 1.
        Returns the request_id (UUID string).
        """
        session = self._session()
        try:
            req = ProcurementRequest(
                product=spec.get("product", ""),
                category=spec.get("category", ""),
                quantity=spec.get("quantity"),
                unit=spec.get("unit"),
                budget_min=spec.get("budget_min"),
                budget_max=spec.get("budget_max"),
                deadline=spec.get("deadline"),
                requester_email=spec.get("requester_email", ""),
                is_valid=spec.get("is_valid", True),
                rejection_reason=spec.get("rejection_reason"),
                status="pending",
            )
            session.add(req)
            session.commit()
            request_id = str(req.id)
            logger.info("Stored procurement request", extra={"request_id": request_id})
            return request_id
        except Exception as exc:
            session.rollback()
            logger.error("Failed to store request", extra={"error": str(exc)})
            raise
        finally:
            session.close()

    # ── Suppliers ────────────────────────────────────────────────────────────

    def store_suppliers(self, request_id: str, supplier_list: dict) -> list:
        """
        Store suppliers from Agent 2.
        Returns list of (supplier_name, supplier_db_id) tuples.
        """
        session = self._session()
        try:
            req_uuid = uuid.UUID(request_id)
            result = []
            for s in supplier_list.get("suppliers", []):
                supplier = Supplier(
                    request_id=req_uuid,
                    name=s.get("name", ""),
                    website=s.get("website"),
                    email=s.get("email"),
                    country=s.get("country"),
                    category=s.get("category"),
                    relevance_score=s.get("relevance_score"),
                    source_url=s.get("source_url"),
                )
                session.add(supplier)
                session.flush()
                result.append((s.get("name", ""), str(supplier.id)))

            session.commit()
            logger.info("Stored suppliers", extra={
                "request_id": request_id, "count": len(result),
            })
            return result
        except Exception as exc:
            session.rollback()
            logger.error("Failed to store suppliers", extra={"error": str(exc)})
            raise
        finally:
            session.close()

    # ── RFQs ─────────────────────────────────────────────────────────────────

    def store_rfqs(self, request_id: str, rfq_records: list, supplier_map: dict) -> list:
        """
        Store RFQ records from Agent 3 Phase 1.

        Args:
            request_id: UUID string
            rfq_records: list of RFQRecord dicts
            supplier_map: dict mapping supplier_email -> supplier_db_id

        Returns:
            list of (supplier_name, rfq_db_id) tuples.
        """
        session = self._session()
        try:
            req_uuid = uuid.UUID(request_id)
            result = []
            for r in rfq_records:
                email = r.get("supplier_email", "")
                supplier_id = supplier_map.get(email)
                if not supplier_id:
                    logger.warning("No supplier_id for email", extra={"email": email})
                    continue

                rfq = RFQ(
                    request_id=req_uuid,
                    supplier_id=uuid.UUID(supplier_id),
                    subject=r.get("subject", ""),
                    message_id=r.get("message_id"),
                    status=r.get("status", "failed"),
                    sent_at=datetime.fromisoformat(r["sent_at"]) if r.get("sent_at") else None,
                )
                session.add(rfq)
                session.flush()
                result.append((r.get("supplier_name", ""), str(rfq.id)))

            session.commit()
            logger.info("Stored RFQs", extra={
                "request_id": request_id, "count": len(result),
            })
            return result
        except Exception as exc:
            session.rollback()
            logger.error("Failed to store RFQs", extra={"error": str(exc)})
            raise
        finally:
            session.close()

    # ── Offers ───────────────────────────────────────────────────────────────

    def store_offers(self, request_id: str, offers: list, supplier_map: dict, rfq_map: dict) -> list:
        """
        Store parsed supplier offers from Agent 3 Phase 2.

        Args:
            request_id: UUID string
            offers: list of SupplierOffer dicts
            supplier_map: dict mapping supplier_email -> supplier_db_id
            rfq_map: dict mapping supplier_email -> rfq_db_id

        Returns:
            list of (supplier_name, offer_db_id) tuples.
        """
        session = self._session()
        try:
            req_uuid = uuid.UUID(request_id)
            result = []
            for o in offers:
                email = o.get("supplier_email", "")
                supplier_id = supplier_map.get(email)
                rfq_id = rfq_map.get(email)
                if not supplier_id or not rfq_id:
                    logger.warning("Missing supplier/rfq mapping for offer", extra={"email": email})
                    continue

                offer = Offer(
                    request_id=req_uuid,
                    supplier_id=uuid.UUID(supplier_id),
                    rfq_id=uuid.UUID(rfq_id),
                    unit_price=o.get("unit_price"),
                    total_price=o.get("total_price"),
                    currency=o.get("currency", "TND"),
                    delivery_days=o.get("delivery_days"),
                    warranty=o.get("warranty"),
                    payment_terms=o.get("payment_terms"),
                    notes=o.get("notes"),
                    raw_body=o.get("raw_body"),
                    has_pdf=o.get("has_pdf", False),
                )
                session.add(offer)
                session.flush()
                result.append((o.get("supplier_name", ""), str(offer.id)))

            session.commit()
            logger.info("Stored offers", extra={
                "request_id": request_id, "count": len(result),
            })
            return result
        except Exception as exc:
            session.rollback()
            logger.error("Failed to store offers", extra={"error": str(exc)})
            raise
        finally:
            session.close()

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_request(self, request_id: str) -> Optional[dict]:
        """Fetch a procurement request by ID."""
        session = self._session()
        try:
            req = session.query(ProcurementRequest).filter_by(
                id=uuid.UUID(request_id)
            ).first()
            if not req:
                return None
            return {
                "id": str(req.id),
                "product": req.product,
                "category": req.category,
                "quantity": req.quantity,
                "unit": req.unit,
                "budget_min": req.budget_min,
                "budget_max": req.budget_max,
                "deadline": req.deadline,
                "requester_email": req.requester_email,
                "is_valid": req.is_valid,
                "status": req.status,
                "created_at": req.created_at.isoformat() if req.created_at else None,
            }
        finally:
            session.close()

    def get_offers_for_request(self, request_id: str) -> list:
        """Fetch all offers for a procurement request."""
        session = self._session()
        try:
            offers = session.query(Offer).filter_by(
                request_id=uuid.UUID(request_id)
            ).all()
            return [
                {
                    "id": str(o.id),
                    "supplier_id": str(o.supplier_id),
                    "unit_price": o.unit_price,
                    "total_price": o.total_price,
                    "currency": o.currency,
                    "delivery_days": o.delivery_days,
                    "warranty": o.warranty,
                    "payment_terms": o.payment_terms,
                    "notes": o.notes,
                    "has_pdf": o.has_pdf,
                    "received_at": o.received_at.isoformat() if o.received_at else None,
                }
                for o in offers
            ]
        finally:
            session.close()

    def update_request_status(self, request_id: str, status: str):
        """Update the status of a procurement request."""
        session = self._session()
        try:
            session.query(ProcurementRequest).filter_by(
                id=uuid.UUID(request_id)
            ).update({"status": status})
            session.commit()
            logger.info("Updated request status", extra={
                "request_id": request_id, "status": status,
            })
        except Exception as exc:
            session.rollback()
            logger.error("Failed to update status", extra={"error": str(exc)})
            raise
        finally:
            session.close()

    def mark_reminder_sent(self, rfq_id: str):
        """Mark an RFQ as having had a reminder sent."""
        session = self._session()
        try:
            session.query(RFQ).filter_by(
                id=uuid.UUID(rfq_id)
            ).update({
                "reminder_sent": True,
                "reminder_at": datetime.now(timezone.utc),
            })
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error("Failed to mark reminder", extra={"error": str(exc)})
            raise
        finally:
            session.close()
