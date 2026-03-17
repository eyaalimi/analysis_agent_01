"""
tests/test_agent_sourcing.py
Unit tests for the Sourcing Agent (Agent 2).

All tests use mocks — no real Tavily or Bedrock calls are made.
Run with: pytest tests/test_agent_sourcing.py -v
"""

import json
import pytest
from dataclasses import asdict
from unittest.mock import MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_procurement_spec():
    """Sample output from Agent 1 — a valid procurement request."""
    return {
        "product": "wooden office desk",
        "category": "Office Supplies",
        "quantity": 1,
        "unit": "units",
        "budget_min": None,
        "budget_max": 500,
        "deadline": "2026-04-15",
        "requester_email": "test@example.com",
        "is_valid": True,
        "rejection_reason": None,
    }


@pytest.fixture
def mock_tavily_search_response():
    """Simulated Tavily /search API response for a supplier search."""
    return {
        "results": [
            {
                "title": "OfficePro Furniture — Desks & Chairs",
                "url": "https://www.officepro.com/desks",
                "content": "Contact our sales team at sales@officepro.com. "
                            "We supply office desks, chairs and furniture worldwide.",
                "score": 0.92,
            },
            {
                "title": "DeskMasters Wholesale Supplier",
                "url": "https://www.deskmasters.com",
                "content": "Wholesale office furniture manufacturer. "
                            "Email: info@deskmasters.com — bulk orders welcome.",
                "score": 0.85,
            },
        ]
    }


# ── Tool: search_suppliers ────────────────────────────────────────────────────

class TestSearchSuppliersTool:
    """Unit tests for the search_suppliers @tool function."""

    def test_returns_empty_list_when_no_api_key(self, monkeypatch):
        """Must return [] when TAVILY_API_KEY is not set."""
        from agents.agent_sourcing.agent import search_suppliers
        monkeypatch.setattr("agents.agent_sourcing.agent.settings.tavily_api_key", "")

        result = json.loads(search_suppliers("desk", "Office Supplies"))

        assert result == []

    def test_returns_simplified_results_on_success(
        self, monkeypatch, mock_tavily_search_response
    ):
        """Must return a list of simplified result dicts on a successful Tavily call."""
        from agents.agent_sourcing.agent import search_suppliers
        monkeypatch.setattr("agents.agent_sourcing.agent.settings.tavily_api_key", "fake-key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_tavily_search_response
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp):
            result = json.loads(search_suppliers("wooden office desk", "Office Supplies"))

        assert len(result) == 2
        assert result[0]["url"] == "https://www.officepro.com/desks"
        assert result[0]["score"] == 0.92
        assert "title" in result[0]
        assert "content" in result[0]

    def test_returns_empty_list_on_network_error(self, monkeypatch):
        """Must return [] gracefully on a network/timeout error."""
        import requests as req
        from agents.agent_sourcing.agent import search_suppliers
        monkeypatch.setattr("agents.agent_sourcing.agent.settings.tavily_api_key", "fake-key")

        with patch("requests.post", side_effect=req.RequestException("timeout")):
            result = json.loads(search_suppliers("desk", "Office Supplies"))

        assert result == []

    def test_content_is_truncated_to_400_chars(self, monkeypatch):
        """Content in results must be trimmed to 400 characters."""
        from agents.agent_sourcing.agent import search_suppliers
        monkeypatch.setattr("agents.agent_sourcing.agent.settings.tavily_api_key", "fake-key")

        long_content = "A" * 1000
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [{"title": "T", "url": "https://x.com", "content": long_content, "score": 0.5}]
        }
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp):
            result = json.loads(search_suppliers("item", "Category"))

        assert len(result[0]["content"]) == 400


# ── Tool: get_supplier_contact ────────────────────────────────────────────────

class TestGetSupplierContactTool:
    """Unit tests for the get_supplier_contact @tool function."""

    def test_returns_null_when_no_api_key(self, monkeypatch):
        """Must return {"email": null} when TAVILY_API_KEY is not set."""
        from agents.agent_sourcing.agent import get_supplier_contact
        monkeypatch.setattr("agents.agent_sourcing.agent.settings.tavily_api_key", "")

        result = json.loads(get_supplier_contact("OfficePro", "https://officepro.com"))

        assert result["email"] is None

    def test_extracts_email_from_search_content(self, monkeypatch):
        """Must extract the first valid email found in search result content."""
        from agents.agent_sourcing.agent import get_supplier_contact
        monkeypatch.setattr("agents.agent_sourcing.agent.settings.tavily_api_key", "fake-key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [{"content": "Reach us at contact@supplier.com for procurement inquiries."}]
        }
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp):
            result = json.loads(get_supplier_contact("Supplier Co", "https://supplier.com"))

        assert result["email"] == "contact@supplier.com"

    def test_skips_noreply_emails(self, monkeypatch):
        """Must skip noreply/donotreply addresses and return null if no other email found."""
        from agents.agent_sourcing.agent import get_supplier_contact
        monkeypatch.setattr("agents.agent_sourcing.agent.settings.tavily_api_key", "fake-key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [{"content": "System email: noreply@company.com"}]
        }
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp):
            result = json.loads(get_supplier_contact("Company", "https://company.com"))

        assert result["email"] is None

    def test_returns_null_when_no_email_in_content(self, monkeypatch):
        """Must return {"email": null} when no email is found in search results."""
        from agents.agent_sourcing.agent import get_supplier_contact
        monkeypatch.setattr("agents.agent_sourcing.agent.settings.tavily_api_key", "fake-key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [{"content": "Visit our website for product information."}]
        }
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp):
            result = json.loads(get_supplier_contact("Supplier", "https://supplier.com"))

        assert result["email"] is None

    def test_returns_null_on_network_error(self, monkeypatch):
        """Must return {"email": null} gracefully on a network error."""
        import requests as req
        from agents.agent_sourcing.agent import get_supplier_contact
        monkeypatch.setattr("agents.agent_sourcing.agent.settings.tavily_api_key", "fake-key")

        with patch("requests.post", side_effect=req.RequestException("timeout")):
            result = json.loads(get_supplier_contact("Supplier", "https://supplier.com"))

        assert result["email"] is None


# ── SourcingAgent (LLM mocked) ────────────────────────────────────────────────

class TestSourcingAgent:
    """Integration tests for SourcingAgent with mocked Bedrock/Strands."""

    # Simulated LLM JSON response
    MOCK_LLM_RESPONSE = json.dumps({
        "suppliers": [
            {
                "name": "OfficePro Furniture",
                "website": "https://www.officepro.com",
                "country": "USA",
                "email": "sales@officepro.com",
                "category": "Office Supplies",
                "relevance_score": 0.92,
                "source_url": "https://www.officepro.com/desks",
            },
            {
                "name": "DeskMasters",
                "website": "https://www.deskmasters.com",
                "country": "Germany",
                "email": "info@deskmasters.com",
                "category": "Office Supplies",
                "relevance_score": 0.85,
                "source_url": "https://www.deskmasters.com",
            },
        ],
        "query_used": "wooden office desk supplier manufacturer Office Supplies",
        "search_timestamp": "2026-03-17T10:00:00+00:00",
    })

    def _make_agent(self, llm_response: str):
        """Helper: create a SourcingAgent with a mocked LLM."""
        from agents.agent_sourcing.agent import SourcingAgent

        with patch("agents.agent_sourcing.agent.BedrockModel"):
            with patch("agents.agent_sourcing.agent.Agent"):
                agent = SourcingAgent()
                # Replace the internal agent with a callable mock that returns llm_response
                agent._agent = MagicMock(return_value=llm_response)
                return agent

    def test_source_returns_supplier_list(self, valid_procurement_spec):
        """source() must return a SupplierList with the correct suppliers."""
        from agents.agent_sourcing.agent import SupplierList

        agent = self._make_agent(self.MOCK_LLM_RESPONSE)
        result = agent.source(valid_procurement_spec)

        assert isinstance(result, SupplierList)
        assert len(result.suppliers) == 2
        assert result.suppliers[0].name == "OfficePro Furniture"
        assert result.suppliers[0].relevance_score == 0.92
        assert result.suppliers[0].email == "sales@officepro.com"
        assert result.suppliers[1].name == "DeskMasters"

    def test_source_suppliers_sorted_by_score(self, valid_procurement_spec):
        """Suppliers must come sorted by relevance_score descending."""
        agent = self._make_agent(self.MOCK_LLM_RESPONSE)
        result = agent.source(valid_procurement_spec)

        scores = [s.relevance_score for s in result.suppliers]
        assert scores == sorted(scores, reverse=True)

    def test_source_returns_empty_on_invalid_json(self, valid_procurement_spec):
        """source() must return an empty SupplierList when LLM returns invalid JSON."""
        from agents.agent_sourcing.agent import SupplierList

        agent = self._make_agent("not valid json {{{{")
        result = agent.source(valid_procurement_spec)

        assert isinstance(result, SupplierList)
        assert result.suppliers == []

    def test_source_handles_markdown_wrapped_json(self, valid_procurement_spec):
        """source() must correctly parse JSON wrapped in markdown code fences."""
        from agents.agent_sourcing.agent import SupplierList

        wrapped = f"```json\n{self.MOCK_LLM_RESPONSE}\n```"
        agent = self._make_agent(wrapped)
        result = agent.source(valid_procurement_spec)

        assert isinstance(result, SupplierList)
        assert len(result.suppliers) == 2

    def test_source_output_is_json_serializable(self, valid_procurement_spec):
        """SupplierList output must be fully serializable via asdict + json.dumps."""
        agent = self._make_agent(self.MOCK_LLM_RESPONSE)
        result = agent.source(valid_procurement_spec)

        result_dict = asdict(result)
        serialized = json.dumps(result_dict)  # Must not raise
        parsed = json.loads(serialized)

        assert "suppliers" in parsed
        assert len(parsed["suppliers"]) == 2

    def test_source_uses_product_and_category_in_query(self, valid_procurement_spec):
        """query_used in the result must reflect the product and category."""
        agent = self._make_agent(self.MOCK_LLM_RESPONSE)
        result = agent.source(valid_procurement_spec)

        assert "wooden office desk" in result.query_used.lower() or \
               "office supplies" in result.query_used.lower()


# ── Run tests directly ────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
