"""
agents/orchestrator/agent.py
Orchestrator — a Strands Agent that coordinates the procurement pipeline
using the "Agents as Tools" pattern.

The orchestrator LLM decides which agent-tool to call and when,
passing data between them. Each sub-agent is wrapped as a @tool
in tools.py.

Pipeline flow (decided by the LLM):
  1. analyze_request        → validates the email, extracts ProcurementSpec
  2. source_suppliers       → finds Tunisian suppliers
  3. send_rfqs_and_collect_offers → sends RFQs, checks for replies
  4. store_pipeline_data    → persists everything to the database
  5. evaluate_offers        → scores, ranks, generates PDF report
"""
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from strands import Agent
from strands.models import BedrockModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from logger import get_logger
from agents.orchestrator.tools import (
    analyze_request,
    source_suppliers,
    send_rfqs_and_collect_offers,
    store_pipeline_data,
    evaluate_offers,
)

logger = get_logger(__name__)

# ── Pipeline stage constants ─────────────────────────────────────────────────

STAGE_RECEIVED = "received"
STAGE_ANALYZING = "analyzing"
STAGE_REJECTED = "rejected"
STAGE_SOURCING = "sourcing"
STAGE_COMMUNICATING = "communicating"
STAGE_EVALUATING = "evaluating"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"


# ── Dataclass ────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Summary of a full pipeline run."""
    request_id: Optional[str]
    product: str
    status: str
    suppliers_found: int
    rfqs_sent: int
    offers_received: int
    best_offer: Optional[str]
    report_path: Optional[str]
    error: Optional[str]
    timestamp: str


# ── System prompt ────────────────────────────────────────────────────────────

ORCHESTRATOR_SYSTEM_PROMPT = """
You are the Procurement Pipeline Orchestrator. You coordinate a team of
specialized AI agents to handle end-to-end procurement requests.

You have 5 agent-tools available. Execute them in this order:

1. **analyze_request** — Call FIRST with the email body and sender email.
   - If the result has is_valid=false, STOP and report the rejection reason.

2. **source_suppliers** — Call with the procurement spec JSON from step 1.
   - If the suppliers array is empty, STOP and report that no suppliers were found.

3. **send_rfqs_and_collect_offers** — Call with the spec and supplier list JSONs.
   - This sends RFQ emails and checks for immediate supplier responses.

4. **store_pipeline_data** — Call with spec, suppliers, and communication result JSONs.
   - This persists all data to the database.

5. **evaluate_offers** — Call ONLY if there are offers in the communication result.
   - Pass the spec and the offers array JSON.
   - If no offers were received, skip this step and report "awaiting_responses".

After all steps, return a final JSON summary:
{
  "request_id": "string or null (from store_pipeline_data result)",
  "product": "string",
  "status": "completed" | "rejected" | "failed" | "awaiting_responses",
  "suppliers_found": number,
  "rfqs_sent": number,
  "offers_received": number,
  "best_offer": "string or null (from evaluate_offers result)",
  "report_path": "string or null (from evaluate_offers result)",
  "error": "string or null"
}

Rules:
- Always follow the order: analyze → source → communicate → store → evaluate.
- Pass the EXACT JSON strings between tools — do not modify or summarize them.
- If any tool fails or throws an error, stop and report status="failed" with the error.
- Return ONLY the final JSON summary, no extra text.
"""


# ── Orchestrator class ───────────────────────────────────────────────────────

class Orchestrator:
    """
    Strands Agent orchestrator using the "Agents as Tools" pattern.
    The LLM decides which agent-tool to call and manages data flow.
    """

    def __init__(self, model=None, tools=None):
        if model is None:
            model = BedrockModel(
                model_id=settings.bedrock_model_id,
                region_name=settings.aws_region,
            )
        self._agent = Agent(
            model=model,
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            tools=tools or [
                analyze_request,
                source_suppliers,
                send_rfqs_and_collect_offers,
                store_pipeline_data,
                evaluate_offers,
            ],
        )

    def run(self, email_body: str, requester_email: str) -> PipelineResult:
        """
        Execute the full procurement pipeline.

        The orchestrator LLM will call each agent-tool in sequence,
        passing data between them and making decisions at each step.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        logger.info("Orchestrator pipeline started", extra={
            "requester": requester_email,
        })

        prompt = f"""
Process this procurement request:

Requester email: {requester_email}

Email body:
---
{email_body}
---

Execute the full procurement pipeline using the available tools.
"""

        try:
            response = self._agent(prompt)
            raw = str(response).strip()

            # Parse the final JSON summary from the LLM
            result_data = self._parse_result(raw)

            return PipelineResult(
                request_id=result_data.get("request_id"),
                product=result_data.get("product", ""),
                status=result_data.get("status", STAGE_FAILED),
                suppliers_found=result_data.get("suppliers_found", 0),
                rfqs_sent=result_data.get("rfqs_sent", 0),
                offers_received=result_data.get("offers_received", 0),
                best_offer=result_data.get("best_offer"),
                report_path=result_data.get("report_path"),
                error=result_data.get("error"),
                timestamp=timestamp,
            )

        except Exception as exc:
            logger.error("Orchestrator pipeline failed", extra={"error": str(exc)})
            return PipelineResult(
                request_id=None,
                product="",
                status=STAGE_FAILED,
                suppliers_found=0,
                rfqs_sent=0,
                offers_received=0,
                best_offer=None,
                report_path=None,
                error=str(exc),
                timestamp=timestamp,
            )

    def _parse_result(self, raw: str) -> dict:
        """Extract the final JSON summary from LLM output."""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try markdown code block
        if "```" in raw:
            parts = raw.split("```")
            for part in parts[1::2]:
                cleaned = part.strip()
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    continue

        # Try extracting first JSON object
        start = raw.find("{")
        if start != -1:
            depth = 0
            for i, ch in enumerate(raw[start:], start=start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(raw[start:i + 1])
                        except json.JSONDecodeError:
                            break

        logger.warning("Could not parse orchestrator result", extra={"raw": raw[:300]})
        return {}
