"""
tests/test_agent_storage.py
Unit tests for the Storage Agent (Agent 4).

Uses SQLite in-memory — no PostgreSQL needed.
Run with: pytest tests/test_agent_storage.py -v
"""
import pytest
from datetime import datetime, timezone

from agents.agent_storage.agent import StorageAgent, StorageResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def storage_agent():
    """Create a StorageAgent backed by an in-memory SQLite database."""
    agent = StorageAgent(database_url="sqlite:///:memory:")
    return agent


@pytest.fixture
def sample_spec():
    return {
        "product": "ergonomic office chairs",
        "category": "Office Supplies",
        "quantity": 10,
        "unit": "units",
        "budget_min": None,
        "budget_max": 5000,
        "deadline": "2026-04-30",
        "requester_email": "buyer@company.com",
        "is_valid": True,
        "rejection_reason": None,
    }


@pytest.fixture
def sample_suppliers():
    return {
        "suppliers": [
            {
                "name": "SupplierA",
                "website": "https://suppliera.com",
                "email": "contact@suppliera.com",
                "category": "Office Supplies",
                "relevance_score": 0.95,
            },
            {
                "name": "SupplierB",
                "website": "https://supplierb.com",
                "email": "info@supplierb.com",
                "category": "Office Supplies",
                "relevance_score": 0.88,
            },
        ],
        "query_used": "ergonomic chairs",
        "search_timestamp": "2026-03-20T10:00:00Z",
    }


@pytest.fixture
def sample_rfqs():
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "supplier_name": "SupplierA",
            "supplier_email": "contact@suppliera.com",
            "subject": "RFQ — ergonomic office chairs",
            "message_id": "<msg-001@gmail.com>",
            "status": "sent",
            "sent_at": now,
        },
        {
            "supplier_name": "SupplierB",
            "supplier_email": "info@supplierb.com",
            "subject": "RFQ — ergonomic office chairs",
            "message_id": "<msg-002@gmail.com>",
            "status": "sent",
            "sent_at": now,
        },
    ]


@pytest.fixture
def sample_offers():
    return [
        {
            "supplier_name": "SupplierA",
            "supplier_email": "contact@suppliera.com",
            "unit_price": 450.0,
            "total_price": 4500.0,
            "currency": "TND",
            "delivery_days": 14,
            "warranty": "2 years",
            "payment_terms": "30 days net",
            "notes": "Free delivery",
            "raw_body": "Thank you for your RFQ...",
            "has_pdf": False,
        },
    ]


# ── Store request ────────────────────────────────────────────────────────────

class TestStoreRequest:

    def test_returns_uuid(self, storage_agent, sample_spec):
        request_id = storage_agent.store_request(sample_spec)
        assert request_id is not None
        assert len(request_id) == 36  # UUID format

    def test_request_is_retrievable(self, storage_agent, sample_spec):
        request_id = storage_agent.store_request(sample_spec)
        req = storage_agent.get_request(request_id)
        assert req is not None
        assert req["product"] == "ergonomic office chairs"
        assert req["budget_max"] == 5000
        assert req["requester_email"] == "buyer@company.com"

    def test_request_status_is_analyzing(self, storage_agent, sample_spec):
        request_id = storage_agent.store_request(sample_spec)
        req = storage_agent.get_request(request_id)
        assert req["status"] == "analyzing"


# ── Store suppliers ──────────────────────────────────────────────────────────

class TestStoreSuppliers:

    def test_returns_email_mapping(self, storage_agent, sample_spec, sample_suppliers):
        request_id = storage_agent.store_request(sample_spec)
        supplier_map = storage_agent.store_suppliers(request_id, sample_suppliers)
        assert "contact@suppliera.com" in supplier_map
        assert "info@supplierb.com" in supplier_map

    def test_status_updated_to_sourcing(self, storage_agent, sample_spec, sample_suppliers):
        request_id = storage_agent.store_request(sample_spec)
        storage_agent.store_suppliers(request_id, sample_suppliers)
        req = storage_agent.get_request(request_id)
        assert req["status"] == "sourcing"


# ── Store RFQs ───────────────────────────────────────────────────────────────

class TestStoreRFQs:

    def test_returns_rfq_mapping(self, storage_agent, sample_spec, sample_suppliers, sample_rfqs):
        request_id = storage_agent.store_request(sample_spec)
        supplier_map = storage_agent.store_suppliers(request_id, sample_suppliers)
        rfq_map = storage_agent.store_rfqs(request_id, sample_rfqs, supplier_map)
        assert "contact@suppliera.com" in rfq_map
        assert "info@supplierb.com" in rfq_map

    def test_status_updated_to_rfqs_sent(self, storage_agent, sample_spec, sample_suppliers, sample_rfqs):
        request_id = storage_agent.store_request(sample_spec)
        supplier_map = storage_agent.store_suppliers(request_id, sample_suppliers)
        storage_agent.store_rfqs(request_id, sample_rfqs, supplier_map)
        req = storage_agent.get_request(request_id)
        assert req["status"] == "rfqs_sent"


# ── Store offers ─────────────────────────────────────────────────────────────

class TestStoreOffers:

    def test_stores_and_retrieves_offers(
        self, storage_agent, sample_spec, sample_suppliers, sample_rfqs, sample_offers,
    ):
        request_id = storage_agent.store_request(sample_spec)
        supplier_map = storage_agent.store_suppliers(request_id, sample_suppliers)
        rfq_map = storage_agent.store_rfqs(request_id, sample_rfqs, supplier_map)
        stored = storage_agent.store_offers(request_id, sample_offers, supplier_map, rfq_map)

        assert len(stored) == 1
        assert stored[0][0] == "SupplierA"

        offers = storage_agent.get_offers(request_id)
        assert len(offers) == 1
        assert offers[0]["unit_price"] == 450.0
        assert offers[0]["total_price"] == 4500.0
        assert offers[0]["delivery_days"] == 14

    def test_status_updated_to_offers_received(
        self, storage_agent, sample_spec, sample_suppliers, sample_rfqs, sample_offers,
    ):
        request_id = storage_agent.store_request(sample_spec)
        supplier_map = storage_agent.store_suppliers(request_id, sample_suppliers)
        rfq_map = storage_agent.store_rfqs(request_id, sample_rfqs, supplier_map)
        storage_agent.store_offers(request_id, sample_offers, supplier_map, rfq_map)
        req = storage_agent.get_request(request_id)
        assert req["status"] == "offers_received"


# ── Full pipeline ────────────────────────────────────────────────────────────

class TestFullPipeline:

    def test_store_full_pipeline(
        self, storage_agent, sample_spec, sample_suppliers, sample_rfqs, sample_offers,
    ):
        result = storage_agent.store_full_pipeline(
            sample_spec, sample_suppliers, sample_rfqs, sample_offers,
        )
        assert isinstance(result, StorageResult)
        assert result.suppliers_stored == 2
        assert result.rfqs_stored == 2
        assert result.offers_stored == 1
        assert result.status == "offers_received"
        assert len(result.request_id) == 36

    def test_full_pipeline_data_integrity(
        self, storage_agent, sample_spec, sample_suppliers, sample_rfqs, sample_offers,
    ):
        result = storage_agent.store_full_pipeline(
            sample_spec, sample_suppliers, sample_rfqs, sample_offers,
        )
        req = storage_agent.get_request(result.request_id)
        assert req["product"] == "ergonomic office chairs"

        offers = storage_agent.get_offers(result.request_id)
        assert len(offers) == 1
        assert offers[0]["currency"] == "TND"


# ── Status updates ───────────────────────────────────────────────────────────

class TestStatusUpdates:

    def test_update_status(self, storage_agent, sample_spec):
        request_id = storage_agent.store_request(sample_spec)
        storage_agent.update_status(request_id, "completed")
        req = storage_agent.get_request(request_id)
        assert req["status"] == "completed"

    def test_get_nonexistent_request_returns_none(self, storage_agent):
        result = storage_agent.get_request("00000000-0000-0000-0000-000000000000")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
