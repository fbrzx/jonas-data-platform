"""Email sending — invite links via SMTP (Mailpit in dev, real SMTP in prod)."""

import smtplib
from email.mime.text import MIMEText


def send_invite_email(
    to: str,
    invite_link: str,
    role: str,
    invited_by: str,
    tenant_name: str = "Jonas Data Platform",
) -> None:
    """Send an invite email. Raises on failure (caller logs and surfaces error)."""
    from src.config import settings

    if not settings.smtp_enabled:
        print(f"[email] SMTP disabled — invite link for {to}: {invite_link}")
        return

    body = f"""\
You've been invited to join {tenant_name} as a {role}.

Click the link below to set your password and activate your account:

  {invite_link}

This invite link expires in 72 hours.

Invited by: {invited_by}

If you didn't expect this email, you can safely ignore it.
"""
    msg = MIMEText(body, "plain")
    msg["Subject"] = f"You've been invited to {tenant_name}"
    msg["From"] = settings.smtp_from
    msg["To"] = to

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.sendmail(settings.smtp_from, [to], msg.as_string())
    print(f"[email] Invite sent to {to}")
