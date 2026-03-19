"""
agents/agent_communication/agent.py
Communication Agent — manages the full supplier communication lifecycle:
  Phase 1: Generate and send RFQ emails to all contactable suppliers
  Phase 2: Monitor inbox for supplier replies, parse offers
  Phase 3: Send reminders to non-respondents after 72h

Input  : ProcurementSpec dict + SupplierList dict (outputs of Agent 1 & 2)
Output : CommunicationResult dataclass
"""
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from strands import Agent
from strands.models import BedrockModel

# Ensure project root is importable when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from logger import get_logger
from agents.agent_communication.tools import (
    send_email_to_supplier,
    retry_find_supplier_email,
    fetch_supplier_replies,
    is_reminder_due,
)

logger = get_logger(__name__)

# ── System prompts ────────────────────────────────────────────────────────────

SYSTEM_PROMPT_RFQ = """
You are a procurement communication specialist. Your job is to send professional
Request for Quotation (RFQ) emails to a list of suppliers.

For each supplier in the list:
1. If the supplier has NO email (email is null):
   - Call retry_find_supplier_email(supplier_name, website) to attempt recovery.
   - If still null, skip this supplier.
2. Write a professional RFQ email body in English.
   The email must include:
   - A polite greeting
   - The product/service requested with specifications
   - Quantity and unit
   - Budget range if available (do NOT reveal the exact max budget — say "within a reasonable range")
   - Desired delivery deadline
   - A request for: unit price, total price, delivery time, warranty, payment terms
   - Mention that this is a competitive procurement process
   - A professional closing with the requester's organization name (inferred from requester_email domain)
3. Call send_email_to_supplier(to_email, supplier_name, subject, body) to send each RFQ.
   Use subject format: "RFQ — {product_name}" for all emails.

After processing ALL suppliers, return a JSON object:
{
  "rfqs": [
    {
      "supplier_name": "string",
      "supplier_email": "string",
      "status": "sent" | "skipped_no_email" | "failed",
      "message_id": "string or null",
      "error": "string or null"
    }
  ],
  "total_sent": number,
  "total_skipped": number,
  "total_failed": number
}

Rules:
- Write ALL RFQ email bodies in English.
- Be professional and formal.
- Do NOT reveal the exact maximum budget.
- Include a deadline for response (7 days from now).
- Return ONLY the JSON object, no extra text.
"""

SYSTEM_PROMPT_PARSE = """
You are a procurement offer analyst. Your job is to parse supplier response emails
and extract structured offer information.

For each supplier reply provided:
1. Call fetch_supplier_replies(rfq_subject_prefix) to get new replies.
2. For each reply, extract:
   - unit_price: price per unit (float or null)
   - total_price: total quoted price (float or null)
   - currency: currency code (default "TND")
   - delivery_days: estimated delivery time in days (int or null)
   - warranty: warranty terms (string or null)
   - payment_terms: payment conditions (string or null)
   - notes: any additional remarks (string or null)

Return a JSON object:
{
  "offers": [
    {
      "supplier_name": "string",
      "supplier_email": "string",
      "unit_price": float or null,
      "total_price": float or null,
      "currency": "TND",
      "delivery_days": int or null,
      "warranty": "string or null",
      "payment_terms": "string or null",
      "notes": "string or null",
      "raw_body": "string — first 500 chars of original email"
    }
  ],
  "total_parsed": number
}

Rules:
- Extract prices in TND unless explicitly stated otherwise.
- If a reply is not a real offer (e.g. auto-reply, out-of-office), skip it.
- Return ONLY the JSON object, no extra text.
"""

SYSTEM_PROMPT_REMINDER = """
You are a procurement follow-up specialist. Your job is to send polite reminder
emails to suppliers who have not responded to an RFQ within the deadline.

For each supplier that needs a reminder:
1. Write a polite follow-up email in English reminding them of the original RFQ.
2. Call send_email_to_supplier(to_email, supplier_name, subject, body) to send.
   Use subject format: "Reminder — RFQ — {product_name}"

The reminder should:
- Reference the original RFQ
- Politely ask for a response
- Mention that the deadline is approaching
- Stay professional and courteous

Return a JSON object:
{
  "reminders": [
    {
      "supplier_name": "string",
      "supplier_email": "string",
      "status": "sent" | "failed",
      "error": "string or null"
    }
  ],
  "total_sent": number
}

Rules:
- Write in English.
- Return ONLY the JSON object, no extra text.
"""

# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class RFQRecord:
    """Tracks a single RFQ sent to a supplier."""
    supplier_name: str
    supplier_email: str
    subject: str
    message_id: Optional[str]
    sent_at: str
    status: str  # "sent", "skipped_no_email", "failed"
    error: Optional[str] = None


@dataclass
class SupplierOffer:
    """Parsed offer from a supplier's response email."""
    supplier_name: str
    supplier_email: str
    unit_price: Optional[float]
    total_price: Optional[float]
    currency: str
    delivery_days: Optional[int]
    warranty: Optional[str]
    payment_terms: Optional[str]
    notes: Optional[str]
    raw_body: str
    received_at: str


@dataclass
class CommunicationResult:
    """Full output of the Communication Agent."""
    rfqs_sent: list       # list[RFQRecord]
    offers_received: list  # list[SupplierOffer]
    reminders_sent: list   # list[RFQRecord]
    pending_suppliers: list  # supplier names still awaiting response
    timestamp: str


# ── Helper ────────────────────────────────────────────────────────────────────

def _extract_first_json_object(raw: str) -> Optional[str]:
    """Return the first balanced JSON object found in text, or None."""
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(raw[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start: i + 1]
    return None


def _parse_llm_json(raw: str) -> dict:
    """Parse JSON from LLM response, handling markdown wrappers."""
    text = str(raw).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try markdown code block
    if text.startswith("```") and "```" in text[3:]:
        parts = text.split("```")
        if len(parts) > 1:
            cleaned = parts[1].strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    # Try extracting first JSON object
    candidate = _extract_first_json_object(text)
    if candidate:
        return json.loads(candidate)

    return {}


# ── Agent class ───────────────────────────────────────────────────────────────

class CommunicationAgent:
    """Manages the full supplier communication lifecycle."""

    def __init__(self):
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
        )
        # Separate agent instances for each phase (different system prompts)
        self._rfq_agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT_RFQ,
            tools=[send_email_to_supplier, retry_find_supplier_email],
        )
        self._parse_agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT_PARSE,
            tools=[fetch_supplier_replies],
        )
        self._reminder_agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT_REMINDER,
            tools=[send_email_to_supplier],
        )

    # ── Phase 1: Send RFQs ────────────────────────────────────────────────────

    def send_rfqs(self, procurement_spec: dict, supplier_list: dict) -> list:
        """
        Generate and send RFQ emails to all contactable suppliers.

        Args:
            procurement_spec: dict from Agent 1 (product, category, quantity, etc.)
            supplier_list: dict from Agent 2 (suppliers array)

        Returns:
            list[RFQRecord] — tracking records for each supplier
        """
        product = procurement_spec.get("product", "")
        category = procurement_spec.get("category", "")
        quantity = procurement_spec.get("quantity", "")
        unit = procurement_spec.get("unit", "")
        budget_max = procurement_spec.get("budget_max")
        deadline = procurement_spec.get("deadline")
        requester_email = procurement_spec.get("requester_email", "")

        suppliers = supplier_list.get("suppliers", [])

        logger.info(
            "Communication Agent — Phase 1: Sending RFQs",
            extra={"product": product, "supplier_count": len(suppliers)},
        )

        # Build a summary of suppliers for the LLM
        supplier_summary = json.dumps(suppliers, ensure_ascii=False, indent=2)

        prompt = f"""
Send RFQ emails to the following suppliers for this procurement request:

Product          : {product}
Category         : {category}
Quantity         : {quantity} {unit or ''}
Budget max       : {f"{budget_max} TND" if budget_max else "Not specified"}
Deadline         : {deadline or "Not specified"}
Requester email  : {requester_email}

Suppliers to contact:
{supplier_summary}

Process each supplier: recover missing emails if needed, write the RFQ, and send it.
"""

        try:
            response = self._rfq_agent(prompt)
            data = _parse_llm_json(str(response))
        except Exception as exc:
            logger.error("RFQ phase failed", extra={"error": str(exc)})
            data = {}

        now = datetime.now(timezone.utc).isoformat()
        rfq_subject = f"RFQ — {product}"

        records = []
        for rfq in data.get("rfqs", []):
            records.append(RFQRecord(
                supplier_name=rfq.get("supplier_name", ""),
                supplier_email=rfq.get("supplier_email", ""),
                subject=rfq_subject,
                message_id=rfq.get("message_id"),
                sent_at=now,
                status=rfq.get("status", "failed"),
                error=rfq.get("error"),
            ))

        # If the LLM didn't return structured data, build records from suppliers
        if not records:
            for s in suppliers:
                records.append(RFQRecord(
                    supplier_name=s.get("name", ""),
                    supplier_email=s.get("email", ""),
                    subject=rfq_subject,
                    message_id=None,
                    sent_at=now,
                    status="skipped_no_email" if not s.get("email") else "failed",
                    error="LLM did not return structured results",
                ))

        sent_count = sum(1 for r in records if r.status == "sent")
        logger.info(
            "RFQ phase complete",
            extra={"sent": sent_count, "total": len(records)},
        )

        return records

    # ── Phase 2: Check responses ──────────────────────────────────────────────

    def check_responses(self, rfq_records: list, product: str) -> list:
        """
        Check Gmail inbox for supplier replies and parse offers.

        Args:
            rfq_records: list[RFQRecord] or list[dict] from Phase 1
            product: product name for subject matching

        Returns:
            list[SupplierOffer] — parsed offers from supplier replies
        """
        rfq_subject = f"RFQ — {product}"
        sent_emails = []
        for r in rfq_records:
            rec = r if isinstance(r, dict) else asdict(r)
            if rec.get("status") == "sent":
                sent_emails.append(rec.get("supplier_email", ""))

        if not sent_emails:
            logger.info("No RFQs were sent — nothing to check")
            return []

        logger.info(
            "Communication Agent — Phase 2: Checking responses",
            extra={"product": product, "sent_count": len(sent_emails)},
        )

        prompt = f"""
Check the inbox for replies to our RFQ emails.
The RFQ subject prefix is: "{rfq_subject}"

We sent RFQs to these suppliers: {json.dumps(sent_emails)}

Fetch replies and parse any supplier offers found.
"""

        try:
            response = self._parse_agent(prompt)
            data = _parse_llm_json(str(response))
        except Exception as exc:
            logger.error("Response check failed", extra={"error": str(exc)})
            data = {}

        now = datetime.now(timezone.utc).isoformat()
        offers = []
        for o in data.get("offers", []):
            offers.append(SupplierOffer(
                supplier_name=o.get("supplier_name", ""),
                supplier_email=o.get("supplier_email", ""),
                unit_price=o.get("unit_price"),
                total_price=o.get("total_price"),
                currency=o.get("currency", "TND"),
                delivery_days=o.get("delivery_days"),
                warranty=o.get("warranty"),
                payment_terms=o.get("payment_terms"),
                notes=o.get("notes"),
                raw_body=o.get("raw_body", "")[:500],
                received_at=o.get("received_at", now),
            ))

        logger.info("Offers parsed", extra={"count": len(offers)})
        return offers

    # ── Phase 3: Send reminders ───────────────────────────────────────────────

    def send_reminders(
        self,
        rfq_records: list,
        responded_emails: list,
        product: str,
        hours_threshold: int = 72,
    ) -> list:
        """
        Send reminder emails to suppliers who haven't responded after the threshold.

        Args:
            rfq_records: list[RFQRecord] or list[dict] from Phase 1
            responded_emails: list of email addresses that have already responded
            product: product name
            hours_threshold: hours to wait before sending reminder (default 72)

        Returns:
            list[RFQRecord] — tracking records for sent reminders
        """
        responded_set = {e.lower() for e in responded_emails}

        # Find suppliers who were sent an RFQ but haven't responded and are past threshold
        due_for_reminder = []
        for r in rfq_records:
            rec = r if isinstance(r, dict) else asdict(r)
            if rec.get("status") != "sent":
                continue
            if rec.get("supplier_email", "").lower() in responded_set:
                continue
            if not is_reminder_due(rec.get("sent_at", ""), hours_threshold):
                continue
            due_for_reminder.append(rec)

        if not due_for_reminder:
            logger.info("No reminders due")
            return []

        logger.info(
            "Communication Agent — Phase 3: Sending reminders",
            extra={"count": len(due_for_reminder), "product": product},
        )

        supplier_summary = json.dumps(due_for_reminder, ensure_ascii=False, indent=2)

        prompt = f"""
Send reminder emails to the following suppliers who have not responded
to our RFQ for "{product}" after {hours_threshold} hours:

{supplier_summary}

Write a polite follow-up in French and send each reminder.
"""

        try:
            response = self._reminder_agent(prompt)
            data = _parse_llm_json(str(response))
        except Exception as exc:
            logger.error("Reminder phase failed", extra={"error": str(exc)})
            data = {}

        now = datetime.now(timezone.utc).isoformat()
        records = []
        for rem in data.get("reminders", []):
            records.append(RFQRecord(
                supplier_name=rem.get("supplier_name", ""),
                supplier_email=rem.get("supplier_email", ""),
                subject=f"Reminder — RFQ — {product}",
                message_id=None,
                sent_at=now,
                status=rem.get("status", "failed"),
                error=rem.get("error"),
            ))

        logger.info("Reminders sent", extra={"count": sum(1 for r in records if r.status == "sent")})
        return records

    # ── Full cycle (convenience method) ───────────────────────────────────────

    def run_full_cycle(self, procurement_spec: dict, supplier_list: dict) -> CommunicationResult:
        """
        Run the complete communication cycle: send RFQs → check responses.
        Reminders are handled separately (called by orchestrator after 72h).

        Returns:
            CommunicationResult with all tracking data.
        """
        product = procurement_spec.get("product", "")

        # Phase 1: Send RFQs
        rfq_records = self.send_rfqs(procurement_spec, supplier_list)

        # Phase 2: Check for immediate responses (unlikely but possible)
        offers = self.check_responses(rfq_records, product)

        # Determine pending suppliers
        responded_emails = {o.supplier_email.lower() for o in offers}
        pending = [
            r.supplier_name for r in rfq_records
            if r.status == "sent" and r.supplier_email.lower() not in responded_emails
        ]

        return CommunicationResult(
            rfqs_sent=rfq_records,
            offers_received=offers,
            reminders_sent=[],  # Reminders come later (72h)
            pending_suppliers=pending,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ═══════════════════════════════════════════════════════════════════
# STANDALONE MODE  —  python agents/agent_communication/agent.py
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    from importlib import reload

    _here = os.path.abspath(__file__)
    _root = os.path.dirname(os.path.dirname(os.path.dirname(_here)))
    _env_path = os.path.join(_root, ".env")

    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)
        import config as _cfg
        reload(_cfg)
        from config import settings
    else:
        print(f"  .env not found at {_env_path}")
        sys.exit(1)

    # Sample inputs (from Agent 1 + Agent 2)
    sample_spec = {
        "product": "ergonomic office chairs",
        "category": "Office Supplies",
        "quantity": 10,
        "unit": "units",
        "budget_min": None,
        "budget_max": 5000,
        "deadline": "2026-04-30",
        "requester_email": "eyaaformation@gmail.com",
        "is_valid": True,
    }

    sample_suppliers = {
        "suppliers": [
            {
                "name": "ExampleSupplier",
                "website": "https://example.com",
                "email": "supplier@example.com",
                "category": "Office Supplies",
                "relevance_score": 0.95,
            },
        ],
        "query_used": "ergonomic office chairs",
        "search_timestamp": "2026-03-19T10:00:00Z",
    }

    print("\n  Communication Agent — standalone test")
    print(f"    Product    : {sample_spec['product']}")
    print(f"    Suppliers  : {len(sample_suppliers['suppliers'])}\n")

    agent = CommunicationAgent()

    print("--- Phase 1: Sending RFQs ---")
    rfq_records = agent.send_rfqs(sample_spec, sample_suppliers)
    for r in rfq_records:
        print(f"  [{r.status}] {r.supplier_name} ({r.supplier_email})")
        if r.error:
            print(f"           Error: {r.error}")

    print(f"\n--- Phase 2: Checking responses ---")
    offers = agent.check_responses(rfq_records, sample_spec["product"])
    if offers:
        for o in offers:
            print(f"  Offer from {o.supplier_name}: {o.total_price} {o.currency}")
    else:
        print("  No responses yet.")

    print(f"\n  Full JSON output:")
    result = CommunicationResult(
        rfqs_sent=rfq_records,
        offers_received=offers,
        reminders_sent=[],
        pending_suppliers=[r.supplier_name for r in rfq_records if r.status == "sent"],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False, default=str))
