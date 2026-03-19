"""
agents/analysis/agent.py
Analysis Agent — extracts a structured ProcurementSpec from
a requester's free-text email using Claude Sonnet 4 via Strands.
"""
import json
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from strands import Agent
from strands.models import BedrockModel

# Ensure project root is importable when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from logger import get_logger
from agents.analysis.tools import (
    suggest_procurement_category,
    validate_budget_range,
    validate_deadline,
    normalize_category,
    normalize_unit,
    send_request_acknowledgment,
)

logger = get_logger(__name__)

SYSTEM_PROMPT = """
You are a procurement analysis specialist. Your job is to extract structured
procurement information from a requester's email written in French or English.

You MUST return a valid JSON object with these exact fields:
{
  "product": "string — product or service name",
    "category": "string — broad category (e.g. 'Office Supplies', 'IT Equipment')",
  "quantity": number or null,
    "unit": "string — e.g. 'units', 'kg', 'boxes' or null",
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
- Output language policy: all JSON string values must be in English.
- If source email is French, translate extracted values to English where applicable.
- rejection_reason must be in English.
- You have tools available. Before finalizing JSON:
    1) Call suggest_procurement_category(product_or_text) using the extracted product or email text.
    2) Call validate_budget_range(budget_min, budget_max).
    3) Call validate_deadline(deadline) using the extracted deadline (or null if not mentioned).
- Do NOT send any emails or acknowledgments — that is handled externally.
- If suggest_procurement_category returns a specific category and category is missing/weak, use the tool result.
- If validate_budget_range returns budget_invalid_min_gt_max, set is_valid=false and provide rejection_reason.
- If validate_budget_range returns budget_missing, keep budget fields as null (this alone is not a rejection).
- If validate_deadline returns deadline_in_past, set is_valid=false and rejection_reason="Deadline is in the past".
- If validate_deadline returns deadline_invalid_format, set deadline=null, is_valid=false and rejection_reason="Invalid deadline format".
- If validate_deadline returns deadline_missing, keep deadline as null (this alone is not a rejection).
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
                return raw[start : i + 1]

    return None


class AnalysisAgent:
    """Extracts a ProcurementSpec from a raw requester email."""

    def __init__(self):
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
        )
        self._agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=[
                suggest_procurement_category,
                validate_budget_range,
                validate_deadline,
            ],
        )

    def analyze(self, email_body: str, requester_email: str) -> ProcurementSpec:
        logger.info("Analysis Agent invoked", extra={"requester": requester_email})

        from datetime import date
        today = date.today().isoformat()

        prompt = f"""
Today's date: {today}

Requester email: {requester_email}

Email body:
---
{email_body}
---

Extract the procurement information and return JSON.
When extracting the deadline:
- Convert any natural language date to ISO format YYYY-MM-DD (e.g. "31 mars 2026" → "2026-03-31", "end of this month" → last day of current month based on today's date above, "next week" → 7 days from today).
- If no deadline is mentioned, set deadline to null.
"""
        try:
            response = self._agent(prompt)
            raw = str(response).strip()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                cleaned = raw.strip()
                if cleaned.startswith("```") and "```" in cleaned[3:]:
                    parts = cleaned.split("```")
                    if len(parts) > 1:
                        cleaned = parts[1].strip()
                        if cleaned.lower().startswith("json"):
                            cleaned = cleaned[4:].strip()

                json_candidate = _extract_first_json_object(cleaned)
                if not json_candidate:
                    json_candidate = _extract_first_json_object(raw)
                if not json_candidate:
                    raise

                data = json.loads(json_candidate)
        except json.JSONDecodeError as exc:
            logger.error(
                "JSON parse failed",
                extra={"error": str(exc), "raw_preview": str(response)[:300]},
            )
            return ProcurementSpec(
                product="", category="", quantity=None, unit=None,
                budget_min=None, budget_max=None, deadline=None,
                requester_email=requester_email,
                is_valid=False,
                rejection_reason="LLM returned invalid JSON",
            )

        return ProcurementSpec(
            product=data.get("product", ""),
            category=normalize_category(data.get("category", "")),
            quantity=data.get("quantity"),
            unit=normalize_unit(data.get("unit")),
            budget_min=data.get("budget_min"),
            budget_max=data.get("budget_max"),
            deadline=data.get("deadline"),
            requester_email=data.get("requester_email", requester_email),
            is_valid=data.get("is_valid", False),
            rejection_reason=data.get("rejection_reason"),
        )


# ═══════════════════════════════════════════════════════════════════
# LIVE MODE  —  python agents/analysis/agent.py
# Watches Gmail inbox every 15 s. Ctrl+C to stop.
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import imaplib
    import sys
    import os
    import time
    from dataclasses import asdict
    from datetime import datetime
    from dotenv import load_dotenv

    _here = os.path.abspath(__file__)
    _root = os.path.dirname(os.path.dirname(os.path.dirname(_here)))
    _env_path = os.path.join(_root, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)
        from importlib import reload
        import config as _cfg
        reload(_cfg)
        from config import settings
    else:
        print(f"  .env not found at {_env_path}")
        print("    Create it from .env.example and fill in your credentials.")
        sys.exit(1)

    sys.path.insert(0, _root)
    from email_gateway.parser import EmailParser

    POLL_INTERVAL = 15
    OUTPUT_DIR = os.path.join(_root, "outputs")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    agent = AnalysisAgent()
    parser = EmailParser()

    _password = settings.gmail_app_password.replace(" ", "")

    def process_email(raw_bytes: bytes):
        parsed = parser.parse(raw_bytes)

        print(f"\n{'='*60}")
        print(f"  Nouvel email — {datetime.now().strftime('%H:%M:%S')}")
        print(f"    De      : {parsed.from_email}")
        print(f"    Objet   : {parsed.subject}")
        print(f"    Corps   : {parsed.body[:200].strip()!r}")
        print(f"{'='*60}")

        print("  Analyse en cours (Claude Sonnet 4)...")
        spec = agent.analyze(parsed.body, parsed.from_email)

        try:
            send_request_acknowledgment(
                requester_email=spec.requester_email or parsed.from_email,
                is_valid=spec.is_valid,
                product=spec.product,
            )
            print("[ACK] Automatic acknowledgment email sent.")
        except Exception as exc:
            print(f"[ACK] Failed to send acknowledgment email: {exc}")

        if spec.is_valid:
            print("\n  Demande valide !")
            print(f"    Produit   : {spec.product}")
            print(f"    Categorie : {spec.category}")
            print(f"    Quantite  : {spec.quantity} {spec.unit or ''}")
            print(f"    Budget    : {spec.budget_min or 'N/A'} - {spec.budget_max or 'N/A'} TND")
            print(f"    Deadline  : {spec.deadline or 'Non precisee'}")
        else:
            print(f"\n  Demande rejetee : {spec.rejection_reason}")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        label = "valid" if spec.is_valid else "rejected"
        filename = f"analysis_{label}_{ts}.json"
        out_path = os.path.join(OUTPUT_DIR, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            import json as _json
            _json.dump(asdict(spec), f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  Resultat -> {out_path}")

    def poll_once(conn: imaplib.IMAP4_SSL) -> int:
        """Check for UNSEEN emails. Returns number processed."""
        conn.select("INBOX")
        _, msg_nums = conn.search(None, "UNSEEN")
        ids = msg_nums[0].split()
        for num in ids:
            _, data = conn.fetch(num, "(RFC822)")
            raw = data[0][1]
            conn.store(num, "+FLAGS", "\\Seen")
            try:
                process_email(raw)
            except Exception as exc:
                print(f"  Erreur lors du traitement : {exc}")
        return len(ids)

    print("\n  Analysis Agent — mode surveillance active")
    print(f"    Boite    : {settings.gmail_address}")
    print(f"    Intervalle: toutes les {POLL_INTERVAL} secondes")
    print("    Arret    : Ctrl+C\n")

    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    conn.login(settings.gmail_address, _password)
    print("  Connecte a Gmail — surveillance en cours...\n")

    try:
        while True:
            try:
                n = poll_once(conn)
                if n == 0:
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] Aucun nouveau mail — prochain check dans {POLL_INTERVAL}s")
            except imaplib.IMAP4.abort:
                conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
                conn.login(settings.gmail_address, _password)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n\n  Surveillance arretee.")
        conn.logout()
