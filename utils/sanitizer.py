"""
utils/sanitizer.py
Input sanitization and LLM output validation utilities.
Protects against prompt injection and hallucinated data.
"""
import re
from typing import Optional


# ── Prompt injection patterns ────────────────────────────────────────────────

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+)?(previous|above|prior)",
    r"you\s+are\s+now\s+a",
    r"act\s+as\s+(if|a|an)",
    r"new\s+instructions?\s*:",
    r"system\s*prompt\s*:",
    r"<\s*/?\s*system\s*>",
    r"```\s*(system|prompt|instruction)",
    r"override\s+(your|the)\s+(instructions|rules|prompt)",
    r"forget\s+(everything|all|your)",
    r"do\s+not\s+follow\s+(your|the)\s+(instructions|rules)",
    r"pretend\s+(you|that)",
    r"jailbreak",
    r"DAN\s+mode",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def detect_injection(text: str) -> Optional[str]:
    """
    Scan text for known prompt injection patterns.
    Returns the matched pattern string if found, None otherwise.
    """
    for pattern in _COMPILED_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def sanitize_email_input(text: str) -> str:
    """
    Sanitize email body before passing to LLM.
    - Strips markdown/code fences that could confuse the LLM
    - Removes excessive whitespace
    - Truncates to a safe length
    """
    # Remove markdown code fences
    text = re.sub(r"```[\s\S]*?```", "[code block removed]", text)

    # Remove HTML tags
    text = re.sub(r"<[^>]{1,200}>", "", text)

    # Collapse excessive newlines
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    # Truncate to 10k chars (more than enough for any procurement email)
    text = text[:10000]

    return text.strip()


# ── LLM output validators ───────────────────────────────────────────────────

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def is_valid_email(email: str) -> bool:
    """Check if a string looks like a valid email address."""
    if not email or not isinstance(email, str):
        return False
    return bool(_EMAIL_REGEX.match(email.strip()))


def validate_price(value, min_val: float = 0, max_val: float = 10_000_000) -> Optional[float]:
    """
    Validate a price value from LLM output.
    Returns the float if valid, None if suspicious.
    """
    if value is None:
        return None
    try:
        price = float(value)
        if price < min_val or price > max_val:
            return None
        return price
    except (ValueError, TypeError):
        return None


def validate_delivery_days(value, max_days: int = 365) -> Optional[int]:
    """
    Validate delivery days from LLM output.
    Returns the int if valid, None if suspicious.
    """
    if value is None:
        return None
    try:
        days = int(value)
        if days < 0 or days > max_days:
            return None
        return days
    except (ValueError, TypeError):
        return None
