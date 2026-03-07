"""
email_gateway/poller.py
IMAP inbox poller — checks Gmail every N seconds using APScheduler.
Forwards structured EmailEvent objects to the orchestrator router.
"""
import imaplib
import email
from dataclasses import dataclass
from apscheduler.schedulers.background import BackgroundScheduler

from config import settings
from email_gateway.parser import EmailParser, ParsedEmail
from logger import get_logger

logger = get_logger(__name__)


@dataclass
class EmailEvent:
    """Structured event emitted when a new email arrives."""
    parsed: ParsedEmail
    raw_bytes: bytes


# The router callback is injected at startup (set by email_gateway/router.py)
_on_email_received = None


def set_email_handler(handler):
    """Register the callback that processes each new email."""
    global _on_email_received
    _on_email_received = handler


def _poll_once():
    """Connect to IMAP, fetch unseen emails, emit EmailEvent for each."""
    try:
        conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
        conn.login(settings.gmail_address, settings.gmail_app_password)
        conn.select("INBOX")

        _, msg_nums = conn.search(None, "UNSEEN")
        ids = msg_nums[0].split()
        logger.info("Polling inbox", extra={"unseen_count": len(ids)})

        parser = EmailParser()

        for num in ids:
            _, data = conn.fetch(num, "(RFC822)")
            raw = data[0][1]
            try:
                parsed = parser.parse(raw)
                event = EmailEvent(parsed=parsed, raw_bytes=raw)
                if _on_email_received:
                    _on_email_received(event)
                # Mark as seen
                conn.store(num, "+FLAGS", "\\Seen")
            except Exception as exc:
                logger.error("Failed to process email", extra={"error": str(exc)})

        conn.logout()

    except Exception as exc:
        logger.error("IMAP poll failed", extra={"error": str(exc)})


def start_poller():
    """Start the APScheduler background job."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _poll_once,
        trigger="interval",
        seconds=settings.email_poll_interval_seconds,
        id="imap_poller",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Email poller started", extra={
        "interval_seconds": settings.email_poll_interval_seconds
    })
    return scheduler


def poll_once_now():
    """Manual trigger for testing or Lambda invocation."""
    _poll_once()
