"""
agents/analysis/agent.py
Analysis Agent — extracts a structured ProcurementSpec from
a requester's free-text email using Claude Sonnet 4 via Strands.
"""
import json
from dataclasses import dataclass, asdict
from typing import Optional

from strands import Agent
from strands.models import BedrockModel

from config import settings
from logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """
You are a procurement analysis specialist. Your job is to extract structured
procurement information from a requester's email written in French or English.

You MUST return a valid JSON object with these exact fields:
{
  "product": "string — product or service name",
  "category": "string — broad category (e.g. 'Fournitures de bureau', 'Matériel informatique')",
  "quantity": number or null,
  "unit": "string — e.g. 'unités', 'kg', 'boîtes' or null",
  "budget_min": number or null,
  "budget_max": number or null,
  "deadline": "ISO date string YYYY-MM-DD or null",
  "requester_email": "string — email of the sender",
  "is_valid": true or false,
  "rejection_reason": "string if is_valid is false, else null"
}

Rules:
- is_valid = false if product is missing or the email is unclear
- All monetary values in TND (Tunisian Dinar)
- If budget not mentioned, set both to null
- Return ONLY the JSON object, no extra text
"""


@dataclass
class ProcurementSpec:
    product: str
    category: str
    quantity: Optional[float]
    unit: Optional[str]
    budget_min: Optional[float]
    budget_max: Optional[float]
    deadline: Optional[str]
    requester_email: str
    is_valid: bool
    rejection_reason: Optional[str] = None


class AnalysisAgent:
    """Extracts a ProcurementSpec from a raw requester email."""

    def __init__(self):
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
        )
        self._agent = Agent(model=model, system_prompt=SYSTEM_PROMPT)

    def analyze(self, email_body: str, requester_email: str) -> ProcurementSpec:
        logger.info("Analysis Agent invoked", extra={"requester": requester_email})

        prompt = f"""
Requester email: {requester_email}

Email body:
---
{email_body}
---

Extract the procurement information and return JSON.
"""
        try:
            response = self._agent(prompt)
            # Extract text from Strands response
            raw = str(response).strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw.strip())
        except json.JSONDecodeError as exc:
            logger.error("JSON parse failed", extra={"error": str(exc)})
            return ProcurementSpec(
                product="", category="", quantity=None, unit=None,
                budget_min=None, budget_max=None, deadline=None,
                requester_email=requester_email,
                is_valid=False,
                rejection_reason="LLM returned invalid JSON",
            )

        return ProcurementSpec(
            product=data.get("product", ""),
            category=data.get("category", ""),
            quantity=data.get("quantity"),
            unit=data.get("unit"),
            budget_min=data.get("budget_min"),
            budget_max=data.get("budget_max"),
            deadline=data.get("deadline"),
            requester_email=data.get("requester_email", requester_email),
            is_valid=data.get("is_valid", False),
            rejection_reason=data.get("rejection_reason"),
        )
