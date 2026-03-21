"""
tests/test_orchestrator.py
Unit tests for the Orchestrator (Strands Agents-as-Tools pattern).

Two test layers:
  1. Tool-level tests — mock the sub-agents, test each @tool function
  2. Orchestrator-level tests — mock the Strands Agent, test result parsing

Run with: pytest tests/test_orchestrator.py -v
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, asdict

from agents.orchestrator.agent import (
    Orchestrator,
    STAGE_COMPLETED,
    STAGE_REJECTED,
    STAGE_FAILED,
)


# ── Fake dataclasses to simulate agent outputs ──────────────────────────────

@dataclass
class FakeSpec:
    product: str = "ergonomic office chairs"
    category: str = "Office Supplies"
    quantity: int = 10
    unit: str = "units"
    budget_min: float = None
    budget_max: float = 5000
    deadline: str = "2026-04-30"
    requester_email: str = "user@company.com"
    is_valid: bool = True
    rejection_reason: str = None


@dataclass
class FakeSupplierList:
    suppliers: list = None
    query_used: str = "office chairs"
    search_timestamp: str = "2026-03-20T10:00:00Z"

    def __post_init__(self):
        if self.suppliers is None:
            self.suppliers = [
                {"name": "SupA", "email": "a@sup.com", "website": "https://supa.tn"},
                {"name": "SupB", "email": "b@sup.com", "website": "https://supb.tn"},
            ]


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: Tool-level tests (mock sub-agents, test @tool functions directly)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeRequestTool:

    @patch("agents.orchestrator.tools._get_analysis_agent")
    def test_returns_json_string(self, mock_get):
        mock_agent = MagicMock()
        mock_agent.analyze.return_value = FakeSpec()
        mock_get.return_value = mock_agent

        from agents.orchestrator.tools import analyze_request
        result = analyze_request(
            email_body="I need 10 office chairs",
            requester_email="user@company.com",
        )

        data = json.loads(result)
        assert data["product"] == "ergonomic office chairs"
        assert data["is_valid"] is True
        mock_agent.analyze.assert_called_once()

    @patch("agents.orchestrator.tools._get_analysis_agent")
    def test_rejected_request(self, mock_get):
        mock_agent = MagicMock()
        mock_agent.analyze.return_value = FakeSpec(
            is_valid=False, rejection_reason="Missing product", product=""
        )
        mock_get.return_value = mock_agent

        from agents.orchestrator.tools import analyze_request
        result = analyze_request(email_body="", requester_email="user@co.com")

        data = json.loads(result)
        assert data["is_valid"] is False
        assert data["rejection_reason"] == "Missing product"


class TestSourceSuppliersTool:

    @patch("agents.orchestrator.tools._get_sourcing_agent")
    def test_returns_supplier_list(self, mock_get):
        mock_agent = MagicMock()
        mock_agent.source.return_value = FakeSupplierList()
        mock_get.return_value = mock_agent

        from agents.orchestrator.tools import source_suppliers
        spec_json = json.dumps(asdict(FakeSpec()))
        result = source_suppliers(procurement_spec_json=spec_json)

        data = json.loads(result)
        assert len(data["suppliers"]) == 2
        assert data["suppliers"][0]["name"] == "SupA"


class TestSendRfqsTool:

    @patch("agents.orchestrator.tools._get_communication_agent")
    def test_returns_communication_result(self, mock_get):
        mock_agent = MagicMock()
        comm = MagicMock()
        comm.__dict__ = {}  # Make asdict-like conversion work
        mock_agent.run_full_cycle.return_value = {
            "rfqs_sent": [{"supplier_name": "SupA", "status": "sent"}],
            "offers_received": [],
            "pending_suppliers": ["SupA"],
            "timestamp": "2026-03-20T10:30:00Z",
        }
        mock_get.return_value = mock_agent

        from agents.orchestrator.tools import send_rfqs_and_collect_offers
        result = send_rfqs_and_collect_offers(
            procurement_spec_json=json.dumps(asdict(FakeSpec())),
            supplier_list_json=json.dumps(asdict(FakeSupplierList())),
        )

        data = json.loads(result)
        assert len(data["rfqs_sent"]) == 1


class TestEvaluateOffersTool:

    @patch("agents.orchestrator.tools._get_evaluation_agent")
    def test_returns_evaluation_result(self, mock_get):
        mock_agent = MagicMock()
        mock_agent.evaluate.return_value = {
            "request_product": "office chairs",
            "scores": [],
            "best_offer": "SupA",
            "report_path": "/tmp/report.pdf",
            "timestamp": "2026-03-20T11:00:00Z",
        }
        mock_get.return_value = mock_agent

        from agents.orchestrator.tools import evaluate_offers
        offers = [{"supplier_name": "SupA", "total_price": 4000}]
        result = evaluate_offers(
            procurement_spec_json=json.dumps(asdict(FakeSpec())),
            offers_json=json.dumps(offers),
        )

        data = json.loads(result)
        assert data["best_offer"] == "SupA"


class TestStorePipelineDataTool:

    @patch("agents.orchestrator.tools._get_storage_agent")
    def test_returns_storage_result(self, mock_get):
        mock_agent = MagicMock()
        mock_agent.store_full_pipeline.return_value = {
            "request_id": "req-123",
            "suppliers_stored": 2,
            "rfqs_stored": 2,
            "offers_stored": 1,
            "status": "offers_received",
        }
        mock_get.return_value = mock_agent

        from agents.orchestrator.tools import store_pipeline_data
        comm_result = {
            "rfqs_sent": [{"supplier_name": "SupA", "status": "sent"}],
            "offers_received": [{"supplier_name": "SupA", "total_price": 4000}],
        }
        result = store_pipeline_data(
            procurement_spec_json=json.dumps(asdict(FakeSpec())),
            supplier_list_json=json.dumps(asdict(FakeSupplierList())),
            communication_result_json=json.dumps(comm_result),
        )

        data = json.loads(result)
        assert data["request_id"] == "req-123"


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2: Orchestrator-level tests (mock the Strands Agent LLM call)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrchestratorRun:

    def _make_orchestrator_with_mock_llm(self, llm_response: str):
        """Create an Orchestrator with a mocked Strands Agent."""
        mock_model = MagicMock()
        orch = Orchestrator(model=mock_model, tools=[])
        # Mock the internal agent's __call__
        orch._agent = MagicMock(return_value=llm_response)
        return orch

    def test_completed_pipeline_parsing(self):
        llm_output = json.dumps({
            "request_id": "req-abc",
            "product": "office chairs",
            "status": "completed",
            "suppliers_found": 3,
            "rfqs_sent": 3,
            "offers_received": 2,
            "best_offer": "SupA",
            "report_path": "/tmp/report.pdf",
            "error": None,
        })
        orch = self._make_orchestrator_with_mock_llm(llm_output)
        result = orch.run("I need chairs", "user@co.com")

        assert result.status == STAGE_COMPLETED
        assert result.product == "office chairs"
        assert result.best_offer == "SupA"
        assert result.report_path == "/tmp/report.pdf"
        assert result.suppliers_found == 3
        assert result.offers_received == 2

    def test_rejected_pipeline_parsing(self):
        llm_output = json.dumps({
            "request_id": None,
            "product": "",
            "status": "rejected",
            "suppliers_found": 0,
            "rfqs_sent": 0,
            "offers_received": 0,
            "best_offer": None,
            "report_path": None,
            "error": "Missing product in email",
        })
        orch = self._make_orchestrator_with_mock_llm(llm_output)
        result = orch.run("", "user@co.com")

        assert result.status == STAGE_REJECTED
        assert result.error == "Missing product in email"

    def test_awaiting_responses_parsing(self):
        llm_output = json.dumps({
            "request_id": "req-xyz",
            "product": "chairs",
            "status": "awaiting_responses",
            "suppliers_found": 2,
            "rfqs_sent": 2,
            "offers_received": 0,
            "best_offer": None,
            "report_path": None,
            "error": None,
        })
        orch = self._make_orchestrator_with_mock_llm(llm_output)
        result = orch.run("I need chairs", "user@co.com")

        assert result.status == "awaiting_responses"
        assert result.offers_received == 0

    def test_markdown_wrapped_json_parsing(self):
        llm_output = '```json\n{"request_id": "req-1", "product": "desks", "status": "completed", "suppliers_found": 1, "rfqs_sent": 1, "offers_received": 1, "best_offer": "SupX", "report_path": null, "error": null}\n```'
        orch = self._make_orchestrator_with_mock_llm(llm_output)
        result = orch.run("I need desks", "user@co.com")

        assert result.status == STAGE_COMPLETED
        assert result.best_offer == "SupX"

    def test_llm_exception_returns_failed(self):
        mock_model = MagicMock()
        orch = Orchestrator(model=mock_model, tools=[])
        orch._agent = MagicMock(side_effect=RuntimeError("Bedrock timeout"))

        result = orch.run("test", "user@co.com")

        assert result.status == STAGE_FAILED
        assert "Bedrock timeout" in result.error

    def test_unparseable_output_returns_failed(self):
        orch = self._make_orchestrator_with_mock_llm("I could not process this request.")
        result = orch.run("test", "user@co.com")

        assert result.status == STAGE_FAILED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
