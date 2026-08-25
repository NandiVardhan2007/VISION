"""
Email sending and retrieval automation tools.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from vision.tools.registry import tool
from vision.config import config
from vision.logger import logger


@tool(name="send_email", description="Send an email to a recipient address with subject and body.")
def send_email(to_address: str, subject: str, body: str) -> str:
    """Send email via SMTP."""
    if not config.VISION_EMAIL or not config.EMAIL_PASSWORD:
        return "Error: VISION_EMAIL / VISION_EMAIL_PASSWORD not configured (set VISION_EMAIL and VISION_EMAIL_PASSWORD in .env)."

    try:
        msg = MIMEMultipart()
        msg["From"] = config.VISION_EMAIL
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP(config.EMAIL_SMTP_HOST, config.EMAIL_SMTP_PORT, timeout=15)
        server.starttls()
        server.login(config.VISION_EMAIL, config.EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return f"Successfully sent email to {to_address} with subject '{subject}'."
    except Exception as e:
        logger.error(f"[EmailTool] Send failed: {e}")
        return f"Failed to send email: {e}"
