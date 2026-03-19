"""
agents/analysis/tools.py
Tools and helpers used by the Analysis Agent.
"""
from typing import Optional

from strands import tool


# ── Normalizers ──────────────────────────────────────────────────────────────

def normalize_category(value: Optional[str]) -> str:
    """Normalize category labels to English for consistent JSON outputs."""
    text = (value or "").strip().lower()
    mapping = {
        "materiel informatique": "IT Equipment",
        "matériel informatique": "IT Equipment",
        "fournitures de bureau": "Office Supplies",
        "mobilier": "Furniture",
        "services": "Services",
        "autre": "Other",
    }
    return mapping.get(text, value or "")


def normalize_unit(value: Optional[str]) -> Optional[str]:
    """Normalize common French units to English."""
    if value is None:
        return None
    text = value.strip().lower()
    mapping = {
        "unite": "units",
        "unites": "units",
        "unité": "units",
        "boite": "boxes",
        "boites": "boxes",
        "boîte": "boxes",
        "boîtes": "boxes",
    }
    return mapping.get(text, value)


# ── Strands @tool functions ──────────────────────────────────────────────────

@tool
def suggest_procurement_category(product_or_text: str) -> str:
    """Suggest a broad procurement category from a product or short request text."""
    text = (product_or_text or "").lower()
    if any(k in text for k in ["laptop", "pc", "ordinateur", "imprimante", "printer"]):
        return "IT Equipment"
    if any(k in text for k in ["stylo", "papier", "cahier", "fourniture", "office", "bureau"]):
        return "Office Supplies"
    if any(k in text for k in ["chaise", "table", "bureau meuble", "meuble"]):
        return "Furniture"
    if any(k in text for k in ["maintenance", "support", "service", "consulting", "formation"]):
        return "Services"
    return "Other"


@tool
def validate_budget_range(budget_min: Optional[float], budget_max: Optional[float]) -> str:
    """Validate min/max budget consistency and return guidance."""
    if budget_min is None and budget_max is None:
        return "budget_missing"
    if budget_min is not None and budget_max is not None and budget_min > budget_max:
        return "budget_invalid_min_gt_max"
    return "budget_ok"


@tool
def validate_deadline(deadline: Optional[str]) -> str:
    """Validate that a deadline is a valid future date in YYYY-MM-DD format.
    Returns: deadline_missing | deadline_invalid_format | deadline_in_past | deadline_ok
    """
    if not deadline:
        return "deadline_missing"
    from datetime import date
    try:
        parsed_date = date.fromisoformat(deadline)
    except ValueError:
        return "deadline_invalid_format"
    if parsed_date < date.today():
        return "deadline_in_past"
    return "deadline_ok"


@tool
def send_request_acknowledgment(requester_email: str, is_valid: bool, product: str = "") -> str:
    """Send an automatic acknowledgment email to the requester."""
    from email_gateway.sender import EmailSender

    subject = "We received your procurement request"
    if is_valid:
        body = (
            "Hello,\n\n"
            "We have successfully received your procurement request"
            f" for: {product or 'your requested item'}.\n"
            "Our team is reviewing it and will contact you shortly.\n\n"
            "Regards,\nProcurement AI Team"
        )
    else:
        body = (
            "Hello,\n\n"
            "We have received your message. "
            "It does not seem to contain a complete procurement request yet.\n"
            "Please resend your request with product/service details, quantity, and budget if available.\n\n"
            "Regards,\nProcurement AI Team"
        )

    sender = EmailSender()
    sender.send(to_email=requester_email, subject=subject, body=body)
    return "ack_sent"
