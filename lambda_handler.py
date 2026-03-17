"""
lambda_handler.py
Entry point for AWS Lambda.

Trigger: S3 Event Notification (SES stores raw email in S3 → S3 triggers Lambda)

Flow:
  1. SES receives email → stores the raw .eml in S3
  2. S3 notification triggers this Lambda
  3. Lambda downloads the .eml, parses it, runs the Analysis Agent
  4. Saves result JSON back to S3 (outputs/ prefix)
  5. Sends an ACK email to the requester via SMTP
"""
import json
import os
import sys
import boto3
import urllib.parse
from datetime import datetime
from dataclasses import asdict
from pathlib import Path

# ── Make project modules importable ───────────────────────────────────────────
# In the Docker image, the project root is /var/task/
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from logger import get_logger
from email_gateway.parser import EmailParser
from agents.analysis.agent import AnalysisAgent, send_request_acknowledgment

logger = get_logger(__name__)

# ── Singletons (reused across warm Lambda invocations) ────────────────────────
_s3_client = boto3.client("s3", region_name=settings.aws_region)
_parser = EmailParser()
_agent = AnalysisAgent()

# Output bucket: reuse the same bucket but store results under outputs/ prefix
OUTPUT_BUCKET = os.environ.get("S3_BUCKET_NAME", "")
OUTPUT_PREFIX = os.environ.get("S3_OUTPUT_PREFIX", "outputs/")


def handler(event, context):
    """
    Main Lambda handler.
    Supports two event formats:
      - S3 event (aws:s3) — when S3 triggers Lambda directly
      - SES event (aws:ses) — when SES triggers Lambda directly (no S3)
    """
    logger.info("Lambda invoked", extra={"event_keys": list(event.keys())})

    records = event.get("Records", [])
    if not records:
        logger.warning("No records in event", extra={"event": event})
        return {"statusCode": 400, "body": "No records found"}

    results = []
    for record in records:
        event_source = record.get("eventSource", record.get("EventSource", ""))

        if event_source == "aws:s3":
            result = _handle_s3_record(record)
        elif event_source == "aws:ses":
            result = _handle_ses_record(record)
        else:
            logger.warning("Unknown event source", extra={"source": event_source})
            result = {"status": "skipped", "reason": f"unknown source: {event_source}"}

        results.append(result)

    return {
        "statusCode": 200,
        "body": json.dumps(results, ensure_ascii=False, default=str),
    }


# ── S3 handler ─────────────────────────────────────────────────────────────────

def _handle_s3_record(record: dict) -> dict:
    """Download raw email from S3, parse and analyze it."""
    bucket = record["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

    logger.info("Downloading email from S3", extra={"bucket": bucket, "key": key})

    try:
        response = _s3_client.get_object(Bucket=bucket, Key=key)
        raw_bytes = response["Body"].read()
    except Exception as exc:
        logger.error("Failed to download from S3", extra={"error": str(exc)})
        return {"status": "error", "reason": str(exc)}

    return _process_email(raw_bytes, source_key=key)


# ── SES direct handler ─────────────────────────────────────────────────────────

def _handle_ses_record(record: dict) -> dict:
    """
    Handle SES direct Lambda invocation.
    Note: SES direct call has a 10KB body limit — suitable only for text-only emails.
    """
    ses_data = record.get("ses", {})
    mail_data = ses_data.get("mail", {})
    message_id = mail_data.get("messageId", "unknown")

    # With SES direct, the raw email is NOT in the event body.
    # We must fetch it from S3 if SES is configured to store a copy there.
    if OUTPUT_BUCKET:
        key = f"emails/{message_id}"
        try:
            response = _s3_client.get_object(Bucket=OUTPUT_BUCKET, Key=key)
            raw_bytes = response["Body"].read()
            return _process_email(raw_bytes, source_key=key)
        except Exception as exc:
            logger.warning(
                "Could not fetch email from S3 for SES record, falling back to headers only",
                extra={"error": str(exc)},
            )

    # Fallback: reconstruct minimal email from SES headers
    from_addr = mail_data.get("source", "unknown@example.com")
    subject = next(
        (
            h["value"]
            for h in mail_data.get("headers", [])
            if h["name"].lower() == "subject"
        ),
        "(no subject)",
    )
    body = f"[Email body unavailable — SES direct mode without S3 copy]\nFrom: {from_addr}\nSubject: {subject}"

    return _process_email(body.encode(), source_key=f"ses/{message_id}")


# ── Core processing ────────────────────────────────────────────────────────────

def _process_email(raw_bytes: bytes, source_key: str = "") -> dict:
    """Parse → Analyze → ACK → Save to S3."""
    try:
        parsed = _parser.parse(raw_bytes)
    except Exception as exc:
        logger.error("Email parse failed", extra={"error": str(exc)})
        return {"status": "parse_error", "reason": str(exc)}

    logger.info(
        "Email parsed",
        extra={"from": parsed.from_email, "subject": parsed.subject},
    )

    try:
        spec = _agent.analyze(parsed.body, parsed.from_email)
    except Exception as exc:
        logger.error("Analysis agent failed", extra={"error": str(exc)})
        return {"status": "analysis_error", "reason": str(exc)}

    # ── Send ACK email ─────────────────────────────────────────────
    try:
        send_request_acknowledgment(
            requester_email=spec.requester_email or parsed.from_email,
            is_valid=spec.is_valid,
            product=spec.product,
        )
        logger.info("ACK sent", extra={"to": spec.requester_email})
    except Exception as exc:
        logger.warning("ACK email failed", extra={"error": str(exc)})

    # ── Save result to S3 ──────────────────────────────────────────
    result_dict = asdict(spec)
    result_dict["source_email_key"] = source_key
    result_dict["processed_at"] = datetime.utcnow().isoformat()

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    label = "valid" if spec.is_valid else "rejected"
    output_key = f"{OUTPUT_PREFIX}analysis_{label}_{ts}.json"

    if OUTPUT_BUCKET:
        try:
            _s3_client.put_object(
                Bucket=OUTPUT_BUCKET,
                Key=output_key,
                Body=json.dumps(result_dict, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
                ContentType="application/json",
            )
            logger.info("Result saved to S3", extra={"key": output_key})
        except Exception as exc:
            logger.warning("Failed to save result to S3", extra={"error": str(exc)})
    else:
        logger.warning("OUTPUT_BUCKET not set — result not persisted")

    return {
        "status": "ok",
        "is_valid": spec.is_valid,
        "product": spec.product,
        "requester": spec.requester_email,
        "output_key": output_key,
    }
