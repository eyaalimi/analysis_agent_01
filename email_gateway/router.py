"""
email_gateway/router.py
Classify incoming EmailEvent as requester request or supplier response,
then forward to the orchestrator entry point.
"""
import re
from email_gateway.poller import EmailEvent, set_email_handler
from logger import get_logger

logger = get_logger(__name__)

# Will be injected at app startup
_orchestrator_handle_request   = None
_orchestrator_handle_response  = None


def register_orchestrator(handle_request, handle_response):
    """
    handle_request(parsed_email)  → called for new procurement requests
    handle_response(parsed_email) → called for supplier offer responses
    """
    global _orchestrator_handle_request, _orchestrator_handle_response
    _orchestrator_handle_request  = handle_request
    _orchestrator_handle_response = handle_response
    set_email_handler(_route_event)
    logger.info("Email router registered with orchestrator")


def _route_event(event: EmailEvent):
    """Route an incoming EmailEvent to the correct orchestrator handler."""
    parsed = event.parsed
    logger.info("Routing email", extra={
        "from": parsed.from_email,
        "subject": parsed.subject,
    })

    if _is_supplier_response(parsed):
        logger.info("Classified as SUPPLIER RESPONSE")
        if _orchestrator_handle_response:
            _orchestrator_handle_response(parsed)
    else:
        logger.info("Classified as PROCUREMENT REQUEST")
        if _orchestrator_handle_request:
            _orchestrator_handle_request(parsed)


def _is_supplier_response(parsed) -> bool:
    """
    Heuristic classification:
    - If the email is a reply (In-Reply-To set) → supplier response
    - If subject starts with Re: / Rép: / Réf: → supplier response
    - Otherwise → new procurement request from a requester
    """
    if parsed.in_reply_to:
        return True
    subject_lower = (parsed.subject or "").lower().strip()
    reply_prefixes = ("re:", "rép:", "réponse:", "ref:", "réf:", "aw:")
    return any(subject_lower.startswith(p) for p in reply_prefixes)
