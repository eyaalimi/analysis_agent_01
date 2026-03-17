"""
email_gateway/sender.py
SMTP email sender with TLS + retry logic.
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from tenacity import retry, stop_after_attempt, wait_exponential

import config
from logger import get_logger

logger = get_logger(__name__)


class EmailSender:
    """Send emails via Gmail SMTP with TLS."""

    def __init__(self):
        self.host = config.settings.smtp_host
        self.port = config.settings.smtp_port
        self.username = (config.settings.gmail_address or "").strip()
        # Accept values like "xxxx xxxx xxxx xxxx  # comment" from .env
        # by stripping inline comments and whitespace for SMTP auth.
        raw_password = config.settings.gmail_app_password or ""
        self.password = raw_password.split("#", 1)[0].replace(" ", "").strip()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        attachment_path: str = None,
        in_reply_to: str = None,
        reply_message_id: str = None,
    ) -> str:
        """
        Send an email and return the Message-ID of the sent message.
        Supports optional attachment and threading headers.
        """
        if not self.username:
            raise ValueError("SMTP username is empty. Check GMAIL_ADDRESS in .env")
        if not self.password:
            raise ValueError("SMTP app password is empty. Check GMAIL_APP_PASSWORD in .env")

        msg = MIMEMultipart()
        msg["From"]    = self.username
        msg["To"]      = to_email
        msg["Subject"] = subject

        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"]  = in_reply_to

        msg.attach(MIMEText(body, "plain", "utf-8"))

        if attachment_path:
            self._attach_file(msg, attachment_path)

        with smtplib.SMTP(self.host, self.port) as server:
            server.ehlo()
            server.starttls()
            server.login(self.username, self.password)
            server.sendmail(self.username, [to_email], msg.as_string())

        message_id = msg.get("Message-ID", "")
        logger.info("Email sent", extra={"to": to_email, "subject": subject})
        return message_id

    @staticmethod
    def _attach_file(msg: MIMEMultipart, file_path: str):
        import os
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={filename}")
        msg.attach(part)
