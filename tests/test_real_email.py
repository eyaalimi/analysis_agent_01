"""
tests/test_real_email.py
End-to-end test: reads the latest unseen email from Gmail → Analysis Agent.

Steps:
1. Fill in your .env (GMAIL_ADDRESS + GMAIL_APP_PASSWORD + AWS creds)
2. Send an email to procurement-ai@gmail.com describing a purchase need
3. Run: python tests/test_real_email.py
"""
import sys
import os
import json
import dataclasses
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import imaplib
from email_gateway.parser import EmailParser
from agents.analysis.agent import AnalysisAgent
from config import settings

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_latest_unseen() -> tuple[str, str] | None:
    """
    Connect to Gmail IMAP and return (body, from_email) of the
    most recent UNSEEN message.  Returns None if inbox is empty.
    """
    print(f"\n📬 Connecting to {settings.imap_host} as {settings.gmail_address} ...")
    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    conn.login(settings.gmail_address, settings.gmail_app_password)
    conn.select("INBOX")

    _, msg_nums = conn.search(None, "UNSEEN")
    ids = msg_nums[0].split()

    if not ids:
        print("📭 No unseen emails found.")
        print("   → Send an email to your procurement Gmail account and rerun.\n")
        conn.logout()
        return None

    # Take the most recent one
    latest_id = ids[-1]
    print(f"   Found {len(ids)} unseen email(s). Reading the latest...")

    _, data = conn.fetch(latest_id, "(RFC822)")
    raw = data[0][1]

    # Mark as seen so we don't re-process on the next real poll
    conn.store(latest_id, "+FLAGS", "\\Seen")
    conn.logout()

    parser = EmailParser()
    parsed = parser.parse(raw)

    print(f"\n📧 Email received:")
    print(f"   From    : {parsed.from_email}")
    print(f"   Subject : {parsed.subject}")
    print(f"   Body    :\n{'-'*50}")
    print(parsed.body[:800])
    if len(parsed.body) > 800:
        print("   [... truncated ...]")
    print("-" * 50)

    if parsed.attachments:
        print(f"   Attachments: {[a['filename'] for a in parsed.attachments]}")

    return parsed.body, parsed.from_email


def run():
    result = fetch_latest_unseen()
    if result is None:
        return

    body, from_email = result

    print("\n🤖 Running Analysis Agent (calling Claude Sonnet 4 via Bedrock)...")
    agent = AnalysisAgent()
    spec = agent.analyze(body, from_email)

    print("\n✅ Analysis Result:")
    print(f"   is_valid        : {spec.is_valid}")
    if spec.is_valid:
        print(f"   product         : {spec.product}")
        print(f"   category        : {spec.category}")
        print(f"   quantity        : {spec.quantity} {spec.unit or ''}")
        print(f"   budget          : {spec.budget_min or 'N/A'} \u2013 {spec.budget_max or 'N/A'} TND")
        print(f"   deadline        : {spec.deadline or 'Not specified'}")
        print(f"   requester_email : {spec.requester_email}")

        # ── Save to JSON file ────────────────────────────────────
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(OUTPUT_DIR, f"analysis_result_{timestamp}.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(spec), f, ensure_ascii=False, indent=2, default=str)
        print(f"\n[SAVED] Result saved to: {output_file}")
        print("\n[SUCCESS] The agent successfully extracted the procurement spec from a real email!")
    else:
        print(f"   [REJECTED] Rejected: {spec.rejection_reason}")
        print("   Tip: Make sure the email clearly describes a product/service and quantity.")

        # Save rejection to JSON too
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(OUTPUT_DIR, f"analysis_rejected_{timestamp}.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(spec), f, ensure_ascii=False, indent=2, default=str)
        print(f"\n[SAVED] Rejection details saved to: {output_file}")



if __name__ == "__main__":
    run()
