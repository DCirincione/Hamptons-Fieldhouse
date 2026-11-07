"""Optional SMTP notifications for website messages."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import Settings

logger = logging.getLogger(__name__)


def send_contact_notification(settings: Settings, *, first_name: str, last_name: str,
                              sender_email: str, phone_number: str, message: str) -> bool:
    password = settings.smtp_password.get_secret_value()
    if not settings.smtp_username or not password or not settings.email_notification_to:
        logger.info("Contact notification email is not configured")
        return False

    email = EmailMessage()
    email["Subject"] = "New Hamptons Fieldhouse website contact message"
    email["From"] = settings.smtp_username
    email["To"] = settings.email_notification_to
    email["Reply-To"] = sender_email
    email.set_content(
        f"A new message was submitted through the Hamptons Fieldhouse website.\n\n"
        f"Name: {first_name} {last_name}\n"
        f"Email: {sender_email}\n"
        f"Phone: {phone_number}\n\n"
        f"Message:\n{message}\n"
    )
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(settings.smtp_username, password)
            server.send_message(email)
        return True
    except (OSError, smtplib.SMTPException):
        logger.exception("Could not send contact notification email")
        return False
