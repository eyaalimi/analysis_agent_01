"""
tests/test_agent_communication.py
Unit tests for the Communication Agent (Agent 3).

All tests use mocks — no real SMTP, IMAP, or Bedrock calls are made.
Run with: pytest tests/test_agent_communication.py -v
"""

import json
import pytest
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def procurement_spec():
    """Sample procurement spec from Agent 1."""
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
    }


@pytest.fixture
def supplier_list():
    """Sample supplier list from Agent 2."""
    return {
        "suppliers": [
            {
                "name": "SupplierA",
                "website": "https://suppliera.tn",
                "email": "contact@suppliera.tn",
                "category": "Office Supplies",
                "relevance_score": 0.95,
            },
            {
                "name": "SupplierB",
                "website": "https://supplierb.tn",
                "email": None,  # No email — agent should try recovery
                "category": "Office Supplies",
                "relevance_score": 0.88,
            },
            {
                "name": "SupplierC",
                "website": "https://supplierc.tn",
                "email": "info@supplierc.tn",
                "category": "Office Supplies",
                "relevance_score": 0.80,
            },
        ],
        "query_used": "ergonomic office chairs Tunisia",
        "search_timestamp": "2026-03-19T10:00:00Z",
    }


# ── Tool: send_email_to_supplier ──────────────────────────────────────────────

class TestSendEmailToSupplierTool:
    """Unit tests for the send_email_to_supplier @tool function."""

    def test_send_success(self):
        """Must return status=sent and a message_id on success."""
        from agents.agent_communication.tools import send_email_to_supplier

        mock_sender = MagicMock()
        mock_sender.send.return_value = "<msg-123@gmail.com>"

        with patch("agents.agent_communication.tools.EmailSender", return_value=mock_sender):
            result = json.loads(send_email_to_supplier(
                "contact@test.com", "TestCo", "RFQ — chairs", "Please quote..."
            ))

        assert result["status"] == "sent"
        assert result["message_id"] == "<msg-123@gmail.com>"
        assert result["error"] is None

    def test_send_failure(self):
        """Must return status=failed with error on SMTP failure."""
        from agents.agent_communication.tools import send_email_to_supplier

        mock_sender = MagicMock()
        mock_sender.send.side_effect = Exception("SMTP connection refused")

        with patch("agents.agent_communication.tools.EmailSender", return_value=mock_sender):
            result = json.loads(send_email_to_supplier(
                "contact@test.com", "TestCo", "RFQ — chairs", "Please quote..."
            ))

        assert result["status"] == "failed"
        assert result["message_id"] is None
        assert "SMTP" in result["error"]


# ── Tool: retry_find_supplier_email ───────────────────────────────────────────

class TestRetryFindSupplierEmail:
    """Unit tests for the retry_find_supplier_email @tool function."""

    def test_finds_email_on_contact_page(self):
        """Must return the email found via scraping."""
        from agents.agent_communication.tools import retry_find_supplier_email

        def mock_scrape(url):
            if "/contact" in url:
                return "found@supplier.tn"
            return None

        with patch("agents.agent_communication.tools._scrape_email_from_url", side_effect=mock_scrape):
            result = json.loads(retry_find_supplier_email("SupplierB", "https://supplierb.tn"))

        assert result["email"] == "found@supplier.tn"

    def test_returns_null_when_not_found(self):
        """Must return null when no email is found."""
        from agents.agent_communication.tools import retry_find_supplier_email

        with patch("agents.agent_communication.tools._scrape_email_from_url", return_value=None):
            result = json.loads(retry_find_supplier_email("SupplierX", "https://supplierx.tn"))

        assert result["email"] is None


# ── Tool: fetch_supplier_replies ──────────────────────────────────────────────

class TestFetchSupplierReplies:
    """Unit tests for the fetch_supplier_replies @tool function."""

    def test_returns_empty_when_no_credentials(self, monkeypatch):
        """Must return [] if Gmail credentials are not configured."""
        from agents.agent_communication.tools import fetch_supplier_replies
        monkeypatch.setattr("agents.agent_communication.tools.settings.gmail_address", "")

        result = json.loads(fetch_supplier_replies("RFQ — chairs"))

        assert result == []

    def test_returns_empty_on_imap_error(self, monkeypatch):
        """Must return [] on IMAP connection failure."""
        from agents.agent_communication.tools import fetch_supplier_replies
        monkeypatch.setattr("agents.agent_communication.tools.settings.gmail_address", "test@gmail.com")
        monkeypatch.setattr("agents.agent_communication.tools.settings.gmail_app_password", "pass")

        with patch("agents.agent_communication.tools.imaplib.IMAP4_SSL", side_effect=Exception("Connection refused")):
            result = json.loads(fetch_supplier_replies("RFQ — chairs"))

        assert result == []


# ── Helper: is_reminder_due ───────────────────────────────────────────────────

class TestIsReminderDue:
    """Unit tests for the is_reminder_due helper function."""

    def test_returns_true_after_threshold(self):
        """Must return True when enough time has passed."""
        from agents.agent_communication.tools import is_reminder_due
        # 4 days ago
        old_time = (datetime.now(timezone.utc) - timedelta(hours=96)).isoformat()
        assert is_reminder_due(old_time, hours_threshold=72) is True

    def test_returns_false_before_threshold(self):
        """Must return False when not enough time has passed."""
        from agents.agent_communication.tools import is_reminder_due
        # 1 hour ago
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert is_reminder_due(recent_time, hours_threshold=72) is False

    def test_returns_false_on_invalid_date(self):
        """Must return False on invalid/empty date string."""
        from agents.agent_communication.tools import is_reminder_due
        assert is_reminder_due("", hours_threshold=72) is False
        assert is_reminder_due("not-a-date", hours_threshold=72) is False


# ── CommunicationAgent (LLM mocked) ──────────────────────────────────────────

class TestCommunicationAgent:
    """Integration tests for CommunicationAgent with mocked Bedrock/Strands."""

    MOCK_RFQ_RESPONSE = json.dumps({
        "rfqs": [
            {
                "supplier_name": "SupplierA",
                "supplier_email": "contact@suppliera.tn",
                "status": "sent",
                "message_id": "<msg-001@gmail.com>",
                "error": None,
            },
            {
                "supplier_name": "SupplierB",
                "supplier_email": "",
                "status": "skipped_no_email",
                "message_id": None,
                "error": None,
            },
            {
                "supplier_name": "SupplierC",
                "supplier_email": "info@supplierc.tn",
                "status": "sent",
                "message_id": "<msg-002@gmail.com>",
                "error": None,
            },
        ],
        "total_sent": 2,
        "total_skipped": 1,
        "total_failed": 0,
    })

    MOCK_PARSE_RESPONSE = json.dumps({
        "offers": [
            {
                "supplier_name": "SupplierA",
                "supplier_email": "contact@suppliera.tn",
                "unit_price": 450.0,
                "total_price": 4500.0,
                "currency": "TND",
                "delivery_days": 14,
                "warranty": "2 years",
                "payment_terms": "30 days net",
                "notes": "Free delivery for orders above 3000 TND",
                "raw_body": "Bonjour, suite a votre demande...",
            }
        ],
        "total_parsed": 1,
    })

    MOCK_REMINDER_RESPONSE = json.dumps({
        "reminders": [
            {
                "supplier_name": "SupplierC",
                "supplier_email": "info@supplierc.tn",
                "status": "sent",
                "error": None,
            }
        ],
        "total_sent": 1,
    })

    def _make_agent(self, rfq_response=None, parse_response=None, reminder_response=None):
        """Helper: create a CommunicationAgent with mocked LLMs."""
        from agents.agent_communication.agent import CommunicationAgent

        with patch("agents.agent_communication.agent.BedrockModel"):
            with patch("agents.agent_communication.agent.Agent"):
                agent = CommunicationAgent()
                agent._rfq_agent = MagicMock(return_value=rfq_response or self.MOCK_RFQ_RESPONSE)
                agent._parse_agent = MagicMock(return_value=parse_response or self.MOCK_PARSE_RESPONSE)
                agent._reminder_agent = MagicMock(return_value=reminder_response or self.MOCK_REMINDER_RESPONSE)
                return agent

    def test_send_rfqs_returns_records(self, procurement_spec, supplier_list):
        """send_rfqs() must return a list of RFQRecord objects."""
        agent = self._make_agent()
        records = agent.send_rfqs(procurement_spec, supplier_list)

        assert len(records) == 3
        sent = [r for r in records if r.status == "sent"]
        skipped = [r for r in records if r.status == "skipped_no_email"]
        assert len(sent) == 2
        assert len(skipped) == 1
        assert sent[0].supplier_name == "SupplierA"
        assert sent[0].message_id == "<msg-001@gmail.com>"

    def test_check_responses_returns_offers(self, procurement_spec):
        """check_responses() must return parsed SupplierOffer objects."""
        from agents.agent_communication.agent import SupplierOffer

        agent = self._make_agent()
        rfq_records = [
            {"supplier_name": "SupplierA", "supplier_email": "contact@suppliera.tn",
             "status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()},
        ]
        offers = agent.check_responses(rfq_records, "ergonomic office chairs")

        assert len(offers) == 1
        assert isinstance(offers[0], SupplierOffer)
        assert offers[0].supplier_name == "SupplierA"
        assert offers[0].unit_price == 450.0
        assert offers[0].total_price == 4500.0
        assert offers[0].currency == "TND"
        assert offers[0].delivery_days == 14

    def test_send_reminders_for_non_respondents(self, procurement_spec):
        """send_reminders() must send to suppliers past the threshold who haven't responded."""
        agent = self._make_agent()

        # RFQ sent 4 days ago
        old_time = (datetime.now(timezone.utc) - timedelta(hours=96)).isoformat()
        rfq_records = [
            {"supplier_name": "SupplierA", "supplier_email": "contact@suppliera.tn",
             "status": "sent", "sent_at": old_time},
            {"supplier_name": "SupplierC", "supplier_email": "info@supplierc.tn",
             "status": "sent", "sent_at": old_time},
        ]

        # SupplierA already responded
        responded = ["contact@suppliera.tn"]

        reminders = agent.send_reminders(
            rfq_records, responded, "ergonomic office chairs", hours_threshold=72
        )

        assert len(reminders) == 1
        assert reminders[0].supplier_name == "SupplierC"
        assert reminders[0].status == "sent"

    def test_send_reminders_skips_if_not_due(self, procurement_spec):
        """send_reminders() must skip if threshold not reached."""
        agent = self._make_agent()

        # RFQ sent 1 hour ago
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        rfq_records = [
            {"supplier_name": "SupplierA", "supplier_email": "contact@suppliera.tn",
             "status": "sent", "sent_at": recent_time},
        ]

        reminders = agent.send_reminders(
            rfq_records, [], "ergonomic office chairs", hours_threshold=72
        )

        assert reminders == []

    def test_run_full_cycle_returns_communication_result(self, procurement_spec, supplier_list):
        """run_full_cycle() must return a complete CommunicationResult."""
        from agents.agent_communication.agent import CommunicationResult

        agent = self._make_agent()
        result = agent.run_full_cycle(procurement_spec, supplier_list)

        assert isinstance(result, CommunicationResult)
        assert len(result.rfqs_sent) == 3
        assert isinstance(result.timestamp, str)

    def test_full_cycle_output_is_json_serializable(self, procurement_spec, supplier_list):
        """CommunicationResult must be fully serializable via asdict + json.dumps."""
        agent = self._make_agent()
        result = agent.run_full_cycle(procurement_spec, supplier_list)

        result_dict = asdict(result)
        serialized = json.dumps(result_dict, default=str)
        parsed = json.loads(serialized)

        assert "rfqs_sent" in parsed
        assert "offers_received" in parsed
        assert "reminders_sent" in parsed
        assert "pending_suppliers" in parsed

    def test_send_rfqs_handles_llm_failure(self, procurement_spec, supplier_list):
        """send_rfqs() must return fallback records when LLM fails."""
        agent = self._make_agent(rfq_response="not valid json {{{{")
        records = agent.send_rfqs(procurement_spec, supplier_list)

        # Should fall back to supplier-based records
        assert len(records) == 3


# ── Run tests directly ────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
