"""
Outbound SMTP for the Step 2 justification-email workflow. Infrastructure
plumbing, not assessment logic — kept out of `engines/`.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger("services.email_service")


class EmailNotConfigured(RuntimeError):
    pass


class EmailSendError(RuntimeError):
    pass


def send_email(to: str, subject: str, body: str) -> None:
    """Sends a plain-text email via the configured SMTP server. Raises
    EmailNotConfigured if SMTP is unset, EmailSendError on any send failure —
    caller is responsible for catching and recording send_status."""
    settings = get_settings()
    if not settings.smtp_configured:
        raise EmailNotConfigured("SMTP is not configured — set SMTP_HOST and SMTP_FROM_ADDRESS.")

    msg = EmailMessage()
    msg["From"] = settings.smtp_from_address
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
    except Exception as e:
        logger.warning("Failed to send justification email to %s: %s", to, e)
        raise EmailSendError(str(e)) from e
