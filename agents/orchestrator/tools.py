"""
agents/orchestrator/tools.py
Each sub-agent is wrapped as a @tool callable by the orchestrator LLM.

The orchestrator Agent decides which tool to call and when,
following the "Agents as Tools" pattern from Strands Agents SDK.
"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

from strands import tool

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from logger import get_logger

logger = get_logger(__name__)


# ── Agent singletons (lazy-loaded to avoid import cost at tool-discovery) ────

_analysis_agent = None
_sourcing_agent = None
_communication_agent = None
_storage_agent = None
_evaluation_agent = None


def _get_analysis_agent():
    global _analysis_agent
    if _analysis_agent is None:
        from agents.analysis.agent import AnalysisAgent
        _analysis_agent = AnalysisAgent()
    return _analysis_agent


def _get_sourcing_agent():
    global _sourcing_agent
    if _sourcing_agent is None:
        from agents.agent_sourcing.agent import SourcingAgent
        _sourcing_agent = SourcingAgent()
    return _sourcing_agent


def _get_communication_agent():
    global _communication_agent
    if _communication_agent is None:
        from agents.agent_communication.agent import CommunicationAgent
        _communication_agent = CommunicationAgent()
    return _communication_agent


def _get_storage_agent():
    global _storage_agent
    if _storage_agent is None:
        from agents.agent_storage.agent import StorageAgent
        _storage_agent = StorageAgent()
    return _storage_agent


def _get_evaluation_agent():
    global _evaluation_agent
    if _evaluation_agent is None:
        from agents.agent_evaluation.agent import EvaluationAgent
        _evaluation_agent = EvaluationAgent()
    return _evaluation_agent


def _to_json(obj) -> str:
    """Convert a dataclass or dict to JSON string."""
    if hasattr(obj, "__dict__") and not isinstance(obj, dict):
        return json.dumps(asdict(obj), ensure_ascii=False, default=str)
    return json.dumps(obj, ensure_ascii=False, default=str)


# ── Tool: Analyze Request ────────────────────────────────────────────────────

@tool
def analyze_request(email_body: str, requester_email: str) -> str:
    """
    Analyze a procurement request email and extract structured information.
    Call this FIRST with the raw email body and sender email.
    Returns a JSON ProcurementSpec with product, category, quantity, budget, deadline, is_valid, etc.
    If is_valid is false, the request is rejected and the pipeline should stop.
    """
    logger.info("Tool: analyze_request called", extra={"requester": requester_email})
    agent = _get_analysis_agent()
    result = agent.analyze(email_body, requester_email)
    return _to_json(result)


# ── Tool: Source Suppliers ───────────────────────────────────────────────────

@tool
def source_suppliers(procurement_spec_json: str) -> str:
    """
    Find qualified Tunisian suppliers for a validated procurement request.
    Call this AFTER analyze_request returns a valid spec (is_valid=true).
    Input: the JSON string returned by analyze_request.
    Returns a JSON SupplierList with an array of supplier candidates.
    """
    logger.info("Tool: source_suppliers called")
    spec = json.loads(procurement_spec_json)
    agent = _get_sourcing_agent()
    result = agent.source(spec)
    return _to_json(result)


# ── Tool: Send RFQs and Collect Offers ───────────────────────────────────────

@tool
def send_rfqs_and_collect_offers(procurement_spec_json: str, supplier_list_json: str) -> str:
    """
    Send RFQ emails to suppliers and check for immediate responses.
    Call this AFTER source_suppliers returns a non-empty supplier list.
    Input: procurement_spec JSON and supplier_list JSON from previous tools.
    Returns a JSON CommunicationResult with rfqs_sent, offers_received, and pending_suppliers.
    """
    logger.info("Tool: send_rfqs_and_collect_offers called")
    spec = json.loads(procurement_spec_json)
    suppliers = json.loads(supplier_list_json)
    agent = _get_communication_agent()
    result = agent.run_full_cycle(spec, suppliers)
    return _to_json(result)


# ── Tool: Store Pipeline Data ────────────────────────────────────────────────

@tool
def store_pipeline_data(
    procurement_spec_json: str,
    supplier_list_json: str,
    communication_result_json: str,
) -> str:
    """
    Persist all pipeline data to the database.
    Call this AFTER send_rfqs_and_collect_offers completes.
    Input: all three JSON strings from previous tools.
    Returns a JSON StorageResult with request_id and counts of stored records.
    """
    logger.info("Tool: store_pipeline_data called")
    spec = json.loads(procurement_spec_json)
    suppliers = json.loads(supplier_list_json)
    comm = json.loads(communication_result_json)

    agent = _get_storage_agent()
    result = agent.store_full_pipeline(
        procurement_spec=spec,
        supplier_list=suppliers,
        rfq_records=comm.get("rfqs_sent", []),
        offers=comm.get("offers_received", []),
    )
    return _to_json(result)


# ── Tool: Evaluate Offers ────────────────────────────────────────────────────

@tool
def evaluate_offers(procurement_spec_json: str, offers_json: str) -> str:
    """
    Score, rank, and generate a PDF comparison report for supplier offers.
    Call this AFTER store_pipeline_data, only if there are offers to evaluate.
    Input: procurement_spec JSON and the offers array JSON (from communication result).
    Returns a JSON EvaluationResult with ranked scores, best_offer, and report_path.
    """
    logger.info("Tool: evaluate_offers called")
    spec = json.loads(procurement_spec_json)
    offers = json.loads(offers_json)

    agent = _get_evaluation_agent()
    result = agent.evaluate(offers, spec)
    return _to_json(result)
