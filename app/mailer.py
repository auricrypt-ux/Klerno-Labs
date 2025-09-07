# app/mailer.py
import os
import sendgrid
from sendgrid.helpers.mail import Mail

SENDGRID_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("SENDGRID_FROM")
FROM_NAME = os.getenv("SENDGRID_NAME", "Klerno Labs")

sg = sendgrid.SendGridAPIClient(SENDGRID_KEY)

def send_email(to_email: str, subject: str, content: str):
    """Send a simple email using SendGrid."""
    message = Mail(
        from_email=(FROM_EMAIL, FROM_NAME),
        to_emails=to_email,
        subject=subject,
        plain_text_content=content,
        html_content=f"<p>{content}</p>",
    )
    response = sg.send(message)
    return response.status_code
