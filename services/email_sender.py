from dataclasses import dataclass
from typing import Optional
import uuid

from config import EMAIL_PROVIDER, DEFAULT_FROM_EMAIL, EMAIL_FROM_DOMAIN, FRONTEND_ORIGIN


@dataclass
class EmailSendResult:
    ok: bool
    provider_message_id: Optional[str] = None
    email_message_id: Optional[str] = None  # RFC Message-ID for reply matching
    error: Optional[str] = None


def _build_from_address(user_email: str | None) -> str:
    """
    Build a safe From address.
    For v1 we either use DEFAULT_FROM_EMAIL or, if a domain is configured,
    map the user into that domain (e.g. user@yourdomain.com).
    """
    if DEFAULT_FROM_EMAIL:
        return DEFAULT_FROM_EMAIL
    if EMAIL_FROM_DOMAIN and user_email:
        local = user_email.split("@", 1)[0]
        return f"{local}@{EMAIL_FROM_DOMAIN}"
    # Fallback to user email if absolutely necessary; safer to require config instead.
    if user_email:
        return user_email
    raise ValueError("No valid From email configured")


def send_email(
    *,
    from_email: str,
    from_name: str | None,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    reply_to_email: str | None = None,
    message_id: str | None = None,
) -> EmailSendResult:
    """
    Provider abstraction. If message_id is provided (RFC Message-ID format),
    it is set on the outgoing email for reply matching. If not provided, one is generated.
    """
    if EMAIL_PROVIDER == "none":
        return EmailSendResult(ok=False, error="Email provider not configured")

    safe_from = _build_from_address(from_email)
    if not message_id or not message_id.strip():
        message_id = f"<{uuid.uuid4().hex}@dealflow>"
    if not message_id.startswith("<"):
        message_id = f"<{message_id}>"

    _ = safe_from, from_name, to_email, subject, text_body, html_body, reply_to_email

    return EmailSendResult(
        ok=True,
        provider_message_id="mock-message-id",
        email_message_id=message_id,
    )


def send_approval_notification(
    *,
    to_user_email: str,
    lead_name: str,
    lead_id: str,
) -> EmailSendResult:
    """Send 'An email to [Lead] is waiting for your approval' to the user."""
    if not to_user_email or "@" not in to_user_email:
        return EmailSendResult(ok=False, error="Invalid user email")
    origin = (FRONTEND_ORIGIN or "").rstrip("/") or "http://localhost:3000"
    approve_url = f"{origin}/dashboard/messages?lead={lead_id}"
    subject = f"DealFlow: Approve email to {lead_name}"
    text_body = (
        f"An email to {lead_name} is waiting for your approval.\n\n"
        f"Log in to approve or edit before it is sent:\n{approve_url}"
    )
    from_addr = DEFAULT_FROM_EMAIL or "noreply@dealflow.app"
    return send_email(
        from_email=from_addr,
        from_name="DealFlow",
        to_email=to_user_email,
        subject=subject,
        text_body=text_body,
        message_id=None,
    )