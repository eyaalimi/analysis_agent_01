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

from config import settings
from logger import get_logger

logger = get_logger(__name__)


class EmailSender:
    """Send emails via Gmail SMTP with TLS."""

    def __init__(self):
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.gmail_address
        self.password = settings.gmail_app_password

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
